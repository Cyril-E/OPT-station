"""Explicit single-spool warehouse creation, with persistent retry reconciliation."""
from copy import deepcopy
import hashlib
import json
import uuid

from .prusa_connect import ConnectError, WAREHOUSE_QUERY, identity, positive, utc


EXPORT_NAMESPACE = uuid.UUID("38ed496e-956b-4c3a-9bcf-3d9e95137de1")
PROPERTIES = {
    "density": "density", "hardness_shore_a": "hardnessShoreA", "hardness_shore_d": "hardnessShoreD",
    "min_print_temperature": "minPrintTemperature", "max_print_temperature": "maxPrintTemperature",
    "min_bed_temperature": "minBedTemperature", "max_bed_temperature": "maxBedTemperature",
    "preheat_temperature": "preheatTemperature", "chamber_temperature": "chamberTemperature",
    "min_chamber_temperature": "minChamberTemperature", "max_chamber_temperature": "maxChamberTemperature",
    "drying_temperature": "dryingTemperature", "drying_time": "dryingTime", "min_nozzle_diameter": "minNozzleDiameter",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def export_data(item, organization):
    main, aux = item["main"], item["aux"]
    if not item["in_stock"] or item["completed_at"] or main.get("material_class") != "FFF":
        raise ConnectError("export_data", "Seules les bobines de filament actives peuvent être envoyées vers Connect.", 422)
    if not identity(item.get("instance_uuid")):
        raise ConnectError("export_data", "L’identité de cette bobine est manquante.", 422)
    brand = main.get("brand_name", "").strip()
    kind = main.get("material_type", "").strip()
    name = (main.get("material_name") or kind).strip()
    if not brand or not kind or not name:
        raise ConnectError("export_data", "Renseignez la marque et la matière avant l’envoi vers Connect.", 422)
    nominal = main.get("nominal_netto_full_weight")
    initial = main.get("actual_netto_full_weight", nominal)
    consumed = aux.get("consumed_weight")
    if not positive(nominal):
        raise ConnectError("export_data", "Renseignez le poids net initial nominal, en grammes, puis enregistrez les valeurs.", 422)
    if not positive(initial) or not positive(consumed, zero=True) or consumed > initial:
        raise ConnectError("export_data", "Renseignez une consommation connue, comprise entre zéro et le poids net initial, puis enregistrez les valeurs.", 422)
    title = item["spool_number"] + " · " + brand + " " + name
    brand_id = identity(main.get("brand_uuid")) or str(uuid.uuid5(EXPORT_NAMESPACE, "brand:" + brand.casefold()))
    material = {"name": name, "type": kind, "class": "FFF", "brand": {"uuid": brand_id, "name": brand}}
    if main.get("primary_color"):
        material["primaryColor"] = {"colorRgba": main["primary_color"] + "FF"}
    if main.get("material_abbreviation"):
        material["abbreviation"] = main["material_abbreviation"]
    for key in ("tags", "certifications"):
        if main.get(key):
            material[key] = deepcopy(main[key])
    properties = {remote: main[local] for local, remote in PROPERTIES.items() if main.get(local) is not None}
    if properties:
        material["properties"] = properties
    material["uuid"] = identity(main.get("material_uuid")) or str(uuid.uuid5(EXPORT_NAMESPACE, "material:" + digest(material)))
    package = {"material": material, "nominalNettoFullWeight": nominal}
    if main.get("filament_diameter") is not None:
        package["filamentDiameter"] = round(main["filament_diameter"] * 1000)  # Connect: micrometres; OPT: mm.
    if main.get("nominal_full_length") is not None:
        package["nominalFullLength"] = main["nominal_full_length"]  # Both use millimetres.
    if identity(main.get("package_uuid")):
        package["uuid"] = identity(main["package_uuid"])
    if main.get("empty_container_weight") is not None:
        package["container"] = {"emptyWeight": main["empty_container_weight"]}
    instance = {"uuid": item["instance_uuid"], "dynamicData": {"consumedWeight": consumed}, "package": package}
    if main.get("actual_netto_full_weight") is not None:
        instance["actualNettoFullWeight"] = main["actual_netto_full_weight"]
    payload = {"organizationId": organization, "quantity": 1, "materialPackageInstance": instance}
    if item.get("notes"):
        payload["note"] = item["notes"]
    if aux.get("storage_location"):
        payload["location"] = aux["storage_location"]
    return title, payload


def matching_item(items, instance):
    matches = [x for x in items if identity((x.get("materialPackageInstance") or {}).get("uuid")) == instance]
    if len(matches) > 1:
        raise ConnectError("export_duplicate", "Plusieurs fiches Connect portent cette identité. Aucune nouvelle bobine n’est créée.", 409)
    if matches and not identity(matches[0].get("id")):
        raise ConnectError("contract", "La fiche d’entrepôt Connect est invalide.")
    return matches[0] if matches else None


def differences(remote, title, payload):
    expected = payload["materialPackageInstance"]
    instance = remote.get("materialPackageInstance") or {}
    package = instance.get("package") or {}
    material = package.get("material") or {}
    fields = []
    if remote.get("name") != title:
        fields.append("name")
    if identity(instance.get("uuid")) != expected["uuid"]:
        fields.append("instance_uuid")
    def number(label, actual, wanted):
        if wanted is None:
            return
        if not positive(actual, zero=True) or (abs(actual - wanted) > .001 and not (float(actual).is_integer() and abs(actual - wanted) < 1)):
            fields.append(label)
    number("consumed_weight", remote.get("consumedWeight"), expected["dynamicData"]["consumedWeight"])
    number("nominal_netto_full_weight", remote.get("nominalNettoFullWeight"), expected["package"]["nominalNettoFullWeight"])
    number("actual_netto_full_weight", instance.get("actualNettoFullWeight"), expected.get("actualNettoFullWeight"))
    number("filament_diameter", package.get("filamentDiameter"), expected["package"].get("filamentDiameter"))
    number("nominal_full_length", package.get("nominalFullLength"), expected["package"].get("nominalFullLength"))
    number("empty_container_weight", (package.get("container") or {}).get("emptyWeight"), (expected["package"].get("container") or {}).get("emptyWeight"))
    for label, actual, wanted in (("material_type", material.get("type"), expected["package"]["material"]["type"]),
                                   ("brand_name", (material.get("brand") or {}).get("name"), expected["package"]["material"]["brand"]["name"])):
        if not isinstance(actual, str) or actual.casefold() != wanted.casefold():
            fields.append(label)
    color = expected["package"]["material"].get("primaryColor")
    if color and str((material.get("primaryColor") or {}).get("colorRgba") or "").casefold() != color["colorRgba"].casefold():
        fields.append("primary_color")
    for field in ("note", "location"):
        if (remote.get(field) or "") != (payload.get(field) or ""):
            fields.append(field)
    return fields


class WarehouseExporter:
    def __init__(self, monitor):
        self.monitor = monitor
        self.configuration, self.client, self.store = monitor.configuration, monitor.client, monitor.store

    @staticmethod
    def _key(organization, instance):
        return "connect-warehouse-export:" + organization + ":" + instance

    def _journal(self, key):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, key, value, *, claim=False):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if claim:
                row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
                if row:
                    previous = json.loads(row[0])
                    ready = (previous["phase"] == "material_ready" and not previous.get("creation_attempted")
                             and previous.get("payload_hash") == value.get("payload_hash"))
                    if previous["phase"] != "rejected" and not ready:
                        raise ConnectError("export_uncertain", "Un envoi de cette bobine est déjà enregistré. Relisez l’entrepôt avant de réessayer.", 409)
            db.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def _prepare(self, identifier, version, notes_revision):
        if not self.monitor.allowed():
            raise ConnectError("export_busy", "La station est momentanément indisponible pour cet envoi.", 409)
        config = self.configuration.read()
        if not config["enabled"]:
            raise ConnectError("export_disabled", "Activez Prusa Connect dans les paramètres avant cet envoi.", 409)
        item = self.store.get_spool(identifier)
        if item["version"] != version or item["notes_revision"] != notes_revision:
            raise ConnectError("export_changed", "Cette fiche a changé. Rechargez-la avant l’envoi vers Connect.", 409)
        with self.store.connect() as db:
            pending = db.execute("SELECT inventory_id,detail FROM operations WHERE status IN ('pending','uncertain','tag_verified')").fetchall()
            if any(row["inventory_id"] == item["id"] or (self.store.operation_reuse(row["detail"]) or {}).get("inventory_id") == item["id"] for row in pending):
                raise ConnectError("export_busy", "Terminez l’opération RFID de cette bobine avant son envoi vers Connect.", 409)
        teams = self.client.teams()
        organization = config["organization_id"] or (teams[0]["id"] if len(teams) == 1 else "")
        team = next((t for t in teams if t["id"] == organization), None)
        if team is None:
            raise ConnectError("export_organization", "Choisissez l’organisation Connect dans les paramètres.", 409)
        title, payload = export_data(item, organization)
        warehouse = self.client.collection(WAREHOUSE_QUERY, organization, warehouse=True)
        existing = matching_item(warehouse, item["instance_uuid"])
        key = self._key(organization, item["instance_uuid"])
        journal = self._journal(key)
        material_only = journal and journal["phase"] in {"material_registering", "material_ready"} and not journal.get("creation_attempted")
        if existing is None and journal and journal["phase"] != "rejected" and not material_only:
            raise ConnectError("export_uncertain", "Un envoi précédent n’est pas réconcilié avec l’entrepôt. Aucune seconde création n’est lancée.", 409)
        if existing is None and any(str(x.get("name") or "").split(" · ")[0] == item["spool_number"] for x in warehouse):
            raise ConnectError("export_duplicate", "Ce numéro existe dans Connect avec une autre identité. Vérifiez cette fiche avant l’envoi.", 409)
        fingerprint = digest({"config_revision": config["revision"], "id": item["id"], "version": version,
                              "notes_revision": notes_revision, "title": title, "payload": payload})
        material = self.client.warehouse_material(organization, payload["materialPackageInstance"]["package"]["material"]["uuid"])
        return item, team, title, payload, existing, key, journal, fingerprint, material

    def preview(self, identifier, version, notes_revision):
        with self.monitor.lock, self.configuration.lock:
            item, team, title, payload, existing, key, journal, fingerprint, material = self._prepare(identifier, version, notes_revision)
            return {"fingerprint": fingerprint, "version": version, "notes_revision": notes_revision,
                    "spool_number": item["spool_number"], "name": title, "organization": team["name"],
                    "consumed_weight": item["aux"]["consumed_weight"], "remaining_weight": item["remaining_weight"],
                    "initial_weight": item["main"].get("actual_netto_full_weight", item["main"]["nominal_netto_full_weight"]),
                    "notes": item["notes"], "warehouse_id": existing.get("id") if existing else None,
                    "disposition": "repair" if existing and (not material or material["spoolCount"] == 0) else
                        "resume" if journal and journal["phase"] != "verified" else "present" if existing else "create"}

    def export(self, identifier, version, notes_revision, fingerprint):
        with self.monitor.lock, self.configuration.lock:
            item, team, title, payload, existing, key, journal, expected, material = self._prepare(identifier, version, notes_revision)
            if fingerprint != expected:
                raise ConnectError("export_changed", "L’aperçu d’envoi a changé. Relisez-le avant de confirmer.", 409)
            # Recheck after the network reads; a local/MCP edit must invalidate this preview.
            current = self.store.get_spool(item["id"])
            if current["version"] != version or current["notes_revision"] != notes_revision:
                raise ConnectError("export_changed", "Cette fiche a changé. Rechargez-la avant l’envoi vers Connect.", 409)
            already_present = existing is not None and (not journal or journal["phase"] == "verified")
            registered = False
            if material is None:
                # Connect's material catalogue powers the visible warehouse list.
                # An inline spool snapshot alone is accepted but remains invisible.
                if existing and identity((existing.get("materialPackageInstance", {}).get("package", {}).get("material") or {}).get("uuid")) != payload["materialPackageInstance"]["package"]["material"]["uuid"]:
                    raise ConnectError("export_changed", "Le matériau de la fiche Connect diffère. Vérifiez sa référence avant de réparer son affichage.", 409)
                if journal and journal["phase"] == "material_registering":
                    raise ConnectError("uncertain", "L’enregistrement du matériau Connect n’est pas confirmé. Relisez l’entrepôt avant de reprendre.", 503)
                registration = {"version": 1, "phase": "material_registering", "at": utc(),
                    "warehouse_id": existing["id"] if existing else None, "creation_attempted": bool(existing),
                    "payload_hash": digest({"name": title, "payload": payload})}
                self._save(key, registration, claim=existing is None and not journal)
                try:
                    self.client.register_warehouse_material(payload["materialPackageInstance"]["package"]["material"])
                except ConnectError:
                    # A lost response can be reconciled by reading, never by another write.
                    material = self.client.warehouse_material(team["id"], payload["materialPackageInstance"]["package"]["material"]["uuid"])
                    if material is None:
                        raise
                material = self.client.warehouse_material(team["id"], payload["materialPackageInstance"]["package"]["material"]["uuid"])
                if material is None:
                    raise ConnectError("uncertain", "L’enregistrement du matériau Connect n’est pas confirmé. Relisez l’entrepôt avant de reprendre.", 503)
                registration["phase"] = "material_ready"
                self._save(key, registration)
                registered = True
            if already_present:
                if material["spoolCount"] < 1:
                    raise ConnectError("uncertain", "La fiche existe côté Connect, mais sa visibilité dans l’entrepôt n’est pas encore confirmée.", 503)
                mismatch = differences(existing, title, payload)
                result = {"status": "repaired" if registered else "already_present", "warehouse_id": existing["id"], "spool_number": item["spool_number"],
                          "created": False, "verified": not mismatch, "visible_in_connect": True, "differences": mismatch, "inventory_changed": False, "rfid_written": False}
                # A previously existing record is linked, never overwritten by another export.
                self._save(key, {"version": 1, "phase": "verified", "warehouse_id": existing["id"], "at": utc(), "fingerprint": expected})
                return result
            if journal and journal.get("warehouse_id") and existing and journal["warehouse_id"] != existing["id"]:
                raise ConnectError("export_duplicate", "L’identité Connect ne correspond pas à l’envoi enregistré.", 409)
            payload_hash = digest({"name": title, "payload": payload})
            if journal and journal.get("payload_hash") != payload_hash and journal["phase"] != "rejected":
                raise ConnectError("export_changed", "Les données ont changé depuis l’envoi interrompu. Vérifiez la fiche Connect avant de reprendre.", 409)
            if journal and journal["phase"] == "material_registering" and not journal.get("creation_attempted"):
                # The material appeared after a lost registration response.
                self._save(key, {**journal, "phase": "material_ready"})
            created = existing is None
            record = {"version": 1, "phase": "creating", "fingerprint": expected, "at": utc(), "spool_id": item["id"],
                      "instance_uuid": item["instance_uuid"], "payload": payload, "payload_hash": payload_hash, "name": title,
                      "creation_attempted": created}
            try:
                if created:
                    self._save(key, record, claim=True)
                    response = self.client.create_warehouse_item(payload)
                    record.update(phase="created", warehouse_id=response["id"])
                    self._save(key, record)
                    existing = matching_item(self.client.collection(WAREHOUSE_QUERY, team["id"], warehouse=True), item["instance_uuid"])
                    if existing is None or existing["id"] != response["id"]:
                        raise ConnectError("uncertain", "Connect n’a pas confirmé l’identité attendue. Aucune seconde création ne sera lancée.", 503)
                else:
                    record.update(phase="created", warehouse_id=existing["id"])
                if existing.get("name") != title:
                    record["phase"] = "renaming"
                    self._save(key, record)
                    self.client.name_warehouse_item(team["id"], existing["id"], title)
                remote = matching_item(self.client.collection(WAREHOUSE_QUERY, team["id"], warehouse=True), item["instance_uuid"])
                mismatch = differences(remote, title, payload) if remote else ["instance_uuid"]
                if mismatch or remote["id"] != record["warehouse_id"]:
                    raise ConnectError("uncertain", "La relecture Connect diffère des données envoyées. Aucune nouvelle création n’est lancée.", 503)
                visible = self.client.warehouse_material(team["id"], payload["materialPackageInstance"]["package"]["material"]["uuid"])
                if not visible or visible["spoolCount"] < 1:
                    raise ConnectError("uncertain", "La fiche existe côté Connect, mais sa visibilité dans l’entrepôt n’est pas encore confirmée.", 503)
                record.update(phase="verified", verified_at=utc())
                self._save(key, record)
                return {"status": "created" if created else "reconciled", "warehouse_id": remote["id"], "spool_number": item["spool_number"],
                        "created": created, "verified": True, "visible_in_connect": True, "differences": [], "inventory_changed": False, "rfid_written": False}
            except ConnectError as exc:
                if exc.code in {"warehouse_rejected", "access", "rate_limit"} and created and record["phase"] == "creating":
                    record.update(phase="rejected", error=exc.code)
                    self._save(key, record)
                raise
