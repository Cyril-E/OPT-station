"""Official SIWC public-client OAuth and streamed Responses, owned by this station."""
from contextlib import contextmanager
from copy import deepcopy
import base64
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .backups import private_json

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
JWKS = ISSUER + "/.well-known/jwks.json"
REVOKE = ISSUER + "/api/accounts/oauth/revoke"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT = "chatgpt.tokens.use.direct"
MAX_JSON = 2 * 1024 * 1024
ATTEMPT_SECONDS = 600


class ChatGPTError(ValueError):
    def __init__(self, message, status_code=422, code=None, request_id=None, api_status=None):
        super().__init__(message)
        self.status_code, self.code, self.request_id = status_code, code, request_id
        self.api_status = api_status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def failure(status, value=None, request_id=None):
    error = value.get("error", value) if isinstance(value, dict) else {}
    code = error.get("code") if isinstance(error, dict) else error if isinstance(error, str) else None
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", code):
        code = None
    messages = {
        "subscription_sharing_usage_limit_exceeded": "La limite d’utilisation ChatGPT de cette application est atteinte. Consultez les limites dans ChatGPT.",
        "subscription_sharing_user_not_eligible": "Ce compte ou cet espace ChatGPT n’autorise pas l’utilisation de son abonnement par OPT Station.",
        "subscription_sharing_unsupported_capability": "Le modèle ou une fonction demandée n’est pas disponible avec cette connexion ChatGPT.",
        "subscription_sharing_route_not_supported": "Cette fonction n’est pas disponible avec la connexion ChatGPT.",
    }
    message = messages.get(code) or {
        400: "ChatGPT refuse cette demande. Vérifiez le modèle et les autorisations de l’application.",
        401: "La connexion ChatGPT doit être renouvelée. Reconnectez ce compte dans les paramètres.",
        403: "Le compte ou l’espace ChatGPT refuse cette autorisation.",
        429: "Une limite ChatGPT est atteinte. Consultez l’utilisation du compte avant de réessayer.",
    }.get(status, "ChatGPT est momentanément indisponible. Réessayez plus tard.")
    request_id = request_id if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", request_id) else None
    return ChatGPTError(message, 503, code, request_id, status)


def transport(method, url, body=None, token=None, stream=False):
    """Fixed official endpoints, bounded responses, no proxy/redirect credential forwarding."""
    if url not in {DISCOVERY, JWKS, TOKEN, REVOKE, RESOURCE + "/models", RESOURCE + "/responses"}:
        raise ChatGPTError("Adresse du service ChatGPT invalide.")
    headers = {"User-Agent": "OPT-Station", "Accept": "text/event-stream" if stream else "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        form = url in {TOKEN, REVOKE}
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        data = urlencode(body).encode() if form else json.dumps(body).encode()
    request = Request(url, method=method, data=data, headers=headers)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=90 if stream else 20) as response:
            if stream:
                return completed_stream(response)
            raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ChatGPTError("La réponse ChatGPT est trop volumineuse.", 502)
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        try:
            value = json.loads(error.read(64 * 1024))
        except (ValueError, OSError):
            value = None
        raise failure(error.code, value, error.headers.get("x-request-id")) from None
    except (URLError, OSError, TimeoutError):
        raise ChatGPTError("ChatGPT est injoignable. Vérifiez la connexion Internet du Pi.", 503) from None
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ChatGPTError):
            raise
        raise ChatGPTError("La réponse ChatGPT est illisible.", 502) from None


def completed_stream(response):
    total, parts = 0, []
    while True:
        line = response.readline(MAX_JSON + 1)
        total += len(line)
        if len(line) > MAX_JSON or total > 8 * MAX_JSON:
            raise ChatGPTError("La réponse ChatGPT est trop volumineuse.", 502)
        if not line:
            break
        if line.rstrip(b"\r\n") == b"":
            if not parts:
                continue
            raw, parts = b"\n".join(parts), []
            if raw == b"[DONE]":
                break
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ChatGPTError("Le flux ChatGPT est illisible.", 502) from None
            if not isinstance(event, dict):
                raise ChatGPTError("Le flux ChatGPT est illisible.", 502)
            kind = event.get("type")
            if kind == "response.completed" and event.get("response", {}).get("status") == "completed":
                return event["response"]
            if kind in {"response.failed", "error"}:
                raise failure(503, event.get("response", event))
            if kind == "response.incomplete":
                raise ChatGPTError("L’analyse ChatGPT est incomplète. Relancez-la.", 502)
        elif line.startswith(b"data:"):
            parts.append(line[5:].strip())
    raise ChatGPTError("Le flux ChatGPT a été interrompu avant la fin de l’analyse.", 502)


def unbase64(value):
    if not isinstance(value, str) or len(value) > 32_000 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError()
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verified_identity(token, keys, client_id, nonce, now):
    try:
        head, payload, signature = token.split(".")
        header, claims = json.loads(unbase64(head)), json.loads(unbase64(payload))
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError()
        key = next(k for k in keys["keys"] if k.get("kid") == header["kid"] and k.get("kty") == "RSA" and k.get("alg", "RS256") == "RS256" and k.get("use", "sig") == "sig")
        public = rsa.RSAPublicNumbers(int.from_bytes(unbase64(key["e"]), "big"), int.from_bytes(unbase64(key["n"]), "big")).public_key()
        if public.key_size < 2048:
            raise ValueError()
        public.verify(unbase64(signature), (head + "." + payload).encode(), padding.PKCS1v15(), hashes.SHA256())
        audience = claims.get("aud")
        if (claims.get("iss") != ISSUER or client_id not in (audience if isinstance(audience, list) else [audience])
                or (isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != client_id)
                or type(claims.get("exp")) not in {int, float} or not math.isfinite(claims["exp"]) or claims["exp"] <= now
                or not secrets.compare_digest(str(claims.get("nonce", "")), nonce)
                or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 512):
            raise ValueError()
        for field in ("nbf", "iat"):
            if field in claims and (type(claims[field]) not in {int, float} or not math.isfinite(claims[field]) or claims[field] > now + 60):
                raise ValueError()
        return {"subject": claims["sub"], "email": str(claims.get("email", ""))[:254], "name": str(claims.get("name", ""))[:120]}
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError, InvalidSignature):
        raise ChatGPTError("L’identité renvoyée par ChatGPT n’a pas pu être vérifiée. Recommencez la connexion.", 400) from None


class ChatGPTConnection:
    def __init__(self, directory, fetch=transport, clock=time.time):
        self.path = Path(directory) / "chatgpt-credentials.json"
        self.lock_path = Path(directory) / ".chatgpt-credentials.lock"
        self.lock = threading.RLock()
        self.fetch, self.clock = fetch, clock
        self.pending, self.listeners = {}, []
        self.record = self._read()

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "revision": 0, "host_id": "", "active": None, "profiles": []}
        try:
            if self.path.is_symlink() or self.path.stat().st_size > MAX_JSON:
                raise ValueError()
            record = json.loads(self.path.read_bytes())
            if record["version"] != 1 or type(record["revision"]) is not int or record["revision"] < 0 or not isinstance(record["profiles"], list) or len(record["profiles"]) > 8:
                raise ValueError()
            if record["host_id"] != "urn:uuid:" + str(uuid.UUID(record["host_id"].removeprefix("urn:uuid:"))):
                raise ValueError()
            for profile in record["profiles"]:
                uuid.UUID(profile["id"])
                if (not isinstance(profile["client_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", profile["client_id"])
                        or profile["client_id"] == "dynamic_agent_client" or not isinstance(profile["subject"], str)
                        or not isinstance(profile.get("email"), str) or not isinstance(profile.get("label"), str)
                        or not isinstance(profile.get("tokens"), dict) or not isinstance(profile.get("scopes"), list)
                        or any(not isinstance(s, str) for s in profile["scopes"]) or not isinstance(profile.get("models"), list)
                        or type(profile.get("expires_at")) not in {int, float} or not math.isfinite(profile["expires_at"])):
                    raise ValueError()
                if profile["tokens"] and (set(profile["tokens"]) != {"access_token", "refresh_token", "id_token"}
                        or any(not isinstance(v, str) or len(v) > 32_000 for v in profile["tokens"].values())):
                    raise ValueError()
                if len(profile["models"]) > 200 or any(not isinstance(m, dict) or set(m) != {"slug", "display_name"} or not all(isinstance(v, str) for v in m.values()) for m in profile["models"]):
                    raise ValueError()
            if len({p["id"] for p in record["profiles"]}) != len(record["profiles"]):
                raise ValueError()
            if record["active"] is not None and not any(p["id"] == record["active"] for p in record["profiles"]):
                raise ValueError()
            self.path.chmod(0o600)
            return record
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ChatGPTError("Le fichier de connexion ChatGPT est invalide.", 503) from None

    @contextmanager
    def protected(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                if self.path.exists():
                    self.record = self._read()
                yield
            finally:
                os.close(fd)

    def _save(self):
        self.record["revision"] += 1
        private_json(self.path, self.record)

    def _profile(self, identifier=None):
        identifier = self.record["active"] if identifier is None else identifier
        return next((p for p in self.record["profiles"] if p["id"] == identifier), None)

    def public(self):
        with self.lock:
            profile = self._profile()
            connected = bool(profile and profile.get("tokens"))
            return {"revision": self.record["revision"], "active": self.record["active"], "connected": connected,
                    "plan_enabled": bool(connected and DIRECT in profile["scopes"]),
                    "profiles": [{"id": p["id"], "label": p["label"], "email": p["email"], "connected": bool(p.get("tokens"))} for p in self.record["profiles"]],
                    "models": deepcopy(profile.get("models", [])) if profile else [],
                    "usage_url": "https://chatgpt.com/settings/usage"}

    def busy(self):
        if not self.lock.acquire(blocking=False):
            return True
        try:
            return any(a["status"] == "exchanging" for a in self.pending.values())
        finally:
            self.lock.release()

    def select(self, identifier):
        with self.protected():
            if not self._profile(identifier):
                raise ChatGPTError("Compte ChatGPT introuvable.", 404)
            self.record["active"] = identifier
            self._save()
        return self.public()

    def start(self, identifier=None, consent=False, authorize=lambda: True):
        with self.protected():
            for attempt in self.pending.values():
                if attempt["expires"] <= self.clock() and attempt["status"] in {"pending", "exchanging"}:
                    attempt["status"] = "expired"
            if any(a["status"] in {"pending", "exchanging"} for a in self.pending.values()):
                raise ChatGPTError("Une connexion ChatGPT est déjà en cours. Terminez-la ou annulez-la.", 409)
            profile = self._profile(identifier) if identifier else None
            if identifier and not profile:
                raise ChatGPTError("Compte ChatGPT introuvable.", 404)
            if not identifier and len(self.record["profiles"]) >= 8:
                raise ChatGPTError("Huit comptes ChatGPT sont déjà enregistrés.")
            if not self.record["host_id"]:
                self.record["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self._save()
            attempt_id = secrets.token_urlsafe(24)
            owner = self

            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass  # Callback URLs contain authorization codes.

                def do_GET(self):
                    success = False
                    if len(self.path) <= 8192 and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}":
                        try:
                            owner.complete(attempt_id, f"http://127.0.0.1:{self.server.server_port}" + self.path)
                            success = True
                        except ChatGPTError:
                            pass
                    content = ("<!doctype html><html lang='fr'><meta charset='utf-8'><title>OPT Station</title><p>" +
                               ("Connexion terminée. Revenez dans OPT Station. / Sign-in complete. Return to OPT Station." if success else
                                "Connexion non validée. Revenez dans OPT Station. / Sign-in not validated. Return to OPT Station.") + "</p></html>").encode()
                    self.send_response(200 if success else 400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                    self.end_headers()
                    self.wfile.write(content)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
            server.daemon_threads = True
            verifier, state, nonce = (secrets.token_urlsafe(48) for _ in range(3))
            callback = f"http://127.0.0.1:{server.server_port}/auth/callback"
            attempt = {"status": "pending", "state": state, "nonce": nonce, "verifier": verifier, "callback": callback,
                       "client_id": profile["client_id"] if profile else None, "profile_id": profile["id"] if profile else None,
                       "subject": profile["subject"] if profile else None, "expires": self.clock() + ATTEMPT_SECONDS, "server": server,
                       "authorize": authorize}
            self.pending = {k: a for k, a in self.pending.items() if a["expires"] > self.clock()}
            if len(self.pending) >= 8:
                self.pending.pop(next(iter(self.pending)))
            self.pending[attempt_id] = attempt
            self.listeners.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            expiry = threading.Timer(ATTEMPT_SECONDS, lambda: self.cancel(attempt_id))
            expiry.daemon = True
            expiry.start()
            attempt["timer"] = expiry
            query = {"client_id": attempt["client_id"] or "dynamic_agent_client", "ext_agent_host_id": self.record["host_id"],
                     "response_type": "code", "redirect_uri": callback, "scope": SCOPES, "resource": RESOURCE,
                     "state": state, "nonce": nonce, "code_challenge_method": "S256",
                     "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
            if not profile:
                query["agent_name_hint"] = "OPT Station"
            if consent:
                query["prompt"] = "consent"
            attempt["authorization_url"] = AUTHORIZE + "?" + urlencode(query)
            return self._handoff(attempt_id, attempt)

    def _handoff(self, identifier, attempt):
        return {"attempt_id": identifier, "authorization_url": attempt["authorization_url"], "callback_uri": attempt["callback"],
                "expires_in_seconds": max(0, int(attempt["expires"] - self.clock()))}

    def resume(self):
        """Recover the station's live attempt after navigation, without browser storage."""
        with self.lock:
            for identifier, attempt in reversed(list(self.pending.items())):
                if attempt["status"] in {"pending", "exchanging"}:
                    if attempt["expires"] <= self.clock():
                        attempt["status"] = "expired"
                    elif attempt["authorize"]():
                        return {"pending": self._handoff(identifier, attempt)}
                    else:
                        attempt["status"] = "cancelled"
                        threading.Thread(target=lambda key=identifier: self.cancel(key), daemon=True).start()
            return {"pending": None}

    def attempt(self, identifier):
        with self.lock:
            attempt = self.pending.get(identifier)
            if not attempt:
                raise ChatGPTError("Cette connexion ChatGPT a expiré. Recommencez.", 404)
            if attempt["expires"] <= self.clock() and attempt["status"] in {"pending", "exchanging"}:
                attempt["status"] = "expired"
            return {"status": attempt["status"], "message": attempt.get("message", ""), "connection": self.public()}

    def cancel(self, identifier):
        with self.lock:
            attempt = self.pending.get(identifier)
            if not attempt:
                return {"cancelled": True}
            if attempt["status"] in {"pending", "exchanging"}:
                attempt["status"] = "cancelled"
            server, timer = attempt["server"], attempt.get("timer")
            if attempt.get("closed"):
                return {"cancelled": True}
            attempt["closed"] = True
            if server in self.listeners:
                self.listeners.remove(server)
        if timer:
            timer.cancel()
        server.shutdown()
        server.server_close()
        return {"cancelled": True}

    def complete(self, identifier, callback_url):
        with self.lock:
            attempt = self.pending.get(identifier)
            if not attempt or attempt["expires"] <= self.clock() or attempt["status"] != "pending" or not attempt["authorize"]():
                raise ChatGPTError("Cette connexion ChatGPT a expiré ou a déjà été utilisée.", 409)
            try:
                uri = urlsplit(callback_url)
                if uri.scheme + "://" + uri.netloc + uri.path != attempt["callback"] or uri.fragment or len(callback_url) > 8192:
                    raise ValueError()
                fields = parse_qs(uri.query, strict_parsing=True)
                if any(len(v) != 1 for v in fields.values()) or not secrets.compare_digest(fields.get("state", [""])[0], attempt["state"]):
                    raise ValueError()
            except ValueError:
                raise ChatGPTError("L’adresse de retour ChatGPT ne correspond pas à cette connexion.", 400) from None
            if "error" in fields:
                attempt.update(status="failed", message="Connexion ChatGPT refusée ou annulée. Vous pouvez recommencer.")
                threading.Thread(target=lambda: self.cancel(identifier), daemon=True).start()
                raise ChatGPTError(attempt["message"], 400)
            code = fields.get("code", [""])[0]
            client = fields.get("client_id", [attempt["client_id"] or ""])[0]
            if not code or len(code) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", client) or client == "dynamic_agent_client" or (attempt["client_id"] and client != attempt["client_id"]):
                raise ChatGPTError("La réponse de connexion ChatGPT est incomplète ou incohérente.", 400)
            attempt["status"] = "exchanging"
        try:
            tokens = self.fetch("POST", TOKEN, {"grant_type": "authorization_code", "client_id": client, "code": code,
                "code_verifier": attempt["verifier"], "redirect_uri": attempt["callback"], "resource": RESOURCE})
            if not isinstance(tokens, dict):
                raise ChatGPTError("Les identifiants renvoyés par ChatGPT sont invalides.", 502)
            metadata = self.fetch("GET", DISCOVERY)
            if not isinstance(metadata, dict) or metadata.get("issuer") != ISSUER or metadata.get("jwks_uri") != JWKS:
                raise ChatGPTError("Le service d’identité ChatGPT n’est pas reconnu.", 502)
            identity = verified_identity(tokens.get("id_token", ""), self.fetch("GET", JWKS), client, attempt["nonce"], self.clock())
            if attempt["subject"] and identity["subject"] != attempt["subject"]:
                raise ChatGPTError("Ce compte ChatGPT ne correspond pas au compte choisi. Ajoutez-le séparément.", 409)
            credentials = self._tokens(tokens)
            with self.protected():
                if attempt["status"] != "exchanging" or attempt["expires"] <= self.clock() or not attempt["authorize"]():
                    raise ChatGPTError("La connexion ChatGPT a été annulée ou a expiré.", 409)
                profile = next((p for p in self.record["profiles"] if p["client_id"] == client and p["subject"] == identity["subject"]), None)
                if profile is None:
                    profile = {"id": str(uuid.uuid4()), "client_id": client, **identity,
                               "label": f"{identity['email'] or identity['name'] or 'ChatGPT'} · {len(self.record['profiles']) + 1}", "models": []}
                    self.record["profiles"].append(profile)
                profile.update(credentials)
                self.record["active"] = profile["id"]
                self._save()
                attempt.update(status="connected", message="Connexion ChatGPT enregistrée.")
            return self.public()
        except ChatGPTError as error:
            with self.lock:
                if attempt["status"] == "exchanging":
                    attempt.update(status="failed", message=str(error))
            raise
        finally:
            # Keep the callback listener until the caller has received the result.
            threading.Thread(target=lambda: self.cancel(identifier), daemon=True).start()

    def _tokens(self, value, previous=None):
        if not isinstance(value, dict) or value.get("token_type", "").lower() != "bearer":
            raise ChatGPTError("Les identifiants renvoyés par ChatGPT sont invalides.", 502)
        access = value.get("access_token")
        refresh = value.get("refresh_token", (previous or {}).get("tokens", {}).get("refresh_token", ""))
        lifetime = value.get("expires_in")
        if (not isinstance(access, str) or not 1 <= len(access) <= 20_000 or re.search(r"[\s\x00-\x1f]", access)
                or not isinstance(refresh, str) or not 1 <= len(refresh) <= 20_000 or re.search(r"[\s\x00-\x1f]", refresh)
                or type(lifetime) not in {int, float} or not math.isfinite(lifetime) or not 1 <= lifetime <= 86400):
            raise ChatGPTError("Les identifiants renvoyés par ChatGPT sont invalides.", 502)
        scope = value.get("scope", " ".join((previous or {}).get("scopes", [])))
        if not isinstance(scope, str) or len(scope) > 2000:
            raise ChatGPTError("Les autorisations ChatGPT sont invalides.", 502)
        identity = value.get("id_token", (previous or {}).get("tokens", {}).get("id_token", ""))
        if not isinstance(identity, str) or len(identity) > 32_000:
            raise ChatGPTError("Les identifiants renvoyés par ChatGPT sont invalides.", 502)
        return {"tokens": {"access_token": access, "refresh_token": refresh,
                           "id_token": identity},
                "scopes": scope.split(), "expires_at": self.clock() + lifetime}

    def _access(self):
        profile = self._profile()
        if not profile or not profile.get("tokens") or DIRECT not in profile["scopes"]:
            raise ChatGPTError("Connectez un compte ChatGPT et autorisez l’utilisation de son abonnement.", 409)
        if profile["expires_at"] <= self.clock() + 60:
            try:
                refreshed = self.fetch("POST", TOKEN, {"grant_type": "refresh_token", "client_id": profile["client_id"],
                    "refresh_token": profile["tokens"]["refresh_token"], "resource": RESOURCE})
            except ChatGPTError as error:
                if error.code in {"invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}:
                    profile["tokens"] = {}
                    self._save()
                raise
            profile.update(self._tokens(refreshed, profile))
            self._save()
            if DIRECT not in profile["scopes"]:
                raise ChatGPTError("L’autorisation d’utilisation de l’abonnement ChatGPT n’est plus accordée.", 403)
        return profile["tokens"]["access_token"]

    def models(self):
        with self.protected():
            token = self._access()
            result = self.fetch("GET", RESOURCE + "/models", token=token)
            entries = result.get("models") if isinstance(result, dict) else None
            if not isinstance(entries, list):
                raise ChatGPTError("Le catalogue des modèles ChatGPT est invalide.", 502)
            choices = []
            for entry in entries[:200]:
                if isinstance(entry, dict) and entry.get("visibility") == "list" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", str(entry.get("slug", ""))):
                    choices.append({"slug": entry["slug"], "display_name": str(entry.get("display_name") or entry["slug"])[:200]})
            self._profile()["models"] = choices
            self._save()
            return {"items": choices}

    def infer(self, payload, expected_profile=None):
        with self.protected():
            if expected_profile is not None and self.record["active"] != expected_profile:
                raise ChatGPTError("Le compte ChatGPT a changé pendant l’analyse. Relancez-la.", 409)
            token = self._access()
            active = self.record["active"]
            allowed = {m["slug"] for m in self._profile().get("models", [])}
            if payload.get("model") not in allowed:
                raise ChatGPTError("Choisissez un modèle disponible pour ce compte ChatGPT dans les paramètres.", 409)
        body = {k: v for k, v in payload.items() if k not in {"max_output_tokens", "max_tool_calls"}}
        body.update(store=False, stream=True)
        if isinstance(body.get("input"), str):
            body["input"] = [{"role": "user", "content": [{"type": "input_text", "text": body["input"]}]}]
        result = self.fetch("POST", RESOURCE + "/responses", body, token=token, stream=True)
        with self.lock:
            if self.record["active"] != active or not self._profile().get("tokens"):
                raise ChatGPTError("Le compte ChatGPT a changé pendant l’analyse. Relancez-la.", 409)
        return result

    def disconnect(self, identifier):
        with self.protected():
            profile = self._profile(identifier)
            if not profile:
                raise ChatGPTError("Compte ChatGPT introuvable.", 404)
            for attempt in self.pending.values():
                if attempt["profile_id"] == identifier and attempt["status"] in {"pending", "exchanging"}:
                    attempt["status"] = "cancelled"
            confirmed = not bool(profile.get("tokens"))
            if profile.get("tokens"):
                try:
                    metadata = self.fetch("GET", DISCOVERY)
                    if metadata.get("revocation_endpoint") != REVOKE:
                        raise ChatGPTError("Le service de déconnexion ChatGPT n’est pas reconnu.", 502)
                    for retry in range(3):
                        try:
                            self.fetch("POST", REVOKE, {"token": profile["tokens"]["refresh_token"], "token_type_hint": "refresh_token", "client_id": profile["client_id"]})
                            confirmed = True
                            break
                        except ChatGPTError as error:
                            if retry == 2 or error.api_status not in {None, 429, 500, 502, 503, 504}:
                                raise
                            time.sleep(.1 * (retry + 1))
                except ChatGPTError:
                    pass
            profile["tokens"] = {}
            self._save()
        return {"revocation_confirmed": confirmed, "connection": self.public()}

    def close(self):
        for identifier in list(self.pending):
            self.cancel(identifier)
        for server in list(self.listeners):
            server.shutdown()
            server.server_close()
