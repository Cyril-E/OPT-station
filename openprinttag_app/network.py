"""Partage du réseau local persistant, activable depuis Configuration sans code."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading

MODES = {"disabled", "inventory", "full"}


def lan_host():
    """Relever l’adresse de sortie sans envoyer de paquet ni dépendre du DNS."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("192.0.2.1", 9))
            return connection.getsockname()[0]
    except OSError:
        return socket.gethostname().split(".")[0] + ".local"


class NetworkAccessError(ValueError):
    def __init__(self, message, status_code=403):
        super().__init__(message)
        self.status_code = status_code


class NetworkAccess:
    def __init__(self, directory, enabled=False, url=""):
        self.configured, self.url = enabled, url
        self.settings_path = Path(directory) / "network-settings.json"
        self.mode = "inventory"
        self._lock = threading.RLock()
        if self.settings_path.exists():
            try:
                record = json.loads(self.settings_path.read_text())
                if type(record["version"]) is not int or record["version"] not in {1, 2} or record["mode"] not in MODES:
                    raise ValueError()
                # L'ancien mode complet demandait un code. Son ouverture sans
                # code doit être choisie explicitement, plutôt que déduite.
                self.mode = "inventory" if record["version"] == 1 and record["mode"] == "full" else record["mode"]
                self.settings_path.chmod(0o600)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("La configuration des accès distants est invalide. Restaurer network-settings.json avant de relancer la station.") from exc

    @property
    def enabled(self):
        return self.configured and self.mode == "full"

    def snapshot(self):
        with self._lock:
            return {"configured": self.configured, "mode": self.mode, "enabled": self.enabled, "url": self.url}

    def set_mode(self, mode):
        with self._lock:
            if mode not in MODES:
                raise NetworkAccessError("Mode d’accès distant invalide.", 422)
            if mode != "disabled" and not self.configured:
                raise NetworkAccessError("Relancez d’abord la station avec --lan pour activer l’écoute sur le réseau.", 409)
            self._save_json(self.settings_path, {"version": 2, "mode": mode})
            self.mode = mode
            return self.snapshot()

    @staticmethod
    def _save_json(path, record):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".network-", delete=False) as output:
                temporary = Path(output.name)
                os.fchmod(output.fileno(), 0o600)
                json.dump(record, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
