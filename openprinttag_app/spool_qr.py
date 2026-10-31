"""Self-contained, lossless OPT Station labels (not a manufacturer QR format).

OPT1 = bounded zlib-compressed canonical CBOR, base32, SHA-256/64 checksum.
The checksum detects damage; a label is user data, not an authenticated source.
The physical NFC UID and memory layout belong to the eventual tag, not the QR.
"""
import base64
from datetime import datetime, timezone
import hashlib
import re
import zlib

import cbor2

from .domain import DomainError, SPEC_COMMIT, spool_snapshot, _wire_map, _json_map, _encode_map

PREFIX = "OPT1:"
MAX_TEXT = 8192
MAX_DATA = 32768


def _bounded_cbor(data):
    """Check declared sizes/depth before handing untrusted CBOR to its decoder."""
    budget = 4096
    def visit(offset, depth):
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 8 or offset >= len(data):
            raise ValueError()
        head = data[offset]
        offset += 1
        major, extra = head >> 5, head & 31
        if major == 7:
            width = {20: 0, 21: 0, 22: 0, 25: 2, 26: 4, 27: 8}.get(extra)
            if width is None or offset + width > len(data):
                raise ValueError()
            return offset + width
        if major == 6 or extra > 27:
            raise ValueError()
        if extra < 24:
            size = extra
        else:
            width = 1 << (extra - 24)
            if offset + width > len(data):
                raise ValueError()
            size = int.from_bytes(data[offset:offset + width], "big")
            offset += width
        if major in {2, 3}:
            if size > MAX_DATA or offset + size > len(data):
                raise ValueError()
            offset += size
        elif major in {4, 5}:
            if size > 1024:
                raise ValueError()
            for _ in range(size * (2 if major == 5 else 1)):
                offset = visit(offset, depth + 1)
        return offset
    if visit(0, 0) != len(data):
        raise ValueError()


def stock_date(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if not parsed.tzinfo:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        raise DomainError("La date d’entrée en stock doit inclure un fuseau horaire.") from None


def encode_spool(item):
    if any(item.get("unknown_fields", {}).get(region) for region in ("main", "aux")):
        raise DomainError("Ce tag contient des champs inconnus : un QR complet ne peut pas être produit sans les perdre.")
    record = spool_snapshot(item["main"], item.get("aux", {}))
    if not item["main"].get("instance_uuid"):
        # Legacy NFC tags can derive identity from their UID. Freeze it explicitly
        # on the label, so it remains the same on a different physical tag.
        record["main"]["instance_uuid"] = item["instance_uuid"]
        record = spool_snapshot(record["main"], record["aux"])
    main_wire, aux_wire = _wire_map("main", record["main"]), _wire_map("aux", record["aux"])
    _encode_map(main_wire)
    _encode_map(aux_wire, indefinite=True)
    payload = cbor2.dumps({0: 1, 1: main_wire, 2: aux_wire,
                           3: stock_date(item.get("added_at")), 4: bytes.fromhex(SPEC_COMMIT)}, canonical=True)
    if len(payload) > MAX_DATA:
        raise DomainError("Les données complètes dépassent la taille de QR prise en charge.")
    # Upper-case base32 selects QR alphanumeric mode, giving larger physical
    # modules than byte-mode base64 at the same error correction level.
    text = PREFIX + base64.b32encode(zlib.compress(payload, 9)).decode().rstrip("=")
    text += "." + hashlib.sha256(payload).hexdigest()[:16].upper()
    if len(text) > MAX_TEXT:
        raise DomainError("Les données complètes dépassent la taille de QR prise en charge.")
    return text


def decode_spool(text):
    try:
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError()
        match = re.fullmatch(r"OPT1:([A-Z2-7]+)\.([0-9A-F]{16})", text)
        if not match:
            raise ValueError()
        encoded, checksum = match.groups()
        compressed = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
        inflater = zlib.decompressobj()
        payload = inflater.decompress(compressed, MAX_DATA + 1)
        if len(payload) > MAX_DATA or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
            raise ValueError()
        if hashlib.sha256(payload).hexdigest()[:16].upper() != checksum:
            raise ValueError()
        _bounded_cbor(payload)
        data = cbor2.loads(payload)
        if not isinstance(data, dict) or any(type(key) is not int for key in data) or set(data) != {0, 1, 2, 3, 4}:
            raise ValueError()
        if type(data[0]) is not int or data[0] != 1 or data[4] != bytes.fromhex(SPEC_COMMIT):
            raise ValueError()
        # Reject duplicate keys, trailing data, tags and non-canonical encodings.
        if cbor2.dumps(data, canonical=True) != payload:
            raise ValueError()
        if not isinstance(data[1], dict) or not isinstance(data[2], dict) or 0 not in data[1]:
            raise ValueError()
        if any(type(key) is not int for region in (1, 2) for key in data[region]):
            raise ValueError()
        record = spool_snapshot(_json_map("main", data[1]), _json_map("aux", data[2]))
        if _wire_map("main", record["main"]) != data[1] or _wire_map("aux", record["aux"]) != data[2]:
            raise ValueError()
        record["added_at"] = stock_date(data[3])
        return record
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, zlib.error, cbor2.CBORDecodeError):
        raise DomainError("QR OPT Station invalide, endommagé ou de version non prise en charge. Aucune donnée n’a été appliquée.") from None
