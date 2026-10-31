"""Label rendering and explicit USB jobs, separate from NFC and stock changes."""
import base64
import copy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading

from PIL import Image, ImageDraw, ImageFont
import segno

from .domain import DomainError
from .network import NetworkAccess
from .niimbot import LabelError, PROFILES
from .spool_qr import encode_spool
from .storage import ConflictError

DEFAULTS = {"revision": 0, "enabled": False, "model": "b3s_p", "port": "",
            "width_mm": 70, "height_mm": 40, "density": 3}


def validate_settings(record):
    if not isinstance(record, dict) or set(record) != set(DEFAULTS):
        raise DomainError("Configuration d’étiquettes invalide.")
    result = dict(record)
    if type(result["enabled"]) is not bool or result["model"] not in PROFILES:
        raise DomainError("Profil d’imprimante d’étiquettes invalide.")
    for key, low, high in (("revision", 0, 2**31), ("width_mm", 20, PROFILES[result["model"]]["max_mm"]),
                           ("height_mm", 20, 150), ("density", 1, 5)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            labels = {"revision": "Version des réglages", "width_mm": "Largeur de l’étiquette (mm)", "height_mm": "Hauteur de l’étiquette (mm)", "density": "Densité"}
            raise DomainError(f"{labels[key]} : entier attendu entre {low} et {high}.")
    if not isinstance(result["port"], str) or (result["port"] and not re.fullmatch(
            r"/dev/(?:tty(?:USB|ACM)\d+|serial/by-id/[A-Za-z0-9_.:+-]+)", result["port"])):
        raise DomainError("Sélectionnez un port USB série du Pi, par exemple /dev/ttyACM0.")
    if result["enabled"] and not result["port"]:
        raise DomainError("Sélectionnez le port USB avant d’activer l’impression.")
    return result


def render_label(item, configuration):
    text = encode_spool(item)
    try:
        qr = segno.make_qr(text, error="m", boost_error=False)
    except segno.DataOverflowError:
        raise DomainError("Le contenu complet dépasse la capacité d’un QR. Aucune donnée n’a été supprimée.") from None
    profile = PROFILES[configuration["model"]]
    width = min(configuration["width_mm"] * 8, profile["head"])
    height = configuration["height_mm"] * 8
    width -= width % 8
    margin = 12
    modules = qr.symbol_size(border=4)[0]
    scale = min((width - 2 * margin) // modules, (height - 2 * margin) // modules)
    if scale < 3:
        raise DomainError("Ce QR complet est trop dense pour cette étiquette. Choisissez un format plus grand; aucune donnée n’est retirée.")
    square = modules * scale
    number = item.get("spool_number")
    side_caption = width - square - 2 * margin - 8 >= 95
    if number and not side_caption:
        # Narrow labels reserve an actual band, never drawing on the QR quiet zone.
        scale = min((width - 2 * margin) // modules, (height - 2 * margin - 34) // modules)
        if scale < 3:
            raise DomainError("Ce QR complet est trop dense pour cette étiquette. Choisissez un format plus grand; aucune donnée n’est retirée.")
        square = modules * scale
    png = io.BytesIO()
    qr.save(png, kind="png", scale=scale, border=4, dark="#000", light="#fff")
    code_image = Image.open(io.BytesIO(png.getvalue())).convert("1")
    image = Image.new("1", (width, height), 1)
    y = margin + (height - 2 * margin - square - (34 if number and not side_caption else 0)) // 2
    image.paste(code_image, (margin, y))
    draw = ImageDraw.Draw(image)
    x = square + margin + 8
    available = width - x - margin
    if side_caption:
        font = ImageFont.load_default(size=17)
        small = ImageFont.load_default(size=14)
        main = item["main"]
        name = main.get("material_name") or main.get("material_type") or "Bobine"
        lines = [("OPT Station", small), (main.get("brand_name", ""), small), (str(name), font),
                 (str(main.get("material_type", "")), small), (main.get("primary_color", ""), small)]
        weight = main.get("actual_netto_full_weight", main.get("nominal_netto_full_weight"))
        if weight is not None:
            lines.append((f"{weight:g} g net", small))
        if item.get("added_at"):
            lines.append(("Stock " + datetime.fromisoformat(item["added_at"]).strftime("%d/%m/%Y"), small))
        lines.append((item["instance_uuid"][:8], small))
        ty = margin
        if number:
            size = 28
            number_font = ImageFont.load_default(size=size)
            while draw.textlength(number, font=number_font) > available and size > 8:
                size -= 1
                number_font = ImageFont.load_default(size=size)
            if draw.textlength(number, font=number_font) > available:
                raise DomainError("Le numéro de bobine ne tient pas sur cette étiquette. Choisissez un format plus grand.")
            draw.text((x, ty), number, font=number_font, fill=0)
            ty += 38
        for line, current_font in lines:
            # Only the human-readable caption can be shortened. The QR is whole.
            words = str(line).split()
            while words and ty + 21 < height - margin:
                portion = words.pop(0)
                while words and draw.textlength(portion + " " + words[0], font=current_font) <= available:
                    portion += " " + words.pop(0)
                while draw.textlength(portion, font=current_font) > available and len(portion) > 1:
                    portion = portion[:-2] + "…"
                draw.text((x, ty), portion, font=current_font, fill=0)
                ty += 23
            ty += 5
    else:
        image = Image.new("1", (width, height), 1)
        image.paste(code_image, ((width - square) // 2, y))
        if number:
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default(size=24)
            if draw.textlength(number, font=font) > width - 2 * margin:
                raise DomainError("Le numéro de bobine ne tient pas sur cette étiquette. Choisissez un format plus grand.")
            draw.text(((width - draw.textlength(number, font=font)) // 2, height - margin - 28), number, font=font, fill=0)
    output = io.BytesIO()
    image.save(output, format="PNG", dpi=(203, 203))
    data = output.getvalue()
    return {"text": text, "png": data, "image_sha256": hashlib.sha256(data).hexdigest(),
            "width_px": width, "height_px": height, "module_pixels": scale, "qr_version": qr.version}


def run_worker(action, configuration, png=None):
    port = Path(configuration["port"])
    resolved = port.resolve()
    if not re.fullmatch(r"/dev/tty(?:USB|ACM)\d+", str(resolved)):
        raise LabelError("Le port choisi n’est pas un périphérique USB série du Pi.")
    try:
        if not stat.S_ISCHR(port.stat().st_mode):
            raise LabelError("Le port choisi n’est pas un périphérique USB série.")
    except OSError:
        raise LabelError("Imprimante USB absente. Allumez-la et vérifiez le câble et le port sélectionné.") from None
    request = {"action": action, "configuration": configuration}
    if png is not None:
        request["png"] = base64.b64encode(png).decode()
    try:
        process = subprocess.run([sys.executable, "-m", "openprinttag_app.label_worker"],
                                 input=json.dumps(request), text=True, capture_output=True, timeout=45,
                                 cwd=Path(__file__).resolve().parent.parent)
        result = json.loads(process.stdout)
        if process.returncode or not isinstance(result, dict):
            raise ValueError()
        return result
    except (subprocess.SubprocessError, ValueError):
        return {"status": "uncertain" if action == "print" else "failed",
                "detail": "Communication interrompue. Vérifier l’imprimante et toute étiquette sortie avant de réimprimer."}


class LabelPrinter:
    def __init__(self, directory, store, runner=None):
        self.path = Path(directory) / "label-printer-settings.json"
        self.store = store
        self.runner = runner or run_worker
        self.lock = threading.Lock()
        self.configuration = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            self.configuration = validate_settings(json.loads(self.path.read_text()))
            self.path.chmod(0o600)

    def snapshot(self):
        from serial.tools.list_ports import comports
        ports = [{"port": row.device, "name": row.description} for row in comports()
                 if re.fullmatch(r"/dev/tty(?:USB|ACM)\d+", row.device)]
        return {**copy.deepcopy(self.configuration), "ports": ports, "transport": "USB",
                "profiles": [{"model": name, "name": profile["name"]} for name, profile in PROFILES.items()]}

    def save(self, record):
        settings = validate_settings(record)
        if not self.lock.acquire(blocking=False):
            raise ConflictError("Une opération d’étiquettes est en cours. Attendre sa fin.")
        try:
            if settings["revision"] != self.configuration["revision"]:
                raise ConflictError("Les réglages d’étiquettes ont changé. Rechargez-les avant d’enregistrer.")
            settings["revision"] += 1
            NetworkAccess._save_json(self.path, settings)
            self.configuration = settings
            return self.snapshot()
        finally:
            self.lock.release()

    def preview(self, item):
        configuration = copy.deepcopy(self.configuration)
        result = render_label(item, configuration)
        return {**result, "settings_revision": configuration["revision"], "print_enabled": configuration["enabled"],
                "width_mm": configuration["width_mm"], "height_mm": configuration["height_mm"], "model": configuration["model"]}

    def probe(self):
        if not self.lock.acquire(blocking=False):
            raise ConflictError("Une opération d’étiquettes est en cours.")
        try:
            if not self.configuration["port"]:
                raise LabelError("Sélectionnez d’abord le port USB dans Configuration.")
            return self.runner("probe", copy.deepcopy(self.configuration))
        finally:
            self.lock.release()

    def print(self, item, body):
        previous = self.store.label_job(body.request_id)
        if previous:
            if (previous["spool_id"], previous["version"], previous["settings_revision"], previous["payload_hash"]) != (
                    item["id"], body.version, body.settings_revision, body.image_sha256):
                raise ConflictError("Cette demande d’impression correspond à une autre étiquette.")
            return previous
        if not self.lock.acquire(blocking=False):
            raise ConflictError("Une opération d’étiquettes est en cours. Aucune nouvelle impression n’a été lancée.")
        try:
            previous = self.store.label_job(body.request_id)
            if previous:
                if (previous["spool_id"], previous["version"], previous["settings_revision"], previous["payload_hash"]) != (
                        item["id"], body.version, body.settings_revision, body.image_sha256):
                    raise ConflictError("Cette demande d’impression correspond à une autre étiquette.")
                return previous
            configuration = copy.deepcopy(self.configuration)
            if not configuration["enabled"]:
                raise LabelError("Activez l’imprimante d’étiquettes dans Configuration avant d’imprimer.")
            if item["version"] != body.version or configuration["revision"] != body.settings_revision:
                raise ConflictError("La fiche ou le format a changé. Recharger l’aperçu avant d’imprimer.")
            label = render_label(item, configuration)
            if label["image_sha256"] != body.image_sha256:
                raise ConflictError("L’aperçu a changé. Recharger l’étiquette avant d’imprimer.")
            self.store.begin_label_job(body.request_id, item, configuration["revision"], body.image_sha256)
            try:
                result = self.runner("print", configuration, label["png"])
                if result.get("status") not in {"complete", "failed", "uncertain"}:
                    raise LabelError("État d’impression non reconnu.")
            except LabelError as exc:
                result = {"status": "failed", "detail": str(exc)}
            except Exception:
                result = {"status": "uncertain", "detail": "Résultat non confirmé. Vérifier l’étiquette avant de réimprimer."}
            return self.store.end_label_job(body.request_id, result["status"], result["detail"])
        finally:
            self.lock.release()
