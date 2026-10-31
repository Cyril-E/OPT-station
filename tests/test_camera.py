"""Camera lifecycle and API boundaries, without requiring a Pi on the test host."""
import os
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest
import subprocess

from openprinttag_app.app import create_app
from openprinttag_app.camera import CameraBusy, CameraScanner, RESULT_SECONDS
from openprinttag_app.config import Settings


RAW_QR = " https://prusament.com/spool/23456/abcdef0123\n"


@pytest.fixture
def scanner(tmp_path):
    worker = tmp_path / "fixture_camera.py"
    worker.write_text('''
import json, os, sys, time
from pathlib import Path
directory, mode = Path(sys.argv[1]), sys.argv[2]
(directory / "pid").write_text(str(os.getpid()))
def status(state, codes=None):
    temp = directory / "status.next"
    temp.write_text(json.dumps({"state":state,"message":state,"frames":1,"model":"ov5647","codes":codes or []}))
    temp.replace(directory / "status.json")
status("scanning")
if mode == "crash":
    raise RuntimeError("native camera failed")
if mode == "hang":
    time.sleep(30)
else:
    (directory / "preview.jpg").write_bytes(b"camera-frame")
    time.sleep(0.1)
    status("found", [{"text":" https://prusament.com/spool/23456/abcdef0123\\n","format":"QR Code"}])
''')

    class FixtureScanner(CameraScanner):
        mode = "found"

        def status(self):
            return {"enabled": True, "available": True, "message": "Prête", "scan_seconds": self.scan_seconds}

        def _command(self, directory):
            return [sys.executable, str(worker), str(directory), self.mode]

    instance = FixtureScanner(True, scan_seconds=1, hard_timeout=2)
    yield instance
    instance.close()


def finished(scanner, identifier):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = scanner.get(identifier)
        if not result["active"]:
            return result
        time.sleep(0.02)
    pytest.fail("Camera process did not finish")


def test_camera_result_preserves_text_and_discards_previous_images(scanner):
    first = scanner.start()
    first_directory = scanner._scan.directory
    result = finished(scanner, first["id"])
    assert result["state"] == "found"
    assert result["codes"][0]["text"] == RAW_QR
    assert scanner.preview(first["id"]) == b"camera-frame"
    second = scanner.start()
    assert not first_directory.exists()
    with pytest.raises(KeyError):
        scanner.get(first["id"])
    finished(scanner, second["id"])


def test_busy_camera_can_be_cancelled_and_reused(scanner):
    scanner.mode = "hang"
    first = scanner.start()
    with pytest.raises(CameraBusy):
        scanner.start()
    scanner.cancel(first["id"])
    assert finished(scanner, first["id"])["state"] == "cancelled"
    assert scanner.get(first["id"])["codes"] == []
    scanner.mode = "found"
    second = scanner.start()
    assert finished(scanner, second["id"])["state"] == "found"


def test_stuck_native_capture_is_terminated_and_api_can_retry(scanner):
    scanner.mode = "hang"
    scanner.hard_timeout = 0.35
    first = scanner.start()
    directory = scanner._scan.directory
    result = finished(scanner, first["id"])
    assert result["state"] == "error"
    assert result["codes"] == []
    pid = int((directory / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    scanner.mode = "found"
    scanner.hard_timeout = 2
    assert finished(scanner, scanner.start()["id"])["state"] == "found"


def test_capture_failure_has_a_user_message_and_no_false_result(scanner):
    scanner.mode = "crash"
    result = finished(scanner, scanner.start()["id"])
    assert result["state"] == "error"
    assert "RuntimeError" not in result["message"]
    assert result["codes"] == []


def test_expired_result_is_not_retrievable_and_files_are_removed(scanner):
    scan = scanner.start()
    finished(scanner, scan["id"])
    directory = scanner._scan.directory
    scanner._scan.finished -= RESULT_SECONDS + 1
    with pytest.raises(KeyError):
        scanner.preview(scan["id"])
    assert not directory.exists()


def test_shutdown_releases_camera_and_removes_temporary_files(scanner):
    scanner.mode = "hang"
    scanner.start()
    directory = scanner._scan.directory
    deadline = time.monotonic() + 2
    while not (directory / "pid").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    pid = int((directory / "pid").read_text())
    scanner.close()
    assert not directory.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_camera_api_requires_local_json_and_correct_browser_origin(scanner, tmp_path):
    app = create_app(Settings(tmp_path / "data"), camera=scanner)
    with TestClient(app, client=("192.0.2.50", 12345)) as remote:
        assert remote.post("/api/camera/scans", json={}).status_code == 403
        assert remote.get("/api/camera/scans/unknown").status_code == 403
        assert remote.get("/api/camera/scans/unknown/preview").status_code == 403
        assert remote.request("DELETE", "/api/camera/scans/unknown", json={}).status_code == 403
        assert scanner._scan is None
        with TestClient(app, client=("127.0.0.1", 12345)) as local:
            assert local.post("/api/camera/scans", content="{}").status_code == 415
            assert local.post("/api/camera/scans", json={}, headers={"origin": "https://other.example"}).status_code == 403
            assert scanner._scan is None


def test_camera_text_reuses_inspection_without_touching_tags_or_stock(scanner, tmp_path):
    page = '<script>var spoolData = \'{"ff_goods_id":23456,"filament":{"name":"Prusament PETG"},"weight":1025}\';</script>'
    app = create_app(Settings(tmp_path / "data"), camera=scanner, prusament_fetch=lambda url: page)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        before = client.get("/api/reader/tag").json()
        identifier = client.post("/api/camera/scans", json={}).json()["id"]
        finished(scanner, identifier)
        result = client.get(f"/api/camera/scans/{identifier}").json()
        response = client.get(f"/api/camera/scans/{identifier}/preview")
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
        report = client.post("/api/qr/inspect", json={"text": result["codes"][0]["text"]}).json()
        assert report["raw"] == RAW_QR
        assert report["kind"] == "prusament"
        assert report["main"]["actual_netto_full_weight"] == 1025
        assert client.get("/api/inventory").json()["items"] == []
        after = client.get("/api/reader/tag").json()
        assert before["revision"] == after["revision"]


def test_camera_disabled_keeps_manual_qr_available(tmp_path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.get("/api/status").json()["camera"]["available"] is False
        assert client.post("/api/camera/scans", json={}).status_code == 503
        assert client.post("/api/qr/inspect", json={"text": "8594173672666"}).json()["kind"] == "gtin"


def test_sensor_detection_is_bounded_cached_and_does_not_start_capture(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    calls = []
    def probe(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, '{"cameras":[{"model":"ov5647","index":0}]}', "")
    monkeypatch.setattr(subprocess, "run", probe)
    scanner = CameraScanner(True)
    result = scanner.devices()
    assert result["detected"] is True and result["model"] == "ov5647"
    assert scanner._scan is None
    assert scanner.devices() == result and len(calls) == 1
    scanner.devices(refresh=True)
    assert len(calls) == 2
    assert calls[0][0][-1] == "--list" and calls[0][1]["timeout"] == 5
    scanner.close()


@pytest.mark.parametrize("output", ['{"cameras":[]}', '{"cameras":"invalid"}', 'not json'])
def test_sensor_detection_does_not_invent_a_model_when_unavailable(monkeypatch, output):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, output, ""))
    scanner = CameraScanner(True)
    assert scanner.devices()["detected"] is (False if output == '{"cameras":[]}' else None)
    assert scanner.devices()["model"] is None
    scanner.close()


def test_sensor_detection_during_scan_does_not_launch_another_process(scanner, monkeypatch):
    scanner.mode = "hang"
    scanner.start()
    def forbidden(*args, **kwargs):
        pytest.fail("sensor enumeration must not run during capture")
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert "Scan en cours" in scanner.devices(refresh=True)["detection_message"]


def test_sensor_probe_timeout_keeps_configuration_available(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 5)
    monkeypatch.setattr(subprocess, "run", timed_out)
    app = create_app(Settings(tmp_path))
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        response = client.get("/api/configuration?refresh=true")
        assert response.status_code == 200
        camera = response.json()["camera"]
        assert camera["detected"] is None and camera["model"] is None
        assert "indisponible" in camera["detection_message"]
