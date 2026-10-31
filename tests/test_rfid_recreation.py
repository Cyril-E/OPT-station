"""Inventory -> first/replacement RFID; all writes use the persistent simulator."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import TagImage
from openprinttag_app.readers import ReaderUnavailable, revision
from openprinttag_app.storage import Store

MAIN = {"material_class": "FFF", "material_type": "PETG", "brand_name": "Essai",
        "nominal_netto_full_weight": 1000, "actual_netto_full_weight": 1025,
        "empty_container_weight": 278, "primary_color": "#3B353A", "filament_diameter": 1.75}
AUX = {"consumed_weight": 637, "purchase_time": 2**53 + 11, "storage_location": "Atelier"}


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path / "data", network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


def identity(tag):
    return {"expected_uid": tag["uid"], "expected_revision": tag["revision"]}


def packaged(client):
    response = client.post("/api/inventory/packaged", json={"main": MAIN, "aux": AUX})
    assert response.status_code == 200, response.text
    return response.json()


def body(item, tag, recreate=True, **overrides):
    return {"mode": "create", "main": {}, "aux": {}, **identity(tag),
            "inventory_id": item["id"], "inventory_version": item["version"],
            "inventory_recreate": recreate, **overrides}


def prepare(client, item, recreate=True):
    tag = client.post("/api/simulator/blank", json={}).json()
    response = client.post("/api/reader/prepare", json=body(item, tag, recreate))
    assert response.status_code == 200, response.text
    return response.json(), tag


def commit(client, preview):
    return client.post("/api/reader/write", json={"preview_id": preview["preview_id"]})


def rfid(app, client):
    item = packaged(client)
    preview, _ = prepare(client, item, recreate=False)
    response = commit(client, preview)
    assert response.status_code == 200, response.text
    return app.state.store.get_spool(item["id"])


def same_spool(before, after):
    for key in ("id", "instance_uuid", "spool_number", "added_at", "main", "aux",
                "notes", "notes_revision", "notes_updated_at", "in_stock", "completed_at"):
        assert after[key] == before[key], key


def test_first_tag_and_repeated_replacement_preserve_the_current_spool(station):
    app, client = station
    item = rfid(app, client)
    item = app.state.store.save_spool_notes(item["id"], "Tare mesurée : 278 g", 0)
    previous_uid = item["uid"]
    for _ in range(2):
        preview, tag = prepare(client, item)
        assert preview["recreation"] is True
        assert preview["tag"]["inventory"]["uid"] == previous_uid
        assert preview["tag"]["main"] == item["main"] and preview["tag"]["aux"] == item["aux"]
        assert app.state.store.get_spool(item["id"]) == item  # Preview never detaches the old tag.
        response = commit(client, preview)
        assert response.status_code == 200, response.text
        updated = app.state.store.get_spool(item["id"])
        same_spool(item, updated)
        assert updated["uid"] == tag["uid"] != previous_uid
        assert updated["aux"]["purchase_time"] == 2**53 + 11
        assert updated["remaining_weight"] == 388
        assert app.state.store.operations()[0]["status"] == "complete"
        assert len(app.state.store.list_spools(include_removed=True)) == 1
        item, previous_uid = updated, tag["uid"]
    assert packaged(client)["spool_number"] == "B0001"


def test_retired_tag_and_completed_operation_cannot_restore_the_old_association(station):
    app, client = station
    item = rfid(app, client)
    old_uid = item["uid"]
    preview, _ = prepare(client, item)
    assert commit(client, preview).status_code == 200
    updated = app.state.store.get_spool(item["id"])
    app.state.reader.select(old_uid)
    assert client.get("/api/reader/tag").status_code == 409
    old = app.state.reader.read()
    expected = {"expected_uid": old_uid, "expected_revision": revision(old)}
    assert client.post("/api/inventory/add", json=expected).status_code == 409
    assert client.post(f"/api/inventory/{item['id']}/associate", json={**expected, "version": updated["version"], "recreate": True}).status_code == 409
    assert app.state.store.get_spool(item["id"]) == updated


@pytest.mark.parametrize("source_state,explicit,status", [("qr", False, 200), ("qr", True, 409), ("rfid", False, 409), ("rfid", True, 200)])
def test_first_creation_and_replacement_require_the_matching_explicit_mode(station, source_state, explicit, status):
    app, client = station
    item = rfid(app, client) if source_state == "rfid" else packaged(client)
    tag = client.post("/api/simulator/blank", json={}).json()
    assert client.post("/api/reader/prepare", json=body(item, tag, explicit)).status_code == status


@pytest.mark.parametrize("changes,status", [({"inventory_id": None, "inventory_version": None}, 422),
    ({"favorite_id": "other"}, 422), ({"qr_raw": "text"}, 422), ({"mode": "update"}, 422),
    ({"inventory_version": None}, 422), ({"inventory_recreate": "true"}, 422)])
def test_replacement_cannot_mix_sources_or_skip_identity_and_version(station, changes, status):
    app, client = station
    item = rfid(app, client)
    tag = client.post("/api/simulator/blank", json={}).json()
    result = client.post("/api/reader/prepare", json=body(item, tag, **changes))
    assert result.status_code == status, result.text
    assert app.state.store.get_spool(item["id"]) == item


@pytest.mark.parametrize("change", ["version", "removed", "completed"])
def test_stock_change_after_preview_refuses_physical_write(station, monkeypatch, change):
    app, client = station
    item = rfid(app, client)
    preview, _ = prepare(client, item)
    store = app.state.store
    if change == "removed":
        store.remove(item["id"], item["version"])
    elif change == "completed":
        client.post(f"/api/inventory/{item['id']}/complete", json={"version": item["version"]})
    else:
        with store.connect() as db:
            db.execute("UPDATE spools SET version=version+1 WHERE id=?", (item["id"],))
    def forbidden(*args):
        pytest.fail("A stale preview must not write to the tag")
    monkeypatch.setattr(app.state.reader, "write", forbidden)
    assert commit(client, preview).status_code == 409
    assert app.state.reader.read()["image"] == bytes(320)


@pytest.mark.parametrize("failure", ["after_write", "association", "restart"])
@pytest.mark.parametrize("same_uid", [False, True])
def test_interrupted_replacement_is_recovered_without_a_second_write(station, monkeypatch, failure, same_uid):
    app, client = station
    item = rfid(app, client)
    if same_uid:
        # A previously associated tag may have been erased outside OPT Station.
        app.state.reader.write(bytes(320))
        tag = client.get("/api/reader/tag").json()
        response = client.post("/api/reader/prepare", json=body(item, tag))
        assert response.status_code == 200, response.text
        preview = response.json()
    else:
        preview, tag = prepare(client, item)
    write = app.state.reader.write
    associate = app.state.store.associate
    calls = []
    def interrupted(image):
        calls.append(bytes(image)); write(image)
        if failure in {"after_write", "restart"}:
            raise ReaderUnavailable("Interruption après écriture")
    def failed_association(*args, **kwargs):
        raise sqlite3.OperationalError("Simulated inventory failure")
    monkeypatch.setattr(app.state.reader, "write", interrupted)
    if failure == "association":
        monkeypatch.setattr(app.state.store, "associate", failed_association)
    assert commit(client, preview).status_code == 503
    monkeypatch.setattr(app.state.store, "associate", associate)
    assert app.state.store.get_spool(item["id"]) == item
    if failure == "restart":
        # A crash can leave a pending journal row. Hardware startup marks it uncertain.
        with app.state.store.connect() as db:
            db.execute("UPDATE operations SET status='pending' WHERE uid=?", (tag["uid"],))
        Store(app.state.settings.database).recover_pending_operations()
    reread = client.get("/api/reader/tag")
    assert reread.status_code == 200, reread.text
    current = reread.json()
    assert current["association_pending"] == {"id": item["id"], "version": item["version"], "spool_number": item["spool_number"], "recreate": True}
    assert app.state.store.get_spool(item["id"]) == item  # Reading must not observe/attach it.
    assert client.post("/api/inventory/add", json=identity(current)).status_code == 409
    assert client.post("/api/reader/prepare", json={**identity(current), "mode": "update", "aux": {"consumed_weight": 0}}).status_code == 409
    response = client.post(f"/api/inventory/{item['id']}/associate", json={**identity(current), "version": item["version"], "recreate": True})
    assert response.status_code == 200, response.text
    updated = app.state.store.get_spool(item["id"])
    same_spool(item, updated)
    assert updated["uid"] == tag["uid"] and len(calls) == 1
    assert app.state.store.operations()[0]["status"] == "complete"
    assert "association_pending" not in client.get("/api/reader/tag").json()
    assert client.post(f"/api/inventory/{item['id']}/associate", json={**identity(current), "version": item["version"], "recreate": True}).status_code == 409


def test_recovery_requires_the_exact_journaled_image(station, monkeypatch):
    app, client = station
    item = rfid(app, client)
    preview, _ = prepare(client, item)
    original = app.state.reader.write
    def interrupted(image):
        original(image)
        raise ReaderUnavailable("Interrupted")
    monkeypatch.setattr(app.state.reader, "write", interrupted)
    assert commit(client, preview).status_code == 503
    record = app.state.reader.read()
    changed = TagImage.from_bytes(record["image"], record["uid"]).with_updates(aux_patch={"consumed_weight": 100}).to_bytes()
    original(changed)
    tag = {"uid": record["uid"], "revision": revision(app.state.reader.read())}
    assert client.get("/api/reader/tag").status_code == 409
    assert client.post(f"/api/inventory/{item['id']}/associate", json={**identity(tag), "version": item["version"], "recreate": True}).status_code == 409
    assert app.state.store.get_spool(item["id"]) == item


def test_target_uid_in_another_spool_is_rejected_even_when_physically_blank(station):
    app, client = station
    item = rfid(app, client)
    other = rfid(app, client)
    record = app.state.reader.read()
    with app.state.store.connect() as db:
        db.execute("UPDATE simulated_tags SET image=? WHERE uid=?", (bytes(len(record["image"])), other["uid"]))
    tag = client.get("/api/reader/tag").json()
    response = client.post("/api/reader/prepare", json=body(item, tag))
    assert response.status_code == 409
    assert app.state.store.get_spool(item["id"]) == item
    assert app.state.store.get_spool(other["id"]) == other


@pytest.mark.parametrize("target", ["nonblank", "locked", "unsupported", "small"])
def test_replacement_target_must_be_blank_writable_and_large_enough(station, monkeypatch, target):
    app, client = station
    item = rfid(app, client)
    tag = client.post("/api/simulator/blank", json={}).json()
    if target == "nonblank":
        app.state.reader.write(TagImage.create(tag["uid"], {"material_class": "FFF"}, {}).to_bytes())
    elif target == "locked":
        app.state.reader.protect(True, False)
    else:
        original = app.state.reader.read
        def read():
            result = original()
            result.update({"write_supported": False} if target == "unsupported" else {"usable_capacity": 48})
            return result
        monkeypatch.setattr(app.state.reader, "read", read)
    record = app.state.reader.read()
    tag["revision"] = revision(record)
    response = client.post("/api/reader/prepare", json=body(item, tag))
    assert response.status_code in {409, 422, 423}, response.text
    assert app.state.store.get_spool(item["id"]) == item


def test_unknown_source_fields_are_not_silently_lost(station):
    app, client = station
    item = rfid(app, client)
    with app.state.store.connect() as db:
        snapshot = json.loads(db.execute("SELECT snapshot FROM spools WHERE id=?", (item["id"],)).fetchone()[0])
        snapshot["unknown_fields"]["main"] = [999]
        db.execute("UPDATE spools SET snapshot=? WHERE id=?", (json.dumps(snapshot), item["id"]))
    tag = client.post("/api/simulator/blank", json={}).json()
    response = client.post("/api/reader/prepare", json=body(item, tag))
    assert response.status_code == 422 and "inconnus" in response.json()["detail"]


def test_two_previews_cannot_write_two_replacement_tags_for_one_version(station, monkeypatch):
    app, client = station
    item = rfid(app, client)
    preview, tag = prepare(client, item)
    second = client.post("/api/reader/prepare", json=body(item, tag)).json()
    original = app.state.reader.write
    calls = []
    def write(image):
        calls.append(image); original(image)
    monkeypatch.setattr(app.state.reader, "write", write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda p: commit(client, p), [preview, second]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(calls) == 1


def test_a_normal_update_preview_on_the_old_tag_is_revoked_after_replacement(station, monkeypatch):
    app, client = station
    item = rfid(app, client)
    old = client.get("/api/reader/tag").json()
    previous = client.post("/api/reader/prepare", json={**identity(old), "mode": "update", "aux": {"consumed_weight": 700}})
    assert previous.status_code == 200
    item = app.state.store.get_spool(item["id"])
    preview, _ = prepare(client, item)
    assert commit(client, preview).status_code == 200
    app.state.reader.select(old["uid"])
    def forbidden(*args):
        pytest.fail("An old update preview must not write a retired RFID")
    monkeypatch.setattr(app.state.reader, "write", forbidden)
    assert commit(client, previous.json()).status_code == 409


def test_inventory_access_cannot_prepare_commit_or_confirm_a_replacement(station):
    app, local = station
    item = rfid(app, local)
    preview, tag = prepare(local, item)
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        assert remote.post("/api/reader/prepare", json=body(item, tag)).status_code == 403
        assert commit(remote, preview).status_code == 403
        assert remote.post(f"/api/inventory/{item['id']}/associate", json={**identity(tag), "version": item["version"], "recreate": True}).status_code == 403
        assert remote.put("/api/configuration/network", json={"mode": "full"}).status_code == 200
        assert commit(remote, preview).status_code == 200


def test_replacement_association_and_journal_survive_encrypted_backup_restore(station):
    app, client = station
    item = rfid(app, client)
    preview, _ = prepare(client, item)
    assert commit(client, preview).status_code == 200
    updated = app.state.store.get_spool(item["id"])
    operations = app.state.store.operations()
    password = "replacement-backup-test-password"
    backup = client.post("/api/backups/download", json={"scope": "all", "password": password})
    assert backup.status_code == 200
    app.state.store.remove(item["id"], updated["version"])
    p = client.post("/api/backups/restore/preview", json={"content": base64.b64encode(backup.content).decode(), "password": password})
    assert p.status_code == 200, p.text
    response = client.post("/api/backups/restore/commit", json={"preview_id": p.json()["preview_id"], "confirmed": True})
    assert response.status_code == 200, response.text
    restored = app.state.store.get_spool(item["id"])
    # Restoration deliberately advances optimistic note versions to reject old drafts.
    assert restored["notes_revision"] > updated["notes_revision"]
    same_spool({**updated, "notes_revision": restored["notes_revision"]}, restored)
    assert restored["uid"] == updated["uid"]
    assert app.state.store.operations() == operations
