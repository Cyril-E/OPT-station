"""Counter replay, identity, conflicts and authorization use isolated inventories."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import time
from urllib.parse import parse_qs
from unittest.mock import Mock
import uuid

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import TagImage
from openprinttag_app.inventory_edits import validate_local_edits
from openprinttag_app.prusa_connect import (ConnectClient, ConnectConfiguration, ConnectError, ConnectMonitor,
                                           GRAPHQL_URL, TOKEN_URL, loaded_samples)
from openprinttag_app.storage import Store

ORG = "781e99f2-b7cd-4376-aef0-eaa59f36d06d"
PRINTER = "48292f88-1963-43ea-8c7e-4c368e31bc4a"
UID = "E004015023456789"
TOKEN = "test-only-connect-token"
MAIN = {"material_class": "FFF", "material_type": "PETG", "material_name": "Fixture spool",
        "nominal_netto_full_weight": 1000, "actual_netto_full_weight": 1025,
        "nominal_full_length": 335000, "empty_container_weight": 278}


def add(store, kind="qr", consumed=100):
    aux = {} if consumed is None else {"consumed_weight": consumed}
    return store.create_packaged(MAIN, aux) if kind == "qr" else store.add(TagImage.create(UID, MAIN, aux).snapshot())


def sample(item, consumed=130):
    return {"instance_uuid": item["instance_uuid"], "consumed_weight": consumed, "initial_weight": 1025,
            "printer_uuid": PRINTER, "tool_id": "1", "name": "Fixture spool", "source": "loaded"}


def configure(configuration, **changes):
    value = configuration.public()
    body = {k: v for k, v in value.items() if k not in {"version", "access_expires_at", "access_token_saved", "refresh_token_saved"}}
    body.update(enabled=True, access_token=TOKEN, organization_id=ORG, printer_uuid=PRINTER)
    body.update(changes)
    return configuration.save(body)


class Cloud:
    def __init__(self, item):
        self.calls = []
        self.fail = False
        self.warehouse = []
        self.active = True
        self.item = item
        self.consumed = 130
        self.state = "PRINTING"

    def __call__(self, url, headers, body):
        assert url == GRAPHQL_URL
        self.calls.append((url, headers, json.loads(body)))
        if self.fail:
            raise ConnectError("network", "Prusa Connect est injoignable.")
        query = json.loads(body)["query"]
        assert query.lstrip().startswith("query ") and "mutation " not in query
        if "OptStationTeams" in query:
            data = {"authorization": {"me": {"organizations": [{"id": ORG, "name": "Test team"}]}}}
        elif "OptStationPrinters" in query:
            data = {"printer": {"printers": {"__typename": "PrinterConnection",
                "pageInfo": {"hasNextPage": False, "endCursor": None}, "edges": [{"node": {
                    "id": PRINTER, "name": "Test printer", "state": self.state, "fff": {"tools": [{"id": "1", "telemetry": {"active": self.active},
                    "materialPackageInstance": {"__typename": "FFFToolMaterialPackageInstance", "uuid": self.item["instance_uuid"],
                    "isFromNfc": True, "actualNettoFullWeight": 1025, "dynamicData": {"consumedWeight": self.consumed},
                    "package": {"nominalNettoFullWeight": 1000, "material": {"name": "Fixture spool"}}}}]}}}]}}}
        else:
            data = {"warehouse": {"items": {"totalCount": len(self.warehouse), "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": self.warehouse}}}
        return 200, json.dumps({"data": data}).encode()


@pytest.mark.parametrize("kind", ["qr", "rfid"])
def test_absolute_counter_is_idempotent_and_preserves_every_other_spool_field(tmp_path, kind):
    store = Store(tmp_path / "inventory.sqlite3")
    item = add(store, kind)
    item = store.save_spool_notes(item["id"], "Actual empty spool: 278 g", 0)
    initial = deepcopy(item)
    preview = store.sync_connect_consumption(sample(item), "2026-11-01T15:00:00+00:00")
    assert preview["status"] == "ready" and store.get_spool(item["id"]) == initial
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.sync_connect_consumption(sample(item), "2026-11-01T15:00:00+00:00", apply=True), range(8)))
    assert sum(x["updated"] for x in results) == 1
    after = store.get_spool(item["id"])
    assert after["aux"]["consumed_weight"] == 130 and after["remaining_weight"] == 895
    assert after["version"] == initial["version"] + 1 and store.operations() == []
    for key in ("main", "id", "uid", "instance_uuid", "spool_number", "added_at", "last_seen_at", "notes", "notes_revision", "notes_updated_at", "usage_state", "label_state", "in_stock", "completed_at"):
        assert after[key] == initial[key], key
    if kind == "rfid":
        assert after["last_rfid_data"]["aux"]["consumed_weight"] == 100
        assert after["rfid_pending_fields"] == ["aux.consumed_weight"]
    assert after["connect_sync"]["rfid_written"] is False


@pytest.mark.parametrize("change,status", [
    ({"instance_uuid": None}, "missing_identity"), ({"instance_uuid": str(uuid.uuid4())}, "unmatched"),
    ({"consumed_weight": 99}, "older_counter"), ({"consumed_weight": None}, "invalid_counter"),
    ({"consumed_weight": True}, "invalid_counter"), ({"consumed_weight": float("nan")}, "invalid_counter"),
    ({"consumed_weight": -1}, "invalid_counter"), ({"consumed_weight": 1500}, "invalid_counter"),
    ({"initial_weight": None}, "missing_weight"), ({"initial_weight": 1000}, "weight_conflict"),
])
def test_unusable_or_older_cloud_values_cannot_modify_inventory(tmp_path, change, status):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store)
    result = store.sync_connect_consumption({**sample(item), **change}, "2026-11-01T15:00:00+00:00", apply=True)
    assert result["status"] == status and not result["updated"]
    assert store.get_spool(item["id"]) == item


def test_real_cloud_zero_can_fill_unknown_consumption_but_never_fabricates_mass(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store, consumed=None)
    assert store.sync_connect_consumption(sample(item, 0), "2026-11-01T15:00:00+00:00", apply=True)["updated"]
    assert store.get_spool(item["id"])["aux"]["consumed_weight"] == 0
    unknown = store.create_packaged({"material_class": "FFF", "material_type": "PETG"}, {})
    assert store.sync_connect_consumption(sample(unknown), "2026-11-01T15:00:00+00:00", apply=True)["status"] == "missing_weight"
    assert store.get_spool(unknown["id"]) == unknown


def test_whole_gram_loaded_telemetry_preserves_fractional_rfid_counter(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3")
    item = add(store, "rfid", consumed=899.2727661132812)
    for apply in (False, True):
        rounded = store.sync_connect_consumption(sample(item, 899), "2026-11-01T15:00:00+00:00", apply=apply)
        assert rounded["status"] == "rounded_counter" and not rounded["updated"]
        assert rounded["consumed_weight"] == 899 and rounded["local_consumed_weight"] == item["aux"]["consumed_weight"]
        assert store.get_spool(item["id"]) == item
    for remote, source in ((898, "loaded"), (899.1, "loaded"), (899, "warehouse")):
        result = store.sync_connect_consumption({**sample(item, remote), "source": source}, "2026-11-01T15:00:00+00:00", apply=True)
        assert result["status"] == "older_counter" and store.get_spool(item["id"]) == item
    assert store.sync_connect_consumption(sample(item, 900), "2026-11-01T15:01:00+00:00", apply=True)["updated"]
    assert store.get_spool(item["id"])["aux"]["consumed_weight"] == 900


@pytest.mark.parametrize("kind", ["qr", "rfid"])
def test_manual_quantity_holds_until_explicit_resume_then_tag_can_catch_up(tmp_path, kind):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store, kind)
    store.sync_connect_consumption(sample(item), "2026-11-01T15:00:00+00:00", apply=True)
    item = store.get_spool(item["id"])
    item = store.set_remaining_weight(item["id"], item["version"], 900)["item"]
    assert item["aux"]["consumed_weight"] == 125 and item["connect_sync"]["manual_hold"]
    assert store.sync_connect_consumption(sample(item, 140), "2026-11-01T15:01:00+00:00", apply=True)["status"] == "manual_override"
    item = store.resume_connect_consumption(item["id"], item["version"])
    assert item["aux"]["consumed_weight"] == 125
    assert store.sync_connect_consumption(sample(item, 140), "2026-11-01T15:02:00+00:00", apply=True)["updated"]
    if kind == "rfid":
        # The printer may have written a newer counter than the last cloud poll.
        tag = TagImage.create(UID, {**MAIN, "instance_uuid": item["instance_uuid"]}, {"consumed_weight": 145}).snapshot()
        after = store.observe(tag)
        assert after["aux"]["consumed_weight"] == 145 and not after.get("rfid_sync_pending")
        assert after["connect_sync"]["tag_caught_up"]
        # An older API response still cannot lower the newly read tag counter.
        assert store.sync_connect_consumption(sample(item, 140), "2026-11-01T15:03:00+00:00", apply=True)["status"] == "older_counter"


def test_old_physical_tag_cannot_undo_cloud_counter_or_unrelated_local_edits(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store, "rfid")
    item = store.patch_spool(item["id"], item["version"], main={"material_name": "User correction"})["item"]
    store.sync_connect_consumption(sample(item, 140), "2026-11-01T15:00:00+00:00", apply=True)
    tag = TagImage.create(UID, {**MAIN, "instance_uuid": item["instance_uuid"]}, {"consumed_weight": 130}).snapshot()
    result = store.observe(tag)
    assert result["aux"]["consumed_weight"] == 140 and result["main"]["material_name"] == "User correction"
    with store.connect() as db:
        validate_local_edits(json.loads(db.execute("SELECT snapshot FROM spools WHERE id=?", (item["id"],)).fetchone()[0]))


def test_monitor_reads_even_without_sync_and_never_replays_after_network_error(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store)
    cfg = ConnectConfiguration(tmp_path);configure(cfg)
    cloud = Cloud(item);stamp = [time.time()]
    monitor = ConnectMonitor(cfg, store, fetch=cloud, clock=lambda: stamp[0])
    preview = monitor.check(apply=True, force=True)
    assert preview["connected"] and preview["spools"][0]["status"] == "ready"
    assert store.get_spool(item["id"]) == item
    configure(cfg, sync_consumption=True)
    assert monitor.check(apply=False, force=True)["updated_count"] == 0
    assert store.get_spool(item["id"]) == item
    result = monitor.check(apply=True, force=True)
    assert result["updated_count"] == 1
    saved = store.get_spool(item["id"])
    cloud.fail = True;stamp[0] += 31
    stale = monitor.check(apply=True)
    assert not stale["connected"] and stale["stale"] and stale["updated_count"] == 0
    assert store.get_spool(item["id"]) == saved
    calls = len(cloud.calls);stamp[0] += 30;monitor.check(apply=True)
    assert len(cloud.calls) == calls


def test_warehouse_exact_uuid_matching_no_imports_duplicates_archives_or_note_edits(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store)
    cfg = ConnectConfiguration(tmp_path);configure(cfg, sync_warehouse=True)
    cloud = Cloud(item);cloud.active = False
    def row(uid, consumed=160):
        return {"id": str(uuid.uuid4()), "name": "Remote notes stay remote", "consumedWeight": consumed,
                "archived": False, "nominalNettoFullWeight": 1000,
                "materialPackageInstance": {"uuid": uid, "actualNettoFullWeight": 1025}}
    cloud.warehouse = [row(item["instance_uuid"]), row(str(uuid.uuid4()))]
    monitor = ConnectMonitor(cfg, store, fetch=cloud)
    result = monitor.check(apply=True, force=True)
    assert result["warehouse"] == {"total": 2, "matched": 1, "unmatched": 1} and result["updated_count"] == 1
    assert len(store.list_spools()) == 1 and store.get_spool(item["id"])["notes"] == ""
    saved = store.get_spool(item["id"])
    cloud.warehouse.append(row(item["instance_uuid"], 200))
    result = monitor.check(apply=True, force=True)
    assert sum(x["status"] == "duplicate" for x in result["spools"]) == 2 and result["updated_count"] == 0
    assert store.get_spool(item["id"]) == saved


def test_configuration_masks_tokens_and_refresh_rotation_does_not_conflict_with_open_form(tmp_path):
    cfg = ConnectConfiguration(tmp_path)
    saved = configure(cfg, access_token="", refresh_token="test-only-refresh")
    assert "test-only-refresh" not in json.dumps(saved) and cfg.path.stat().st_mode & 0o777 == 0o600
    calls = []
    def fetch(url, headers, body):
        calls.append(url)
        if url == TOKEN_URL:
            assert parse_qs(body.decode())["grant_type"] == ["refresh_token"]
            return 200, json.dumps({"access_token": "new-test-access", "refresh_token": "new-test-refresh", "token_type": "Bearer"}).encode()
        assert headers["Authorization"] == "Bearer new-test-access"
        return 200, b'{"data":{"ok":true}}'
    client = ConnectClient(cfg, fetch)
    assert client.query("query Test { ok }")["ok"]
    assert calls == [TOKEN_URL, GRAPHQL_URL]
    assert cfg.public()["revision"] == saved["revision"]
    body = {k: v for k, v in saved.items() if k not in {"version", "access_expires_at", "access_token_saved", "refresh_token_saved"}}
    cfg.save(body)
    assert ConnectConfiguration(tmp_path).read()["refresh_token"] == "new-test-refresh"
    with pytest.raises(ConnectError):
        client.query("mutation Unsafe { command }")


def test_warehouse_failure_does_not_stop_loaded_spool_and_settings_race_cannot_apply(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store)
    cfg = ConnectConfiguration(tmp_path);configure(cfg, sync_consumption=True, sync_warehouse=True)
    cloud = Cloud(item)
    def fetch(url, headers, body):
        if "OptStationWarehouse" in json.loads(body)["query"]:
            raise ConnectError("access", "Entrepôt indisponible.")
        return cloud(url, headers, body)
    monitor = ConnectMonitor(cfg, store, fetch=fetch)
    result = monitor.check(apply=True, force=True)
    assert result["connected"] and result["updated_count"] == 1
    assert result["warehouse"]["total"] is None and result["warehouse"]["error"]
    saved = store.get_spool(item["id"]);cloud.consumed = 200
    def raced_fetch(url, headers, body):
        if "OptStationWarehouse" in json.loads(body)["query"]:
            configure(cfg, enabled=False, sync_consumption=True)
        return cloud(url, headers, body)
    monitor.client.fetch = raced_fetch
    monitor.check(apply=True, force=True)
    assert store.get_spool(item["id"]) == saved


def test_manual_edit_before_first_cloud_read_needs_explicit_resume(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3");item = add(store)
    item = store.patch_spool(item["id"], item["version"], aux={"consumed_weight": 120})["item"]
    assert store.sync_connect_consumption(sample(item, 140), "2026-11-01T15:00:00+00:00", apply=True)["status"] == "manual_override"
    assert store.get_spool(item["id"]) == item


@pytest.mark.parametrize("response", [b'{"data":null}', b'{"errors":[{"message":"private upstream details"}]}', b'not json'])
def test_unknown_graphql_contract_does_not_expose_upstream_details(tmp_path, response):
    cfg = ConnectConfiguration(tmp_path);configure(cfg)
    client = ConnectClient(cfg, fetch=lambda *args: (200, response))
    with pytest.raises(ConnectError, match="contrat attendu") as error:
        client.query("query Test { ok }")
    assert "private upstream" not in str(error.value) and TOKEN not in str(error.value)


def test_connect_api_requires_full_access_and_never_exposes_tokens_or_calls_hardware(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path / "data", network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as local:
        item = add(app.state.store)
        cloud = Cloud(item);app.state.connect_monitor.client.fetch = cloud
        configure(app.state.connect_configuration)
        for obj, name in ((app.state.reader, "write"), (app.state.reader, "read"), (app.state.label_printer, "print")):
            monkeypatch.setattr(obj, name, Mock(side_effect=AssertionError("No hardware")))
        response = local.post("/api/printer/connect/test", json={})
        assert response.status_code == 200 and response.json()["connected"]
        assert TOKEN not in response.text and TOKEN not in local.get("/api/configuration/connect").text
        assert app.state.store.get_spool(item["id"]) == item
    # Remote inventory-only clients cannot read settings/telemetry or resume counters.
    with TestClient(app, client=("192.0.2.5", 1)) as remote:
        assert remote.get("/api/configuration/connect").status_code == 403
        assert remote.get("/api/printer/connect").status_code == 403
        assert remote.post("/api/printer/connect/test", json={}).status_code == 403


def test_backup_carries_private_access_and_provenance_but_restore_disables_connect(tmp_path):
    import base64
    cloud = None
    app = create_app(Settings(tmp_path / "data"), connect_fetch=lambda *args: cloud(*args))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        item = add(app.state.store);cloud = Cloud(item)
        configure(app.state.connect_configuration)
        app.state.store.sync_connect_consumption(sample(item), "2026-11-01T15:00:00+00:00", apply=True)
        saved = app.state.store.get_spool(item["id"])
        backup = client.post("/api/backups/download", json={"scope": "all"})
        assert backup.status_code == 200
        # A later manual correction must be replaced only by explicit restoration.
        app.state.store.set_remaining_weight(saved["id"], saved["version"], 900)
        preview = client.post("/api/backups/restore/preview", json={"content": base64.b64encode(backup.content).decode()})
        assert preview.status_code == 200, preview.text
        restored = client.post("/api/backups/restore/commit", json={"preview_id": preview.json()["preview_id"], "confirmed": True})
        assert restored.status_code == 200, restored.text
        assert app.state.store.get_spool(item["id"])["connect_sync"] == saved["connect_sync"]
        config = app.state.connect_configuration.read()
        assert config["access_token"] == TOKEN and config["enabled"] is False
        assert TOKEN not in client.get("/api/configuration/connect").text


def test_printer_upload_key_is_distinguished_from_a_web_session_token(tmp_path):
    cfg = ConnectConfiguration(tmp_path);configure(cfg, access_token="test-key-1234567")
    client = ConnectClient(cfg, fetch=lambda *args: (403, b""))
    with pytest.raises(ConnectError, match="auth.access_token") as error:
        client.teams()
    assert "test-key-1234567" not in str(error.value)


def test_real_transport_identifies_the_station_for_account_and_graphql(monkeypatch, tmp_path):
    import io
    import openprinttag_app.prusa_connect as module
    cfg = ConnectConfiguration(tmp_path);configure(cfg, access_token="", refresh_token="test-only-refresh")
    seen = []
    class Opener:
        def open(self, request, timeout):
            # Prusa Account refused the default Python client during qualification.
            assert request.get_header("User-agent").startswith("OPT-Station/")
            seen.append(request.full_url)
            value = ({"access_token": TOKEN, "refresh_token": "test-only-rotated", "token_type": "Bearer"}
                     if request.full_url == TOKEN_URL else {"data": {"authorization": {"me": {"organizations": []}}}})
            response = io.BytesIO(json.dumps(value).encode());response.status = 200
            return response
    monkeypatch.setattr(module, "build_opener", lambda *args: Opener())
    assert ConnectClient(cfg).teams() == []
    assert seen == [TOKEN_URL, GRAPHQL_URL]
    assert cfg.read()["refresh_token"] == "test-only-rotated"


def warehouse_row(instance, **changes):
    return {"id": str(uuid.uuid4()), "name": "Fixture warehouse item", "archived": False,
            "nominalNettoFullWeight": 1000, "consumedWeight": 100,
            "materialPackageInstance": {"uuid": instance, "actualNettoFullWeight": 1025}, **changes}


def test_inventory_presence_includes_loaded_spool_but_filters_unknown_archived_and_duplicate_identities(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3"); item = add(store)
    cfg = ConnectConfiguration(tmp_path); configure(cfg)
    cloud = Cloud(item); foreign = str(uuid.uuid4())
    cloud.warehouse = [warehouse_row(item["instance_uuid"]), warehouse_row(foreign)]
    monitor = ConnectMonitor(cfg, store, fetch=cloud)
    assert monitor.inventory_warehouse() == {"instances": [], "checked_at": None, "stale": False}
    monitor.check(force=True)
    calls = len(cloud.calls)
    presence = monitor.inventory_warehouse()
    assert presence["instances"] == [item["instance_uuid"]] and presence["checked_at"] and not presence["stale"]
    assert len(cloud.calls) == calls and store.get_spool(item["id"]) == item
    cloud.warehouse.append(warehouse_row(item["instance_uuid"]))
    monitor.check(force=True)
    assert monitor.inventory_warehouse()["instances"] == []
    cloud.warehouse = [warehouse_row(item["instance_uuid"], archived=True)]
    monitor.check(force=True)
    assert monitor.inventory_warehouse()["instances"] == []


def test_inventory_presence_marks_outages_and_old_observations_then_removes_deleted_or_other_organization_items(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3"); item = add(store)
    cfg = ConnectConfiguration(tmp_path); configure(cfg)
    cloud = Cloud(item); cloud.warehouse = [warehouse_row(item["instance_uuid"])]
    stamp = [time.time()]
    monitor = ConnectMonitor(cfg, store, fetch=cloud, clock=lambda: stamp[0])
    monitor.check(force=True); known = monitor.inventory_warehouse()
    stamp[0] += 61
    assert monitor.inventory_warehouse() == {**known, "stale": True}
    cloud.fail = True; monitor.check(force=True)
    assert monitor.inventory_warehouse() == {**known, "stale": True}
    cloud.fail = False; cloud.warehouse = []; monitor.check(force=True)
    assert monitor.inventory_warehouse()["instances"] == [] and not monitor.inventory_warehouse()["stale"]
    cloud.warehouse = [warehouse_row(item["instance_uuid"])]; monitor.check(force=True)
    configure(cfg, organization_id=str(uuid.uuid4()))
    assert monitor.inventory_warehouse() == {"instances": [], "checked_at": None, "stale": False}
    assert store.get_spool(item["id"]) == item


def test_inventory_presence_status_does_not_wait_for_cloud_or_credential_locks(tmp_path):
    store = Store(tmp_path / "inventory.sqlite3"); item = add(store)
    cfg = ConnectConfiguration(tmp_path); configure(cfg)
    cloud = Cloud(item); cloud.warehouse = [warehouse_row(item["instance_uuid"])]
    monitor = ConnectMonitor(cfg, store, fetch=cloud); monitor.check(force=True)
    # A status request must remain responsive while another thread is waiting
    # for the network with both of the collector's locks held.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with monitor.lock, cfg.lock:
            value = pool.submit(monitor.inventory_warehouse).result(timeout=1)
    assert value["instances"] == [item["instance_uuid"]]


def test_inventory_only_remote_status_shows_presence_without_cloud_secrets_or_foreign_stock(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("192.0.2.9", 1)) as client:
        app.state.connect_monitor.close()
        item = add(app.state.store); foreign = str(uuid.uuid4())
        cloud = Cloud(item); cloud.warehouse = [warehouse_row(item["instance_uuid"]), warehouse_row(foreign)]
        app.state.connect_monitor.client.fetch = cloud; configure(app.state.connect_configuration)
        app.state.connect_monitor.check(force=True)
        calls = len(cloud.calls)
        response = client.get("/api/status")
        assert response.status_code == 200 and not response.json()["station_access"]
        assert response.json()["connect_warehouse"]["instances"] == [item["instance_uuid"]]
        assert TOKEN not in response.text and foreign not in response.text and ORG not in response.text
        assert len(cloud.calls) == calls and app.state.store.get_spool(item["id"]) == item
    hidden = create_app(Settings(tmp_path / "disabled"))
    with TestClient(hidden, client=("192.0.2.9", 1)) as client:
        hidden.state.network.set_mode("disabled")
        assert client.get("/api/status").json()["connect_warehouse"] is None
