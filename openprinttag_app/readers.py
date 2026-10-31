"""Contrat de lecteur et simulateur persistant, indépendant du pilote PC/SC."""
from hashlib import sha256
import secrets
import threading
from typing import Protocol

from .domain import TagImage


class ReaderUnavailable(ValueError):
    pass


class WriteRejected(ReaderUnavailable):
    """An operation refused before sending any write command to the tag."""

    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


class Reader(Protocol):
    lock: threading.RLock

    def status(self) -> dict: ...
    def read(self) -> dict: ...
    def write(self, image: bytes) -> None: ...


def revision(record):
    content = bytes(record["image"]) + bytes([record["main_locked"], record["aux_locked"]])
    return sha256(content + record.get("protection_signature", "").encode("ascii")).hexdigest()


class SimulatedReader:
    name = "Lecteur NFC simulé — aucun matériel utilisé"

    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        with store.connect() as db:
            if not db.execute("SELECT 1 FROM state WHERE key='simulator_initialized'").fetchone():
                samples = [
                    ("E004010000000001", "PLA bleu · démonstration fictive", "PLA", "#397dd8", 125, False),
                    ("E004010000000002", "PETG orange · Main protégé · démonstration fictive", "PETG", "#e97536", 40, True),
                ]
                for uid, label, kind, color, consumed, locked in samples:
                    image = TagImage.create(uid, {"material_class": "FFF", "material_type": kind, "brand_name": "Demonstration", "material_name": f"{kind} fictif", "nominal_netto_full_weight": 1000, "filament_diameter": 1.75, "primary_color": color}, {"consumed_weight": consumed}).to_bytes()
                    db.execute("INSERT INTO simulated_tags VALUES (?,?,?,?,?)", (uid, label, image, int(locked), 0))
                db.execute("INSERT INTO state VALUES ('active_uid',?)", (samples[0][0],))
                db.execute("INSERT INTO state VALUES ('simulator_initialized','1')")

    def status(self):
        return {"name": self.name, "connected": True, "present": True, "simulated": True}

    def read(self):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM simulated_tags WHERE uid=(SELECT value FROM state WHERE key='active_uid')").fetchone()
        if row is None:
            raise ReaderUnavailable("Aucun tag simulé sélectionné.")
        return dict(row)

    def write(self, image):
        current = self.read()
        with self.store.connect() as db:
            db.execute("UPDATE simulated_tags SET image=? WHERE uid=?", (image, current["uid"]))

    def list_tags(self):
        with self.store.connect() as db:
            return [{"uid": r["uid"], "label": r["label"], "blank": not any(r["image"])} for r in db.execute("SELECT * FROM simulated_tags ORDER BY rowid")]

    def select(self, uid):
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM simulated_tags WHERE uid=?", (uid,)).fetchone():
                raise ValueError("Tag simulé inconnu.")
            db.execute("UPDATE state SET value=? WHERE key='active_uid'", (uid,))

    def blank(self):
        uid = "E00401" + secrets.token_hex(5).upper()
        with self.store.connect() as db:
            db.execute("INSERT INTO simulated_tags VALUES (?,?,?,?,?)", (uid, "Tag vierge · simulation", bytes(320), 0, 0))
            db.execute("UPDATE state SET value=? WHERE key='active_uid'", (uid,))

    def protect(self, main, aux):
        current = self.read()
        with self.store.connect() as db:
            db.execute("UPDATE simulated_tags SET main_locked=?,aux_locked=? WHERE uid=?", (int(main), int(aux), current["uid"]))
