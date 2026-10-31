import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.network import NetworkAccess, NetworkAccessError


class Camera:
    def status(self):
        return {"available": True}

    def devices(self, refresh=False):
        return {"detected": True, "model": "ov5647", "devices": [{"model": "ov5647", "index": 0}]}

    def start(self):
        return {"id": "test-camera", "active": True}

    def get(self, identifier):
        return {"id": identifier, "active": True}

    def preview(self, identifier):
        return b"test-preview"

    def cancel(self, identifier):
        return {"id": identifier, "active": False}

    def close(self):
        pass


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True, network_url="http://192.0.2.10:8765"), camera=Camera())
    with TestClient(app, client=("127.0.0.1", 1234)) as local, TestClient(app, client=("192.0.2.42", 1234)) as remote:
        yield app, local, remote


def set_mode(client, mode):
    response = client.put("/api/configuration/network", json={"mode": mode})
    assert response.status_code == 200, response.text
    return response.json()


def test_inventory_and_favorites_are_public_but_full_access_is_opt_in(station):
    app, local, remote = station
    tag = local.get("/api/reader/tag").json()
    item = local.post("/api/inventory/add", json={"expected_uid": tag["uid"], "expected_revision": tag["revision"]}).json()
    status = remote.get("/api/status").json()
    assert status["station_access"] is False and not status["local_station"]
    assert status["network"] == {"configured": True, "mode": "inventory", "enabled": False, "url": "http://192.0.2.10:8765"}
    assert remote.get("/api/inventory").json()["items"][0]["id"] == item["id"]
    assert remote.post("/api/favorites", json={"name": "Modèle réseau", "main": {"material_class": "FFF"}}).status_code == 200
    assert remote.get("/api/reader/tag").status_code == 403
    assert remote.post("/api/camera/scans", json={}).status_code == 403
    assert remote.get("/api/printer/status").status_code == 403
    assert not (app.state.settings.data_dir / "network-access.json").exists()


def test_full_access_can_be_enabled_from_the_desk_without_code_or_cookie(station):
    app, local, remote = station
    result = set_mode(remote, "full")
    assert result["enabled"] and not remote.cookies
    status = remote.get("/api/status")
    assert status.json()["station_access"] is True
    assert "set-cookie" not in status.headers
    assert remote.get("/api/reader/tag").status_code == 200
    assert remote.post("/api/camera/scans", json={}).json()["id"] == "test-camera"
    assert remote.get("/api/camera/scans/test-camera/preview").content == b"test-preview"
    assert remote.request("DELETE", "/api/camera/scans/test-camera", json={}).json()["active"] is False
    assert remote.get("/api/printer/status").status_code == 200
    assert remote.get("/api/configuration/printer").status_code == 200


def test_setting_applies_to_all_lan_clients_and_can_be_disabled_from_either(station):
    app, local, remote = station
    with TestClient(app, client=("192.0.2.43", 1234)) as other:
        set_mode(remote, "full")
        assert other.get("/api/reader/tag").status_code == 200
        assert not other.cookies
        set_mode(other, "inventory")
        assert remote.get("/api/reader/tag").status_code == 403
        assert other.get("/api/reader/tag").status_code == 403
        assert local.get("/api/reader/tag").status_code == 200
        remote.cookies.set("opt_station_access", "old-browser-token")
        assert remote.get("/api/reader/tag").status_code == 403
        set_mode(remote, "full")
        assert remote.get("/api/reader/tag").status_code == 200


def test_saved_full_access_survives_app_restart_without_a_browser_session(tmp_path):
    settings = Settings(tmp_path, network_enabled=True)
    app = create_app(settings, camera=Camera())
    with TestClient(app, client=("192.0.2.42", 1234)) as first:
        set_mode(first, "full")
        assert first.get("/api/printer/status").status_code == 200
    restarted = create_app(settings, camera=Camera())
    with TestClient(restarted, client=("192.0.2.99", 1234)) as fresh_browser:
        assert not fresh_browser.cookies
        assert fresh_browser.get("/api/status").json()["station_access"] is True
        assert fresh_browser.get("/api/reader/tag").status_code == 200
        assert fresh_browser.get("/api/printer/status").status_code == 200
    assert json.loads((tmp_path / "network-settings.json").read_text()) == {"version": 2, "mode": "full"}
    assert (tmp_path / "network-settings.json").stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "network-access.json").exists()


def test_full_remote_write_remains_explicit_verified_and_separate_from_stock(station):
    app, local, remote = station
    set_mode(remote, "full")
    remote.post("/api/simulator/blank", json={}).raise_for_status()
    tag = remote.get("/api/reader/tag").json()
    proposal = remote.post("/api/reader/prepare", json={"expected_uid": tag["uid"], "expected_revision": tag["revision"], "mode": "create", "main": {"material_class": "FFF", "brand_name": "Essai réseau"}})
    assert proposal.status_code == 200
    assert local.get("/api/reader/tag").json()["blank"] is True
    result = remote.post("/api/reader/write", json={"preview_id": proposal.json()["preview_id"]})
    assert result.status_code == 200 and result.json()["verified"]
    observed = local.get("/api/reader/tag").json()
    assert observed["main"]["brand_name"] == "Essai réseau"
    assert observed["revision"] == result.json()["tag"]["revision"]
    assert observed["remaining_weight"] is None
    assert remote.get("/api/inventory").json()["items"] == []


def test_disabling_full_access_denies_prepared_writes_without_touching_the_tag(station):
    app, local, remote = station
    set_mode(remote, "full")
    tag = remote.get("/api/reader/tag").json()
    proposal = remote.post("/api/reader/prepare", json={"expected_uid": tag["uid"], "expected_revision": tag["revision"], "mode": "update", "aux": {"consumed_weight": 170}}).json()
    set_mode(remote, "inventory")
    assert remote.post("/api/reader/write", json={"preview_id": proposal["preview_id"]}).status_code == 403
    assert local.get("/api/reader/tag").json()["revision"] == tag["revision"]
    assert remote.get("/api/inventory").status_code == 200


def test_network_settings_keep_same_origin_json_and_host_boundaries(station):
    app, local, remote = station
    assert remote.put("/api/configuration/network", json={"mode": "full"}, headers={"Origin": "http://other.invalid"}).status_code == 403
    assert remote.put("/api/configuration/network", content='{"mode":"full"}').status_code == 415
    assert remote.put("/api/configuration/network", json={"mode": "anything"}).status_code == 422
    assert remote.put("/api/configuration/network", json={"mode": "full"}, headers={"Host": "other.invalid"}).status_code == 400
    assert remote.get("/api/reader/tag", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    response = remote.put("/api/configuration/network", json={"mode": "full"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert app.state.network.mode == "full"


def test_disabled_data_can_be_reenabled_from_configuration_without_visiting_the_pi(station):
    app, local, remote = station
    favorite = remote.post("/api/favorites", json={"name": "Conservé", "main": {}}).json()
    set_mode(remote, "full")
    set_mode(remote, "disabled")
    assert not remote.get("/api/status").json()["station_access"]
    for path in ("/api/inventory", "/api/favorites", "/api/reader/tag", "/api/schema", "/api/configuration/printer", "/api/printer/status"):
        denied = remote.get(path)
        assert denied.status_code == 403, path
        assert denied.headers["cache-control"] == "no-store"
    assert remote.post("/api/favorites", json={"name": "Interdit", "main": {}}).status_code == 403
    assert remote.get("/").status_code == 200
    assert remote.get("/static/theme.js").status_code == 200
    assert remote.get("/api/configuration").status_code == 200
    assert local.get("/api/reader/tag").status_code == 200
    set_mode(remote, "inventory")
    assert remote.get("/api/favorites").json()["items"][0]["id"] == favorite["id"]
    set_mode(remote, "full")
    assert remote.get("/api/reader/tag").status_code == 200


@pytest.mark.parametrize("mode", ["disabled", "inventory", "full"])
def test_choices_are_persistent_and_failed_saves_preserve_the_current_policy(tmp_path, monkeypatch, mode):
    access = NetworkAccess(tmp_path, True)
    access.set_mode(mode)
    restarted = NetworkAccess(tmp_path, True)
    assert restarted.mode == mode and restarted.enabled == (mode == "full")
    before = access.settings_path.read_bytes()
    def unavailable(*args):
        raise OSError("full disk")
    monkeypatch.setattr(restarted, "_save_json", unavailable)
    with pytest.raises(OSError):
        restarted.set_mode("inventory" if mode != "inventory" else "full")
    assert restarted.mode == mode and access.settings_path.read_bytes() == before


@pytest.mark.parametrize("version,mode,expected", [(1, "full", "inventory"), (1, "inventory", "inventory"), (1, "disabled", "disabled"), (2, "full", "full")])
def test_legacy_coded_mode_needs_an_explicit_choice_before_becoming_open(tmp_path, version, mode, expected):
    path = tmp_path / "network-settings.json"
    path.write_text(json.dumps({"version": version, "mode": mode}))
    access = NetworkAccess(tmp_path, True)
    assert access.mode == expected
    assert json.loads(path.read_text())["version"] == version
    access.set_mode("full")
    assert NetworkAccess(tmp_path, True).enabled
    assert json.loads(path.read_text()) == {"version": 2, "mode": "full"}


@pytest.mark.parametrize("record", [{"version": 3, "mode": "full"}, {"version": True, "mode": "full"}, {"version": 2, "mode": "invalid"}, {"version": 2, "mode": []}])
def test_invalid_settings_are_not_silently_replaced(tmp_path, record):
    path = tmp_path / "network-settings.json"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="configuration des accès distants"):
        NetworkAccess(tmp_path, True)
    assert json.loads(path.read_text()) == record


def test_retired_code_file_is_unused_and_never_replaced(tmp_path):
    path = tmp_path / "network-access.json"
    path.write_text('legacy private contents')
    access = NetworkAccess(tmp_path, True)
    access.set_mode("full")
    assert access.enabled and path.read_text() == 'legacy private contents'


def test_no_stored_choice_can_enable_hardware_without_the_lan_server_flag(tmp_path):
    access = NetworkAccess(tmp_path, False)
    with pytest.raises(NetworkAccessError) as error:
        access.set_mode("full")
    assert error.value.status_code == 409
    assert not access.settings_path.exists()
    NetworkAccess(tmp_path, True).set_mode("full")
    app = create_app(Settings(tmp_path, network_enabled=False), camera=Camera())
    with TestClient(app, client=("192.0.2.42", 1234)) as remote:
        assert remote.get("/api/reader/tag").status_code == 403
        assert remote.put("/api/configuration/network", json={"mode": "full"}).status_code == 409


def test_public_configuration_identifies_hardware_without_connection_secrets(station):
    app, local, remote = station
    result = remote.get("/api/configuration")
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json()["camera"]["model"] == "ov5647"
    assert result.json()["reader"]["simulated"]
    assert set(result.json()["network"]) == {"configured", "mode", "enabled", "url"}


def test_code_dialogs_and_session_endpoints_are_removed(station):
    app, local, remote = station
    page = remote.get("/").text
    assert 'id="network-login-dialog"' not in page and 'id="network-code-dialog"' not in page
    assert "Accès complet sans code" in page
    for method, path in (("GET", "/api/network/code"), ("POST", "/api/network/code/renew"), ("POST", "/api/network/login"), ("POST", "/api/network/logout")):
        assert remote.request(method, path, **({"json": {}} if method == "POST" else {})).status_code == 404


def test_network_change_during_authorized_write_keeps_verification_running(station, monkeypatch):
    app, local, remote = station
    set_mode(remote, "full")
    tag = remote.get("/api/reader/tag").json()
    proposal = remote.post("/api/reader/prepare", json={"expected_uid": tag["uid"], "expected_revision": tag["revision"], "mode": "update", "aux": {"consumed_weight": 321}}).json()
    started, release = threading.Event(), threading.Event()
    original_write = app.state.reader.write
    def blocked_write(image):
        started.set()
        assert release.wait(5)
        original_write(image)
    monkeypatch.setattr(app.state.reader, "write", blocked_write)
    with ThreadPoolExecutor(max_workers=1) as executor:
        writing = executor.submit(remote.post, "/api/reader/write", json={"preview_id": proposal["preview_id"]})
        try:
            assert started.wait(5)
            set_mode(local, "disabled")
        finally:
            release.set()
        result = writing.result(timeout=5)
    assert result.status_code == 200 and result.json()["verified"] is True
    assert local.get("/api/reader/tag").json()["aux"]["consumed_weight"] == 321
    assert remote.get("/api/reader/tag").status_code == 403
    assert local.get("/api/operations").json()["items"][0]["status"] == "complete"


def test_failed_save_returns_an_actionable_error_without_changing_access(station, monkeypatch):
    app, local, remote = station
    set_mode(remote, "full")
    def unavailable(*args):
        raise OSError("full disk")
    monkeypatch.setattr(app.state.network, "_save_json", unavailable)
    response = remote.put("/api/configuration/network", json={"mode": "disabled"})
    assert response.status_code == 503 and "conservés" in response.json()["detail"]
    assert app.state.network.mode == "full"
    assert remote.get("/api/reader/tag").status_code == 200


@pytest.mark.parametrize("lan,host", [(False, "127.0.0.1"), (True, "0.0.0.0")])
def test_cli_lan_listens_directly_and_keeps_explicit_allowed_address(monkeypatch, lan, host):
    from openprinttag_app.__main__ import main
    import uvicorn
    for key in ("OPENPRINTTAG_NETWORK", "OPENPRINTTAG_NETWORK_URL", "OPENPRINTTAG_MODE", "OPENPRINTTAG_ALLOWED_HOSTS"):
        monkeypatch.setenv(key, "0" if key == "OPENPRINTTAG_NETWORK" else "simulation" if key == "OPENPRINTTAG_MODE" else "")
    monkeypatch.setattr(sys, "argv", ["opt-station", "--allowed-host", "192.0.2.10", *(["--lan"] if lan else [])])
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    main()
    assert calls[0]["host"] == host and calls[0]["proxy_headers"] is False
    settings = Settings.from_env()
    assert settings.network_enabled is lan and "192.0.2.10" in settings.allowed_hosts
    if lan:
        assert settings.network_url == "http://192.0.2.10:8765"
