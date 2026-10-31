"""Backups use temporary databases and fake mounts; never restore real Pi data."""
from datetime import datetime, timedelta, timezone
import base64
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.backups import (BackupError, BackupManager, MaintenanceGate, decrypt, encrypt,
                                    private_json, database_copy, recover_restore, mounted_volumes)
from openprinttag_app.config import Settings
from openprinttag_app.storage import ConflictError, Store

PASSWORD = "test-backup-password-2026"
MAIN = {"material_class": "FFF", "material_type": "PETG", "brand_name": "Test", "nominal_netto_full_weight": 1000, "empty_container_weight": 234}


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path / "data", network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


def get_backup(client, scope="all"):
    response = client.post("/api/backups/download", json={"scope": scope, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.content


def preview(client, content):
    response = client.post("/api/backups/restore/preview", json={"content": base64.b64encode(content).decode(), "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def schedule(manager, tmp_path, enabled=True, password=PASSWORD, **changes):
    mount = tmp_path / "external"; mount.mkdir(exist_ok=True)
    volumes = [{"path": str(mount), "source": "/dev/fake1", "filesystem": "ext4", "writable": True, "network": False}]
    manager.volumes = lambda: deepcopy(volumes)
    body = {k: v for k, v in manager.configuration.items() if k not in {"version", "station_id"}}
    body.update(enabled=enabled, destination=str(mount / "opt-backups"), mount_path=str(mount), mount_source="/dev/fake1", password=password)
    body.update(changes)
    manager.save(body)
    return mount, volumes


def test_encryption_authentication_and_bounded_format():
    record = {"private": "test-secret", "unicode": "é📦", "large": 2**53 + 11}
    content = encrypt(record, PASSWORD)
    assert b"test-secret" not in content and decrypt(content, PASSWORD) == record
    assert encrypt(record, PASSWORD) != content
    for altered in (content[:-1], content[:40] + bytes([content[40] ^ 1]) + content[41:], b"bad"):
        with pytest.raises(BackupError): decrypt(altered, PASSWORD)
    with pytest.raises(BackupError): decrypt(content, "wrong-password")
    with pytest.raises(BackupError): encrypt(record, "short")


@pytest.mark.parametrize("scope", ["all", "inventory", "configuration"])
def test_manual_scope_portability_no_sql_and_no_private_automation_key(station, scope):
    app, client = station
    spool = app.state.store.create_packaged(MAIN, {"consumed_weight": 100})
    app.state.store.save_spool_notes(spool["id"], "Tare mesurée 234 g", 0)
    app.state.store.save_inventory_notes("Référence indicative", 0)
    private_json(app.state.settings.data_dir / "backup-key.json", {"secret": "NEVER EXPORT"})
    content = get_backup(client, scope)
    record = decrypt(content, PASSWORD)
    assert record["scope"] == scope and record["mode"] == "simulation"
    assert ("inventory" in record) == (scope != "configuration")
    assert ("configuration" in record) == (scope != "inventory")
    assert "NEVER EXPORT" not in json.dumps(record)
    report = preview(client, content)
    assert report["scope"] == scope
    assert app.state.store.get_spool("B0000")["notes"] == "Tare mesurée 234 g"
    assert not (app.state.settings.data_dir / "restore-points").exists()


def test_restore_replaces_inventory_preserves_counter_archives_notes_and_versions(station):
    app, client = station; store = app.state.store
    first = store.create_packaged(MAIN, {"consumed_weight": 500})
    store.save_spool_notes(first["id"], "Une note\nmesurée", 0)
    store.save_inventory_notes("Un carnet 📦", 0)
    archived = store.create_packaged(MAIN, {})
    store.complete(archived["id"], 1)
    favorite = store.save_favorite("Modèle", {"empty_container_weight": 234}, kind="model")
    content = get_backup(client, "inventory")
    store.save_inventory_notes("Après sauvegarde", 1)
    store.save_spool_notes(first["id"], "Nouvelle note", 1)
    store.patch_template(favorite["id"], 1, "model", main={"empty_container_weight": 300})
    store.create_packaged(MAIN, {})  # B0002 may not be recycled after restore.
    report = preview(client, content)
    assert report["spools"] == 2 and report["completed"] == 1 and report["templates"] == 1
    assert client.post("/api/backups/restore/commit", json={"preview_id": report["preview_id"], "confirmed": False}).status_code == 422
    response = client.post("/api/backups/restore/commit", json={"preview_id": report["preview_id"], "confirmed": True})
    assert response.status_code == 200, response.text
    assert store.get_spool("B0000")["notes"] == "Une note\nmesurée"
    assert store.get_spool("B0000")["aux"]["consumed_weight"] == 500
    assert store.get_spool("B0001")["completed_at"] == archived.get("completed_at") or store.completed_count() == 1
    assert store.inventory_notes()["text"] == "Un carnet 📦" and store.inventory_notes()["revision"] > 2
    assert store.favorites()[0]["main"] == {"empty_container_weight": 234} and store.favorites()[0]["version"] > 2
    assert store.create_packaged(MAIN, {})["spool_number"] == "B0003"
    assert response.json()["rollback_point"]
    point = app.state.settings.data_dir / "restore-points" / response.json()["rollback_point"]
    assert (point / "inventory.sqlite3").stat().st_mode & 0o777 == 0o600
    assert point.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ConflictError): store.save_inventory_notes("stale", 2)
    assert client.post("/api/backups/restore/commit", json={"preview_id": report["preview_id"], "confirmed": True}).status_code == 409


def test_configuration_restored_and_reloaded_without_hardware_commands(station, tmp_path):
    app, client = station
    client.put("/api/configuration/network", json={"mode": "full"})
    client.put("/api/configuration/mcp", json={"enabled": True, "revision": 0})
    manager = app.state.backups
    schedule(manager, tmp_path)
    content = get_backup(client, "configuration")
    client.put("/api/configuration/network", json={"mode": "inventory"})
    client.put("/api/configuration/mcp", json={"enabled": False, "revision": 1})
    report = preview(client, content)
    result = client.post("/api/backups/restore/commit", json={"preview_id": report["preview_id"], "confirmed": True})
    assert result.status_code == 200, result.text
    assert app.state.network.mode == "full" and app.state.mcp_configuration.enabled
    assert app.state.mcp_configuration.revision > 2
    assert not manager.configuration["enabled"] and manager.key_path.exists()
    assert client.get("/api/status").json()["network"]["mode"] == "full"


@pytest.mark.parametrize("mutation", ["mode", "table", "column", "counter", "notes", "path", "config", "schema", "missing", "snapshot"])
def test_invalid_or_hostile_data_never_modifies_current_state(station, mutation):
    app, client = station
    app.state.store.create_packaged(MAIN, {})
    record = decrypt(get_backup(client), PASSWORD)
    original = app.state.backups.fingerprint()
    tables = record["inventory"]["tables"]
    if mutation == "mode": record["mode"] = "hardware"
    if mutation == "table": tables['spools; DROP TABLE favorites'] = tables.pop("spools")
    if mutation == "column": tables["spools"]["columns"][0] = "bad"
    if mutation == "counter":
        row = next(r for r in tables["metadata"]["rows"] if r[0] == "next_spool_number"); row[1] = "-1"
    if mutation == "notes": tables["inventory_notes"]["rows"][0][1] = "a" * 16001
    if mutation == "path": record["nfc_backups"]["../../outside.bin"] = "YQ=="
    if mutation == "config": record["configuration"]["../../evil.json"] = {}
    if mutation == "schema": record["inventory"]["schema"] = 99
    if mutation == "missing": del record["inventory"]
    if mutation == "snapshot": tables["spools"]["rows"][0][tables["spools"]["columns"].index("snapshot")] = '"not an object"'
    response = client.post("/api/backups/restore/preview", json={"content": base64.b64encode(encrypt(record, PASSWORD)).decode(), "password": PASSWORD})
    assert response.status_code == 422, response.text
    assert app.state.backups.fingerprint() == original


def test_changed_data_busy_hardware_gate_and_power_block_restore(station):
    app, client = station
    app.state.store.create_packaged(MAIN, {})
    content = get_backup(client)
    report = preview(client, content)
    app.state.store.save_inventory_notes("Change ailleurs", 0)
    assert client.post("/api/backups/restore/commit", json={"preview_id": report["preview_id"], "confirmed": True}).status_code == 409
    app.state.backups.busy = lambda: True
    assert client.post("/api/backups/download", json={"scope": "all", "password": PASSWORD}).status_code == 409
    app.state.backups.busy = lambda: False
    app.state.maintenance.enter()
    assert client.post("/api/backups/download", json={"scope": "all", "password": PASSWORD}).status_code == 409
    app.state.maintenance.leave()
    with app.state.maintenance.hold(requests=0):
        assert client.get("/api/status").status_code == 503
    app.state.station_power.phase = "requested"
    assert client.post("/api/backups/download", json={"scope": "all", "password": PASSWORD}).status_code == 503


def test_failed_restore_rolls_back_database_and_configuration(station):
    app, client = station
    content = get_backup(client)
    app.state.store.create_packaged(MAIN, {})
    app.state.store.save_inventory_notes("Avant échec", 0)
    report = preview(client, content)
    previous = app.state.backups.fingerprint()
    reload = app.state.backups.reload_configuration
    calls = []
    def fail_once():
        calls.append(1)
        if len(calls) == 1: raise OSError("Injected failure")
        reload()
    app.state.backups.reload_configuration = fail_once
    result = client.post("/api/backups/restore/commit", json={"preview_id": report["preview_id"], "confirmed": True})
    assert result.status_code == 503 and len(calls) == 2
    assert app.state.backups.fingerprint() == previous
    assert not (app.state.settings.data_dir / "restore-pending.json").exists()


def test_restart_recovers_interrupted_restore_before_opening_database(station):
    app, client = station; manager = app.state.backups
    store = app.state.store
    store.create_packaged(MAIN, {})
    point_id = "a" * 32
    point = manager.directory / "restore-points" / point_id
    point.mkdir(parents=True)
    database_copy(store.path, point / "inventory.sqlite3")
    private_json(point / "files.json", {"mcp-settings.json": False})
    private_json(manager.directory / "restore-pending.json", {"point": point_id, "inventory": True, "nfc_added": []})
    store.create_packaged(MAIN, {})
    private_json(manager.directory / "mcp-settings.json", {"version": 1, "revision": 4, "enabled": True})
    recovered = create_app(app.state.settings)
    assert len(recovered.state.store.list_spools()) == 1
    assert not recovered.state.mcp_configuration.enabled
    assert not (manager.directory / "restore-pending.json").exists()


def test_access_limits_origin_json_and_actual_body_size(station):
    app, client = station
    payload = {"scope": "all", "password": PASSWORD}
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        assert remote.get("/api/configuration/backups").status_code == 403
        assert remote.post("/api/backups/download", json=payload).status_code == 403
        client.put("/api/configuration/network", json={"mode": "full"})
        assert remote.post("/api/backups/download", json=payload).status_code == 200
        client.put("/api/configuration/network", json={"mode": "disabled"})
        assert remote.post("/api/backups/download", json=payload).status_code == 403
    assert client.post("/api/backups/download", json=payload, headers={"Origin": "http://evil.invalid"}).status_code == 403
    assert client.post("/api/backups/download", content=json.dumps(payload), headers={"Content-Type": "text/plain"}).status_code == 415
    chunks = (b"x" * 1_000_000 for _ in range(7))
    assert client.post("/api/library/import/preview", content=chunks, headers={"Content-Type": "application/json"}).status_code == 413


def test_schedule_persists_key_is_private_and_passphrase_not_stored(station, tmp_path):
    app, client = station; manager = app.state.backups
    mount, volumes = schedule(manager, tmp_path)
    assert manager.configuration["enabled"]
    assert manager.key_path.stat().st_mode & 0o777 == 0o600
    assert PASSWORD not in manager.key_path.read_text() and PASSWORD not in manager.path.read_text()
    manager.gate.enter()
    result = manager.run()
    manager.gate.leave()
    assert result["last_result"]["status"] == "success"
    files = list((mount / "opt-backups").glob("*.optbak"))
    assert len(files) == 1
    record = decrypt(files[0].read_bytes(), PASSWORD)
    assert record["scope"] == "all" and "backup-key.json" not in record["configuration"]
    fresh = BackupManager(app.state.settings, app.state.store, MaintenanceGate(), volumes=lambda: volumes)
    assert fresh.snapshot()["password_saved"] and fresh.state["status"] == "success"


@pytest.mark.parametrize("failure", ["absent", "readonly", "different", "symlink"])
def test_no_backup_on_root_fallback_if_mount_is_not_available(station, tmp_path, failure):
    app, client = station; manager = app.state.backups
    mount, volumes = schedule(manager, tmp_path)
    if failure == "absent": volumes.clear()
    if failure == "readonly": volumes[0]["writable"] = False
    if failure == "different": volumes[0]["source"] = "/dev/other"
    if failure == "symlink": (mount / "opt-backups").symlink_to(tmp_path / "data", target_is_directory=True)
    manager.gate.enter()
    with pytest.raises(BackupError): manager.run()
    manager.gate.leave()
    assert not list(mount.rglob("*.optbak"))
    assert manager.state["status"] == "failed"
    assert not (mount / "opt-backups").exists() or failure == "symlink"


def test_schedule_daily_weekly_missed_run_retry_and_retention(station, tmp_path):
    app, client = station; manager = app.state.backups
    clock = [datetime(2026, 10, 26, 0, 30, tzinfo=timezone.utc)]  # 01:30 Paris after DST.
    manager.utcnow = lambda: clock[0]
    mount, volumes = schedule(manager, tmp_path, time="02:00", keep=2)
    assert manager.next_run() == "2026-10-26T01:00:00+00:00"
    manager.tick(); assert not list((mount / "opt-backups").glob("*.optbak"))
    clock[0] += timedelta(hours=1)
    manager.tick(); assert manager.state["status"] == "success"
    manager.tick(); assert len(list((mount / "opt-backups").glob("*.optbak"))) == 1
    unrelated = mount / "opt-backups/opt-station-unrelated.optbak"; unrelated.write_bytes(b"Keep me")
    for _ in range(3): clock[0] += timedelta(days=1); manager.tick()
    assert len(list((mount / "opt-backups").glob("*.optbak"))) == 3 and unrelated.read_bytes() == b"Keep me"
    clock[0] += timedelta(days=1); volumes[0]["writable"] = False
    manager.tick(); assert manager.state["status"] == "failed"
    attempted = manager.state["attempted_at"]
    clock[0] += timedelta(minutes=2); manager.tick(); assert manager.state["attempted_at"] == attempted
    volumes[0]["writable"] = True
    clock[0] += timedelta(minutes=14); manager.tick(); assert manager.state["status"] == "success"
    schedule(manager, tmp_path, frequency="weekly", weekday=0, password=None)
    assert datetime.fromisoformat(manager.next_run()).astimezone(__import__('zoneinfo').ZoneInfo("Europe/Paris")).weekday() == 0


def test_schedule_timezone_spring_forward_and_fall_back_once_per_slot(station, tmp_path):
    app, client = station; manager = app.state.backups
    clock = [datetime(2027, 3, 27, 23, 0, tzinfo=timezone.utc)]
    manager.utcnow = lambda: clock[0]
    mount, _ = schedule(manager, tmp_path, time="02:30")
    assert manager.next_run() == "2027-03-28T01:30:00+00:00"
    clock[0] = datetime(2027, 3, 28, 1, 31, tzinfo=timezone.utc)
    manager.tick(); assert manager.state["status"] == "success"
    manager.tick(); assert len(list((mount / "opt-backups").glob("*.optbak"))) == 1


def test_nfc_files_round_trip_and_conflict_never_overwrites(station):
    app, client = station; folder = app.state.settings.data_dir / "nfc-backups"
    folder.mkdir()
    (folder / "test-123.bin").write_bytes(b"private-nfc")
    (folder / "test-123.json").write_text('{"status":"complete"}')
    content = get_backup(client, "inventory")
    (folder / "test-123.bin").unlink(); (folder / "test-123.json").unlink()
    p = preview(client, content)
    result = client.post("/api/backups/restore/commit", json={"preview_id": p["preview_id"], "confirmed": True})
    assert result.status_code == 200
    assert (folder / "test-123.bin").read_bytes() == b"private-nfc"
    (folder / "test-123.bin").write_bytes(b"different")
    p = preview(client, content)
    assert client.post("/api/backups/restore/commit", json={"preview_id": p["preview_id"], "confirmed": True}).status_code == 422
    assert (folder / "test-123.bin").read_bytes() == b"different"


def test_pinned_mount_descriptor_never_falls_back_during_copy(station, tmp_path):
    app, client = station; manager = app.state.backups
    mount, _ = schedule(manager, tmp_path)
    with manager._open_destination() as descriptor:
        detached = tmp_path / "detached"
        mount.rename(detached)
        mount.mkdir()  # Simulate the now-visible directory on the system disk.
        prefix = "opt-station-" + manager.configuration["station_id"][:8] + "-simulation-"
        name = prefix + "20261026T010000Z-aaaaaaaa.optbak"
        manager._write_on_volume(descriptor, name, b"encrypted test payload", prefix)
    assert not list(mount.iterdir())
    assert (detached / "opt-backups" / name).read_bytes() == b"encrypted test payload"


def test_mount_replaced_before_open_is_refused(station, tmp_path):
    app, client = station; manager = app.state.backups
    mount, volumes = schedule(manager, tmp_path)
    volumes[0]["device"] = "999:999"
    with pytest.raises(BackupError):
        with manager._open_destination():
            pytest.fail("Must not open a replaced mount")
    assert not (mount / "opt-backups").exists()


def test_local_restore_point_can_be_previewed_and_restored_without_recycling_numbers(station):
    app, client = station; store = app.state.store
    first = store.create_packaged(MAIN, {})
    content = get_backup(client)
    store.create_packaged(MAIN, {})
    p = preview(client, content)
    restored = client.post('/api/backups/restore/commit', json={'preview_id':p['preview_id'],'confirmed':True}).json()
    point = restored['rollback_point']
    assert len(store.list_spools()) == 1
    store.create_packaged(MAIN, {})  # B0002, also issued after the rollback point.
    points = client.get('/api/configuration/backups').json()['restore_points']
    assert point in {x['id'] for x in points}
    response = client.post('/api/backups/points/'+point+'/preview',json={})
    assert response.status_code == 200, response.text
    assert response.json()['spools'] == 2
    result = client.post('/api/backups/restore/commit',json={'preview_id':response.json()['preview_id'],'confirmed':True})
    assert result.status_code == 200 and len(store.list_spools()) == 2
    assert store.create_packaged(MAIN,{})['spool_number'] == 'B0003'
    assert client.post('/api/backups/points/invalid/preview',json={}).status_code == 404


def test_imported_consumption_and_identity_must_match_snapshot(station):
    app, client = station
    app.state.store.create_packaged(MAIN, {'consumed_weight':100})
    record = decrypt(get_backup(client), PASSWORD)
    table = record['inventory']['tables']['spools']
    index = table['columns'].index('snapshot')
    snapshot = json.loads(table['rows'][0][index]);snapshot['remaining_weight'] = 123
    table['rows'][0][index] = json.dumps(snapshot)
    r = client.post('/api/backups/restore/preview',json={'content':base64.b64encode(encrypt(record,PASSWORD)).decode(),'password':PASSWORD})
    assert r.status_code == 422 and app.state.store.get_spool('B0000')['remaining_weight'] == 900


def test_recovery_point_date_is_immutable_when_viewed(station):
    import os
    app, client = station
    content = get_backup(client)
    p = preview(client, content)
    restored = client.post('/api/backups/restore/commit',json={'preview_id':p['preview_id'],'confirmed':True}).json()
    identifier = restored['rollback_point']
    first = app.state.backups.restore_points()[0]['created_at']
    point = app.state.settings.data_dir/'restore-points'/identifier
    os.utime(point,(1,1))  # Directory metadata can change when SQLite opens sidecars.
    assert app.state.backups.restore_points()[0]['created_at'] == first
    assert client.post('/api/backups/points/'+identifier+'/preview',json={}).json()['created_at'] == first
