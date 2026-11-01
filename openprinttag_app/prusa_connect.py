"""Connect counters and explicit warehouse exports, never printer commands.

The queries follow Connect's web client (2026.39), not a stable third-party API.
Only an exact OpenPrintTag instance UUID can select a local inventory record.
"""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

from . import __version__


GRAPHQL_URL = "https://connect-api.prusa3d.com/graphql"
TOKEN_URL = "https://account.prusa3d.com/o/token/"
# Public identifier shipped by connect.prusa3d.com/environment.js; not a secret.
WEB_CLIENT_ID = "MRHTlZhZqkNrrQ6FUPtjyusAz8nc59ErHXP8XkS4"
MAX_BODY = 2 * 1024 * 1024

ME_QUERY = """query OptStationTeams { authorization { me { organizations { id name } } } }"""
PRINTERS_QUERY = """query OptStationPrinters($organizationId: UUID!, $first: Int!, $after: String) {
  printer { printers(organizationId: $organizationId, first: $first, after: $after, sortBy: NAME) {
    __typename ... on PrinterConnection { pageInfo { hasNextPage endCursor } edges { node {
      id name state fff { tools { id class type telemetry { active }
        materialPackageInstance { __typename ... on FFFToolMaterialPackageInstance {
          uuid actualNettoFullWeight isFromNfc dynamicData { consumedWeight }
          package { nominalNettoFullWeight material { name abbreviation brand { name } } }
        } ... on ToolMaterialPackageInstanceEmpty { reason } }
      } }
    } } } ... on ConnectError { message }
  } }
}"""
WAREHOUSE_QUERY = """query OptStationWarehouse($organizationId: String!, $first: Int!, $after: String) {
  warehouse { items(organizationId: $organizationId, first: $first, after: $after) {
    totalCount pageInfo { hasNextPage endCursor } nodes {
      id name consumedWeight remainingWeight nominalNettoFullWeight loaded empty archived
      materialPackageInstanceUuidSource printer { id name } toolId
      note location materialPackageInstance { uuid actualNettoFullWeight
        package { nominalNettoFullWeight nominalFullLength filamentDiameter
          container { emptyWeight }
          material { uuid name type brand { name } primaryColor { colorRgba } }
        }
      }
    }
  } }
}"""

CREATE_WAREHOUSE_MUTATION = """mutation OptStationCreateWarehouseItem($input: WarehouseCreateItemsInput!) {
  warehouse { createItems(input: $input) {
    __typename ... on WarehouseCreateItemsSuccess { items { id name } }
    ... on WarehouseServiceError { errorCode }
    ... on WarehouseValidationError { errorCode }
  } }
}"""
RENAME_WAREHOUSE_MUTATION = """mutation OptStationNameWarehouseItem($organizationId: String!, $uuid: String!, $input: WarehouseUpdateItemInput!) {
  warehouse { updateItem(organizationId: $organizationId, uuid: $uuid, input: $input) {
    __typename ... on WarehouseMutateItemSuccess { item { id name } }
    ... on WarehouseServiceError { errorCode }
    ... on WarehouseValidationError { errorCode }
  } }
}"""
WAREHOUSE_MATERIALS_QUERY = """query OptStationWarehouseMaterials($organizationId: String!, $materialUuid: [UUID!], $first: Int!, $after: String) {
  warehouse { materials(organizationId: $organizationId, materialUuid: $materialUuid, first: $first, after: $after) {
    totalCount totalSpoolCount totalRemainingWeight pageInfo { hasNextPage endCursor }
    nodes { uuid spoolCount material { uuid name type brand { name } } }
  } }
}"""
CREATE_MATERIAL_MUTATION = """mutation OptStationRegisterWarehouseMaterial($material: WarehouseMaterialInput!) {
  warehouse { createCustomMaterial(material: $material) { id createdAt } }
}"""


def utc(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat()


class ConnectError(ValueError):
    def __init__(self, code, message, status_code=502):
        self.code, self.status_code = code, status_code
        super().__init__(message)


def positive(value, *, zero=False):
    return type(value) in {int, float} and math.isfinite(value) and (value >= 0 if zero else value > 0)


def identity(value):
    try:
        if not isinstance(value, str):
            return None
        parsed = uuid.UUID(value)
        return str(parsed) if parsed.int else None
    except (ValueError, AttributeError):
        return None


def expires_at(token):
    """Expiry is a UI/refresh hint only; Connect authenticates the actual token."""
    try:
        part = token.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        expiry = value.get("exp")
        return float(expiry) if positive(expiry) and expiry <= 253402300799 else None
    except (ValueError, IndexError, TypeError, AttributeError):
        return None


def defaults(printer_uuid=""):
    return {"version": 1, "revision": 0, "enabled": False, "printer_uuid": printer_uuid,
            "organization_id": "", "sync_consumption": False, "sync_warehouse": False,
            "poll_seconds": 30, "access_token": "", "refresh_token": "", "client_id": WEB_CLIENT_ID}


def validate(record):
    if not isinstance(record, dict) or set(record) != set(defaults()):
        raise ValueError("Réglages Prusa Connect invalides.")
    if (type(record["version"]) is not int or record["version"] != 1
            or type(record["revision"]) is not int or record["revision"] < 0
            or any(type(record[k]) is not bool for k in ("enabled", "sync_consumption", "sync_warehouse"))
            or type(record["poll_seconds"]) is not int or not 30 <= record["poll_seconds"] <= 900):
        raise ValueError("Réglages Prusa Connect invalides.")
    result = deepcopy(record)
    for key in ("printer_uuid", "organization_id"):
        if not isinstance(record[key], str) or (record[key] and not identity(record[key])):
            raise ValueError("L’imprimante et l’organisation Connect utilisent des UUID.")
        result[key] = identity(record[key]) or ""
    for key in ("access_token", "refresh_token", "client_id"):
        if not isinstance(record[key], str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{0,16384}", record[key]):
            raise ValueError("Accès Prusa Connect invalide.")
    if not result["client_id"] or len(result["client_id"]) > 200:
        raise ValueError("Identifiant de client Prusa invalide.")
    if result["enabled"] and not (result["access_token"] or result["refresh_token"]):
        raise ValueError("Renseignez un accès utilisateur Connect avant d’activer la connexion.")
    if result["sync_consumption"] and not result["printer_uuid"]:
        raise ValueError("Choisissez l’imprimante Connect avant d’activer sa synchronisation.")
    return result


class ConnectConfiguration:
    def __init__(self, directory, printer_uuid=""):
        self.path = Path(directory) / "connect-settings.json"
        self.lock = threading.RLock()
        self.record = defaults(printer_uuid)
        if self.path.exists():
            self.record = validate(json.loads(self.path.read_bytes()))
            self.path.chmod(0o600)

    def read(self):
        with self.lock:
            return deepcopy(self.record)

    def public(self):
        record = self.read()
        expiry = expires_at(record["access_token"])
        record["access_expires_at"] = utc(expiry) if expiry else None
        for key in ("access_token", "refresh_token"):
            record[key + "_saved"] = bool(record.pop(key))
        return record

    def _write(self, record):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.path.parent, prefix=".connect-", delete=False) as output:
                temporary = Path(output.name)
                os.fchmod(output.fileno(), 0o600)
                json.dump(record, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        self.record = record

    def save(self, body):
        with self.lock:
            if body["revision"] != self.record["revision"]:
                raise ConnectError("conflict", "Ces réglages Connect ont changé. Rechargez-les avant d’enregistrer.", 409)
            record = {**self.record, **{k: v for k, v in body.items() if k in defaults() and k not in {"version", "access_token", "refresh_token"}}}
            if record["client_id"] != self.record["client_id"] and not body.get("refresh_token"):
                record["refresh_token"] = ""
            for key in ("access_token", "refresh_token"):
                if body.get("clear_" + key):
                    record[key] = ""
                elif body.get(key) is not None:
                    record[key] = body[key].strip()
            record = validate(record)
            record["revision"] += 1
            self._write(record)
            return self.public()

    def rotate(self, old, tokens):
        with self.lock:
            if self.record != old:
                raise ConnectError("changed", "Les accès Connect ont changé pendant la connexion. Réessayez.", 409)
            record = {**old, **tokens}
            self._write(validate(record))
            return self.read()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def connect_request(url, headers, body):
    # Two fixed HTTPS origins, verified TLS, no ambient proxy or redirects.
    if url not in {GRAPHQL_URL, TOKEN_URL}:
        raise ConnectError("destination", "Destination Prusa Connect refusée.")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(
                Request(url, headers={"User-Agent": "OPT-Station/" + __version__, **headers}, data=body, method="POST"), timeout=8) as response:
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ConnectError("response", "Réponse Connect trop volumineuse.")
            return response.status, raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        return status, b""  # No upstream error bodies, headers or secrets in diagnostics.
    except (URLError, OSError, TimeoutError):
        raise ConnectError("network", "Prusa Connect est injoignable. Les quantités enregistrées sont conservées.") from None


class ConnectClient:
    def __init__(self, configuration, fetch=connect_request, clock=time.time):
        self.configuration, self.fetch, self.clock = configuration, fetch, clock
        self.lock = threading.RLock()

    def _refresh(self, record):
        if not record["refresh_token"]:
            raise ConnectError("access", "L’accès Connect a expiré ou a été refusé. Remplacez le jeton dans les paramètres.")
        status, raw = self.fetch(TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                                 urlencode({"grant_type": "refresh_token", "refresh_token": record["refresh_token"],
                                            "client_id": record["client_id"]}).encode())
        if status != 200:
            raise ConnectError("access", "Le renouvellement Connect a été refusé. Reconnectez la session dédiée.")
        try:
            value = json.loads(raw)
            token = value["access_token"]
            if not isinstance(token, str) or not token or value.get("token_type", "Bearer").lower() != "bearer":
                raise ValueError()
            return self.configuration.rotate(record, {"access_token": token,
                                                       "refresh_token": value.get("refresh_token") or record["refresh_token"]})
        except ConnectError:
            raise
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ConnectError("response", "Réponse d’autorisation Connect invalide.") from None

    def query(self, query, variables=None):
        if not query.lstrip().startswith("query "):
            raise ConnectError("readonly", "Seules les lectures Connect sont autorisées.")
        return self._execute(query, variables)

    def _execute(self, query, variables=None, *, write=False):
        if write and query not in {CREATE_WAREHOUSE_MUTATION, RENAME_WAREHOUSE_MUTATION, CREATE_MATERIAL_MUTATION}:
            raise ConnectError("readonly", "Opération Connect refusée.")
        with self.lock:
            record = self.configuration.read()
            expiry = expires_at(record["access_token"])
            if not record["access_token"] or (expiry and expiry - self.clock() < 60 and record["refresh_token"]):
                record = self._refresh(record)
            body = json.dumps({"query": query, "variables": variables or {}}, allow_nan=False).encode()
            for attempt in range(2):
                try:
                    status, raw = self.fetch(GRAPHQL_URL, {"Authorization": "Bearer " + record["access_token"],
                                             "Content-Type": "application/json", "Accept": "application/json",
                                             "graphql-client-name": "opt-station"}, body)
                except ConnectError:
                    if write:
                        raise ConnectError("uncertain", "L’envoi Connect n’est pas confirmé. Une relecture de l’entrepôt est nécessaire avant toute nouvelle création.", 503) from None
                    raise
                if not write and status == 401 and attempt == 0 and record["refresh_token"]:
                    record = self._refresh(record)
                    continue
                if status in {401, 403}:
                    if record["access_token"].count(".") != 2 and not record["refresh_token"]:
                        raise ConnectError("access", "Cet accès demande le jeton de session web auth.access_token, pas la clé API de l’imprimante. Consultez l’aide de connexion dans les paramètres.")
                    raise ConnectError("access", "Accès Connect refusé. Vérifiez le jeton utilisateur et les droits sur l’équipe.")
                if status == 429:
                    raise ConnectError("rate_limit", "Prusa Connect limite les lectures. La station réessaiera plus tard.")
                if status != 200:
                    if write:
                        raise ConnectError("uncertain", "L’envoi Connect n’est pas confirmé. Une relecture de l’entrepôt est nécessaire avant toute nouvelle création.", 503)
                    raise ConnectError("network", "Lecture Connect indisponible. Les quantités enregistrées sont conservées.")
                try:
                    result = json.loads(raw)
                    if not isinstance(result, dict) or result.get("errors") or not isinstance(result.get("data"), dict):
                        raise ValueError()
                    return result["data"]
                except (ValueError, TypeError):
                    if write:
                        raise ConnectError("uncertain", "L’envoi Connect n’est pas confirmé. Une relecture de l’entrepôt est nécessaire avant toute nouvelle création.", 503) from None
                    raise ConnectError("contract", "La réponse Connect ne correspond pas au contrat attendu. Aucune quantité n’est modifiée.") from None

    def _warehouse_write(self, query, variables, field, success):
        value = self._execute(query, variables, write=True)
        try:
            result = value["warehouse"][field]
            if result["__typename"] == success:
                return result
            if result["__typename"] in {"WarehouseServiceError", "WarehouseValidationError"}:
                if any(word in str(result.get("errorCode", "")).lower() for word in ("quota", "limit")):
                    raise ConnectError("warehouse_rejected", "La limite de bobines de l’entrepôt Prusa Connect est atteinte.", 409)
                raise ConnectError("warehouse_rejected", "Prusa Connect a refusé ces données de bobine. La fiche locale est conservée.", 422)
        except (KeyError, TypeError):
            pass
        raise ConnectError("uncertain", "L’envoi Connect n’est pas confirmé. Une relecture de l’entrepôt est nécessaire avant toute nouvelle création.", 503)

    def create_warehouse_item(self, payload):
        result = self._warehouse_write(CREATE_WAREHOUSE_MUTATION, {"input": payload}, "createItems", "WarehouseCreateItemsSuccess")
        items = result.get("items")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict) or not identity(items[0].get("id")):
            raise ConnectError("uncertain", "La création Connect n’a pas retourné une bobine unique. Relisez l’entrepôt.", 503)
        return items[0]

    def name_warehouse_item(self, organization, identifier, name):
        return self._warehouse_write(RENAME_WAREHOUSE_MUTATION,
            {"organizationId": organization, "uuid": identifier, "input": {"name": name}},
            "updateItem", "WarehouseMutateItemSuccess")

    def warehouse_material(self, organization, material_uuid):
        value = self.query(WAREHOUSE_MATERIALS_QUERY, {"organizationId": organization,
            "materialUuid": [material_uuid], "first": 100, "after": None})
        try:
            page = value["warehouse"]["materials"]
            nodes = page["nodes"]
            if (not isinstance(nodes, list) or type(page["totalCount"]) is not int
                    or page["totalCount"] != len(nodes) or page["pageInfo"]["hasNextPage"] is not False
                    or len(nodes) > 1):
                raise ValueError()
            if not nodes:
                return None
            node = nodes[0]
            count = node["spoolCount"]
            if (identity(node.get("uuid")) != material_uuid
                    or count is not None and (type(count) is not int or count < 0)
                    or identity(node["material"].get("uuid")) != material_uuid):
                raise ValueError()
            # The real catalogue returns null for a custom material with no
            # warehouse item yet. This is a stock count, never filament mass.
            return {**node, "spoolCount": 0 if count is None else count}
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ConnectError("contract", "Le catalogue de matériaux Connect n’a pas confirmé cette référence.") from None

    def register_warehouse_material(self, material):
        value = self._execute(CREATE_MATERIAL_MUTATION, {"material": material}, write=True)
        try:
            result = value["warehouse"]["createCustomMaterial"]
            if isinstance(result, dict) and result.get("id"):
                return
        except (KeyError, TypeError):
            pass
        raise ConnectError("uncertain", "L’enregistrement du matériau Connect n’est pas confirmé. Relisez l’entrepôt avant de reprendre.", 503)

    def teams(self):
        try:
            items = self.query(ME_QUERY)["authorization"]["me"]["organizations"]
            if not isinstance(items, list) or len(items) > 200:
                raise ValueError()
            result = [{"id": identity(x["id"]), "name": str(x.get("name") or "")[:150]} for x in items]
            if any(not x["id"] for x in result) or len({x["id"] for x in result}) != len(result):
                raise ValueError()
            return result
        except ConnectError:
            raise
        except (KeyError, ValueError, TypeError):
            raise ConnectError("contract", "Liste des organisations Connect invalide.") from None

    def collection(self, query, organization_id, *, warehouse=False):
        items, cursor, seen = [], None, set()
        for _ in range(10):
            response = self.query(query, {"organizationId": organization_id, "first": 100, "after": cursor})
            try:
                page = response["warehouse"]["items"] if warehouse else response["printer"]["printers"]
                values = page["nodes"] if warehouse else [x["node"] for x in page["edges"]]
                info = page["pageInfo"]
                if not isinstance(values, list) or len(values) > 100 or type(info["hasNextPage"]) is not bool:
                    raise ValueError()
                items.extend(values)
                if not info["hasNextPage"]:
                    if warehouse and (type(page["totalCount"]) is not int or page["totalCount"] != len(items)):
                        raise ValueError()
                    return items
                cursor = info["endCursor"]
                if not isinstance(cursor, str) or not cursor or len(cursor) > 1000 or cursor in seen:
                    raise ValueError()
                seen.add(cursor)
            except (KeyError, ValueError, TypeError):
                raise ConnectError("contract", "Liste Connect incomplète ou invalide. Aucune quantité n’est modifiée.") from None
        raise ConnectError("limit", "Liste Connect trop longue. Aucune quantité n’est modifiée.")


def loaded_samples(printer):
    """Only physically NFC-identified FFF print heads/slots; no file estimates."""
    if printer.get("state") in {"OFFLINE", "UNKNOWN", None}:
        return []
    fff = printer.get("fff")
    if fff is None:
        return []
    if not isinstance(fff, dict) or not isinstance(fff.get("tools"), list):
        raise ConnectError("contract", "Description des outils Connect invalide.")
    result = []
    for tool in fff["tools"]:
        material = tool.get("materialPackageInstance")
        if not isinstance(material, dict) or material.get("__typename") != "FFFToolMaterialPackageInstance" or material.get("isFromNfc") is not True:
            continue
        if (tool.get("telemetry") or {}).get("active") is not True:
            continue
        package = material.get("package") or {}
        description = package.get("material") or {}
        result.append({"instance_uuid": identity(material.get("uuid")),
                       "consumed_weight": (material.get("dynamicData") or {}).get("consumedWeight"),
                       "initial_weight": material.get("actualNettoFullWeight") if material.get("actualNettoFullWeight") is not None else package.get("nominalNettoFullWeight"),
                       "printer_uuid": identity(printer.get("id")), "tool_id": str(tool.get("id", ""))[:80],
                       "name": str(description.get("name") or description.get("abbreviation") or "")[:180],
                       "source": "loaded"})
    return result


def warehouse_samples(items):
    result = []
    for item in items:
        material = item.get("materialPackageInstance") or {}
        if item.get("archived") is not False:
            continue
        result.append({"instance_uuid": identity(material.get("uuid")), "consumed_weight": item.get("consumedWeight"),
                       "initial_weight": material.get("actualNettoFullWeight") if material.get("actualNettoFullWeight") is not None else item.get("nominalNettoFullWeight"),
                       "name": str(item.get("name") or "")[:180], "warehouse_id": str(item.get("id") or "")[:100],
                       "source": "warehouse"})
    return result


class ConnectMonitor:
    def __init__(self, configuration, store, *, fetch=connect_request, allowed=lambda: True, maintenance=None, clock=time.time):
        self.configuration, self.store = configuration, store
        self.client = ConnectClient(configuration, fetch, clock)
        self.allowed, self.maintenance, self.clock = allowed, maintenance, clock
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self._last_attempt = float("-inf")
        self._warehouse_presence = None
        self._state = {"connected": False, "stale": False, "checked_at": None, "message": "Prusa Connect est désactivé.", "spools": [], "warehouse": None}

    def settings_changed(self):
        with self.lock:
            self._last_attempt = float("-inf")
            self._state = {"connected": False, "stale": False, "checked_at": None, "message": "Réglages Connect enregistrés. Lancez le test de connexion.", "spools": [], "warehouse": None}
        self.wake.set()

    def inventory_warehouse(self):
        """Cached presence for inventory readers; no cloud call or network lock.

        Configuration records and this cache are replaced atomically, never
        edited in place. Reading them must not wait for a slow cloud request.
        Only identities already in the local inventory may leave this method.
        """
        cached, config = self._warehouse_presence, self.configuration.record
        if not cached or config["organization_id"] != cached["configured_organization"]:
            return {"instances": [], "checked_at": None, "stale": False}
        with self.store.connect() as db:
            known = {row[0] for row in db.execute("SELECT instance_uuid FROM spools")}
        stale = (not config["enabled"] or not self._state["connected"]
                 or bool((self._state.get("warehouse") or {}).get("error"))
                 or config["revision"] != cached["configuration_revision"]
                 or self.clock() - cached["at"] > max(60, 2 * config["poll_seconds"]))
        return {"instances": sorted(known.intersection(cached["instances"])),
                "checked_at": cached["checked_at"], "stale": stale}

    def warehouse_changed(self):
        """Refresh the existing collector promptly after a confirmed export."""
        with self.lock:
            self._last_attempt = float("-inf")
        self.wake.set()

    def public(self):
        with self.lock:
            config = self.configuration.read()
            return {**deepcopy(self._state), "enabled": config["enabled"],
                    "inventory_sync_active": config["enabled"] and config["sync_consumption"],
                    "warehouse_sync_active": config["enabled"] and config["sync_warehouse"],
                    "poll_seconds": config["poll_seconds"], "read_only_cloud": False,
                    "background_cloud_read_only": True, "manual_warehouse_export_available": True}

    def check(self, *, apply=False, force=False):
        with self.lock:
            config = self.configuration.read()
            if not config["enabled"]:
                self._state = {"connected": False, "stale": False, "checked_at": None, "message": "Prusa Connect est désactivé.", "spools": [], "warehouse": None}
                return self.public()
            delay = max(config["poll_seconds"], 120 if not self._state["connected"] else 30)
            if not force and self.clock() - self._last_attempt < delay or not self.allowed():
                return self.public()
            self._last_attempt = self.clock()
            try:
                teams = self.client.teams()
                organization = config["organization_id"] or (teams[0]["id"] if len(teams) == 1 else "")
                if not organization or organization not in {x["id"] for x in teams}:
                    self._state = {"connected": True, "stale": False, "checked_at": utc(self.clock()), "message": "Choisissez l’organisation Connect à utiliser.", "teams": teams, "printers": [], "spools": [], "warehouse": None}
                    return self.public()
                printers = self.client.collection(PRINTERS_QUERY, organization)
                if any(not isinstance(p, dict) or not identity(p.get("id")) for p in printers) or len({p["id"] for p in printers}) != len(printers):
                    raise ConnectError("contract", "Liste des imprimantes Connect invalide.")
                selected = next((p for p in printers if identity(p["id"]) == config["printer_uuid"]), None)
                samples = loaded_samples(selected) if selected else []
                warehouse_error = None
                try:
                    warehouse = self.client.collection(WAREHOUSE_QUERY, organization, warehouse=True)
                except ConnectError as exc:
                    # Warehouse availability/rights must not stop the loaded-spool reader.
                    warehouse, warehouse_error = [], str(exc)
                warehouse_counters = warehouse_samples(warehouse)
                # Loaded telemetry wins over the warehouse's stored copy of a spool.
                all_samples = [(s, config["sync_consumption"]) for s in samples]
                loaded_ids = {s["instance_uuid"] for s in samples if s["instance_uuid"]}
                all_samples += [(s, config["sync_warehouse"]) for s in warehouse_counters if s["instance_uuid"] not in loaded_ids]
                duplicates = {s["instance_uuid"] for s, _ in all_samples if s["instance_uuid"] and sum(x["instance_uuid"] == s["instance_uuid"] for x, _ in all_samples) > 1}
                checked = utc(self.clock())
                outcomes = []
                current = self.configuration.read()
                # Token rotation may change credentials; settings revision/selection must still match.
                if not self.allowed() or any(current[k] != config[k] for k in ("revision", "enabled", "printer_uuid", "organization_id", "sync_consumption", "sync_warehouse")):
                    return self.public()
                entered = False
                try:
                    if apply and self.maintenance:
                        self.maintenance.enter()
                        entered = True
                    for sample, sync in all_samples:
                        if sample["instance_uuid"] in duplicates:
                            outcomes.append({**sample, "status": "duplicate", "updated": False})
                            continue
                        outcomes.append(self.store.sync_connect_consumption(sample, checked, apply=apply and sync))
                finally:
                    if entered:
                        self.maintenance.leave()
                known = {x["instance_uuid"] for x in self.store.list_spools(include_removed=True)}
                matched = sum(identity((x.get("materialPackageInstance") or {}).get("uuid")) in known for x in warehouse)
                if warehouse_error is None:
                    present = [identity((x.get("materialPackageInstance") or {}).get("uuid"))
                               for x in warehouse if x.get("archived") is False and identity(x.get("id"))]
                    self._warehouse_presence = {"configured_organization": config["organization_id"],
                        "configuration_revision": config["revision"], "at": self.clock(), "checked_at": checked,
                        "instances": tuple(x for x in set(present) if x and present.count(x) == 1)}
                self._state = {"connected": True, "stale": False, "checked_at": checked,
                    "message": "Lecture Connect réussie. Les compteurs sont rapprochés par l’identité de chaque bobine.",
                    "teams": teams, "printers": [{"id": p["id"], "name": str(p.get("name") or "")[:150], "state": p.get("state")} for p in printers],
                    "selected_printer_found": selected is not None, "spools": outcomes,
                    "warehouse": ({"error": warehouse_error, "total": None, "matched": None, "unmatched": None} if warehouse_error else
                                  {"total": len(warehouse), "matched": matched, "unmatched": len(warehouse) - matched}),
                    "updated_count": sum(x.get("updated") is True for x in outcomes), "preview": not apply}
            except ConnectError as exc:
                self._state = {**self._state, "connected": False, "stale": self._state.get("checked_at") is not None,
                               "error": exc.code, "message": str(exc), "updated_count": 0}
            return self.public()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        def run():
            while not self.stop.is_set():
                try:
                    self.check(apply=True)
                except Exception:
                    # Do not log raw upstream exceptions, tokens or private inventory.
                    with self.lock:
                        self._state.update(connected=False, stale=bool(self._state.get("checked_at")),
                                           error="internal", message="La synchronisation Connect est suspendue. Les quantités enregistrées sont conservées.")
                self.wake.wait(5)
                self.wake.clear()
        self.thread = threading.Thread(target=run, name="opt-connect", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=10)
