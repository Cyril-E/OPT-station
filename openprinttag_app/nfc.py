"""Supervise bounded PC/SC operations without loading native NFC code in the API."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from .readers import ReaderUnavailable, WriteRejected, revision


class HardwareReader:
    name = "ACS ACR1552U-M1 · NFC-V"

    def __init__(self, backup_dir):
        self.backup_dir = Path(backup_dir)
        self.lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._process = None
        self._closed = False
        self._last_read = None
        self._status_time = 0
        self._status = {"name": self.name, "connected": False, "present": False, "simulated": False,
                        "message": "Vérification du lecteur…"}

    def _command(self):
        return [sys.executable, "-m", "openprinttag_app.nfc_worker"]

    def _run(self, operation, **values):
        timeout = {"status": 3, "read": 8, "write": 18}[operation]
        with self._process_lock:
            if self._closed:
                raise ReaderUnavailable("La station s’arrête. Relancez l’opération après son démarrage.")
            try:
                process = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True)
            except OSError as exc:
                raise ReaderUnavailable("Le processus de lecture NFC n’a pas pu démarrer.") from exc
            self._process = process
        try:
            try:
                stdout, _ = process.communicate(json.dumps({"operation": operation, **values}), timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise ReaderUnavailable("Le lecteur NFC n’a pas répondu dans le délai prévu. Relire le tag avant de réessayer.") from exc
            try:
                response = json.loads(stdout)
                if not isinstance(response, dict) or process.returncode != 0:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise ReaderUnavailable("La communication NFC a été interrompue. Relire le tag avant de réessayer.") from exc
            if not response.get("ok"):
                message = response.get("message", "Le lecteur NFC est indisponible.")
                if operation == "write" and not response.get("dirty", True):
                    code = {"conflict": 409, "protected": 423, "invalid": 422}.get(response.get("kind"), 503)
                    raise WriteRejected(message, code)
                raise ReaderUnavailable(message)
            return response["result"]
        finally:
            with self._process_lock:
                if self._process is process:
                    self._process = None

    def status(self):
        if not self.lock.acquire(blocking=False):
            return dict(self._status)
        try:
            if time.monotonic() - self._status_time >= 2:
                try:
                    self._status = {"name": self.name, "simulated": False, **self._run("status")}
                except ReaderUnavailable as exc:
                    self._status = {"name": self.name, "connected": False, "present": False,
                                    "simulated": False, "message": str(exc)}
                self._status_time = time.monotonic()
            return dict(self._status)
        finally:
            self.lock.release()

    def read(self):
        with self.lock:
            self._last_read = None
            result = self._run("read")
            result["image"] = bytes.fromhex(result["image"])
            self._last_read = result
            return dict(result)

    def write(self, image, *, reuse=False):
        with self.lock:
            current = self._last_read
            self._last_read = None
            if current is None:
                raise WriteRejected("Relire le tag avant de préparer son écriture.")
            self._run("write", image=bytes(image).hex(), expected_uid=current["uid"],
                      expected_revision=revision(current), backup_dir=str(self.backup_dir), reuse=reuse)
            self._status_time = 0

    def close(self):
        with self._process_lock:
            self._closed = True
            if self._process is not None:
                self._process.kill()
