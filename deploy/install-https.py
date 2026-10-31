#!/usr/bin/env python3
"""Idempotent Debian/Pi OS HTTPS setup; also callable by a future bootstrap.

Run --dry-run as the station user first. Apply with sudo, from trusted sources.
Never copies inventories, rotates an existing CA or disables browser validation.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

MARKER = "# Managed by OPT Station HTTPS"
CONFIG = Path("/etc/opt-station")
STATE = Path("/var/lib/opt-station-caddy")
CA = STATE / "data/caddy/pki/authorities/local/root.crt"
PORT = 8766


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, text=True, **kwargs)


def unit_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def discover_addresses():
    rows = json.loads(subprocess.check_output(["ip", "-j", "-4", "address", "show", "scope", "global"], text=True))
    return [a["local"] for row in rows for a in row.get("addr_info", []) if a.get("family") == "inet"]


def addresses(hostname, values):
    hostname = hostname.lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        raise ValueError("Le nom court du Pi doit contenir seulement lettres, chiffres et tirets.")
    ips = []
    for value in values:
        address = ipaddress.ip_address(value)
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("L’adresse doit être une IPv4 privée attribuée au Pi.")
        ips.append(str(address))
    return list(dict.fromkeys([hostname + ".local", *ips, "localhost", "127.0.0.1"]))


def caddyfile(hosts, port=PORT, http_port=80, https_port=443, legacy_port=8765):
    # All values originate in validated host/IP input, never a user-supplied URL.
    for host in hosts:
        if not re.fullmatch(r"[a-z0-9.-]+", host):
            raise ValueError("Nom de machine invalide.")
    secure = ", ".join(f"https://{host}:{https_port}" for host in hosts)
    plain = ", ".join(f"http://{host}:{p}" for p in dict.fromkeys((http_port, legacy_port)) for host in hosts)
    canonical = f"https://{hosts[0]}" + (f":{https_port}" if https_port != 443 else "")
    proxy = f"""reverse_proxy 127.0.0.1:{port} {{
        header_up X-Forwarded-For {{http.request.remote.host}}
        header_up X-Forwarded-Proto {{scheme}}
        header_up -Forwarded
    }}"""
    return f"""{MARKER}
{{
    admin off
    skip_install_trust
    auto_https disable_redirects
}}
{secure} {{
    tls internal
    {proxy}
}}
{plain} {{
    @setup path /https /https/certificate /api/configuration/https /static/translations.js /static/i18n.js /static/https.js /static/theme.js /static/style.css
    handle @setup {{
        {proxy}
    }}
    handle / {{
        redir * /https 302
    }}
    handle {{
        redir {canonical}{{uri}} 308
    }}
}}
"""


def firefox_policy(raw, certificate):
    record = json.loads(raw) if raw else {}
    if not isinstance(record, dict) or not isinstance(record.get("policies", {}), dict):
        raise ValueError("La politique Firefox existante doit être examinée avant l’installation.")
    policies = record.setdefault("policies", {})
    if not isinstance(policies.get("Certificates", {}), dict):
        raise ValueError("La politique Firefox existante doit être examinée avant l’installation.")
    certificates = policies.setdefault("Certificates", {})
    install = certificates.setdefault("Install", [])
    if not isinstance(install, list) or any(not isinstance(x, str) for x in install):
        raise ValueError("La politique Firefox existante doit être examinée avant l’installation.")
    if certificate not in install:
        install.append(certificate)
    return json.dumps(record, ensure_ascii=False, indent=2) + "\n"


class Files:
    """Private, restorable copies of only the configuration files being changed."""
    def __init__(self, backup):
        self.backup, self.saved = backup, []
        backup.mkdir(parents=True, mode=0o700)

    def write(self, path, content, mode=0o644, owner=None):
        path = Path(path)
        if path.is_symlink():
            raise ValueError(f"Lien inattendu à examiner : {path}")
        if path not in [item[0] for item in self.saved]:
            old = path.stat() if path.exists() else None
            copy = self.backup / str(len(self.saved))
            if old:
                shutil.copy2(path, copy)
            self.saved.append((path, old, copy))
            (self.backup / "files.json").write_text(json.dumps([
                {"path": str(p), "copy": c.name if st else None,
                 "mode": st.st_mode & 0o777 if st else None, "uid": st.st_uid if st else None,
                 "gid": st.st_gid if st else None} for p, st, c in self.saved], indent=2))
        parents = []
        parent = path.parent
        while not parent.exists():
            parents.append(parent)
            parent = parent.parent
        for parent in reversed(parents):
            parent.mkdir(mode=0o700 if owner else 0o755)
            if owner:
                os.chown(parent, *owner)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(mode)
            if owner:
                os.chown(temporary, *owner)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def restore(self):
        for path, old, copy in reversed(self.saved):
            if old:
                shutil.copy2(copy, path)
                os.chown(path, old.st_uid, old.st_gid)
            else:
                path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Installer HTTPS pour une station déjà installée.")
    parser.add_argument("--user", default=os.getenv("SUDO_USER") or os.getenv("USER"))
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--hostname", default=socket.gethostname().split(".")[0])
    parser.add_argument("--address", action="append", help="IPv4 du Pi; détection automatique par défaut")
    parser.add_argument("--mode", choices=("hardware", "simulation"))
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    account = pwd.getpwnam(args.user or "")
    if account.pw_uid == 0:
        parser.error("Indiquez le compte ordinaire de la station avec --user.")
    home, source = Path(account.pw_dir), args.source.resolve()
    hosts = addresses(args.hostname, args.address or discover_addresses())
    metadata = {"version": 1, "url": "https://" + hosts[0],
                "aliases": ["https://" + x for x in hosts[1:] if x not in {"localhost", "127.0.0.1"}],
                "kiosk_url": "https://localhost", "ca_cert": str(CONFIG / "root-ca.crt")}
    if args.dry_run:
        print(json.dumps({"user": account.pw_name, "source": str(source), "https": metadata,
                          "backend": f"127.0.0.1:{PORT}", "gateway": [80, 443, 8765]}, indent=2))
        print(caddyfile(hosts))
        return
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("L’application des réglages demande sudo sur Raspberry Pi OS/Debian.")
    if not (source / ".venv/bin/python").is_file() or not (source / "openprinttag_app/https.py").is_file():
        parser.error("Préparez les nouvelles sources et leur environnement Python avant HTTPS.")
    stable_source = home / "apps/openprinttag-station"
    if stable_source.resolve() != source:
        parser.error("Activez d’abord les nouvelles sources dans apps/openprinttag-station.")
    uid, gid = account.pw_uid, account.pw_gid
    def userctl(*arguments, check=True):
        return subprocess.run(["runuser", "-u", account.pw_name, "--", "env",
                               f"XDG_RUNTIME_DIR=/run/user/{uid}", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                               "systemctl", "--user", *arguments], check=check, text=True, capture_output=True)
    if userctl("is-active", "openprinttag.service", check=False).returncode:
        parser.error("Ouvrez la session du compte de la station et démarrez OPT Station avant cette étape.")
    pid = int(userctl("show", "openprinttag.service", "--property=MainPID", "--value").stdout.strip())
    arguments = Path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
    if "--data-dir" not in arguments or arguments.index("--data-dir") + 1 == len(arguments):
        parser.error("Le service doit préciser son répertoire de données avec --data-dir avant cette installation.")
    data_dir = Path(arguments[arguments.index("--data-dir") + 1]).resolve()
    owned = CONFIG / "Caddyfile"
    if owned.exists() and not owned.read_text().startswith(MARKER):
        parser.error("Une configuration HTTPS existante doit être examinée; aucun fichier n’est remplacé.")
    active = subprocess.run(["systemctl", "is-active", "--quiet", "opt-station-https.service"]).returncode == 0
    if not active:
        for port in (80, 443, PORT):
            with socket.socket() as listener:
                try:
                    listener.bind(("0.0.0.0", port))
                except OSError:
                    parser.error(f"Le port {port} est occupé. Aucun autre serveur n’est arrêté.")
    # Refuse to interrupt hardware operations. New code must be running already.
    old_port = PORT if active else 8765
    with urlopen(f"http://127.0.0.1:{old_port}/api/system/power", timeout=8) as response:
        ready = json.load(response)
    if ready.get("pending") or ready.get("busy", True):
        parser.error("Une opération est en cours, ou les nouvelles sources ne sont pas encore actives. Terminez les opérations puis réessayez.")
    with urlopen(f"http://127.0.0.1:{old_port}/api/status", timeout=8) as response:
        status = json.load(response)
    mode = args.mode or status.get("mode")
    if mode not in {"hardware", "simulation"}:
        parser.error("Le mode de la station n’est pas reconnu.")
    backup = Path("/var/lib/opt-station-https-backups") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%f")
    files = Files(backup)
    installed = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Status}", "caddy"], capture_output=True, text=True)
    had_caddy = installed.returncode == 0 and installed.stdout.strip() == "installed"
    applied = False
    try:
        run("apt-get", "update")
        run("apt-get", "install", "--yes", "--no-install-recommends", "caddy", "avahi-daemon", "ca-certificates")
        if not had_caddy:
            # Only the welcome service created by this package installation.
            run("systemctl", "disable", "--now", "caddy.service")
        run("systemctl", "enable", "--now", "avahi-daemon.service")
        STATE.mkdir(mode=0o700, exist_ok=True)
        caddy = pwd.getpwnam("caddy")
        os.chown(STATE, caddy.pw_uid, caddy.pw_gid)
        files.write(CONFIG / "Caddyfile", caddyfile(hosts))
        files.write(CONFIG / "https.json", json.dumps(metadata, indent=2) + "\n")
        files.write(Path("/etc/systemd/system/opt-station-https.service"), (source / "deploy/opt-station-https.service").read_text())
        run("runuser", "-u", "caddy", "--", "env", f"XDG_DATA_HOME={STATE}/data", f"XDG_CONFIG_HOME={STATE}/config",
            "/usr/bin/caddy", "validate", "--config", str(owned), "--adapter", "caddyfile")
        # Provisioning the internal issuer creates its unique root; never rotate it.
        if not CA.is_file():
            raise ValueError("Caddy n’a pas créé son certificat racine; activation interrompue.")
        files.write(CONFIG / "root-ca.crt", CA.read_text())
        files.write(Path("/usr/local/share/ca-certificates/opt-station.crt"), CA.read_text())
        run("update-ca-certificates")
        policy = Path("/etc/firefox/policies/policies.json")
        files.write(policy, firefox_policy(policy.read_text() if policy.exists() else "", str(CONFIG / "root-ca.crt")))
        python = stable_source / ".venv/bin/python"
        arguments = [str(python), "-m", "openprinttag_app", "--mode", mode, "--lan", "--host", "127.0.0.1",
                     "--port", str(PORT), "--data-dir", str(data_dir), "--https-config", str(CONFIG / "https.json")]
        if not args.no_camera and status.get("camera", {}).get("enabled", False):
            arguments.append("--camera")
        dropin = home / ".config/systemd/user/openprinttag.service.d/https.conf"
        if dropin.exists() and not dropin.read_text().startswith(MARKER):
            raise ValueError("Une surcharge HTTPS non reconnue doit être examinée.")
        files.write(dropin, MARKER + "\n[Service]\nExecStart=\nExecStart=" + " ".join(unit_quote(x) for x in arguments) + "\n", 0o600, (uid, gid))
        files.write(home / ".local/lib/openprinttag-screen/launch.py", (source / "deploy/openprinttag-display.py").read_text(), 0o600, (uid, gid))
        files.write(home / ".config/systemd/user/openprinttag-display.service.d/https.conf",
                    MARKER + '\n[Service]\nEnvironment=OPENPRINTTAG_HTTPS_CONFIG=/etc/opt-station/https.json\n', 0o600, (uid, gid))
        applied = True
        userctl("daemon-reload")
        userctl("restart", "openprinttag.service")
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", "opt-station-https.service")
        if active:
            run("systemctl", "restart", "opt-station-https.service")
        context = ssl.create_default_context(cafile=str(CONFIG / "root-ca.crt"))
        deadline = time.monotonic() + 45
        while True:
            try:
                with urlopen("https://localhost/api/status", context=context, timeout=3) as response:
                    status = json.load(response)
                if not status.get("local_station"):
                    raise ValueError("Le navigateur local n’est pas reconnu.")
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        if userctl("is-active", "openprinttag-display.service", check=False).returncode == 0:
            if userctl("restart", "openprinttag-display.service", check=False).returncode:
                print("HTTPS répond. Relancez le navigateur local après vérification de sa session graphique.", file=sys.stderr)
        pem = CA.read_text()
        der = base64.b64decode(''.join(line for line in pem.splitlines() if not line.startswith('---')))
        print("HTTPS installé :", metadata["url"])
        print("Aide depuis un autre appareil : http://" + hosts[0] + "/https")
        print("Empreinte SHA-256 :", ':'.join(f'{b:02X}' for b in hashlib.sha256(der).digest()))
        print("Sauvegarde des réglages précédents :", backup)
    except BaseException:
        if applied:
            subprocess.run(["systemctl", "stop", "opt-station-https.service"], check=False)
            if not active:
                subprocess.run(["systemctl", "disable", "opt-station-https.service"], check=False)
        files.restore()
        subprocess.run(["update-ca-certificates"], check=False, capture_output=True)
        if applied:
            userctl("daemon-reload", check=False)
            userctl("restart", "openprinttag.service", check=False)
        run("systemctl", "daemon-reload")
        if active:
            subprocess.run(["systemctl", "start", "opt-station-https.service"], check=False)
        print("Installation interrompue; réglages précédents restaurés. Diagnostic :", backup, file=sys.stderr)
        raise


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
