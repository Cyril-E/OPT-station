"""Codec checks use official binary/YAML fixtures as inert reference data only."""

from __future__ import annotations

import uuid

import cbor2
import pytest
import yaml

from openprinttag_app.domain import (
    DomainError, SPEC_ROOT, TagImage, get_schema, normalize_uid,
    validate_favorite_main, validate_fields,
)


UID = "E0040108662F6FBC"  # Public specification fixture: tests/encode_decode/01_input.yaml.
MAIN = {
    "material_class": "FFF", "material_type": "PLA", "brand_name": "Essai",
    "material_name": "PLA test", "nominal_netto_full_weight": 1000,
    "primary_color": "#123456",
}


def make_tag(main=None, aux=None, capacity=320):
    return TagImage.create(UID, main or dict(MAIN), aux, capacity=capacity)


def region_bytes(tag, region):
    start, size = tag.regions[region]
    return tag.to_bytes()[tag.payload_offset + start:tag.payload_offset + start + size]


def replace_region(tag, region, values):
    encoded = cbor2.dumps(values, canonical=True)
    start, size = tag.regions[region]
    assert len(encoded) <= size
    image = bytearray(tag.to_bytes())
    absolute = tag.payload_offset + start
    image[absolute:absolute + size] = encoded + bytes(size - len(encoded))
    return TagImage.from_bytes(bytes(image), tag.uid)


def assert_numeric_equal(actual, expected):
    if isinstance(expected, (int, float)):
        assert actual == pytest.approx(expected, rel=0.001, abs=0.001)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for got, wanted in zip(actual, expected):
            assert_numeric_equal(got, wanted)
    else:
        assert actual == expected


@pytest.mark.parametrize("number", ["01", "02", "03", "04", "05"])
def test_official_binary_fixtures_match_official_decoded_fields(number):
    root = SPEC_ROOT / "tests" / "encode_decode"
    image = (root / f"{number}_data.bin").read_bytes()
    expected = yaml.safe_load((root / f"{number}_info.yaml").read_text(encoding="utf-8"))
    tag = TagImage.from_bytes(image, UID)
    snapshot = tag.snapshot()
    for region in ("main", "aux"):
        for name, value in expected["data"][region].items():
            assert name in snapshot[region]
            assert_numeric_equal(snapshot[region][name], value)
        assert snapshot["usage"][f"{region}_used"] == expected["regions"][region]["used_size"]
        assert snapshot["usage"][f"{region}_capacity"] == expected["regions"][region]["size"]
    assert tag.to_bytes() == image


def test_official_sample_image_decodes_explicit_instance_uuid():
    image = (SPEC_ROOT / "docs_src" / "sample_data" / "sample_tag.bin").read_bytes()
    tag = TagImage.from_bytes(image, UID)
    assert tag.instance_uuid == "473bb8cd-e129-45b8-9fcf-da1c3add9c47"
    assert tag.snapshot()["main"]["material_class"] == "FFF"


def test_uid_derivation_uses_official_binary_namespace_rule():
    tag = TagImage.from_bytes((SPEC_ROOT / "tests/encode_decode/01_data.bin").read_bytes(), UID)
    assert "instance_uuid" not in tag.snapshot()["main"]
    assert tag.instance_uuid == "bf63e92d-9ca5-53d7-9fab-ffdd0240c585"
    assert normalize_uid("e0:04:01:08:66:2f:6f:bc") == UID
    with pytest.raises(DomainError, match="UID NFC-V"):
        normalize_uid("BC6F2F66080104E0")


@pytest.mark.parametrize("capacity", [128, 256, 304, 312, 320, 512, 1024])
def test_new_simulation_profile_round_trips_short_and_long_ndef(capacity):
    tag = TagImage.create(UID, {"material_class": "FFF"}, {"consumed_weight": 0}, capacity)
    parsed = TagImage.from_bytes(tag.to_bytes(), UID)
    assert len(tag.to_bytes()) == capacity
    assert tag.to_bytes()[2] * 8 == capacity
    assert parsed.snapshot()["main"]["material_class"] == "FFF"
    assert parsed.snapshot()["aux"]["consumed_weight"] == 0
    assert (parsed.payload_offset + parsed.regions["aux"][0]) % 4 == 0
    assert parsed.regions["aux"][1] >= 32


def test_simulated_1024_byte_tag_has_large_main_allocation_and_short_section():
    tag = TagImage.create(UID, {"material_class": "FFF"}, capacity=1024)
    usage = tag.snapshot()["usage"]
    assert usage["main_capacity"] > 512
    assert usage["main_used"] < 512
    updated = tag.with_updates({"brand_name": "Test"})
    assert len(updated.to_bytes()) == 1024
    assert updated.regions == tag.regions
    assert updated.snapshot()["main"]["brand_name"] == "Test"


def test_new_creations_from_same_favorite_have_different_instances():
    profile = validate_favorite_main(MAIN)
    first = make_tag(profile)
    second = make_tag(profile)
    assert first.instance_uuid != second.instance_uuid
    assert uuid.UUID(first.instance_uuid).version == 4


def test_aux_update_preserves_meta_headers_main_and_other_ndef_records():
    original = (SPEC_ROOT / "tests/encode_decode/01_data.bin").read_bytes()
    # Insert a NULL TLV, an unrelated proprietary TLV and another NULL TLV.
    # Original fixture already contains a URI NDEF record before OpenPrintTag.
    prefix = b"\x00\xfd\x04test\x00"
    image = original[:2] + bytes([40]) + original[3:4] + prefix + original[4:]
    tag = TagImage.from_bytes(image, UID)
    updated = tag.with_updates({}, {"consumed_weight": 123.5})
    absolute = tag.payload_offset + tag.regions["aux"][0]
    end = absolute + tag.regions["aux"][1]
    assert updated.to_bytes()[:absolute] == image[:absolute]
    assert updated.to_bytes()[end:] == image[end:]
    assert b"3dtag.org/s/334c54f088" in updated.to_bytes()
    assert updated.snapshot()["remaining_weight"] == pytest.approx(888.5)


def test_main_update_preserves_unknown_cbor_values_and_unknown_enum_items():
    tag = make_tag(aux={"consumed_weight": 100})
    values = cbor2.loads(region_bytes(tag, "main"))
    future = cbor2.CBORTag(60099, {"future": [b"opaque", 65535]})
    values[60000] = future
    values[9] = 65000  # material_type unknown integer enum
    values[28] = [65535]  # unknown tags enum item
    tag = replace_region(tag, "main", values)
    changed = tag.with_updates({"primary_color": "#abcdef88"}, {})
    raw = cbor2.loads(region_bytes(changed, "main"))
    assert raw[60000] == future
    assert raw[9] == 65000
    assert raw[28] == [65535]
    assert changed.snapshot()["main"]["material_type"] == 65000
    assert changed.snapshot()["main"]["tags"] == [65535]
    assert changed.snapshot()["unknown_fields"]["main"] == [60000]
    start = tag.payload_offset + tag.regions["main"][0]
    end = start + tag.regions["main"][1]
    assert changed.to_bytes()[:start] == tag.to_bytes()[:start]
    assert changed.to_bytes()[end:] == tag.to_bytes()[end:]


def test_explicit_region_offsets_sizes_and_gaps_are_preserved():
    tag = make_tag()
    payload = bytearray(tag.payload_length)
    metadata = cbor2.dumps({0: 24, 1: 160, 2: 224, 3: 32})
    payload[:len(metadata)] = metadata
    payload[24:27] = cbor2.dumps({8: 0})
    payload[224] = 0xA0
    payload[184:224] = b"\x99" * 40  # unused gap outside either region
    image = bytearray(tag.to_bytes())
    image[tag.payload_offset:tag.payload_offset + tag.payload_length] = payload
    parsed = TagImage.from_bytes(bytes(image), UID)
    assert parsed.regions["main"] == (24, 160)
    assert parsed.regions["aux"] == (224, 32)
    updated = parsed.with_updates({"brand_name": "Test"}, {})
    assert updated.regions == parsed.regions
    assert updated.to_bytes()[tag.payload_offset + 184:tag.payload_offset + 224] == b"\x99" * 40
    assert region_bytes(updated, "meta") == region_bytes(parsed, "meta")


@pytest.mark.parametrize("main_start,main_capacity", [(24, 600), (600, 100)])
def test_large_region_allocations_are_bounded_by_payload_not_section_limit(main_start, main_capacity):
    # nfc_data_format.md sections 2 and 3.1 distinguish reserved regions from
    # CBOR sections. The first layout reserves 600 B for Main; the second for Meta.
    tag = make_tag(capacity=1024)
    payload = bytearray(tag.payload_length)
    metadata = cbor2.dumps({0: main_start, 1: main_capacity, 2: 800, 3: 100})
    payload[:len(metadata)] = metadata
    main = cbor2.dumps({8: 0})
    payload[main_start:main_start + len(main)] = main
    payload[800] = 0xA0
    image = bytearray(tag.to_bytes())
    image[tag.payload_offset:tag.payload_offset + tag.payload_length] = payload
    parsed = TagImage.from_bytes(bytes(image), UID)
    assert parsed.regions["main"] == (main_start, main_capacity)
    assert parsed.regions["meta"] == (0, main_start)
    assert parsed.snapshot()["usage"]["main_used"] == len(main)
    updated = parsed.with_updates({"brand_name": "Test"})
    absolute = tag.payload_offset + main_start
    end = absolute + main_capacity
    assert updated.to_bytes()[:absolute] == bytes(image)[:absolute]
    assert updated.to_bytes()[end:] == bytes(image)[end:]
    assert updated.regions == parsed.regions
    assert updated.snapshot()["main"]["brand_name"] == "Test"


def test_large_allocation_does_not_allow_cbor_section_over_512_bytes():
    tag = make_tag(capacity=1024)
    assert tag.regions["main"][1] > 512
    with pytest.raises(DomainError, match="512 octets"):
        replace_region(tag, "main", {8: 0, 60000: b"x" * 520})


def test_update_cannot_grow_section_over_512_even_if_allocation_fits():
    tag = replace_region(make_tag(capacity=1024), "main", {8: 0, 60000: b"x" * 480})
    assert tag.snapshot()["usage"]["main_used"] <= 512
    assert tag.regions["main"][1] > 512
    original = tag.to_bytes()
    with pytest.raises(DomainError, match="512 octets"):
        tag.with_updates({"brand_name": "é" * 15})
    assert tag.to_bytes() == original


def test_update_cannot_allocate_missing_aux_region():
    tag = make_tag()
    payload = bytearray(tag.payload_length)
    payload[:4] = cbor2.dumps({}) + cbor2.dumps({8: 0})
    image = bytearray(tag.to_bytes())
    image[tag.payload_offset:tag.payload_offset + len(payload)] = payload
    no_aux = TagImage.from_bytes(bytes(image), UID)
    assert no_aux.snapshot()["usage"]["aux_capacity"] == 0
    with pytest.raises(DomainError, match="ne dispose pas"):
        no_aux.with_updates({}, {"consumed_weight": 2})


def test_update_fails_instead_of_growing_aux_or_touching_image():
    tag = make_tag(aux={"consumed_weight": 20})
    values = cbor2.loads(region_bytes(tag, "aux"))
    values[60001] = b"1234567890123456789012345"
    tag = replace_region(tag, "aux", values)
    original = tag.to_bytes()
    with pytest.raises(DomainError, match="nécessite"):
        tag.with_updates({}, {"storage_location": "ABCDEFGH"})
    assert tag.to_bytes() == original


def test_null_removes_optional_field_and_required_or_identity_is_protected():
    tag = make_tag()
    changed = tag.with_updates({"material_name": None}, {})
    assert "material_name" not in changed.snapshot()["main"]
    assert changed.instance_uuid == tag.instance_uuid
    with pytest.raises(DomainError, match="obligatoire"):
        tag.with_updates({"material_class": None}, {})
    with pytest.raises(DomainError, match="identité"):
        tag.with_updates({"instance_uuid": str(uuid.uuid4())}, {})
    with pytest.raises(DomainError, match="identité"):
        tag.with_updates({"instance_uuid": None}, {})


def test_noop_update_does_not_reencode_official_image():
    image = (SPEC_ROOT / "tests/encode_decode/01_data.bin").read_bytes()
    tag = TagImage.from_bytes(image, UID)
    changed = tag.with_updates({"brand_name": "Prusament"}, {})
    assert changed.to_bytes() == image
    assert changed.revision == tag.revision


def test_actual_weight_has_priority_and_missing_consumption_stays_unknown():
    main = dict(MAIN, actual_netto_full_weight=1012)
    tag = make_tag(main)
    assert tag.snapshot()["remaining_weight"] is None
    assert tag.snapshot()["remaining_estimated"] is False
    tag = tag.with_updates({}, {"consumed_weight": 12})
    assert tag.snapshot()["remaining_weight"] == 1000
    fallback = make_tag(aux={"consumed_weight": 0})
    assert fallback.snapshot()["remaining_weight"] == 1000
    assert fallback.snapshot()["remaining_estimated"] is True
    no_weight = make_tag({"material_class": "FFF"}, {"consumed_weight": 2})
    assert no_weight.snapshot()["remaining_weight"] is None


def test_consistency_of_initial_and_consumed_weights():
    tag = make_tag(aux={"consumed_weight": 500})
    with pytest.raises(DomainError, match="dépasse"):
        tag.with_updates({}, {"consumed_weight": 1001})
    with pytest.raises(DomainError, match="dépasse"):
        tag.with_updates({"actual_netto_full_weight": 499}, {})
    with pytest.raises(DomainError, match="négatif"):
        validate_fields("aux", {"consumed_weight": -1})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, 2**10000])
def test_numeric_values_are_finite_and_not_booleans(value):
    with pytest.raises(DomainError):
        validate_fields("aux", {"consumed_weight": value})


def test_utf8_limits_colors_enum_arrays_and_required_data():
    assert validate_fields("aux", {"storage_location": "é" * 4})["storage_location"] == "é" * 4
    with pytest.raises(DomainError, match="octets"):
        validate_fields("aux", {"storage_location": "é" * 5})
    with pytest.raises(DomainError, match="octets"):
        validate_fields("main", {"brand_name": "é" * 16})
    with pytest.raises(DomainError, match="UTF-8"):
        validate_fields("main", {"brand_name": "\ud800"})
    with pytest.raises(DomainError, match="couleur"):
        validate_fields("main", {"primary_color": "orange"})
    assert validate_fields("main", {"primary_color": "#AAFF0088"}) == {"primary_color": "#aaff0088"}
    assert validate_fields("main", {"material_type": 65535}) == {"material_type": 65535}
    with pytest.raises(DomainError):
        validate_fields("main", {"material_type": 65536})
    with pytest.raises(DomainError):
        validate_fields("main", {"material_type": 1.0})
    with pytest.raises(DomainError):
        validate_fields("main", {"tags": [0] * 17})
    with pytest.raises(DomainError, match="obligatoire"):
        TagImage.create(UID, {"brand_name": "test"})
    with pytest.raises(DomainError, match="inconnu"):
        validate_fields("main", {"custom_extension": 4})


@pytest.mark.parametrize("name,value", [
    ("instance_uuid", str(uuid.uuid4())), ("actual_netto_full_weight", 1002),
    ("brand_specific_instance_id", "ABC"), ("manufactured_date", 1000),
])
def test_favorites_do_not_duplicate_instance_data(name, value):
    with pytest.raises(DomainError, match="favori"):
        validate_favorite_main({name: value})


def test_favorite_may_be_partial_but_is_still_validated():
    assert validate_favorite_main({"brand_name": "Test", "primary_color": None}) == {"brand_name": "Test"}
    with pytest.raises(DomainError):
        validate_favorite_main({"primary_color": "blue"})


def test_malformed_or_unsupported_images_fail_closed():
    good = make_tag().to_bytes()
    with pytest.raises(DomainError):
        TagImage.from_bytes(good[:-1], UID)
    with pytest.raises(DomainError, match="CC E1"):
        TagImage.from_bytes(b"\xe2" + good[1:], UID)
    image = bytearray(good)
    image[6:8] = b"\xff\xff"  # impossible extended TLV length
    with pytest.raises(DomainError, match="TLV"):
        TagImage.from_bytes(bytes(image), UID)
    tag = make_tag()
    image = bytearray(good)
    # Metadata makes Main and Aux overlap at the same offset.
    metadata = cbor2.dumps({0: 24, 2: 24})
    image[tag.payload_offset:tag.payload_offset + len(metadata)] = metadata
    with pytest.raises(DomainError, match="superposées"):
        TagImage.from_bytes(bytes(image), UID)


def test_schema_exposes_official_types_and_tokens_without_shared_mutability():
    schema = get_schema()
    material = next(row for row in schema["main"] if row["name"] == "material_type")
    assert material["type"] == "enum"
    assert {"value": "PLA", "label": "PLA"} in material["options"]
    main = next(row for row in schema["main"] if row["name"] == "material_class")
    assert main["required"] is True
    material["options"].clear()
    assert next(row for row in get_schema()["main"] if row["name"] == "material_type")["options"]


def test_enum_encoded_as_cbor_float_is_rejected_even_for_an_integer_value():
    tag = make_tag()
    values = cbor2.loads(region_bytes(tag, "main"))
    values[9] = 1.0
    with pytest.raises(DomainError, match="énumération"):
        replace_region(tag, "main", values)
