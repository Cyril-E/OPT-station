"""Explicit, confirmed Pi power requests through logind, without forced stops."""
import secrets
import shlex
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

METHODS = {"poweroff": ("CanPowerOff", "PowerOff"), "reboot": ("CanReboot", "Reboot")}
BUS = ["/usr/bin/busctl", "--system", "--allow-interactive-authorization=no", "--timeout=5", "call",
       "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager"]


class PowerError(ValueError):
    def __init__(self, message, status_code=409, uncertain=False):
        super().__init__(message)
        self.status_code = status_code
        self.uncertain = uncertain


class LogindPower:
    def __init__(self, enabled=False):
        self.supported = False
        if enabled and sys.platform == "linux":
            try:
                self.supported = Path("/proc/device-tree/model").read_text().startswith("Raspberry Pi")
            except OSError:
                pass

    def capabilities(self):
        result = {"supported": self.supported, "actions": {name: False for name in METHODS},
                  "message": "Ces commandes sont disponibles sur le Raspberry Pi en mode matériel."}
        if not self.supported:
            return result
        try:
            for name, (query, _) in METHODS.items():
                response = subprocess.run([*BUS, query], capture_output=True, text=True, timeout=7, check=True)
                values = shlex.split(response.stdout)
                result["actions"][name] = values == ["s", "yes"]
            result["message"] = ("Arrêt et redémarrage autorisés par le système." if all(result["actions"].values())
                                 else "Une action n’est pas autorisée ou est bloquée par le système. Actualisez depuis le service du Pi; aucune autorisation n’est contournée.")
        except (OSError, ValueError, subprocess.SubprocessError):
            result["actions"] = {name: False for name in METHODS}
            result["message"] = "Impossible de vérifier les droits d’arrêt du Pi. Vérifiez que son service est démarré."
        return result

    def request(self, action):
        if not self.supported or action not in METHODS:
            raise PowerError("Action système indisponible.", 422)
        try:
            # interactive=false: never display a password prompt or ignore an inhibitor.
            subprocess.run([*BUS, METHODS[action][1], "b", "false"],
                           capture_output=True, text=True, timeout=8, check=True)
        except subprocess.TimeoutExpired:
            raise PowerError("Le Pi n’a pas confirmé la demande. Vérifiez son état avant toute nouvelle action.", 503, uncertain=True) from None
        except (OSError, subprocess.CalledProcessError):
            raise PowerError("Le système a refusé la demande d’arrêt ou de redémarrage. Vérifiez ses autorisations et les opérations en cours.", 503) from None


class StationPower:
    def __init__(self, backend, busy=lambda: False, clock=time.monotonic):
        self.backend, self.busy, self.clock = backend, busy, clock
        self.lock = threading.RLock()
        self.operations = 0
        self.tokens = OrderedDict()
        self.instance = secrets.token_urlsafe(18)
        self.phase, self.action, self.message = "idle", None, ""

    def _pending(self):
        return self.phase in {"requested", "executing", "accepted", "uncertain"}

    def state(self):
        with self.lock:
            return {"phase": self.phase, "action": self.action, "pending": self._pending(),
                    "message": self.message, "instance_id": self.instance}

    def snapshot(self):
        capabilities = self.backend.capabilities()
        state = self.state()
        with self.lock:
            busy = bool(self.operations or self.busy())
        return {**capabilities, **state, "busy": busy, "message": state["message"] or capabilities["message"]}

    def enter_operation(self):
        with self.lock:
            if self._pending():
                raise PowerError("Le Pi s’arrête ou redémarre. Aucune nouvelle opération n’est lancée.", 503)
            self.operations += 1

    def leave_operation(self):
        with self.lock:
            self.operations -= 1

    def _ready(self):
        if self._pending():
            raise PowerError("Une demande d’arrêt ou de redémarrage est déjà en cours.")
        if self.operations or self.busy():
            raise PowerError("Une opération est en cours. Attendez la fin de l’écriture NFC ou de l’impression, et arrêtez le scan QR avant de réessayer.")

    def _allowed(self, action):
        if action not in METHODS:
            raise PowerError("Action système invalide.", 422)
        capabilities = self.backend.capabilities()
        if not capabilities["supported"] or not capabilities["actions"].get(action):
            raise PowerError(capabilities["message"], 503)

    def prepare(self, action):
        self._allowed(action)
        with self.lock:
            self._ready()
            if self.phase == "failed":
                self.phase, self.action, self.message = "idle", None, ""
            stamp = self.clock()
            self.tokens = OrderedDict((key, value) for key, value in self.tokens.items() if value[1] > stamp)
            while len(self.tokens) >= 16:
                self.tokens.popitem(last=False)
            token = secrets.token_urlsafe(24)
            self.tokens[token] = (action, stamp + 120)
            return {"confirmation_token": token, "action": action, "expires_in_seconds": 120}

    def confirm(self, action, token):
        self._allowed(action)
        with self.lock:
            expected = self.tokens.get(token)
            if not expected or expected[0] != action or expected[1] <= self.clock():
                raise PowerError("La confirmation a expiré ou a déjà été utilisée. Reprenez le bouton dans Configuration.")
            self._ready()
            del self.tokens[token]
            self.tokens.clear()
            self.phase, self.action = "requested", action
            self.message = "Arrêt du Pi demandé…" if action == "poweroff" else "Redémarrage du Pi demandé…"
            return self.state()

    def execute(self):
        with self.lock:
            if self.phase != "requested":
                return
            self.phase = "executing"
            action = self.action
        try:
            self.backend.request(action)
        except Exception as exc:
            with self.lock:
                self.phase = "uncertain" if getattr(exc, "uncertain", True) else "failed"
                self.message = str(exc) if isinstance(exc, PowerError) else "La demande système n’a pas été confirmée. Vérifiez l’état du Pi; aucune nouvelle demande n’est envoyée."
        else:
            with self.lock:
                self.phase = "accepted"
                self.message = "Le système a accepté l’arrêt du Pi." if action == "poweroff" else "Le système a accepté le redémarrage du Pi."
