"""Bounded, local camera scans in a separate process.

The web server never imports the Pi camera stack. A stuck native capture can be
terminated without blocking the API. Images and unconfirmed QR text stay in one
private temporary directory, discarded at the next scan or on shutdown.
"""
from dataclasses import dataclass, field
import importlib.util
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time


SCAN_SECONDS = 45
RESULT_SECONDS = 180
ACTIVE_STATES = {"starting", "scanning", "stopping"}
IMAGE_CONTROLS = {
    "Brightness": (0.0, 0.05, None),
    "Contrast": (1.0, 0.1, 4.0),
    "Saturation": (1.0, 0.1, 4.0),
    "Sharpness": (1.0, 0.1, 4.0),
    "ExposureValue": (0.0, 0.5, None),
    "AfMode": (2, 1, None),
}


def image_controls(available):
    result = []
    for name, (default, step, limit) in IMAGE_CONTROLS.items():
        if name not in available:
            continue
        low, high, _ = available[name]
        if name == "AfMode" and not low <= 0 < 2 <= high:
            continue
        maximum = min(high, limit) if limit is not None else high
        result.append({"name": name, "min": low, "max": maximum,
                       "default": max(low, min(maximum, default)), "step": step})
    return result


def validate_image_controls(values, supported):
    if not isinstance(values, dict) or len(values) > len(IMAGE_CONTROLS):
        raise ValueError("Réglages caméra invalides.")
    options = {item["name"]: item for item in supported}
    for name, value in values.items():
        option = options.get(name)
        if (name not in IMAGE_CONTROLS or option is None or type(value) not in (int, float) or not math.isfinite(value)
                or not option["min"] <= value <= option["max"]
                or name == "AfMode" and (type(value) is not int or value not in (0, 2))):
            raise ValueError("Réglage caméra indisponible ou hors limites.")
    return dict(values)


def validate_saved_image_settings(record):
    if (not isinstance(record, dict) or set(record) != {"revision", "model", "controls"}
            or type(record["revision"]) is not int or record["revision"] < 0
            or not isinstance(record["model"], str) or not 1 <= len(record["model"]) <= 100
            or not isinstance(record["controls"], dict)):
        raise ValueError("Réglages caméra invalides.")
    for name, value in record["controls"].items():
        if (name not in IMAGE_CONTROLS or type(value) not in (int, float) or not math.isfinite(value)
                or name == "AfMode" and (type(value) is not int or value not in (0, 2))):
            raise ValueError("Réglages caméra invalides.")
    return record


def write_image_settings(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".camera-", delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            json.dump(record, output, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class CameraUnavailable(Exception):
    pass


class CameraBusy(Exception):
    pass


@dataclass
class Scan:
    id: str
    temporary: tempfile.TemporaryDirectory
    kind: str = "qr"
    seconds: float = SCAN_SECONDS
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    result: dict = field(default_factory=lambda: {"state": "starting", "message": "Ouverture de la caméra…", "frames": 0, "codes": []})
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    @property
    def directory(self):
        return Path(self.temporary.name)


class CameraScanner:
    def __init__(self, enabled=False, *, scan_seconds=SCAN_SECONDS, hard_timeout=None, settings_path=None):
        self.enabled = enabled
        self.scan_seconds = scan_seconds
        self.hard_timeout = hard_timeout if hard_timeout is not None else scan_seconds + 12
        self._lock = threading.RLock()
        self._scan: Scan | None = None
        self._closed = False
        self._expiry: threading.Timer | None = None
        self._devices_cache = None
        self._devices_time = 0
        self.settings_path = Path(settings_path) if settings_path is not None else None
        self._image_record = {"revision": 0, "model": None, "controls": {}}
        self._image_capabilities = None
        self._image_time = 0

    def _read_image_settings(self):
        if self.settings_path is None:
            return dict(self._image_record)
        try:
            record = json.loads(self.settings_path.read_text())
        except FileNotFoundError:
            return {"revision": 0, "model": None, "controls": {}}
        except (OSError, ValueError):
            raise CameraUnavailable("Les réglages de la caméra sont illisibles.") from None
        try:
            validate_saved_image_settings(record)
        except ValueError:
            raise CameraUnavailable("Les réglages de la caméra sont illisibles.") from None
        return record

    def image_settings(self):
        if not self.status()["available"]:
            raise CameraUnavailable(self.status()["message"])
        with self._lock:
            active = self._active(self._scan)
            if active and self._image_capabilities is None:
                raise CameraBusy("Une capture est en cours. Attendez sa fin pour ouvrir les réglages.")
            if not active and (self._image_capabilities is None or time.monotonic() - self._image_time > 30):
                try:
                    probe = subprocess.run([sys.executable, "-m", "openprinttag_app.camera_worker", "--controls"],
                                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=6, check=True)
                    result = json.loads(probe.stdout)
                    if not isinstance(result["model"], str) or not result["model"] or not isinstance(result["controls"], list):
                        raise ValueError()
                    validate_image_controls({item["name"]: item["default"] for item in result["controls"]}, result["controls"])
                except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
                    raise CameraUnavailable("Les réglages de la caméra sont indisponibles. Fermez les autres captures puis réessayez.") from None
                self._image_capabilities, self._image_time = result, time.monotonic()
            record = self._read_image_settings()
            capabilities = self._image_capabilities
            values = {item["name"]: item["default"] for item in capabilities["controls"]}
            if record["model"] == capabilities["model"]:
                values.update(validate_image_controls(record["controls"], capabilities["controls"]))
            return {**capabilities, "revision": record["revision"], "values": values}

    def save_image_settings(self, revision, model, controls):
        with self._lock:
            current = self.image_settings()
            if current["revision"] != revision or current["model"] != model:
                raise CameraBusy("La caméra ou ses réglages ont changé. Rouvrez l’aperçu.")
            if self._active(self._scan) and self._scan.kind != "preview":
                raise CameraBusy("Terminez le scan ou la photo avant de régler l’image.")
            values = validate_image_controls(controls, current["controls"])
            record = {"revision": revision + 1, "model": model, "controls": values}
            if self.settings_path:
                write_image_settings(self.settings_path, record)
            self._image_record = record
            if self._active(self._scan):
                write_image_settings(self._scan.directory / "controls.json", record)
            return self.image_settings()

    def devices(self, refresh=False):
        """Enumerate sensors without starting a capture or importing libcamera here."""
        with self._lock:
            if self._active(self._scan):
                model = self._scan.result.get("model")
                return self._devices_cache or {"detected": True if model else None, "model": model, "devices": [],
                                               "detection_message": "Scan en cours; matériel actualisé après son arrêt."}
            if not refresh and self._devices_cache is not None and time.monotonic() - self._devices_time < 30:
                return dict(self._devices_cache)
            result = {"detected": None, "model": None, "devices": [], "detection_message": "Aucune caméra détectée."}
            if sys.platform != "linux":
                result["detection_message"] = "Détection disponible sur le Raspberry Pi."
            else:
                try:
                    completed = subprocess.run([sys.executable, "-m", "openprinttag_app.camera_worker", "--list"],
                                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=True)
                    cameras = json.loads(completed.stdout)["cameras"]
                    if not isinstance(cameras, list) or any(not isinstance(item, dict) or not isinstance(item.get("model"), str) for item in cameras):
                        raise ValueError()
                    result.update(detected=bool(cameras), devices=cameras, model=cameras[0]["model"] if cameras else None,
                                  detection_message="Capteur détecté; la capture se vérifie pendant un scan." if cameras else "Aucune caméra détectée.")
                except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
                    result["detection_message"] = "Détection indisponible. Vérifiez les composants caméra et le raccordement."
            self._devices_cache, self._devices_time = result, time.monotonic()
            return dict(result)

    def status(self):
        if not self.enabled:
            message = "La capture caméra n’est pas activée sur cette station."
        elif sys.platform != "linux":
            message = "La capture utilise la caméra raccordée au Raspberry Pi."
        else:
            missing = []
            for name in ("picamera2", "zxingcpp", "numpy", "PIL"):
                try:
                    present = importlib.util.find_spec(name) is not None
                except (ImportError, ValueError):
                    present = False
                if not present:
                    missing.append(name)
            message = "Les composants caméra ne sont pas encore installés sur cette station." if missing else "Prête pour un scan."
            return {"enabled": True, "available": not missing, "message": message, "scan_seconds": self.scan_seconds}
        return {"enabled": self.enabled, "available": False, "message": message, "scan_seconds": self.scan_seconds}

    def _command(self, directory):
        return [sys.executable, "-m", "openprinttag_app.camera_worker", str(directory), str(self.scan_seconds)]

    def _active(self, scan):
        return scan is not None and scan.thread is not None and scan.thread.is_alive()

    def is_scanning(self):
        with self._lock:
            return self._active(self._scan)

    def _current(self, identifier):
        scan = self._scan
        if scan is None or scan.id != identifier:
            raise KeyError("Cet essai caméra n’existe plus. Relancez un scan.")
        if scan.finished is not None and time.monotonic() - scan.finished > RESULT_SECONDS:
            scan.temporary.cleanup()
            self._scan = None
            raise KeyError("Le résultat caméra a expiré. Relancez un scan.")
        return scan

    def _snapshot(self, scan):
        result = json.loads(json.dumps(scan.result))
        result.update(id=scan.id, active=self._active(scan),
                      remaining_seconds=result.get("remaining_seconds", max(0, round(scan.seconds - (time.monotonic() - scan.started)))),
                      preview_ready=(scan.directory / "preview.jpg").is_file())
        return result

    def start(self, kind="qr"):
        if kind not in {"qr", "photo", "preview"}:
            raise ValueError("Type de capture caméra invalide.")
        capabilities = self.status()
        if not capabilities["available"]:
            raise CameraUnavailable(capabilities["message"])
        with self._lock:
            if self._closed:
                raise CameraUnavailable("La station s’arrête. Réessayez après son redémarrage.")
            if self._active(self._scan):
                raise CameraBusy("Un scan est déjà en cours. Arrêtez-le avant d’en lancer un autre.")
            if self._expiry:
                self._expiry.cancel()
            if self._scan:
                self._scan.temporary.cleanup()
            scan = Scan(secrets.token_urlsafe(18), tempfile.TemporaryDirectory(prefix="openprinttag-qr-"), kind=kind,
                        seconds=120 if kind == "preview" else self.scan_seconds)
            write_image_settings(scan.directory / "controls.json", self._read_image_settings())
            self._scan = scan
            scan.thread = threading.Thread(target=self._run, args=(scan,), daemon=True, name="openprinttag-camera")
            scan.thread.start()
            return self._snapshot(scan)

    def get(self, identifier):
        with self._lock:
            return self._snapshot(self._current(identifier))

    def preview(self, identifier):
        with self._lock:
            scan = self._current(identifier)
            try:
                return (scan.directory / "preview.jpg").read_bytes()
            except FileNotFoundError:
                raise KeyError("La première image n’est pas encore disponible.") from None

    def start_photo(self):
        return self.start(kind="photo")

    def photo(self, identifier):
        with self._lock:
            scan = self._current(identifier)
            path = scan.directory / ("photo.jpg" if scan.kind == "photo" else "preview.jpg")
            if not path.is_file():
                raise KeyError("La photo n’est pas encore disponible.")
            return path.read_bytes()

    def cancel(self, identifier):
        with self._lock:
            scan = self._current(identifier)
            if self._active(scan):
                scan.cancel.set()
                scan.result = {"state": "stopping", "message": "Arrêt de la caméra…", "frames": scan.result.get("frames", 0), "codes": []}
            return self._snapshot(scan)

    @staticmethod
    def _terminate(process):
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _run(self, scan):
        process = None
        try:
            with (scan.directory / "capture.log").open("wb") as log:
                command = ([sys.executable, "-m", "openprinttag_app.camera_worker", "--photo", str(scan.directory)]
                           if scan.kind == "photo" else self._command(scan.directory))
                if scan.kind == "preview":
                    command = [sys.executable, "-m", "openprinttag_app.camera_worker", "--preview", str(scan.directory), str(scan.seconds)]
                process = subprocess.Popen(command, stdout=log, stderr=log,
                                           stdin=subprocess.DEVNULL, start_new_session=True)
                while True:
                    if scan.cancel.is_set():
                        self._terminate(process)
                        with self._lock:
                            scan.result = {"state": "cancelled", "message": "Scan arrêté.", "frames": scan.result.get("frames", 0), "codes": []}
                        break
                    if time.monotonic() - scan.started > (scan.seconds + 12 if scan.kind == "preview" else self.hard_timeout):
                        self._terminate(process)
                        with self._lock:
                            scan.result = {"state": "error", "message": "La caméra ne transmet pas d’image ou ne répond plus. Vérifiez son raccordement avant de réessayer.", "frames": scan.result.get("frames", 0), "codes": []}
                        break
                    try:
                        update = json.loads((scan.directory / "status.json").read_text())
                        if update.get("state") not in {"starting", "scanning", "found", "timeout", "error"}:
                            raise ValueError("État caméra invalide")
                        with self._lock:
                            if not scan.cancel.is_set():
                                scan.result = update
                    except (FileNotFoundError, json.JSONDecodeError):
                        pass
                    if process.poll() is not None:
                        with self._lock:
                            if scan.cancel.is_set():
                                scan.result = {"state": "cancelled", "message": "Scan arrêté.", "frames": scan.result.get("frames", 0), "codes": []}
                            elif scan.result["state"] in ACTIVE_STATES or process.returncode != 0:
                                scan.result = {"state": "error", "message": "La capture n’a pas pu démarrer. Vérifiez la caméra et fermez les autres applications qui l’utilisent.", "frames": scan.result.get("frames", 0), "codes": []}
                        break
                    time.sleep(0.12)
        except Exception:
            with self._lock:
                scan.result = {"state": "error", "message": "La capture caméra est indisponible. Réessayez après avoir vérifié la station.", "frames": 0, "codes": []}
        finally:
            if process is not None:
                self._terminate(process)
            with self._lock:
                scan.finished = time.monotonic()
                if not self._closed:
                    self._expiry = threading.Timer(RESULT_SECONDS, self._expire, args=(scan.id,))
                    self._expiry.daemon = True
                    self._expiry.start()

    def _expire(self, identifier):
        with self._lock:
            if self._scan and self._scan.id == identifier and not self._active(self._scan):
                self._scan.temporary.cleanup()
                self._scan = None

    def close(self):
        with self._lock:
            self._closed = True
            if self._expiry:
                self._expiry.cancel()
            scan = self._scan
            if scan:
                scan.cancel.set()
        if scan and scan.thread:
            scan.thread.join(timeout=6)
        with self._lock:
            if scan and not self._active(scan):
                scan.temporary.cleanup()
                self._scan = None
