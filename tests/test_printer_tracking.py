"""Prusa initial-data checks must never invent a mass or reset consumption."""
import copy
import struct

import cbor2
from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import DomainError, TagImage
from openprinttag_app.printer_tracking import missing_prusa_tracking_data


@pytest.mark.parametrize("main,missing", [
    ({"material_class": "FFF"}, ["initial_weight", "initial_length"]),
    ({"material_class": "FFF", "nominal_netto_full_weight": 1000}, ["initial_length"]),
    ({"material_class": "FFF", "actual_netto_full_weight": 1000, "nominal_full_length": 330000}, []),
    ({"material_class": "FFF", "actual_netto_full_weight": 0, "nominal_netto_full_weight": 1000, "actual_full_length": 10}, ["initial_weight"]),
    ({"material_class": "FFF", "actual_netto_full_weight": 1000, "nominal_full_length": 330000, "actual_full_length": 0}, ["initial_length"]),
    ({"material_class": "FFF", "actual_netto_full_weight": 1000, "nominal_full_length": 330000, "actual_full_length": 351000}, []),
    ({"material_class": "SLA"}, []),
    ({"material_class": "FFF", "nominal_netto_full_weight": 1000, "nominal_full_length": -3}, ["initial_length"]),
    ({"material_class": "FFF", "nominal_netto_full_weight": 1000, "nominal_full_length": float('nan')}, ["initial_length"]),
    ({"material_class": "FFF", "nominal_netto_full_weight": True, "nominal_full_length": 330000}, ["initial_weight"]),
])
def test_missing_data_respects_actual_priority_and_never_fills_values(main, missing):
    before = dict(main)
    assert missing_prusa_tracking_data(main) == missing
    assert main.keys() == before.keys()
    assert all(main[key] is before[key] for key in main)


@pytest.mark.parametrize("length,missing", [(None, ["initial_length"]), (330000, []), (0, ["initial_length"])])
def test_preview_warns_without_writing_or_changing_inventory(tmp_path, monkeypatch, length, missing):
    app = create_app(Settings(tmp_path))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        response = client.post('/api/simulator/blank', json={})
        assert response.status_code == 200, response.text
        tag = response.json()
        with app.state.store.connect() as db:
            before = list(db.iterdump())
        monkeypatch.setattr(app.state.reader, 'write', lambda *a, **k: pytest.fail('Preview must not write'))
        main = {"material_class": "FFF", "nominal_netto_full_weight": 1000, "actual_netto_full_weight": 1000,
                "density": 1.26, "filament_diameter": 1.75}
        if length is not None:
            main['nominal_full_length'] = length
        response = client.post('/api/reader/prepare', json={"mode": "create", "expected_uid": tag['uid'],
            "expected_revision": tag['revision'], "main": main, "aux": {"consumed_weight": 889}})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['prusa_tracking_missing'] == missing
        assert result['tag']['main'].get('nominal_full_length') == length
        assert 'actual_full_length' not in result['tag']['main']
        assert result['tag']['aux']['consumed_weight'] == 889
        assert result['tag']['remaining_weight'] == 111
        with app.state.store.connect() as db:
            assert list(db.iterdump()) == before


UID = "E0040108662F6FBC"  # Public specification fixture, not a real stock item.


def region_bytes(tag, name):
    offset, size = tag.regions[name]
    return tag.to_bytes()[tag.payload_offset + offset:tag.payload_offset + offset + size]


@pytest.mark.parametrize("consumed", [0.0, 637.0, 889.0, 1025.0])
def test_whole_consumption_is_an_exact_cbor_integer(consumed):
    tag = TagImage.create(UID, {"material_class": "FFF"}, {"consumed_weight": consumed})
    assert region_bytes(tag, "aux").startswith(b"\xbf\x00" + cbor2.dumps(int(consumed)) + b"\xff")
    assert tag.snapshot()["aux"]["consumed_weight"] == consumed


@pytest.mark.parametrize("consumed", [0.1, 637.3, 889.1, 123.5])
def test_fractional_consumption_uses_single_precision_not_double(consumed):
    tag = TagImage.create(UID, {"material_class": "FFF"}, {"consumed_weight": consumed})
    # Prusa's nanocbor_get_float rejects CBOR double (0xfb). This is the
    # independently specified CBOR single-precision wire representation.
    assert region_bytes(tag, "aux").startswith(b"\xbf\x00\xfa" + struct.pack(">f", consumed) + b"\xff")
    assert tag.snapshot()["aux"]["consumed_weight"] == pytest.approx(consumed, rel=6e-8)


def test_new_material_numbers_are_readable_without_modifying_source_values():
    main = {"material_class": "FFF", "actual_netto_full_weight": 1000.0,
            "nominal_full_length": 330000, "density": 1.26, "filament_diameter": 1.75}
    aux = {"consumed_weight": 889.0}
    before = copy.deepcopy((main, aux))
    tag = TagImage.create(UID, main, aux)
    assert (main, aux) == before
    assert b"\x18\x1d\xfa" + struct.pack(">f", 1.26) in region_bytes(tag, "main")
    snapshot = tag.snapshot()
    assert snapshot["main"]["actual_netto_full_weight"] == 1000
    assert snapshot["main"]["nominal_full_length"] == 330000
    assert snapshot["aux"]["consumed_weight"] == 889
    assert snapshot["remaining_weight"] == 111


def test_measured_lab_components_use_single_precision_and_keep_array_structure():
    values = [53.24, 111.12, -27.3]
    tag = TagImage.create(UID, {"material_class": "FFF", "primary_color_lab": values})
    expected = b"\x18\x3b\x83" + b"".join(b"\xfa" + struct.pack(">f", value) for value in values)
    assert expected in region_bytes(tag, "main")
    assert tag.snapshot()["main"]["primary_color_lab"] == pytest.approx(values, rel=6e-8)
    assert values == [53.24, 111.12, -27.3]


@pytest.mark.parametrize("value", [1e39, 1e-60])
def test_rfid_number_range_error_cannot_silently_create_infinity_or_zero(value):
    with pytest.raises(DomainError, match="plage"):
        TagImage.create(UID, {"material_class": "FFF", "density": value})


def test_partial_update_keeps_legacy_numbers_and_unknown_fields_untouched():
    tag = TagImage.create(UID, {"material_class": "FFF"}, {"consumed_weight": 0})
    values = cbor2.loads(region_bytes(tag, "main"))
    values.update({29: 1.26, 60000: 1.27})
    legacy = cbor2.dumps(values, canonical=True)
    image = bytearray(tag.to_bytes())
    offset, capacity = tag.regions["main"]
    start = tag.payload_offset + offset
    image[start:start + capacity] = legacy + bytes(capacity - len(legacy))
    tag = TagImage.from_bytes(image, UID)
    updated = tag.with_updates({"brand_name": "Test"}, {"consumed_weight": 12.3})
    assert b"\x18\x1d" + cbor2.dumps(1.26, canonical=True) in region_bytes(updated, "main")
    assert cbor2.loads(region_bytes(updated, "main"))[60000] == 1.27
    assert b"\xfb" in region_bytes(updated, "main")  # no implicit legacy migration
    assert region_bytes(updated, "aux").startswith(b"\xbf\x00\xfa" + struct.pack(">f", 12.3))
    assert updated.instance_uuid == tag.instance_uuid and updated.regions == tag.regions
