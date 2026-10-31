"""API de la station. Opérations locales ou ouvertes par le partage réseau."""
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
import asyncio
import base64
import hashlib
import ipaddress
import logging
import math
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from anyio import CancelScope
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from . import APP_NAME, __version__
from .camera import CameraBusy, CameraScanner, CameraUnavailable
from .config import Settings
from .https import HTTPSConfiguration, HTTPSProxyMiddleware
from .domain import DomainError, TagImage, get_schema, validate_favorite_main, spool_snapshot, reusable_profile
from .qr import inspect_qr
from .prusament import PrusamentError, resolve_prusament
from .prusa_product import resolve_prusa_product
from .nfc import HardwareReader
from .network import NetworkAccess, NetworkAccessError
from .printer import PrinterConfiguration, PrinterError, PrusaLinkMonitor
from .printer_events import PrinterEvents, event_frame
from .printer_cameras import PrinterCameras
from .readers import ReaderUnavailable, SimulatedReader, WriteRejected, revision
from .storage import ConflictError, Store, MAX_NOTES_LENGTH
from .spool_qr import encode_spool
from .labels import LabelPrinter
from .power import LogindPower, PowerError, StationPower
from .mcp_server import MCPConfiguration, MCPTransport
from .library_transfer import LibraryTransfer
from .backups import BackupManager, BackupError, MaintenanceGate, recover_restore, MAX_ARCHIVE
from .updates import ReleaseMonitor
from .assistant import LabelAssistant, AssistantError, MAX_IMAGE

LOG = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedTag(Model):
    expected_uid: str = Field(min_length=16, max_length=16)
    expected_revision: str = Field(min_length=1, max_length=150)


class Prepare(ExpectedTag):
    mode: Literal["create", "update"]
    main: dict[str, Any] = Field(default_factory=dict)
    aux: dict[str, Any] = Field(default_factory=dict)
    qr_raw: str | None = Field(default=None, max_length=8192)
    favorite_id: str | None = Field(default=None, max_length=100)
    inventory_id: str | None = Field(default=None, max_length=100)
    inventory_version: StrictInt | None = Field(default=None, ge=1)
    inventory_recreate: StrictBool = False


class Commit(Model):
    preview_id: str = Field(min_length=8, max_length=100)


class PowerAction(Model):
    action: Literal["poweroff", "reboot"]


class PowerConfirmation(PowerAction):
    confirmation_token: str = Field(min_length=8, max_length=100)


class Version(Model):
    version: StrictInt = Field(ge=1)


class UsageState(Version):
    usage_state: Literal["stock", "in_service"]


class Notes(Model):
    text: str = Field(max_length=MAX_NOTES_LENGTH)
    revision: StrictInt = Field(ge=0)


class UpdateSettings(Model):
    revision: StrictInt = Field(ge=0)
    enabled: StrictBool
    repository: str = Field(max_length=140)
    interval_hours: StrictInt = Field(ge=1, le=168)
    include_prereleases: StrictBool
    token: str | None = Field(default=None, max_length=512)
    clear_token: StrictBool = False


class LibraryExport(Model):
    identifiers: list[str] = Field(min_length=1, max_length=1000)


class LibraryFile(Model):
    document: str = Field(max_length=1_000_000)


class ImportChoice(Model):
    index: StrictInt = Field(ge=0, le=999)
    action: Literal["skip", "create", "replace", "rename"]
    name: str = Field(default="", max_length=120)


class LibraryImport(Model):
    preview_id: str = Field(min_length=8, max_length=100)
    choices: list[ImportChoice] = Field(min_length=1, max_length=1000)


class AssistantSettings(Model):
    revision: StrictInt = Field(ge=0)
    enabled: StrictBool
    model: str = Field(min_length=1, max_length=100)
    web_search: StrictBool
    api_key: str | None = Field(default=None, max_length=512)
    clear_key: StrictBool = False


class AssistantAnalysis(Model):
    scan_id: str | None = Field(default=None, max_length=100)
    image: str | None = Field(default=None, max_length=MAX_IMAGE * 4 // 3 + 100)
    language: Literal["fr", "en"] = "fr"


class BackupDownload(Model):
    scope: Literal["all", "inventory", "configuration"]
    password: str | None = Field(default=None, max_length=256)


class BackupFile(Model):
    content: str = Field(max_length=(MAX_ARCHIVE * 4 // 3 + 8))
    password: str | None = Field(default=None, max_length=256)


class BackupRestore(Model):
    preview_id: str = Field(min_length=8, max_length=100)
    confirmed: StrictBool


class BackupSettings(Model):
    revision: StrictInt = Field(ge=0)
    enabled: StrictBool
    encrypted: StrictBool = False
    destination: str = Field(max_length=1000)
    mount_path: str = Field(max_length=1000)
    mount_source: str = Field(max_length=1000)
    frequency: Literal["daily", "weekly"]
    time: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    weekday: StrictInt = Field(ge=0, le=6)
    timezone: str = Field(max_length=100)
    keep: StrictInt = Field(ge=1, le=365)
    password: str | None = Field(default=None, max_length=256)


class Packaged(Model):
    main: dict[str, Any]
    aux: dict[str, Any] = Field(default_factory=dict)
    qr_raw: str | None = Field(default=None, max_length=8192)
    favorite_id: str | None = Field(default=None, max_length=100)


class Associate(ExpectedTag, Version):
    recreate: StrictBool = False


class LabelSettings(Model):
    revision: StrictInt = Field(ge=0)
    enabled: bool = False
    model: Literal["b3s_p", "b1"] = "b3s_p"
    port: str = Field(default="", max_length=250)
    width_mm: StrictInt = Field(default=70, ge=20, le=72)
    height_mm: StrictInt = Field(default=40, ge=20, le=150)
    density: StrictInt = Field(default=3, ge=1, le=5)


class LabelJob(Version):
    settings_revision: StrictInt = Field(ge=0)
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


class Favorite(Model):
    name: str = Field(min_length=1, max_length=120)
    main: dict[str, Any] = Field(default_factory=dict)
    kind: Literal["favorite", "model"] | None = None


class FavoriteUpdate(Favorite):
    version: StrictInt = Field(ge=1)


class QR(Model):
    text: str = Field(min_length=1, max_length=8192)


class ModelSource(Model):
    source: Literal["rfid", "qr"]
    text: str | None = Field(default=None, min_length=1, max_length=8192)
    expected_uid: str | None = Field(default=None, pattern=r"^[0-9A-F]{16}$")
    expected_revision: str | None = Field(default=None, min_length=1, max_length=150)


class SelectTag(Model):
    uid: str = Field(min_length=16, max_length=16)


class Consume(Model):
    amount_g: float = Field(gt=0, allow_inf_nan=False)


class Protection(Model):
    main: bool
    aux: bool


class NetworkConfiguration(Model):
    mode: Literal["disabled", "inventory", "full"]


class MCPSettings(Model):
    enabled: StrictBool
    revision: StrictInt = Field(ge=0)


class PrinterDevice(Model):
    enabled: bool = False
    name: str = Field(default="Prusa CORE One", max_length=80)
    url: str = Field(default="", max_length=2000)
    auth: Literal["api_key", "digest"] = "api_key"
    username: str = Field(default="maker", max_length=120)
    secret: str | None = Field(default=None, max_length=1024)
    clear_secret: bool = False


class PrinterCameraDevice(Model):
    id: str | None = Field(default=None, max_length=64)
    enabled: bool = True
    name: str = Field(default="Caméra", max_length=80)
    url: str = Field(default="", max_length=2000)
    auth: Literal["none", "basic", "digest"] = "none"
    username: str = Field(default="", max_length=120)
    secret: str | None = Field(default=None, max_length=1024)
    clear_secret: bool = False


class ConnectPreparation(Model):
    printer_uuid: str = Field(default="", max_length=36)


class PrinterSettings(Model):
    revision: StrictInt = Field(ge=0)
    printer: PrinterDevice
    connect: ConnectPreparation = Field(default_factory=ConnectPreparation)
    cameras: list[PrinterCameraDevice] = Field(default_factory=list, max_length=4)


@dataclass
class Preview:
    uid: str
    revision: str
    image: bytes
    expires: float
    provenance: dict
    inventory_id: str | None = None
    inventory_version: int | None = None
    inventory_recreate: bool = False


def local_station(request):
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        return False


def station_access(request):
    return local_station(request) or request.app.state.network.enabled


def require_station(request):
    if not station_access(request):
        raise HTTPException(403, "Activez l’accès complet dans Configuration → Accès distant pour utiliser le lecteur, les caméras et le suivi imprimante.")


def blank(record):
    return not any(record["image"][:record.get("usable_capacity", len(record["image"]))])


def create_app(settings: Settings | None = None, camera: CameraScanner | None = None, reader=None,
               printer_fetch=None, printer_capture=None, label_runner=None, power_backend=None, updates_fetch=None,
               prusament_fetch=None, prusa_product_fetch=None, assistant_fetch=None):
    settings = settings or Settings.from_env()
    https = HTTPSConfiguration.load(settings.https_config)
    if https.url:
        settings = replace(settings, network_enabled=True, network_url=https.url,
                           allowed_hosts=tuple(dict.fromkeys((*settings.allowed_hosts, *https.hosts))))
    recover_restore(settings.data_dir, settings.database)
    store = Store(settings.database)
    store.recover_label_jobs()
    network = NetworkAccess(settings.data_dir, settings.network_enabled, settings.network_url)
    mcp_configuration = MCPConfiguration(settings.data_dir)
    if reader is None:
        reader = SimulatedReader(store) if settings.mode == "simulation" else HardwareReader(Path(settings.data_dir) / "nfc-backups")
    if settings.mode == "hardware":
        store.recover_pending_operations()
    previews: OrderedDict[str, Preview] = OrderedDict()
    camera = camera or CameraScanner(settings.camera_enabled)
    printer_configuration = PrinterConfiguration(settings.data_dir)
    printer_monitor = PrusaLinkMonitor(printer_configuration, **({"fetch": printer_fetch} if printer_fetch else {}))
    printer_events = PrinterEvents(printer_monitor)
    printer_cameras = PrinterCameras(printer_configuration, capture=printer_capture,
                                    **({"fetch": printer_fetch} if printer_fetch else {}))
    label_printer = LabelPrinter(settings.data_dir, store, runner=label_runner)
    maintenance = MaintenanceGate()
    library_transfer = LibraryTransfer(store)
    assistant = LabelAssistant(settings.data_dir, **({"fetch": assistant_fetch} if assistant_fetch else {}))

    def hardware_busy():
        if assistant.analysis_lock.locked():
            return True
        if getattr(camera, "is_scanning", lambda: False)() or label_printer.lock.locked():
            return True
        if not reader.lock.acquire(blocking=False):
            return True
        reader.lock.release()
        return False

    station_power = StationPower(power_backend or LogindPower(enabled=settings.mode == "hardware"), busy=hardware_busy)
    updates = ReleaseMonitor(settings.data_dir, **({"fetch": updates_fetch} if updates_fetch else {}),
                             allowed=lambda: not station_power.state()["pending"] and not maintenance.exclusive)

    def reload_configuration():
        nonlocal network, mcp_configuration, printer_configuration
        network = NetworkAccess(settings.data_dir, settings.network_enabled, settings.network_url)
        mcp_configuration = MCPConfiguration(settings.data_dir)
        printer_configuration = PrinterConfiguration(settings.data_dir)
        printer_monitor.configuration = printer_configuration
        printer_monitor._revision = None
        printer_events.reset()
        printer_cameras.configuration = printer_configuration
        label_printer.configuration = LabelPrinter(settings.data_dir, store).configuration
        previews.clear()
        library_transfer.previews.clear()
        app.state.network, app.state.mcp_configuration = network, mcp_configuration
        app.state.printer_configuration = printer_configuration
        updates.reload()
        assistant.reload()

    backups = BackupManager(settings, store, maintenance,
                            busy=lambda: hardware_busy() or station_power.state()["pending"],
                            reload_configuration=reload_configuration)

    @asynccontextmanager
    async def lifespan(app):
        backups.start()
        updates.start()
        try:
            yield
        finally:
            backups.close()
            updates.close()
            printer_cameras.close()
            camera.close()
            if hasattr(reader, "close"):
                reader.close()

    app = FastAPI(title=APP_NAME, version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store, app.state.reader, app.state.settings = store, reader, settings
    app.state.camera = camera
    app.state.assistant = assistant
    app.state.network = network
    app.state.printer_configuration = printer_configuration
    app.state.printer_monitor = printer_monitor
    app.state.printer_events = printer_events
    app.state.printer_cameras = printer_cameras
    app.state.label_printer = label_printer
    app.state.station_power = station_power
    app.state.mcp_configuration = mcp_configuration
    app.state.backups, app.state.maintenance = backups, maintenance
    app.state.library_transfer = library_transfer
    app.state.updates = updates
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def browser_boundary(request: Request, call_next):
        mcp_request = request.url.path.rstrip("/") == "/mcp"
        if (network.mode == "disabled" and not local_station(request)
                and request.url.path not in {"/", "/api/status", "/api/configuration", "/api/configuration/network", "/api/configuration/mcp",
                                             "/https", "/https/certificate", "/api/configuration/https"}
                and not request.url.path.startswith("/static/")):
            return JSONResponse({"detail": "Les fonctions distantes sont désactivées. Vous pouvez les réactiver dans Configuration → Accès distant."},
                                status_code=403, headers={"Cache-Control": "no-store"})
        if mcp_request:
            if not mcp_configuration.enabled:
                return JSONResponse({"detail": "Le serveur MCP est désactivé dans Configuration."}, status_code=404, headers={"Cache-Control": "no-store"})
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != request.url.scheme or parsed.netloc.casefold() != request.headers.get("host", "").casefold():
                    return JSONResponse({"detail": "Origine de requête non autorisée."}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                return JSONResponse({"detail": "Une requête JSON est requise."}, status_code=415)
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != request.url.scheme or parsed.netloc.casefold() != request.headers.get("host", "").casefold():
                    return JSONResponse({"detail": "Origine de requête non autorisée."}, status_code=403)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Taille de requête invalide."}, status_code=400)
            limit = (MAX_ARCHIVE * 4 // 3 + 2048 if request.url.path == "/api/backups/restore/preview"
                     else 6_100_000 if request.url.path in {"/api/library/import/preview", "/api/assistant/analyse"} else 256_000)
            if length > limit:
                return JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
            if request.url.path in {"/api/backups/restore/preview", "/api/library/import/preview", "/api/assistant/analyse"}:
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        return JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
        operation = ((request.url.path.startswith("/api/") or mcp_request)
                     and not request.url.path.startswith("/api/system/power")
                     and (request.method in {"POST", "PUT", "PATCH", "DELETE"} or request.url.path == "/api/reader/tag"))
        from .installation import installation_busy
        if (operation or (request.url.path.startswith("/api/system/power") and request.method == "POST")) and installation_busy():
            return JSONResponse({"detail": "L’installation d’OPT Station est en cours. Réessayez dans un instant."},
                                status_code=503, headers={"Cache-Control": "no-store"})
        if operation:
            try:
                station_power.enter_operation()
            except PowerError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=exc.status_code, headers={"Cache-Control": "no-store"})
        guarded = request.url.path.startswith("/api/") or mcp_request
        if guarded:
            try:
                maintenance.enter()
            except BackupError as exc:
                if operation:
                    station_power.leave_operation()
                return JSONResponse({"detail": str(exc)}, status_code=exc.status_code, headers={"Cache-Control": "no-store"})
        try:
            response = await call_next(request)
        finally:
            if guarded:
                maintenance.leave()
            if operation:
                station_power.leave_operation()
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/") or mcp_request or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(ConflictError)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ReaderUnavailable)
    async def reader_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(CameraUnavailable)
    async def camera_unavailable_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(CameraBusy)
    async def camera_busy_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(NetworkAccessError)
    async def network_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(PowerError)
    async def power_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(BackupError)
    async def backup_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(AssistantError)
    async def assistant_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(PrinterError)
    async def printer_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(PrusamentError)
    async def prusament_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(KeyError)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": str(exc.args[0])}, status_code=404)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        errors = "; ".join(f"{'.'.join(str(x) for x in e['loc'] if x != 'body')} : {e['msg']}" for e in exc.errors())
        return JSONResponse({"detail": "Requête invalide : " + errors}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def database_handler(request, exc):
        LOG.exception("Erreur de base de données")
        return JSONResponse({"detail": "La base de données est indisponible. Réessayer après avoir vérifié le stockage."}, status_code=503)

    def tag_snapshot(record=None, observe=False, pending_inventory=None):
        record = record or reader.read()
        if blank(record):
            result = {"uid": record["uid"], "revision": revision(record), "blank": True, "main": {}, "aux": {}, "instance_uuid": None, "remaining_weight": None, "remaining_estimated": False, "usage": {"main_used": 0, "main_capacity": 0, "aux_used": 0, "aux_capacity": 0}}
        else:
            tag = TagImage.from_bytes(bytes(record["image"]), record["uid"])
            result = tag.snapshot()
            result.update(blank=False, revision=revision(record), instance_uuid=str(tag.instance_uuid))
        result["protections"] = {"main": bool(record["main_locked"]), "aux": bool(record["aux_locked"])}
        result["simulation"] = settings.mode == "simulation"
        result["memory"] = {"capacity": len(record["image"]), "usable_capacity": record.get("usable_capacity", len(record["image"])),
                            "block_bytes": record.get("block_bytes"), "write_supported": record.get("write_supported", True)}
        result["provenance"] = store.source(record["uid"])
        if pending_inventory is not None:
            store.check_tag_destination(pending_inventory, result)
            result["inventory"] = pending_inventory
        elif not result["blank"]:
            candidate = store.pending_replacement(result, hashlib.sha256(bytes(record["image"])).hexdigest())
            if candidate:
                result["inventory"] = None
                result["association_pending"] = {"id": candidate["id"], "version": candidate["version"],
                                                  "spool_number": candidate["spool_number"], "recreate": True}
                result.setdefault("warnings", []).append("Ce tag a été écrit, mais son association à la bobine reste à confirmer.")
            else:
                result["inventory"] = store.observe(result) if observe else store.find(result)
        else:
            result["inventory"] = None
        return result

    def expected(record, body):
        if record["uid"] != body.expected_uid or revision(record) != body.expected_revision:
            raise ConflictError("Le tag présent ou ses données ont changé. Relire la bobine et préparer à nouveau l’opération.")

    def inspect_online_qr(text):
        result = inspect_qr(text)
        if result["kind"] == "url":
            result = (resolve_prusament(text, fetch=prusament_fetch)
                      or resolve_prusa_product(text, fetch=prusa_product_fetch) or result)
        return result

    def simulator(request):
        require_station(request)
        if settings.mode != "simulation":
            raise HTTPException(409, "Le simulateur est désactivé en mode matériel.")

    @app.get("/")
    def index():
        if not (STATIC / "index.html").exists():
            raise HTTPException(503, "Interface en cours de préparation.")
        markup = (STATIC / "index.html").read_text(encoding="utf-8")
        for name in ("translations.js", "i18n.js", "app.js", "printer.js", "notifications.js", "power.js", "mcp.js", "maintenance.js", "updates.js", "https.js", "assistant.js", "configuration.js", "theme.js", "style.css", "favicon.svg"):
            digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:16]
            markup = markup.replace(f'"/static/{name}"', f'"/static/{name}?v={digest}"')
        return HTMLResponse(markup)

    @app.get("/https")
    def https_help():
        markup = (STATIC / "https.html").read_text(encoding="utf-8")
        for name in ("translations.js", "i18n.js", "https.js", "theme.js", "style.css"):
            digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:16]
            markup = markup.replace(f'"/static/{name}"', f'"/static/{name}?v={digest}"')
        return HTMLResponse(markup, headers={"Cache-Control": "no-store"})

    @app.get("/api/configuration/https")
    def https_settings(request: Request):
        return https.public(secure=request.url.scheme == "https")

    @app.get("/https/certificate")
    def https_certificate():
        try:
            content = https.pem()
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None
        return Response(content, media_type="application/x-pem-file",
                        headers={"Content-Disposition": 'attachment; filename="opt-station-root-ca.crt"', "Cache-Control": "no-store"})

    @app.get("/api/status")
    def status(request: Request):
        return {"version": __version__, "mode": settings.mode, "local_station": local_station(request), "station_access": station_access(request),
                "network": network.snapshot(),
                "power": station_power.state(),
                "mcp": {"enabled": mcp_configuration.enabled, "revision": mcp_configuration.revision},
                "updates": updates.snapshot() if local_station(request) or network.mode != "disabled" else None,
                "assistant": assistant.public() if station_access(request) else None,
                "library_revision": store.library_revision(),
                "inventory_revision": store.inventory_revision() if local_station(request) or network.mode != "disabled" else None,
                "inventory_notes_revision": store.inventory_notes()["revision"] if local_station(request) or network.mode != "disabled" else None,
                "completed_spools_count": store.completed_count() if local_station(request) or network.mode != "disabled" else None,
                "reader": reader.status(), "camera": camera.status(), "specification_commit": "060e420892d66c062c8af440c97701aab96bac79"}

    @app.get("/api/system/power")
    def power_capabilities(request: Request):
        require_station(request)
        return station_power.snapshot()

    @app.post("/api/system/power/prepare")
    def prepare_power(request: Request, body: PowerAction):
        require_station(request)
        return station_power.prepare(body.action)

    @app.post("/api/system/power")
    def confirm_power(request: Request, body: PowerConfirmation, background_tasks: BackgroundTasks):
        require_station(request)
        result = station_power.confirm(body.action, body.confirmation_token)
        # Send the acknowledgement before logind stops this service.
        background_tasks.add_task(station_power.execute)
        return JSONResponse(result, status_code=202)

    @app.get("/api/configuration")
    def configuration(refresh: bool = False):
        camera_details = camera.devices(refresh=refresh) if hasattr(camera, "devices") else {}
        return {"reader": reader.status(), "camera": {**camera.status(), **camera_details}, "network": network.snapshot(),
                "printer": printer_configuration.public()}

    @app.get("/api/configuration/updates")
    def update_settings(request: Request):
        require_station(request)
        return updates.settings()

    @app.put("/api/configuration/updates")
    def save_update_settings(request: Request, body: UpdateSettings):
        require_station(request)
        try:
            return updates.save(body.model_dump())
        except OSError:
            raise HTTPException(503, "L’enregistrement des réglages GitHub n’est pas confirmé. Rechargez-les avant de réessayer.") from None

    @app.post("/api/updates/check", status_code=202)
    def check_updates(request: Request):
        require_station(request)
        return updates.request_check()

    def mcp_snapshot(request):
        endpoint = (network.url if network.configured else str(request.base_url).rstrip("/")) + "/mcp"
        return mcp_configuration.snapshot(endpoint)

    @app.get("/api/configuration/mcp")
    def mcp_settings(request: Request):
        return mcp_snapshot(request)

    @app.put("/api/configuration/mcp")
    def save_mcp_settings(request: Request, body: MCPSettings):
        require_station(request)
        try:
            mcp_configuration.save(body.enabled, body.revision)
        except OSError:
            raise HTTPException(503, "Impossible d’enregistrer la configuration MCP. Le réglage précédent est conservé.") from None
        return mcp_snapshot(request)

    def require_printer_access(request):
        if not station_access(request):
            raise HTTPException(403, "Activez l’accès complet dans Configuration → Accès distant pour consulter l’imprimante, ses caméras et ses réglages.")

    @app.get("/api/configuration/printer")
    def printer_settings(request: Request):
        require_printer_access(request)
        return printer_configuration.editable()

    @app.put("/api/configuration/printer")
    def save_printer_settings(request: Request, body: PrinterSettings):
        require_printer_access(request)
        try:
            return printer_configuration.save(body.model_dump())
        except OSError:
            raise HTTPException(503, "Impossible d’enregistrer la configuration imprimante sur le Pi.") from None

    @app.get("/api/printer/status")
    def printer_status(request: Request, refresh: bool = False):
        require_printer_access(request)
        return printer_monitor.snapshot(force=refresh)

    @app.get("/api/printer/events")
    async def printer_event_stream(request: Request):
        require_printer_access(request)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Origine de requête non autorisée.")

        async def stream():
            with CancelScope(shield=True):
                await run_in_threadpool(printer_events.subscribe)
            try:
                cursor = None
                while not await request.is_disconnected():
                    if not station_access(request):
                        yield event_frame("access", {"allowed": False})
                        break
                    if maintenance.exclusive or station_power.state()["pending"]:
                        yield event_frame("paused", {})
                        break
                    next_cursor, status, events = await run_in_threadpool(printer_events.poll, cursor)
                    if not station_access(request):
                        yield event_frame("access", {"allowed": False})
                        break
                    if maintenance.exclusive or station_power.state()["pending"]:
                        yield event_frame("paused", {})
                        break
                    # Chaque connexion part de l'état courant, sans rejouer un ancien événement.
                    yield event_frame("status", status)
                    for event in events:
                        yield event_frame("printer", event, event["id"])
                    cursor = next_cursor
                    await asyncio.sleep(printer_events.interval)
            finally:
                with CancelScope(shield=True):
                    await run_in_threadpool(printer_events.unsubscribe)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/printer/thumbnail")
    def printer_thumbnail(request: Request):
        require_printer_access(request)
        mime, data = printer_monitor.thumbnail()
        return Response(data, media_type=mime)

    @app.get("/api/printer/cameras/{identifier}/image")
    def printer_camera_image(identifier: str, request: Request):
        require_printer_access(request)
        mime, data = printer_cameras.image(identifier)
        return Response(data, media_type=mime)

    @app.put("/api/configuration/network")
    def configure_network(request: Request, body: NetworkConfiguration):
        try:
            return network.set_mode(body.mode)
        except OSError as exc:
            raise HTTPException(503, "Impossible d’enregistrer les accès sur le stockage du Pi. Les réglages actuels sont conservés.") from exc

    @app.get("/api/configuration/labels")
    def label_settings(request: Request):
        require_station(request)
        return label_printer.snapshot()

    @app.put("/api/configuration/labels")
    def save_label_settings(request: Request, body: LabelSettings):
        require_station(request)
        try:
            return label_printer.save(body.model_dump())
        except OSError:
            raise HTTPException(503, "Impossible d’enregistrer les réglages de l’imprimante d’étiquettes.") from None

    @app.post("/api/labels/probe")
    def probe_labels(request: Request):
        require_station(request)
        return label_printer.probe()

    @app.get("/api/schema")
    def schema():
        return get_schema()

    @app.get("/api/reader/tag")
    def read_tag(request: Request):
        require_station(request)
        with reader.lock:
            return tag_snapshot(observe=True)

    @app.post("/api/reader/prepare")
    def prepare(request: Request, body: Prepare):
        require_station(request)
        with reader.lock:
            current = reader.read()
            expected(current, body)
            if not blank(current) and store.pending_replacement(
                    TagImage.from_bytes(bytes(current["image"]), current["uid"]).snapshot(),
                    hashlib.sha256(bytes(current["image"])).hexdigest()):
                raise ConflictError("Ce tag attend son association à la bobine. Confirmer l’association sans réécrire le tag.")
            if (body.inventory_id is None) != (body.inventory_version is None):
                raise DomainError("L’identité et la version de la fiche doivent être fournies ensemble.")
            if body.inventory_recreate and (body.inventory_id is None or body.qr_raw or body.favorite_id or body.mode != "create"):
                raise DomainError("La recréation doit être préparée depuis la fiche actuelle de la bobine dans l’inventaire.")
            inventory_item = None
            report = inspect_qr(body.qr_raw) if body.qr_raw else None
            if body.inventory_id is not None and report is None:
                if body.mode != "create":
                    raise ConflictError("Une fiche de stock prépare un nouveau tag. Relire le RFID existant pour le modifier.")
                inventory_item = store.pending(body.inventory_id, body.inventory_version, recreate=body.inventory_recreate)
                if any(inventory_item.get("unknown_fields", {}).values()):
                    raise DomainError("Cette bobine contient des champs RFID inconnus. Une recréation complète nécessite leur prise en charge.")
                if body.main.get("instance_uuid", inventory_item["instance_uuid"]) != inventory_item["instance_uuid"]:
                    raise ConflictError("L’identité de la bobine doit rester celle de la fiche d’inventaire.")
                # Keep unchanged values on the server, including large integers.
                body.main = {**inventory_item["main"], **body.main, "instance_uuid": inventory_item["instance_uuid"]}
                body.aux = {**inventory_item["aux"], **body.aux}
            if report and report["kind"] == "opt_station":
                if body.mode != "create":
                    raise ConflictError("Une étiquette QR prépare un nouveau tag. Relire le RFID existant pour le modifier.")
                if body.main.get("instance_uuid", report["instance_uuid"]) != report["instance_uuid"]:
                    raise ConflictError("L’identité de la bobine doit rester celle du QR.")
                # Unchanged values are decoded from CBOR on the server, including
                # integers that cannot round-trip through a JavaScript Number.
                body.main = {**report["main"], **body.main, "instance_uuid": report["instance_uuid"]}
                body.aux = {**report["aux"], **body.aux}
                inventory_item = store.by_instance(report["instance_uuid"])
                if inventory_item:
                    if body.inventory_id != inventory_item["id"] or body.inventory_version != inventory_item["version"]:
                        raise ConflictError("Recharger la fiche et son QR avant de préparer le tag.")
                    store.pending(body.inventory_id, body.inventory_version)
                    if report["main"] != inventory_item["main"] or report["aux"] != inventory_item["aux"]:
                        raise ConflictError("Cette étiquette contient une ancienne fiche. Réimprimer le QR actuel depuis l’inventaire.")
            if body.inventory_id is not None and (not inventory_item or inventory_item["id"] != body.inventory_id):
                raise ConflictError("L’association nécessite la fiche d’inventaire ou son QR complet actuel.")
            if current.get("write_supported") is False:
                raise HTTPException(423, current.get("write_reason", "L’écriture n’est pas prise en charge pour ce tag."))
            if body.mode == "create":
                if not blank(current):
                    raise ConflictError("Le tag contient déjà des données. Utiliser Modifier, ou présenter un tag vierge.")
                capacity = current.get("usable_capacity", len(current["image"]))
                created = TagImage.create(current["uid"], body.main, body.aux, capacity=capacity).to_bytes()
                proposed = TagImage.from_bytes(created + bytes(current["image"])[capacity:], current["uid"])
                before = {"main": {}, "aux": {}}
            else:
                if blank(current):
                    raise ConflictError("Ce tag est vierge. Utiliser Créer un nouveau tag.")
                original = TagImage.from_bytes(bytes(current["image"]), current["uid"])
                before = original.snapshot()
                proposed = original.with_updates(body.main, body.aux)
                if proposed.instance_uuid != original.instance_uuid:
                    raise DomainError("Une simple modification doit conserver l’identité de la bobine. Le réemploi est une opération distincte.")
            after = proposed.snapshot()
            changes = []
            for region in ("main", "aux"):
                changed = before.get(region, {}) != after.get(region, {})
                if changed and current[f"{region}_locked"]:
                    raise HTTPException(423, f"La région {region} est protégée. Les champs concernés ne peuvent pas être modifiés.")
                for name in sorted(set(before.get(region, {})) | set(after.get(region, {}))):
                    old, new = before.get(region, {}).get(name), after.get(region, {}).get(name)
                    if old != new:
                        changes.append({"region": region, "name": name, "before": old, "after": new})
            if body.mode == "update" and not changes:
                raise DomainError("Aucune modification à écrire.")
            proposed_record = {**current, "image": proposed.to_bytes()}
            # Détecter une identité déjà liée à un autre tag avant l’écriture.
            preview_snapshot = tag_snapshot(proposed_record, observe=False, pending_inventory=inventory_item)
            if (preview_snapshot.get("inventory") or {}).get("label_state") == "qr" and not inventory_item:
                raise ConflictError("Cette identité possède une fiche QR. Préparer le tag depuis son étiquette complète pour l’associer à cette fiche.")
            stamp = time.monotonic()
            for token in list(previews):
                if previews[token].expires < stamp:
                    del previews[token]
            while len(previews) >= 16:
                previews.popitem(last=False)
            token = secrets.token_urlsafe(24)
            provenance = store.source(current["uid"]) if body.mode == "update" else {"kind": "manual"}
            if inventory_item and report is None:
                provenance = {"kind": "inventory", "inventory_id": inventory_item["id"], "spool_number": inventory_item["spool_number"]}
            if body.favorite_id:
                matches = [f for f in store.favorites() if f["id"] == body.favorite_id]
                if not matches:
                    raise DomainError("Le favori sélectionné n’existe plus. Recharger les favoris.")
                provenance = {"kind": "favorite", "favorite_id": body.favorite_id, "favorite_name": matches[0]["name"], "favorite_version": matches[0]["version"]}
            if body.qr_raw:
                report = inspect_qr(body.qr_raw)
                provenance = {"kind": "qr", "raw": body.qr_raw, "qr_kind": report["kind"], "message": report["message"]}
            previews[token] = Preview(current["uid"], revision(current), proposed.to_bytes(), stamp + 300, provenance,
                                      inventory_item["id"] if inventory_item else None,
                                      inventory_item["version"] if inventory_item else None, body.inventory_recreate)
            return {"preview_id": token, "tag": preview_snapshot, "changes": changes, "expires_in_seconds": 300,
                    "recreation": body.inventory_recreate}

    @app.post("/api/reader/write")
    def write_tag(request: Request, body: Commit):
        require_station(request)
        with reader.lock:
            proposal = previews.pop(body.preview_id, None)
            if not proposal or proposal.expires < time.monotonic():
                raise ConflictError("La préparation a expiré ou a déjà été utilisée. Préparer l’écriture à nouveau.")
            current = reader.read()
            if current["uid"] != proposal.uid or revision(current) != proposal.revision:
                raise ConflictError("Le tag a changé depuis la préparation. Aucune nouvelle écriture n’a été lancée; relire puis préparer à nouveau.")
            if not blank(current):
                snapshot = tag_snapshot(current, observe=False)
                if snapshot.get("association_pending"):
                    raise ConflictError("Ce tag attend son association à la bobine. Confirmer l’association sans réécrire le tag.")
            if proposal.inventory_id:
                target = store.pending(proposal.inventory_id, proposal.inventory_version, recreate=proposal.inventory_recreate)
                intended = TagImage.from_bytes(proposal.image, proposal.uid).snapshot()
                store.check_tag_destination(target, intended)
            operation = store.begin_operation(proposal.uid, proposal.revision, proposal.inventory_id, proposal.inventory_version,
                                              hashlib.sha256(proposal.image).hexdigest())
            try:
                reader.write(proposal.image)
                observed = reader.read()
                if observed["uid"] != proposal.uid or bytes(observed["image"]) != proposal.image:
                    raise ReaderUnavailable("La relecture ne correspond pas à l’écriture demandée.")
            except WriteRejected as exc:
                store.end_operation(operation, "rejected", detail=str(exc))
                raise HTTPException(exc.status_code, str(exc)) from exc
            except Exception as exc:
                try:
                    store.end_operation(operation, "uncertain", detail="Écriture non confirmée par relecture; ne pas répéter sans lire le tag.")
                except sqlite3.Error:
                    LOG.exception("Écriture incertaine; journal indisponible : %s", operation)
                raise HTTPException(503, "Le résultat de l’écriture est incertain. Relire le tag avant toute nouvelle tentative.") from exc
            try:
                store.end_operation(operation, "tag_verified", revision(observed))
                store.save_source(proposal.uid, proposal.provenance)
                if proposal.inventory_id:
                    target = store.pending(proposal.inventory_id, proposal.inventory_version, recreate=proposal.inventory_recreate)
                    store.associate(proposal.inventory_id, proposal.inventory_version,
                                    tag_snapshot(observed, observe=False, pending_inventory=target),
                                    recreate=proposal.inventory_recreate, image_hash=hashlib.sha256(proposal.image).hexdigest())
                result = tag_snapshot(observed, observe=True)
                store.end_operation(operation, "complete", revision(observed))
            except (sqlite3.Error, ConflictError) as exc:
                LOG.exception("Tag vérifié, inventaire à réconcilier : %s", operation)
                raise HTTPException(503, "Le tag a été écrit et vérifié, mais la mise à jour de l’inventaire n’est pas confirmée. Relire le tag; ne pas répéter automatiquement l’écriture.") from exc
            return {"tag": result, "verified": True, "simulation": settings.mode == "simulation", "operation_id": operation}

    @app.get("/api/inventory")
    def inventory(search: str = "", include_removed: bool = False, sort: Literal["recent", "oldest", "newest"] = "oldest"):
        return {"items": store.list_spools(search[:200], include_removed, sort)}

    @app.get("/api/inventory/notes")
    def inventory_notes():
        return store.inventory_notes()

    @app.put("/api/inventory/notes")
    def save_inventory_notes(body: Notes):
        return store.save_inventory_notes(body.text, body.revision)

    @app.put("/api/inventory/{identifier}/notes")
    def save_spool_notes(identifier: str, body: Notes):
        return store.save_spool_notes(identifier, body.text, body.revision)

    @app.post("/api/inventory/packaged")
    def create_packaged(body: Packaged):
        provenance = {"kind": "manual"}
        added_at = None
        if body.favorite_id:
            matches = [f for f in store.favorites() if f["id"] == body.favorite_id]
            if not matches:
                raise ConflictError("Ce favori n’existe plus. Recharger la liste.")
            provenance = {"kind": "favorite", "favorite_id": body.favorite_id, "favorite_name": matches[0]["name"]}
        if body.qr_raw:
            report = inspect_qr(body.qr_raw)
            provenance = {"kind": "qr", "raw": body.qr_raw, "qr_kind": report["kind"]}
            if report["kind"] == "opt_station":
                if body.main.get("instance_uuid", report["instance_uuid"]) != report["instance_uuid"]:
                    raise ConflictError("L’identité logique de la bobine doit rester celle de son étiquette.")
                body.main = {**report["main"], **body.main}
                body.aux = {**report["aux"], **body.aux}
                added_at = report["added_at"]
        # Ensure the complete data can be encoded before inserting anything.
        snapshot = spool_snapshot(body.main, body.aux)
        encode_spool(snapshot)
        return store.create_packaged(snapshot["main"], snapshot["aux"], added_at, provenance)

    @app.get("/api/inventory/{identifier}")
    def inventory_detail(identifier: str):
        return store.get_spool(identifier)

    @app.post("/api/inventory/{identifier}/usage")
    def inventory_usage(identifier: str, body: UsageState):
        with reader.lock:
            return store.set_usage(identifier, body.version, body.usage_state)

    @app.post("/api/inventory/{identifier}/model-source")
    def inventory_model_source(identifier: str, body: Version):
        item = store.get_spool(identifier)
        if item["version"] != body.version:
            raise ConflictError("Cette fiche a changé. Rechargez la bobine avant de préparer son modèle.")
        warnings = (["Certains champs non pris en charge du tag ne sont pas copiés dans le modèle."]
                    if any(item.get("unknown_fields", {}).values()) else [])
        return {**reusable_profile(item["main"], item["aux"]), "source": "inventory",
                "spool_number": item["spool_number"], "warnings": warnings, "matches": []}

    @app.get("/api/inventory/{identifier}/qr")
    def inventory_qr(identifier: str, version: int):
        item = store.get_spool(identifier)
        if item["version"] != version:
            raise ConflictError("La fiche a changé. Recharger l’étiquette.")
        return {"text": encode_spool(item), "item": item}

    @app.get("/api/inventory/{identifier}/label")
    def inventory_label(identifier: str, version: int):
        item = store.get_spool(identifier)
        if item["version"] != version:
            raise ConflictError("La fiche a changé. Recharger l’étiquette.")
        label = label_printer.preview(item)
        png = label.pop("png")
        return {**label, "image": "data:image/png;base64," + base64.b64encode(png).decode(), "item": item}

    @app.post("/api/inventory/{identifier}/print")
    def inventory_print(identifier: str, request: Request, body: LabelJob):
        require_station(request)
        return label_printer.print(store.get_spool(identifier), body)

    @app.post("/api/inventory/{identifier}/associate")
    def associate_existing_tag(identifier: str, request: Request, body: Associate):
        require_station(request)
        with reader.lock:
            item = store.pending(identifier, body.version, recreate=body.recreate)
            current = reader.read()
            expected(current, body)
            if blank(current):
                raise ConflictError("Le tag est vierge. Préparer son écriture depuis le QR de la bobine.")
            snapshot = tag_snapshot(current, observe=False, pending_inventory=item)
            image_hash = hashlib.sha256(bytes(current["image"])).hexdigest()
            if body.recreate:
                candidate = store.pending_replacement(snapshot, image_hash)
                if candidate is None or candidate["id"] != item["id"]:
                    raise ConflictError("Ce tag n’attend pas une association vérifiée. Préparer sa recréation depuis la fiche de la bobine.")
            if (item["main"] != snapshot["main"] or item["aux"] != snapshot["aux"]) and not store.matching_association(
                    identifier, snapshot["uid"], hashlib.sha256(bytes(current["image"])).hexdigest()):
                raise ConflictError("Les données du tag diffèrent de la fiche QR. Vérifier les deux fiches avant association.")
            return store.associate(identifier, body.version, snapshot, recreate=body.recreate, image_hash=image_hash)

    @app.post("/api/inventory/add")
    def add_inventory(request: Request, body: ExpectedTag):
        require_station(request)
        with reader.lock:
            record = reader.read()
            expected(record, body)
            if blank(record):
                raise DomainError("Un tag vierge ne peut pas être ajouté à l’inventaire.")
            result = tag_snapshot(record)
            if result.get("association_pending"):
                raise ConflictError("Ce tag attend son association à la bobine. Confirmer l’association sans réécrire le tag.")
            result.pop("inventory", None)
            return store.add(result)

    @app.post("/api/inventory/{identifier}/remove")
    def remove_inventory(identifier: str, body: Version):
        return store.remove(identifier, body.version)

    @app.post("/api/inventory/{identifier}/restore")
    def restore_inventory(identifier: str, body: Version):
        return store.restore(identifier, body.version)

    @app.post("/api/inventory/{identifier}/complete")
    def complete_inventory(identifier: str, body: Version):
        with reader.lock:
            return store.complete(identifier, body.version)

    @app.get("/api/favorites")
    def favorites():
        return {"items": store.favorites()}

    @app.post("/api/library/model-source")
    def model_source(request: Request, body: ModelSource):
        if body.source == "rfid":
            require_station(request)
            if body.text is not None or (body.expected_uid is None) != (body.expected_revision is None):
                raise DomainError("Indiquez soit un QR, soit une lecture RFID avec son identité complète.")
            with reader.lock:
                current = reader.read()
                if body.expected_uid is not None:
                    expected(current, body)
                source = tag_snapshot(current, observe=False)
            result = reusable_profile(source["main"], source["aux"])
            warnings = (["Certains champs non pris en charge du tag ne sont pas copiés dans le modèle."]
                        if any(source.get("unknown_fields", {}).values()) else [])
            return {**result, "source": "rfid", "warnings": warnings, "matches": []}
        if body.expected_uid is not None or body.expected_revision is not None or not body.text or not body.text.strip():
            raise DomainError("Scannez ou collez d’abord le contenu d’un QR ou d’un code produit.")
        source = inspect_online_qr(body.text)
        if len(source.get("matches", [])) > 1:
            return {"source": "qr", "main": {}, "suggested_name": "", "excluded_fields": [],
                    "warnings": source.get("warnings", []), "message": source["message"],
                    "matches": [{**reusable_profile(match["main"], {}), "label": match.get("label") or match["main"].get("material_name")}
                                for match in source["matches"]]}
        if not source.get("main"):
            raise DomainError(source["message"])
        return {**reusable_profile(source["main"], source.get("aux", {})), "source": "qr",
                "warnings": source.get("warnings", []), "matches": []}

    @app.post("/api/favorites")
    def add_favorite(body: Favorite):
        return store.save_favorite(body.name, validate_favorite_main(body.main), kind=body.kind)

    @app.put("/api/favorites/{identifier}")
    def update_favorite(identifier: str, body: FavoriteUpdate):
        return store.save_favorite(body.name, validate_favorite_main(body.main), identifier, body.version, kind=body.kind)

    @app.delete("/api/favorites/{identifier}")
    def delete_favorite(identifier: str, body: Version):
        try:
            return store.delete_favorite(identifier, body.version)
        except KeyError:
            raise HTTPException(404, "Cette fiche n’existe plus. Rechargez la bibliothèque.") from None

    @app.post("/api/library/export")
    def export_library(body: LibraryExport):
        from .storage import dumps
        return Response(dumps(library_transfer.export(body.identifiers)).encode(), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="opt-station-library.json"'})

    @app.post("/api/library/import/preview")
    def preview_library(body: LibraryFile):
        return library_transfer.preview(body.document)

    @app.post("/api/library/import/commit")
    def import_library(body: LibraryImport):
        return library_transfer.commit(body.preview_id, [x.model_dump() for x in body.choices])

    @app.get("/api/configuration/backups")
    def backup_settings(request: Request):
        require_station(request)
        return backups.snapshot()

    @app.put("/api/configuration/backups")
    def save_backup_settings(request: Request, body: BackupSettings):
        require_station(request)
        try:
            return backups.save(body.model_dump(exclude_unset=True))
        except OSError:
            raise HTTPException(503, "Impossible d’enregistrer les réglages de sauvegarde.") from None

    @app.post("/api/backups/download")
    def download_backup(request: Request, body: BackupDownload):
        require_station(request)
        try:
            content = backups.download(body.scope, body.password)
        except OSError:
            raise HTTPException(503, "Impossible de créer la sauvegarde. Vérifiez le stockage du Pi.") from None
        return Response(content, media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="opt-station-' + body.scope + '.optbak"'})

    @app.post("/api/backups/restore/preview")
    def preview_backup(request: Request, body: BackupFile):
        require_station(request)
        try:
            content = base64.b64decode(body.content, validate=True)
        except ValueError:
            raise HTTPException(422, "Fichier de sauvegarde illisible.") from None
        return backups.preview(content, body.password)

    @app.post("/api/backups/restore/commit")
    def restore_backup(request: Request, body: BackupRestore):
        require_station(request)
        if not body.confirmed:
            raise HTTPException(422, "Confirmez le remplacement des données avant de restaurer.")
        return backups.restore(body.preview_id)

    @app.post("/api/backups/points/{identifier}/preview")
    def preview_restore_point(identifier: str, request: Request):
        require_station(request)
        return backups.preview_point(identifier)

    @app.post("/api/backups/run")
    def run_backup(request: Request):
        require_station(request)
        return backups.run()

    @app.post("/api/qr/inspect")
    def qr(body: QR):
        report = inspect_online_qr(body.text)
        if report["kind"] == "opt_station":
            item = store.by_instance(report["instance_uuid"])
            if item:
                if item["completed_at"]:
                    report["inventory"] = item
                    report["message"] = "Bobine terminée et archivée. Sa fiche est consultable dans Inventaire → Terminées · archives."
                    return report
                if item["label_state"] != "qr":
                    raise ConflictError("Cette bobine possède déjà un RFID. Ouvrir sa fiche existante; le QR ne réinitialise pas sa consommation.")
                if report["main"] != item["main"] or report["aux"] != item["aux"]:
                    raise ConflictError("Cette étiquette contient une ancienne fiche. Utiliser le QR actuel de l’inventaire.")
                if not item["in_stock"]:
                    report["message"] = "Bobine retrouvée hors stock. Ouvrir son étiquette pour la remettre explicitement au stock avant de préparer le RFID."
            report["inventory"] = item
        return report

    @app.get("/api/configuration/assistant")
    def assistant_settings(request: Request):
        require_station(request)
        return assistant.public()

    @app.put("/api/configuration/assistant")
    def save_assistant_settings(request: Request, body: AssistantSettings):
        require_station(request)
        return assistant.save(body.model_dump())

    @app.post("/api/assistant/photo")
    def assistant_photo(request: Request):
        require_station(request)
        return camera.start_photo()

    @app.post("/api/assistant/analyse")
    def assistant_analyse(request: Request, body: AssistantAnalysis):
        require_station(request)
        if bool(body.scan_id) == bool(body.image):
            raise AssistantError("Choisissez une photo ou une capture caméra.")
        if body.scan_id:
            image = camera.photo(body.scan_id)
        else:
            content = body.image
            if content.startswith("data:"):
                if not content.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")):
                    raise AssistantError("Format d’image non pris en charge.")
                content = content.split(",", 1)[1]
            try:
                image = base64.b64decode(content, validate=True)
            except ValueError:
                raise AssistantError("La photo est illisible.") from None
        return assistant.analyse(image, body.language)

    @app.post("/api/camera/scans")
    def camera_start(request: Request):
        require_station(request)
        return camera.start()

    @app.get("/api/camera/scans/{identifier}")
    def camera_result(identifier: str, request: Request):
        require_station(request)
        return camera.get(identifier)

    @app.get("/api/camera/scans/{identifier}/preview")
    def camera_preview(identifier: str, request: Request):
        require_station(request)
        return Response(camera.preview(identifier), media_type="image/jpeg")

    @app.delete("/api/camera/scans/{identifier}")
    def camera_cancel(identifier: str, request: Request):
        require_station(request)
        return camera.cancel(identifier)

    @app.get("/api/simulator/tags")
    def simulated_tags(request: Request):
        simulator(request)
        with reader.lock:
            return {"items": reader.list_tags()}

    @app.post("/api/simulator/select")
    def select_simulated_tag(request: Request, body: SelectTag):
        simulator(request)
        with reader.lock:
            reader.select(body.uid)
            return tag_snapshot(observe=False)

    @app.post("/api/simulator/blank")
    def blank_simulated_tag(request: Request):
        simulator(request)
        with reader.lock:
            reader.blank()
            return tag_snapshot(observe=False)

    @app.post("/api/simulator/consume")
    def consume_simulated_tag(request: Request, body: Consume):
        simulator(request)
        with reader.lock:
            current = reader.read()
            if blank(current):
                raise DomainError("Initialiser le tag avant de simuler sa consommation.")
            if current["aux_locked"]:
                raise HTTPException(423, "La région Aux est protégée.")
            tag = TagImage.from_bytes(bytes(current["image"]), current["uid"])
            snap = tag.snapshot()
            consumed = snap["aux"].get("consumed_weight")
            remaining = snap.get("remaining_weight")
            if consumed is None:
                raise DomainError("La consommation initiale est inconnue. La renseigner avant cette simulation.")
            if not math.isfinite(body.amount_g) or (remaining is not None and body.amount_g > remaining):
                raise DomainError("La consommation simulée dépasse la quantité restante connue.")
            reader.write(tag.with_updates({}, {"consumed_weight": consumed + body.amount_g}).to_bytes())
            return tag_snapshot(observe=False)

    @app.post("/api/simulator/protection")
    def protect_simulated_tag(request: Request, body: Protection):
        simulator(request)
        with reader.lock:
            reader.protect(body.main, body.aux)
            return tag_snapshot(observe=False)

    @app.get("/api/operations")
    def operations(request: Request):
        require_station(request)
        return {"items": store.operations()}

    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    mcp_transport = MCPTransport(store, settings.allowed_hosts)
    for path in ("/mcp", "/mcp/"):
        app.router.routes.append(Route(path, endpoint=mcp_transport, methods=["GET", "POST", "DELETE"]))
    app.add_middleware(HTTPSProxyMiddleware, enabled=bool(https.url))
    return app
