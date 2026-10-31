from copy import deepcopy
import io
import socket
import tarfile
import urllib.request

import pytest

from openprinttag_app import qr
from scripts.build_catalogue import _profile, _read_archive


PRUSA_GTIN = "8594173675292"


@pytest.mark.parametrize("value", ["96385074", "036000291452", PRUSA_GTIN, "08594173675292"])
def test_gtin_checksum_supports_four_lengths(value):
    assert qr.normalize_gtin(value) == value.zfill(14)


@pytest.mark.parametrize("value", ["8594173675293", "123", "١٢٣٤٥٦٧٨", "8594173675292.0", " 96385074", "9638507a", "00000000"])
def test_invalid_gtin_is_not_recognized(value):
    assert qr.normalize_gtin(value) is None


def test_catalogue_match_has_correct_units_and_provenance():
    result = qr.inspect_qr(PRUSA_GTIN)
    assert result["kind"] == "gtin"
    # The pinned database contains both old-spool and current-spool packages
    # under this GTIN. This is real ambiguity and must not select a package.
    assert len(result["matches"]) == 2
    assert result["main"] == {"gtin": int(PRUSA_GTIN)}
    match = next(entry for entry in result["matches"] if entry["provenance"]["package_path"].endswith("prusament-pla-prusa-orange-1000-spool.yaml"))
    assert match["main"]["brand_name"] == "Prusament"
    assert match["main"]["material_name"] == "PLA Prusa Orange"
    assert match["main"]["material_class"] == "FFF"
    assert match["main"]["material_type"] == "PLA"
    assert match["main"]["filament_diameter"] == 1.75
    assert match["main"]["nominal_netto_full_weight"] == 1000
    provenance = match["provenance"]
    assert provenance["commit"] == qr.DATABASE_COMMIT
    assert provenance["package_path"].endswith("prusament-pla-prusa-orange-1000-spool.yaml")
    assert "instance_uuid" not in match["main"]
    assert "actual_netto_full_weight" not in match["main"]
    assert "consumed_weight" not in match["main"]


def test_unique_catalogue_match_prefills_product_values():
    result = qr.inspect_qr("8594173672666")
    assert len(result["matches"]) == 1
    assert result["main"]["material_name"] == "PLA CMYK Cyan"
    assert result["main"] == result["matches"][0]["main"]


def test_catalogue_profiles_conform_to_pinned_openprinttag_fields():
    from openprinttag_app.domain import validate_fields
    catalogue = qr._load_catalogue()
    assert catalogue["source"]["license"] == "MIT"
    assert "Permission is hereby granted" in catalogue["source"]["license_text"]
    for matches in catalogue["items"].values():
        for match in matches:
            validate_fields("main", match["main"], partial=True)


def test_leading_zero_and_raw_scanner_text_are_preserved():
    raw = " 08594173675292\r\n"
    result = qr.inspect_qr(raw)
    assert result["raw"] == raw
    assert result["matches"] == qr.inspect_qr(PRUSA_GTIN)["matches"]
    assert result["main"]["gtin"] == int(PRUSA_GTIN)


def test_unknown_and_url_do_not_fetch_or_invent_fields(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("QR inspection must not open a network connection")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    for value, expected in [
        ("https://example.com/spool?gtin=" + PRUSA_GTIN, "url"),
        ("<script>alert('x')</script>", "unknown"),
        ("8594173675293", "unknown"),
        ("", "unknown"),
    ]:
        result = qr.inspect_qr(value)
        assert result["kind"] == expected
        assert result["raw"] == value
        assert result["main"] == {}
        assert result["matches"] == []


def test_multiple_catalogue_matches_require_explicit_choice(monkeypatch):
    entry = deepcopy(qr.inspect_qr(PRUSA_GTIN)["matches"][0])
    alternative = deepcopy(entry)
    alternative["main"]["nominal_netto_full_weight"] = 500
    monkeypatch.setattr(qr, "_load_catalogue", lambda: {"items": {PRUSA_GTIN.zfill(14): [entry, alternative]}})
    result = qr.inspect_qr(PRUSA_GTIN)
    assert len(result["matches"]) == 2
    assert result["main"] == {"gtin": int(PRUSA_GTIN)}


def test_unavailable_catalogue_keeps_gtin_only(monkeypatch):
    def unavailable():
        raise OSError("missing")
    monkeypatch.setattr(qr, "_load_catalogue", unavailable)
    result = qr.inspect_qr(PRUSA_GTIN)
    assert result["kind"] == "gtin"
    assert result["main"] == {"gtin": int(PRUSA_GTIN)}
    assert result["matches"] == []


def test_qr_input_bounds():
    with pytest.raises(ValueError):
        qr.inspect_qr(None)
    with pytest.raises(ValueError):
        qr.inspect_qr("x" * (qr.MAX_QR_TEXT_LENGTH + 1))


def test_profile_omits_absent_values_and_measured_instance_data():
    package = {"data": {"gtin": int(PRUSA_GTIN), "class": "FFF", "nominal_netto_full_weight": 1000,
                        "filament_diameter": 1750, "actual_netto_full_weight": 1012,
                        "instance_uuid": "not-a-product-field"}, "path": "data/material-packages/example.yaml"}
    profile = _profile(package, None, None, {"FFF", "SLA"}, {"PLA"})
    assert profile["main"] == {"gtin": int(PRUSA_GTIN), "material_class": "FFF",
                               "nominal_netto_full_weight": 1000, "filament_diameter": 1.75}


def test_archive_paths_are_never_extracted_and_traversal_is_rejected(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("../escape.yaml")
        data = b"slug: wrong\n"
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="Chemin non sûr"):
        _read_archive(archive)
    assert not (tmp_path.parent / "escape.yaml").exists()
