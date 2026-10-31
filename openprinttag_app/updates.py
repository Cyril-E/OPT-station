"""Opt-in GitHub release detection. No downloads, installs or system commands."""
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from packaging.version import InvalidVersion, Version

from . import __version__
from .network import NetworkAccess
from .storage import ConflictError

DEFAULT_REPOSITORY = "Cyril-E/OPT-station"
MAX_BODY = 2 * 1024 * 1024


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


def version(value):
    try:
        parsed = Version(value.removeprefix("v"))
        return Version(parsed.public)  # Local build labels do not imply a newer release.
    except (InvalidVersion, AttributeError, TypeError):
        return None


def validate(record):
    keys = {"version", "revision", "enabled", "repository", "interval_hours", "include_prereleases", "token"}
    if (not isinstance(record, dict) or set(record) != keys or type(record["version"]) is not int or record["version"] != 1
            or type(record["revision"]) is not int or record["revision"] < 0
            or type(record["enabled"]) is not bool or type(record["include_prereleases"]) is not bool
            or type(record["interval_hours"]) is not int or not 1 <= record["interval_hours"] <= 168
            or not isinstance(record["repository"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", record["repository"])
            or record["repository"].split("/")[1] in {".", ".."}
            or not isinstance(record["token"], str) or record["token"] and not re.fullmatch(r"[A-Za-z0-9_]{10,512}", record["token"])):
        raise ValueError("Réglages de recherche de versions invalides.")
    return deepcopy(record)


class UpdateConfiguration:
    def __init__(self, directory):
        self.path = Path(directory) / "updates-settings.json"
        self.record = {"version": 1, "revision": 0, "enabled": False, "repository": DEFAULT_REPOSITORY,
                       "interval_hours": 6, "include_prereleases": True, "token": ""}
        if self.path.exists():
            try:
                self.record = validate(json.loads(self.path.read_bytes()))
                self.path.chmod(0o600)
            except (ValueError, TypeError, KeyError):
                raise ValueError("La configuration des mises à jour est invalide. Restaurez updates-settings.json avant de relancer la station.") from None

    def public(self):
        record = deepcopy(self.record)
        record["token_saved"] = bool(record.pop("token"))
        return record


class UpdateFailure(Exception):
    def __init__(self, code, retry_after=900):
        self.code, self.retry_after = code, retry_after


MESSAGES = {
    "network": "GitHub est injoignable. La dernière vérification réussie est conservée.",
    "access": "Dépôt introuvable ou privé. Vérifiez son nom et renseignez un jeton autorisé à lire ce dépôt.",
    "token": "Le jeton GitHub est refusé ou a expiré. Remplacez-le dans Configuration.",
    "permissions": "GitHub refuse cet accès. Vérifiez les droits de lecture du jeton sur ce dépôt.",
    "rate_limit": "La limite GitHub est atteinte. La station attendra l’heure de reprise indiquée.",
    "response": "La réponse de GitHub est invalide. Aucune version à jour ne peut être confirmée.",
    "incomplete": "La liste des versions est trop longue ou incomplète. Aucune version à jour ne peut être confirmée.",
    "storage": "Le résultat de vérification n’a pas pu être enregistré sur le Pi.",
    "moved": "Le dépôt GitHub a changé d’adresse. Mettez à jour son nom dans Configuration.",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_request(url, headers, timeout):
    # Fixed HTTPS origin, verified TLS, no redirects or proxy credential forwarding.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(Request(url, headers=headers), timeout=timeout) as response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise UpdateFailure("response")
            return response.status, dict(response.headers), body
    except HTTPError as exc:
        return exc.code, dict(exc.headers), b""  # Never echo response bodies or credentials.
    except (URLError, OSError, TimeoutError):
        raise UpdateFailure("network") from None


def release(item, repository):
    if not isinstance(item, dict) or item.get("draft") is not False or type(item.get("prerelease")) is not bool:
        return None
    tag, published, url = item.get("tag_name"), item.get("published_at"), item.get("html_url")
    if not isinstance(tag, str) or len(tag) > 100 or version(tag) is None or not isinstance(published, str) or not isinstance(url, str):
        return None
    try:
        if datetime.fromisoformat(published.replace("Z", "+00:00")).tzinfo is None:
            return None
        parsed = urlsplit(url)
        prefix = f"/{repository}/releases/tag/"
        if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
                or not parsed.path.casefold().startswith(prefix.casefold()) or unquote(parsed.path[len(prefix):]) != tag):
            return None
    except (ValueError, TypeError):
        return None
    name = item.get("name")
    return {"tag": tag, "version": str(version(tag)), "name": name[:200] if isinstance(name, str) else tag,
            "url": url, "published_at": published,
            "prerelease": item["prerelease"] or version(tag).is_prerelease or version(tag).is_devrelease}


def next_page(link, repository):
    if not link:
        return None
    for url, relation in re.findall(r'<([^>]+)>\s*;\s*rel="([^"]+)"', link):
        if relation != "next":
            continue
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if (parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.fragment
                or parsed.path.casefold() != f"/repos/{repository}/releases".casefold()
                or set(query) != {"page", "per_page"} or query["per_page"] != ["100"]
                or len(query["page"]) != 1 or not re.fullmatch(r"[1-9][0-9]{0,5}", query["page"][0])):
            raise UpdateFailure("response")
        return url
    if 'rel="next"' in link:
        raise UpdateFailure("response")
    return None


class ReleaseMonitor:
    def __init__(self, directory, fetch=github_request, installed=__version__, clock=time.time, allowed=lambda: True):
        self.directory = Path(directory)
        self.path = self.directory / "updates-state.json"
        self.configuration = UpdateConfiguration(directory)
        self.fetch, self.installed, self.clock, self.allowed = fetch, installed, clock, allowed
        self.lock = threading.RLock()
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.worker = None
        self.checking = False
        self.generation = 0
        self.state = {}
        if self.path.exists():
            try:
                record = json.loads(self.path.read_bytes())
                if record.get("revision") == self.configuration.record["revision"]:
                    if not isinstance(record.get("pages", {}), dict):
                        raise ValueError()
                    for key in ("next_at", "retry_at"):
                        if type(record.get(key, 0)) not in {int, float} or not math.isfinite(record.get(key, 0)) or not 0 <= record.get(key, 0) <= 253402300799:
                            raise ValueError()
                    latest = record.get("latest")
                    if latest is not None:
                        sanitized = release({"draft": False, "prerelease": latest["prerelease"], "tag_name": latest["tag"],
                                             "published_at": latest["published_at"], "html_url": latest["url"], "name": latest["name"]}, self.configuration.record["repository"])
                        if not sanitized:
                            raise ValueError()
                        record["latest"] = sanitized
                    self.state = record
            except (ValueError, TypeError, AttributeError, KeyError):
                pass

    def snapshot(self):
        with self.lock:
            enabled = self.configuration.record["enabled"]
            latest = self.state.get("latest") if enabled else None
            parsed = version(latest.get("tag")) if isinstance(latest, dict) else None
            installed = version(self.installed)
            available = parsed > installed if parsed is not None and installed is not None else None
            return {"enabled": enabled, "revision": self.configuration.record["revision"], "installed_version": self.installed,
                    "repository": self.configuration.record["repository"], "checking": self.checking,
                    "phase": "disabled" if not enabled else "checking" if self.checking else self.state.get("phase", "not_checked"),
                    "latest": deepcopy(latest), "update_available": available,
                    "comparison": "ahead" if parsed and installed and installed > parsed else "current" if available is False else None,
                    "checked_at": self.state.get("checked_at"), "last_attempt_at": self.state.get("last_attempt_at"),
                    "next_check_at": stamp(self.state.get("next_at", 0)) if enabled else None,
                    "error_code": self.state.get("error"), "message": MESSAGES.get(self.state.get("error"), ""),
                    "stale": bool(latest and self.state.get("error")),
                    "retry_allowed_at": stamp(self.state.get("retry_at", 0))}

    def settings(self):
        with self.lock:
            return {**self.configuration.public(), "status": self.snapshot()}

    def save(self, body):
        with self.lock:
            old = self.configuration.record
            if body["revision"] != old["revision"]:
                raise ConflictError("Les réglages de mise à jour ont changé. Rechargez-les avant d’enregistrer.")
            token = "" if body.get("clear_token") else old["token"] if body.get("token") is None else body["token"]
            if body["repository"].casefold() != old["repository"].casefold() and body.get("token") is None:
                token = ""  # Credentials must be chosen explicitly for a new repository.
            record = validate({**old, **{k: v for k, v in body.items() if k not in {"token", "clear_token"}}, "revision": old["revision"] + 1, "token": token})
            NetworkAccess._save_json(self.configuration.path, record)
            self.configuration.record = record
            self.generation += 1
            cooldown = self.state.get("retry_at", 0) if token == old["token"] else 0
            self.state = {"revision": record["revision"], "retry_at": cooldown, "next_at": cooldown}
            self._persist()
            self.wake.set()
            return self.settings()

    def reload(self):
        with self.lock:
            self.configuration = UpdateConfiguration(self.directory)
            self.generation += 1
            self.state = {"revision": self.configuration.record["revision"]}
            self._persist()
            self.wake.set()

    def _persist(self):
        try:
            NetworkAccess._save_json(self.path, self.state)
        except OSError:
            self.state["error"] = "storage"

    def request_check(self):
        with self.lock:
            if not self.configuration.record["enabled"]:
                raise ConflictError("Activez la recherche de mises à jour avant de vérifier GitHub.")
            if self.checking:
                return self.snapshot()
            if self.clock() < self.state.get("retry_at", 0):
                raise ConflictError("La prochaine vérification GitHub n’est pas encore autorisée. Attendez l’heure de reprise indiquée.")
            self.state["next_at"] = 0
            self.wake.set()
            return self.snapshot()

    def _fetch_releases(self, configuration, cache):
        repository = configuration["repository"]
        url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page=1"
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "OPT-Station/" + self.installed}
        if configuration["token"]:
            headers["Authorization"] = "Bearer " + configuration["token"]
        pages, releases, visited = {}, [], set()
        deadline = time.monotonic() + 30
        for _ in range(10):
            if url in visited or time.monotonic() >= deadline:
                raise UpdateFailure("incomplete")
            visited.add(url)
            previous = cache.get(url, {})
            request_headers = dict(headers)
            if previous.get("etag"):
                request_headers["If-None-Match"] = previous["etag"]
            status, response_headers, body = self.fetch(url, request_headers, min(8, max(.1, deadline - time.monotonic())))
            response_headers = {key.lower(): value for key, value in response_headers.items()}
            if status in {403, 429} and (status == 429 or response_headers.get("x-ratelimit-remaining") == "0" or response_headers.get("retry-after")):
                retry = 60
                try:
                    value = response_headers.get("retry-after", "")
                    if value:
                        retry = max(retry, int(value) if value.isdigit() else parsedate_to_datetime(value).timestamp() - self.clock())
                    retry = max(retry, float(response_headers.get("x-ratelimit-reset", 0)) - self.clock())
                except (ValueError, TypeError, OverflowError):
                    pass
                if not math.isfinite(retry) or retry > 253402300799 - self.clock():
                    retry = 900
                raise UpdateFailure("rate_limit", retry)
            if status == 401: raise UpdateFailure("token")
            if status == 404: raise UpdateFailure("access")
            if status == 403: raise UpdateFailure("permissions")
            if status in {301, 302, 307, 308}: raise UpdateFailure("moved")
            if status == 304:
                if not previous or not previous.get("etag") or not isinstance(previous.get("items"), list):
                    raise UpdateFailure("response")
                page = previous
            elif status == 200:
                if len(body) > MAX_BODY:
                    raise UpdateFailure("response")
                try:
                    raw = json.loads(body)
                    if not isinstance(raw, list) or len(raw) > 100:
                        raise ValueError()
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    raise UpdateFailure("response") from None
                items = []
                for value in raw:
                    item = release(value, repository)
                    if item:
                        items.append(item)
                etag = response_headers.get("etag", "")
                if len(etag) > 512 or any(ord(c) < 32 for c in etag):
                    etag = ""
                page = {"items": items, "etag": etag, "next": next_page(response_headers.get("link", ""), repository)}
            else:
                raise UpdateFailure("network" if status >= 500 else "response")
            pages[url] = page
            releases.extend(x for x in page["items"] if configuration["include_prereleases"] or not x["prerelease"])
            url = page.get("next")
            if not url:
                latest = max(releases, key=lambda item: version(item["tag"])) if releases else None
                return latest, pages
            # Cached links are revalidated too, never followed to another origin.
            next_page(f'<{url}>; rel="next"', repository)
        raise UpdateFailure("incomplete")

    def tick(self):
        with self.lock:
            if (self.checking or not self.configuration.record["enabled"] or not self.allowed()
                    or self.clock() < max(self.state.get("next_at", 0), self.state.get("retry_at", 0))):
                return
            self.checking = True
            configuration, generation = deepcopy(self.configuration.record), self.generation
            previous = deepcopy(self.state)
        try:
            latest, pages = self._fetch_releases(configuration, previous.get("pages", {}))
            result = {"revision": configuration["revision"], "phase": "ok", "latest": latest, "pages": pages,
                      "checked_at": stamp(self.clock()), "last_attempt_at": stamp(self.clock()),
                      "next_at": self.clock() + configuration["interval_hours"] * 3600, "retry_at": self.clock() + 60}
        except Exception as exc:
            code = exc.code if isinstance(exc, UpdateFailure) else "response"
            failures = previous.get("failures", 0) + 1
            delay = exc.retry_after if isinstance(exc, UpdateFailure) else 900
            if code != "rate_limit":
                delay = min(21600, max(delay, 900 * 2 ** min(failures - 1, 5)))
            result = {**previous, "revision": configuration["revision"], "phase": "error", "error": code,
                      "failures": failures, "last_attempt_at": stamp(self.clock()),
                      "next_at": self.clock() + delay, "retry_at": self.clock() + delay}
        with self.lock:
            self.checking = False
            if self.generation == generation:
                self.state = result
                self._persist()

    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            self.stop_event.clear()
            def loop():
                while not self.stop_event.is_set():
                    self.tick()
                    self.wake.wait(20)
                    self.wake.clear()
            self.worker = threading.Thread(target=loop, name="opt-release-check", daemon=True)
            self.worker.start()

    def close(self):
        with self.lock:
            self.generation += 1
        self.stop_event.set(); self.wake.set()
        if self.worker:
            self.worker.join(timeout=9)
