"""Persist screen idle time and supervise a native, screen-only Wayland timer."""
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import threading

from .touchscreen import LabwcTouchscreen, TouchscreenError


TIMEOUTS = (0, 1, 2, 5, 10, 15, 30, 60)
UNAVAILABLE = "La veille de l’écran est disponible sur le Raspberry Pi avec son bureau ouvert."
FAILED = "La veille de l’écran n’a pas pu démarrer. Vérifiez le bureau du Pi puis actualisez."


class ScreenSleepError(ValueError):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def validate_screen_settings(record):
    if (not isinstance(record, dict) or set(record) != {"revision", "timeout_minutes"}
            or type(record["revision"]) is not int or record["revision"] < 0
            or type(record["timeout_minutes"]) is not int or record["timeout_minutes"] not in TIMEOUTS):
        raise ValueError("Réglages de veille de l’écran invalides.")
    return record


def write_settings(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".screen-sleep-", delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            json.dump(record, output)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class WaylandIdle:
    def __init__(self, enabled=False, *, desktop=None, runner=subprocess.run, spawn=subprocess.Popen,
                 idle_program=Path("/usr/bin/swayidle"), power_program=Path("/usr/bin/wlopm")):
        self.enabled = enabled
        self.desktop = desktop or LabwcTouchscreen(enabled)
        self.runner, self.spawn = runner, spawn
        self.idle_program, self.power_program = Path(idle_program), Path(power_program)

    def environment(self):
        try:
            if not self.enabled or not self.desktop.model_path.read_text().startswith("Raspberry Pi"):
                raise ScreenSleepError(UNAVAILABLE)
            self.desktop._compositor()
            if not all(path.is_file() and os.access(path, os.X_OK) for path in (self.idle_program, self.power_program)):
                raise ScreenSleepError("Les composants de veille de l’écran ne sont pas installés. Mettez à jour l’installation du Pi.")
            response = self.runner(["/usr/bin/systemctl", "--user", "show-environment"],
                                   capture_output=True, text=True, timeout=3, check=True)
            environment = os.environ.copy()
            # Read the current desktop socket, even when this service predates login.
            for line in response.stdout.splitlines():
                key, separator, value = line.partition("=")
                if separator and key in {"WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"}:
                    environment[key] = value
            runtime = Path(environment.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
            name = environment.get("WAYLAND_DISPLAY", "")
            if not name or Path(name).name != name or name in {".", ".."}:
                raise ScreenSleepError(UNAVAILABLE)
            socket = runtime / name
            if not stat.S_ISSOCK(socket.stat().st_mode) or socket.stat().st_uid != os.getuid():
                raise ScreenSleepError(UNAVAILABLE)
            return environment
        except (OSError, TouchscreenError, subprocess.SubprocessError):
            raise ScreenSleepError(UNAVAILABLE) from None

    def command(self, minutes):
        if type(minutes) is not int or minutes not in TIMEOUTS or not minutes:
            raise ScreenSleepError("Réglages de veille de l’écran invalides.", 422)
        return [str(self.idle_program), "-w", "-C", "/dev/null", "timeout", str(minutes * 60),
                shlex.join([str(self.power_program), "--off", "*"]),
                "resume", shlex.join([str(self.power_program), "--on", "*"])]

    def launch(self, minutes):
        try:
            process = self.spawn(self.command(minutes), env=self.environment(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if process.poll() is not None:
                raise ScreenSleepError(FAILED)
            return process
        except OSError:
            raise ScreenSleepError(FAILED) from None

    def wake(self):
        try:
            self.runner([str(self.power_program), "--on", "*"], env=self.environment(),
                        capture_output=True, text=True, timeout=4, check=True)
        except (OSError, subprocess.SubprocessError):
            raise ScreenSleepError("L’écran n’a pas confirmé son réveil. Vérifiez le bureau du Pi.") from None

    def stop(self, process):
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        except ProcessLookupError:
            pass
        # Also recover from a crashed timer which could have left its output off.
        self.wake()


class ScreenSleep:
    def __init__(self, data_dir, backend=None):
        self.path = Path(data_dir) / "screen-settings.json"
        self.backend = backend or WaylandIdle()
        self.lock = threading.RLock()
        self.process, self.applied_minutes, self.error = None, 0, ""
        self.event, self.closed = threading.Event(), threading.Event()
        self.thread = None

    def record(self):
        try:
            return validate_screen_settings(json.loads(self.path.read_text())) if self.path.exists() else {"revision": 0, "timeout_minutes": 0}
        except (OSError, ValueError):
            raise ScreenSleepError("Les réglages de veille de l’écran sont illisibles.") from None

    def _stop(self):
        previous, self.process = self.process, None
        self.applied_minutes = 0
        if previous is not None:
            self.backend.stop(previous)

    def _apply(self, record):
        minutes = record["timeout_minutes"]
        if self.process is not None and self.process.poll() is None and self.applied_minutes == minutes:
            return
        self._stop()
        if minutes:
            self.process = self.backend.launch(minutes)
            self.applied_minutes = minutes
        self.error = ""

    def snapshot(self):
        with self.lock:
            record = self.record()
            try:
                self.backend.environment()
                supported, message = True, ("Mise en veille de l’écran activée." if record["timeout_minutes"] else "L’écran reste allumé.")
            except ScreenSleepError as exc:
                supported, message = False, str(exc)
            running = self.process is not None and self.process.poll() is None
            if supported and record["timeout_minutes"] and not running:
                message = self.error or "La veille sera appliquée dès que le bureau du Pi sera prêt."
            return {**record, "supported": supported, "running": running, "message": message}

    def save(self, revision, minutes):
        with self.lock:
            previous = self.record()
            if revision != previous["revision"]:
                raise ScreenSleepError("Le délai de veille a changé. Actualisez avant de réessayer.", 409)
            record = validate_screen_settings({"revision": revision + 1, "timeout_minutes": minutes})
            self.backend.environment()
            existed = self.path.exists()
            write_settings(self.path, record)
            try:
                self._apply(record)
            except (OSError, ScreenSleepError):
                if existed:
                    write_settings(self.path, previous)
                else:
                    self.path.unlink(missing_ok=True)
                try:
                    self._apply(previous)
                except (OSError, ScreenSleepError):
                    self.error = FAILED
                raise ScreenSleepError(FAILED) from None
            self.event.set()
            return self.snapshot()

    def reload(self):
        self.event.set()

    def wake(self):
        with self.lock:
            self.backend.wake()
            return {"message": "Écran réveillé."}

    def start(self):
        if not self.backend.enabled or self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name="opt-screen-idle")
        self.thread.start()

    def _run(self):
        while not self.closed.is_set():
            with self.lock:
                try:
                    self._apply(self.record())
                except (OSError, ScreenSleepError) as exc:
                    self.error = str(exc)
            self.event.wait(5)
            self.event.clear()

    def close(self):
        self.closed.set()
        self.event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
        with self.lock:
            try:
                self._stop()
            except (OSError, ScreenSleepError):
                pass
