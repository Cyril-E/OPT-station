"""MCP over the actual mounted SDK transport; all data and devices are temporary."""
import json
from pathlib import Path
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import spool_snapshot
from openprinttag_app.mcp_server import MCPConfiguration, MCPTransport

MAIN = {"material_class": "FFF", "brand_name": "Example", "material_type": "PETG", "material_name": "Reusable model", "nominal_netto_full_weight": 1000}
HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


def rpc(client, method, params=None):
    return client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def enable(client, value=True):
    previous = client.get("/api/configuration/mcp").json()
    response = client.put("/api/configuration/mcp", json={"enabled": value, "revision": previous["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def tool(client, name, arguments=None):
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    return result


def structured(result):
    assert not result.get("isError"), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


def rfid_spool(store, aux=None, factory=False):
    snapshot = spool_snapshot(MAIN, aux or {"consumed_weight": 100})
    if factory:
        snapshot["main"].pop("instance_uuid")
    snapshot.update(uid="E004010000001234", revision="observed-tag-revision", protections={"main": False, "aux": False},
                    unknown_fields={"main": [900], "aux": [901]}, warnings=["Unsupported tag fields retained"])
    return store.add(snapshot), snapshot


def test_mcp_is_off_by_default_and_opt_in_persists(station):
    app, client = station
    result = client.get("/api/configuration/mcp").json()
    assert result["enabled"] is False and result["endpoint"].endswith("/mcp")
    assert rpc(client, "tools/list").status_code == 404
    enabled = enable(client)
    assert enabled["revision"] == 1 and enabled["enabled"]
    assert MCPConfiguration(app.state.settings.data_dir).enabled
    assert (app.state.settings.data_dir / "mcp-settings.json").stat().st_mode & 0o777 == 0o600
    enable(client, False)
    assert rpc(client, "tools/list").status_code == 404


def test_legacy_initialize_and_exact_bounded_tool_catalog(station):
    _, client = station
    enable(client)
    response = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    assert response.status_code == 200 and response.json()["result"]["serverInfo"]["name"] == "OPT Station"
    assert "mcp-session-id" not in response.headers
    response = rpc(client, "tools/list")
    assert response.headers["cache-control"] == "no-store"
    catalog = response.json()["result"]["tools"]
    assert {item["name"] for item in catalog} == {"list_inventory", "get_spool", "update_spool", "get_inventory_notes", "get_material_schema", "list_favorites", "list_spool_models", "create_favorite", "create_spool_model", "update_favorite", "update_spool_model", "delete_favorite", "delete_spool_model"}
    for item in catalog:
        assert item["annotations"]["destructiveHint"] == item["name"].startswith(("update_", "delete_"))
        assert item["annotations"]["readOnlyHint"] == item["name"].startswith(("list_", "get_"))
        assert item["annotations"]["idempotentHint"] is True
    assert client.post("/mcp/", headers=HEADERS, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).status_code == 200


def test_inventory_queries_preserve_unknowns_and_do_not_read_hardware(station, monkeypatch):
    app, client = station
    item = client.post("/api/inventory/packaged", json={"main": MAIN, "aux": {}}).json()
    enable(client)
    monkeypatch.setattr(app.state.reader, "read", lambda: pytest.fail("MCP must never read a physical tag"))
    result = structured(tool(client, "list_inventory", {"search": "example", "limit": 1}))
    assert result["total"] == 1 and result["items"][0]["id"] == item["id"]
    assert result["items"][0]["remaining_weight"] is None and result["items"][0]["label_state"] == "qr"
    detail = structured(tool(client, "get_spool", {"identifier": item["id"]}))
    assert detail["main"] == item["main"] and detail["added_at"] == item["added_at"]
    assert tool(client, "get_spool", {"identifier": "unknown"}).get("isError")
    assert structured(tool(client, "list_inventory", {"offset": 1}))["items"] == []


def test_schema_explains_prusa_tracking_without_changing_data_or_hardware(station, monkeypatch):
    app, client = station
    item, _ = rfid_spool(app.state.store, {"consumed_weight": 123.25})
    enable(client)
    monkeypatch.setattr(app.state.reader, "read", lambda: pytest.fail("Schema must not access NFC"))
    with app.state.store.connect() as db:
        before = list(db.iterdump())
    schema = structured(tool(client, "get_material_schema"))
    requirements = schema["prusa_tracking"]
    assert requirements["required_positive"]["initial_length"] == {
        "preference": ["actual_full_length", "nominal_full_length"], "unit": "mm"}
    assert requirements["required_positive"]["initial_weight"]["unit"] == "g"
    estimation = requirements["length_estimation"]
    assert estimation["destination"] == "nominal_full_length"
    assert estimation["requires_user_authorization"] and estimation["preserve_existing_lengths"]
    assert estimation["actual_full_length_is_never_estimated"]
    assert not requirements["physical_tag_written"] and requirements["consumption"]["preserve_known_values"]
    initialized = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"}}).json()["result"]
    assert "nominal_full_length in millimetres" in initialized["instructions"]
    assert "never calculate actual_full_length" in initialized["instructions"].lower()
    assert app.state.store.get_spool(item["id"])["aux"]["consumed_weight"] == 123.25
    with app.state.store.connect() as db:
        assert list(db.iterdump()) == before


@pytest.mark.parametrize("name,kind,list_tool", [("create_favorite", "favorite", "list_favorites"), ("create_spool_model", "model", "list_spool_models")])
def test_creation_is_visible_in_ui_reusable_and_idempotent(station, name, kind, list_tool):
    _, client = station
    enable(client)
    first = structured(tool(client, name, {"name": "Example PETG", "main": MAIN}))
    assert first["created"] and first["item"]["kind"] == kind
    again = structured(tool(client, name, {"name": "example petg", "main": MAIN}))
    assert not again["created"] and again["item"]["id"] == first["item"]["id"]
    ui = client.get("/api/favorites").json()["items"]
    assert len(ui) == 1 and ui[0]["main"] == MAIN and ui[0]["kind"] == kind
    assert structured(tool(client, list_tool))["items"][0]["id"] == first["item"]["id"]
    conflict = tool(client, name, {"name": "Example PETG", "main": {**MAIN, "brand_name": "Other"}})
    assert conflict.get("isError") and client.get("/api/favorites").json()["items"] == ui
    assert client.get("/api/inventory").json()["items"] == []


def test_concurrent_retries_create_only_one_template(station):
    app, client = station
    enable(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: structured(tool(client, "create_spool_model", {"name": "Single model", "main": MAIN})), range(2)))
    assert len({item["item"]["id"] for item in results}) == 1
    assert sorted(item["created"] for item in results) == [False, True]


def test_library_updates_are_advertised_to_browser_polling(station):
    _, client = station
    enable(client)
    before = client.get("/api/status").json()["library_revision"]
    payload = {"name": "Live model", "main": MAIN}
    structured(tool(client, "create_spool_model", payload))
    assert client.get("/api/status").json()["library_revision"] == before + 1
    structured(tool(client, "create_spool_model", payload))
    assert client.get("/api/status").json()["library_revision"] == before + 1


@pytest.mark.parametrize("field,value", [("instance_uuid", "some-identity"), ("actual_netto_full_weight", 1001), ("consumed_weight", 0), ("not_a_field", "x"), ("material_type", "invented-enum")])
def test_shared_schema_validation_rejects_per_spool_or_invalid_data(station, field, value):
    _, client = station
    enable(client)
    assert tool(client, "create_spool_model", {"name": "Invalid model", "main": {**MAIN, field: value}}).get("isError")
    assert client.get("/api/favorites").json()["items"] == []
    assert structured(tool(client, "get_material_schema"))["main"]


@pytest.mark.parametrize("arguments", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"search": "a" * 201}, {"sort": "bad"}])
def test_tool_argument_limits_are_enforced(station, arguments):
    _, client = station
    enable(client)
    assert tool(client, "list_inventory", arguments).get("isError")


def test_remote_network_levels_and_disable_are_enforced_on_each_call(station):
    app, local = station
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        assert remote.get("/api/configuration/mcp").status_code == 200
        assert remote.put("/api/configuration/mcp", json={"enabled": True, "revision": 0}).status_code == 403
        enable(local)
        assert rpc(remote, "tools/list").status_code == 200
        item = structured(tool(remote, "create_favorite", {"name": "LAN template", "main": MAIN}))["item"]
        assert not item.get("uid")
        changed = structured(tool(remote, "update_favorite", {"identifier": item["id"], "version": 1, "main": {"density": 1.25}}))["item"]
        assert changed["version"] == 2
        local.put("/api/configuration/network", json={"mode": "disabled"})
        assert rpc(remote, "tools/list").status_code == 403
        assert rpc(remote, "tools/call", {"name": "delete_favorite", "arguments": {"identifier": item["id"], "version": 2}}).status_code == 403
        assert app.state.store.favorites() == [changed]
        assert rpc(local, "tools/list").status_code == 200
        assert remote.get("/api/configuration/mcp").status_code == 200
        local.put("/api/configuration/network", json={"mode": "inventory"})
        assert structured(tool(remote, "delete_favorite", {"identifier": item["id"], "version": 2}))["deleted"]
        local.put("/api/configuration/network", json={"mode": "full"})
        enable(remote, False)
        assert rpc(local, "tools/list").status_code == 404


def test_origins_hosts_and_json_are_checked(station):
    _, client = station
    enable(client)
    for method in ("GET", "POST", "DELETE"):
        response = client.request(method, "/mcp", headers={"Origin": "https://malicious.example", "Content-Type": "application/json"}, content="{}")
        assert response.status_code == 403
    assert client.post("/mcp", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/mcp", json={}, headers={"Host": "malicious.example"}).status_code == 400
    assert rpc(client, "tools/list").status_code == 200
    assert client.post("/mcp", headers={**HEADERS, "Origin": "http://testserver"}, json={"jsonrpc":"2.0","id":1,"method":"tools/list"}).status_code == 200


def test_no_hardware_private_configuration_or_shell_tools(station):
    _, client = station
    enable(client)
    for name in ("write_tag", "shutdown", "reboot", "print_label", "remove_spool", "read_credentials", "exec"):
        result = rpc(client, "tools/call", {"name": name, "arguments": {}}).json()
        assert "error" in result or result.get("result", {}).get("isError")


def test_no_mcp_changes_during_power_request(station):
    app, client = station
    enable(client)
    item = app.state.store.save_favorite("Keep", MAIN)
    app.state.station_power.phase = "requested"
    assert rpc(client, "tools/call", {"name": "create_favorite", "arguments": {"name": "Blocked", "main": MAIN}}).status_code == 503
    for name in ("update_favorite", "delete_favorite"):
        assert rpc(client, "tools/call", {"name": name, "arguments": {"identifier": item["id"], "version": 1}}).status_code == 503
    assert app.state.store.favorites() == [item]


def test_conflicting_or_failed_settings_save_preserves_previous_choice(station, monkeypatch):
    app, client = station
    enable(client)
    assert client.put("/api/configuration/mcp", json={"enabled": False, "revision": 0}).status_code == 409
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr("openprinttag_app.mcp_server.NetworkAccess._save_json", fail)
    assert client.put("/api/configuration/mcp", json={"enabled": False, "revision": 1}).status_code == 503
    assert app.state.mcp_configuration.enabled and MCPConfiguration(app.state.settings.data_dir).enabled


def test_existing_favorite_model_kind_is_preserved_by_older_clients(station):
    _, client = station
    model = client.post("/api/favorites", json={"name": "Product model", "main": MAIN, "kind": "model"}).json()
    updated = client.put("/api/favorites/" + model["id"], json={"name": "Renamed", "main": MAIN, "version": model["version"]})
    assert updated.status_code == 200 and updated.json()["kind"] == "model"


def test_old_favorite_table_is_migrated_without_losing_data(tmp_path):
    from openprinttag_app.storage import Store
    path = tmp_path / "simulation.sqlite3"
    store = Store(path)
    item = store.save_favorite("Existing", MAIN)
    with store.connect() as db:
        db.execute("ALTER TABLE favorites DROP COLUMN kind")
    migrated = Store(path).favorites()[0]
    assert migrated["id"] == item["id"] and migrated["main"] == MAIN and migrated["kind"] == "favorite"


@pytest.mark.parametrize("suffix,kind", [("favorite", "favorite"), ("spool_model", "model")])
def test_library_update_merges_preserves_and_deletes_without_changing_stock(station, suffix, kind, monkeypatch):
    app, client = station
    enable(client)
    item = structured(tool(client, "create_" + suffix, {"name": "Original", "main": {**MAIN, "empty_container_weight": 278}}))["item"]
    spool = client.post("/api/inventory/packaged", json={"main": item["main"], "aux": {}, "favorite_id": item["id"]}).json()
    before = app.state.store.library_revision()
    monkeypatch.setattr(app.state.reader, "read", lambda: pytest.fail("library operations must never read a tag"))
    result = structured(tool(client, "update_" + suffix, {"identifier": item["id"], "version": item["version"], "name": "Renamed", "main": {"density": 1.25}}))
    updated = result["item"]
    assert result["updated"] and updated["kind"] == kind and updated["version"] == item["version"] + 1
    assert updated["id"] == item["id"] and updated["name"] == "Renamed"
    assert updated["main"] == {**item["main"], "density": 1.25}
    assert app.state.store.library_revision() == before + 1
    assert tool(client, "update_" + suffix, {"identifier": item["id"], "version": item["version"], "main": {"density": 1.24}}).get("isError")
    assert tool(client, "delete_" + suffix, {"identifier": item["id"], "version": item["version"]}).get("isError")
    assert app.state.store.favorites() == [updated]
    assert structured(tool(client, "delete_" + suffix, {"identifier": item["id"], "version": updated["version"]})) == {"deleted": True, "id": item["id"], "kind": kind}
    assert app.state.store.library_revision() == before + 2
    assert tool(client, "delete_" + suffix, {"identifier": item["id"], "version": updated["version"]}).get("isError")
    assert app.state.store.library_revision() == before + 2
    assert client.get("/api/inventory/" + spool["id"]).json() == spool
    assert app.state.store.favorites() == []


def test_partial_update_clear_and_noop_do_not_erase_unmentioned_fields(station):
    app, client = station
    enable(client)
    item = structured(tool(client, "create_spool_model", {"name": "Model", "main": {**MAIN, "empty_container_weight": 234}}))["item"]
    revision = app.state.store.library_revision()
    args = {"identifier": item["id"], "version": item["version"]}
    noop = structured(tool(client, "update_spool_model", {**args, "main": {"empty_container_weight": 234}}))
    assert noop == {"updated": False, "item": item}
    assert app.state.store.library_revision() == revision
    cleared = structured(tool(client, "update_spool_model", {**args, "main": {"empty_container_weight": None}}))["item"]
    assert cleared["main"] == MAIN and "empty_container_weight" not in cleared["main"]
    assert cleared["name"] == item["name"] and cleared["kind"] == "model"


@pytest.mark.parametrize("field,value", [("instance_uuid", "x"), ("actual_netto_full_weight", 1000), ("consumed_weight", 0), ("not_a_field", None), ("material_type", "invented-enum"), ("density", -1)])
def test_invalid_updates_leave_entry_and_revision_intact(station, field, value):
    app, client = station
    enable(client)
    item = app.state.store.save_favorite("Safe", MAIN, kind="model")
    revision = app.state.store.library_revision()
    assert tool(client, "update_spool_model", {"identifier": item["id"], "version": 1, "main": {field: value}}).get("isError")
    assert app.state.store.favorites() == [item] and app.state.store.library_revision() == revision


@pytest.mark.parametrize("version", [0, -1, True, "1", 1.5, None])
def test_library_tool_versions_are_required_strict_positive_integers(station, version):
    app, client = station
    enable(client)
    item = app.state.store.save_favorite("Safe", MAIN)
    for operation in ("update_favorite", "delete_favorite"):
        assert tool(client, operation, {"identifier": item["id"], "version": version}).get("isError")
        assert tool(client, operation, {"identifier": item["id"]}).get("isError")
    assert app.state.store.favorites() == [item]


def test_wrong_kind_missing_id_and_duplicate_name_cannot_change_other_entries(station):
    app, client = station
    enable(client)
    favorite = app.state.store.save_favorite("Favorite", MAIN)
    model = app.state.store.save_favorite("Model", MAIN, kind="model")
    before = app.state.store.favorites()
    revision = app.state.store.library_revision()
    for operation in ("update_spool_model", "delete_spool_model"):
        assert tool(client, operation, {"identifier": favorite["id"], "version": 1}).get("isError")
    for operation in ("update_favorite", "delete_favorite"):
        assert tool(client, operation, {"identifier": model["id"], "version": 1}).get("isError")
        assert tool(client, operation, {"identifier": "unknown", "version": 1}).get("isError")
    for name in ("favorite", "  ", "a" * 121):
        assert tool(client, "update_spool_model", {"identifier": model["id"], "version": 1, "name": name}).get("isError")
    assert app.state.store.favorites() == before and app.state.store.library_revision() == revision


def test_spool_update_by_number_merges_known_fields_and_preserves_identity(station, monkeypatch):
    app, client = station
    item = client.post('/api/inventory/packaged', json={'main': MAIN, 'aux': {}}).json()
    enable(client)
    monkeypatch.setattr(app.state.reader, 'read', lambda: pytest.fail('No NFC read for inventory editing'))
    monkeypatch.setattr(app.state.reader, 'write', lambda *a: pytest.fail('No NFC write for inventory editing'))
    before_revision = app.state.store.inventory_revision()
    changed = structured(tool(client, 'update_spool', {'identifier': item['spool_number'], 'version': item['version'],
        'main': {'empty_container_weight': 278, 'actual_netto_full_weight': 1025},
        'aux': {'consumed_weight': 637}, 'usage_state': 'in_service'}))
    assert changed['updated'] and not changed['rfid_written']
    after = changed['item']
    assert after['main']['brand_name'] == item['main']['brand_name']
    assert after['remaining_weight'] == 388 and not after['remaining_estimated']
    assert after['usage_state'] == 'in_service'
    for field in ('id', 'instance_uuid', 'uid', 'spool_number', 'added_at', 'last_seen_at', 'label_state', 'in_stock', 'completed_at'):
        assert after[field] == item[field]
    assert after['version'] == item['version'] + 1 and app.state.store.inventory_revision() == before_revision + 1
    assert client.get('/api/inventory/' + item['id']).json() == after
    assert structured(tool(client, 'get_spool', {'identifier': item['spool_number']})) == after
    assert not after.get('rfid_sync_pending') and app.state.store.favorites() == []


def test_spool_unknowns_nulls_and_noop_do_not_invent_consumption(station):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    enable(client)
    before_revision = app.state.store.inventory_revision()
    same = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': 1}))
    assert same['updated'] is False and same['item'] == item
    assert app.state.store.inventory_revision() == before_revision
    changed = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': 1,
        'main': {'density': 1.27}}))['item']
    assert changed['remaining_weight'] is None and 'consumed_weight' not in changed['aux']
    consumed = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': changed['version'],
        'aux': {'consumed_weight': 250}}))['item']
    assert consumed['remaining_weight'] == 750
    cleared = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': consumed['version'],
        'main': {'density': None}, 'aux': {'consumed_weight': None}}))['item']
    assert 'density' not in cleared['main'] and 'consumed_weight' not in cleared['aux'] and cleared['remaining_weight'] is None


@pytest.mark.parametrize('changes', [
    {'main': {'instance_uuid': None}}, {'main': {'write_protection': 1}},
    {'main': {'material_type': 'invented'}}, {'main': {'material_class': None}},
    {'main': {'uid': 'foreign'}}, {'main': {'spool_number': 'B9999'}},
    {'aux': {'consumed_weight': -1}}, {'aux': {'consumed_weight': 1001}},
    {'main': {'actual_netto_full_weight': 0}}, {'main': {'density': True}},
    {'notes': 'Replacement without current notes revision'}, {'notes_revision': 0},
    {'usage_state': 'completed'}, {'reset_tag_overrides': 'yes'},
])
def test_invalid_spool_updates_are_atomic(station, changes):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    enable(client)
    revision = app.state.store.inventory_revision()
    result = tool(client, 'update_spool', {'identifier': item['id'], 'version': 1, **changes})
    assert result.get('isError'), result
    assert app.state.store.get_spool(item['id']) == item and app.state.store.inventory_revision() == revision


@pytest.mark.parametrize('version', [0, -1, True, 1.5, '1', 99])
def test_spool_update_rejects_invalid_or_stale_versions(station, version):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    enable(client)
    assert tool(client, 'update_spool', {'identifier': item['id'], 'version': version, 'main': {'density': 1.27}}).get('isError')
    assert app.state.store.get_spool(item['id']) == item


def test_notes_revision_guards_a_combined_spool_correction(station):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    enable(client)
    ui = client.put('/api/inventory/' + item['id'] + '/notes', json={'text': 'New UI note', 'revision': 0}).json()
    assert ui['version'] == item['version'] and ui['notes_revision'] == 1
    result = tool(client, 'update_spool', {'identifier': item['id'], 'version': 1,
        'main': {'empty_container_weight': 278}, 'notes': 'Stale MCP note', 'notes_revision': 0})
    assert result.get('isError') and app.state.store.get_spool(item['id']) == ui
    after = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': 1,
        'main': {'empty_container_weight': 278}, 'notes': 'Known empty spool: 278 g', 'notes_revision': 1}))['item']
    assert after['notes_revision'] == 2 and after['version'] == 2 and after['main']['empty_container_weight'] == 278
    same = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': 2,
        'notes': after['notes'], 'notes_revision': 2}))
    assert same['updated'] is False and same['item'] == after


def test_rfid_corrections_survive_rereads_and_reset_is_explicit(station):
    app, client = station
    item, observed = rfid_spool(app.state.store, factory=True)
    enable(client)
    changed = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': item['version'],
        'main': {'empty_container_weight': 278}, 'aux': {'consumed_weight': 200}}))['item']
    assert changed['rfid_sync_pending'] and set(changed['rfid_pending_fields']) == {'main.empty_container_weight', 'aux.consumed_weight'}
    assert changed['last_rfid_data']['aux']['consumed_weight'] == 100
    assert changed['remaining_weight'] == 800
    after = app.state.store.observe(observed)
    assert after['main'] == changed['main'] and after['aux'] == changed['aux']
    assert after['unknown_fields'] == observed['unknown_fields'] and after['protections'] == observed['protections']
    newer = {**observed, 'aux': {'consumed_weight': 300}, 'remaining_weight': 700}
    after = app.state.store.observe(newer)
    assert after['aux']['consumed_weight'] == 200 and after['last_rfid_data']['aux']['consumed_weight'] == 300
    reset = structured(tool(client, 'update_spool', {'identifier': item['spool_number'], 'version': after['version'],
        'reset_tag_overrides': True}))['item']
    assert not reset.get('rfid_sync_pending') and reset['remaining_weight'] == 700
    assert reset['main'] == observed['main'] and reset['unknown_fields'] == observed['unknown_fields']
    assert reset['uid'] == item['uid'] and reset['added_at'] == item['added_at']


def test_matching_physical_tag_acknowledges_only_matching_local_fields(station):
    app, client = station
    item, observed = rfid_spool(app.state.store)
    enable(client)
    structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': 1,
        'main': {'empty_container_weight': 278}, 'aux': {'consumed_weight': 200}}))
    partial = {**observed, 'main': {**observed['main'], 'empty_container_weight': 278}}
    after = app.state.store.observe(partial)
    assert after['rfid_pending_fields'] == ['aux.consumed_weight']
    matched = {**partial, 'aux': {'consumed_weight': 200}, 'remaining_weight': 800}
    after = app.state.store.observe(matched)
    assert not after.get('rfid_sync_pending') and after['aux']['consumed_weight'] == 200
    with app.state.store.connect() as db:
        raw = json.loads(db.execute('SELECT snapshot FROM spools WHERE id=?', (item['id'],)).fetchone()[0])
    assert 'local_edits' not in raw


def test_physical_reread_cannot_silently_replace_incompatible_local_weights(station):
    app, client = station
    item, observed = rfid_spool(app.state.store)
    enable(client)
    before = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': 1,
        'main': {'actual_netto_full_weight': 500}}))['item']
    with pytest.raises(ValueError, match='conflit'):
        app.state.store.observe({**observed, 'aux': {'consumed_weight': 600}, 'remaining_weight': 400})
    assert app.state.store.get_spool(item['id']) == before


def test_archives_keep_identity_and_counter_and_only_allow_note_edits(station):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    item = app.state.store.complete(item['id'], item['version'])
    enable(client)
    count = app.state.store.completed_count()
    assert tool(client, 'update_spool', {'identifier': item['id'], 'version': item['version'],
        'aux': {'consumed_weight': 1}}).get('isError')
    after = structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': item['version'],
        'notes': 'Archived reference', 'notes_revision': item['notes_revision']}))['item']
    assert after['completed_at'] == item['completed_at'] and not after['in_stock']
    assert app.state.store.completed_count() == count and after['notes'] == 'Archived reference'


def test_pending_rfid_association_prevents_inventory_correction(station):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    app.state.store.begin_operation('E004010000001234', 'revision', item['id'], item['version'], 'new-image')
    enable(client)
    assert tool(client, 'update_spool', {'identifier': item['id'], 'version': item['version'],
        'main': {'empty_container_weight': 278}}).get('isError')
    assert app.state.store.get_spool(item['id']) == item


def test_concurrent_spool_patches_reject_the_second_stale_version(station):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    enable(client)
    def change(value):
        return tool(client, 'update_spool', {'identifier': item['id'], 'version': 1, 'main': {'empty_container_weight': value}})
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(change, [200, 278]))
    assert sum(bool(r.get('isError')) for r in result) == 1
    after = app.state.store.get_spool(item['id'])
    assert after['version'] == 2 and after['main']['empty_container_weight'] in {200, 278}


def test_spool_update_uses_existing_lan_and_power_boundaries(station):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    enable(client)
    with TestClient(app, client=('192.0.2.42', 1)) as remote:
        after = structured(tool(remote, 'update_spool', {'identifier': item['id'], 'version': 1,
            'aux': {'consumed_weight': 250}}))['item']
        assert after['remaining_weight'] == 750
        client.put('/api/configuration/network', json={'mode': 'disabled'})
        assert rpc(remote, 'tools/call', {'name': 'update_spool', 'arguments': {'identifier': item['id'],
            'version': after['version'], 'aux': {'consumed_weight': 500}}}).status_code == 403
    app.state.station_power.phase = 'requested'
    assert rpc(client, 'tools/call', {'name': 'update_spool', 'arguments': {'identifier': item['id'],
        'version': after['version'], 'notes': 'Blocked', 'notes_revision': 0}}).status_code == 503
    assert app.state.store.get_spool(item['id']) == after


def test_pending_rfid_corrections_are_validated_in_backup_preview(station):
    from openprinttag_app.backups import decrypt, encode_backup
    app, client = station
    item, observed = rfid_spool(app.state.store)
    enable(client)
    structured(tool(client, 'update_spool', {'identifier': item['id'], 'version': 1,
        'aux': {'consumed_weight': 250}}))
    archive = client.post('/api/backups/download', json={'scope': 'inventory'}).content
    import base64
    preview = client.post('/api/backups/restore/preview', json={'content': base64.b64encode(archive).decode()})
    assert preview.status_code == 200, preview.text
    restored = client.post('/api/backups/restore/commit', json={'preview_id': preview.json()['preview_id'], 'confirmed': True})
    assert restored.status_code == 200, restored.text
    # Actual restore/reopen and another hardware observation must retain the
    # correction; this database is the temporary test fixture, never real stock.
    after = app.state.store.observe(observed)
    assert after['rfid_sync_pending'] and after['aux']['consumed_weight'] == 250
    assert after['last_rfid_data']['aux']['consumed_weight'] == 100
    record = decrypt(archive)
    table = record['inventory']['tables']['spools']
    index = table['columns'].index('snapshot')
    snapshot = json.loads(table['rows'][0][index])
    snapshot['local_edits']['aux']['consumed_weight'] = 500
    table['rows'][0][index] = json.dumps(snapshot)
    tampered = encode_backup(record)
    invalid = client.post('/api/backups/restore/preview', json={'content': base64.b64encode(tampered).decode()})
    assert invalid.status_code == 422
    assert app.state.store.get_spool(item['id'])['aux']['consumed_weight'] == 250


def test_inventory_correction_waits_for_the_active_reader_operation(station, monkeypatch):
    app, client = station
    item = app.state.store.create_packaged(MAIN, {})
    enable(client)
    entered = threading.Event()
    original = MCPTransport.__call__

    async def observe_request(self, scope, receive, send):
        entered.set()
        return await original(self, scope, receive, send)

    monkeypatch.setattr(MCPTransport, '__call__', observe_request)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with app.state.reader.lock:
            future = pool.submit(tool, client, 'update_spool', {'identifier': item['id'], 'version': 1,
                'main': {'empty_container_weight': 278}})
            assert entered.wait(timeout=2)
            with pytest.raises(FutureTimeout):
                future.result(timeout=.2)
            assert app.state.store.get_spool(item['id']) == item
        result = structured(future.result(timeout=5))
    assert result['item']['main']['empty_container_weight'] == 278
