"""Power requests use a fake backend throughout; never stop the test host."""
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.power import BUS, LogindPower, PowerError, StationPower


class FakePower:
    def __init__(self, error=None):
        self.calls = []
        self.error = error
        self.allowed = {"poweroff": True, "reboot": True}

    def capabilities(self):
        return {"supported": True, "actions": dict(self.allowed), "message": "Droits de test autorisés."}

    def request(self, action):
        self.calls.append(action)
        if self.error:
            raise self.error


@pytest.fixture
def station(tmp_path):
    backend = FakePower()
    app = create_app(Settings(tmp_path, network_enabled=True), power_backend=backend)
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        yield app, client, backend


def prepare(client, action="reboot"):
    response = client.post("/api/system/power/prepare", json={"action": action})
    assert response.status_code == 200, response.text
    return {"action": action, "confirmation_token": response.json()["confirmation_token"]}


@pytest.mark.parametrize("action", ["poweroff", "reboot"])
def test_prepare_and_read_are_harmless_confirm_executes_once(station, action):
    app, client, backend = station
    snapshot = client.get("/api/system/power").json()
    assert snapshot["actions"] == {"poweroff": True, "reboot": True}
    assert snapshot["message"] and not snapshot["pending"]
    body = prepare(client, action)
    assert backend.calls == []  # Opening and cancelling the dialog does not call the OS.
    response = client.post("/api/system/power", json=body)
    assert response.status_code == 202 and response.json()["pending"]
    assert backend.calls == [action]
    assert client.get("/api/status").json()["power"]["phase"] == "accepted"
    assert client.post("/api/system/power", json=body).status_code == 409
    app.state.station_power.execute()
    assert backend.calls == [action]
    for path, data in [("/api/favorites", {"name": "Test", "main": {}}),
                       ("/api/reader/write", {"preview_id": "unused-token"}),
                       ("/api/labels/probe", {}),
                       ("/api/configuration/network", {"mode": "inventory"})]:
        method = client.put if path.endswith("/network") else client.post
        assert method(path, json=data).status_code == 503
    assert client.get("/api/reader/tag").status_code == 503
    assert client.get("/api/inventory").status_code == 200
    assert client.get("/api/system/power").status_code == 200


def test_confirmation_requires_matching_live_token_and_system_permission(station):
    app, client, backend = station
    assert client.post("/api/system/power", json={"action": "reboot"}).status_code == 422
    assert client.post("/api/system/power", json={"action": "reboot", "confirmation_token": "random-string"}).status_code == 409
    body = prepare(client)
    assert client.post("/api/system/power", json={**body, "action": "poweroff"}).status_code == 409
    app.state.station_power.clock = lambda: float("inf")
    assert client.post("/api/system/power", json=body).status_code == 409
    assert not backend.calls


@pytest.mark.parametrize("payload", [
    {"action": "shutdown -h now"}, {"action": "reboot; touch /tmp/injected"},
    {"action": "poweroff", "command": "reboot"}, {"action": "PowerOff"}, {},
])
def test_only_fixed_actions_accepted(station, payload):
    _, client, backend = station
    assert client.post("/api/system/power/prepare", json=payload).status_code == 422
    assert not backend.calls


def test_permission_revoked_between_prepare_and_confirm(station):
    _, client, backend = station
    body = prepare(client)
    backend.allowed["reboot"] = False
    assert client.post("/api/system/power", json=body).status_code == 503
    assert not backend.calls


@pytest.mark.parametrize("mode,expected", [("inventory", 403), ("disabled", 403), ("full", 200)])
def test_remote_access_levels_apply_to_every_power_endpoint(station, mode, expected):
    app, local, backend = station
    body = prepare(local)
    assert local.put("/api/configuration/network", json={"mode": mode}).status_code == 200
    with TestClient(app, client=("192.0.2.80", 2000)) as remote:
        assert remote.get("/api/system/power").status_code == expected
        assert remote.post("/api/system/power/prepare", json={"action": "reboot"}).status_code == expected
        assert remote.post("/api/system/power", json=body).status_code == (202 if mode == "full" else 403)
    assert backend.calls == (["reboot"] if mode == "full" else [])


def test_json_and_same_origin_are_required(station):
    _, client, backend = station
    assert client.post("/api/system/power/prepare", content='{"action":"reboot"}').status_code == 415
    assert client.post("/api/system/power/prepare", json={"action": "reboot"}, headers={"Origin": "http://elsewhere.local"}).status_code == 403
    assert not backend.calls


@pytest.mark.parametrize("busy_kind", ["request", "reader", "label", "camera"])
def test_inflight_work_blocks_prepare_and_confirmation(station, monkeypatch, busy_kind):
    app, client, backend = station
    body = prepare(client)
    controller = app.state.station_power
    if busy_kind == "request":
        controller.enter_operation()
        cleanup = controller.leave_operation
    elif busy_kind == "reader":
        app.state.reader.lock.acquire()
        cleanup = app.state.reader.lock.release
    elif busy_kind == "label":
        app.state.label_printer.lock.acquire()
        cleanup = app.state.label_printer.lock.release
    else:
        monkeypatch.setattr(app.state.camera, "is_scanning", lambda: True)
        cleanup = lambda: monkeypatch.setattr(app.state.camera, "is_scanning", lambda: False)
    try:
        assert client.post("/api/system/power/prepare", json={"action": "reboot"}).status_code == 409
        assert client.post("/api/system/power", json=body).status_code == 409
        assert not backend.calls
    finally:
        cleanup()
    assert client.post("/api/system/power", json=body).status_code == 202
    assert backend.calls == ["reboot"]


def test_controller_does_not_race_new_operations_with_power_commit():
    backend = FakePower()
    power = StationPower(backend)
    token = power.prepare("reboot")["confirmation_token"]
    barrier = threading.Barrier(2)
    results = []

    def enter():
        barrier.wait()
        try:
            power.enter_operation()
            results.append("operation")
        except PowerError:
            results.append("operation-rejected")

    thread = threading.Thread(target=enter)
    thread.start()
    barrier.wait()
    try:
        power.confirm("reboot", token)
        results.append("power")
    except PowerError:
        results.append("power-rejected")
    thread.join(2)
    assert not thread.is_alive()
    assert sorted(results) in [sorted(["operation", "power-rejected"]), sorted(["power", "operation-rejected"])]
    assert not backend.calls


def test_http_operation_must_finish_before_power_is_accepted(station):
    app, client, backend = station
    entered, release = threading.Event(), threading.Event()

    @app.post("/api/test-operation")
    def hold():
        entered.set()
        assert release.wait(5)
        return {"finished": True}

    responses = []
    thread = threading.Thread(target=lambda: responses.append(client.post("/api/test-operation", json={})))
    thread.start()
    try:
        assert entered.wait(3)
        assert app.state.station_power.operations == 1
        assert client.post("/api/system/power/prepare", json={"action": "reboot"}).status_code == 409
        assert not backend.calls
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and responses[0].status_code == 200
    assert app.state.station_power.operations == 0
    assert client.post("/api/system/power", json=prepare(client)).status_code == 202
    assert backend.calls == ["reboot"]


@pytest.mark.parametrize("error,phase,pending", [
    (PowerError("Refus du système", 503), "failed", False),
    (PowerError("Délai dépassé", 503, uncertain=True), "uncertain", True),
    (RuntimeError("unknown private error"), "uncertain", True),
])
def test_failure_is_visible_and_never_retries(station, error, phase, pending):
    app, client, backend = station
    backend.error = error
    body = prepare(client)
    assert client.post("/api/system/power", json=body).status_code == 202
    result = client.get("/api/status").json()["power"]
    assert result["phase"] == phase and result["pending"] is pending
    assert "private" not in result["message"]
    app.state.station_power.execute()
    assert backend.calls == ["reboot"]
    assert client.post("/api/favorites", json={"name": "Possible", "main": {}}).status_code == (503 if pending else 200)


def test_default_backend_never_runs_commands_outside_pi_hardware(tmp_path, monkeypatch):
    run = Mock(side_effect=AssertionError("No system calls in simulation"))
    monkeypatch.setattr("openprinttag_app.power.subprocess.run", run)
    with TestClient(create_app(Settings(tmp_path)), client=("127.0.0.1", 1234)) as client:
        assert not client.get("/api/system/power").json()["supported"]
        assert client.post("/api/system/power/prepare", json={"action": "poweroff"}).status_code == 503
    run.assert_not_called()


def test_user_can_prepare_a_new_request_after_a_definite_system_refusal(station):
    _, client, backend = station
    backend.error = PowerError("Refus du système", 503)
    assert client.post("/api/system/power", json=prepare(client)).status_code == 202
    assert client.get("/api/status").json()["power"]["phase"] == "failed"
    backend.error = None
    body = prepare(client, "poweroff")
    assert client.get("/api/status").json()["power"]["phase"] == "idle"
    assert backend.calls == ["reboot"]
    assert client.post("/api/system/power", json=body).status_code == 202
    assert backend.calls == ["reboot", "poweroff"]


def test_linux_non_pi_is_never_supported(monkeypatch):
    monkeypatch.setattr("openprinttag_app.power.sys.platform", "linux")
    monkeypatch.setattr("openprinttag_app.power.Path.read_text", lambda path: "Other computer")
    assert not LogindPower(enabled=True).supported


def logind(monkeypatch):
    monkeypatch.setattr("openprinttag_app.power.sys.platform", "linux")
    monkeypatch.setattr("openprinttag_app.power.Path.read_text", lambda path: "Raspberry Pi 5 Model B Rev 1.0\x00")
    return LogindPower(enabled=True)


@pytest.mark.parametrize("answer,allowed", [('s "yes"', True), ('s "challenge"', False), ('s "no"', False), ('s "na"', False), ('s "inhibited"', False)])
def test_capability_queries_cannot_prompt_or_execute_shutdown(monkeypatch, answer, allowed):
    backend = logind(monkeypatch)
    run = Mock(return_value=SimpleNamespace(stdout=answer))
    monkeypatch.setattr("openprinttag_app.power.subprocess.run", run)
    assert backend.capabilities()["actions"] == {"poweroff": allowed, "reboot": allowed}
    assert [call.args[0][-1] for call in run.call_args_list] == ["CanPowerOff", "CanReboot"]
    assert all("--allow-interactive-authorization=no" in call.args[0] for call in run.call_args_list)


@pytest.mark.parametrize("action,method", [("poweroff", "PowerOff"), ("reboot", "Reboot")])
def test_real_adapter_fixed_command_shape_only_with_mocked_subprocess(monkeypatch, action, method):
    backend = logind(monkeypatch)
    run = Mock()
    monkeypatch.setattr("openprinttag_app.power.subprocess.run", run)
    backend.request(action)
    run.assert_called_once_with([*BUS, method, "b", "false"], capture_output=True, text=True, timeout=8, check=True)
    with pytest.raises(PowerError):
        backend.request("anything-else")
    assert run.call_count == 1


@pytest.mark.parametrize("error,uncertain", [(subprocess.TimeoutExpired("busctl", 8), True),
                                           (subprocess.CalledProcessError(1, "busctl"), False), (FileNotFoundError(), False)])
def test_adapter_errors_are_bounded_and_translated(monkeypatch, error, uncertain):
    backend = logind(monkeypatch)
    monkeypatch.setattr("openprinttag_app.power.subprocess.run", Mock(side_effect=error))
    with pytest.raises(PowerError) as caught:
        backend.request("reboot")
    assert caught.value.status_code == 503 and caught.value.uncertain is uncertain
    result = backend.capabilities()
    assert result["actions"] == {"poweroff": False, "reboot": False} and result["message"]


def test_confirmation_tokens_are_bounded_and_expire():
    clock = [0]
    power = StationPower(FakePower(), clock=lambda: clock[0])
    first = power.prepare("reboot")["confirmation_token"]
    for _ in range(20):
        power.prepare("poweroff")
    assert len(power.tokens) == 16 and first not in power.tokens
    clock[0] = 121
    power.prepare("reboot")
    assert len(power.tokens) == 1
