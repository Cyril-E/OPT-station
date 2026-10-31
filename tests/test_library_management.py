"""Versioned library deletion and concurrent edits must preserve physical stock."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.storage import Store, ConflictError


MAIN = {"material_class": "FFF", "material_type": "PLA", "brand_name": "Test", "empty_container_weight": 234}


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


@pytest.mark.parametrize("kind", ["favorite", "model"])
def test_delete_preserves_qr_rfid_provenance_and_persists(station, kind):
    app, client = station
    item = client.post("/api/favorites", json={"name": "Template", "main": MAIN, "kind": kind}).json()
    qr = client.post("/api/inventory/packaged", json={"main": MAIN, "aux": {}, "favorite_id": item["id"]}).json()
    tag = client.get("/api/reader/tag").json()
    rfid = client.post("/api/inventory/add", json={"expected_uid": tag["uid"], "expected_revision": tag["revision"]}).json()
    library_revision = app.state.store.library_revision()
    changed = client.put("/api/favorites/" + item["id"], json={"name": "Changed", "main": {**MAIN, "empty_container_weight": 300}, "version": 1}).json()
    assert changed["kind"] == kind and changed["version"] == 2
    assert client.request("DELETE", "/api/favorites/" + item["id"], json={"version": 1}).status_code == 409
    assert app.state.store.favorites() == [changed]
    response = client.request("DELETE", "/api/favorites/" + item["id"], json={"version": 2})
    assert response.status_code == 200 and response.json() == {"deleted": True, "id": item["id"], "kind": kind}
    assert client.get("/api/inventory/" + qr["id"]).json() == qr
    assert client.get("/api/inventory/" + rfid["id"]).json() == rfid
    persisted = Store(app.state.settings.database)
    assert persisted.favorites() == [] and persisted.library_revision() == library_revision + 2
    assert client.request("DELETE", "/api/favorites/" + item["id"], json={"version": 2}).status_code == 404
    assert persisted.library_revision() == library_revision + 2


@pytest.mark.parametrize("version", [True, "1", 0, -1, 1.5, None])
def test_delete_api_requires_positive_integer_version(station, version):
    app, client = station
    item = app.state.store.save_favorite("Template", MAIN)
    assert client.request("DELETE", "/api/favorites/" + item["id"], json={"version": version}).status_code == 422
    assert client.request("DELETE", "/api/favorites/" + item["id"], json={}).status_code == 422
    assert app.state.store.favorites() == [item]


def test_delete_obeys_inventory_access_disabled_access_and_power_boundary(station):
    app, local = station
    item = app.state.store.save_favorite("Remote", MAIN)
    with TestClient(app, client=("192.0.2.42", 1)) as remote:
        url = "/api/favorites/" + item["id"]
        local.put("/api/configuration/network", json={"mode": "disabled"})
        assert remote.request("DELETE", url, json={"version": 1}).status_code == 403
        local.put("/api/configuration/network", json={"mode": "inventory"})
        app.state.station_power.phase = "requested"
        assert remote.request("DELETE", url, json={"version": 1}).status_code == 503
        assert app.state.store.favorites() == [item]
        app.state.station_power.phase = "idle"
        assert remote.request("DELETE", url, json={"version": 1}).status_code == 200


def test_delete_checks_origin_host_and_json(station):
    app, client = station
    item = app.state.store.save_favorite("Safe", MAIN)
    url = "/api/favorites/" + item["id"]
    assert client.request("DELETE", url, json={"version": 1}, headers={"Origin": "http://evil.invalid"}).status_code == 403
    assert client.request("DELETE", url, json={"version": 1}, headers={"Host": "evil.invalid"}).status_code == 400
    assert client.request("DELETE", url, content='{"version":1}', headers={"Content-Type": "text/plain"}).status_code == 415
    assert app.state.store.favorites() == [item]


@pytest.mark.parametrize("other_operation", ["patch", "replace", "delete"])
def test_concurrent_delete_and_edit_only_one_current_version_wins(tmp_path, other_operation):
    path = tmp_path / "library.sqlite3"
    store = Store(path)
    item = store.save_favorite("Template", MAIN, kind="model")
    barrier = threading.Barrier(2)
    def change(operation):
        independent = Store(path)
        barrier.wait(timeout=5)
        try:
            if operation == "delete":
                independent.delete_favorite(item["id"], 1)
            elif operation == "replace":
                independent.save_favorite("Replaced", MAIN, item["id"], 1)
            else:
                independent.patch_template(item["id"], 1, "model", main={"density": 1.25})
            return True
        except (ConflictError, KeyError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, ["delete", other_operation]))
    assert sorted(results) == [False, True]
    assert store.library_revision() == 2
    remaining = store.favorites()
    assert remaining == [] or (len(remaining) == 1 and remaining[0]["version"] == 2)


@pytest.mark.parametrize("operation", ["patch", "delete"])
def test_failed_library_revision_rolls_back_entire_operation(tmp_path, operation):
    store = Store(tmp_path / "rollback.sqlite3")
    item = store.save_favorite("Keep", MAIN, kind="model")
    with store.connect() as db:
        db.executescript("""CREATE TRIGGER fail_library_revision BEFORE UPDATE ON metadata
            WHEN NEW.key='library_revision' BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END;""")
    with pytest.raises((sqlite3.IntegrityError, ConflictError)):
        if operation == "patch":
            store.patch_template(item["id"], 1, "model", main={"density": 1.25})
        else:
            store.delete_favorite(item["id"], 1)
    assert store.favorites() == [item] and store.library_revision() == 1
