"""Portable, validated library files; imports are previewed and committed atomically."""
from collections import OrderedDict
import json
import secrets
import threading
import time

from . import __version__
from .domain import validate_favorite_main
from .storage import ConflictError, dumps, now

MAX_LIBRARY_BYTES = 1_000_000


def read_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Le fichier contient des clés JSON dupliquées.")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Fichier JSON invalide ou ambigu.") from None


class LibraryTransfer:
    def __init__(self, store, clock=time.monotonic):
        self.store, self.clock = store, clock
        self.lock = threading.RLock()
        self.previews = OrderedDict()

    def export(self, identifiers):
        items = {x["id"]: x for x in self.store.favorites()}
        if not identifiers or len(identifiers) != len(set(identifiers)) or any(x not in items for x in identifiers):
            raise ValueError("Sélectionnez au moins une fiche existante, sans doublon.")
        return {"format": "opt-station-library", "version": 1, "application_version": __version__, "exported_at": now(),
                "items": [{k: items[x][k] for k in ("name", "kind", "main")} for x in identifiers]}

    def preview(self, document):
        if len(document.encode("utf-8")) > MAX_LIBRARY_BYTES:
            raise ValueError("Le fichier de bibliothèque dépasse 1 Mo.")
        record = read_json(document)
        if (not isinstance(record, dict) or record.get("format") != "opt-station-library"
                or type(record.get("version")) is not int or record["version"] != 1
                or not isinstance(record.get("items"), list) or not 1 <= len(record["items"]) <= 1000):
            raise ValueError("Format de bibliothèque OPT Station non reconnu.")
        items, names = [], set()
        with self.store.connect() as db:
            db.execute("BEGIN")
            current = [self.store._favorite(row) for row in db.execute("SELECT * FROM favorites")]
            revision = db.execute("SELECT value FROM metadata WHERE key='library_revision'").fetchone()
            revision = int(revision[0]) if revision else 0
        existing = {x["name"].casefold(): x for x in current}
        for index, item in enumerate(record["items"]):
            if (not isinstance(item, dict) or set(item) != {"name", "kind", "main"}
                    or not isinstance(item["name"], str) or not 1 <= len(item["name"].strip()) <= 120
                    or "\x00" in item["name"] or item["kind"] not in {"model", "favorite"}
                    or not isinstance(item["main"], dict)):
                raise ValueError("Une fiche importée est invalide.")
            name = item["name"].strip()
            if name.casefold() in names:
                raise ValueError("Plusieurs fiches du fichier portent le même nom. Séparez-les avant l’import.")
            names.add(name.casefold())
            main = validate_favorite_main(item["main"])
            previous = existing.get(name.casefold())
            items.append({"index": index, "name": name, "kind": item["kind"], "main": main,
                          "existing": {k: previous[k] for k in ("id", "version", "kind")} if previous else None,
                          "identical": bool(previous and previous["main"] == main and previous["kind"] == item["kind"])})
        with self.lock:
            self._expire()
            while len(self.previews) >= 8:
                self.previews.popitem(last=False)
            token = secrets.token_urlsafe(24)
            self.previews[token] = {"expires": self.clock() + 600, "revision": revision, "items": items}
        return {"preview_id": token, "expires_in_seconds": 600, "items": items}

    def _expire(self):
        self.previews = OrderedDict((key, value) for key, value in self.previews.items() if value["expires"] > self.clock())

    def commit(self, token, choices):
        with self.lock:
            self._expire()
            preview = self.previews.get(token)
            if not preview:
                raise ConflictError("L’aperçu d’import a expiré. Sélectionnez à nouveau le fichier.")
            signature = dumps(choices)
            if "result" in preview:
                if preview["signature"] != signature:
                    raise ConflictError("Cet import a déjà été confirmé avec d’autres choix.")
                return preview["result"]
            if len(choices) != len(preview["items"]) or {x["index"] for x in choices} != set(range(len(choices))):
                raise ValueError("Un choix est nécessaire pour chaque fiche importée.")
            choices = {x["index"]: x for x in choices}
            import uuid
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                revision = db.execute("SELECT value FROM metadata WHERE key='library_revision'").fetchone()
                if (int(revision[0]) if revision else 0) != preview["revision"]:
                    raise ConflictError("La bibliothèque a changé. Reprenez l’aperçu avant d’importer.")
                names = {row[0].casefold() for row in db.execute("SELECT name FROM favorites")}
                created = replaced = skipped = 0
                for item in preview["items"]:
                    choice = choices[item["index"]]
                    action = choice["action"]
                    if action == "skip":
                        skipped += 1
                        continue
                    if action == "replace":
                        previous = item["existing"]
                        if not previous or previous["kind"] != item["kind"]:
                            raise ValueError("Le remplacement nécessite une fiche existante du même type.")
                        cursor = db.execute("UPDATE favorites SET main=?,version=version+1,updated_at=? WHERE id=? AND version=?",
                                            (dumps(item["main"]), now(), previous["id"], previous["version"]))
                        if cursor.rowcount != 1:
                            raise ConflictError("La fiche à remplacer a changé. Reprenez l’aperçu.")
                        replaced += 1
                    elif action in {"create", "rename"}:
                        name = item["name"] if action == "create" else choice.get("name", "").strip()
                        if not 1 <= len(name) <= 120 or "\x00" in name or name.casefold() in names:
                            raise ValueError("Choisissez un nom unique de 1 à 120 caractères pour chaque nouvelle fiche.")
                        db.execute("INSERT INTO favorites(id,name,kind,main,updated_at) VALUES(?,?,?,?,?)",
                                   (str(uuid.uuid4()), name, item["kind"], dumps(item["main"]), now()))
                        names.add(name.casefold())
                        created += 1
                    else:
                        raise ValueError("Choix d’import inconnu.")
                if created or replaced:
                    self.store._bump_library(db)
            result = {"created": created, "replaced": replaced, "skipped": skipped}
            preview.update(result=result, signature=signature)
            return result
