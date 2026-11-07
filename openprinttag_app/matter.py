"""Commandes locales et limitées du contrôleur Matter du Pi."""
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt, model_validator
from websockets.exceptions import WebSocketException
from websockets.sync.client import unix_connect

from .backups import private_json


SETTINGS_FILE = "matter-settings.json"
ON_OFF = 6
UINT64_TEXT = r"^[1-9][0-9]{0,19}$"
ON_OFF_PATH = re.compile(r"([1-9][0-9]{0,4})/6/0")
NO_CONTROLLER = "Le contrôleur Matter du Pi ne répond pas."
CHANGED = "Les appareils Matter ont changé. Actualisez la liste."
UNCERTAIN = "État Matter à vérifier. Actualisez avant de renvoyer une commande."
AMBIGUOUS_PRINTER = "Attribuez le profil Imprimante à une seule prise pour autoriser l’arrêt."


class MatterError(Exception):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


class ControllerRejection(MatterError):
    def __init__(self, reason):
        super().__init__("Le contrôleur Matter a refusé la demande.", 502)
        self.reason = reason if isinstance(reason, str) else None


class MatterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatterDevice(MatterModel):
    node_id: str = Field(pattern=UINT64_TEXT)
    endpoint: StrictInt = Field(ge=1, le=65534)
    identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    role: Literal["accessory", "printer"]


class MatterSettings(MatterModel):
    revision: StrictInt = Field(default=0, ge=0)
    enabled: StrictBool = False
    fabric: str | None = Field(default=None, pattern=UINT64_TEXT)
    devices: list[MatterDevice] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def check_bindings(self):
        if bool(self.fabric) != bool(self.devices) or len({target(row) for row in self.devices}) != len(self.devices):
            raise ValueError("Liste d’appareils Matter invalide.")
        return self

    def unique_printer_outlet(self):
        return sum(device.role == "printer" for device in self.devices) == 1


class MatterAction(MatterModel):
    revision: StrictInt = Field(ge=0)
    node_id: str = Field(pattern=UINT64_TEXT)
    endpoint: StrictInt = Field(ge=1, le=65534)
    on: StrictBool


class MatterPairing(MatterModel):
    fabric: str = Field(pattern=UINT64_TEXT)
    code: SecretStr = Field(max_length=256)
    network_only: StrictBool = True
    wifi_ssid: str | None = Field(default=None, max_length=32)
    wifi_password: SecretStr | None = Field(default=None, max_length=64)


def target(device):
    return device.node_id, device.endpoint


def socket_path():
    if override := os.environ.get("OPENPRINTTAG_MATTER_SOCKET"):
        return Path(override)
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    return runtime / "opt-station-matter.sock"


def uint64(value):
    return type(value) is int and 0 < value < 2**64


def bridged_uid(attrs, parents, endpoint):
    seen = set()
    while type(endpoint) is int and endpoint > 0 and endpoint not in seen:
        if isinstance(uid := attrs.get(f"{endpoint}/57/18"), str) and uid:
            return uid
        seen.add(endpoint)
        endpoint = parents.get(str(endpoint))
    return None


class MatterSession:
    def __init__(self, wire):
        self.wire = wire
        self.sequence = 0
        self.info = self.receive(3)
        schema = self.info.get("schema_version")
        minimum = self.info.get("min_supported_schema_version")
        fabric = self.info.get("compressed_fabric_id")
        if (type(schema) is not int or type(minimum) is not int or not minimum <= 14 <= schema
                or not uint64(fabric)):
            raise MatterError("Version du contrôleur Matter incompatible.")
        self.fabric = str(fabric)

    def receive(self, timeout):
        try:
            packet = json.loads(self.wire.recv(timeout=max(0, timeout)))
        except (WebSocketException, TimeoutError, OSError, ValueError) as exc:
            raise MatterError(NO_CONTROLLER) from exc
        if not isinstance(packet, dict):
            raise MatterError(NO_CONTROLLER)
        return packet

    def call(self, command, args=None, timeout=5):
        self.sequence += 1
        message_id = str(self.sequence)
        deadline = time.monotonic() + timeout
        try:
            self.wire.send(json.dumps({"message_id": message_id, "command": command, "args": args or {}}))
        except (WebSocketException, OSError) as exc:
            raise MatterError(NO_CONTROLLER) from exc
        while time.monotonic() < deadline:
            packet = self.receive(deadline - time.monotonic())
            if packet.get("message_id") == message_id:
                if "result" in packet and "error_code" not in packet:
                    return packet["result"]
                raise ControllerRejection(packet.get("reason"))
        raise MatterError(NO_CONTROLLER)


def endpoints(nodes):
    """Expose les canaux qui portent réellement l’attribut serveur OnOff."""
    if not isinstance(nodes, list):
        raise MatterError(NO_CONTROLLER)
    devices = {}
    for node in nodes:
        if not isinstance(node, dict) or not uint64(node.get("node_id")):
            continue
        attrs, commissioned = node.get("attributes"), node.get("date_commissioned")
        if not isinstance(attrs, dict) or not isinstance(commissioned, str) or not commissioned:
            continue
        node_id = str(node["node_id"])
        parents = node.get("endpoint_parents")
        parents = parents if isinstance(parents, dict) else {}
        for path, state in attrs.items():
            match = ON_OFF_PATH.fullmatch(path)
            if not match or type(state) is not bool or (endpoint := int(match[1])) >= 65535:
                continue
            child_uid = bridged_uid(attrs, parents, endpoint)
            if node.get("is_bridge") is True and child_uid is None:
                continue
            labels = [attrs.get(f"{endpoint}/57/5"), attrs.get(f"{endpoint}/57/3"),
                      attrs.get("0/40/5"), attrs.get("0/40/3")]
            name = next((label.strip()[:80] for label in labels if isinstance(label, str) and label.strip()), "")
            stable_ids = [child_uid, attrs.get("0/40/18"), attrs.get("0/40/15")]
            identity = hashlib.sha256(json.dumps([commissioned, *stable_ids], sort_keys=True).encode()).hexdigest()
            key = node_id, endpoint
            if key in devices:
                raise MatterError(NO_CONTROLLER)
            devices[key] = {"node_id": node_id, "endpoint": endpoint, "identity": identity, "name": name,
                            "on": state if node.get("available") is True else None}
    return devices


class MatterControl:
    def __init__(self, directory, socket, printer_monitor):
        self.path = Path(directory) / SETTINGS_FILE
        self.socket = socket
        self.printer_monitor = printer_monitor
        self.lock = threading.Lock()

    def settings(self):
        try:
            return MatterSettings.model_validate_json(self.path.read_bytes())
        except FileNotFoundError:
            return MatterSettings()
        except (OSError, ValueError) as exc:
            raise MatterError("Les réglages Matter sont illisibles.") from exc

    @contextmanager
    def session(self):
        if not self.socket:
            raise MatterError(NO_CONTROLLER)
        try:
            wire = unix_connect(str(self.socket), uri="ws://localhost/ws", open_timeout=2, close_timeout=0.25,
                                max_size=8 * 1024 * 1024, compression=None, ping_interval=None)
        except (OSError, WebSocketException, TimeoutError) as exc:
            raise MatterError(NO_CONTROLLER) from exc
        with wire:
            yield MatterSession(wire)

    @contextmanager
    def operation(self):
        if not self.lock.acquire(blocking=False):
            raise MatterError("Une opération Matter est déjà en cours.", 409)
        try:
            yield
        finally:
            self.lock.release()

    def discovery(self):
        with self.session() as session:
            devices = endpoints(session.call("get_nodes"))
            return {"fabric": session.fabric, "bluetooth": session.info.get("bluetooth_enabled") is True,
                    "devices": list(devices.values())}

    def save(self, candidate):
        with self.operation():
            current = self.settings()
            if candidate.revision != current.revision:
                raise MatterError(CHANGED, 409)
            existing = {(*target(device), device.identity) for device in current.devices}
            wanted = {(*target(device), device.identity) for device in candidate.devices}
            needs_check = (candidate.fabric != current.fabric or (candidate.enabled and not current.enabled)
                           or not wanted <= existing)
            if candidate.devices and needs_check:
                discovery = self.discovery()
                found = {(row["node_id"], row["endpoint"], row["identity"]) for row in discovery["devices"]}
                if discovery["fabric"] != candidate.fabric or not wanted <= found:
                    raise MatterError(CHANGED, 409)
            saved = candidate.model_copy(update={"revision": current.revision + 1})
            try:
                private_json(self.path, saved.model_dump())
            except OSError as exc:
                raise MatterError("L’enregistrement des réglages Matter n’est pas confirmé. Actualisez la liste.") from exc
            return saved

    def status(self):
        settings = self.settings()
        result = {"enabled": settings.enabled, "revision": settings.revision, "devices": [], "message": None}
        if not settings.enabled or not settings.devices:
            return result
        live = {}
        try:
            with self.session() as session:
                if session.fabric != settings.fabric:
                    raise MatterError(CHANGED, 409)
                live = endpoints(session.call("get_nodes"))
        except MatterError as exc:
            result["message"] = str(exc)
        for device in settings.devices:
            row = live.get(target(device))
            on = row["on"] if row and row["identity"] == device.identity else None
            state = {**device.model_dump(), "on": on}
            if device.role == "printer" and on is True:
                state["power_off_block_reason"] = (
                    self.printer_monitor.snapshot()["power_off_block_reason"]
                    if settings.unique_printer_outlet() else AMBIGUOUS_PRINTER
                )
            result["devices"].append(state)
        return result

    @staticmethod
    def read_on(session, node_id, path):
        data = session.call("read_attribute", {"node_id": node_id, "attribute_path": path})
        state = data.get(path) if isinstance(data, dict) else None
        if type(state) is not bool:
            raise MatterError("L’état de cet appareil Matter est indisponible.")
        return state

    def command(self, request):
        with self.operation():
            settings = self.settings()
            if not settings.enabled or settings.revision != request.revision:
                raise MatterError(CHANGED, 409)
            device = next((item for item in settings.devices if target(item) == target(request)), None)
            if device is None:
                raise MatterError(CHANGED, 409)
            printer_off = device.role == "printer" and not request.on
            if printer_off and not settings.unique_printer_outlet():
                raise MatterError(AMBIGUOUS_PRINTER, 409)
            node_id, path = int(device.node_id), f"{device.endpoint}/{ON_OFF}/0"
            with self.session() as session:
                if session.fabric != settings.fabric:
                    raise MatterError(CHANGED, 409)
                node = session.call("get_node", {"node_id": node_id})
                current = endpoints([node]).get(target(device))
                if not current or current["identity"] != device.identity:
                    raise MatterError(CHANGED, 409)
                if current["on"] is None:
                    raise MatterError("L’état de cet appareil Matter est indisponible.")
                if self.read_on(session, node_id, path) != request.on:
                    check = self.printer_monitor.confirm_power_off() if printer_off else nullcontext()
                    try:
                        with check:
                            session.call("device_command", {"node_id": node_id, "endpoint_id": device.endpoint,
                                         "cluster_id": ON_OFF, "command_name": "on" if request.on else "off",
                                         "payload": {}, "interaction_timeout_ms": 2500}, timeout=8)
                        if self.read_on(session, node_id, path) != request.on:
                            raise MatterError(UNCERTAIN, 502)
                    except MatterError as exc:
                        raise MatterError(UNCERTAIN, 502) from exc
            return {"on": request.on}

    def pair(self, request):
        code = request.code.get_secret_value().strip().upper()
        if not code.startswith("MT:"):
            code = re.sub(r"[\s-]", "", code)
        if not re.fullmatch(r"(?:MT:[0-9A-Z.\-]{8,253}|[0-9]{11}|[0-9]{21})", code):
            raise MatterError("Code d’association Matter invalide.", 422)
        ssid = request.wifi_ssid
        password = request.wifi_password.get_secret_value() if request.wifi_password is not None else ""
        if ((ssid is not None and (request.network_only or not 1 <= len(ssid.encode()) <= 32))
                or (password and (ssid is None or len(password.encode()) > 64))):
            raise MatterError("Réseau Wi-Fi d’association invalide.", 422)
        with self.operation(), self.session() as session:
            if session.fabric != request.fabric:
                raise MatterError(CHANGED, 409)
            if not request.network_only and session.info.get("bluetooth_enabled") is not True:
                raise MatterError("Le Bluetooth du contrôleur Matter est désactivé.", 409)
            if ssid is not None:
                session.call("set_wifi_credentials", {"ssid": ssid, "credentials": password})
            try:
                session.call("commission_with_code", {"code": code, "network_only": request.network_only,
                             "discovery_timeout_s": 45}, timeout=95)
            except ControllerRejection as exc:
                messages = {"not-discovered": "Appareil Matter introuvable. Vérifiez son mode d’association.",
                            "passcode-mismatch": "Code d’association Matter refusé.",
                            "invalid-payload": "Code d’association Matter invalide.",
                            "attestation-rejected": "La certification de l’appareil Matter a été refusée."}
                if exc.reason in messages:
                    raise MatterError(messages[exc.reason], 409) from exc
                raise MatterError("Association Matter à vérifier. Actualisez la liste des appareils.", 502) from exc
            except MatterError as exc:
                raise MatterError("Association Matter à vérifier. Actualisez la liste des appareils.", 502) from exc
        return {"paired": True}
