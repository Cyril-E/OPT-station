"""Bootstrap trust boundaries and transactional installation on an isolated host.

The host tests fake apt/systemd/HTTPS and use real private files and SQLite.
They do not qualify a first boot on a physical, freshly imaged Raspberry Pi.
"""
import argparse
import fcntl
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.backups import BackupError, MaintenanceGate
from openprinttag_app.config import Settings
from openprinttag_app import installation

ROOT = Path(__file__).parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


bootstrap = module("bootstrap_test", "bootstrap.py")
installer = module("station_installer_test", "install-station.py")


def release(tag="v0.17.0", **extras):
    return {"tag_name": tag, "draft": False, "prerelease": True,
            "assets": [{"name": f"opt-station-{tag}.tar.gz"}, {"name": f"opt-station-{tag}.tar.gz.sha256"}], **extras}


def test_release_discovery_includes_prereleases_and_checks_assets():
    assert bootstrap.select_release([release("v0.16.1"), release(), release("v0.18.0", draft=True)])["tag_name"] == "v0.17.0"
    assert bootstrap.select_release([release(), release("v0.18.0")], "v0.17.0")["tag_name"] == "v0.17.0"
    with pytest.raises(ValueError, match="Aucune release"):
        bootstrap.select_release([release("v0.16.1"), release(assets=[])])
    with pytest.raises(ValueError, match="Aucune release"):
        bootstrap.select_release([release(assets=release()["assets"] * 2)])


@pytest.mark.parametrize("tag", ["../bad", "v0.17.0/evil", "$(echo bad)", "v00.17.0", "v0.17.0\n", None])
def test_invalid_release_tags_never_become_download_paths(tag):
    with pytest.raises(ValueError):
        bootstrap.version_key(tag)


@pytest.mark.parametrize("url", ["http://github.com/test", "https://github.com.evil.test/file",
                                  "https://user@github.com/file", "https://github.com:444/file", "file:///tmp/file"])
def test_downloads_and_redirects_require_known_https_hosts(url):
    assert not bootstrap.allowed_url(url)
    with pytest.raises(ValueError):
        bootstrap.Redirects().redirect_request(None, None, 302, "", {}, url)


def test_checksums_are_exact_and_bound_to_filename(tmp_path):
    path = tmp_path / "opt-station-v0.17.0.tar.gz"
    path.write_bytes(b"verified sources")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    record = (digest + "  " + path.name + "\n").encode()
    assert bootstrap.verify_checksum(path, record, path.name, "sha256:" + digest) == digest
    for text in (record.replace(path.name.encode(), b"another.tar.gz"), record + record, b"0" * 64 + b"  " + path.name.encode()):
        with pytest.raises(ValueError):
            bootstrap.verify_checksum(path, text, path.name)
    with pytest.raises(ValueError):
        bootstrap.verify_checksum(path, record, path.name, "sha256:" + "0" * 64)


def package(path, extra=None, omit=None, project="0.17.0"):
    with tarfile.open(path, "w:gz") as archive:
        for name in (*bootstrap.REQUIRED, ".gitignore"):
            if name == omit:
                continue
            content = (f'[project]\nversion="{project}"\n' if name == "pyproject.toml" else
                       f'__version__ = "{project}"\n' if name == "openprinttag_app/__init__.py" else "source\n").encode()
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        if extra:
            archive.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.isfile() else None)


def test_complete_sources_extract_without_owner_or_special_modes(tmp_path):
    archive = tmp_path / "sources.tar.gz"
    package(archive)
    target = tmp_path / "target"; target.mkdir()
    bootstrap.extract_sources(archive, target, "v0.17.0")
    assert (target / ".gitignore").read_text() == "source\n"
    assert (target / "deploy/install-station.py").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("name,kind", [("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
    (".git/config", tarfile.REGTYPE), ("var/private.json", tarfile.REGTYPE), ("deploy/link", tarfile.SYMTYPE),
    ("deploy/hardlink", tarfile.LNKTYPE), ("deploy/device", tarfile.CHRTYPE), ("pyproject.toml", tarfile.REGTYPE),
    ("a/../../escape", tarfile.REGTYPE), ("a\\escape", tarfile.REGTYPE), ("a//escape", tarfile.REGTYPE)])
def test_untrusted_archive_is_rejected_before_writing(tmp_path, name, kind):
    archive = tmp_path / "sources.tar.gz"
    extra = tarfile.TarInfo(name); extra.type = kind; extra.linkname = "../../escape"
    package(archive, extra)
    target = tmp_path / "target"; target.mkdir()
    with pytest.raises(ValueError, match="Archive non sûre"):
        bootstrap.extract_sources(archive, target, "v0.17.0")
    assert list(target.iterdir()) == []


def test_missing_installer_version_mismatch_and_expansion_limit(tmp_path, monkeypatch):
    archive = tmp_path / "sources.tar.gz"
    target = tmp_path / "target"; target.mkdir()
    package(archive, omit="deploy/install-station.py")
    with pytest.raises(ValueError, match="incomplète"):
        bootstrap.extract_sources(archive, target, "v0.17.0")
    assert not list(target.iterdir())
    package(archive, project="0.16.1")
    with pytest.raises(ValueError, match="version des sources"):
        bootstrap.extract_sources(archive, target, "v0.17.0")
    shutil.rmtree(target); target.mkdir()
    monkeypatch.setattr(bootstrap, "MAX_EXTRACTED", 4)
    with pytest.raises(ValueError, match="volumineuse"):
        bootstrap.extract_sources(archive, target, "v0.17.0")
    assert not list(target.iterdir())


def test_debian_identified_pi_os_is_accepted_but_not_other_hosts(tmp_path, monkeypatch):
    model = tmp_path / "model"; model.write_bytes(b"Raspberry Pi 5 Model B\0")
    monkeypatch.setattr(bootstrap, "PI_MODEL", model)
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(bootstrap.platform, "freedesktop_os_release", lambda: {"ID": "debian", "VERSION_CODENAME": "trixie"})
    bootstrap.supported_platform()
    model.write_bytes(b"Other ARM computer")
    with pytest.raises(ValueError, match="Trixie uniquement"):
        bootstrap.supported_platform()


def test_systemd_command_quotes_spaces_and_percent_and_stays_loopback(tmp_path):
    source = tmp_path / "apps with space/opt%station"
    text = installer.service(source, tmp_path / "data", "hardware", True)
    assert '"--host" "127.0.0.1"' in text and '"--camera"' in text
    assert "opt%%station" in text and "--lan" not in text
    assert 'WorkingDirectory=' + str(source).replace('%', '%%') + '\n' in text
    assert "TimeoutStopSec=45" in text


class Host:
    """Fake only operating-system operations, never the transaction filesystem."""
    def __init__(self, tmp_path, monkeypatch, existing=False, kiosk=False):
        self.home, self.root = tmp_path / "home/maker", tmp_path / "system"
        self.source = self.home / "apps/new-source"
        self.source.mkdir(parents=True)
        shutil.copytree(ROOT / "deploy", self.source / "deploy", ignore=shutil.ignore_patterns("__pycache__"))
        (self.source / "pyproject.toml").write_text('[project]\nversion="0.17.0"\n')
        self.account = pwd.struct_passwd(("maker", "x", os.getuid(), os.getgid(), "", str(self.home), "/bin/bash"))
        self.args = argparse.Namespace(source=self.source, no_camera=False, no_kiosk=not kiosk, archive_sha256="a" * 64)
        self.calls, self.failure, self.binds = [], None, []
        self.live_source = None
        self.old_source = self.home / "apps/previous-source"
        self.stable = self.home / "apps/openprinttag-station"
        self.data = self.home / "openprinttag-data"
        self.unit = self.home / ".config/systemd/user/openprinttag.service"
        self.dropin = self.unit.parent / "openprinttag.service.d/https.conf"
        self.ca = self.system("/etc/opt-station/root-ca.crt")
        self.metadata = self.system("/etc/opt-station/https.json")
        self.active = existing
        self.enabled = existing
        self.gateway_active = existing
        self.gateway_enabled = existing
        if existing:
            self.old_source.mkdir()
            (self.old_source / "pyproject.toml").write_text('[project]\nversion="0.16.1"\n')
            self.stable.symlink_to(self.old_source)
            self.live_source = self.old_source
            self.data.mkdir()
            with sqlite3.connect(self.data / "inventory.sqlite3") as db:
                db.execute("CREATE TABLE spools(number TEXT, notes TEXT)")
                db.execute("INSERT INTO spools VALUES ('B0003', 'empty spool 278 g')")
            (self.data / "printer-settings.json").write_text('{"api_key":"local-test-secret"}\n')
            self.unit.parent.mkdir(parents=True)
            self.unit.write_text(installer.service(self.stable, self.data, "hardware", True))
            self.dropin.parent.mkdir()
            self.dropin.write_text('# Managed by OPT Station HTTPS\n[Service]\nExecStart=\nExecStart="python" "-m" "openprinttag_app" "--data-dir" "' + str(self.data) + '" "--mode" "hardware" "--port" "8766" "--camera"\n')
            self.ca.parent.mkdir(parents=True)
            self.ca.write_text("existing-public-ca\n")
            self.metadata.write_text('{"url":"https://station.local"}\n')
            self.system("/etc/opt-station/Caddyfile").write_text("# Managed by OPT Station HTTPS\nold gateway\n")
            proc = self.system("/proc/12345/cmdline"); proc.parent.mkdir(parents=True)
            proc.write_bytes(("python\0-m\0openprinttag_app\0--data-dir\0" + str(self.data) + "\0--mode\0hardware\0--port\08766\0--camera\0").encode())
        if kiosk:
            lightdm = self.system("/etc/lightdm/lightdm.conf"); lightdm.parent.mkdir(parents=True)
            lightdm.write_text("[Seat:*]\n#autologin-user=\n")
            init = self.system("/etc/init.d/lightdm"); init.parent.mkdir(parents=True); init.touch()
        monkeypatch.setattr(installer, "SYSTEM_ROOT", self.root)
        monkeypatch.setattr(installer, "run", self.run)
        monkeypatch.setattr(installer, "read_json", self.read_json)
        monkeypatch.setattr(installer.os, "chown", lambda *args: None)
        monkeypatch.setattr(installer.os, "lchown", lambda *args: None)
        monkeypatch.setattr(installer.os, "fchown", lambda *args: None)
        monkeypatch.setattr(installer.pwd, "getpwuid", lambda _: self.account)
        monkeypatch.setattr(installer.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * 1024**3))
        host = self
        class Listener:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def bind(self, address): host.binds.append(address[1])
        monkeypatch.setattr(installer.socket, "socket", Listener)
        real_load = installer.load
        monkeypatch.setattr(installer, "load", lambda name, path: (
            SimpleNamespace(supported_platform=lambda: None) if name == "opt_bootstrap" else
            SimpleNamespace(addresses=lambda *args: ["station.local"], discover_addresses=lambda: ["192.0.2.10"])
            if name == "opt_https_installer" else real_load(name, path)))

    def system(self, name):
        return self.root / name.lstrip("/")

    def read_json(self, url):
        if url.endswith("/api/system/power"):
            return {"busy": False, "pending": None}
        return {"version": "wrong" if self.failure == "final-health" and self.gateway_active else "0.17.0", "mode": "hardware"}

    def run(self, *arguments, check=True, capture_output=False, **kwargs):
        args = list(map(str, arguments)); self.calls.append(args)
        code, text = 0, ""
        if args[0] == "runuser":
            if "systemd-analyze" in args:
                return subprocess.CompletedProcess(args, 1 if self.failure == "unit-validation" else 0,
                                                   "", "invalid unit" if self.failure == "unit-validation" else "")
            if "systemctl" not in args:
                return subprocess.CompletedProcess(args, 0, "", "")
            args = args[args.index("systemctl"):]  # use the same state for user units
        if args[0] == "tar":
            name = args[args.index("-czpf") + 1] if "-czpf" in args else args[args.index("-xzpf") + 1]
            target = Path(args[args.index("-C") + 1])
            if "-czpf" in args:
                if self.failure == "snapshot":
                    raise OSError("disk full during backup")
                assert not self.active, "SQLite must be copied only after service stop"
                with tarfile.open(name, "w:gz") as archive: archive.add(target, arcname=".")
            else:
                with tarfile.open(name) as archive: archive.extractall(target, filter="data")
        elif args[0] == "systemctl":
            command = next((a for a in args[1:] if not a.startswith("--")), "")
            gateway = "opt-station-https.service" in args
            active, enabled = (self.gateway_active, self.gateway_enabled) if gateway else (self.active, self.enabled)
            if "openprinttag-display.service" in args:
                active = enabled = False
            if command == "is-active": code = 0 if active else 3
            elif command == "is-enabled": code = 0 if enabled else 1
            elif command == "show":
                if "--property=FragmentPath" in args: text = str(self.unit) + "\n"
                if "--property=DropInPaths" in args: text = str(self.dropin) + "\n" if self.dropin.exists() else "\n"
                if "--property=MainPID" in args: text = "12345\n"
            elif command in {"stop", "start", "enable", "disable"}:
                if gateway:
                    if command in {"stop", "start"}: self.gateway_active = command == "start"
                    if command in {"enable", "disable"}: self.gateway_enabled = command == "enable"
                elif "openprinttag.service" in args:
                    if command == "stop": self.active = False
                    if command == "disable": self.enabled = False
                    if command == "enable": self.enabled = True
                    if command == "start" or (command == "enable" and "--now" in args):
                        self.active = True
                        self.live_source = self.stable.resolve()
                        if self.live_source == self.source and self.data.exists():
                            (self.data / "migration-attempt.json").write_text("new version data\n")
        elif args[0] == "loginctl":
            text = "yes\n"
        elif args[0] == "python3" and args[1].endswith("install-https.py"):
            if self.failure == "https":
                raise subprocess.CalledProcessError(1, args)
            self.ca.parent.mkdir(parents=True, exist_ok=True)
            if not self.ca.exists(): self.ca.write_text("new-public-ca\n")
            self.metadata.write_text('{"url":"https://station.local"}\n')
            self.dropin.parent.mkdir(parents=True, exist_ok=True)
            self.dropin.write_text("# Managed by OPT Station HTTPS\nnew override\n")
            self.gateway_active = self.gateway_enabled = True
        if code and check:
            raise subprocess.CalledProcessError(code, args, text)
        return subprocess.CompletedProcess(args, code, text, "")

    def install(self):
        self.instance = installer.Installer(self.args, self.account)
        self.instance.apply()
        return self.instance


def test_fresh_headless_install_creates_services_data_receipt_and_https(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch)
    instance = host.install()
    assert host.stable.resolve() == host.source
    assert host.active and host.enabled and host.gateway_active
    assert host.data.is_dir() and host.ca.read_text() == "new-public-ca\n"
    assert json.loads(instance.receipt.read_text())["archive_sha256"] == "a" * 64
    assert instance.receipt.stat().st_mode & 0o777 == 0o600
    assert not any("reboot" in call for call in host.calls)
    assert not (host.home / ".config/autostart/openprinttag.desktop").exists()


def test_rerun_preserves_database_settings_ca_and_camera_profile(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, existing=True)
    before = {p.name: p.read_bytes() for p in host.data.iterdir()}
    ca = host.ca.read_bytes()
    instance = host.install()
    assert host.stable.resolve() == host.source and host.active
    assert all((host.data / name).read_bytes() == content for name, content in before.items())
    assert host.ca.read_bytes() == ca
    assert json.loads(instance.receipt.read_text())["camera"] is True
    assert (instance.backup / "data-before.tar.gz").is_file()
    assert (instance.backup / "files/manifest.json").is_file()


def test_https_failure_restores_previous_sources_sqlite_settings_and_units(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, existing=True)
    before = {p.name: p.read_bytes() for p in host.data.iterdir()}
    unit, dropin = host.unit.read_bytes(), host.dropin.read_bytes()
    host.failure = "https"
    with pytest.raises(subprocess.CalledProcessError): host.install()
    assert host.stable.resolve() == host.old_source and host.active and host.gateway_active
    assert {p.name: p.read_bytes() for p in host.data.iterdir()} == before
    assert host.unit.read_bytes() == unit and host.dropin.read_bytes() == dropin
    assert host.ca.read_text() == "existing-public-ca\n"
    assert (host.instance.failed_data / "migration-attempt.json").exists()


def test_backup_failure_leaves_original_data_and_restarts_old_version(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, existing=True)
    before = {p.name: p.read_bytes() for p in host.data.iterdir()}
    host.failure = "snapshot"
    with pytest.raises(OSError, match="disk full"): host.install()
    assert {p.name: p.read_bytes() for p in host.data.iterdir()} == before
    assert host.stable.resolve() == host.old_source and host.active
    assert not hasattr(host.instance, "failed_data")


def test_unknown_service_and_active_operation_are_refused_before_apt(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, existing=True)
    host.unit.write_text("[Service]\nExecStart=/usr/bin/another-app\n")
    with pytest.raises(ValueError, match="non reconnu"): host.install()
    assert not any(call[0] == "apt-get" for call in host.calls)
    host.unit.write_text(installer.service(host.stable, host.data, "hardware", True))
    monkeypatch.setattr(installer, "read_json", lambda _: {"busy": True})
    with pytest.raises(ValueError, match="Terminez"): host.install()
    assert not any(call[0] == "apt-get" for call in host.calls)


def test_desktop_autostart_and_autologin_are_installed_without_reboot(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, kiosk=True)
    host.install()
    assert (host.home / ".config/autostart/openprinttag.desktop").is_file()
    assert "autologin-user=maker" in host.system("/etc/lightdm/lightdm.conf.d/50-opt-station.conf").read_text()
    assert ["systemctl", "set-default", "graphical.target"] in host.calls
    assert not any("reboot" in call for call in host.calls)


def test_lite_without_no_kiosk_and_conflicting_autologin_are_refused(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch)
    host.args.no_kiosk = False
    with pytest.raises(ValueError, match="avec bureau"): host.install()
    path = host.system("/etc/lightdm/lightdm.conf"); path.parent.mkdir(parents=True)
    path.write_text("[Seat:*]\nautologin-user=another-user\n")
    init = host.system("/etc/init.d/lightdm"); init.parent.mkdir(parents=True); init.touch()
    with pytest.raises(ValueError, match="autre session"): host.install()


def test_system_lock_blocks_mutations_hardware_and_power_but_not_health(tmp_path, monkeypatch):
    path = tmp_path / "install.lock"; path.touch()
    monkeypatch.setattr(installation, "INSTALL_LOCK", path)
    with TestClient(create_app(Settings(tmp_path / "data")), client=("127.0.0.1", 1)) as client, path.open("rb") as lock:
        assert not installation.installation_busy()
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert installation.installation_busy()
        assert client.get("/api/status").status_code == 200
        assert client.get("/api/system/power").status_code == 200
        assert client.get("/api/inventory").status_code == 200
        for method, route in (("GET", "/api/reader/tag"), ("POST", "/api/system/power"), ("PUT", "/api/configuration/network")):
            assert client.request(method, route, json={}).status_code == 503
        with pytest.raises(BackupError, match="installation"):
            with MaintenanceGate().hold(requests=0): pass
        fcntl.flock(lock, fcntl.LOCK_UN)
        assert not installation.installation_busy()
        assert client.get("/api/reader/tag").status_code == 200


@pytest.mark.parametrize("dry_run", [False, True])
def test_bootstrap_verifies_release_before_invoking_installer(tmp_path, monkeypatch, dry_run):
    archive = tmp_path / "archive.tar.gz"; package(archive)
    payload = archive.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    row = release()
    row["assets"][0]["digest"] = "sha256:" + digest
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(bootstrap.pwd, "getpwuid", lambda _: SimpleNamespace(pw_dir=str(home), pw_name="maker"))
    monkeypatch.setattr(bootstrap, "supported_platform", lambda: None)
    calls = []
    def fetch(url, limit, target=None):
        if url.startswith(bootstrap.API): return json.dumps([row]).encode()
        if url.endswith(".sha256"): return (digest + "  opt-station-v0.17.0.tar.gz\n").encode()
        assert target is not None
        target.write(payload)
    monkeypatch.setattr(bootstrap, "fetch", fetch)
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda args, **kwargs: calls.append(args))
    arguments = ["--no-kiosk", "--no-camera"] + (["--dry-run"] if dry_run else [])
    bootstrap.main(arguments)
    assert len(calls) == 1
    assert calls[0][0] == ("python3" if dry_run else "sudo")
    assert "--archive-sha256" in calls[0] and digest in calls[0]
    assert "--no-kiosk" in calls[0] and "--no-camera" in calls[0]
    assert (home / "apps").exists() is not dry_run


def test_newer_version_and_custom_override_are_not_overwritten(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, existing=True)
    (host.old_source / "pyproject.toml").write_text('[project]\nversion="0.18.0"\n')
    with pytest.raises(ValueError, match="plus ancienne"): host.install()
    assert not any(call[0] == "apt-get" for call in host.calls)
    (host.old_source / "pyproject.toml").write_text('[project]\nversion="0.16.1"\n')
    host.dropin.write_text("[Service]\nExecStart=/usr/bin/custom\n")
    with pytest.raises(ValueError, match="n’est pas reconnue"): host.install()
    assert not any(call[0] == "apt-get" for call in host.calls)


def test_https_repair_uses_the_running_backend_port():
    https = module("https_installer_ports", "install-https.py")
    assert https.runtime_port(["python", "-m", "openprinttag_app"]) == 8765
    assert https.runtime_port(["python", "--port", "8766"]) == 8766
    for arguments in (["--port"], ["--port", "bad"], ["--port", "0"], ["--port", "65536"]):
        with pytest.raises(ValueError): https.runtime_port(arguments)


def test_gateway_repair_does_not_treat_own_backend_as_a_conflict(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, existing=True)
    host.gateway_active = False
    host.install()
    assert host.binds == [80, 443, 8765]
    assert host.active and host.gateway_active


def test_failed_activation_restores_desktop_and_new_install_files(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, kiosk=True)
    lightdm = host.system("/etc/lightdm/lightdm.conf")
    before = lightdm.read_bytes()
    host.failure = "final-health"
    with pytest.raises(ValueError, match="version et le mode"): host.install()
    assert lightdm.read_bytes() == before
    assert not host.stable.exists() and not host.unit.exists()
    assert not host.active and not host.gateway_active
    assert not host.system("/etc/lightdm/lightdm.conf.d/50-opt-station.conf").exists()
    assert not (host.home / ".config/autostart/openprinttag.desktop").exists()
    assert not host.ca.exists()


def test_data_symlink_outside_account_is_refused_before_any_installation(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch)
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "keep.txt").write_text("keep\n")
    host.data.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="dossier de données"): host.install()
    assert not any(call[0] == "apt-get" for call in host.calls)
    assert (outside / "keep.txt").read_text() == "keep\n"


def test_release_builder_produces_a_verified_installable_pair_and_rejects_snapshots(tmp_path):
    builder = module("installer_release_builder", "build-release.py")
    archive = tmp_path / "source.tar.gz"; package(archive)
    output = tmp_path / "output"
    asset, checksum = builder.build(gzip.decompress(archive.read_bytes()), output)
    assert asset.name == "opt-station-v0.17.0.tar.gz"
    assert bootstrap.verify_checksum(asset, checksum.read_bytes(), asset.name)
    with pytest.raises(ValueError, match="existent déjà"):
        builder.build(gzip.decompress(archive.read_bytes()), output)
    package(archive, project="0.17.0.dev0")
    with pytest.raises(ValueError, match="Finalisez"):
        builder.build(gzip.decompress(archive.read_bytes()), tmp_path / "snapshot")


def test_installer_version_order_refuses_a_same_patch_downgrade(tmp_path):
    file = tmp_path / "pyproject.toml"
    keys = []
    for version in ("0.17.0.dev0", "0.17.0rc1", "0.17.0rc2", "0.17.0", "0.17.1.dev0"):
        file.write_text(f'[project]\nversion="{version}"\n')
        keys.append(installer.version(file)[1])
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


def test_invalid_systemd_unit_is_refused_before_stopping_existing_station(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, existing=True)
    host.failure = "unit-validation"
    with pytest.raises(ValueError, match="n’a pas été arrêtée"):
        host.install()
    assert host.active and host.stable.resolve() == host.old_source
    assert not any("stop" in call for call in host.calls)
    assert not (host.home / "openprinttag-backups").exists()


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="The real systemd parser is only available on Linux")
def test_real_systemd_parser_accepts_service_directory_with_spaces_and_percent(tmp_path):
    source = tmp_path / "apps with spaces/opt%station"
    (source / ".venv/bin").mkdir(parents=True)
    (source / ".venv/bin/python").symlink_to(sys.executable)
    unit = tmp_path / "opt-unit-integration.service"
    unit.write_text(installer.service(source, tmp_path / "data", "hardware", True))
    result = subprocess.run(["systemd-analyze", "--user", "verify", "--man=no", str(unit)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_https_public_directories_remain_traversable_with_private_umask(tmp_path):
    https = module("https_directory_permissions", "install-https.py")
    previous = os.umask(0o077)
    try:
        transaction = https.Files(tmp_path / "backup")
        certificate = tmp_path / "etc/opt-station/root-ca.crt"
        transaction.write(certificate, "public certificate\n")
        assert certificate.parent.stat().st_mode & 0o777 == 0o755
        assert certificate.parent.parent.stat().st_mode & 0o777 == 0o755
        assert certificate.stat().st_mode & 0o777 == 0o644
        transaction.restore()
        assert not certificate.parent.exists()
    finally:
        os.umask(previous)


def test_installer_public_directories_and_cleanup_under_private_umask(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.os, "chown", lambda *args: None)
    monkeypatch.setattr(installer.os, "fchown", lambda *args: None)
    previous = os.umask(0o077)
    try:
        transaction = installer.Transaction(tmp_path / "backup")
        config = tmp_path / "etc/lightdm/conf.d/station.conf"
        transaction.write(config, "[Seat:*]\n", mode=0o644)
        assert all(path.stat().st_mode & 0o777 == 0o755 for path in transaction.created_dirs)
        transaction.restore()
        assert not config.parent.exists()
    finally:
        os.umask(previous)
