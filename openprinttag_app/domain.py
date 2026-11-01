"""OpenPrintTag data codec, independent from any physical reader.

Field definitions and wire format follow the locally frozen official specification
060e420892d66c062c8af440c97701aab96bac79. The upstream sources are read as data;
none of their Python utilities are imported or executed by this module.

This first implementation supports the E1 / four-byte Capability Container used
by the official examples. A newly created 320-byte image is a simulation profile,
not a claim about the usable memory of a physical tag.
"""

from __future__ import annotations

import copy
import hashlib
import io
import math
import re
import struct
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import cbor2
import yaml


class DomainError(ValueError):
    """Invalid user data, unsupported image or invalid OpenPrintTag structure."""


SPEC_COMMIT = "060e420892d66c062c8af440c97701aab96bac79"
SPEC_ROOT = Path(__file__).resolve().parents[1] / "references" / "upstream" / "openprinttag-specification-060e420"
MIME_TYPE = b"application/vnd.openprinttag"
INSTANCE_NAMESPACE = uuid.UUID("31062f81-b5bd-4f86-a5f8-46367e841508")
_FAVORITE_FORBIDDEN = {
    "instance_uuid", "brand_specific_instance_id", "actual_netto_full_weight",
    "actual_full_length", "manufactured_date", "expiration_date", "write_protection",
}
_MASS_NAMES = {
    "nominal_netto_full_weight", "actual_netto_full_weight", "empty_container_weight", "consumed_weight",
}


@lru_cache(maxsize=1)
def _definitions() -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for region in ("main", "aux"):
        path = SPEC_ROOT / "data" / f"{region}_fields.yaml"
        with path.open(encoding="utf-8") as stream:
            rows = yaml.safe_load(stream)
        result[region] = {}
        for source in rows:
            if source.get("deprecated") or "name" not in source:
                continue
            field = copy.deepcopy(source)
            options = []
            if field.get("items_file"):
                with (path.parent / field["items_file"]).open(encoding="utf-8") as stream:
                    enum_rows = yaml.safe_load(stream)
                for item in enum_rows:
                    if item.get("deprecated") or "name" not in item:
                        continue
                    token = item.get("abbreviation", item["name"])
                    options.append({"value": token, "label": token, "key": item["key"], "name": item["name"]})
            field["options"] = options
            result[region][field["name"]] = field
    return result


def get_schema() -> dict[str, Any]:
    """Return JSON-friendly official field definitions for the editor."""
    public: dict[str, Any] = {"spec_commit": SPEC_COMMIT}
    for region, fields in _definitions().items():
        public[region] = []
        for field in fields.values():
            public[region].append({
                "key": field["key"], "name": field["name"], "type": field["type"],
                "unit": field.get("unit"), "required": field.get("required", False),
                "max_length": field.get("max_length"), "category": field.get("category"),
                "description": copy.deepcopy(field.get("description", [])),
                "options": [{"value": item["value"], "label": item["label"]} for item in field["options"]],
            })
    return public


def normalize_uid(uid: str) -> str:
    """Canonical NFC-V UID: eight bytes, E0 first (not silently reversed)."""
    if not isinstance(uid, str):
        raise DomainError("L’UID du tag doit être une chaîne hexadécimale.")
    normalized = uid.replace(":", "").replace(" ", "").upper()
    if not re.fullmatch(r"E0[0-9A-F]{14}", normalized):
        raise DomainError("UID NFC-V attendu : 8 octets avec E0 en premier, dans l’ordre canonique.")
    return normalized


def _derive_instance_uuid(uid: str) -> str:
    digest = hashlib.sha1(INSTANCE_NAMESPACE.bytes + bytes.fromhex(normalize_uid(uid))).digest()
    return str(uuid.UUID(bytes=digest[:16], version=5))


def _number(value: Any, name: str, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainError(f"{name} doit être un nombre{' entier' if integer else ''}.")
    if isinstance(value, int) and not -(2**64) <= value < 2**64:
        raise DomainError(f"{name} dépasse la plage entière CBOR prise en charge.")
    if not math.isfinite(value):
        raise DomainError(f"{name} doit être un nombre fini.")
    if integer and not isinstance(value, int):
        raise DomainError(f"{name} doit être un entier.")
    return value


def _enum(value: Any, field: dict[str, Any]) -> str | int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise DomainError(f"{field['name']} doit être une valeur d’énumération.")
    for item in field["options"]:
        if value == item["value"] or value == item["name"] or value == item["key"]:
            return item["value"]
    if isinstance(value, int) and 0 <= value <= 65535:
        return value
    raise DomainError(f"Valeur inconnue pour {field['name']} : choisir une valeur officielle ou un entier de 0 à 65535.")


def _normalize_value(value: Any, field: dict[str, Any]) -> Any:
    name, kind = field["name"], field["type"]
    if kind in {"int", "timestamp"}:
        value = _number(value, name, integer=True)
        if kind == "timestamp" and value < 0:
            raise DomainError(f"{name} doit être une date Unix positive.")
    elif kind == "number":
        value = _number(value, name)
    elif kind == "string":
        if not isinstance(value, str):
            raise DomainError(f"{name} doit être un texte.")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise DomainError(f"{name} n’est pas un texte UTF-8 valide.") from exc
        if field.get("max_length") is not None and len(encoded) > field["max_length"]:
            raise DomainError(f"{name} dépasse {field['max_length']} octets UTF-8.")
    elif kind == "uuid":
        try:
            if not isinstance(value, str):
                raise ValueError()
            value = str(uuid.UUID(value))
        except (ValueError, AttributeError) as exc:
            raise DomainError(f"{name} doit être un UUID valide.") from exc
    elif kind == "bytes":
        if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", value):
            raise DomainError(f"{name} doit être une chaîne hexadécimale de longueur paire.")
        if field.get("max_length") is not None and len(value) // 2 > field["max_length"]:
            raise DomainError(f"{name} dépasse {field['max_length']} octets.")
        value = value.lower()
    elif kind == "color_rgba":
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
            raise DomainError(f"{name} doit être une couleur #RRGGBB ou #RRGGBBAA.")
        value = value.lower()
    elif kind == "color_lab":
        if not isinstance(value, list) or len(value) != 3:
            raise DomainError(f"{name} doit contenir trois nombres Lab.")
        value = [_number(item, name) for item in value]
    elif kind == "enum":
        value = _enum(value, field)
    elif kind == "enum_array":
        if not isinstance(value, list):
            raise DomainError(f"{name} doit être une liste de valeurs.")
        if field.get("max_length") is not None and len(value) > field["max_length"]:
            raise DomainError(f"{name} accepte au plus {field['max_length']} valeurs.")
        value = [_enum(item, field) for item in value]
    else:
        raise DomainError(f"Type de champ non pris en charge : {kind}.")
    return value


def validate_fields(region: str, fields: dict[str, Any], partial: bool = True) -> dict[str, Any]:
    """Validate editor values; a partial null explicitly removes an optional field."""
    if region not in _definitions() or not isinstance(fields, dict):
        raise DomainError("Une région main ou aux et un objet de champs sont attendus.")
    result = {}
    for name, value in fields.items():
        if not isinstance(name, str) or name not in _definitions()[region]:
            raise DomainError(f"Champ OpenPrintTag inconnu dans {region} : {name}.")
        field = _definitions()[region][name]
        if value is None:
            if field.get("required") is True:
                raise DomainError(f"Le champ obligatoire {name} ne peut pas être supprimé.")
            if partial:
                result[name] = None
            continue
        value = _normalize_value(value, field)
        if name in _MASS_NAMES and value < 0:
            raise DomainError(f"{name} ne peut pas être négatif.")
        if name in {"nominal_netto_full_weight", "actual_netto_full_weight", "density", "filament_diameter"} and value <= 0:
            raise DomainError(f"{name} doit être strictement positif.")
        if name == "gtin" and value < 0:
            raise DomainError("Le GTIN doit être positif.")
        result[name] = value
    if not partial:
        for field in _definitions()[region].values():
            if field.get("required") is True and field["name"] not in result:
                raise DomainError(f"Champ obligatoire manquant : {field['name']}.")
    return result


def validate_favorite_main(fields: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(fields, dict):
        raise DomainError("Les données du favori doivent être un objet.")
    forbidden = set(fields) & _FAVORITE_FORBIDDEN
    if forbidden:
        raise DomainError("Un favori ne peut pas copier les données propres à une bobine : " + ", ".join(sorted(forbidden)))
    return {key: value for key, value in validate_fields("main", fields).items() if value is not None}


def reusable_profile(main: dict[str, Any], aux: dict[str, Any]) -> dict[str, Any]:
    """Project a decoded spool onto reusable material/package fields only."""
    definitions = _definitions()["main"]
    reusable = {key: value for key, value in main.items()
                if key in definitions and key not in _FAVORITE_FORBIDDEN and not definitions[key].get("deprecated")
                and value is not None}
    reusable = validate_favorite_main(reusable)
    if not reusable:
        raise DomainError("Cette source ne contient aucune donnée réutilisable pour un modèle.")
    return {"main": reusable,
            "suggested_name": (reusable.get("material_name") or " ".join(str(reusable.get(k) or "") for k in ("brand_name", "material_type")).strip())[:100],
            "excluded_fields": [f"main.{key}" for key in main if key not in reusable]
                               + [f"aux.{key}" for key in aux]}


def spool_snapshot(main: dict[str, Any], aux: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete spool record without inventing a physical tag UID."""
    main = validate_fields("main", main, partial=False)
    aux = validate_fields("aux", aux, partial=False)
    main.setdefault("instance_uuid", str(uuid.uuid4()))
    _check_mass_total(main, aux)
    initial = main.get("actual_netto_full_weight", main.get("nominal_netto_full_weight"))
    consumed = aux.get("consumed_weight")
    return {"uid": None, "instance_uuid": main["instance_uuid"], "main": main, "aux": aux,
            "remaining_weight": initial - consumed if initial is not None and consumed is not None else None,
            "remaining_estimated": initial is not None and "actual_netto_full_weight" not in main,
            "unknown_fields": {"main": [], "aux": []}, "warnings": []}


def _to_wire(value: Any, field: dict[str, Any]) -> Any:
    kind = field["type"]
    if kind == "uuid":
        return uuid.UUID(value).bytes
    if kind == "bytes":
        return bytes.fromhex(value)
    if kind == "color_rgba":
        return bytes.fromhex(value[1:])
    if kind == "enum":
        for item in field["options"]:
            if item["value"] == value:
                return item["key"]
    if kind == "enum_array":
        return [_to_wire(item, {**field, "type": "enum"}) for item in value]
    return value


def _from_wire(value: Any, field: dict[str, Any]) -> Any:
    kind, name = field["type"], field["name"]
    if kind in {"bytes", "uuid", "color_rgba"}:
        if not isinstance(value, bytes):
            raise DomainError(f"Le champ {name} doit être une chaîne d’octets CBOR.")
        if kind == "uuid":
            if len(value) != 16:
                raise DomainError(f"Le champ UUID {name} ne fait pas 16 octets.")
            return str(uuid.UUID(bytes=value))
        if kind == "color_rgba":
            return _normalize_value("#" + value.hex(), field)
        return _normalize_value(value.hex(), field)
    return _normalize_value(value, field)


def _wire_map(region: str, values: dict[str, Any]) -> dict[int, Any]:
    return {_definitions()[region][name]["key"]: _to_wire(value, _definitions()[region][name]) for name, value in values.items()}


def _json_map(region: str, values: dict[int, Any]) -> dict[str, Any]:
    known = {field["key"]: field for field in _definitions()[region].values()}
    return {known[key]["name"]: _from_wire(value, known[key]) for key, value in values.items() if key in known}


class _RFIDFloat:
    """An explicitly single-precision CBOR number, not a CBOR extension tag."""

    def __init__(self, raw: bytes):
        self.raw = raw


def _rfid_number(value: int | float) -> int | _RFIDFloat:
    # JSON often represents whole masses as floats. Integer encoding preserves
    # their exact values and avoids depending on half-float decoding in readers.
    if isinstance(value, int):
        return value
    if value.is_integer() and -(2**64) <= value < 2**64:
        return int(value)
    try:
        raw = struct.pack(">f", value)
    except (OverflowError, struct.error) as exc:
        raise DomainError("La valeur numérique dépasse la plage prise en charge par le RFID.") from exc
    encoded_value = struct.unpack(">f", raw)[0]
    if not math.isfinite(encoded_value) or (value != 0 and encoded_value == 0):
        raise DomainError("La valeur numérique dépasse la plage prise en charge par le RFID.")
    return _RFIDFloat(raw)


def _number_types(region: str, names=None) -> dict[int, str]:
    return {field["key"]: field["type"] for name, field in _definitions()[region].items()
            if (names is None or name in names) and field["type"] in {"number", "color_lab"}}


def _encode_rfid_float(encoder, value):
    if not isinstance(value, _RFIDFloat):
        raise cbor2.CBOREncodeError("Unsupported CBOR value")
    encoder.write(b"\xfa" + value.raw)


def _encode_map(values: dict[int, Any], indefinite: bool = False,
                number_types: dict[int, str] | None = None) -> bytes:
    # Limit conversion to known numeric fields being written. Existing fields
    # outside a patch and opaque/unknown values retain the previous encoding path.
    values = dict(values)
    for key, kind in (number_types or {}).items():
        if key in values:
            values[key] = ([_rfid_number(item) for item in values[key]] if kind == "color_lab"
                           else _rfid_number(values[key]))
    try:
        if not indefinite:
            encoded = cbor2.dumps(values, canonical=True, default=_encode_rfid_float)
        else:
            # Aux roots are recommended as indefinite-length maps by the specification.
            encoded = b"\xbf" + b"".join(cbor2.dumps(key, canonical=True) + cbor2.dumps(
                values[key], canonical=True, default=_encode_rfid_float) for key in sorted(values)) + b"\xff"
    except (cbor2.CBOREncodeError, ValueError, RecursionError) as exc:
        raise DomainError("Les valeurs de la région ne peuvent pas être réencodées en CBOR sans perte.") from exc
    # Section CBOR size is bounded independently of the allocated region size.
    if len(encoded) > 512:
        raise DomainError("La section CBOR encodée dépasse 512 octets.")
    return encoded


def _read_map(data: bytes, label: str) -> tuple[dict[int, Any], int]:
    stream = io.BytesIO(data)
    try:
        values = cbor2.load(stream)
    except (ValueError, EOFError, cbor2.CBORError) as exc:
        raise DomainError(f"Section CBOR {label} illisible ou tronquée.") from exc
    if not isinstance(values, dict) or any(isinstance(key, bool) or not isinstance(key, int) for key in values):
        raise DomainError(f"La section {label} doit être une carte CBOR à clés entières.")
    if stream.tell() > 512:
        raise DomainError(f"La section {label} dépasse 512 octets.")
    return values, stream.tell()


def _check_mass_total(main: dict[str, Any], aux: dict[str, Any]) -> None:
    initial = main.get("actual_netto_full_weight", main.get("nominal_netto_full_weight"))
    consumed = aux.get("consumed_weight")
    if initial is not None and consumed is not None and consumed > initial:
        raise DomainError("La quantité consommée dépasse le poids net initial de matière.")


def _find_payload(image: bytes) -> tuple[int, int]:
    if not 6 <= len(image) <= 2040 or image[0] != 0xE1:
        raise DomainError("Profil NFC-V non pris en charge : un CC E1 de 4 octets est attendu.")
    if image[1] >> 4 != 4:
        raise DomainError("Version du conteneur NFC-V non prise en charge.")
    memory_limit = image[2] * 8
    if memory_limit < 8 or memory_limit > len(image):
        raise DomainError("L’image du tag est plus courte que la capacité déclarée par son CC.")
    cursor = 4
    message_start = message_end = None
    while cursor < memory_limit:
        kind = image[cursor]
        cursor += 1
        if kind == 0x00:  # NULL TLV is one byte, not a length-bearing record.
            continue
        if kind == 0xFE:
            break
        if cursor >= memory_limit:
            raise DomainError("En-tête TLV tronqué.")
        length = image[cursor]
        cursor += 1
        if length == 0xFF:
            if cursor + 2 > memory_limit:
                raise DomainError("Longueur TLV étendue tronquée.")
            length = int.from_bytes(image[cursor:cursor + 2], "big")
            cursor += 2
        if cursor + length > memory_limit:
            raise DomainError("Le TLV dépasse la mémoire fournie.")
        if kind == 0x03:
            message_start, message_end = cursor, cursor + length
            break
        cursor += length
    if message_start is None or message_end is None:
        raise DomainError("Aucun TLV NDEF trouvé dans le tag.")

    cursor = message_start
    payloads: list[tuple[int, int]] = []
    first = True
    ended = False
    while cursor < message_end:
        if cursor + 2 > message_end:
            raise DomainError("En-tête NDEF tronqué.")
        flags, type_len = image[cursor:cursor + 2]
        cursor += 2
        mb, me, cf, sr, il = (bool(flags & bit) for bit in (0x80, 0x40, 0x20, 0x10, 0x08))
        if mb != first or ended:
            raise DomainError("Drapeaux de début/fin NDEF incohérents.")
        size_len = 1 if sr else 4
        if cursor + size_len + (1 if il else 0) > message_end:
            raise DomainError("Longueur NDEF tronquée.")
        payload_len = int.from_bytes(image[cursor:cursor + size_len], "big")
        cursor += size_len
        id_len = image[cursor] if il else 0
        if il:
            cursor += 1
        if cursor + type_len + id_len + payload_len > message_end:
            raise DomainError("L’enregistrement NDEF dépasse son message.")
        record_type = image[cursor:cursor + type_len]
        cursor += type_len + id_len
        if flags & 0x07 == 0x02 and record_type == MIME_TYPE:
            if cf:
                raise DomainError("Un enregistrement OpenPrintTag découpé en chunks est interdit.")
            payloads.append((cursor, payload_len))
        cursor += payload_len
        first, ended = False, me
        if me and cursor != message_end:
            raise DomainError("Données après le dernier enregistrement NDEF.")
    if not ended:
        raise DomainError("Le message NDEF n’a pas de dernier enregistrement.")
    if len(payloads) != 1:
        raise DomainError("Un unique enregistrement MIME OpenPrintTag est attendu.")
    return payloads[0]


class TagImage:
    """Immutable NFC-V memory image with region-preserving field updates."""

    def __init__(self, image: bytes, uid: str):
        self.uid = normalize_uid(uid)
        self._image = bytes(image)
        self.payload_offset, self.payload_length = _find_payload(self._image)
        payload = self._image[self.payload_offset:self.payload_offset + self.payload_length]
        self._meta, meta_used = _read_map(payload, "Meta")
        for key in (0, 1, 2, 3):
            if key in self._meta and (isinstance(self._meta[key], bool) or not isinstance(self._meta[key], int)):
                raise DomainError("Les offsets et tailles Meta doivent être des entiers.")
        main_start = self._meta.get(0, meta_used)
        aux_start = self._meta.get(2)
        if 3 in self._meta and aux_start is None:
            raise DomainError("Une taille Aux a été déclarée sans offset Aux.")
        starts = [main_start] + ([aux_start] if aux_start is not None else [])
        if any(start < meta_used or start >= len(payload) for start in starts) or len(set(starts)) != len(starts):
            raise DomainError("Offsets de régions invalides ou régions superposées.")
        boundaries = sorted(starts + [len(payload)])
        self.regions: dict[str, tuple[int, int]] = {"meta": (0, min(starts))}
        for name, start, size_key in (("main", main_start, 1), ("aux", aux_start, 3)):
            if start is None:
                continue
            next_start = next(boundary for boundary in boundaries if boundary > start)
            size = self._meta.get(size_key, next_start - start)
            # A region may reserve more than 512 bytes; the CBOR section itself
            # is limited by _read_map, and the allocation by its next boundary.
            if size < 1 or start + size > next_start:
                raise DomainError(f"Taille de région {name} invalide ou chevauchement.")
            if name == "aux" and size < 16:
                raise DomainError("La région Aux doit disposer d’au moins 16 octets.")
            self.regions[name] = (start, size)
        self._maps: dict[str, dict[int, Any]] = {}
        self._used: dict[str, int] = {"meta": meta_used}
        for name in ("main", "aux"):
            if name not in self.regions:
                continue
            offset, size = self.regions[name]
            self._maps[name], self._used[name] = _read_map(payload[offset:offset + size], name)
            # Validate known field representations, while retaining unknown CBOR values.
            _json_map(name, self._maps[name])

    @classmethod
    def from_bytes(cls, image: bytes, uid: str) -> "TagImage":
        if not isinstance(image, (bytes, bytearray, memoryview)):
            raise DomainError("Une image binaire de tag est attendue.")
        return cls(bytes(image), uid)

    @classmethod
    def create(cls, uid: str, main: dict[str, Any], aux: dict[str, Any] | None = None, capacity: int = 320) -> "TagImage":
        normalize_uid(uid)
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity % 8 or not 96 <= capacity <= 1024:
            raise DomainError("La capacité simulée doit être un multiple de 8 entre 96 et 1024 octets.")
        main = validate_fields("main", main, partial=False)
        aux = validate_fields("aux", aux or {}, partial=False)
        main.setdefault("instance_uuid", str(uuid.uuid4()))
        _check_mass_total(main, aux)
        main_encoded = _encode_map(_wire_map("main", main), number_types=_number_types("main"))
        aux_encoded = _encode_map(_wire_map("aux", aux), indefinite=True, number_types=_number_types("aux"))
        tlv_header_size = 4 if capacity - 7 > 254 else 2
        message_length = capacity - 4 - tlv_header_size - 1
        short_payload_size = message_length - 3 - len(MIME_TYPE)
        short = short_payload_size <= 255
        payload_size = message_length - (3 if short else 6) - len(MIME_TYPE)
        payload_offset = 4 + tlv_header_size + (3 if short else 6) + len(MIME_TYPE)
        aux_start = payload_size - 32
        aux_start -= (payload_offset + aux_start) % 4
        metadata = _encode_map({2: aux_start})
        main_capacity = aux_start - len(metadata)
        aux_capacity = payload_size - aux_start
        if main_capacity < 1 or aux_capacity < 16:
            raise DomainError("La capacité choisie ne permet pas ce profil Main/Aux.")
        if len(main_encoded) > main_capacity or len(aux_encoded) > aux_capacity:
            raise DomainError("Les données ne tiennent pas dans les régions du tag simulé.")
        payload = bytearray(payload_size)
        payload[:len(metadata)] = metadata
        payload[len(metadata):len(metadata) + len(main_encoded)] = main_encoded
        payload[aux_start:aux_start + len(aux_encoded)] = aux_encoded
        flags = 0xD2 if short else 0xC2  # MB | ME | [SR] | MIME TNF
        ndef = bytes([flags, len(MIME_TYPE)]) + len(payload).to_bytes(1 if short else 4, "big") + MIME_TYPE + payload
        tlv = bytes([0x03, len(ndef)]) if len(ndef) <= 254 else b"\x03\xff" + len(ndef).to_bytes(2, "big")
        image = bytes([0xE1, 0x40, capacity // 8, 0x01]) + tlv + ndef + b"\xfe"
        return cls.from_bytes(image, uid)

    @property
    def revision(self) -> str:
        return hashlib.sha256(self._image).hexdigest()

    @property
    def instance_uuid(self) -> str:
        explicit = self._maps["main"].get(0)
        if explicit is not None:
            return _from_wire(explicit, _definitions()["main"]["instance_uuid"])
        return _derive_instance_uuid(self.uid)

    def to_bytes(self) -> bytes:
        return self._image

    def snapshot(self) -> dict[str, Any]:
        main = _json_map("main", self._maps["main"])
        aux = _json_map("aux", self._maps.get("aux", {}))
        initial = main.get("actual_netto_full_weight", main.get("nominal_netto_full_weight"))
        consumed = aux.get("consumed_weight")
        remaining = initial - consumed if initial is not None and consumed is not None else None
        warnings = []
        if remaining is not None and remaining < 0:
            warnings.append("La consommation enregistrée dépasse le poids net initial.")
        if "material_class" not in main:
            warnings.append("Le champ obligatoire material_class est absent du tag.")
        unknown = {}
        for region, values in self._maps.items():
            keys = {field["key"] for field in _definitions()[region].values()}
            unknown[region] = [key for key in values if key not in keys]
        return {
            "uid": self.uid, "revision": self.revision, "instance_uuid": self.instance_uuid,
            "main": main, "aux": aux, "remaining_weight": remaining,
            "remaining_estimated": "actual_netto_full_weight" not in main and initial is not None,
            "usage": {
                "main_used": self._used["main"], "main_capacity": self.regions["main"][1],
                "aux_used": self._used.get("aux", 0), "aux_capacity": self.regions.get("aux", (0, 0))[1],
            },
            "unknown_fields": unknown, "warnings": warnings,
        }

    def with_updates(self, main_patch: dict[str, Any] | None = None, aux_patch: dict[str, Any] | None = None) -> "TagImage":
        patches = {"main": validate_fields("main", main_patch or {}), "aux": validate_fields("aux", aux_patch or {})}
        if "instance_uuid" in patches["main"] and patches["main"]["instance_uuid"] != self.instance_uuid:
            raise DomainError("Une modification ne peut pas changer l’identité de la bobine; utiliser une création distincte pour réemployer le tag.")
        # Only replace/delete map entries; opaque CBOR values are never mutated.
        # A shallow copy also preserves CBORTag objects that are not pickleable.
        maps = {region: dict(values) for region, values in self._maps.items()}
        changed: set[str] = set()
        for region, patch in patches.items():
            if not patch:
                continue
            if region not in self.regions:
                raise DomainError(f"Le tag ne dispose pas d’une région {region}; une mise à jour ne peut pas en ajouter.")
            for name, value in patch.items():
                field = _definitions()[region][name]
                key = field["key"]
                if value is None:
                    if key in maps[region]:
                        del maps[region][key]
                        changed.add(region)
                else:
                    wire = _to_wire(value, field)
                    if key not in maps[region] or maps[region][key] != wire:
                        maps[region][key] = wire
                        changed.add(region)
        main = _json_map("main", maps["main"])
        aux = _json_map("aux", maps.get("aux", {}))
        if "material_class" not in main:
            raise DomainError("Le tag doit contenir le champ obligatoire material_class.")
        _check_mass_total(main, aux)
        image = bytearray(self._image)
        for region in changed:
            encoded = _encode_map(maps[region], indefinite=region == "aux",
                                  number_types=_number_types(region, patches[region]))
            offset, capacity = self.regions[region]
            if len(encoded) > capacity:
                raise DomainError(f"La région {region} nécessite {len(encoded)} octets pour seulement {capacity} disponibles.")
            start = self.payload_offset + offset
            # Unused bytes may retain previous content; everything outside the region
            # remains byte-for-byte identical, including Meta, NDEF and other records.
            image[start:start + len(encoded)] = encoded
        return type(self).from_bytes(bytes(image), self.uid)
