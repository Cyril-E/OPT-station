import base64
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import unix_serve

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.matter import AMBIGUOUS_PRINTER
from openprinttag_app.printer import POWER_OFF_BUSY, POWER_OFF_HOT, POWER_OFF_UNAVAILABLE, PrinterError


NODE_ID = 9007199254740999
FABRIC = 9007199254741027


class Controller:
    def __init__(self, socket):
        self.socket = socket
        self.fabric = FABRIC
        self.available = True
        self.apply_command = True
        self.lose_response = False
        self.commands = []
        self.node = {
            "node_id": NODE_ID, "date_commissioned": "2026-11-07T10:00:00Z", "available": True,
            "attributes": {"0/40/3": "Prise Matter", "1/6/0": False, "2/6/0": True, "3/8/0": 127},
        }

    def handle(self, wire):
        wire.send(json.dumps({"schema_version": 14, "min_supported_schema_version": 11,
                              "compressed_fabric_id": self.fabric, "bluetooth_enabled": True}))
        try:
            for raw in wire:
                message = json.loads(raw)
                cmd, args = message["command"], message["args"]
                self.commands.append((cmd, args))
                result = {}
                if cmd in {"get_nodes", "get_node"}:
                    node = {**deepcopy(self.node), "available": self.available}
                    result = [node] if cmd == "get_nodes" else node
                if cmd == "read_attribute":
                    path = args["attribute_path"]
                    result = {path: self.node["attributes"][path]}
                if cmd == "device_command":
                    assert args["node_id"] == NODE_ID and args["cluster_id"] == 6
                    if self.apply_command:
                        self.node["attributes"][f"{args['endpoint_id']}/6/0"] = args["command_name"] == "on"
                    if self.lose_response:
                        return
                    result = None
                wire.send(json.dumps({"message_id": message["message_id"], "result": result}))
        except ConnectionClosed:
            pass


@pytest.fixture
def matter_controller():
    with TemporaryDirectory(prefix="opt-matter-", dir="/tmp") as directory:
        controller = Controller(Path(directory) / "ws.sock")
        with unix_serve(controller.handle, str(controller.socket)) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield controller
            finally:
                server.shutdown()
                thread.join(2)


@pytest.fixture
def client(tmp_path, matter_controller):
    app = create_app(Settings(tmp_path, network_enabled=True), matter_socket=matter_controller.socket)
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield client


class PrusaLink:
    def __init__(self):
        self.status = {"printer": {"state": "IDLE", "temp_nozzle": 24, "temp_bed": 23,
                                   "target_nozzle": 0, "target_bed": 0}}
        self.job = None
        self.reachable = True
        self.calls = []

    def __call__(self, url, *args):
        path = urlsplit(url).path
        self.calls.append(path)
        if not self.reachable:
            raise PrinterError("PrusaLink indisponible.")
        data = {"/api/v1/status": self.status, "/api/v1/job": self.job}.get(path, {})
        return (204, "application/json", b"") if data is None else (200, "application/json", json.dumps(data).encode())


@pytest.fixture
def prusalink(client):
    device = PrusaLink()
    client.app.state.printer_monitor.fetch = device
    settings = client.get("/api/configuration/printer").json()
    response = client.put("/api/configuration/printer", json={
        "revision": settings["revision"],
        "printer": {"enabled": True, "url": "http://192.0.2.20", "secret": "prusalink-test"},
    })
    assert response.status_code == 200, response.text
    return device


def configure(client):
    discovery = client.get("/api/matter/discovery").json()
    assert discovery["fabric"] == str(FABRIC)
    devices = [{key: value for key, value in row.items() if key != "on"} for row in discovery["devices"]]
    assert [device["endpoint"] for device in devices] == [1, 2]
    devices[0].update(name="Sèche-filament", role="accessory")
    devices[1].update(name="Prise imprimante", role="printer")
    response = client.put("/api/configuration/matter", json={
        "revision": 0, "enabled": True, "fabric": discovery["fabric"], "devices": devices,
    })
    assert response.status_code == 200, response.text
    return response.json()


def action(client, settings, endpoint, on):
    return client.post("/api/matter/command", json={"revision": settings["revision"],
                       "node_id": str(NODE_ID), "endpoint": endpoint, "on": on})


def test_controls_are_explicit_and_verify_a_real_readback(client, matter_controller):
    assert client.get("/api/matter/status").json()["enabled"] is False
    assert matter_controller.commands == []
    settings = configure(client)
    assert client.get("/api/configuration/matter").json() == settings
    assert [row["on"] for row in client.get("/api/matter/status").json()["devices"]] == [False, True]
    assert action(client, settings, 1, True).json() == {"on": True}
    calls = matter_controller.commands
    assert [name for name, _ in calls[-4:]] == ["get_node", "read_attribute", "device_command", "read_attribute"]
    assert calls[-2][1]["command_name"] == "on"
    assert action(client, settings, 1, True).json() == {"on": True}
    assert action(client, settings, 2, False).json()["detail"] == POWER_OFF_UNAVAILABLE
    assert action(client, settings, 3, False).status_code == 409
    assert sum(name == "device_command" for name, _ in calls) == 1
    assert action(client, settings, 1, False).json() == {"on": False}


@pytest.mark.parametrize("state", ["IDLE", "READY"])
def test_printer_power_off_uses_fresh_prusalink_then_verifies_the_outlet(client, matter_controller, prusalink, state):
    settings = configure(client)
    prusalink.status["printer"]["state"] = state
    preview = client.get("/api/matter/status").json()["devices"][1]
    assert preview["power_off_block_reason"] is None
    prusalink.calls.clear()

    assert action(client, settings, 2, False).json() == {"on": False}
    assert prusalink.calls == ["/api/v1/job", "/api/v1/status"]
    assert [name for name, _ in matter_controller.commands[-4:]] == [
        "get_node", "read_attribute", "device_command", "read_attribute",
    ]
    assert matter_controller.commands[-2][1]["command_name"] == "off"
    prusalink.reachable = False
    assert action(client, settings, 2, False).json() == {"on": False}
    assert action(client, settings, 2, True).json() == {"on": True}
    assert [args["command_name"] for cmd, args in matter_controller.commands if cmd == "device_command"] == ["off", "on"]


@pytest.mark.parametrize(("printer", "telemetry", "job", "reachable", "reason", "code"), [
    ({"state": "PRINTING"}, {}, None, True, POWER_OFF_BUSY, 409),
    ({"state": "PAUSED"}, {}, None, True, POWER_OFF_BUSY, 409),
    ({"state": "FINISHED"}, {}, None, True, POWER_OFF_BUSY, 409),
    ({}, {"job": {"id": 3}}, None, True, POWER_OFF_BUSY, 409),
    ({}, {"transfer": {"progress": 10}}, None, True, POWER_OFF_BUSY, 409),
    ({}, {}, {"state": "PRINTING", "id": 3}, True, POWER_OFF_BUSY, 409),
    ({}, {}, {}, True, POWER_OFF_BUSY, 409),
    ({"target_nozzle": 170}, {}, None, True, POWER_OFF_HOT, 409),
    ({"target_bed": 60}, {}, None, True, POWER_OFF_HOT, 409),
    ({"temp_nozzle": 40}, {}, None, True, POWER_OFF_HOT, 409),
    ({"temp_bed": 44}, {}, None, True, POWER_OFF_HOT, 409),
    ({"temp_bed": None}, {}, None, True, POWER_OFF_UNAVAILABLE, 503),
    ({"target_nozzle": None}, {}, None, True, POWER_OFF_UNAVAILABLE, 503),
    ({}, {}, None, False, POWER_OFF_UNAVAILABLE, 503),
])
def test_fresh_prusalink_denial_cannot_be_bypassed_by_an_idle_preview(
    client, matter_controller, prusalink, printer, telemetry, job, reachable, reason, code
):
    settings = configure(client)
    assert client.get("/api/matter/status").json()["devices"][1]["power_off_block_reason"] is None
    prusalink.status.update(telemetry)
    prusalink.status["printer"].update(printer)
    prusalink.job = job
    prusalink.reachable = reachable

    blocked = action(client, settings, 2, False)
    assert blocked.status_code == code
    assert blocked.json()["detail"] == reason
    assert not any(cmd == "device_command" for cmd, _ in matter_controller.commands)
    assert matter_controller.node["attributes"]["2/6/0"] is True


def test_only_one_outlet_can_use_the_prusalink_shutdown_check(client, matter_controller, prusalink):
    settings = configure(client)
    settings["devices"][0]["role"] = "printer"
    saved = client.put("/api/configuration/matter", json=settings).json()
    assert client.get("/api/matter/status").json()["devices"][1]["power_off_block_reason"] == AMBIGUOUS_PRINTER
    assert action(client, saved, 2, False).json()["detail"] == AMBIGUOUS_PRINTER
    assert prusalink.calls == []
    assert not any(cmd == "device_command" for cmd, _ in matter_controller.commands)


def test_changed_identity_offline_and_stale_settings_block_writes(client, matter_controller):
    settings = configure(client)
    assert action(client, {**settings, "revision": 0}, 1, True).status_code == 409
    matter_controller.available = False
    assert action(client, settings, 1, True).status_code == 503
    assert client.get("/api/matter/status").json()["devices"][0]["on"] is None
    matter_controller.available = True
    matter_controller.node["date_commissioned"] = "2026-11-08T10:00:00Z"
    assert action(client, settings, 1, True).status_code == 409
    matter_controller.fabric += 1
    assert action(client, settings, 1, True).status_code == 409
    assert not any(cmd == "device_command" for cmd, _ in matter_controller.commands)


def test_a_reused_bridge_channel_does_not_inherit_an_existing_binding(client, matter_controller):
    node = matter_controller.node
    node.update(is_bridge=True, endpoint_parents={"1": 10, "2": 10})
    node["attributes"]["10/57/18"] = "child-A"
    settings = configure(client)
    node["attributes"]["10/57/18"] = "child-B"
    assert action(client, settings, 1, True).status_code == 409
    assert not any(cmd == "device_command" for cmd, _ in matter_controller.commands)


@pytest.mark.parametrize("lost_reply", [True, False])
def test_an_unverified_command_is_never_replayed(client, matter_controller, lost_reply):
    settings = configure(client)
    matter_controller.lose_response = lost_reply
    matter_controller.apply_command = lost_reply
    response = action(client, settings, 1, True)
    assert response.status_code == 502
    assert "à vérifier" in response.json()["detail"]
    assert sum(cmd == "device_command" for cmd, _ in matter_controller.commands) == 1
    assert client.get("/api/matter/status").json()["devices"][0]["on"] is lost_reply


def test_pairing_secrets_are_sent_only_to_the_local_controller(client, matter_controller, tmp_path):
    body = {"fabric": str(FABRIC), "code": "1234-567-8901", "network_only": False,
            "wifi_ssid": "Réseau test", "wifi_password": "secret-fictif"}
    response = client.post("/api/matter/pair", json=body)
    assert response.json() == {"paired": True}
    assert matter_controller.commands == [
        ("set_wifi_credentials", {"ssid": "Réseau test", "credentials": "secret-fictif"}),
        ("commission_with_code", {"code": "12345678901", "network_only": False, "discovery_timeout_s": 45}),
    ]
    assert not (tmp_path / "matter-settings.json").exists()
    assert client.post("/api/matter/pair", json={**body, "network_only": True}).status_code == 422
    assert len(matter_controller.commands) == 2


def test_full_access_and_https_are_required_for_remote_control(tmp_path, matter_controller):
    app = create_app(Settings(tmp_path, network_enabled=True), matter_socket=matter_controller.socket)
    path = "/api/matter/discovery"
    with TestClient(app, base_url="https://testserver", client=("192.0.2.2", 1)) as remote:
        assert remote.get(path).status_code == 403
        app.state.network.set_mode("full")
        assert remote.get(path).status_code == 200
        assert remote.get("http://testserver" + path).status_code == 403
        assert remote.post("/api/matter/pair", headers={"Origin": "https://external.invalid"}, json={
            "fabric": str(FABRIC), "code": "12345678901",
        }).status_code == 403
        assert all(cmd == "get_nodes" for cmd, _ in matter_controller.commands)


def test_backup_restores_matter_selection_with_controls_disabled(client, matter_controller):
    settings = configure(client)
    calls = len(matter_controller.commands)
    backup = client.post("/api/backups/download", json={"scope": "configuration"})
    assert backup.status_code == 200
    preview = client.post("/api/backups/restore/preview", json={"content": base64.b64encode(backup.content).decode()})
    assert preview.status_code == 200, preview.text
    restored = client.post("/api/backups/restore/commit", json={"preview_id": preview.json()["preview_id"], "confirmed": True})
    assert restored.status_code == 200, restored.text
    after = client.get("/api/configuration/matter").json()
    assert after["enabled"] is False and after["devices"] == settings["devices"]
    assert client.get("/api/matter/status").json()["devices"] == []
    assert len(matter_controller.commands) == calls
