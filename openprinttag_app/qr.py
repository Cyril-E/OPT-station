"""Inspect QR/scanner text without following URLs or guessing vendor formats.

The local catalogue is a reproducible subset of the pinned official database.
Camera capture belongs to the acquisition adapter; this module accepts its text.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .spool_qr import decode_spool
from .prusa_product import product_url


CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "resources" / "catalogue.json"
DATABASE_COMMIT = "2451ae7adc115cfc40cf1892bddbb0b4a2f1b1a3"
MAX_QR_TEXT_LENGTH = 8192


def normalize_gtin(value: str) -> str | None:
    """Return a validated, zero-padded GTIN-14 key; retain raw text elsewhere.

    OpenPrintTag stores GTIN as an integer. Padding here is only for catalogue
    lookup, so UPC/EAN representations with leading zeroes find the same product.
    """
    if (not isinstance(value, str) or not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12,14})", value)
            or set(value) == {"0"}):
        return None
    # GTIN-13 uses 1/3 alternating weights from the left. Counting from the
    # rightmost data digit works for all four supported GTIN lengths.
    weighted = sum(int(digit) * (3 if index % 2 == 0 else 1)
                   for index, digit in enumerate(reversed(value[:-1])))
    if (10 - weighted % 10) % 10 != int(value[-1]):
        return None
    return value.zfill(14)


@lru_cache(maxsize=1)
def _load_catalogue() -> dict:
    with CATALOGUE_PATH.open(encoding="utf-8") as stream:
        catalogue = json.load(stream)
    if catalogue.get("format_version") != 1 or not isinstance(catalogue.get("items"), dict):
        raise ValueError("Format du catalogue local non pris en charge.")
    if catalogue.get("source", {}).get("commit") != DATABASE_COMMIT:
        raise ValueError("La version du catalogue local ne correspond pas à la référence.")
    return catalogue


def inspect_qr(text: str) -> dict:
    """Classify text and propose only data supported by a checked local GTIN.

    No URL is requested. In particular, an URL printed on a spool is not treated
    as an OpenPrintTag payload, a GTIN, or a brand-specific ID by assumption.
    """
    if not isinstance(text, str):
        raise ValueError("Le contenu du QR doit être du texte.")
    if len(text) > MAX_QR_TEXT_LENGTH:
        raise ValueError("Le contenu du QR dépasse 8 192 caractères.")
    value = text.strip()
    result = {"kind": "unknown", "raw": text, "main": {}, "matches": []}
    if not value:
        result["message"] = "Aucun contenu reçu. Scannez un QR ou saisissez son texte."
        return result

    if value.startswith("OPT") and ":" in value[:12]:
        item = decode_spool(value)
        result.update(kind="opt_station", main=item["main"], aux=item["aux"],
                      instance_uuid=item["instance_uuid"], added_at=item["added_at"],
                      message="QR OPT Station complet : données RFID et identité de bobine retrouvées. Vérifiez la fiche avant écriture.")
        return result

    gtin_key = normalize_gtin(value)
    if gtin_key is not None:
        result.update(kind="gtin", main={"gtin": int(value)})
        try:
            catalogue = _load_catalogue()
        except (OSError, ValueError, json.JSONDecodeError):
            result["message"] = (
                "GTIN valide, mais catalogue local indisponible. "
                "Complétez et vérifiez les informations manuellement."
            )
            return result
        matches = deepcopy(catalogue["items"].get(gtin_key, []))
        result["matches"] = matches
        if len(matches) == 1:
            result["main"] = deepcopy(matches[0]["main"])
            result["message"] = (
                "Référence retrouvée dans la base officielle locale. "
                "Vérifiez les valeurs avant de préparer le tag."
            )
        elif matches:
            result["message"] = (
                "Plusieurs références partagent ce GTIN. "
                "Choisissez la fiche correspondant à la bobine; aucune n’est appliquée automatiquement."
            )
        else:
            result["message"] = (
                "GTIN valide, sans référence dans la base locale. "
                "Le GTIN seul ne décrit pas le matériau : complétez les informations."
            )
        return result

    try:
        url = urlsplit(value)
        is_web_url = (url.scheme.lower() in {"http", "https"} and bool(url.hostname)) or product_url(value) is not None
    except ValueError:
        is_web_url = False
    if is_web_url:
        result.update(
            kind="url",
            message=(
                "Ce QR contient une adresse web. Elle n’est pas ouverte automatiquement "
                "et aucun mapping matière n’est défini pour cette adresse. "
                "Utilisez une fiche favorite ou complétez les informations manuellement."
            ),
        )
    else:
        result["message"] = (
            "Format non reconnu. Le texte brut est conservé; "
            "aucune donnée matériau n’est déduite sans règle documentée."
        )
    return result
