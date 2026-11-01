"""Stockage partagé entre la station et ses clients web, sans écriture NFC implicite."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .domain import spool_snapshot, validate_favorite_main
from .inventory_edits import observe_with_edits, patch_snapshot, validate_local_edits
from .spool_qr import encode_spool, stock_date

MAX_NOTES_LENGTH = 16000

def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # PRAGMA journal_mode can return SQLITE_BUSY immediately despite the
            # connection busy timeout. Avoid rewriting an existing WAL mode and
            # retry that transition while another startup finishes its migration.
            deadline = time.monotonic() + 10
            while True:
                try:
                    if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                        db.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if (getattr(exc, "sqlite_errorcode", 0) & 255) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1');
                CREATE TABLE IF NOT EXISTS spools (
                    id TEXT PRIMARY KEY, instance_uuid TEXT NOT NULL UNIQUE,
                    uid TEXT NOT NULL UNIQUE, in_stock INTEGER NOT NULL DEFAULT 1,
                    snapshot TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    main TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulated_tags (
                    uid TEXT PRIMARY KEY, label TEXT NOT NULL, image BLOB NOT NULL,
                    main_locked INTEGER NOT NULL DEFAULT 0,
                    aux_locked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tag_sources (uid TEXT PRIMARY KEY, source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, uid TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL, before_revision TEXT NOT NULL,
                    after_revision TEXT, detail TEXT
                );
            """)
            # Serialize migration discovery as well as the migration itself.
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
            if version not in {"1", "2", "3", "4", "5", "6"}:
                raise ValueError("Version de base inconnue; sauvegarder avant migration.")
            if version == "1":
                # Old last_seen_at is a reading time, never an arrival date.
                db.execute("ALTER TABLE spools RENAME TO spools_v1")
                db.execute("""CREATE TABLE spools (
                    id TEXT PRIMARY KEY, instance_uuid TEXT NOT NULL UNIQUE,
                    uid TEXT UNIQUE, in_stock INTEGER NOT NULL DEFAULT 1,
                    snapshot TEXT NOT NULL, last_seen_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1, added_at TEXT,
                    label_state TEXT NOT NULL DEFAULT 'rfid' CHECK(label_state IN ('qr','rfid'))
                )""")
                db.execute("""INSERT INTO spools (id,instance_uuid,uid,in_stock,snapshot,last_seen_at,version)
                    SELECT id,instance_uuid,uid,in_stock,snapshot,last_seen_at,version FROM spools_v1""")
                db.execute("DROP TABLE spools_v1")
                db.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
                version = "2"
            if version == "2":
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE spools ADD COLUMN completed_at TEXT")
                db.execute("UPDATE metadata SET value='3' WHERE key='schema_version'")
                version = "3"
            if version == "3":
                db.execute("""ALTER TABLE spools ADD COLUMN sequence_number INTEGER NOT NULL DEFAULT 0
                    CHECK(typeof(sequence_number)='integer' AND sequence_number>=0)""")
                # Known arrival dates come first; unknown dates stay unknown.
                rows = db.execute("SELECT id FROM spools ORDER BY added_at IS NULL,added_at,id").fetchall()
                for number, row in enumerate(rows):
                    db.execute("UPDATE spools SET sequence_number=? WHERE id=?", (number, row["id"]))
                db.execute("CREATE UNIQUE INDEX spool_sequence_unique ON spools(sequence_number)")
                db.execute("""CREATE TRIGGER spool_number_immutable BEFORE UPDATE OF sequence_number ON spools
                    WHEN NEW.sequence_number!=OLD.sequence_number
                    BEGIN SELECT RAISE(ABORT,'Spool numbers cannot be reassigned'); END""")
                db.execute("INSERT INTO metadata(key,value) VALUES('next_spool_number',?)", (str(len(rows)),))
                db.execute("ALTER TABLE spools ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
                db.execute("ALTER TABLE spools ADD COLUMN notes_revision INTEGER NOT NULL DEFAULT 0")
                db.execute("ALTER TABLE spools ADD COLUMN notes_updated_at TEXT")
                db.execute("""CREATE TABLE inventory_notes (
                    id INTEGER PRIMARY KEY CHECK(id=1), text TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT)""")
                db.execute("INSERT INTO inventory_notes(id) VALUES(1)")
                db.execute("UPDATE metadata SET value='4' WHERE key='schema_version'")
                version = "4"
            if version == "4":
                db.execute("""ALTER TABLE spools ADD COLUMN usage_state TEXT NOT NULL DEFAULT 'in_service'
                    CHECK(usage_state IN ('stock','in_service'))""")
                # Preserve the previously displayed state, then let usage and identification vary independently.
                db.execute("UPDATE spools SET usage_state='stock' WHERE label_state='qr'")
                db.execute("UPDATE metadata SET value='5' WHERE key='schema_version'")
            db.execute("""CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY, spool_id TEXT REFERENCES spools(id) ON DELETE CASCADE,
                template_id TEXT REFERENCES favorites(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                image BLOB NOT NULL, thumbnail BLOB NOT NULL,
                CHECK((spool_id IS NOT NULL AND template_id IS NULL) OR
                      (spool_id IS NULL AND template_id IS NOT NULL))
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS photos_spool ON photos(spool_id)")
            db.execute("CREATE INDEX IF NOT EXISTS photos_template ON photos(template_id)")
            db.execute("UPDATE metadata SET value='6' WHERE key='schema_version'")
            db.execute("""CREATE TABLE IF NOT EXISTS label_jobs (
                request_id TEXT PRIMARY KEY, spool_id TEXT NOT NULL, version INTEGER NOT NULL,
                settings_revision INTEGER NOT NULL, payload_hash TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
            )""")
            operation_columns = {row[1] for row in db.execute("PRAGMA table_info(operations)")}
            for name, kind in (("inventory_id", "TEXT"), ("inventory_version", "INTEGER"), ("intended_revision", "TEXT")):
                if name not in operation_columns:
                    db.execute(f"ALTER TABLE operations ADD COLUMN {name} {kind}")
            if "kind" not in {row[1] for row in db.execute("PRAGMA table_info(favorites)")}:
                db.execute("ALTER TABLE favorites ADD COLUMN kind TEXT NOT NULL DEFAULT 'favorite' CHECK(kind IN ('favorite','model'))")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _spool(row):
        if row is None:
            return None
        result = json.loads(row["snapshot"])
        validate_local_edits(result)
        edits = result.pop("local_edits", None)
        if edits:
            if row["label_state"] != "rfid":
                raise ValueError("Les corrections RFID ne s’appliquent pas à une fiche QR.")
            result.update(rfid_sync_pending=True,
                          rfid_pending_fields=[region + "." + name for region in ("main", "aux") for name in edits[region]],
                          last_rfid_data={"main": edits["tag_main"], "aux": edits["tag_aux"]})
        result.pop("inventory", None)
        result.update(id=row["id"], in_stock=bool(row["in_stock"]), version=row["version"], last_seen_at=row["last_seen_at"])
        result.update(added_at=row["added_at"], label_state=row["label_state"], age_days=None)
        result["usage_state"] = row["usage_state"]
        result["completed_at"] = row["completed_at"]
        result["spool_number"] = f"B{row['sequence_number']:04d}"
        result.update(notes=row["notes"], notes_revision=row["notes_revision"], notes_updated_at=row["notes_updated_at"])
        if row["added_at"]:
            result["age_days"] = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(row["added_at"])).days)
        return result

    def find(self, snapshot):
        identity = snapshot.get("instance_uuid")
        with self.connect() as db:
            rows = db.execute("SELECT * FROM spools WHERE uid=? OR instance_uuid=?", (snapshot["uid"], identity)).fetchall()
        if not rows:
            return None
        if len(rows) > 1 or (rows[0]["uid"] is not None and rows[0]["uid"] != snapshot["uid"]) or rows[0]["instance_uuid"] != identity:
            raise ConflictError("Identité ambiguë : ce tag ou cette bobine est déjà associé à une autre fiche. Le remplacement/réemploi doit être traité explicitement.")
        return self._spool(rows[0])

    def observe(self, snapshot):
        existing = self.find(snapshot)
        if existing is None:
            return None
        if existing["label_state"] == "qr" or existing["completed_at"]:
            # Association stays explicit; completed archives retain their snapshot.
            return existing
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM spools WHERE id=?", (existing["id"],)).fetchone()
            if row["completed_at"]:
                return self._spool(row)
            try:
                observed = observe_with_edits(snapshot, json.loads(row["snapshot"]))
            except ValueError:
                raise ConflictError("La lecture RFID entre en conflit avec les corrections locales. Vérifiez la fiche avant de synchroniser le tag.") from None
            cursor = db.execute("UPDATE spools SET snapshot=?, last_seen_at=?, version=version+1 WHERE id=? AND completed_at IS NULL", (dumps(observed), now(), existing["id"]))
            if cursor.rowcount:
                self._bump_inventory(db)
            return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (existing["id"],)).fetchone())

    @staticmethod
    def _bump_inventory(db):
        db.execute("""INSERT INTO metadata(key,value) VALUES('inventory_revision','1')
            ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1""")

    def inventory_revision(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='inventory_revision'").fetchone()
            return int(row[0]) if row else 0

    @staticmethod
    def _allocate_number(db):
        # Called only within the same write transaction as the spool insertion.
        row = db.execute("SELECT value FROM metadata WHERE key='next_spool_number'").fetchone()
        number = max(int(row[0]), db.execute("SELECT COALESCE(MAX(sequence_number)+1,0) FROM spools").fetchone()[0])
        db.execute("UPDATE metadata SET value=? WHERE key='next_spool_number'", (str(number + 1),))
        return number

    def add(self, snapshot):
        existing = self.find(snapshot)
        if existing:
            if existing["completed_at"]:
                raise ConflictError("Cette bobine est terminée et archivée. Sa fiche ne peut pas être remise au stock.")
            if existing["label_state"] == "qr":
                raise ConflictError("Cette bobine possède déjà une fiche QR. Vérifier et associer son tag depuis sa fiche, sans créer un nouveau stock.")
            with self.connect() as db:
                cursor = db.execute("UPDATE spools SET in_stock=1, snapshot=?, last_seen_at=?, version=version+1 WHERE id=? AND completed_at IS NULL", (dumps(snapshot), now(), existing["id"]))
                if cursor.rowcount != 1:
                    raise ConflictError("Cette bobine est terminée et archivée. Sa fiche ne peut pas être remise au stock.")
                self._bump_inventory(db)
                return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (existing["id"],)).fetchone())
        identifier = str(uuid.uuid4())
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                stamp = now()
                number = self._allocate_number(db)
                db.execute("INSERT INTO spools (id,instance_uuid,uid,snapshot,last_seen_at,added_at,sequence_number) VALUES (?,?,?,?,?,?,?)", (identifier, snapshot["instance_uuid"], snapshot["uid"], dumps(snapshot), stamp, stamp, number))
                self._bump_inventory(db)
                return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Cette bobine ou ce tag figure déjà dans l’inventaire. Relire avant de poursuivre.") from exc

    def create_packaged(self, main, aux, added_at=None, provenance=None):
        snapshot = spool_snapshot(main, aux)
        snapshot["provenance"] = provenance or {"kind": "manual"}
        identifier = str(uuid.uuid4())
        stamp = stock_date(added_at) if added_at else now()
        if datetime.fromisoformat(stamp) > datetime.now(timezone.utc):
            raise ValueError("La date d’entrée ne peut pas être dans le futur.")
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                number = self._allocate_number(db)
                db.execute("""INSERT INTO spools (id,instance_uuid,uid,snapshot,last_seen_at,added_at,label_state,sequence_number,usage_state)
                    VALUES (?,?,NULL,?,NULL,?,'qr',?,'stock')""", (identifier, snapshot["instance_uuid"], dumps(snapshot), stamp, number))
                self._bump_inventory(db)
                return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())
        except sqlite3.IntegrityError:
            raise ConflictError("Cette identité de bobine est déjà dans l’inventaire. Retrouvez sa fiche existante.") from None

    def by_instance(self, identity):
        with self.connect() as db:
            return self._spool(db.execute("SELECT * FROM spools WHERE instance_uuid=?", (identity,)).fetchone())

    def pending(self, identifier, version, recreate=False):
        item = self.get_spool(identifier)
        if item["version"] != version or item["label_state"] != ("rfid" if recreate else "qr") or not item["in_stock"] or item["completed_at"]:
            raise ConflictError("La fiche a changé, est hors stock ou son état RFID a changé. Recharger la bobine avant de poursuivre.")
        return item

    def check_tag_destination(self, item, snapshot):
        if item["instance_uuid"] != snapshot["instance_uuid"] or not snapshot.get("uid"):
            raise ConflictError("Le tag ne correspond pas à l’identité de cette bobine.")
        with self.connect() as db:
            other = db.execute("SELECT id FROM spools WHERE uid=? AND id!=?", (snapshot["uid"], item["id"])).fetchone()
        if other:
            raise ConflictError("Ce tag est déjà associé à une autre bobine.")

    def pending_replacement(self, snapshot, image_hash):
        """Only a journaled, exact write awaiting association can bypass find()."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM spools WHERE instance_uuid=?", (snapshot.get("instance_uuid"),)).fetchone()
            if row is None or row["label_state"] != "rfid" or not row["in_stock"] or row["completed_at"]:
                return None
            operation = db.execute("""SELECT 1 FROM operations WHERE inventory_id=? AND inventory_version=?
                AND uid=? AND intended_revision=? AND status IN ('uncertain','tag_verified') LIMIT 1""",
                (row["id"], row["version"], snapshot.get("uid"), image_hash)).fetchone()
            if operation is None or db.execute("SELECT 1 FROM spools WHERE uid=? AND id!=?", (snapshot.get("uid"), row["id"])).fetchone():
                return None
            return self._spool(row)

    def associate(self, identifier, version, snapshot, recreate=False, image_hash=None):
        item = self.pending(identifier, version, recreate=recreate)
        self.check_tag_destination(item, snapshot)
        stored = {key: value for key, value in snapshot.items() if key not in {"inventory", "association_pending"}}
        try:
            with self.connect() as db:
                cursor = db.execute("""UPDATE spools SET uid=?,snapshot=?,last_seen_at=?,label_state='rfid',
                    usage_state=CASE WHEN label_state='qr' THEN 'in_service' ELSE usage_state END,version=version+1
                    WHERE id=? AND version=? AND label_state=? AND in_stock=1 AND completed_at IS NULL""",
                    (snapshot["uid"], dumps(stored), now(), identifier, version, "rfid" if recreate else "qr"))
                if cursor.rowcount != 1:
                    raise ConflictError("La fiche a changé pendant l’association. Relire le tag et recharger l’inventaire.")
                if image_hash:
                    db.execute("""UPDATE operations SET status='complete',after_revision=? WHERE inventory_id=?
                        AND inventory_version=? AND uid=? AND intended_revision=? AND status IN ('uncertain','tag_verified')""",
                        (snapshot.get("revision"), identifier, version, snapshot["uid"], image_hash))
                self._bump_inventory(db)
                return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())
        except sqlite3.IntegrityError:
            raise ConflictError("Ce tag est déjà associé à une autre bobine.") from None

    def list_spools(self, search="", include_removed=False, sort="recent"):
        order = {"recent": "last_seen_at DESC, id", "oldest": "added_at IS NULL, added_at ASC, id", "newest": "added_at IS NULL, added_at DESC, id"}
        if sort not in order:
            raise ValueError("Tri d’inventaire inconnu.")
        with self.connect() as db:
            rows = db.execute("SELECT * FROM spools ORDER BY " + order[sort]).fetchall()
        items = [self._spool(r) for r in rows if include_removed or r["in_stock"]]
        query = search.casefold().strip()
        number = re.fullmatch(r"b([0-9]{1,18})", query)
        if number:
            target = f"B{int(number[1]):04d}"
            return [x for x in items if x["spool_number"] == target]
        return [x for x in items if not query or query in dumps(x).casefold()]

    def get_spool(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone()
            if row is None and isinstance(identifier, str) and identifier.strip().upper().startswith("B"):
                digits = identifier.strip().upper()[1:]
                if digits.isascii() and digits.isdigit() and len(digits) <= 18:
                    row = db.execute("SELECT * FROM spools WHERE sequence_number=?", (int(digits),)).fetchone()
            item = self._spool(row)
        if item is None:
            raise KeyError("Bobine introuvable.")
        return item

    @staticmethod
    def _validate_notes(text):
        if not isinstance(text, str) or len(text) > MAX_NOTES_LENGTH or "\x00" in text:
            raise ValueError("Les notes doivent être un texte de 16 000 caractères maximum, sans caractère nul.")

    def patch_spool(self, identifier, version, main=None, aux=None, notes=None, notes_revision=None,
                    usage_state=None, reset_tag_overrides=False):
        """Atomic inventory-only correction; NFC identity and observations remain separate."""
        identifier = self.get_spool(identifier)["id"]
        if notes is not None:
            self._validate_notes(notes)
            if type(notes_revision) is not int or notes_revision < 0:
                raise ValueError("Indiquez la révision actuelle des notes pour les modifier.")
        elif notes_revision is not None:
            raise ValueError("La révision des notes accompagne un texte de notes.")
        if usage_state is not None and usage_state not in {"stock", "in_service"}:
            raise ValueError("État d’utilisation inconnu.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Bobine introuvable.")
            if row["version"] != version:
                raise ConflictError("La fiche de bobine a changé. Relisez sa version avant de la modifier.")
            if notes is not None and row["notes_revision"] != notes_revision:
                raise ConflictError("Les notes ont changé. Relisez leur révision avant de les modifier.")
            if (main or aux or usage_state is not None or reset_tag_overrides) and (not row["in_stock"] or row["completed_at"]):
                raise ConflictError("Seules les notes d’une bobine retirée ou terminée restent modifiables.")
            if db.execute("SELECT 1 FROM operations WHERE inventory_id=? AND status IN ('pending','uncertain','tag_verified') LIMIT 1", (identifier,)).fetchone():
                raise ConflictError("Cette bobine attend la confirmation d’une écriture RFID. Terminez sa réconciliation avant de modifier la fiche.")
            before = json.loads(row["snapshot"])
            after = patch_snapshot(before, main, aux, rfid=row["label_state"] == "rfid", reset_tag_overrides=reset_tag_overrides)
            if row["label_state"] == "qr" and after != before:
                encode_spool({**after, "added_at": row["added_at"]})
            next_usage = row["usage_state"] if usage_state is None else usage_state
            next_notes = row["notes"] if notes is None else notes
            notes_changed = next_notes != row["notes"]
            if after == before and next_usage == row["usage_state"] and not notes_changed:
                return {"updated": False, "item": self._spool(row), "rfid_written": False}
            db.execute("""UPDATE spools SET snapshot=?,usage_state=?,notes=?,
                notes_revision=notes_revision+?,notes_updated_at=?,version=version+1 WHERE id=?""",
                (dumps(after), next_usage, next_notes, int(notes_changed), now() if notes_changed else row["notes_updated_at"], identifier))
            self._bump_inventory(db)
            return {"updated": True, "item": self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone()),
                    "rfid_written": False}

    def inventory_notes(self):
        with self.connect() as db:
            row = db.execute("SELECT text,revision,updated_at FROM inventory_notes WHERE id=1").fetchone()
            return dict(row)

    def set_remaining_weight(self, identifier, version, remaining_weight, actual_initial_weight=None):
        """Convert an explicit net remainder into consumption using a known initial mass."""
        if type(remaining_weight) not in {int, float} or not math.isfinite(remaining_weight) or remaining_weight < 0:
            raise ValueError("Indiquez une quantité restante positive ou nulle, en grammes.")
        if actual_initial_weight is not None and (type(actual_initial_weight) not in {int, float}
                or not math.isfinite(actual_initial_weight) or actual_initial_weight <= 0):
            raise ValueError("Le poids net initial réel doit être strictement positif, en grammes.")
        item = self.get_spool(identifier)
        if item["version"] != version:
            raise ConflictError("Cette fiche a changé. Rechargez la quantité avant de la modifier.")
        if not item["in_stock"] or item["completed_at"]:
            raise ConflictError("La quantité se modifie uniquement sur une bobine en stock ou en service.")
        initial = (actual_initial_weight if actual_initial_weight is not None else
                   item["main"].get("actual_netto_full_weight", item["main"].get("nominal_netto_full_weight")))
        if initial is None:
            raise ValueError("Le poids initial est inconnu. Renseignez le poids net initial réel pour calculer la consommation.")
        if remaining_weight > initial:
            raise ValueError("La quantité restante dépasse le poids net initial de référence. Corrigez le poids initial si vous le connaissez.")
        consumed = float(Decimal(str(initial)) - Decimal(str(remaining_weight)))
        main = {"actual_netto_full_weight": actual_initial_weight} if actual_initial_weight is not None else None
        # patch_spool rechecks the version and active status inside its transaction.
        # Its RFID correction handling preserves the last physical observation.
        return self.patch_spool(item["id"], version, main=main, aux={"consumed_weight": consumed})

    def save_inventory_notes(self, text, revision):
        self._validate_notes(text)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT text,revision,updated_at FROM inventory_notes WHERE id=1").fetchone()
            if row["revision"] != revision:
                raise ConflictError("Le carnet commun a été modifié ailleurs. Votre saisie est conservée; rechargez les notes avant de les remplacer.")
            if row["text"] != text:
                db.execute("UPDATE inventory_notes SET text=?,revision=revision+1,updated_at=? WHERE id=1", (text, now()))
            return dict(db.execute("SELECT text,revision,updated_at FROM inventory_notes WHERE id=1").fetchone())

    def save_spool_notes(self, identifier, text, revision):
        self._validate_notes(text)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Bobine introuvable.")
            if row["notes_revision"] != revision:
                raise ConflictError("Les notes de cette bobine ont été modifiées ailleurs. Votre saisie est conservée; rechargez les notes avant de les remplacer.")
            if row["notes"] != text:
                db.execute("UPDATE spools SET notes=?,notes_revision=notes_revision+1,notes_updated_at=? WHERE id=?", (text, now(), identifier))
                self._bump_inventory(db)
            return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())

    def remove(self, identifier, version):
        with self.connect() as db:
            cursor = db.execute("UPDATE spools SET in_stock=0,version=version+1 WHERE id=? AND version=? AND completed_at IS NULL", (identifier, version))
            if cursor.rowcount != 1:
                raise ConflictError("Cette fiche a changé ou a été retirée. Actualiser l’inventaire.")
            self._bump_inventory(db)
            return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())

    def set_usage(self, identifier, version, usage_state):
        """Change only the station's usage state; physical tags and observations stay untouched."""
        if usage_state not in {"stock", "in_service"}:
            raise ValueError("État d’utilisation inconnu.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Bobine introuvable.")
            if row["version"] != version or not row["in_stock"] or row["completed_at"]:
                raise ConflictError("Cette fiche a changé ou la bobine n’est plus active. Rechargez sa fiche avant de changer son utilisation.")
            if row["usage_state"] != usage_state:
                db.execute("UPDATE spools SET usage_state=?,version=version+1 WHERE id=?", (usage_state, identifier))
                self._bump_inventory(db)
            return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())

    def restore(self, identifier, version):
        with self.connect() as db:
            cursor = db.execute("UPDATE spools SET in_stock=1,version=version+1 WHERE id=? AND version=? AND in_stock=0 AND completed_at IS NULL", (identifier, version))
            if cursor.rowcount != 1:
                raise ConflictError("Cette fiche a changé ou est déjà au stock. Recharger l’inventaire.")
            self._bump_inventory(db)
            return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())

    def complete(self, identifier, version):
        """Archive once, keeping the last observed data and never writing NFC."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Bobine introuvable.")
            if row["completed_at"]:
                return self._spool(row)
            if row["version"] != version:
                raise ConflictError("Cette fiche a changé. Actualiser avant de marquer la bobine comme terminée.")
            db.execute("UPDATE spools SET in_stock=0,completed_at=?,version=version+1 WHERE id=?", (now(), identifier))
            self._bump_inventory(db)
            return self._spool(db.execute("SELECT * FROM spools WHERE id=?", (identifier,)).fetchone())

    def completed_count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM spools WHERE completed_at IS NOT NULL").fetchone()[0]

    @staticmethod
    def _favorite(row):
        return {"id": row["id"], "name": row["name"], "main": json.loads(row["main"]), "version": row["version"], "updated_at": row["updated_at"], "kind": row["kind"]}

    def favorites(self):
        with self.connect() as db:
            return [self._favorite(x) for x in db.execute("SELECT * FROM favorites ORDER BY name COLLATE NOCASE")]

    @staticmethod
    def _template_row(db, identifier, kind=None):
        row = db.execute("SELECT * FROM favorites WHERE id=?", (identifier,)).fetchone()
        if row is None or (kind is not None and row["kind"] != kind):
            raise KeyError(identifier)
        return row

    @staticmethod
    def _bump_library(db):
        db.execute("""INSERT INTO metadata(key,value) VALUES('library_revision','1')
            ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1""")

    def patch_template(self, identifier, version, kind, name=None, main=None):
        """Merge only explicit fields under the same lock as the version check."""
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._template_row(db, identifier, kind)
                if row["version"] != version:
                    raise ConflictError("Cette fiche a changé. Rechargez la bibliothèque avant de la modifier.")
                name = row["name"] if name is None else name.strip()
                if not name or len(name) > 120:
                    raise ValueError("Le nom du favori doit comporter de 1 à 120 caractères.")
                fields = validate_favorite_main({**json.loads(row["main"]), **(main or {})})
                if name == row["name"] and fields == json.loads(row["main"]):
                    return {"updated": False, "item": self._favorite(row)}
                db.execute("UPDATE favorites SET name=?,main=?,version=version+1,updated_at=? WHERE id=?",
                           (name, dumps(fields), now(), identifier))
                self._bump_library(db)
                return {"updated": True, "item": self._favorite(self._template_row(db, identifier, kind))}
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Un favori porte déjà ce nom.") from exc

    def delete_favorite(self, identifier, version, kind=None):
        """Delete a library definition only; spool snapshots are independent."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._template_row(db, identifier, kind)
            if row["version"] != version:
                raise ConflictError("Cette fiche a changé. Rechargez la bibliothèque avant de la supprimer.")
            db.execute("DELETE FROM favorites WHERE id=?", (identifier,))
            self._bump_library(db)
            return {"deleted": True, "id": identifier, "kind": row["kind"]}

    def save_favorite(self, name, main, identifier=None, version=None, kind=None):
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("Le nom du favori doit comporter de 1 à 120 caractères.")
        if kind is not None and kind not in {"favorite", "model"}:
            raise ValueError("Type de fiche invalide.")
        try:
            with self.connect() as db:
                if identifier:
                    cursor = db.execute("UPDATE favorites SET name=?,main=?,kind=COALESCE(?,kind),version=version+1,updated_at=? WHERE id=? AND version=?", (name, dumps(main), kind, now(), identifier, version))
                    if cursor.rowcount != 1:
                        raise ConflictError("Ce favori a changé. Recharger avant de l’enregistrer.")
                else:
                    identifier = str(uuid.uuid4())
                    db.execute("INSERT INTO favorites (id,name,main,updated_at,kind) VALUES (?,?,?,?,?)", (identifier, name, dumps(main), now(), kind or "favorite"))
                self._bump_library(db)
                return self._favorite(db.execute("SELECT * FROM favorites WHERE id=?", (identifier,)).fetchone())
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Un favori porte déjà ce nom.") from exc

    def library_revision(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='library_revision'").fetchone()
            return int(row[0]) if row else 0

    def create_template_once(self, name, main, kind):
        """AI retries return the same record, and never overwrite a different one."""
        try:
            return {"created": True, "item": self.save_favorite(name, main, kind=kind)}
        except ConflictError:
            with self.connect() as db:
                row = db.execute("SELECT * FROM favorites WHERE name=? COLLATE NOCASE", (name.strip(),)).fetchone()
            if row is not None and row["kind"] == kind and json.loads(row["main"]) == main:
                return {"created": False, "item": self._favorite(row)}
            raise

    def begin_operation(self, uid, revision, inventory_id=None, inventory_version=None, intended_revision=None):
        identifier = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("""INSERT INTO operations (id,uid,created_at,status,before_revision,inventory_id,inventory_version,intended_revision)
                VALUES (?,?,?,?,?,?,?,?)""", (identifier, uid, now(), "pending", revision, inventory_id, inventory_version, intended_revision))
        return identifier

    def matching_association(self, identifier, uid, image_revision):
        with self.connect() as db:
            return db.execute("""SELECT 1 FROM operations WHERE inventory_id=?
                AND uid=? AND intended_revision=? AND status IN ('pending','uncertain','tag_verified','complete') LIMIT 1""",
                (identifier, uid, image_revision)).fetchone() is not None

    def recover_pending_operations(self):
        with self.connect() as db:
            db.execute("UPDATE operations SET status='uncertain', detail=? WHERE status='pending'",
                       ("La station a redémarré avant confirmation. Relire le tag avant toute nouvelle écriture.",))

    def end_operation(self, identifier, status, revision=None, detail=None):
        with self.connect() as db:
            db.execute("UPDATE operations SET status=?,after_revision=?,detail=? WHERE id=?", (status, revision, detail, identifier))

    def operations(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM operations ORDER BY created_at DESC LIMIT 30")]

    def source(self, uid):
        with self.connect() as db:
            row = db.execute("SELECT source FROM tag_sources WHERE uid=?", (uid,)).fetchone()
        return json.loads(row[0]) if row else {"kind": "tag", "message": "Valeurs observées sur le tag"}

    def save_source(self, uid, source):
        with self.connect() as db:
            db.execute("INSERT INTO tag_sources VALUES (?,?) ON CONFLICT(uid) DO UPDATE SET source=excluded.source", (uid, dumps(source)))

    def label_job(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM label_jobs WHERE request_id=?", (identifier,)).fetchone()
            return dict(row) if row else None

    def begin_label_job(self, identifier, spool, settings_revision, payload_hash):
        with self.connect() as db:
            db.execute("INSERT INTO label_jobs VALUES (?,?,?,?,?,'pending',?,'')",
                       (identifier, spool["id"], spool["version"], settings_revision, payload_hash, now()))

    def end_label_job(self, identifier, status, detail):
        with self.connect() as db:
            db.execute("UPDATE label_jobs SET status=?,detail=? WHERE request_id=?", (status, detail, identifier))
        return self.label_job(identifier)

    def recover_label_jobs(self):
        with self.connect() as db:
            db.execute("UPDATE label_jobs SET status='uncertain',detail='Station redémarrée pendant une impression. Vérifier l’étiquette avant de réimprimer.' WHERE status='pending'")

    @staticmethod
    def _photo_owner(db, kind, identifier):
        if kind not in {"spool", "template"}:
            raise ValueError("Type de fiche invalide.")
        table, column = ("spools", "spool_id") if kind == "spool" else ("favorites", "template_id")
        if not db.execute("SELECT 1 FROM " + table + " WHERE id=?", (identifier,)).fetchone():
            raise KeyError(identifier)
        return column

    def photos(self, kind, identifier):
        with self.connect() as db:
            column = self._photo_owner(db, kind, identifier)
            return [dict(row) for row in db.execute("SELECT id,created_at,width,height FROM photos WHERE " + column + "=? ORDER BY created_at,id", (identifier,))]

    def photo(self, kind, identifier, photo_id, thumbnail=False):
        with self.connect() as db:
            column = self._photo_owner(db, kind, identifier)
            row = db.execute("SELECT image,thumbnail FROM photos WHERE " + column + "=? AND id=?", (identifier, photo_id)).fetchone()
            if row is None:
                raise KeyError(photo_id)
            return row["thumbnail" if thumbnail else "image"]

    def add_photo(self, kind, identifier, content):
        from .photos import normalize_photo, MAX_PHOTOS
        image, thumbnail, width, height = normalize_photo(content)
        photo_id, stamp = str(uuid.uuid4()), now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            column = self._photo_owner(db, kind, identifier)
            count = db.execute("SELECT COUNT(*) FROM photos WHERE " + column + "=?", (identifier,)).fetchone()[0]
            if count >= MAX_PHOTOS:
                raise ValueError("Une fiche peut contenir au maximum 8 photos.")
            db.execute("INSERT INTO photos (id," + column + ",created_at,width,height,image,thumbnail) VALUES (?,?,?,?,?,?,?)",
                       (photo_id, identifier, stamp, width, height, image, thumbnail))
            (self._bump_inventory if kind == "spool" else self._bump_library)(db)
        return {"id": photo_id, "created_at": stamp, "width": width, "height": height}

    def delete_photo(self, kind, identifier, photo_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            column = self._photo_owner(db, kind, identifier)
            deleted = db.execute("DELETE FROM photos WHERE " + column + "=? AND id=?", (identifier, photo_id))
            if not deleted.rowcount:
                raise KeyError(photo_id)
            (self._bump_inventory if kind == "spool" else self._bump_library)(db)
        return {"deleted": True}
