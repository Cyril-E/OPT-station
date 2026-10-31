from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.printer import (PrinterConfiguration, PrinterError, PrusaLinkMonitor,
                                     address, read_resource, thumbnail_path)
from openprinttag_app.printer_cameras import PrinterCameras


JPEG = b"\xff\xd8\xfftest-image"
SECRET = "test-only-secret-not-real"


def settings(configuration, cameras=0):
    record = configuration.editable()
    return {"revision": record["revision"],
            "printer": {"enabled": True, "name": "CORE One atelier", "url": "192.0.2.20", "auth": "api_key", "username": "maker", "secret": SECRET},
            "connect": {"printer_uuid": ""},
            "cameras": [{"id": f"camera{i}", "enabled": True, "name": f"Vue {i}", "url": f"rtsp://192.0.2.{30+i}/live",
                         "auth": "none", "username": "", "secret": None} for i in range(cameras)]}


class Device:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.status = {"printer": {"state": "PRINTING", "temp_nozzle": 264.5, "target_nozzle": 265, "temp_bed": 89.5, "target_bed": 90,
                                   "axis_z": 4.2, "speed": 100},
                       "job": {"id": 42, "progress": 37.5, "time_printing": 600, "time_remaining": 900}}
        self.job = {"id": 42, "file": {"display_name": "Pièce.gcode", "refs": {"thumbnail": "/thumb/l/usb/PIECE.GCO"}}}

    def __call__(self, url, auth, username, secret, **kwargs):
        self.calls.append((urlsplit(url).path, auth, username, secret))
        assert secret == SECRET
        if self.fail:
            raise PrinterError("Appareil injoignable ou délai dépassé.")
        path = urlsplit(url).path
        if path.startswith("/thumb/"):
            return 200, "image/jpeg", JPEG
        data = {"/api/version": {"firmware": "8.0.0+17068", "printertype": "CORE One"},
                "/api/v1/info": {"hostname": "core-one", "nozzle_diameter": 0.4},
                "/api/v1/status": self.status, "/api/v1/job": self.job}[path]
        return (204, "application/json", b"") if data is None else (200, "application/json", json.dumps(data).encode())


def test_private_settings_are_atomic_masked_and_preserved_after_restart(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    saved = configuration.save(settings(configuration, 2))
    assert saved["revision"] == 1 and saved["printer"]["secret_saved"]
    assert SECRET not in json.dumps(saved)
    assert configuration.path.stat().st_mode & 0o777 == 0o600
    assert PrinterConfiguration(tmp_path).record() == configuration.record()
    body = settings(configuration, 2)
    body["printer"]["secret"] = None
    configuration.save(body)
    assert configuration.record()["printer"]["secret"] == SECRET
    before = configuration.path.read_bytes()
    with pytest.raises(PrinterError, match="ont changé"):
        configuration.save(body)
    assert configuration.path.read_bytes() == before


def test_moving_to_a_different_device_never_forwards_saved_credentials(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    configuration.save(settings(configuration))
    body = settings(configuration)
    body["printer"].update(url="192.0.2.21", secret=None)
    with pytest.raises(PrinterError, match="nouveau le secret"):
        configuration.save(body)
    assert configuration.record()["printer"]["url"] == "http://192.0.2.20"
    body["printer"].update(enabled=False)
    configuration.save(body)
    assert configuration.record()["printer"]["secret"] == ""


@pytest.mark.parametrize("url", ["http://localhost/", "127.0.0.1", "http://[::1]", "http://169.254.1.1", "ftp://192.0.2.1",
                                 "http://user:password@192.0.2.20", "http://192.0.2.20/api/network/code", "http://192.0.2.20?x=y"])
def test_printer_addresses_are_device_origins_without_embedded_credentials(url):
    with pytest.raises(PrinterError):
        address(url)


def test_four_cameras_and_secret_changes_are_bounded(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    body = settings(configuration, 4)
    body["cameras"][0].update(auth="basic", username="camera", secret="camera-test-secret")
    saved = configuration.save(body)
    assert len(saved["cameras"]) == 4
    assert "camera-test-secret" not in json.dumps(saved)
    body = settings(configuration, 5)
    with pytest.raises(PrinterError, match="Quatre"):
        configuration.save(body)
    body = settings(configuration, 2)
    body["cameras"][1]["id"] = body["cameras"][0]["id"]
    with pytest.raises(PrinterError, match="dupliqué"):
        configuration.save(body)


def test_read_only_monitor_normalizes_and_shares_polling_then_preserves_stale_data(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    configuration.save(settings(configuration, 2))
    device = Device()
    stamp = [10.0]
    monitor = PrusaLinkMonitor(configuration, device, clock=lambda: stamp[0])
    result = monitor.snapshot()
    assert result["connected"] and result["read_only"] and not result["stale"]
    assert result["job"]["progress"] == 37.5
    assert result["job"]["time_remaining"] == 900
    assert result["printer"]["temp_nozzle"] == 264.5
    assert result["identity"]["firmware"] == "8.0.0+17068"
    assert len(result["cameras"]) == 2
    assert SECRET not in json.dumps(result) and "192.0.2." not in json.dumps(result)
    assert result["connect"]["inventory_sync_active"] is False
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert all(r == result for r in pool.map(lambda _: monitor.snapshot(), range(12)))
    assert len(device.calls) == 4
    stamp[0] += 5
    result = monitor.snapshot()
    assert len(device.calls) == 6  # Les informations stables ne sont pas relues.
    device.fail = True
    stamp[0] += 5
    stale = monitor.snapshot()
    assert not stale["connected"] and stale["stale"]
    assert stale["observed_at"] == result["observed_at"]
    assert stale["job"]["progress"] == 37.5
    calls = len(device.calls)
    stamp[0] += 6
    monitor.snapshot()
    assert len(device.calls) == calls  # Ralentissement après une panne.
    device.fail = False
    stamp[0] += 10
    assert monitor.snapshot()["connected"]


def test_missing_values_no_job_and_changed_job_identity_are_not_fabricated(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    configuration.save(settings(configuration))
    device = Device()
    device.status["printer"]["temp_nozzle"] = True
    device.status["job"]["progress"] = float("nan")
    result = PrusaLinkMonitor(configuration, device).snapshot()
    assert result["printer"]["temp_nozzle"] is None and result["job"]["progress"] is None
    device.job["id"] = 43
    result = PrusaLinkMonitor(configuration, device).snapshot()
    assert result["job"]["id"] == 43 and result["job"]["time_remaining"] is None
    device.job = None
    result = PrusaLinkMonitor(configuration, device).snapshot()
    assert result["connected"] and result["job"]["id"] is None
    assert result["job"]["progress"] is None and not result["job"]["thumbnail_available"]


def test_notification_metadata_reports_only_confirmed_prusalink_facts(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    configuration.save(settings(configuration))
    device = Device()
    device.status["printer"].update(state="ATTENTION", status_printer={"ok": False, "message": "Filament absent"})
    device.job["state"] = "PAUSED"
    monitor = PrusaLinkMonitor(configuration, device)
    result = monitor.snapshot()
    assert result["configuration_revision"] == 1
    assert result["printer"]["message"] == "Filament absent"
    assert result["job"]["state"] == "PAUSED" and result["job"]["consistent"]
    device.job["id"] = 43
    monitor._last_attempt = float("-inf")
    result = monitor.snapshot()
    assert result["job"]["status_id"] == 42 and result["job"]["id"] == 43
    assert result["job"]["consistent"] is False
    device.status["printer"]["status_printer"]["ok"] = True
    monitor._last_attempt = float("-inf")
    assert monitor.snapshot()["printer"]["message"] is None


def test_invalid_status_and_untrusted_thumbnail_are_rejected(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    configuration.save(settings(configuration))
    device = Device()
    device.status = None
    result = PrusaLinkMonitor(configuration, device).snapshot()
    assert not result["connected"] and "incomplète" in result["message"]
    assert thumbnail_path("https://other.invalid/steal") is None
    assert thumbnail_path("/thumb/%2e%2e/api/network/code") is None
    assert thumbnail_path("//other.invalid/image.jpg") is None
    device.status = {"printer": {"state": "IDLE"}}
    device.job["file"]["refs"]["thumbnail"] = "https://other.invalid/steal"
    monitor = PrusaLinkMonitor(configuration, device)
    assert not monitor.snapshot()["job"]["thumbnail_available"]
    with pytest.raises(PrinterError):
        monitor.thumbnail()
    assert all(not path.startswith("/steal") for path, *_ in device.calls)


def test_camera_frames_are_shared_and_removed_cameras_stop_immediately(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    configuration.save(settings(configuration, 4))
    calls = []
    def capture(camera):
        calls.append(camera["id"])
        return "image/jpeg", JPEG
    cameras = PrinterCameras(configuration, capture=capture)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: cameras.image("camera0"), range(16)))
        assert all(r == ("image/jpeg", JPEG) for r in results)
        assert calls == ["camera0"]
        body = settings(configuration, 0)
        configuration.save(body)
        with pytest.raises(PrinterError, match="absente"):
            cameras.image("camera0")
    finally:
        cameras.close()


def test_camera_change_during_capture_does_not_deliver_an_obsolete_frame(tmp_path):
    configuration = PrinterConfiguration(tmp_path)
    configuration.save(settings(configuration, 1))
    def capture(camera):
        configuration.save(settings(configuration, 0))
        return "image/jpeg", JPEG
    cameras = PrinterCameras(configuration, capture=capture)
    try:
        with pytest.raises(PrinterError, match="a changé"):
            cameras.image("camera0")
    finally:
        cameras.close()


def test_printer_routes_require_full_access_and_never_change_inventory(tmp_path):
    device = Device()
    app = create_app(Settings(tmp_path, network_enabled=True), printer_fetch=device,
                     printer_capture=lambda camera: ("image/jpeg", JPEG))
    with TestClient(app, client=("127.0.0.1", 1234)) as local, TestClient(app, client=("192.0.2.42", 1234)) as remote:
        routes = ["/api/configuration/printer", "/api/printer/status", "/api/printer/thumbnail", "/api/printer/cameras/camera0/image"]
        for route in routes:
            assert remote.get(route).status_code == 403
        body = settings(app.state.printer_configuration, 4)
        assert remote.put("/api/configuration/printer", json=body).status_code == 403
        response = local.put("/api/configuration/printer", json=body)
        assert response.status_code == 200 and SECRET not in response.text
        assert "192.0.2." not in remote.get("/api/configuration").text
        before = local.get("/api/inventory?include_removed=true").json()
        operations = local.get("/api/operations").json()
        assert remote.put("/api/configuration/network", json={"mode": "full"}).status_code == 200
        assert not remote.cookies
        for route in routes:
            response = remote.get(route)
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            assert SECRET.encode() not in response.content
        for method in ("POST", "PUT", "DELETE"):
            assert local.request(method, "/api/printer/status", json={}).status_code == 405
        assert local.post("/api/printer/job/42/pause", json={}).status_code == 404
        assert local.get("/api/inventory?include_removed=true").json() == before
        assert local.get("/api/operations").json() == operations
        remote.put("/api/configuration/network", json={"mode": "inventory"}).raise_for_status()
        assert remote.get(routes[-1]).status_code == 403
        local.put("/api/configuration/network", json={"mode": "disabled"})
        for route in routes:
            assert remote.get(route).status_code == 403
        assert local.get("/api/printer/status").status_code == 200


def test_more_than_four_camera_inputs_are_rejected_without_overwriting_settings(tmp_path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        before = app.state.printer_configuration.record()
        response = client.put("/api/configuration/printer", json=settings(app.state.printer_configuration, 5))
        assert response.status_code == 422
        assert app.state.printer_configuration.record() == before


@pytest.fixture
def http_device():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.path, dict(self.headers)))
            if self.path == "/redirect":
                self.send_response(302); self.send_header("Location", "/exfiltration"); self.end_headers(); return
            if self.path == "/digest" and not self.headers.get("Authorization", "").startswith("Digest "):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Digest realm="PrusaLink", nonce="abcdef0123456789", algorithm=MD5')
                self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"ok":true}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_http_transport_uses_get_and_digest_or_api_key_without_following_redirects(http_device):
    url, calls = http_device
    assert read_resource(url + "/api", "api_key", secret=SECRET)[0] == 200
    assert calls[-1][1]["X-Api-Key"] == SECRET
    assert read_resource(url + "/digest", "digest", "maker", SECRET)[0] == 200
    assert calls[-1][1]["Authorization"].startswith("Digest ")
    with pytest.raises(PrinterError) as failure:
        read_resource(url + "/redirect", "api_key", secret=SECRET)
    assert not any(path == "/exfiltration" for path, _ in calls)
    assert SECRET not in str(failure.value)
    with pytest.raises(PrinterError, match="volumineuse"):
        read_resource(url + "/api", limit=2)
