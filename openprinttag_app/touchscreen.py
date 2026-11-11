"""Manage the current user's labwc touchscreen profiles without changing outputs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET


ET.register_namespace("", "http://openbox.org/3.4/rc")
UNAVAILABLE = "Le mode tactile est disponible sur le Raspberry Pi avec un écran tactile raccordé."
CHANGED = "Les réglages du bureau ou l’écran tactile ont changé. Actualisez avant de réessayer."
INVALID = "Les réglages du bureau ne peuvent pas être modifiés. Vérifiez leur fichier de configuration."
APPLY_FAILED = "Le mode tactile n’a pas pu être appliqué. Actualisez et vérifiez le bureau du Pi."


class TouchscreenError(ValueError):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def name_of(tag):
    return tag.rsplit("}", 1)[-1].casefold() if isinstance(tag, str) else ""


def option(entry, name, default=""):
    values = [value for key, value in entry.attrib.items() if name_of(key) == name.casefold()]
    values += [(child.text or "").strip() for child in entry if name_of(child.tag) == name.casefold()]
    if len(values) > 1:
        raise TouchscreenError(INVALID)
    return values[0] if values else default


def set_option(entry, name, value):
    children = [child for child in entry if name_of(child.tag) == name.casefold()]
    attributes = [key for key in entry.attrib if name_of(key) == name.casefold()]
    if children:
        children[0].text = value
    else:
        entry.set(attributes[0] if attributes else name, value)


class LabwcTouchscreen:
    def __init__(self, enabled=False, *, home=None, input_dir=Path("/sys/class/input"),
                 udev_dir=Path("/run/udev/data"), proc_dir=Path("/proc"),
                 model_path=Path("/proc/device-tree/model"), runner=subprocess.run):
        self.enabled = enabled
        self.home = Path.home() if home is None else Path(home)
        self.path = self.home / ".config/labwc/rc.xml"
        self.input_dir, self.udev_dir, self.proc_dir = Path(input_dir), Path(udev_dir), Path(proc_dir)
        self.model_path, self.runner = Path(model_path), runner
        self.lock = threading.RLock()

    def _devices(self):
        devices = set()
        for event in sorted(self.input_dir.glob("event*")):
            try:
                number = (event / "dev").read_text().strip()
                if not all(piece.isdigit() for piece in number.split(":")) or number.count(":") != 1:
                    continue
                properties = (self.udev_dir / ("c" + number)).read_text().splitlines()
                if "E:ID_INPUT_TOUCHSCREEN=1" in properties:
                    name = (event / "device/name").read_text().strip()
                    if name:
                        devices.add(name)
            except OSError:
                continue
        return sorted(devices)

    def _compositor(self):
        try:
            result = self.runner(["/usr/bin/pgrep", "-u", str(os.getuid()), "-x", "labwc"],
                                 capture_output=True, text=True, timeout=3, check=True)
            pids = result.stdout.split()
            if len(pids) != 1 or not pids[0].isdigit() or int(pids[0]) <= 1:
                raise ValueError()
            directory = self.proc_dir / pids[0]
            if directory.stat().st_uid != os.getuid() or (directory / "comm").read_text().strip() != "labwc":
                raise ValueError()
            args = (directory / "cmdline").read_bytes().decode().split("\0")
            environment = dict(item.split("=", 1) for item in (directory / "environ").read_bytes().decode().split("\0") if "=" in item)
            if (any(arg in {"-c", "--config", "-C", "--config-dir"} or arg.startswith(("--config=", "--config-dir="))
                    or arg.startswith(("-c", "-C")) for arg in args[1:] if arg)
                    or Path(environment.get("XDG_CONFIG_HOME", self.home / ".config")) != self.home / ".config"):
                raise ValueError()
            return pids[0]
        except (OSError, ValueError, subprocess.SubprocessError):
            raise TouchscreenError("Le bureau du Pi n’est pas disponible pour régler le tactile. Ouvrez sa session graphique puis actualisez.") from None

    def _check_paths(self):
        private_parent = False
        for directory in (self.home, self.home / ".config", self.path.parent):
            if directory.is_symlink():
                raise TouchscreenError(INVALID)
            if directory.exists():
                info = directory.stat()
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o022 and not private_parent):
                    raise TouchscreenError(INVALID)
                private_parent = private_parent or not info.st_mode & 0o077
        for path in (self.path, self.path.with_name("rc.xml.opt-station-backup")):
            if path.is_symlink():
                raise TouchscreenError(INVALID)
            if path.exists():
                info = path.stat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o022 and not private_parent):
                    raise TouchscreenError(INVALID)

    def _read(self):
        self._check_paths()
        if not self.path.exists():
            return b"", ET.Element("labwc_config")
        if self.path.stat().st_size > 131072:
            raise TouchscreenError(INVALID)
        raw = self.path.read_bytes()
        if len(raw) > 131072 or b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
            raise TouchscreenError(INVALID)
        try:
            root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
        except ET.ParseError:
            raise TouchscreenError(INVALID) from None
        if name_of(root.tag) not in {"labwc_config", "openbox_config"}:
            raise TouchscreenError(INVALID)
        return raw, root

    def _context(self):
        try:
            if not self.enabled or not self.model_path.read_text().startswith("Raspberry Pi"):
                raise TouchscreenError(UNAVAILABLE)
            devices = self._devices()
            if not devices:
                raise TouchscreenError("Aucun écran tactile détecté. Vérifiez le raccordement puis actualisez.")
            pid = self._compositor()
            raw, root = self._read()
            return raw, root, devices, pid
        except OSError:
            raise TouchscreenError(UNAVAILABLE) from None

    def _entries(self, root, device):
        entries = [entry for entry in root if name_of(entry.tag) == "touch"]
        exact = [entry for entry in entries if option(entry, "deviceName") == device]
        fallback = [entry for entry in entries if not option(entry, "deviceName")]
        if len(exact) > 1 or not exact and len(fallback) > 1:
            raise TouchscreenError(INVALID)
        return exact, exact or fallback

    def _snapshot(self, raw, root, devices, pid):
        states = []
        for device in devices:
            _, entries = self._entries(root, device)
            value = option(entries[0], "mouseEmulation", "no").casefold() if entries else "no"
            if value not in {"yes", "true", "1", "on", "no", "false", "0", "off"}:
                raise TouchscreenError(INVALID)
            states.append(value in {"no", "false", "0", "off"})
        revision = hashlib.sha256(raw + b"\0" + json.dumps([devices, pid], ensure_ascii=True).encode()).hexdigest()
        return {"supported": True, "enabled": all(states), "mixed": len(set(states)) > 1,
                "revision": revision, "devices": devices, "message": "Le mode tactile permet de faire défiler les listes en glissant un doigt."}

    def snapshot(self):
        with self.lock:
            try:
                return self._snapshot(*self._context())
            except TouchscreenError as exc:
                return {"supported": False, "enabled": None, "mixed": False, "revision": None, "devices": [], "message": str(exc)}

    @staticmethod
    def _write(path, raw, mode=0o600):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".opt-touch-", delete=False) as output:
                temporary = Path(output.name)
                os.fchmod(output.fileno(), mode)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def save(self, revision, enabled):
        with self.lock:
            raw, root, devices, pid = self._context()
            current = self._snapshot(raw, root, devices, pid)
            if revision != current["revision"]:
                raise TouchscreenError(CHANGED, 409)
            if current["enabled"] == enabled and not current["mixed"]:
                return {**current, "message": "Mode tactile activé." if enabled else "Mode tactile désactivé."}
            for device in devices:
                exact, effective = self._entries(root, device)
                namespace = root.tag.rsplit("}", 1)[0] + "}" if "}" in root.tag else ""
                if exact:
                    entry = exact[0]
                else:
                    entry = copy.deepcopy(effective[0]) if effective else ET.Element(namespace + "touch")
                    set_option(entry, "deviceName", device)
                    root.append(entry)
                set_option(entry, "mouseEmulation", "no" if enabled else "yes")
            updated = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            mode = stat.S_IMODE(self.path.stat().st_mode) if raw else 0o600
            if (self.path.read_bytes() if self.path.exists() else b"") != raw:
                raise TouchscreenError(CHANGED, 409)
            try:
                (self.home / ".config").mkdir(mode=0o700, exist_ok=True)
                self.path.parent.mkdir(mode=0o700, exist_ok=True)
                self._check_paths()
                if raw:
                    self._write(self.path.with_name("rc.xml.opt-station-backup"), raw)
                self._write(self.path, updated, mode)
                environment = os.environ.copy()
                environment["LABWC_PID"] = pid
                self.runner(["/usr/bin/labwc", "--reconfigure"], env=environment,
                            capture_output=True, text=True, timeout=5, check=True)
            except (OSError, subprocess.SubprocessError):
                if self.path.exists() and self.path.read_bytes() == updated:
                    if raw:
                        self._write(self.path, raw, mode)
                    else:
                        self.path.unlink()
                    try:
                        self.runner(["/usr/bin/labwc", "--reconfigure"], env={**os.environ, "LABWC_PID": pid},
                                    capture_output=True, text=True, timeout=5, check=True)
                    except (OSError, subprocess.SubprocessError):
                        pass
                raise TouchscreenError(APPLY_FAILED) from None
            return {**self._snapshot(*self._context()), "message": "Mode tactile activé." if enabled else "Mode tactile désactivé."}
