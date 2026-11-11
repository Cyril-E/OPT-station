"""Touchscreen settings use private fixtures, never the test host's desktop."""
import json
import subprocess
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.touchscreen import LabwcTouchscreen, TouchscreenError, option


class DesktopRunner:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.on_reload = None

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[0] == "/usr/bin/pgrep":
            return SimpleNamespace(stdout="314\n")
        assert command == ["/usr/bin/labwc", "--reconfigure"]
        assert kwargs["env"]["LABWC_PID"] == "314"
        if self.on_reload:
            self.on_reload()
        if self.fail:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout="")


@pytest.fixture
def desktop(tmp_path):
    home = tmp_path / "home"
    folder = home / ".config/labwc"
    folder.mkdir(parents=True)
    path = folder / "rc.xml"
    path.write_text('''<?xml version="1.0"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <!-- Keep the installed screen orientation and other desktop settings. -->
  <touch deviceName="Panel A" mapToOutput="DSI-2" mouseEmulation="yes"/>
  <touch deviceName="Other panel" mapToOutput="HDMI-A-1" mouseEmulation="yes"/>
  <libinput><device category="touch"><calibrationMatrix>0 -1 1 1 0 0</calibrationMatrix></device></libinput>
  <keyboard><keybind key="W-e"><action name="Execute" command="file-manager"/></keybind></keyboard>
</openbox_config>''')
    model = tmp_path / "model"; model.write_text("Raspberry Pi 5 Model B\0")
    input_dir = tmp_path / "input"
    event = input_dir / "event5"; (event / "device").mkdir(parents=True)
    (event / "device/name").write_text("Panel A\n"); (event / "dev").write_text("13:69\n")
    udev = tmp_path / "udev"; udev.mkdir(); (udev / "c13:69").write_text("E:ID_INPUT_TOUCHSCREEN=1\n")
    proc = tmp_path / "proc"; process = proc / "314"; process.mkdir(parents=True)
    (process / "comm").write_text("labwc\n")
    (process / "cmdline").write_bytes(b"/usr/bin/labwc\0-m\0")
    (process / "environ").write_bytes(b"XDG_RUNTIME_DIR=/run/user/1000\0")
    runner = DesktopRunner()
    backend = LabwcTouchscreen(True, home=home, input_dir=input_dir, udev_dir=udev,
                              proc_dir=proc, model_path=model, runner=runner)
    return backend, runner


def test_read_is_harmless_and_save_preserves_output_calibration_and_other_profiles(desktop):
    backend, runner = desktop
    original = backend.path.read_bytes()
    current = backend.snapshot()
    assert current["supported"] and not current["enabled"] and current["devices"] == ["Panel A"]
    assert backend.path.read_bytes() == original
    assert all(command[0] == "/usr/bin/pgrep" for command, _ in runner.calls)
    saved = backend.save(current["revision"], True)
    assert saved["enabled"] and saved["revision"] != current["revision"]
    root = ET.fromstring(backend.path.read_bytes())
    ns = {"x": "http://openbox.org/3.4/rc"}
    panel = root.find("x:touch[@deviceName='Panel A']", ns)
    assert panel.attrib == {"deviceName": "Panel A", "mapToOutput": "DSI-2", "mouseEmulation": "no"}
    assert root.find("x:touch[@deviceName='Other panel']", ns).get("mouseEmulation") == "yes"
    assert root.find("x:libinput/x:device/x:calibrationMatrix", ns).text == "0 -1 1 1 0 0"
    assert root.find("x:keyboard/x:keybind/x:action", ns).get("command") == "file-manager"
    assert b"Keep the installed screen orientation" in backend.path.read_bytes()
    assert backend.path.with_name("rc.xml.opt-station-backup").read_bytes() == original
    calls = len(runner.calls)
    backend.save(saved["revision"], True)
    assert len(runner.calls) == calls + 1  # A no-op only finds the compositor.
    disabled = backend.save(saved["revision"], False)
    assert not disabled["enabled"]


def test_external_edit_and_hotplug_invalidate_an_open_form(desktop):
    backend, _ = desktop
    before = backend.snapshot()
    backend.path.write_bytes(backend.path.read_bytes().replace(b'command="file-manager"', b'command="other-manager"'))
    with pytest.raises(TouchscreenError) as error:
        backend.save(before["revision"], True)
    assert error.value.status_code == 409 and b"other-manager" in backend.path.read_bytes()
    before = backend.snapshot()
    (backend.input_dir / "event5/device/name").write_text("Different panel")
    with pytest.raises(TouchscreenError) as error:
        backend.save(before["revision"], True)
    assert error.value.status_code == 409


def test_reload_failure_restores_previous_configuration(desktop):
    backend, runner = desktop
    before = backend.snapshot(); original = backend.path.read_bytes()
    runner.fail = True
    with pytest.raises(TouchscreenError):
        backend.save(before["revision"], True)
    assert backend.path.read_bytes() == original
    assert len([command for command, _ in runner.calls if command[0] == "/usr/bin/labwc"]) == 2


def test_failed_reload_does_not_overwrite_a_concurrent_desktop_edit(desktop):
    backend, runner = desktop
    before = backend.snapshot()
    concurrent = backend.path.read_bytes() + b"\n<!-- external edit -->"
    runner.on_reload = lambda: backend.path.write_bytes(concurrent)
    runner.fail = True
    with pytest.raises(TouchscreenError):
        backend.save(before["revision"], True)
    assert backend.path.read_bytes() == concurrent


def test_fallback_and_child_options_keep_mapping_for_other_devices(desktop):
    backend, _ = desktop
    backend.path.write_text('<labwc_config><touch mouseEmulation="yes" mapToOutput="DSI-2"/></labwc_config>')
    before = backend.snapshot()
    saved = backend.save(before["revision"], True)
    assert saved["enabled"]
    entries = list(ET.fromstring(backend.path.read_bytes()))
    assert entries[0].attrib == {"mouseEmulation": "yes", "mapToOutput": "DSI-2"}
    assert entries[1].attrib == {"deviceName": "Panel A", "mapToOutput": "DSI-2", "mouseEmulation": "no"}
    backend.path.write_text('<labwc_config><touch><deviceName>Panel A</deviceName><mapToOutput>DSI-2</mapToOutput><mouseEmulation>yes</mouseEmulation></touch></labwc_config>')
    saved = backend.save(backend.snapshot()["revision"], True)
    entry = list(ET.fromstring(backend.path.read_bytes()))[0]
    assert option(entry, "mouseEmulation") == "no" and option(entry, "mapToOutput") == "DSI-2"
    assert "mouseEmulation" not in entry.attrib


def test_creates_a_user_profile_when_the_desktop_uses_defaults(desktop):
    backend, _ = desktop
    backend.path.unlink()
    before = backend.snapshot()
    assert before["supported"] and before["enabled"]
    assert not backend.save(before["revision"], False)["enabled"]
    assert backend.path.is_file() and backend.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("bad_xml", [
    '<labwc_config><touch deviceName="Panel A" mouseEmulation="yes"><mouseEmulation>no</mouseEmulation></touch></labwc_config>',
    '<labwc_config><touch deviceName="Panel A"/><touch deviceName="Panel A"/></labwc_config>',
    '<!DOCTYPE labwc_config [<!ENTITY test "bad">]><labwc_config/>',
    '<labwc_config>', '<other_root/>',
])
def test_ambiguous_or_invalid_configuration_is_not_written(desktop, bad_xml):
    backend, _ = desktop
    backend.path.write_text(bad_xml)
    assert not backend.snapshot()["supported"]
    with pytest.raises(TouchscreenError):
        backend.save("0" * 64, True)
    assert backend.path.read_text() == bad_xml


def test_symlinks_and_custom_desktop_paths_are_not_followed(desktop, tmp_path):
    backend, _ = desktop
    other = tmp_path / "other.xml"; other.write_text("unrelated file")
    original = backend.path.read_bytes(); backend.path.unlink(); backend.path.symlink_to(other)
    assert not backend.snapshot()["supported"]
    with pytest.raises(TouchscreenError): backend.save("0" * 64, True)
    assert other.read_text() == "unrelated file"
    backend.path.unlink(); backend.path.write_bytes(original)
    (backend.proc_dir / "314/cmdline").write_bytes(b"labwc\0--config\0/another/config.xml\0")
    assert not backend.snapshot()["supported"]


def test_simulation_and_disconnected_touchscreen_cannot_modify_the_desktop(desktop):
    backend, _ = desktop
    before = backend.path.read_bytes()
    backend.enabled = False
    assert not backend.snapshot()["supported"]
    with pytest.raises(TouchscreenError): backend.save("0" * 64, True)
    backend.enabled = True
    (backend.udev_dir / "c13:69").write_text("E:ID_INPUT_MOUSE=1\n")
    assert not backend.snapshot()["supported"]
    assert backend.path.read_bytes() == before


def test_standard_pi_permissions_inside_a_private_home_are_supported(desktop):
    backend, _ = desktop
    backend.home.chmod(0o700)
    (backend.home / ".config").chmod(0o775)
    backend.path.chmod(0o664)
    current = backend.snapshot()
    assert current["supported"]
    assert backend.save(current["revision"], True)["enabled"]
    assert backend.path.stat().st_mode & 0o777 == 0o664
    backend.home.chmod(0o755)
    assert not backend.snapshot()["supported"]


@pytest.mark.parametrize("mode,expected", [("disabled", 403), ("inventory", 403), ("full", 200)])
def test_api_requires_local_or_full_access(desktop, tmp_path, mode, expected):
    backend, _ = desktop
    app = create_app(Settings(tmp_path / "data", network_enabled=True), touchscreen_backend=backend)
    with TestClient(app, client=("127.0.0.1", 1)) as local:
        body = {"revision": local.get('/api/configuration/touchscreen').json()["revision"], "enabled": True}
        assert local.put('/api/configuration/network', json={"mode": mode}).status_code == 200
        with TestClient(app, client=("192.0.2.10", 1)) as remote:
            assert remote.get('/api/configuration/touchscreen').status_code == expected
            assert remote.put('/api/configuration/touchscreen', json=body).status_code == expected
        if expected == 403:
            assert local.put('/api/configuration/touchscreen', json=body).json()["enabled"]


def test_api_checks_types_origin_revision_and_power_state(desktop, tmp_path):
    backend, _ = desktop
    app = create_app(Settings(tmp_path / "data"), touchscreen_backend=backend)
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        current = client.get('/api/configuration/touchscreen').json()
        body = {"revision": current["revision"], "enabled": True}
        for invalid in [{**body, "enabled": "true"}, {**body, "path": "/tmp/other"}, {**body, "revision": "wrong"}]:
            assert client.put('/api/configuration/touchscreen', json=invalid).status_code == 422
        assert client.put('/api/configuration/touchscreen', content=json.dumps(body)).status_code == 415
        assert client.put('/api/configuration/touchscreen', json=body, headers={"Origin": "http://other.test"}).status_code == 403
        assert client.put('/api/configuration/touchscreen', json={**body, "revision": "0" * 64}).status_code == 409
        app.state.station_power.phase = "requested"
        assert client.put('/api/configuration/touchscreen', json=body).status_code == 503
        assert not backend.snapshot()["enabled"]
