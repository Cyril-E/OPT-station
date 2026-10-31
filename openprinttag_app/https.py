"""Local HTTPS deployment metadata and a deliberately single-hop proxy boundary.

Only the loopback Caddy gateway may supply an address. It overwrites forwarded
headers; a forwarded chain is rejected rather than interpreted as a local user.
Private CA keys stay in Caddy's system data directory, outside the application.
"""
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from starlette.responses import JSONResponse


def https_url(value):
    if not isinstance(value, str) or len(value) > 255:
        raise ValueError("Adresse HTTPS invalide.")
    parsed = urlsplit(value)
    try:
        port = parsed.port
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or not host
                or any(c in value for c in "\r\n\t \\") or not (port is None or 1 <= port <= 65535)):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or ".." in host:
                raise ValueError()
    except ValueError:
        raise ValueError("Adresse HTTPS invalide.") from None
    authority = f"[{host}]" if ":" in host else host
    return f"https://{authority}" + (f":{port}" if port and port != 443 else "")


@dataclass(frozen=True)
class HTTPSConfiguration:
    url: str = ""
    aliases: tuple[str, ...] = ()
    ca_cert: Path | None = None
    kiosk_url: str = "https://localhost"

    @classmethod
    def load(cls, path=None):
        if not path:
            return cls()
        try:
            raw = Path(path).read_bytes()
            if len(raw) > 16384:
                raise ValueError()
            record = json.loads(raw)
            if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
                raise ValueError()
            aliases = record.get("aliases", [])
            if not isinstance(aliases, list) or len(aliases) > 16:
                raise ValueError()
            certificate = Path(record["ca_cert"])
            if not certificate.is_absolute():
                raise ValueError()
            kiosk = https_url(record.get("kiosk_url", "https://localhost"))
            if urlsplit(kiosk).hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError()
            return cls(https_url(record["url"]), tuple(https_url(x) for x in aliases), certificate, kiosk)
        except (OSError, KeyError, TypeError, ValueError):
            raise ValueError("La configuration HTTPS est invalide ou inaccessible. Vérifiez l’installation HTTPS avant de relancer la station.") from None

    @property
    def hosts(self):
        return tuple(dict.fromkeys(urlsplit(url).hostname for url in (self.url, *self.aliases, self.kiosk_url) if url)) if self.url else ()

    def certificate(self):
        if not self.url or not self.ca_cert:
            raise ValueError("Le certificat HTTPS n’est pas encore disponible.")
        try:
            raw = self.ca_cert.read_bytes()
            if len(raw) > 32768 or b"PRIVATE KEY" in raw:
                raise ValueError()
            cert = x509.load_pem_x509_certificate(raw)
            if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                raise ValueError()
            return cert
        except (OSError, ValueError, x509.ExtensionNotFound):
            raise ValueError("Le certificat HTTPS n’est pas encore disponible.") from None

    def public(self, secure=False):
        result = {"enabled": bool(self.url), "secure": secure, "url": self.url,
                  "aliases": list(self.aliases), "certificate_available": False,
                  "certificate_name": "", "fingerprint_sha256": "",
                  "certificate_url": "/https/certificate", "help_url": "/https"}
        try:
            cert = self.certificate()
            names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            result.update(certificate_available=True,
                          certificate_name=names[0].value if names else cert.subject.rfc4514_string(),
                          fingerprint_sha256=":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256())))
        except ValueError:
            pass
        return result

    def pem(self):
        return self.certificate().public_bytes(serialization.Encoding.PEM)


class HTTPSProxyMiddleware:
    def __init__(self, app, enabled=False):
        self.app, self.enabled = app, enabled

    async def __call__(self, scope, receive, send):
        if self.enabled and scope["type"] == "http":
            peer = scope.get("client")
            # Caddy connects to the IPv4 loopback listener, never a LAN socket.
            if peer and peer[0] == "127.0.0.1":
                forwarded = [v for k, v in scope["headers"] if k.lower() == b"x-forwarded-for"]
                protocols = [v for k, v in scope["headers"] if k.lower() == b"x-forwarded-proto"]
                if forwarded or protocols:
                    try:
                        if len(forwarded) != 1 or len(protocols) != 1 or protocols[0] not in {b"http", b"https"}:
                            raise ValueError()
                        client = str(ipaddress.ip_address(forwarded[0].decode("ascii")))
                        scope = dict(scope, client=(client, 0), scheme=protocols[0].decode("ascii"))
                    except (ValueError, UnicodeError):
                        response = JSONResponse({"detail": "En-têtes de passerelle HTTPS invalides."}, status_code=400)
                        await response(scope, receive, send)
                        return
        await self.app(scope, receive, send)
