"""MCP over the actual mounted SDK transport; all data and devices are temporary."""
import json
from pathlib import Path
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.mcp_server import MCPConfiguration

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
    assert {item["name"] for item in catalog} == {"list_inventory", "get_spool", "get_inventory_notes", "get_material_schema", "list_favorites", "list_spool_models", "create_favorite", "create_spool_model", "update_favorite", "update_spool_model", "delete_favorite", "delete_spool_model"}
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
