"""Native screen timers are replaced by private, deterministic process models."""
import base64
import json
from pathlib import Path
import socket
import tempfile
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.screen_sleep import ScreenSleep, ScreenSleepError, WaylandIdle, validate_screen_settings, write_settings


class Process:
    def __init__(self):
        self.code = None
    def poll(self): return self.code
    def terminate(self): self.code = 0
    def wait(self, timeout=None): return self.code
    def kill(self): self.code = -9


class Idle:
    enabled = False  # API tests need no polling thread.
    def __init__(self):
        self.processes, self.delays = [], []
        self.wakes, self.failure, self.available = 0, None, True
    def environment(self):
        if not self.available: raise ScreenSleepError("Bureau indisponible.")
        return {}
    def launch(self, minutes):
        if self.failure == minutes: raise ScreenSleepError("Échec du minuteur.")
        self.environment(); self.delays.append(minutes)
        process = Process(); self.processes.append(process)
        return process
    def stop(self, process): process.terminate(); self.wake()
    def wake(self): self.environment(); self.wakes += 1


def test_settings_are_persistent_and_stale_requests_do_not_replace_them(tmp_path):
    backend = Idle(); manager = ScreenSleep(tmp_path, backend)
    original = manager.snapshot()
    assert original["timeout_minutes"] == 0 and not original["running"]
    assert backend.processes == [] and not manager.path.exists()
    saved = manager.save(0, 5)
    assert saved["running"] and saved["timeout_minutes"] == 5
    assert manager.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ScreenSleepError) as error: manager.save(0, 10)
    assert error.value.status_code == 409 and manager.record()["timeout_minutes"] == 5
    manager.save(saved["revision"], 10)
    assert backend.processes[0].poll() == 0 and backend.delays == [5, 10]
    stopped = manager.save(2, 0)
    assert not stopped["running"] and backend.wakes == 2
    manager.close()


def test_failed_change_restores_the_saved_delay_and_its_timer(tmp_path):
    backend = Idle(); manager = ScreenSleep(tmp_path, backend)
    manager.save(0, 5); previous = manager.path.read_bytes()
    backend.failure = 10
    with pytest.raises(ScreenSleepError): manager.save(1, 10)
    assert manager.path.read_bytes() == previous
    assert manager.snapshot()["running"] and manager.record()["timeout_minutes"] == 5
    assert backend.delays == [5, 5]
    manager.close()


def test_failed_first_activation_leaves_no_new_settings(tmp_path):
    backend = Idle(); backend.failure = 5
    manager = ScreenSleep(tmp_path, backend)
    with pytest.raises(ScreenSleepError): manager.save(0, 5)
    assert not manager.path.exists() and not manager.snapshot()["running"]


def await_condition(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.01)
    pytest.fail("Le minuteur de test n’a pas pris en compte les réglages.")


def test_start_restores_delay_and_reload_applies_a_restored_backup(tmp_path):
    backend = Idle(); backend.enabled = True
    write_settings(tmp_path / "screen-settings.json", {"revision": 4, "timeout_minutes": 5})
    manager = ScreenSleep(tmp_path, backend)
    manager.start()
    try:
        await_condition(lambda: backend.delays == [5])
        write_settings(manager.path, {"revision": 9, "timeout_minutes": 1})
        manager.reload()
        await_condition(lambda: backend.delays == [5, 1])
        assert backend.processes[0].poll() == 0
    finally: manager.close()
    assert all(process.poll() is not None for process in backend.processes)


def test_dead_timer_is_recovered_and_screen_is_woken(tmp_path):
    backend = Idle(); backend.enabled = True
    manager = ScreenSleep(tmp_path, backend)
    manager.save(0, 5)
    backend.processes[0].code = 1
    manager.start()
    try:
        await_condition(lambda: len(backend.processes) == 2)
        assert backend.wakes == 1 and manager.snapshot()["running"]
    finally: manager.close()


@pytest.mark.parametrize("value", [-1, 3, 7, 61, True, 5.0, "5", None])
def test_only_supported_delays_are_accepted(value):
    with pytest.raises(ValueError): validate_screen_settings({"revision": 0, "timeout_minutes": value})


def test_native_timer_uses_current_wayland_socket_and_only_screen_power(tmp_path):
    model = tmp_path / "model"; model.write_text("Raspberry Pi 5\0")
    desktop = SimpleNamespace(model_path=model, _compositor=lambda: "314")
    idle_file, power_file = tmp_path / "swayidle", tmp_path / "wlopm"
    for file in (idle_file, power_file): file.write_text("fixture"); file.chmod(0o700)
    calls = []
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="idle-") as runtime:
        with socket.socket(socket.AF_UNIX) as display:
            display.bind(str(Path(runtime) / "wayland-0"))
            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return SimpleNamespace(stdout=f"WAYLAND_DISPLAY=wayland-0\nXDG_RUNTIME_DIR={runtime}\nOTHER_SECRET=not-imported\n")
            def spawn(command, **kwargs):
                calls.append((command, kwargs)); return Process()
            backend = WaylandIdle(True, desktop=desktop, runner=runner, spawn=spawn,
                                  idle_program=idle_file, power_program=power_file)
            environment = backend.environment()
            assert environment["WAYLAND_DISPLAY"] == "wayland-0" and "OTHER_SECRET" not in environment
            process = backend.launch(5)
            command = calls[-1][0]
            assert command[:6] == [str(idle_file), "-w", "-C", "/dev/null", "timeout", "300"]
            assert command[7] == "resume" and "--off '*'" in command[6] and "--on '*'" in command[8]
            assert not any(word in " ".join(command) for word in ("suspend", "poweroff", "reboot", "loginctl"))
            backend.stop(process)
            assert calls[-1][0] == [str(power_file), "--on", "*"]


@pytest.mark.parametrize("mode,expected", [("disabled", 403), ("inventory", 403), ("full", 200)])
def test_local_or_full_access_is_required_for_settings_and_wake(tmp_path, mode, expected):
    backend = Idle(); app = create_app(Settings(tmp_path, network_enabled=True), screen_sleep_backend=backend)
    with TestClient(app, client=("127.0.0.1", 1)) as local:
        assert local.get('/api/configuration/screen').json()["timeout_minutes"] == 0
        assert local.put('/api/configuration/network', json={"mode": mode}).status_code == 200
        body = {"revision": 0, "timeout_minutes": 5}
        with TestClient(app, client=("192.0.2.12", 1)) as remote:
            assert remote.get('/api/configuration/screen').status_code == expected
            assert remote.put('/api/configuration/screen', json=body).status_code == expected
            assert remote.post('/api/configuration/screen/wake', json={}).status_code == expected
        if expected == 403:
            assert not (tmp_path / 'screen-settings.json').exists()


def test_api_types_origin_unknown_fields_and_power_are_checked(tmp_path):
    backend = Idle(); app = create_app(Settings(tmp_path), screen_sleep_backend=backend)
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        body = {"revision": 0, "timeout_minutes": 5}
        for invalid in [{**body, "timeout_minutes": "5"}, {**body, "timeout_minutes": 3}, {**body, "command": "anything"}]:
            assert client.put('/api/configuration/screen', json=invalid).status_code == 422
        assert client.put('/api/configuration/screen', content=json.dumps(body)).status_code == 415
        assert client.put('/api/configuration/screen', json=body, headers={"Origin": "http://another.host"}).status_code == 403
        assert client.post('/api/configuration/screen/wake', json={}, headers={"Origin": "http://another.host"}).status_code == 403
        assert backend.processes == [] and backend.wakes == 0
        app.state.station_power.phase = "requested"
        assert client.put('/api/configuration/screen', json=body).status_code == 503
        assert client.post('/api/configuration/screen/wake', json={}).status_code == 503


def test_configured_delay_is_in_backup_and_invalid_restore_is_rejected(tmp_path):
    from openprinttag_app.backups import encode_backup
    backend = Idle(); app = create_app(Settings(tmp_path), screen_sleep_backend=backend)
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        assert client.put('/api/configuration/screen', json={"revision": 0, "timeout_minutes": 5}).status_code == 200
        record = app.state.backups.collect('all')
        assert record['configuration']['screen-settings.json']['timeout_minutes'] == 5
        encoded = base64.b64encode(encode_backup(record, None)).decode()
        assert client.post('/api/backups/restore/preview', json={"content": encoded}).status_code == 200
        record['configuration']['screen-settings.json']['timeout_minutes'] = 3
        encoded = base64.b64encode(encode_backup(record, None)).decode()
        assert client.post('/api/backups/restore/preview', json={"content": encoded}).status_code == 422
