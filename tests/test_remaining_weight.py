"""Net remainder corrections use known mass and never write physical tags."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import TagImage
from openprinttag_app.qr import inspect_qr
from openprinttag_app.storage import ConflictError, Store

MAIN = {"material_class": "FFF", "material_type": "PETG", "material_name": "Test spool",
        "nominal_netto_full_weight": 1000, "actual_netto_full_weight": 1025,
        "empty_container_weight": 278}
UID = "E004015023456789"


@pytest.fixture
def station(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path / "data", network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        for owner, method in [(app.state.reader, "read"), (app.state.reader, "write"), (app.state.label_printer, "print")]:
            monkeypatch.setattr(owner, method, Mock(side_effect=AssertionError("No hardware for inventory corrections")))
        yield app, client


def add(app, kind="qr", main=None, aux=None):
    main = deepcopy(MAIN if main is None else main)
    aux = {"consumed_weight": 100} if aux is None else aux
    return (app.state.store.create_packaged(main, aux) if kind == "qr" else
            app.state.store.add(TagImage.create(UID, main, aux).snapshot()))


def adjust(client, item, value, **extra):
    return client.post(f"/api/inventory/{item['id']}/remaining", json={"version": item["version"], "remaining_weight": value, **extra})


@pytest.mark.parametrize("kind", ["qr", "rfid"])
@pytest.mark.parametrize("usage", ["stock", "in_service"])
def test_net_weight_preserves_spool_identity_notes_usage_and_tare(station, kind, usage):
    app, client = station
    item = add(app, kind)
    item = app.state.store.set_usage(item["id"], item["version"], usage)
    item = app.state.store.save_spool_notes(item["id"], "Measured tare: 278 g", 0)
    response = adjust(client, item, 555.5)
    assert response.status_code == 200, response.text
    result = response.json(); after = result["item"]
    assert result["updated"] and not result["rfid_written"]
    assert after["remaining_weight"] == 555.5
    assert after["aux"]["consumed_weight"] == 469.5  # 1025 - 555.5, tare is not subtracted
    assert after["version"] == item["version"] + 1
    for field in ("id", "uid", "instance_uuid", "spool_number", "added_at", "last_seen_at", "label_state", "usage_state", "notes", "notes_revision", "notes_updated_at", "in_stock", "completed_at", "main"):
        assert after[field] == item[field], field
    assert app.state.store.completed_count() == 0 and app.state.store.operations() == []
    assert Store(app.state.settings.database).get_spool(item["id"]) == after
    if kind == "rfid":
        assert after["rfid_sync_pending"] and after["rfid_pending_fields"] == ["aux.consumed_weight"]
        assert after["last_rfid_data"]["aux"] == item["aux"]
    else:
        qr = client.get(f"/api/inventory/{item['id']}/qr", params={"version": after["version"]}).json()["text"]
        decoded = inspect_qr(qr)
        assert decoded["aux"]["consumed_weight"] == 469.5
        assert client.get(f"/api/inventory/{item['id']}/qr", params={"version": item["version"]}).status_code == 409


def test_nominal_reference_is_explicitly_estimated_without_inventing_actual_mass(station):
    app, client = station
    item = add(app, main={"material_class": "FFF", "nominal_netto_full_weight": 1000}, aux={})
    assert item["remaining_weight"] is None
    after = adjust(client, item, 250).json()["item"]
    assert after["remaining_weight"] == 250 and after["aux"]["consumed_weight"] == 750
    assert after["remaining_estimated"] and "actual_netto_full_weight" not in after["main"]


def test_unknown_initial_mass_stays_unknown_until_explicitly_provided(station):
    app, client = station
    item = add(app, main={"material_class": "FFF"}, aux={})
    response = adjust(client, item, 500)
    assert response.status_code == 422 and "inconnu" in response.json()["detail"]
    assert app.state.store.get_spool(item["id"]) == item
    after = adjust(client, item, 500, actual_initial_weight=1200).json()["item"]
    assert after["main"]["actual_netto_full_weight"] == 1200
    assert after["aux"]["consumed_weight"] == 700 and not after["remaining_estimated"]


def test_explicit_actual_mass_can_correct_a_nominal_reference_and_never_changes_tare(station):
    app, client = station
    item = add(app, main={"material_class": "FFF", "nominal_netto_full_weight": 1000, "empty_container_weight": 278})
    assert adjust(client, item, 1010).status_code == 422
    after = adjust(client, item, 1010, actual_initial_weight=1025).json()["item"]
    assert after["remaining_weight"] == 1010 and after["aux"]["consumed_weight"] == 15
    assert after["main"]["empty_container_weight"] == 278
    assert after["main"]["nominal_netto_full_weight"] == 1000 and not after["remaining_estimated"]


@pytest.mark.parametrize("value", [0, 1025, 999.75])
def test_zero_full_and_fractional_remainders_do_not_archive_or_reuse_numbers(station, value):
    app, client = station
    item = add(app)
    after = adjust(client, item, value).json()["item"]
    assert after["remaining_weight"] == pytest.approx(value)
    assert after["aux"]["consumed_weight"] == pytest.approx(1025 - value)
    assert after["in_stock"] and after["completed_at"] is None and app.state.store.completed_count() == 0
    revision = app.state.store.inventory_revision()
    same = adjust(client, after, value).json()
    assert not same["updated"] and same["item"] == after
    assert app.state.store.inventory_revision() == revision


@pytest.mark.parametrize("body", [
    {"remaining_weight": -1}, {"remaining_weight": True}, {"remaining_weight": "500"},
    {"remaining_weight": None}, {"remaining_weight": 1026}, {"remaining_weight": 500, "version": True},
    {"remaining_weight": 500, "version": 0}, {"remaining_weight": 500, "version": "1"},
    {"remaining_weight": 500, "actual_initial_weight": 0}, {"remaining_weight": 500, "actual_initial_weight": -1},
    {"remaining_weight": 500, "actual_initial_weight": "1000"}, {"remaining_weight": 500, "actual_initial_weight": True},
    {"remaining_weight": 500, "uid": "OTHER"}, {"remaining_weight": 500, "consumed_weight": 1},
])
def test_invalid_body_never_changes_inventory(station, body):
    app, client = station; item = add(app)
    response = client.post(f"/api/inventory/{item['id']}/remaining", json={"version": item["version"], **body})
    assert response.status_code == 422, response.text
    assert app.state.store.get_spool(item["id"]) == item


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_numbers_are_rejected(station, value):
    app, client = station; item = add(app)
    response = client.post(f"/api/inventory/{item['id']}/remaining", content='{"version":1,"remaining_weight":'+value+'}', headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert app.state.store.get_spool(item["id"]) == item


@pytest.mark.parametrize("state", ["removed", "completed"])
def test_inactive_records_are_immutable(station, state):
    app, client = station; item = add(app)
    current = (app.state.store.remove if state == "removed" else app.state.store.complete)(item["id"], item["version"])
    assert adjust(client, current, 500).status_code == 409
    assert app.state.store.get_spool(item["id"]) == current


def test_stale_version_and_rfid_reread_preserve_the_correction(station):
    app, client = station; item = add(app, "rfid")
    after = adjust(client, item, 400).json()["item"]
    assert adjust(client, item, 600).status_code == 409
    reread = app.state.store.observe(TagImage.create(UID, item["main"], item["aux"]).snapshot())
    assert reread["remaining_weight"] == 400 and reread["rfid_sync_pending"]
    assert reread["last_rfid_data"]["aux"]["consumed_weight"] == 100
    matching = app.state.store.observe(TagImage.create(UID, item["main"], {"consumed_weight": 625}).snapshot())
    assert matching["remaining_weight"] == 400 and not matching.get("rfid_sync_pending")


def test_concurrent_edits_only_accept_one_version(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3"); item = store.create_packaged(MAIN, {"consumed_weight": 100})
    def adjust_one(amount):
        try:return store.set_remaining_weight(item["id"], item["version"], amount)
        except ConflictError:return None
    with ThreadPoolExecutor(max_workers=6) as pool:results = list(pool.map(adjust_one, [10, 20, 30, 40, 50, 60]))
    assert sum(r is not None for r in results) == 1
    assert store.get_spool(item["id"])["remaining_weight"] in [10, 20, 30, 40, 50, 60]
    assert store.get_spool(item["id"])["version"] == item["version"] + 1


def test_inventory_network_access_is_allowed_but_disabled_access_and_wrong_origin_are_refused(station):
    app, client = station; item = add(app)
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        response = adjust(remote, item, 500); assert response.status_code == 200
        current = response.json()["item"]
        assert remote.post(f"/api/inventory/{item['id']}/remaining", json={"version": current["version"], "remaining_weight": 400}, headers={"Origin": "https://unrelated.invalid"}).status_code == 403
        client.put('/api/configuration/network', json={"mode": "disabled"})
        assert adjust(remote, current, 400).status_code == 403
    assert app.state.store.get_spool(item["id"]) == current


@pytest.mark.parametrize("kind", ["qr", "rfid"])
def test_corrected_weights_survive_backup_restore_with_the_same_spool(station, kind):
    import base64
    app, client = station
    item = add(app, kind)
    corrected = adjust(client, item, 350, actual_initial_weight=1100).json()["item"]
    backup = client.post('/api/backups/download', json={"scope": "inventory"})
    assert backup.status_code == 200
    changed = adjust(client, corrected, 100).json()["item"]
    preview = client.post('/api/backups/restore/preview', json={"content": base64.b64encode(backup.content).decode()})
    assert preview.status_code == 200, preview.text
    restored = client.post('/api/backups/restore/commit', json={"preview_id": preview.json()["preview_id"], "confirmed": True})
    assert restored.status_code == 200, restored.text
    after = app.state.store.get_spool(item["id"])
    assert after["remaining_weight"] == 350 and after["aux"]["consumed_weight"] == 750
    assert after["main"]["actual_netto_full_weight"] == 1100
    assert after["spool_number"] == item["spool_number"] and after["instance_uuid"] == item["instance_uuid"]
    assert bool(after.get("rfid_sync_pending")) == (kind == "rfid")
    assert adjust(client, changed, 200).status_code == 409
