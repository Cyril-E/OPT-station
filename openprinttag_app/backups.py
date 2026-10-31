"""Application backups with optional encryption, guarded restore and scheduling.

Archives contain data, never SQL or executable code. SQLite schemas always come
from this application; imported rows are checked in a temporary trusted schema.
"""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import __version__
from .domain import validate_favorite_main, spool_snapshot
from .library_transfer import read_json
from .network import NetworkAccess
from .storage import ConflictError, Store, dumps, now

MAGIC = b"OPTBAK1\n"
PLAIN_MAGIC = b"OPTBAK0\n"
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_PLAIN = 64 * 1024 * 1024
CONFIG_FILES = ("network-settings.json", "printer-settings.json", "mcp-settings.json", "label-printer-settings.json", "backup-settings.json", "updates-settings.json")
TABLES = ("metadata", "spools", "favorites", "simulated_tags", "state", "tag_sources", "operations", "label_jobs", "inventory_notes")
NFC_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,140}\.(?:bin|json)\Z")


class BackupError(ValueError):
    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


def private_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".opt-backup-", delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def private_json(path, record):
    private_write(path, dumps(record).encode())


def derive(password, salt):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise BackupError("Choisissez un mot de passe de sauvegarde de 10 à 256 caractères.")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))


def encrypt(record, password=None, material=None):
    salt = material[0] if material else secrets.token_bytes(16)
    key = material[1] if material else derive(password, salt)
    nonce = secrets.token_bytes(12)
    raw = dumps(record).encode()
    if len(raw) > MAX_PLAIN:
        raise BackupError("Les données dépassent la limite de sauvegarde de 64 Mo.")
    encrypted = MAGIC + salt + nonce + AESGCM(key).encrypt(nonce, gzip.compress(raw), MAGIC + salt)
    if len(encrypted) > MAX_ARCHIVE:
        raise BackupError("La sauvegarde dépasse la limite de fichier de 32 Mo.")
    return encrypted


def encode_backup(record, password=None, material=None):
    if password not in (None, "") or material is not None:
        return encrypt(record, password=password, material=material)
    raw = dumps(record).encode()
    if len(raw) > MAX_PLAIN:
        raise BackupError("Les données dépassent la limite de sauvegarde de 64 Mo.")
    zipped = gzip.compress(raw)
    content = PLAIN_MAGIC + hashlib.sha256(zipped).digest() + zipped
    if len(content) > MAX_ARCHIVE:
        raise BackupError("La sauvegarde dépasse la limite de fichier de 32 Mo.")
    return content


def decrypt(content, password=None):
    if not isinstance(content, bytes) or not 40 <= len(content) <= MAX_ARCHIVE:
        raise BackupError("Fichier de sauvegarde OPT Station invalide ou trop volumineux.")
    try:
        if content.startswith(PLAIN_MAGIC):
            zipped = content[40:]
            if not secrets.compare_digest(content[8:40], hashlib.sha256(zipped).digest()):
                raise BackupError("Sauvegarde altérée : le contrôle d’intégrité a échoué.")
        elif content.startswith(MAGIC) and len(content) >= 52:
            if password in (None, ""):
                raise BackupError("Cette sauvegarde est protégée. Saisissez son mot de passe.")
            salt, nonce = content[8:24], content[24:36]
            zipped = AESGCM(derive(password, salt)).decrypt(nonce, content[36:], MAGIC + salt)
        else:
            raise BackupError("Fichier de sauvegarde OPT Station invalide ou trop volumineux.")
        decoder = zlib.decompressobj(31)
        raw = decoder.decompress(zipped, MAX_PLAIN + 1)
        if len(raw) > MAX_PLAIN or not decoder.eof or decoder.unused_data:
            raise BackupError("Contenu de sauvegarde invalide ou trop volumineux.")
        return read_json(raw)
    except InvalidTag:
        raise BackupError("Mot de passe incorrect ou sauvegarde altérée.") from None
    except BackupError:
        raise
    except (zlib.error, UnicodeError, ValueError):
        raise BackupError("Contenu de sauvegarde illisible.") from None


class MaintenanceGate:
    """Count requests rather than holding a thread lock across an async request."""
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.exclusive = False

    def enter(self):
        with self.lock:
            if self.exclusive:
                raise BackupError("Une sauvegarde ou restauration est en cours. Réessayez dans un instant.", 503)
            self.active += 1

    def leave(self):
        with self.lock:
            self.active -= 1

    @contextmanager
    def hold(self, requests=1):
        from .installation import installation_busy
        if installation_busy():
            raise BackupError("L’installation d’OPT Station est en cours. Réessayez dans un instant.", 503)
        with self.lock:
            if self.exclusive or self.active != requests:
                raise BackupError("Une opération est en cours. Réessayez la sauvegarde ou restauration après sa fin.", 409)
            self.exclusive = True
        try:
            yield
        finally:
            with self.lock:
                self.exclusive = False


def mounted_volumes():
    """Use the kernel mount table, never create a fake destination on the root disk."""
    result = []
    path = Path("/proc/self/mountinfo")
    if not path.exists():
        return result
    def unescape(value):
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)
    for line in path.read_text().splitlines():
        fields = line.split()
        split = fields.index("-")
        target, filesystem, source = unescape(fields[4]), fields[split + 1], unescape(fields[split + 2])
        if target in {"/", "/boot", "/boot/firmware"}:
            continue
        if not (source.startswith("/dev/") or filesystem in {"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"}):
            continue
        options = set(fields[5].split(",")) | set(fields[split + 3].split(","))
        result.append({"path": target, "source": source, "filesystem": filesystem,
                       "device": fields[2],
                       "writable": "ro" not in options and os.access(target, os.W_OK),
                       "network": filesystem in {"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"}})
    return result


def default_settings():
    return {"version": 1, "revision": 0, "enabled": False, "encrypted": False, "destination": "", "mount_path": "", "mount_source": "",
            "frequency": "daily", "time": "02:00", "weekday": 6, "timezone": "Europe/Paris", "keep": 14,
            "station_id": uuid.uuid4().hex}


def validate_schedule(record):
    if not isinstance(record, dict):
        raise BackupError("Réglages de sauvegarde invalides.")
    record = {"encrypted": True, **record}  # Legacy schedules always used encryption.
    for key in ("revision", "weekday", "keep", "version"):
        if type(record.get(key)) is not int:
            raise BackupError("Réglages de sauvegarde invalides.")
    if (record["version"] != 1 or record["revision"] < 0 or type(record.get("enabled")) is not bool or type(record.get("encrypted")) is not bool
            or not 0 <= record["weekday"] <= 6 or not 1 <= record["keep"] <= 365
            or record.get("frequency") not in {"daily", "weekly"}
            or not isinstance(record.get("time"), str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", record["time"])
            or not re.fullmatch(r"[a-f0-9]{32}", str(record.get("station_id", "")))):
        raise BackupError("Réglages de sauvegarde invalides.")
    try:
        ZoneInfo(record["timezone"])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise BackupError("Fuseau horaire de sauvegarde invalide.") from None
    for key in ("destination", "mount_path", "mount_source"):
        if not isinstance(record.get(key), str) or len(record[key]) > 1000 or "\x00" in record[key]:
            raise BackupError("Destination de sauvegarde invalide.")
    return deepcopy(record)


def database_copy(source, target):
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    Path(target).chmod(0o600)


def recover_restore(directory, database):
    """An interrupted multi-file restore always rolls back before the app opens."""
    directory = Path(directory)
    journal = directory / "restore-pending.json"
    if not journal.exists():
        return
    record = read_json(journal.read_bytes())
    identifier = record.get("point", "")
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise BackupError("Le journal de restauration est invalide. Conservez les données et le point de retour.", 503)
    point = directory / "restore-points" / identifier
    previous = read_json((point / "files.json").read_bytes())
    if not set(previous) <= set(CONFIG_FILES) | {"backup-key.json", "backup-state.json"}:
        raise BackupError("Le point de retour est invalide.", 503)
    if record.get("inventory"):
        database_copy(point / "inventory.sqlite3", database)
    for name, present in previous.items():
        path = directory / name
        if present:
            private_write(path, (point / name).read_bytes())
        else:
            path.unlink(missing_ok=True)
    for name in record.get("nfc_added", []):
        if not NFC_NAME.fullmatch(name):
            raise BackupError("Le journal des sauvegardes NFC est invalide.", 503)
        (directory / "nfc-backups" / name).unlink(missing_ok=True)
    journal.unlink()


class BackupManager:
    def __init__(self, settings, store, gate, busy=lambda: False, reload_configuration=lambda: None,
                 volumes=mounted_volumes, utcnow=lambda: datetime.now(timezone.utc)):
        self.settings, self.store, self.gate = settings, store, gate
        self.directory = Path(settings.data_dir)
        self.busy, self.reload_configuration, self.volumes, self.utcnow = busy, reload_configuration, volumes, utcnow
        self.lock = threading.RLock()
        self.path = self.directory / "backup-settings.json"
        self.key_path = self.directory / "backup-key.json"
        self.state_path = self.directory / "backup-state.json"
        self.configuration = validate_schedule(read_json(self.path.read_bytes())) if self.path.exists() else default_settings()
        self.state = read_json(self.state_path.read_bytes()) if self.state_path.exists() else {}
        self.previews = OrderedDict()
        self.stop_event = threading.Event()
        self.worker = None

    def snapshot(self):
        with self.lock:
            return {**deepcopy(self.configuration), "password_saved": self.configuration["encrypted"] and self.key_path.is_file(), "volumes": self.volumes(),
                    "last_result": deepcopy(self.state), "next_run": self.next_run() if self.configuration["enabled"] else None,
                    "restore_points": self.restore_points()}

    def restore_points(self):
        points = []
        for folder in (self.directory / "restore-points").glob("*"):
            if re.fullmatch(r"[a-f0-9]{32}", folder.name) and not folder.is_symlink() and (folder / "files.json").is_file():
                info = read_json((folder / "point.json").read_bytes()) if (folder / "point.json").exists() else {}
                points.append({"id": folder.name, "created_at": info.get("created_at") or datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat()})
        return sorted(points, key=lambda x: x["created_at"], reverse=True)[:20]

    def preview_point(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise BackupError("Point de retour introuvable.", 404)
        point = self.directory / "restore-points" / identifier
        if point.is_symlink() or not (point / "files.json").is_file():
            raise BackupError("Point de retour introuvable.", 404)
        with self.gate.hold(), self.lock:
            # This database was made locally by SQLite.backup, never uploaded.
            previous = read_json((point / "files.json").read_bytes())
            info = read_json((point / "point.json").read_bytes()) if (point / "point.json").exists() else {}
            if not isinstance(previous, dict) or not set(previous) <= set(CONFIG_FILES) | {"backup-key.json", "backup-state.json"}:
                raise BackupError("Le point de retour est invalide.")
            record = {"format": "opt-station-backup", "version": 1, "application_version": __version__,
                      "mode": self.settings.mode, "scope": "all", "created_at": info.get("created_at") or datetime.fromtimestamp(point.stat().st_mtime, timezone.utc).isoformat(),
                      "inventory": self._inventory(Store(point / "inventory.sqlite3")), "nfc_backups": {},
                      "configuration": {name: read_json((point / name).read_bytes()) for name in CONFIG_FILES if previous.get(name)}}
            summary = self._validate(record)
            return self._remember_preview(record, summary)

    def _destination(self, configuration):
        root, destination = Path(configuration["mount_path"]), Path(configuration["destination"])
        if not root.is_absolute() or not destination.is_absolute() or destination == root or ".." in destination.parts:
            raise BackupError("Choisissez un dossier de sauvegarde à l’intérieur d’un disque externe ou partage monté.")
        volume = next((x for x in self.volumes() if x["path"] == str(root) and x["source"] == configuration["mount_source"]), None)
        if not volume or not volume["writable"]:
            raise BackupError("Le disque ou partage de sauvegarde est absent ou en lecture seule. Aucune copie n’est créée sur le disque système.", 409)
        if root.resolve() != root or not destination.resolve().is_relative_to(root):
            raise BackupError("Le dossier doit rester sur le support choisi, sans lien vers un autre emplacement.")
        # Pin every existing component; never follow a symbolic link.
        for part in (destination, *destination.parents):
            if part == root:
                break
            if part.is_symlink():
                raise BackupError("Les liens symboliques ne sont pas acceptés comme destination de sauvegarde.")
        return destination

    @contextmanager
    def _open_destination(self):
        destination = self._destination(self.configuration)
        root = Path(self.configuration["mount_path"])
        volume = next(x for x in self.volumes() if x["path"] == str(root) and x["source"] == self.configuration["mount_source"])
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            device = os.fstat(descriptor).st_dev
            if volume.get("device") and volume["device"] != f"{os.major(device)}:{os.minor(device)}":
                raise BackupError("Le support de sauvegarde a été déconnecté. Aucune copie n’est créée sur le disque système.", 409)
            # Pin the mounted filesystem. Even if it is unmounted during the copy,
            # relative writes keep using this descriptor, never the root disk.
            for part in destination.relative_to(root).parts:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
                if os.fstat(descriptor).st_dev != device:
                    raise BackupError("Le dossier de sauvegarde traverse un autre support.")
            yield descriptor
        finally:
            os.close(descriptor)

    def _write_on_volume(self, descriptor, filename, content, prefix):
        temporary = ".opt-backup-" + secrets.token_hex(12)
        try:
            file = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            with os.fdopen(file, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.rename(temporary, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            os.fsync(descriptor)
            file = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            with os.fdopen(file, "rb") as check:
                if hashlib.sha256(check.read()).digest() != hashlib.sha256(content).digest():
                    raise BackupError("La copie de sauvegarde n’a pas pu être vérifiée.", 503)
            matching = re.compile(re.escape(prefix) + r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\.optbak\Z")
            files = []
            for name in os.listdir(descriptor):
                if matching.fullmatch(name):
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        files.append((name == filename, info.st_mtime_ns, name))
            files.sort(reverse=True)
            for _, _, name in files[self.configuration["keep"]:]:
                os.unlink(name, dir_fd=descriptor)
            os.fsync(descriptor)
        finally:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass

    def save(self, body):
        with self.lock:
            if body["revision"] != self.configuration["revision"]:
                raise ConflictError("Les réglages de sauvegarde ont changé. Rechargez-les avant d’enregistrer.")
            values = {**self.configuration, **{k: v for k, v in body.items() if k != "password"}}
            if "encrypted" not in body and body.get("password"):
                values["encrypted"] = True  # Preserve requests made by older clients.
            record = validate_schedule(values)
            password = body.get("password")
            material = None
            if record["encrypted"] and password:
                salt = secrets.token_bytes(16)
                material = {"salt": base64.b64encode(salt).decode(), "key": base64.b64encode(derive(password, salt)).decode()}
            if record["enabled"]:
                self._destination(record)
                if record["encrypted"] and not material and not self.key_path.exists():
                    raise BackupError("Saisissez le mot de passe à conserver pour les sauvegardes automatiques.")
            record["revision"] += 1
            before_key = self.key_path.read_bytes() if self.key_path.exists() else None
            try:
                if material:
                    private_json(self.key_path, material)
                elif not record["encrypted"]:
                    self.key_path.unlink(missing_ok=True)
                private_json(self.path, record)
            except OSError:
                if before_key is not None:
                    private_write(self.key_path, before_key)
                else:
                    self.key_path.unlink(missing_ok=True)
                raise
            was_enabled = self.configuration["enabled"]
            self.configuration = record
            if record["enabled"] and not was_enabled:
                self.state["last_slot"] = self._latest_slot()[0]
                private_json(self.state_path, self.state)
            return self.snapshot()

    def _inventory(self, store=None):
        tables = {}
        with (store or self.store).connect() as db:
            db.execute("BEGIN")
            for name in TABLES:
                columns = [r[1] for r in db.execute('PRAGMA table_info("' + name + '")')]
                rows = [[{"bytes": base64.b64encode(value).decode()} if isinstance(value, bytes) else value for value in row]
                        for row in db.execute('SELECT * FROM "' + name + '"')]
                tables[name] = {"columns": columns, "rows": rows}
        return {"schema": 5, "tables": tables}

    def collect(self, scope):
        if scope not in {"inventory", "configuration", "all"}:
            raise BackupError("Contenu de sauvegarde inconnu.")
        record = {"format": "opt-station-backup", "version": 1, "application_version": __version__,
                  "mode": self.settings.mode, "created_at": now(), "scope": scope}
        if scope in {"inventory", "all"}:
            record["inventory"] = self._inventory()
            record["nfc_backups"] = {}
            folder = self.directory / "nfc-backups"
            if folder.is_symlink():
                raise BackupError("Le dossier de sauvegardes NFC ne doit pas être un lien symbolique.")
            total = 0
            for path in sorted(folder.glob("*")):
                if not path.is_file() or path.is_symlink() or not NFC_NAME.fullmatch(path.name):
                    raise BackupError("Le dossier de sauvegardes NFC contient un fichier non reconnu.")
                total += path.stat().st_size
                if total > MAX_PLAIN // 2:
                    raise BackupError("Les sauvegardes NFC dépassent la limite de taille.")
                record["nfc_backups"][path.name] = base64.b64encode(path.read_bytes()).decode()
        if scope in {"configuration", "all"}:
            record["configuration"] = {name: read_json((self.directory / name).read_bytes()) for name in CONFIG_FILES if (self.directory / name).exists()}
        return record

    def download(self, scope, password=None):
        with self.gate.hold(), self.lock:
            if self.busy():
                raise BackupError("Arrêtez le scan QR et attendez la fin des opérations matérielles avant de sauvegarder.", 409)
            return encode_backup(self.collect(scope), password=password)

    def _validate_inventory(self, inventory, folder):
        if (not isinstance(inventory, dict) or type(inventory.get("schema")) is not int or inventory["schema"] not in {4, 5}
                or set(inventory.get("tables", {})) != set(TABLES)):
            raise BackupError("Schéma d’inventaire non pris en charge. Utilisez une version compatible d’OPT Station.")
        candidate = Store(folder / "candidate.sqlite3")
        self._insert_inventory(candidate, inventory, preserve=None)
        # Parse data through the same contracts used by the UI and MCP.
        for item in candidate.list_spools(include_removed=True):
            uuid.UUID(item["id"])
            uuid.UUID(item["instance_uuid"])
            if not isinstance(item.get("main"), dict) or not isinstance(item.get("aux"), dict) or type(item["version"]) is not int or item["version"] < 1:
                raise BackupError("Une fiche de bobine sauvegardée est invalide.")
            # Factory tags may derive their identity from the UID instead of
            # storing Main.instance_uuid. Validate using that existing identity.
            validated = spool_snapshot({"instance_uuid": item["instance_uuid"], **item["main"]}, item["aux"])
            if validated["instance_uuid"] != item["instance_uuid"] or validated["remaining_weight"] != item.get("remaining_weight"):
                raise BackupError("L’identité ou la consommation d’une bobine sauvegardée est incohérente.")
            Store._validate_notes(item["notes"])
            if type(item["notes_revision"]) is not int or item["notes_revision"] < 0:
                raise BackupError("Les notes sauvegardées sont invalides.")
            for field in ("added_at", "last_seen_at", "completed_at", "notes_updated_at"):
                if item.get(field):
                    stamp = datetime.fromisoformat(item[field])
                    if stamp.tzinfo is None:
                        raise BackupError("Une date de l’inventaire sauvegardé est invalide.")
        for item in candidate.favorites():
            uuid.UUID(item["id"])
            if not isinstance(item["name"], str) or not 1 <= len(item["name"].strip()) <= 120 or item["version"] < 1:
                raise BackupError("Une fiche de bibliothèque sauvegardée est invalide.")
            validate_favorite_main(item["main"])
        notes = candidate.inventory_notes()
        Store._validate_notes(notes["text"])
        if type(notes["revision"]) is not int or notes["revision"] < 0:
            raise BackupError("Le carnet commun sauvegardé est invalide.")
        with candidate.connect() as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("L’inventaire sauvegardé est incohérent.")
            counter = db.execute("SELECT value FROM metadata WHERE key='next_spool_number'").fetchone()
            highest = db.execute("SELECT COALESCE(MAX(sequence_number)+1,0) FROM spools").fetchone()[0]
            schema = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if not counter or not counter[0].isascii() or not counter[0].isdigit() or not highest <= int(counter[0]) <= 2**63 - 1 or not schema or schema[0] != "5":
                raise BackupError("Le compteur de bobines sauvegardé est invalide.")
            for key in ("library_revision", "inventory_revision"):
                revision = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
                if revision and (not revision[0].isascii() or not revision[0].isdigit() or int(revision[0]) > 2**63 - 2):
                    raise BackupError("Une révision de l’inventaire sauvegardé est invalide.")
            if db.execute("SELECT 1 FROM spools WHERE in_stock NOT IN (0,1) OR usage_state NOT IN ('stock','in_service') OR version<1 OR notes_revision<0 LIMIT 1").fetchone():
                raise BackupError("L’état d’une bobine sauvegardée est invalide.")
        return {"spools": len(candidate.list_spools(include_removed=True)), "completed": candidate.completed_count(),
                "templates": len(candidate.favorites())}

    @staticmethod
    def _insert_inventory(store, inventory, preserve):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for name in TABLES:
                table = inventory["tables"][name]
                columns = [r[1] for r in db.execute('PRAGMA table_info("' + name + '")')]
                old_spools = inventory["schema"] == 4 and name == "spools"
                expected_columns = columns[:-1] if old_spools else columns
                if not isinstance(table, dict) or table.get("columns") != expected_columns or not isinstance(table.get("rows"), list):
                    raise BackupError("Structure de sauvegarde d’inventaire invalide.")
                db.execute('DELETE FROM "' + name + '"')
                for row in table["rows"]:
                    if not isinstance(row, list) or len(row) != len(expected_columns):
                        raise BackupError("Ligne d’inventaire sauvegardée invalide.")
                    values = []
                    for value in row:
                        if isinstance(value, dict) and set(value) == {"bytes"}:
                            value = base64.b64decode(value["bytes"], validate=True)
                        if value is not None and type(value) not in {str, int, float, bytes}:
                            raise BackupError("Valeur d’inventaire sauvegardée invalide.")
                        values.append(value)
                    if old_spools:
                        values.append("stock" if values[columns.index("label_state")] == "qr" else "in_service")
                    if name == "metadata" and values[0] == "schema_version":
                        if values[1] != str(inventory["schema"]):
                            raise BackupError("La version de l’inventaire sauvegardé est incohérente.")
                        values[1] = "5"
                    db.execute('INSERT INTO "' + name + '" VALUES(' + ','.join('?' for _ in columns) + ')', values)
            if preserve:
                # Never recycle a number issued after the backup, even on rollback.
                for key in ("next_spool_number", "inventory_revision", "library_revision"):
                    row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
                    number = max(int(row[0]) if row else 0, preserve[key]) + (key != "next_spool_number")
                    db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, str(number)))
                for row in db.execute("SELECT id,version,notes_revision FROM spools").fetchall():
                    previous = preserve["spools"].get(row["id"], (0, 0))
                    db.execute("UPDATE spools SET version=?,notes_revision=? WHERE id=?",
                               (max(row["version"], previous[0]) + 1, max(row["notes_revision"], previous[1]) + 1, row["id"]))
                for row in db.execute("SELECT id,version FROM favorites").fetchall():
                    db.execute("UPDATE favorites SET version=? WHERE id=?", (max(row["version"], preserve["favorites"].get(row["id"], 0)) + 1, row["id"]))
                db.execute("UPDATE inventory_notes SET revision=MAX(revision,?)+1 WHERE id=1", (preserve["notes_revision"],))

    def _validate(self, record):
        if (not isinstance(record, dict) or record.get("format") != "opt-station-backup" or type(record.get("version")) is not int
                or record["version"] != 1 or record.get("mode") != self.settings.mode
                or record.get("scope") not in {"all", "inventory", "configuration"}):
            raise BackupError("Sauvegarde incompatible : vérifiez le format et le mode matériel ou simulation.")
        scope = record["scope"]
        expected = {"format", "version", "application_version", "mode", "created_at", "scope"}
        expected |= {"inventory", "nfc_backups"} if scope != "configuration" else set()
        expected |= {"configuration"} if scope != "inventory" else set()
        if set(record) != expected:
            raise BackupError("Contenu de sauvegarde incomplet ou inattendu.")
        datetime.fromisoformat(record["created_at"])
        summary = {"scope": scope, "created_at": record["created_at"], "application_version": record["application_version"]}
        with tempfile.TemporaryDirectory(prefix=".backup-check-", dir=self.directory) as scratch:
            folder = Path(scratch)
            if "inventory" in record:
                summary.update(self._validate_inventory(record["inventory"], folder))
                if not isinstance(record["nfc_backups"], dict):
                    raise BackupError("Liste de sauvegardes NFC invalide.")
                for name, content in record["nfc_backups"].items():
                    if not NFC_NAME.fullmatch(name) or not isinstance(content, str):
                        raise BackupError("Nom de sauvegarde NFC invalide.")
                    base64.b64decode(content, validate=True)
                summary["nfc_backups"] = len(record["nfc_backups"])
            if "configuration" in record:
                configurations = record["configuration"]
                if not isinstance(configurations, dict) or not set(configurations) <= set(CONFIG_FILES):
                    raise BackupError("Fichiers de configuration non reconnus.")
                for name, value in configurations.items():
                    private_json(folder / name, value)
                from .printer import PrinterConfiguration
                from .mcp_server import MCPConfiguration
                from .labels import LabelPrinter
                from .app import PrinterSettings
                printer = PrinterConfiguration(folder)
                if "printer-settings.json" in configurations:
                    # Reuse the public request contract, then the secret-aware loader.
                    raw = printer.record()
                    PrinterSettings.model_validate({k: raw[k] for k in ("revision", "printer", "connect", "cameras")})
                NetworkAccess(folder, True)
                MCPConfiguration(folder)
                LabelPrinter(folder, self.store)
                if "backup-settings.json" in configurations:
                    validate_schedule(configurations["backup-settings.json"])
                if "updates-settings.json" in configurations:
                    from .updates import UpdateConfiguration
                    UpdateConfiguration(folder)
                summary["configuration_files"] = list(configurations)
        return summary

    def fingerprint(self):
        record = self.collect("all")
        record.pop("created_at")
        return hashlib.sha256(dumps(record).encode()).hexdigest()

    def preview(self, content, password=None):
        record = decrypt(content, password)
        try:
            summary = self._validate(record)
        except BackupError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, OverflowError):
            raise BackupError("Les données de la sauvegarde sont invalides ou incompatibles.") from None
        with self.gate.hold(), self.lock:
            return self._remember_preview(record, summary)

    def _remember_preview(self, record, summary):
        self.previews = OrderedDict((k, v) for k, v in self.previews.items() if v["expires"] > time.monotonic())
        while len(self.previews) >= 2:
            self.previews.popitem(last=False)
        token = secrets.token_urlsafe(24)
        self.previews[token] = {"record": record, "fingerprint": self.fingerprint(), "expires": time.monotonic() + 600}
        return {"preview_id": token, "expires_in_seconds": 600, **summary}

    def restore(self, token):
        with self.gate.hold(), self.lock:
            preview = self.previews.get(token)
            if not preview or preview["expires"] <= time.monotonic():
                raise ConflictError("L’aperçu de restauration a expiré. Sélectionnez à nouveau la sauvegarde.")
            if self.busy():
                raise BackupError("Arrêtez le scan QR et attendez la fin des opérations matérielles avant de restaurer.", 409)
            if self.fingerprint() != preview["fingerprint"]:
                raise ConflictError("Les données ont changé depuis l’aperçu. Reprenez la vérification avant de restaurer.")
            record = preview["record"]
            identifier = uuid.uuid4().hex
            point = self.directory / "restore-points" / identifier
            point.mkdir(parents=True, mode=0o700)
            (self.directory / "restore-points").chmod(0o700)
            private_json(point / "point.json", {"created_at": now(), "scope": record["scope"], "application_version": __version__})
            database_copy(self.store.path, point / "inventory.sqlite3")
            previous = {}
            for name in (*CONFIG_FILES, "backup-key.json", "backup-state.json"):
                previous[name] = (self.directory / name).exists()
                if previous[name]:
                    private_write(point / name, (self.directory / name).read_bytes())
            private_json(point / "files.json", previous)
            nfc = record.get("nfc_backups", {})
            folder = self.directory / "nfc-backups"
            if folder.is_symlink():
                raise BackupError("Le dossier de sauvegardes NFC ne doit pas être un lien symbolique.")
            additions = []
            for name, value in nfc.items():
                path = folder / name
                if path.exists():
                    if path.is_symlink() or path.read_bytes() != base64.b64decode(value):
                        raise BackupError("Une sauvegarde NFC locale porte le même nom avec un contenu différent.")
                else:
                    additions.append(name)
            journal = self.directory / "restore-pending.json"
            private_json(journal, {"point": identifier, "inventory": "inventory" in record, "nfc_added": additions})
            try:
                if "inventory" in record:
                    with self.store.connect() as db:
                        meta = dict(db.execute("SELECT key,value FROM metadata"))
                        preserve = {key: int(meta.get(key, 0)) for key in ("next_spool_number", "inventory_revision", "library_revision")}
                        preserve["spools"] = {r[0]: (r[1], r[2]) for r in db.execute("SELECT id,version,notes_revision FROM spools")}
                        preserve["favorites"] = dict(db.execute("SELECT id,version FROM favorites"))
                    preserve["notes_revision"] = self.store.inventory_notes()["revision"]
                    self._insert_inventory(self.store, record["inventory"], preserve)
                    self.store.recover_pending_operations()
                    self.store.recover_label_jobs()
                if "configuration" in record:
                    for name in CONFIG_FILES:
                        path = self.directory / name
                        if name in record["configuration"]:
                            value = deepcopy(record["configuration"][name])
                            if name == "backup-settings.json":
                                value["enabled"] = False
                                value["station_id"] = self.configuration["station_id"]
                            if isinstance(value, dict) and "revision" in value:
                                current = read_json(path.read_bytes()) if path.exists() else {}
                                value["revision"] = max(value["revision"], current.get("revision", 0)) + 1
                            private_json(path, value)
                        else:
                            path.unlink(missing_ok=True)
                for name in additions:
                    private_write(folder / name, base64.b64decode(nfc[name]))
                self.reload_configuration()
                self.configuration = validate_schedule(read_json(self.path.read_bytes())) if self.path.exists() else default_settings()
                journal.unlink()
            except Exception:
                recover_restore(self.directory, self.store.path)
                self.reload_configuration()
                self.configuration = validate_schedule(read_json(self.path.read_bytes())) if self.path.exists() else default_settings()
                raise BackupError("La restauration a échoué. L’état précédent a été rétabli depuis le point de retour.", 503) from None
            self.previews.clear()
            return {"restored": True, "scope": record["scope"], "rollback_point": identifier, "reload_required": True}

    def _latest_slot(self):
        c = self.configuration
        current = self.utcnow().astimezone(ZoneInfo(c["timezone"]))
        hour, minute = map(int, c["time"].split(":"))
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
        if c["frequency"] == "weekly":
            candidate -= timedelta(days=(candidate.weekday() - c["weekday"]) % 7)
        if candidate.astimezone(timezone.utc) > current.astimezone(timezone.utc):
            candidate -= timedelta(days=7 if c["frequency"] == "weekly" else 1)
        return candidate.date().isoformat(), candidate

    def next_run(self):
        _, latest = self._latest_slot()
        next_date = latest + timedelta(days=7 if self.configuration["frequency"] == "weekly" else 1)
        # Resolve a spring-forward missing time to the corresponding real time.
        return next_date.astimezone(timezone.utc).isoformat()

    def run(self, scheduled=False):
        with self.gate.hold(requests=0 if scheduled else 1), self.lock:
            if self.busy():
                raise BackupError("Une opération matérielle est en cours. La sauvegarde attendra sa fin.", 409)
            slot, _ = self._latest_slot()
            try:
                material = None
                if self.configuration["encrypted"]:
                    key = read_json(self.key_path.read_bytes())
                    material = (base64.b64decode(key["salt"], validate=True), base64.b64decode(key["key"], validate=True))
                content = encode_backup(self.collect("all"), material=material)
                # Recheck mount presence after collection, before writing anything.
                self._destination(self.configuration)
                prefix = "opt-station-" + self.configuration["station_id"][:8] + "-" + self.settings.mode + "-"
                filename = prefix + self.utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4) + ".optbak"
                with self._open_destination() as descriptor:
                    space = os.fstatvfs(descriptor)
                    if space.f_bavail * space.f_frsize < len(content) + 1024 * 1024:
                        raise BackupError("Le support de sauvegarde manque d’espace libre.", 409)
                    self._write_on_volume(descriptor, filename, content, prefix)
                self.state = {**self.state, "status": "success", "attempted_at": self.utcnow().isoformat(),
                              "completed_at": self.utcnow().isoformat(), "filename": filename, "bytes": len(content),
                              "message": "Sauvegarde chiffrée enregistrée et vérifiée." if self.configuration["encrypted"] else "Sauvegarde sans mot de passe enregistrée et vérifiée."}
                if scheduled:
                    self.state["last_slot"] = slot
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.state = {**self.state, "status": "failed", "attempted_at": self.utcnow().isoformat(),
                              "message": str(exc) if isinstance(exc, BackupError) else "Échec de la sauvegarde. Vérifiez le support, les droits et le mot de passe enregistré."}
                private_json(self.state_path, self.state)
                raise BackupError(self.state["message"], 409) from None
            private_json(self.state_path, self.state)
            return self.snapshot()

    def tick(self):
        with self.lock:
            if not self.configuration["enabled"]:
                return
            slot, _ = self._latest_slot()
            if self.state.get("last_slot", "") >= slot:
                return
            attempted = self.state.get("attempted_at")
            if attempted and (self.utcnow() - datetime.fromisoformat(attempted)).total_seconds() < 900:
                return
        try:
            self.run(scheduled=True)
        except (BackupError, OSError):
            pass  # Persisted failure is visible in Configuration; retry after 15 minutes.

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        def loop():
            while not self.stop_event.is_set():
                self.tick()
                self.stop_event.wait(20)
        self.worker = threading.Thread(target=loop, name="opt-backups", daemon=True)
        self.worker.start()

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=10)
