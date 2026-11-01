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


def inspect_for(client, item):
    response = client.post('/api/reader/inspect-inventory', json={
        'inventory_id': item['id'], 'inventory_version': item['version'],
        'inventory_recreate': item['label_state'] == 'rfid'})
    assert response.status_code == 200, response.text
    return response.json()


def reuse_preview(client, item, tag):
    response = client.post('/api/reader/prepare', json=body(item, tag,
        recreate=item['label_state'] == 'rfid', reuse_tag=True))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('target_kind', ['qr', 'rfid'])
@pytest.mark.parametrize('previous_state', ['active', 'removed', 'completed'])
def test_reuse_transfers_only_the_uid_after_verified_write(station, target_kind, previous_state):
    app, client = station
    old = rfid(app, client)
    old = app.state.store.save_spool_notes(old['id'], 'Tare et historique à conserver', 0)
    old = app.state.store.patch_spool(old['id'], old['version'], aux={'consumed_weight': 500})['item']
    if previous_state == 'removed':
        old = app.state.store.remove(old['id'], old['version'])
    elif previous_state == 'completed':
        old = client.post(f"/api/inventory/{old['id']}/complete", json={'version': old['version']}).json()
    target = packaged(client) if target_kind == 'qr' else rfid(app, client)
    app.state.reader.select(old['uid'])
    before = app.state.store.list_spools(include_removed=True)
    tag = inspect_for(client, target)
    assert tag['reuse_required'] and tag['reuse_source']['id'] == old['id']
    assert app.state.store.list_spools(include_removed=True) == before
    preview = reuse_preview(client, target, tag)
    assert preview['reuse'] and preview['reused_tag']['inventory']['id'] == old['id']
    assert any(c['name'] == 'instance_uuid' and c['before'] == old['instance_uuid'] and c['after'] == target['instance_uuid'] for c in preview['changes'])
    assert app.state.store.list_spools(include_removed=True) == before
    response = commit(client, preview)
    assert response.status_code == 200, response.text
    updated = app.state.store.get_spool(target['id'])
    same_spool(target, updated)
    assert updated['uid'] == old['uid'] and updated['label_state'] == 'rfid'
    previous = app.state.store.get_spool(old['id'])
    same_spool(old, previous)
    assert previous['usage_state'] == old['usage_state'] and previous['last_seen_at'] == old['last_seen_at']
    assert previous['uid'] is None and previous['label_state'] == 'qr'
    assert not previous.get('rfid_sync_pending')
    assert previous['version'] == old['version'] + 1
    assert len(app.state.store.list_spools(include_removed=True)) == 2
    operation = app.state.store.operations()[0]
    assert operation['status'] == 'complete' and operation['reuse_from']['inventory_id'] == old['id']
    assert operation['detail'] is None


@pytest.mark.parametrize('known_owner', [False, True])
def test_reuse_requires_explicit_consent_and_inspection_never_observes_inventory(station, monkeypatch, known_owner):
    app, client = station
    if known_owner:
        rfid(app, client)
    target = packaged(client)
    before = app.state.store.list_spools(include_removed=True)
    tag = inspect_for(client, target)
    monkeypatch.setattr(app.state.reader, 'write', lambda *a, **k: pytest.fail('No consent: no write'))
    response = client.post('/api/reader/prepare', json=body(target, tag, recreate=False))
    assert response.status_code == 409
    assert app.state.store.list_spools(include_removed=True) == before


def test_an_unregistered_used_tag_can_be_reused_without_creating_an_old_spool(station):
    app, client = station
    target = packaged(client)
    tag = inspect_for(client, target)
    assert tag['reuse_source'] is None
    response = commit(client, reuse_preview(client, target, tag))
    assert response.status_code == 200, response.text
    assert len(app.state.store.list_spools(include_removed=True)) == 1


def test_a_retired_copy_can_be_inspected_and_reused_without_detaching_the_current_tag(station):
    app, client = station
    old = rfid(app, client)
    preview, _ = prepare(client, old)
    assert commit(client, preview).status_code == 200
    current_old = app.state.store.get_spool(old['id'])
    target = packaged(client)
    app.state.reader.select(old['uid'])
    assert client.get('/api/reader/tag').status_code == 409
    tag = inspect_for(client, target)
    assert tag['reuse_source'] is None
    assert commit(client, reuse_preview(client, target, tag)).status_code == 200
    assert app.state.store.get_spool(old['id']) == current_old


def test_a_physically_erased_tag_still_needs_consent_to_move_its_association(station):
    app, client = station
    old = rfid(app, client)
    app.state.reader.write(bytes(320))
    target = packaged(client)
    tag = inspect_for(client, target)
    assert tag['blank'] and tag['reuse_required']
    assert commit(client, reuse_preview(client, target, tag)).status_code == 200
    assert app.state.store.get_spool(old['id'])['uid'] is None


@pytest.mark.parametrize('changed', ['source', 'target', 'tag'])
def test_reuse_rechecks_both_inventory_versions_and_the_physical_tag(station, monkeypatch, changed):
    app, client = station
    old = rfid(app, client); target = packaged(client)
    preview = reuse_preview(client, target, inspect_for(client, target))
    if changed == 'tag':
        app.state.reader.protect(True, False)
    else:
        item = old if changed == 'source' else target
        app.state.store.set_usage(item['id'], item['version'], 'stock' if item['usage_state'] != 'stock' else 'in_service')
    monkeypatch.setattr(app.state.reader, 'write', lambda *a, **k: pytest.fail('Stale preparation must not write'))
    assert commit(client, preview).status_code == 409


@pytest.mark.parametrize('target_kind', ['qr', 'rfid'])
@pytest.mark.parametrize('failure', ['after_write', 'association', 'restart'])
def test_interrupted_reuse_preserves_both_spools_and_recovers_without_rewriting(station, monkeypatch, target_kind, failure):
    app, client = station
    old = rfid(app, client)
    target = packaged(client) if target_kind == 'qr' else rfid(app, client)
    app.state.reader.select(old['uid'])
    preview = reuse_preview(client, target, inspect_for(client, target))
    original = app.state.reader.write; calls = []
    def write(image, *, reuse=False):
        assert reuse
        calls.append(image); original(image, reuse=reuse)
        if failure != 'association':
            raise ReaderUnavailable('Interruption après écriture')
    monkeypatch.setattr(app.state.reader, 'write', write)
    if failure == 'association':
        with app.state.store.connect() as db:
            db.execute(f"CREATE TRIGGER reject_target BEFORE UPDATE ON spools WHEN OLD.id='{target['id']}' BEGIN SELECT RAISE(ABORT,'test interruption'); END")
    assert commit(client, preview).status_code == 503
    assert app.state.store.get_spool(old['id']) == old
    assert app.state.store.get_spool(target['id']) == target
    with pytest.raises(ValueError, match='attend la confirmation'):
        app.state.store.patch_spool(old['id'], old['version'], aux={'consumed_weight': 50})
    if failure == 'association':
        with app.state.store.connect() as db:
            db.execute('DROP TRIGGER reject_target')
    if failure == 'restart':
        with app.state.store.connect() as db:
            db.execute("UPDATE operations SET status='pending' WHERE inventory_id=? AND status='uncertain'", (target['id'],))
        Store(app.state.settings.database).recover_pending_operations()
    monkeypatch.setattr(app.state.reader, 'write', lambda *a, **k: pytest.fail('Reconciliation must not rewrite'))
    current = client.get('/api/reader/tag')
    assert current.status_code == 200, current.text
    tag = current.json(); pending = tag['association_pending']
    assert pending['id'] == target['id'] and pending['recreate'] == (target_kind == 'rfid')
    response = client.post(f"/api/inventory/{target['id']}/associate", json={**identity(tag), 'version': pending['version'], 'recreate': pending['recreate']})
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert app.state.store.get_spool(old['id'])['uid'] is None
    assert app.state.store.get_spool(target['id'])['uid'] == old['uid']
    assert app.state.store.operations()[0]['status'] == 'complete'


@pytest.mark.parametrize('changes,status', [({'reuse_tag': 'true'}, 422), ({'mode': 'update'}, 409),
    ({'inventory_id': None, 'inventory_version': None}, 422), ({'favorite_id': 'any'}, 422)])
def test_reuse_is_strictly_scoped_to_an_inventory_creation(station, changes, status):
    app, client = station
    target = packaged(client); tag = inspect_for(client, target)
    response = client.post('/api/reader/prepare', json={**body(target, tag, recreate=False, reuse_tag=True), **changes})
    assert response.status_code == status, response.text


def test_reused_associations_and_journal_survive_backup_restore(station):
    app, client = station
    old = rfid(app, client); target = packaged(client)
    assert commit(client, reuse_preview(client, target, inspect_for(client, target))).status_code == 200
    expected = {item['id']: item for item in app.state.store.list_spools(include_removed=True)}
    operations = app.state.store.operations()
    backup = client.post('/api/backups/download', json={'scope': 'all', 'password': ''})
    assert backup.status_code == 200
    current = app.state.store.get_spool(target['id'])
    app.state.store.remove(target['id'], current['version'])
    preview = client.post('/api/backups/restore/preview', json={'content': base64.b64encode(backup.content).decode(), 'password': ''})
    assert preview.status_code == 200, preview.text
    restored = client.post('/api/backups/restore/commit', json={'preview_id': preview.json()['preview_id'], 'confirmed': True})
    assert restored.status_code == 200, restored.text
    for item in app.state.store.list_spools(include_removed=True):
        same_spool({**expected[item['id']], 'notes_revision': item['notes_revision']}, item)
        assert item['uid'] == expected[item['id']]['uid'] and item['label_state'] == expected[item['id']]['label_state']
    assert app.state.store.operations() == operations


def test_reuse_is_refused_remotely_without_full_access(station):
    app, local = station
    old = rfid(app, local); target = packaged(local)
    preview = reuse_preview(local, target, inspect_for(local, target))
    local.put('/api/configuration/network', json={'mode': 'inventory'})
    with TestClient(app, client=('192.0.2.42', 1)) as remote:
        assert remote.post('/api/reader/inspect-inventory', json={'inventory_id': target['id'], 'inventory_version': target['version']}).status_code == 403
        assert remote.post('/api/reader/prepare', json=body(target, inspect_for(local, target), recreate=False, reuse_tag=True)).status_code == 403
        assert commit(remote, preview).status_code == 403
    assert app.state.store.get_spool(old['id']) == old


def test_reuse_of_the_same_physical_tag_preserves_local_consumption(station):
    app, client = station
    target = rfid(app, client)
    target = app.state.store.patch_spool(target['id'], target['version'], aux={'consumed_weight': 700})['item']
    preview = reuse_preview(client, target, inspect_for(client, target))
    assert commit(client, preview).status_code == 200
    updated = app.state.store.get_spool(target['id'])
    same_spool(target, updated)
    assert updated['uid'] == target['uid'] and updated['aux']['consumed_weight'] == 700
    assert not updated.get('rfid_sync_pending')


def test_two_reuse_previews_on_the_same_tag_cannot_transfer_it_twice(station, monkeypatch):
    app, client = station
    old = rfid(app, client); first = packaged(client); second = packaged(client)
    previews = [reuse_preview(client, item, inspect_for(client, item)) for item in (first, second)]
    original = app.state.reader.write; calls = []
    def write(image, *, reuse=False):
        calls.append(image); original(image, reuse=reuse)
    monkeypatch.setattr(app.state.reader, 'write', write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda preview: commit(client, preview), previews))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(calls) == 1
    assert app.state.store.get_spool(old['id'])['uid'] is None
    records = [app.state.store.get_spool(item['id']) for item in (first, second)]
    assert sum(item.get('uid') == old['uid'] for item in records) == 1


def test_the_current_inventory_qr_can_also_prepare_explicit_tag_reuse(station):
    from openprinttag_app.spool_qr import encode_spool
    app, client = station
    target = packaged(client); tag = inspect_for(client, target)
    preview = client.post('/api/reader/prepare', json=body(target, tag, recreate=False,
        reuse_tag=True, qr_raw=encode_spool(target)))
    assert preview.status_code == 200, preview.text
    assert commit(client, preview.json()).status_code == 200
    assert app.state.store.get_spool(target['id'])['uid'] == tag['uid']
