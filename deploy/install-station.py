#!/usr/bin/env python3
"""Install verified sources on Pi OS; invoked by the unprivileged bootstrap.

System packages stay installed on failure. Application files, data, units and
HTTPS configuration have a private rollback copy. Never reboot automatically.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from urllib.request import urlopen

MARKER = "# Managed by OPT Station installer"
LOCK = Path("/run/lock/opt-station-install.lock")
SYSTEM_ROOT = Path("/")
SYSTEM_FILES = (
    "/etc/opt-station/Caddyfile", "/etc/opt-station/https.json", "/etc/opt-station/root-ca.crt",
    "/etc/systemd/system/opt-station-https.service", "/etc/firefox/policies/policies.json",
    "/usr/local/share/ca-certificates/opt-station.crt", "/etc/lightdm/lightdm.conf.d/50-opt-station.conf",
    "/etc/systemd/system/default.target", "/etc/lightdm/lightdm.conf",
)
PACKAGES = ("python3-venv", "python3-numpy", "python3-pil", "pcscd", "libccid", "pcsc-tools",
            "python3-pyscard", "ca-certificates", "ffmpeg")
CAMERA_PACKAGES = ("python3-picamera2", "python3-libcamera")
DESKTOP_PACKAGES = ("firefox", "desktop-file-utils", "libglib2.0-bin")


def system_path(value):
    return SYSTEM_ROOT / value.lstrip("/")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args, check=True, capture_output=False, **kwargs):
    return subprocess.run([str(a) for a in args], check=check, text=True, capture_output=capture_output, **kwargs)


def read_json(url):
    with urlopen(url, timeout=5) as response:
        return json.load(response)


def unit_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def service(source, data_dir, mode, camera):
    arguments = [str(source / ".venv/bin/python"), "-m", "openprinttag_app", "--mode", mode,
                 "--host", "127.0.0.1", "--data-dir", str(data_dir)]
    if camera:
        arguments.append("--camera")
    return (MARKER + "\n[Unit]\nDescription=OPT Station\n[Service]\nType=simple\nWorkingDirectory="
            + str(source).replace("%", "%%") + "\nExecStart=" + " ".join(map(unit_quote, arguments))
            + "\nEnvironment=PYTHONUNBUFFERED=1\nRestart=on-failure\nRestartSec=3\nTimeoutStopSec=45\n"
            "KillMode=control-group\nUMask=0077\nNoNewPrivileges=true\n[Install]\nWantedBy=default.target\n")


def version(path):
    value = tomllib.loads(path.read_text())["project"]["version"]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(rc|\.dev)(\d+))?", value)
    if not match:
        raise ValueError("Version des sources non reconnue.")
    major, minor, patch, stage, number = match.groups()
    return value, (int(major), int(minor), int(patch), {".dev": 0, "rc": 1, None: 2}[stage], int(number or 0))


def profile(arguments):
    """Preserve the explicit runtime data path, mode and camera on reinstallation."""
    def option(name, default=None):
        if name not in arguments:
            return default
        index = arguments.index(name) + 1
        if index >= len(arguments):
            raise ValueError(f"Option de service incomplète : {name}")
        return arguments[index]
    data = option("--data-dir")
    mode = option("--mode", "simulation")
    if not data or mode not in {"hardware", "simulation"}:
        raise ValueError("Le service existant doit préciser --data-dir et un mode reconnu.")
    return Path(data).resolve(), mode, "--camera" in arguments, int(option("--port", "8765"))


@contextmanager
def installation_lock():
    descriptor = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
    try:
        if os.fstat(descriptor).st_uid != 0 or not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Le verrou d’installation doit être un fichier système ordinaire.")
        os.fchmod(descriptor, 0o644)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Une autre installation d’OPT Station est déjà en cours.") from None
        yield
    finally:
        os.close(descriptor)


class Transaction:
    """Record only selected paths; preserve links and ownership, including absence."""
    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(parents=True, mode=0o700)
        self.saved = []
        self.created_dirs, self.directory_modes = [], []

    def capture(self, path):
        path = Path(path)
        if any(item[0] == path for item in self.saved):
            return
        old = path.lstat() if path.exists() or path.is_symlink() else None
        copy, link = None, None
        if old:
            if stat.S_ISLNK(old.st_mode):
                link = os.readlink(path)
            elif stat.S_ISREG(old.st_mode):
                copy = self.folder / str(len(self.saved))
                shutil.copy2(path, copy)
            else:
                raise ValueError(f"Ce chemin doit être un fichier ou un lien : {path}")
        self.saved.append((path, old, copy, link))
        (self.folder / "manifest.json").write_text(json.dumps([
            {"path": str(p), "existed": info is not None, "copy": str(saved.name) if saved else None,
             "link": target, "uid": info.st_uid if info else None, "gid": info.st_gid if info else None,
             "mode": stat.S_IMODE(info.st_mode) if info else None}
            for p, info, saved, target in self.saved], indent=2) + "\n")

    def write(self, path, text, uid=0, gid=0, mode=0o600):
        self.capture(path)
        if path.is_symlink():
            raise ValueError(f"Un fichier de configuration est un lien symbolique : {path}")
        parents, parent = [], path.parent
        while not parent.exists():
            parents.append(parent)
            parent = parent.parent
        for parent in reversed(parents):
            parent.mkdir(mode=0o755 if uid == 0 else 0o700)
            parent.chmod(0o755 if uid == 0 else 0o700)  # independent of the installer's private umask
            os.chown(parent, uid, gid)
            self.created_dirs.append(parent)
        # A previously interrupted install may have left an empty root-owned
        # public configuration directory. Record its old mode before repairing it.
        parent = path.parent
        if (uid == 0 and mode & 0o044 and parent not in self.created_dirs
                and parent.stat().st_uid == 0 and not any(parent.iterdir())):
            previous = stat.S_IMODE(parent.stat().st_mode)
            if previous != 0o755:
                self.directory_modes.append((parent, previous))
                parent.chmod(0o755)
        (self.folder / "directories.json").write_text(json.dumps({
            "created": list(map(str, self.created_dirs)),
            "permissions_before": [{"path": str(p), "mode": old} for p, old in self.directory_modes],
        }, indent=2) + "\n")
        descriptor, temporary = tempfile.mkstemp(prefix=".opt-install-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                os.fchmod(output.fileno(), mode)
                os.fchown(output.fileno(), uid, gid)
                output.write(text)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def link(self, path, target):
        self.capture(path)
        temporary = path.with_name(path.name + ".install-next")
        if temporary.exists() or temporary.is_symlink():
            raise ValueError(f"Un ancien lien temporaire doit être examiné : {temporary}")
        temporary.symlink_to(target)
        os.replace(temporary, path)

    def restore(self):
        for path, old, copy, link in reversed(self.saved):
            if path.is_symlink() or path.is_file():
                path.unlink()
            if not old:
                continue
            if link is not None:
                path.symlink_to(link)
                os.lchown(path, old.st_uid, old.st_gid)
            else:
                shutil.copy2(copy, path)
                os.chown(path, old.st_uid, old.st_gid)
        for path, mode in reversed(self.directory_modes):
            path.chmod(mode)
        for path in reversed(self.created_dirs):
            try:
                path.rmdir()
            except OSError:
                pass  # Keep a directory if another component now owns files inside it.


class Installer:
    def __init__(self, args, account):
        self.args, self.account = args, account
        self.home = Path(account.pw_dir)
        if any(c in str(self.home) for c in ('\n', '\r', '"', '\\', '%', '$')):
            raise ValueError("Le chemin du compte contient des caractères incompatibles avec le lancement du bureau.")
        self.source = args.source.resolve()
        self.stable = self.home / "apps/openprinttag-station"
        self.units = self.home / ".config/systemd/user"
        self.receipt = self.home / ".local/state/opt-station/installation.json"
        self.data = (self.home / "openprinttag-data").resolve()
        self.mode, self.camera = "hardware", not args.no_camera
        self.runtime_port = None
        self.kiosk = not args.no_kiosk
        self.active = self.display_active = self.enabled = self.gateway_active = self.gateway_enabled = False
        self.old_source = self.stable.resolve() if self.stable.is_symlink() else None
        self.old_linger = True
        self.transaction = None
        self.stopped = False
        self.data_backup_ready = False
        self.data_mutated = False
        self.new_version, self.version_key = version(self.source / "pyproject.toml")

    def userctl(self, *arguments, check=True):
        uid = self.account.pw_uid
        return run("runuser", "-u", self.account.pw_name, "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}",
                   f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus", "systemctl", "--user", *arguments,
                   check=check, capture_output=True)

    def as_user(self, *arguments):
        return run("runuser", "-u", self.account.pw_name, "--", "env", "PYTHONNOUSERSITE=1", *arguments,
                   cwd=self.source)

    def preflight(self):
        bootstrap = load("opt_bootstrap", self.source / "deploy/bootstrap.py")
        bootstrap.supported_platform()
        if (not self.source.is_relative_to(self.home / "apps") or self.source == self.stable
                or self.source.stat().st_uid != self.account.pw_uid or '$' in str(self.source)
                or any(ord(c) < 32 for c in str(self.source))):
            raise ValueError("Les sources doivent être préparées dans un nouveau dossier apps du compte de la station.")
        if self.stable.exists() and not self.stable.is_symlink():
            raise ValueError("apps/openprinttag-station existe sans être un lien; aucun dossier n’est remplacé.")
        if self.stable.is_symlink() and not self.stable.is_dir():
            raise ValueError("Le lien de l’installation existante est cassé; examinez-le avant de poursuivre.")
        if self.old_source == self.source:
            raise ValueError("Préparez une nouvelle copie des sources; ne remplacez pas l’environnement Python en cours.")
        if self.old_source and version(self.old_source / "pyproject.toml")[1] > self.version_key:
            raise ValueError("Le retour à une version plus ancienne exige une restauration manuelle de sa sauvegarde.")
        unit = self.units / "openprinttag.service"
        if unit.exists():
            if not self.old_source or "openprinttag_app" not in unit.read_text():
                raise ValueError("Un service existant non reconnu doit être examiné.")
            fragment = self.userctl("show", "openprinttag.service", "--property=FragmentPath", "--value", check=False)
            if fragment.returncode or fragment.stdout.strip() != str(unit):
                raise ValueError("Le service doit provenir du compte de la station et sa session doit être ouverte.")
            dropins = self.userctl("show", "openprinttag.service", "--property=DropInPaths", "--value").stdout.split()
            expected = self.units / "openprinttag.service.d/https.conf"
            if any(Path(path) != expected for path in dropins):
                raise ValueError("Une surcharge personnalisée du service doit être examinée avant l’installation.")
            if expected.exists() and not expected.read_text().startswith("# Managed by OPT Station HTTPS"):
                raise ValueError("La surcharge HTTPS existante n’est pas reconnue.")
            self.active = self.userctl("is-active", "openprinttag.service", check=False).returncode == 0
            self.enabled = self.userctl("is-enabled", "openprinttag.service", check=False).returncode == 0
            if self.active:
                pid = int(self.userctl("show", "openprinttag.service", "--property=MainPID", "--value").stdout.strip())
                arguments = system_path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
            else:
                text = expected.read_text() if expected.exists() else unit.read_text()
                lines = [line.removeprefix("ExecStart=") for line in text.splitlines() if line.startswith("ExecStart=") and line != "ExecStart="]
                if not lines:
                    raise ValueError("La commande du service existant n’est pas reconnue.")
                arguments = shlex.split(lines[-1].replace("%h", str(self.home)))
            self.data, self.mode, previous_camera, port = profile(arguments)
            self.runtime_port = port if self.active else None
            self.camera = previous_camera and not self.args.no_camera
            if self.active:
                state = read_json(f"http://127.0.0.1:{port}/api/system/power")
                if state.get("busy", True) or state.get("pending"):
                    raise ValueError("Terminez les opérations NFC, caméra ou impression d’étiquette avant l’installation.")
        elif self.old_source:
            raise ValueError("Les sources existantes n’ont pas de service reconnu; reprendre l’installation manuelle.")
        reserved = [self.home / name for name in ("apps", "openprinttag-backups", ".config", ".local")]
        if (not self.data.is_relative_to(self.home) or self.data == self.home or self.data.is_mount()
                or '$' in str(self.data) or any(ord(c) < 32 for c in str(self.data))
                or any(self.data.is_relative_to(path) or path.is_relative_to(self.data) for path in reserved)):
            raise ValueError("Le dossier de données doit être indépendant des sources et situé dans le compte de la station.")
        if self.receipt.exists():
            receipt = json.loads(self.receipt.read_text())
            self.kiosk = bool(receipt.get("kiosk", self.kiosk)) and not self.args.no_kiosk
        elif self.old_source:
            self.kiosk = (self.units / "openprinttag-display.service").exists() and not self.args.no_kiosk
        for name in ("openprinttag-display.service",):
            path = self.units / name
            if path.exists() and "openprinttag-screen/launch.py" not in path.read_text():
                raise ValueError("Un service d’affichage personnalisé doit être examiné.")
        self.display_active = self.userctl("is-active", "openprinttag-display.service", check=False).returncode == 0
        self.gateway_active = run("systemctl", "is-active", "--quiet", "opt-station-https.service", check=False).returncode == 0
        self.gateway_enabled = run("systemctl", "is-enabled", "--quiet", "opt-station-https.service", check=False).returncode == 0
        caddy = system_path("/etc/opt-station/Caddyfile")
        if caddy.exists() and not caddy.read_text().startswith("# Managed by OPT Station HTTPS"):
            raise ValueError("Une configuration Caddy étrangère est présente; aucun serveur n’est remplacé.")
        for port in (() if self.gateway_active else (80, 443, 8765, 8766)):
            if port == self.runtime_port:
                continue
            with socket.socket() as listener:
                try:
                    listener.bind(("0.0.0.0", port))
                except OSError:
                    raise ValueError(f"Le port {port} est occupé par un autre service.") from None
        if self.kiosk:
            lightdm = system_path("/etc/lightdm/lightdm.conf")
            if not lightdm.is_file() or not system_path("/etc/init.d/lightdm").exists():
                raise ValueError("Le plein écran exige Raspberry Pi OS avec bureau. Utilisez --no-kiosk sur Lite.")
            for config in [lightdm, *system_path("/etc/lightdm/lightdm.conf.d").glob("*.conf")]:
                users = re.findall(r"^[ \t]*autologin-user[ \t]*=[ \t]*(.*?)[ \t]*$", config.read_text(), re.M)
                if any(user and user != self.account.pw_name for user in users):
                    raise ValueError("L’ouverture automatique d’une autre session est configurée. Utilisez --no-kiosk ou adaptez LightDM.")
            if not re.search(r"^[ \t]*#?[ \t]*autologin-user[ \t]*=", lightdm.read_text(), re.M):
                raise ValueError("La configuration LightDM est personnalisée; utilisez --no-kiosk ou adaptez l’ouverture du bureau.")
            autostart = self.home / ".config/autostart/openprinttag.desktop"
            if autostart.exists() and "openprinttag-screen/launch.py" not in autostart.read_text():
                raise ValueError("Un lancement automatique existant doit être examiné.")
            managed = system_path("/etc/lightdm/lightdm.conf.d/50-opt-station.conf")
            if managed.exists() and not managed.read_text().startswith(MARKER):
                raise ValueError("Le fichier de session OPT Station existant n’est pas reconnu.")
        required = 1024**3 + (sum(p.stat().st_size for p in self.data.rglob("*") if p.is_file() and not p.is_symlink()) * 2
                              if self.data.is_dir() else 0)
        if shutil.disk_usage(self.home).free < required:
            raise ValueError("Espace insuffisant pour le nouvel environnement et une sauvegarde des données.")

    def snapshot(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%f")
        self.backup = self.home / "openprinttag-backups" / ("before-install-" + stamp)
        self.transaction = Transaction(self.backup / "files")
        paths = [self.stable, self.receipt, self.units / "openprinttag.service",
                 self.units / "openprinttag.service.d/https.conf", self.units / "openprinttag-display.service",
                 self.units / "openprinttag-display.service.d/https.conf", self.home / ".local/lib/openprinttag-screen/launch.py",
                 self.home / ".config/autostart/openprinttag.desktop", *map(system_path, SYSTEM_FILES)]
        for path in paths:
            self.transaction.capture(path)
        self.data_existed = self.data.exists()
        if self.data_existed:
            run("tar", "--acls", "--xattrs", "-czpf", self.backup / "data-before.tar.gz", "-C", self.data, ".")
        self.data_backup_ready = True
        (self.backup / "installation-before.json").write_text(json.dumps({
            "source": str(self.old_source) if self.old_source else None, "data_dir": str(self.data),
            "new_source": str(self.source), "version": self.new_version, "active": self.active,
            "enabled": self.enabled, "gateway_active": self.gateway_active, "gateway_enabled": self.gateway_enabled,
        }, indent=2) + "\n")

    def wait_http(self, port):
        deadline = time.monotonic() + 60
        while True:
            try:
                status = read_json(f"http://127.0.0.1:{port}/api/status")
                if status.get("version") != self.new_version or status.get("mode") != self.mode:
                    raise ValueError("Le service ne répond pas avec la version et le mode attendus.")
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)

    def validate_service(self):
        # Verify with the prepared source path: the stable link does not exist on
        # a first install. This uses systemd's actual parser, without starting a unit.
        with tempfile.TemporaryDirectory(prefix=".opt-unit-check-", dir=self.source) as temporary:
            folder = Path(temporary)
            os.chown(folder, self.account.pw_uid, self.account.pw_gid)
            unit = folder / "openprinttag.service"
            unit.write_text(service(self.source, self.data, self.mode, self.camera))
            unit.chmod(0o600)
            os.chown(unit, self.account.pw_uid, self.account.pw_gid)
            uid = self.account.pw_uid
            result = run("runuser", "-u", self.account.pw_name, "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}",
                         f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus", "systemd-analyze", "--user", "verify",
                         "--man=no", unit, check=False, capture_output=True)
            if result.returncode:
                raise ValueError("Fichier de démarrage refusé par systemd; l’application n’a pas été arrêtée.\n"
                                 + result.stderr.strip())

    def rollback(self):
        self.userctl("stop", "openprinttag-display.service", "openprinttag.service", check=False)
        run("systemctl", "stop", "opt-station-https.service", check=False)
        if not self.enabled:
            self.userctl("disable", "openprinttag.service", check=False)
        if not self.gateway_enabled:
            run("systemctl", "disable", "opt-station-https.service", check=False)
        if self.transaction:
            self.transaction.restore()
            if self.data_backup_ready and self.data_mutated and self.data.exists():
                # Retain, rather than delete, the attempted version's data.
                self.failed_data = self.data.with_name(self.data.name + ".failed-" + self.backup.name)
                self.data.rename(self.failed_data)
            if self.data_backup_ready and self.data_mutated and self.data_existed:
                self.data.mkdir(mode=0o700)
                run("tar", "--acls", "--xattrs", "-xzpf", self.backup / "data-before.tar.gz", "-C", self.data)
            run("systemctl", "daemon-reload", check=False)
            run("update-ca-certificates", check=False, capture_output=True)
        self.userctl("daemon-reload", check=False)
        if self.enabled:
            self.userctl("enable", "openprinttag.service", check=False)
        if self.gateway_enabled:
            run("systemctl", "enable", "opt-station-https.service", check=False)
        if self.active:
            self.userctl("start", "openprinttag.service", check=False)
        if self.gateway_active:
            run("systemctl", "start", "opt-station-https.service", check=False)
        if self.display_active:
            self.userctl("start", "openprinttag-display.service", check=False)
        if not self.old_linger:
            run("loginctl", "disable-linger", self.account.pw_name, check=False)

    def apply(self):
        self.preflight()
        https = load("opt_https_installer", self.source / "deploy/install-https.py")
        # Validate the hostname/address set before installing packages or stopping anything.
        https.addresses(socket.gethostname().split(".")[0], https.discover_addresses())
        packages = [*PACKAGES, *(CAMERA_PACKAGES if self.camera else ()), *(DESKTOP_PACKAGES if self.kiosk else ())]
        print("Installation des dépendances système…", flush=True)
        run("apt-get", "update")
        run("apt-get", "install", "--yes", "--no-install-recommends", *packages)
        run("systemctl", "enable", "--now", "pcscd.socket")
        print("Préparation de Python avec les dépendances verrouillées…", flush=True)
        self.as_user("python3", "-m", "venv", "--system-site-packages", self.source / ".venv")
        python = self.source / ".venv/bin/python"
        arguments = [str(python), "-m", "pip", "install", "--only-binary=:all:", "-r", "requirements.lock"]
        if self.camera:
            arguments.extend(["-r", "requirements-camera.lock"])
        self.as_user(*arguments)
        imports = "import openprinttag_app.app, smartcard" + (", picamera2, libcamera, zxingcpp" if self.camera else "")
        self.as_user(python, "-c", imports)
        self.validate_service()
        linger = run("loginctl", "show-user", self.account.pw_name, "--property=Linger", "--value", check=False, capture_output=True)
        self.old_linger = linger.returncode == 0 and linger.stdout.strip() == "yes"
        # Recheck after downloads: an operation could have started in the meantime.
        if self.active:
            pid = int(self.userctl("show", "openprinttag.service", "--property=MainPID", "--value").stdout.strip())
            current = profile(system_path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0"))
            state = read_json(f"http://127.0.0.1:{current[3]}/api/system/power")
            if state.get("busy", True) or state.get("pending"):
                raise ValueError("Une opération a commencé. Terminez-la puis relancez l’installation.")
        print("Sauvegarde privée et activation de la nouvelle version…", flush=True)
        try:
            if self.display_active:
                self.userctl("stop", "openprinttag-display.service")
            if (self.units / "openprinttag.service").exists():
                self.userctl("stop", "openprinttag.service")
            self.stopped = True
            run("loginctl", "enable-linger", self.account.pw_name)
            run("systemctl", "start", f"user@{self.account.pw_uid}.service")
            self.snapshot()
            self.data_mutated = True
            self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chown(self.data, self.account.pw_uid, self.account.pw_gid)
            tx, uid, gid = self.transaction, self.account.pw_uid, self.account.pw_gid
            tx.link(self.stable, self.source)
            os.lchown(self.stable, uid, gid)
            tx.write(self.units / "openprinttag.service", service(self.stable, self.data, self.mode, self.camera), uid, gid)
            if self.kiosk:
                tx.write(self.units / "openprinttag-display.service", (self.source / "deploy/openprinttag-display.service").read_text(), uid, gid)
                tx.write(self.home / ".config/autostart/openprinttag.desktop",
                         (self.source / "deploy/openprinttag.desktop.in").read_text().replace("@HOME@", str(self.home)), uid, gid)
                tx.write(system_path("/etc/lightdm/lightdm.conf.d/50-opt-station.conf"),
                         MARKER + f"\n[Seat:*]\nautologin-user={self.account.pw_name}\nautologin-user-timeout=0\n", mode=0o644)
                lightdm = system_path("/etc/lightdm/lightdm.conf")
                text = re.sub(r"^[ \t]*#?[ \t]*autologin-user[ \t]*=.*$",
                              "autologin-user=" + self.account.pw_name, lightdm.read_text(), flags=re.M)
                tx.write(lightdm, text, mode=0o644)
                run("systemctl", "set-default", "graphical.target")
            elif self.args.no_kiosk:
                autostart = self.home / ".config/autostart/openprinttag.desktop"
                if autostart.exists():
                    if "openprinttag-screen/launch.py" not in autostart.read_text():
                        raise ValueError("Le lancement automatique existant doit être examiné.")
                    autostart.unlink()
                autologin = system_path("/etc/lightdm/lightdm.conf.d/50-opt-station.conf")
                if autologin.exists() and autologin.read_text().startswith(MARKER):
                    autologin.unlink()
            self.userctl("daemon-reload")
            self.userctl("enable", "--now", "openprinttag.service")
            port = 8766 if (self.units / "openprinttag.service.d/https.conf").exists() else 8765
            self.wait_http(port)
            arguments = ["python3", self.source / "deploy/install-https.py", "--user", self.account.pw_name, "--source", self.source]
            if not self.camera:
                arguments.append("--no-camera")
            run(*arguments)
            # HTTPS helper has already verified TLS through the station's own CA.
            self.wait_http(8766)
            receipt = {"version": 1, "application_version": self.new_version, "source": str(self.source),
                       "data_dir": str(self.data), "kiosk": self.kiosk, "camera": self.camera,
                       "archive_sha256": self.args.archive_sha256, "backup": str(self.backup)}
            tx.write(self.receipt, json.dumps(receipt, indent=2) + "\n", uid, gid)
        except BaseException:
            print("Échec de l’activation : restauration de la version précédente…", file=sys.stderr)
            try:
                self.rollback()
            except BaseException as recovery:
                print(f"Restauration incomplète : {recovery}. Conserver la sauvegarde privée {getattr(self, 'backup', '')}.", file=sys.stderr)
                raise
            raise
        print(f"OPT Station {self.new_version} installé. Sauvegarde privée : {self.backup}", flush=True)
        metadata = json.loads(system_path("/etc/opt-station/https.json").read_text())
        print("Ouvrir : " + metadata["url"] + "/")
        print("Sur chaque autre appareil, approuver une fois le certificat : " + metadata["url"].replace("https:", "http:") + "/https")
        print("Renseigner ensuite les équipements et clés API dans Configuration.")
        if self.kiosk:
            environment = self.userctl("show-environment", check=False).stdout
            if self.display_active or any(line.startswith(("DISPLAY=", "WAYLAND_DISPLAY=")) for line in environment.splitlines()):
                if self.userctl("start", "openprinttag-display.service", check=False).returncode:
                    print("Le serveur répond; l’affichage local démarrera à la prochaine ouverture du bureau.")
            print("Le bureau s’ouvrira automatiquement en plein écran au prochain démarrage. Aucun redémarrage n’a été lancé.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Installer OPT Station, ses services et HTTPS sur Raspberry Pi OS.")
    parser.add_argument("--user", default=os.getenv("SUDO_USER") or os.getenv("USER"))
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--archive-sha256", default="")
    parser.add_argument("--no-kiosk", action="store_true")
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    account = pwd.getpwnam(args.user or "")
    if account.pw_uid == 0:
        parser.error("Indiquez le compte ordinaire de la station avec --user.")
    if args.archive_sha256 and not re.fullmatch(r"[a-f0-9]{64}", args.archive_sha256):
        parser.error("Empreinte d’archive invalide.")
    installer = Installer(args, account)
    if args.dry_run:
        print(json.dumps({"version": installer.new_version, "source": str(installer.source), "user": account.pw_name,
                          "data_dir_default": str(installer.data), "existing_installation": installer.old_source is not None,
                          "preserve_existing": True, "kiosk_default": installer.kiosk,
                          "camera_default": installer.camera, "https": True, "ports": [80, 443, 8765],
                          "requires": "Raspberry Pi OS 64-bit Trixie; Desktop unless --no-kiosk", "automatic_reboot": False}, indent=2))
        return
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Utilisez le lancement en une commande; cette étape système demande sudo sur le Pi.")
    os.umask(0o077)
    with installation_lock():
        installer.apply()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Installation interrompue : {exc}", file=sys.stderr)
        sys.exit(1)
