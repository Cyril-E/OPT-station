"""Usage belongs to inventory; reusable profiles never inherit an individual spool."""
from concurrent.futures import ThreadPoolExecutor
import base64
import sqlite3
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.backups import decrypt, encrypt
from openprinttag_app.config import Settings
from openprinttag_app.domain import SPEC_ROOT, TagImage
from openprinttag_app.storage import ConflictError, Store

MAIN = {"material_class": "FFF", "material_type": "PETG", "brand_name": "Essai",
        "material_name": "Bobine reçue", "nominal_netto_full_weight": 1000,
        "actual_netto_full_weight": 1025, "empty_container_weight": 278,
        "filament_diameter": 1.75, "primary_color": "#123456",
        "brand_specific_instance_id": "THIS-SPOOL-ONLY", "manufactured_date": 1775012345}
AUX = {"consumed_weight": 637, "storage_location": "Sous-sol"}
UID = "E004015023456789"


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path / "data", network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


def usage(client, item, value):
    return client.post(f"/api/inventory/{item['id']}/usage", json={"version": item["version"], "usage_state": value})


def rfid(store):
    return store.add(TagImage.create(UID, MAIN, AUX).snapshot())


def factory_rfid(store):
    tag = TagImage.from_bytes((SPEC_ROOT / "tests/encode_decode/01_data.bin").read_bytes(), UID)
    assert "instance_uuid" not in tag.snapshot()["main"]
    return store.add(tag.snapshot())


def assert_same_spool(before, after):
    for key in before.keys() - {"version", "usage_state"}:
        assert after[key] == before[key], key


def forbid_hardware(app, monkeypatch):
    for obj, method in ((app.state.reader, "read"), (app.state.reader, "write"), (app.state.label_printer, "print")):
        monkeypatch.setattr(obj, method, Mock(side_effect=AssertionError("No physical I/O for inventory usage or profiles")))


def test_rfid_roundtrip_preserves_identity_consumption_notes_and_inventory(station, monkeypatch):
    app, client = station
    item = rfid(app.state.store)
    item = app.state.store.save_spool_notes(item["id"], "Tare mesurée 278 g", 0)
    assert item["usage_state"] == "in_service" and item["label_state"] == "rfid"
    forbid_hardware(app, monkeypatch)
    original_revision = app.state.store.inventory_revision()
    stocked = usage(client, item, "stock")
    assert stocked.status_code == 200, stocked.text
    stocked = stocked.json()
    assert stocked["usage_state"] == "stock" and stocked["in_stock"]
    assert stocked["version"] == item["version"] + 1
    assert_same_spool(item, stocked)
    assert Store(app.state.settings.database).get_spool(item["id"]) == stocked
    active = usage(client, stocked, "in_service").json()
    assert active["usage_state"] == "in_service" and active["remaining_weight"] == 388
    assert_same_spool(item, active)
    assert app.state.store.inventory_revision() == original_revision + 2
    assert client.get("/api/inventory").json()["items"] == [active]
    assert app.state.store.completed_count() == 0 and app.state.store.operations() == []
    assert app.state.store.create_packaged(MAIN, {})["spool_number"] == "B0001"


def test_reread_readdition_and_removal_restore_do_not_reset_rfid_usage(station):
    app, client = station
    item = usage(client, rfid(app.state.store), "stock").json()
    snapshot = TagImage.create(UID, item["main"], {"consumed_weight": 700}).snapshot()
    observed = app.state.store.observe(snapshot)
    assert observed["usage_state"] == "stock" and observed["aux"]["consumed_weight"] == 700
    readded = app.state.store.add(snapshot)
    assert readded["usage_state"] == "stock"
    removed = app.state.store.remove(item["id"], readded["version"])
    assert usage(client, removed, "in_service").status_code == 409
    restored = app.state.store.restore(item["id"], removed["version"])
    assert restored["usage_state"] == "stock" and restored["uid"] == UID


def test_qr_can_be_in_service_without_creating_a_tag(station, monkeypatch):
    app, client = station
    item = app.state.store.create_packaged(MAIN, AUX)
    assert item["usage_state"] == "stock"
    forbid_hardware(app, monkeypatch)
    result = usage(client, item, "in_service").json()
    assert result["usage_state"] == "in_service" and result["label_state"] == "qr"
    assert result["uid"] is None and result["in_stock"]
    assert_same_spool(item, result)


def test_same_state_is_idempotent_but_stale_changes_are_rejected(station):
    app, client = station
    item = rfid(app.state.store)
    revision = app.state.store.inventory_revision()
    assert usage(client, item, "in_service").json() == item
    assert app.state.store.inventory_revision() == revision
    changed = usage(client, item, "stock").json()
    assert usage(client, item, "in_service").status_code == 409
    assert app.state.store.get_spool(item["id"]) == changed


@pytest.mark.parametrize("body", [{}, {"version": True, "usage_state": "stock"},
    {"version": "1", "usage_state": "stock"}, {"version": 0, "usage_state": "stock"},
    {"version": 1, "usage_state": "rfid"}, {"version": 1, "usage_state": None},
    {"version": 1, "usage_state": "stock", "consumed_weight": 0}])
def test_invalid_usage_cannot_change_a_spool(station, body):
    app, client = station
    item = rfid(app.state.store)
    response = client.post(f"/api/inventory/{item['id']}/usage", json=body)
    assert response.status_code == 422
    assert app.state.store.get_spool(item["id"]) == item


def test_archived_records_cannot_be_reactivated_or_uncounted(station):
    app, client = station
    item = rfid(app.state.store)
    archived = app.state.store.complete(item["id"], item["version"])
    for value in ("stock", "in_service"):
        assert usage(client, archived, value).status_code == 409
    assert app.state.store.completed_count() == 1
    assert app.state.store.get_spool(item["id"]) == archived


def test_competing_usage_changes_conflict_across_connections(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3")
    item = rfid(store)
    def change(_):
        try:
            return store.set_usage(item["id"], item["version"], "stock")
        except ConflictError:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(change, range(6)))
    assert sum(value is not None for value in results) == 1
    assert store.get_spool(item["id"])["usage_state"] == "stock"


@pytest.mark.parametrize("kind", ["qr", "rfid", "archived"])
def test_inventory_model_preview_is_reviewable_readonly_and_excludes_individual_data(station, monkeypatch, kind):
    app, client = station
    store = app.state.store
    item = store.create_packaged(MAIN, AUX) if kind == "qr" else rfid(store)
    if kind == "archived":
        item = store.complete(item["id"], item["version"])
    item = store.save_spool_notes(item["id"], "Notes privées de cette bobine", 0)
    forbid_hardware(app, monkeypatch)
    revision = store.inventory_revision()
    response = client.post(f"/api/inventory/{item['id']}/model-source", json={"version": item["version"]})
    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile["source"] == "inventory" and profile["spool_number"] == item["spool_number"]
    assert profile["suggested_name"] == MAIN["material_name"]
    assert profile["main"]["empty_container_weight"] == 278
    assert profile["main"]["nominal_netto_full_weight"] == 1000
    assert not {"uid", "instance_uuid", "notes", "actual_netto_full_weight", "brand_specific_instance_id", "manufactured_date", "consumed_weight"} & profile["main"].keys()
    assert not {"aux", "notes", "usage_state", "uid", "added_at"} & profile.keys()
    assert store.favorites() == [] and store.get_spool(item["id"]) == item
    assert store.inventory_revision() == revision
    reviewed = {**profile["main"], "material_name": "Modèle vérifié"}
    saved = client.post("/api/favorites", json={"kind": "model", "name": "Mon nouveau modèle", "main": reviewed})
    assert saved.status_code == 200, saved.text
    assert saved.json()["main"] == reviewed
    assert store.get_spool(item["id"]) == item
    assert client.post("/api/favorites", json={"kind": "model", "name": "Mon nouveau modèle", "main": reviewed}).status_code == 409


def test_inventory_profile_does_not_invent_missing_nominal_weight_or_tare(station):
    app, client = station
    item = app.state.store.create_packaged({"material_class": "FFF", "material_type": "PLA", "actual_netto_full_weight": 995}, {})
    result = client.post(f"/api/inventory/{item['id']}/model-source", json={"version": item["version"]}).json()
    assert result["main"] == {"material_class": "FFF", "material_type": "PLA"}


def test_inventory_model_preview_rejects_a_stale_version(station):
    app, client = station
    item = rfid(app.state.store)
    usage(client, item, "stock").raise_for_status()
    assert client.post(f"/api/inventory/{item['id']}/model-source", json={"version": item["version"]}).status_code == 409
    assert app.state.store.favorites() == []


def test_new_inventory_actions_obey_access_origin_and_power_guards(station, monkeypatch):
    app, client = station
    item = rfid(app.state.store)
    forbid_hardware(app, monkeypatch)
    client.put("/api/configuration/network", json={"mode": "inventory"}).raise_for_status()
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        item = usage(remote, item, "stock").json()
        assert remote.post(f"/api/inventory/{item['id']}/model-source", json={"version": item["version"]}).status_code == 200
        client.put("/api/configuration/network", json={"mode": "disabled"}).raise_for_status()
        assert usage(remote, item, "in_service").status_code == 403
        assert remote.post(f"/api/inventory/{item['id']}/model-source", json={"version": item["version"]}).status_code == 403
    for route, body in (("usage", {"version": item["version"], "usage_state": "in_service"}), ("model-source", {"version": item["version"]})):
        path = f"/api/inventory/{item['id']}/{route}"
        assert client.post(path, json=body, headers={"Origin": "https://other.example"}).status_code == 403
        assert client.post(path, content="{}").status_code == 415
        assert client.post(path.replace(item["id"], "missing"), json=body).status_code == 404
        app.state.station_power.phase = "requested"
        assert client.post(path, json=body).status_code == 503
        app.state.station_power.phase = "idle"


def legacy_v4(path):
    store = Store(path)
    a, b = rfid(store), store.create_packaged(MAIN, AUX)
    store.save_spool_notes(a["id"], "À conserver", 0)
    with store.connect() as db:
        db.execute("ALTER TABLE spools DROP COLUMN usage_state")
        db.execute("UPDATE metadata SET value='4' WHERE key='schema_version'")
        rows = [dict(row) for row in db.execute("SELECT * FROM spools ORDER BY sequence_number")]
    return a, b, rows


def test_v4_migration_preserves_data_and_initializes_previously_displayed_usage(tmp_path):
    path = tmp_path / "old.sqlite3"
    a, b, before = legacy_v4(path)
    store = Store(path)
    assert store.get_spool(a["id"])["usage_state"] == "in_service"
    assert store.get_spool(b["id"])["usage_state"] == "stock"
    with store.connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM spools ORDER BY sequence_number")]
        for row in rows:
            del row["usage_state"]
        assert rows == before
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == "6"
    assert Store(path).get_spool(b["id"])["usage_state"] == "stock"


def test_failed_usage_migration_rolls_back_without_modifying_old_data(tmp_path):
    path = tmp_path / "old.sqlite3"
    _, _, before = legacy_v4(path)
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TRIGGER refuse_migration BEFORE UPDATE ON metadata
            WHEN NEW.key='schema_version' BEGIN SELECT RAISE(ABORT,'storage failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError):
        Store(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert "usage_state" not in {row[1] for row in db.execute("PRAGMA table_info(spools)")}
        assert [dict(row) for row in db.execute("SELECT * FROM spools ORDER BY sequence_number")] == before
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == "4"


@pytest.mark.parametrize("schema", [4, 5])
@pytest.mark.parametrize("factory", [False, True])
def test_backup_restore_preserves_usage_and_accepts_previous_backups(station, schema, factory):
    app, client = station
    item = factory_rfid(app.state.store) if factory else rfid(app.state.store)
    if schema == 5:
        item = usage(client, item, "stock").json()
    qr = app.state.store.create_packaged(MAIN, {})
    password = "test-only-password-2026"
    response = client.post("/api/backups/download", json={"scope": "inventory", "password": password})
    assert response.status_code == 200, response.text
    record = decrypt(response.content, password)
    assert record["inventory"]["schema"] == 6
    record["inventory"]["schema"] = schema
    record["inventory"]["tables"].pop("photos")
    for row in record["inventory"]["tables"]["metadata"]["rows"]:
        if row[0] == "schema_version":
            row[1] = str(schema)
    if schema == 4:
        table = record["inventory"]["tables"]["spools"]
        index = table["columns"].index("usage_state")
        del table["columns"][index]
        for row in table["rows"]:
            del row[index]
        for row in record["inventory"]["tables"]["metadata"]["rows"]:
            if row[0] == "schema_version":
                row[1] = "4"
    usage(client, item, "in_service" if schema == 5 else "stock").raise_for_status()
    content = base64.b64encode(encrypt(record, password)).decode()
    preview = client.post("/api/backups/restore/preview", json={"content": content, "password": password})
    assert preview.status_code == 200, preview.text
    restored = client.post("/api/backups/restore/commit", json={"preview_id": preview.json()["preview_id"], "confirmed": True})
    assert restored.status_code == 200, restored.text
    current = app.state.store.get_spool(item["id"])
    assert current["usage_state"] == item["usage_state"]
    assert current["main"] == item["main"] and current["aux"] == item["aux"]
    assert app.state.store.get_spool(qr["id"])["usage_state"] == "stock"
    with app.state.store.connect() as db:
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == "6"


def test_factory_rfid_usage_and_model_keep_the_uid_derived_spool_identity(station, monkeypatch):
    app, client = station
    item = factory_rfid(app.state.store)
    forbid_hardware(app, monkeypatch)
    stocked = usage(client, item, "stock").json()
    assert_same_spool(item, stocked)
    assert stocked["usage_state"] == "stock"
    profile = client.post(f"/api/inventory/{item['id']}/model-source", json={"version": stocked["version"]})
    assert profile.status_code == 200, profile.text
    assert profile.json()["main"]["material_type"] == item["main"]["material_type"]
    assert "instance_uuid" not in profile.json()["main"]
    assert app.state.store.get_spool(item["id"]) == stocked and app.state.store.favorites() == []


def test_first_rfid_creation_activates_usage_but_recreation_preserves_explicit_stock(station):
    app, client = station
    item = app.state.store.create_packaged(MAIN, AUX)
    for recreate in (False, True):
        blank = client.post("/api/simulator/blank", json={}).json()
        response = client.post("/api/reader/prepare", json={"mode": "create",
            "expected_uid": blank["uid"], "expected_revision": blank["revision"],
            "inventory_id": item["id"], "inventory_version": item["version"], "inventory_recreate": recreate})
        assert response.status_code == 200, response.text
        result = client.post("/api/reader/write", json={"preview_id": response.json()["preview_id"]})
        assert result.status_code == 200, result.text
        item = app.state.store.get_spool(item["id"])
        assert item["usage_state"] == ("stock" if recreate else "in_service")
        assert item["label_state"] == "rfid" and item["aux"] == AUX
        item = usage(client, item, "stock").json()
