#!/usr/bin/env python3
"""Build the GTIN lookup from the pinned, local OpenPrintTag data archive.

Only data are parsed. Nothing is extracted from the archive or executed, and
no network access is required. Run with the project's virtual environment:

    .venv/bin/python scripts/build_catalogue.py
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from openprinttag_app.qr import DATABASE_COMMIT, normalize_gtin


ARCHIVE = ROOT / "references" / "openprinttag-material-database-2451ae7.tar.gz"
ARCHIVE_SHA256 = "effb295912943c3cc6d5b0341251b7b7352a5da63322285676dc316a54c265ab"
SPEC_DATA = ROOT / "references" / "upstream" / "openprinttag-specification-060e420" / "data"
SPEC_COMMIT = "060e420892d66c062c8af440c97701aab96bac79"
SCHEMA_COMMIT = "954d050b1a83a8cee03ea8ab8d342d6741c61281"
MAX_YAML_BYTES = 1_048_576
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _read_archive(archive: Path) -> tuple[dict[str, list[dict]], str]:
    """Read bounded regular YAML members in the three needed data directories."""
    records: dict[str, list[dict]] = defaultdict(list)
    license_text = ""
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Chemin non sûr dans l’archive de référence.")
            if not member.isfile():
                continue
            if len(path.parts) == 2 and path.name == "LICENSE":
                if member.size > 65536:
                    raise ValueError("Licence de taille inattendue.")
                license_text = tar.extractfile(member).read().decode("utf-8")
                continue
            if len(path.parts) < 4 or path.parts[1] != "data" or path.suffix != ".yaml":
                continue
            category = path.parts[2]
            if category not in {"brands", "materials", "material-packages"}:
                continue
            if member.size > MAX_YAML_BYTES:
                raise ValueError("Fichier YAML de référence de taille inattendue.")
            source = tar.extractfile(member)
            if source is None:
                raise ValueError("Membre YAML illisible.")
            # CSafeLoader, when available, has the same safe constructor policy
            # as safe_load; never select yaml.Loader or unsafe object loaders.
            data = yaml.load(source.read(), Loader=SAFE_LOADER)
            if not isinstance(data, dict):
                raise ValueError(f"Document YAML non objet : {path.name}")
            records[category].append({
                "data": data,
                "path": "/".join(path.parts[1:]),
                "brand_folder": path.parts[3] if len(path.parts) > 4 else None,
            })
    return records, license_text


def _indexes(records: list[dict]) -> tuple[dict, dict]:
    by_slug: dict[str, list[dict]] = defaultdict(list)
    by_uuid: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        data = record["data"]
        if isinstance(data.get("slug"), str):
            by_slug[data["slug"]].append(record)
        if isinstance(data.get("uuid"), str):
            by_uuid[data["uuid"]].append(record)
    return by_slug, by_uuid


def _resolve(ref: object, indexes: tuple[dict, dict], brand_folder: str | None = None) -> dict | None:
    if not isinstance(ref, dict):
        return None
    by_slug, by_uuid = indexes
    candidates = by_slug.get(ref.get("slug"), []) if "slug" in ref else by_uuid.get(ref.get("uuid"), [])
    if len(candidates) > 1 and brand_folder:
        candidates = [record for record in candidates if record["brand_folder"] == brand_folder]
    return candidates[0] if len(candidates) == 1 else None


def _number(value: object, *, positive: bool = False) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def _gtin_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        # The source schema uses a number, so leading zeroes may have been
        # discarded by YAML. All GTIN widths share the same checksum when
        # zero-padded; use a GTIN-14 key without inventing nonzero digits.
        return str(value).zfill(14) if 0 < value < 10**14 else None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value)).zfill(14) if 0 < value < 10**14 else None
    if isinstance(value, str):
        return value
    return None


def _profile(package: dict, material: dict | None, brand: dict | None,
             classes: set[str], material_types: set[str]) -> dict | None:
    data = package["data"]
    gtin_text = _gtin_text(data.get("gtin"))
    if gtin_text is None or normalize_gtin(gtin_text) is None:
        return None
    main: dict = {"gtin": int(gtin_text)}
    material_data = material["data"] if material else {}
    brand_data = brand["data"] if brand else {}
    material_class = data.get("class", material_data.get("class"))
    if material_class in classes:
        main["material_class"] = material_class
    material_type = material_data.get("type")
    if material_type in material_types:
        main["material_type"] = material_type
    # Omit unsuitable values instead of truncating source strings or inventing
    # replacements. The UI can complete any missing field before writing.
    for field, value, byte_limit in [
        ("brand_name", brand_data.get("name"), 31),
        ("material_name", material_data.get("name"), 63),
    ]:
        if isinstance(value, str) and value and len(value.encode("utf-8")) <= byte_limit:
            main[field] = value
    weight = data.get("nominal_netto_full_weight")
    if _number(weight, positive=True):
        main["nominal_netto_full_weight"] = weight
    diameter_um = data.get("filament_diameter")
    if material_class == "FFF" and _number(diameter_um, positive=True):
        # Database schema stores µm; OpenPrintTag main key 30 stores mm.
        main["filament_diameter"] = diameter_um / 1000
    primary = material_data.get("primary_color")
    if isinstance(primary, dict):
        primary = primary.get("color_rgba")
    if isinstance(primary, str) and re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", primary):
        main["primary_color"] = primary.lower()

    label_parts = [brand_data.get("name"), material_data.get("name")]
    label = " ".join(str(part) for part in label_parts if part)
    if not label:
        label = str(data.get("slug", gtin_text))
    if "nominal_netto_full_weight" in main:
        label += f" · {main['nominal_netto_full_weight']:g} g"
    provenance = {
        "repository": "OpenPrintTag/openprinttag-database",
        "commit": DATABASE_COMMIT,
        "package_path": package["path"],
        "source_url": f"https://github.com/OpenPrintTag/openprinttag-database/blob/{DATABASE_COMMIT}/{package['path']}",
    }
    if material:
        provenance["material_path"] = material["path"]
    if brand:
        provenance["brand_path"] = brand["path"]
    return {"label": label, "main": main, "provenance": provenance}


def build_catalogue(archive: Path = ARCHIVE) -> dict:
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive_hash != ARCHIVE_SHA256:
        raise ValueError("L’empreinte de l’archive ne correspond pas au commit épinglé.")
    records, license_text = _read_archive(archive)
    if not license_text:
        raise ValueError("Licence upstream manquante dans l’archive.")
    classes_data = yaml.safe_load((SPEC_DATA / "material_class_enum.yaml").read_text(encoding="utf-8"))
    types_data = yaml.safe_load((SPEC_DATA / "material_type_enum.yaml").read_text(encoding="utf-8"))
    classes = {item["name"] for item in classes_data}
    material_types = {item["abbreviation"] for item in types_data}
    material_indexes = _indexes(records["materials"])
    brand_indexes = _indexes(records["brands"])
    items: dict[str, list[dict]] = defaultdict(list)
    valid_count = 0
    invalid_count = 0
    for package in records["material-packages"]:
        material = _resolve(package["data"].get("material"), material_indexes, package["brand_folder"])
        brand = _resolve(material["data"].get("brand"), brand_indexes) if material else None
        profile = _profile(package, material, brand, classes, material_types)
        if profile is None:
            invalid_count += 1
            continue
        valid_count += 1
        key = normalize_gtin(_gtin_text(package["data"]["gtin"]))
        items[key].append(profile)
    for matches in items.values():
        matches.sort(key=lambda entry: (entry["label"], entry["provenance"]["package_path"]))
        labels = [entry["label"] for entry in matches]
        for entry in matches:
            if labels.count(entry["label"]) > 1:
                package_slug = PurePosixPath(entry["provenance"]["package_path"]).stem
                entry["label"] += f" · {package_slug}"
    return {
        "format_version": 1,
        "source": {
            "repository": "OpenPrintTag/openprinttag-database",
            "commit": DATABASE_COMMIT,
            "specification_commit": SPEC_COMMIT,
            "schema_commit": SCHEMA_COMMIT,
            "archive_sha256": archive_hash,
            "license": "MIT",
            "license_text": license_text,
            "mapping": "Explicit package/material/brand joins; filament diameter µm → mm; no inferred defaults or instance data.",
        },
        "stats": {
            "packages_seen": len(records["material-packages"]),
            "packages_with_valid_gtin": valid_count,
            "packages_without_valid_gtin": invalid_count,
            "gtin_count": len(items),
            "ambiguous_gtin_count": sum(len(matches) > 1 for matches in items.values()),
        },
        "items": dict(sorted(items.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "resources" / "catalogue.json")
    args = parser.parse_args()
    catalogue = build_catalogue()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalogue, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(catalogue["stats"], ensure_ascii=False))
    print(f"Catalogue écrit : {args.output}")


if __name__ == "__main__":
    main()
