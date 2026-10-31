"""Bounded, local camera scans in a separate process.

The web server never imports the Pi camera stack. A stuck native capture can be
terminated without blocking the API. Images and unconfirmed QR text stay in one
private temporary directory, discarded at the next scan or on shutdown.
"""
from dataclasses import dataclass, field
import importlib.util
import json
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


class CameraUnavailable(Exception):
    pass


class CameraBusy(Exception):
    pass


@dataclass
class Scan:
    id: str
    temporary: tempfile.TemporaryDirectory
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    result: dict = field(default_factory=lambda: {"state": "starting", "message": "Ouverture de la caméra…", "frames": 0, "codes": []})
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    @property
    def directory(self):
        return Path(self.temporary.name)


class CameraScanner:
    def __init__(self, enabled=False, *, scan_seconds=SCAN_SECONDS, hard_timeout=None):
        self.enabled = enabled
        self.scan_seconds = scan_seconds
        self.hard_timeout = hard_timeout if hard_timeout is not None else scan_seconds + 12
        self._lock = threading.RLock()
        self._scan: Scan | None = None
        self._closed = False
        self._expiry: threading.Timer | None = None
        self._devices_cache = None
        self._devices_time = 0

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
                      remaining_seconds=result.get("remaining_seconds", max(0, round(self.scan_seconds - (time.monotonic() - scan.started)))),
                      preview_ready=(scan.directory / "preview.jpg").is_file())
        return result

    def start(self):
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
            scan = Scan(secrets.token_urlsafe(18), tempfile.TemporaryDirectory(prefix="openprinttag-qr-"))
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
                process = subprocess.Popen(self._command(scan.directory), stdout=log, stderr=log,
                                           stdin=subprocess.DEVNULL, start_new_session=True)
                while True:
                    if scan.cancel.is_set():
                        self._terminate(process)
                        with self._lock:
                            scan.result = {"state": "cancelled", "message": "Scan arrêté.", "frames": scan.result.get("frames", 0), "codes": []}
                        break
                    if time.monotonic() - scan.started > self.hard_timeout:
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
