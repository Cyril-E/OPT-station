"""PrusaLink en lecture seule, configuration privée et mesures sans effet sur le stock."""
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import (HTTPBasicAuthHandler, HTTPDigestAuthHandler,
                            HTTPPasswordMgrWithDefaultRealm, HTTPRedirectHandler,
                            ProxyHandler, Request, build_opener)
import uuid


class PrinterError(ValueError):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def address(value, camera=False):
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    try:
        parsed = urlsplit(value)
        allowed = {"http", "https", "rtsp"} if camera else {"http", "https"}
        if (parsed.scheme not in allowed or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or not 1 <= (parsed.port or 80) <= 65535
                or any(ord(c) < 33 for c in value) or "\\" in value):
            raise ValueError()
        if not camera and (parsed.path not in {"", "/"} or parsed.query):
            raise ValueError()
        try:
            ip = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            ip = None
        if ip and (ip.is_unspecified or ip.is_multicast or ip.is_loopback or ip.is_link_local):
            raise ValueError()
        if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
            raise ValueError()
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path if camera else "", parsed.query, ""))
    except ValueError as exc:
        raise PrinterError("Adresse invalide. Utilisez l’adresse réseau de l’appareil; saisissez les identifiants dans les champs séparés.", 422) from exc


class PrinterConfiguration:
    def __init__(self, directory):
        self.path = Path(directory) / "printer-settings.json"
        self.lock = threading.RLock()
        self._record = {"version": 1, "revision": 0,
                        "printer": {"enabled": False, "name": "Prusa CORE One", "url": "", "auth": "api_key", "username": "maker", "secret": ""},
                        "connect": {"printer_uuid": ""}, "cameras": []}
        if self.path.exists():
            try:
                record = json.loads(self.path.read_text())
                if record["version"] != 1 or not isinstance(record["revision"], int):
                    raise ValueError()
                self._record = self._normalize(record, record)
                self.path.chmod(0o600)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("Configuration imprimante invalide. Restaurer printer-settings.json depuis la sauvegarde privée.") from exc

    def record(self):
        with self.lock:
            return deepcopy(self._record)

    def public(self):
        record = self.record()
        return {"configured": record["printer"]["enabled"], "camera_count": len(record["cameras"])}

    def editable(self):
        record = self.record()
        for device in [record["printer"], *record["cameras"]]:
            device["secret_saved"] = bool(device.pop("secret", ""))
        record["camera_capture_available"] = shutil.which("ffmpeg") is not None
        record["connect"]["status"] = "planned"
        record["connect"]["inventory_sync_active"] = False
        return record

    @staticmethod
    def _secret(device, previous, changed):
        value = device.get("secret")
        if device.get("clear_secret") or (changed and value is None):
            return ""
        return previous.get("secret", "") if value is None else value

    def _normalize(self, body, old):
        p = body["printer"]
        url = address(p.get("url", ""))
        auth = p.get("auth", "api_key")
        username = p.get("username", "maker").strip()
        if auth not in {"api_key", "digest"}:
            raise PrinterError("Authentification PrusaLink invalide.", 422)
        changed = (url, auth, username) != tuple(old["printer"].get(k) for k in ("url", "auth", "username"))
        secret = self._secret(p, old["printer"], changed)
        if p["enabled"] and (not url or not secret or (auth == "digest" and not username)):
            raise PrinterError("Renseignez l’adresse et les identifiants avant d’activer PrusaLink. Après un changement d’adresse ou de compte, saisissez à nouveau le secret.", 422)
        cameras = []
        if len(body.get("cameras", [])) > 4:
            raise PrinterError("Quatre caméras au maximum.", 422)
        for c in body.get("cameras", []):
            identifier = c.get("id") or uuid.uuid4().hex
            if not isinstance(identifier, str) or not identifier.isalnum() or len(identifier) > 64 or any(x["id"] == identifier for x in cameras):
                raise PrinterError("Identifiant caméra invalide ou dupliqué.", 422)
            previous = next((x for x in old["cameras"] if x["id"] == identifier), {})
            camera_url = address(c.get("url", ""), camera=True)
            camera_auth = c.get("auth", "none")
            camera_username = c.get("username", "").strip()
            if camera_auth not in {"none", "basic", "digest"}:
                raise PrinterError("Authentification caméra invalide.", 422)
            different = (camera_url, camera_auth, camera_username) != tuple(previous.get(k) for k in ("url", "auth", "username"))
            camera_secret = self._secret(c, previous, different)
            if c.get("enabled", True) and (not camera_url or (camera_auth != "none" and (not camera_username or not camera_secret))):
                raise PrinterError("Renseignez l’adresse et, si nécessaire, les identifiants de chaque caméra active.", 422)
            if camera_url.startswith("rtsp:") and camera_auth == "digest":
                raise PrinterError("Pour RTSP, utilisez Sans identifiants ou Utilisateur et mot de passe.", 422)
            cameras.append({"id": identifier, "name": c.get("name", "Caméra").strip() or "Caméra", "enabled": c.get("enabled", True),
                            "url": camera_url, "auth": camera_auth, "username": camera_username, "secret": camera_secret})
        connect_uuid = body.get("connect", {}).get("printer_uuid", "").strip()
        if connect_uuid:
            try:
                connect_uuid = str(uuid.UUID(connect_uuid))
            except ValueError as exc:
                raise PrinterError("L’identifiant Prusa Connect doit être un UUID d’imprimante.", 422) from exc
        return {"version": 1, "revision": body["revision"],
                "printer": {"enabled": p["enabled"], "name": p.get("name", "Prusa CORE One").strip() or "Prusa CORE One",
                            "url": url, "auth": auth, "username": username, "secret": secret},
                "connect": {"printer_uuid": connect_uuid}, "cameras": cameras}

    def save(self, body):
        with self.lock:
            if body["revision"] != self._record["revision"]:
                raise PrinterError("Ces réglages ont changé depuis leur ouverture. Rechargez-les avant d’enregistrer.", 409)
            record = self._normalize(body, self._record)
            record["revision"] += 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile("w", dir=self.path.parent, prefix=".printer-", delete=False) as output:
                    temporary = Path(output.name)
                    os.fchmod(output.fileno(), 0o600)
                    json.dump(record, output, ensure_ascii=False, allow_nan=False)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
            self._record = record
            return self.editable()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_resource(url, auth="none", username="", secret="", limit=1_000_000, timeout=4):
    """GET borné sans proxy d’environnement, redirection ni diffusion des erreurs amont."""
    handlers = [NoRedirect(), ProxyHandler({})]
    headers = {"Accept": "application/json", "User-Agent": "OPT-Station/PrusaLink-readonly"}
    if auth == "api_key":
        headers["X-Api-Key"] = secret
    elif auth in {"digest", "basic"}:
        credentials = HTTPPasswordMgrWithDefaultRealm()
        credentials.add_password(None, url, username, secret)
        handlers.append((HTTPDigestAuthHandler if auth == "digest" else HTTPBasicAuthHandler)(credentials))
    try:
        with build_opener(*handlers).open(Request(url, headers=headers, method="GET"), timeout=timeout) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise PrinterError("Réponse de l’appareil trop volumineuse.")
            return response.status, response.headers.get_content_type(), data
    except HTTPError as exc:
        code = exc.code
        exc.close()
        if code in {401, 403}:
            raise PrinterError("Identifiants refusés par l’appareil. Vérifiez le mode d’authentification et le secret.", 502) from None
        if code == 404:
            raise PrinterError("Cette fonction n’est pas disponible sur l’appareil.", 404) from None
        raise PrinterError(f"L’appareil a refusé la lecture (HTTP {code}).", 502) from None
    except PrinterError:
        raise
    except (URLError, OSError, TimeoutError, ValueError):
        raise PrinterError("Appareil injoignable ou délai dépassé. Vérifiez l’adresse et le réseau.") from None


def numeric(value, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    if low is not None and value < low or high is not None and value > high:
        return None
    return value


def text(value, maximum=250):
    return value[:maximum] if isinstance(value, str) else None


def thumbnail_path(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path.startswith("/thumb/")
            or ".." in unquote(parsed.path) or "\\" in unquote(parsed.path) or len(value) > 1200):
        return None
    return parsed.path


class PrusaLinkMonitor:
    def __init__(self, configuration, fetch=read_resource, clock=time.monotonic):
        self.configuration, self.fetch, self.clock = configuration, fetch, clock
        self.lock = threading.RLock()
        self._revision = None
        self._last_attempt = float("-inf")
        self._last_good = None
        self._error = None
        self._identity = {}
        self._identity_at = float("-inf")

    def _json(self, p, path, optional=False):
        try:
            status, _, data = self.fetch(p["url"] + path, p["auth"], p["username"], p["secret"])
            if status == 204:
                return None
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except PrinterError as exc:
            if optional and exc.status_code == 404:
                return {}
            raise
        except (ValueError, UnicodeError):
            raise PrinterError("Réponse PrusaLink illisible. Vérifiez la compatibilité du firmware.", 502) from None

    def snapshot(self, force=False):
        with self.lock:
            record = self.configuration.record()
            p = record["printer"]
            if record["revision"] != self._revision:
                self._revision = record["revision"]
                self._last_attempt = self._identity_at = float("-inf")
                self._last_good, self._error, self._identity = None, None, {}
            base = {"configured": p["enabled"], "name": p["name"], "read_only": True, "configuration_revision": record["revision"],
                    "connect": {"prepared": bool(record["connect"]["printer_uuid"]), "inventory_sync_active": False,
                                "message": "Consommation Connect en préparation. Le stock reste basé sur la dernière lecture NFC."},
                    "cameras": [{"id": c["id"], "name": c["name"]} for c in record["cameras"] if c["enabled"]]}
            if not p["enabled"]:
                return {**base, "connected": False, "stale": False, "message": "Configurez PrusaLink dans Configuration pour démarrer le suivi."}
            stamp = self.clock()
            delay = 15 if self._error else 5
            if stamp - self._last_attempt >= (1 if force else delay):
                self._last_attempt = stamp
                try:
                    if stamp - self._identity_at >= 300:
                        version = self._json(p, "/api/version", optional=True) or {}
                        info = self._json(p, "/api/v1/info", optional=True) or {}
                        self._identity = {"model": text(version.get("printertype")) or "Prusa CORE One", "firmware": text(version.get("firmware")),
                                          "hostname": text(info.get("hostname")), "nozzle_diameter": numeric(info.get("nozzle_diameter"), 0)}
                        self._identity_at = stamp
                    status = self._json(p, "/api/v1/status")
                    job = self._json(p, "/api/v1/job")
                    if not isinstance(status, dict) or not isinstance(status.get("printer"), dict) or not isinstance(status["printer"].get("state"), str):
                        raise PrinterError("Réponse PrusaLink incomplète : état de l’imprimante absent.", 502)
                    printer = status["printer"]
                    stats = status.get("job") if isinstance(status.get("job"), dict) else {}
                    status_id = stats.get("id")
                    status_id = status_id if type(status_id) is int and status_id >= 0 else None
                    job_id = job.get("id") if job else None
                    job_id = job_id if type(job_id) is int and job_id >= 0 else None
                    consistent = not job or status_id is None or status_id == job_id
                    # Une nouvelle impression peut démarrer entre les deux GET.
                    if job and stats.get("id") != job.get("id"):
                        stats = {}
                    file = job.get("file", {}) if job else {}
                    if not isinstance(file, dict):
                        file = {}
                    refs = file.get("refs", {})
                    thumb = thumbnail_path(refs.get("thumbnail")) if isinstance(refs, dict) else None
                    normalized = {key: numeric(printer.get(key)) for key in
                                  ("temp_nozzle", "target_nozzle", "temp_bed", "target_bed", "axis_z", "speed", "flow", "fan_hotend", "fan_print")}
                    normalized["state"] = text(printer["state"], 40)
                    notice = printer.get("status_printer")
                    normalized["message"] = text(notice.get("message"), 500) if isinstance(notice, dict) and notice.get("ok") is False else None
                    self._last_good = {"observed_at": datetime.now(timezone.utc).isoformat(), "identity": self._identity,
                                       "printer": normalized,
                                       "job": {"id": job_id, "status_id": status_id, "state": text(job.get("state"), 40) if job else None,
                                               "consistent": consistent, "filename": text(file.get("display_name")) or text(file.get("name")),
                                               "progress": numeric(stats.get("progress"), 0, 100) if job else None,
                                               "time_printing": numeric(stats.get("time_printing"), 0) if job else None,
                                               "time_remaining": numeric(stats.get("time_remaining"), 0) if job else None,
                                               "thumbnail_available": bool(thumb)}, "_thumbnail": thumb}
                    self._error = None
                except PrinterError as exc:
                    self._error = str(exc)
            value = deepcopy(self._last_good or {})
            value.pop("_thumbnail", None)
            return {**base, **value, "connected": self._error is None and self._last_good is not None,
                    "stale": self._error is not None and self._last_good is not None,
                    "message": self._error or "Suivi PrusaLink en lecture seule. Actualisation toutes les 5 secondes."}

    def thumbnail(self):
        with self.lock:
            state = self.snapshot()
            path = (self._last_good or {}).get("_thumbnail")
            if not path or not state["connected"]:
                raise PrinterError("Miniature indisponible.", 404)
            p = self.configuration.record()["printer"]
            _, mime, data = self.fetch(p["url"] + path, p["auth"], p["username"], p["secret"], limit=2_000_000)
            return checked_image(mime, data)


def checked_image(mime, data):
    if mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff") or mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return mime, data
    raise PrinterError("L’appareil n’a pas fourni une image JPEG ou PNG valide.", 502)
