"""Exercise real-adapter invariants against an independent block-memory device."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import TagImage
from openprinttag_app.nfc import HardwareReader
from openprinttag_app.nfc_worker import NFCError, PCSCSession, execute, read_record, write_image
from openprinttag_app.readers import ReaderUnavailable, WriteRejected, revision


UID = "E004010000000010"  # Fictitious device UID, never read from hardware.
MAIN = {"material_class": "FFF", "material_type": "PETG", "material_name": "Test PETG", "nominal_netto_full_weight": 1000}


class Device:
    def __init__(self, image=None):
        self.image = bytearray(image or bytes(320))
        self.wire_uid = bytes.fromhex(UID)[::-1]
        self.security = bytearray(80)
        self.nxp = bytes.fromhex("0000007f350000")
        self.writes = []
        self.fail_at = None
        self.corrupt = False
        self.connected = False

    def uid(self):
        return self.wire_uid

    def readers(self):
        return ["ACS ACR1552 PICC"] if self.connected else []

    def connect(self, name, direct=False):
        if not self.connected:
            raise NFCError("Lecteur absent.")

    def present(self, name):
        return self.connected

    def iso(self, command, uid, data=b"", manufacturer=None):
        if uid != self.wire_uid:
            raise NFCError("Ce tag n’est plus dans le champ radio.")
        if command == 0x2B:
            return b"\x0f" + uid + b"\x00\x00\x4f\x03\x01"
        if command == 0xAB:
            if self.nxp is None:
                raise NFCError("Commande non disponible.")
            return self.nxp
        if command == 0x2C:
            return bytes(self.security[data[0]:data[0] + data[1] + 1])
        if command == 0x20:
            return bytes(self.image[data[0] * 4:data[0] * 4 + 4])
        assert command == 0x21, "Unexpected mutating RF command"
        block = data[0]
        assert len(data) == 5
        assert block < 79, "The device counter must never be written"
        if self.fail_at is not None and len(self.writes) == self.fail_at:
            raise NFCError("Tag retiré pendant l’écriture.")
        if self.security[block] & 1:
            raise NFCError("Bloc verrouillé.")
        self.writes.append(block)
        self.image[block * 4:block * 4 + 4] = data[1:]
        if self.corrupt:
            self.image[block * 4] ^= 1
        return b""


def proposed(device, aux=None):
    return TagImage.create(UID, MAIN, aux or {}, capacity=312).to_bytes() + bytes(device.image[312:])


def request(device, image, directory):
    current = read_record(device)
    return {"operation": "write", "expected_uid": current["uid"],
            "expected_revision": revision({**current, "image": bytes.fromhex(current["image"])}),
            "image": image.hex(), "backup_dir": str(directory)}


def test_initialization_keeps_reserved_counter_and_publishes_header_last(tmp_path):
    device = Device(bytes(312) + b"reserved")
    before = bytes(device.image)
    image = proposed(device)
    result = write_image(device, request(device, image, tmp_path))
    assert result["verified"]
    assert bytes(device.image) == image
    assert device.writes[-1] == 0
    assert set(device.writes).isdisjoint({78, 79})
    assert Path(result["backup"]).read_bytes() == before
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["status"] == "verified"


def test_aux_update_preserves_every_byte_and_block_outside_aux(tmp_path):
    device = Device()
    device.image[:] = proposed(device, {"consumed_weight": 20})
    original = TagImage.from_bytes(device.image, UID)
    offset, length = original.regions["aux"]
    start = original.payload_offset + offset
    device.nxp = bytes.fromhex("3c02007f350000")  # Page L below block 60 is write protected.
    current = read_record(device)
    assert current["main_locked"] and not current["aux_locked"]
    after = original.with_updates({}, {"consumed_weight": 45}).to_bytes()
    before = bytes(device.image)
    write_image(device, request(device, after, tmp_path))
    assert bytes(device.image[:start]) == before[:start]
    assert bytes(device.image[start + length:]) == before[start + length:]
    assert all(start <= block * 4 and block * 4 + 4 <= start + length for block in device.writes)


@pytest.mark.parametrize("change", ["data", "uid", "protection"])
def test_changed_tag_or_protection_is_rejected_before_any_write(tmp_path, change):
    device = Device()
    job = request(device, proposed(device), tmp_path)
    if change == "data":
        device.image[15] = 1
    elif change == "uid":
        device.wire_uid = b"\x99" + device.wire_uid[1:]
    else:
        device.security[0] = 1
    with pytest.raises(NFCError, match="changé") as caught:
        write_image(device, job)
    assert caught.value.kind == "conflict"
    assert device.writes == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("protection", ["permanent", "password", "unknown"])
def test_protected_or_unknown_protection_never_starts_a_write(tmp_path, protection):
    device = Device()
    if protection == "permanent":
        device.security[0] = 1
    elif protection == "password":
        device.nxp = bytes.fromhex("0020007f350000")
    else:
        device.nxp = None
    with pytest.raises(NFCError) as caught:
        write_image(device, request(device, proposed(device), tmp_path))
    assert caught.value.kind == "protected"
    assert not caught.value.dirty
    assert device.writes == []


def test_reserved_block_tampering_is_refused(tmp_path):
    device = Device()
    image = bytearray(proposed(device))
    image[-1] = 1
    with pytest.raises(NFCError, match="réservé"):
        write_image(device, request(device, image, tmp_path))
    assert device.writes == []


def test_failed_backup_aborts_without_touching_tag(tmp_path):
    device = Device()
    path = tmp_path / "not-a-directory"
    path.write_text("occupied")
    with pytest.raises(NFCError, match="sauvegarde") as caught:
        write_image(device, request(device, proposed(device), path))
    assert not caught.value.dirty
    assert device.writes == []


@pytest.mark.parametrize("failure", ["removed", "corrupt"])
def test_partial_or_unverified_write_is_uncertain_and_never_retried(tmp_path, failure):
    device = Device()
    job = request(device, proposed(device), tmp_path)
    if failure == "removed":
        device.fail_at = 1
    else:
        device.corrupt = True
    with pytest.raises(NFCError) as caught:
        write_image(device, job)
    assert caught.value.dirty
    assert len(device.writes) == 1
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["status"] == "uncertain"
    assert next(tmp_path.glob("*.bin")).read_bytes() == bytes(320)


def test_existing_headers_cannot_be_rewritten_during_update(tmp_path):
    device = Device()
    device.image[:] = proposed(device)
    image = bytearray(device.image)
    image[3] ^= 1
    with pytest.raises(NFCError, match="en-têtes"):
        write_image(device, request(device, image, tmp_path))
    assert device.writes == []


def test_rf_commands_use_explicit_uid_and_decode_error_flags():
    session = PCSCSession.__new__(PCSCSession)
    commands = []
    session.transmit = lambda command: commands.append(command) or b"\x00abcd"
    wire_uid = bytes.fromhex(UID)[::-1]
    assert session.iso(0x20, wire_uid, b"\x04") == b"abcd"
    assert commands == [[0xFF, 0xFB, 0, 0x22, 10, 0x20, *wire_uid, 4]]
    session.transmit = lambda command: b"\x01\x12"
    with pytest.raises(NFCError):
        session.iso(0x20, wire_uid, b"\x04")


@pytest.mark.parametrize("event,present", [(0x22, True), (0x12, False)])
def test_presence_uses_get_status_change_flags_exported_by_pyscard(event, present):
    session = PCSCSession.__new__(PCSCSession)
    session.context = 42
    def status(context, timeout, readers):
        assert (context, timeout, readers) == (42, 0, [("ACR1552 PICC", 0)])
        return 0, [("ACR1552 PICC", event, [])]
    session.sc = SimpleNamespace(SCARD_S_SUCCESS=0, SCARD_STATE_UNAWARE=0,
                                 SCARD_STATE_PRESENT=0x20, SCardGetStatusChange=status)
    assert session.present("ACR1552 PICC") is present


def test_supervisor_terminates_a_stuck_native_process(tmp_path, monkeypatch):
    reader = HardwareReader(tmp_path)
    monkeypatch.setattr(reader, "_command", lambda: [sys.executable, "-c", "import time; time.sleep(60)"])
    original = subprocess.Popen.communicate
    def communicate(process, input=None, timeout=None):
        return original(process, input=input, timeout=0.05 if timeout is not None else None)
    monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
    with pytest.raises(ReaderUnavailable, match="délai"):
        reader.read()
    assert reader._process is None


def test_hardware_api_uses_312_bytes_and_keeps_simulator_separate(tmp_path, monkeypatch):
    device = Device(bytes(312) + b"reserved")
    device.connected = True
    reader = HardwareReader(tmp_path / "nfc-backups")
    def run(operation, **values):
        try:
            return execute({"operation": operation, **values}, device)
        except NFCError as exc:
            if operation == "write" and not exc.dirty:
                raise WriteRejected(str(exc), 409) from exc
            raise ReaderUnavailable(str(exc)) from exc
    monkeypatch.setattr(reader, "_run", run)
    app = create_app(Settings(tmp_path, mode="hardware"), reader=reader)
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        tag = client.get("/api/reader/tag").json()
        assert tag["blank"] and tag["memory"]["usable_capacity"] == 312
        assert client.post("/api/simulator/blank", json={}).status_code == 409
        preview = client.post("/api/reader/prepare", json={"mode":"create", "expected_uid":tag["uid"], "expected_revision":tag["revision"], "main": MAIN, "aux": {}})
        assert preview.status_code == 200, preview.text
        assert preview.json()["tag"]["remaining_weight"] is None
        written = client.post("/api/reader/write", json={"preview_id":preview.json()["preview_id"]})
        assert written.status_code == 200, written.text
        assert written.json()["verified"] and not written.json()["simulation"]
        assert client.get("/api/inventory").json()["items"] == []
        assert bytes(device.image[312:]) == b"reserved"
        assert client.post("/api/reader/write", json={"preview_id":preview.json()["preview_id"]}).status_code == 409


def test_restarting_hardware_mode_marks_interrupted_operations_uncertain(tmp_path):
    app = create_app(Settings(tmp_path, mode="hardware"))
    identifier = app.state.store.begin_operation(UID, "old")
    other = create_app(Settings(tmp_path, mode="hardware"))
    operation = other.state.store.operations()[0]
    assert operation["id"] == identifier and operation["status"] == "uncertain"


def test_api_reports_a_preflight_rejection_without_calling_it_a_partial_write(tmp_path, monkeypatch):
    device = Device()
    device.connected = True
    reader = HardwareReader(tmp_path / "nfc-backups")
    def run(operation, **values):
        if operation == "write":
            raise WriteRejected("Le tag a changé. Aucune écriture n’a été lancée.")
        return execute({"operation": operation, **values}, device)
    monkeypatch.setattr(reader, "_run", run)
    app = create_app(Settings(tmp_path, mode="hardware"), reader=reader)
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        tag = client.get("/api/reader/tag").json()
        preview = client.post("/api/reader/prepare", json={"mode":"create", "expected_uid":tag["uid"], "expected_revision":tag["revision"], "main":MAIN}).json()
        response = client.post("/api/reader/write", json={"preview_id":preview["preview_id"]})
        assert response.status_code == 409 and "Aucune écriture" in response.json()["detail"]
        assert app.state.store.operations()[0]["status"] == "rejected"
        assert device.writes == []
