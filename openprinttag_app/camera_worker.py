"""Pi-only capture process. Started and supervised by CameraScanner."""
import json
import os
from pathlib import Path
import sys
import time
import traceback

from .camera import image_controls, validate_image_controls


def configure_image(camera, directory, previous=None):
    """Apply persisted image controls only to their matching sensor."""
    path = directory / "controls.json"
    record = json.loads(path.read_text()) if path.exists() else {"revision": 0, "model": None, "controls": {}}
    signature = json.dumps(record, sort_keys=True)
    if signature == previous:
        return previous
    supported = image_controls(camera.camera_controls)
    values = {item["name"]: item["default"] for item in supported}
    if record.get("model") == camera.camera_properties.get("Model"):
        values.update(validate_image_controls(record["controls"], supported))
    if values:
        camera.set_controls(values)
    return signature


def run(directory: Path, seconds: float, *, preview_only=False):
    from picamera2 import Picamera2
    from PIL import Image
    import numpy as np
    if not preview_only:
        import zxingcpp

    frames = 0
    model = ""
    deadline = None

    def status(state, message, codes=None):
        temporary = directory / "status.next"
        temporary.write_text(json.dumps({"state": state, "message": message, "frames": frames,
                                        "remaining_seconds": max(0, round(deadline - time.monotonic())) if deadline else round(seconds),
                                        "model": model, "codes": codes or []}, ensure_ascii=False))
        os.replace(temporary, directory / "status.json")

    def preview(frame):
        image = frame.copy()
        image.thumbnail((960, 720))
        temporary = directory / "preview.next"
        image.save(temporary, format="JPEG", quality=80)
        os.replace(temporary, directory / "preview.jpg")

    try:
        status("starting", "Ouverture de la caméra…")
        with Picamera2(0) as camera:
            model = str(camera.camera_properties.get("Model", "Caméra Raspberry Pi"))
            config = camera.create_still_configuration(
                main={"size": (2592, 1944), "format": "RGB888"}, buffer_count=3,
                controls={"FrameDurationLimits": (100000, 100000)})
            camera.configure(config)
            applied = configure_image(camera, directory)
            camera.start()
            try:
                time.sleep(1.5)
                deadline = time.monotonic() + seconds
                last_preview = 0
                status("scanning", "Aperçu caméra en direct." if preview_only else "Présentez le QR et ajustez la distance jusqu’à obtenir une image nette.")
                while time.monotonic() < deadline:
                    applied = configure_image(camera, directory, applied)
                    request = camera.capture_request()
                    try:
                        frame = request.make_image("main").copy()
                    finally:
                        request.release()
                    frames += 1
                    readings = [] if preview_only else zxingcpp.read_barcodes(
                        np.asarray(frame.convert("L")), formats=zxingcpp.BarcodeFormat.QRCode,
                        text_mode=zxingcpp.TextMode.Plain)
                    codes = []
                    seen = set()
                    for item in readings:
                        if item.text not in seen:
                            if not item.text or len(item.text) > 8192:
                                preview(frame)
                                status("error", "Ce QR dépasse le format texte pris en charge. Utilisez un autre code.")
                                return
                            seen.add(item.text)
                            codes.append({"text": item.text, "format": "QR Code"})
                            if len(codes) == 4:
                                break
                    now = time.monotonic()
                    if codes or now - last_preview >= 0.4:
                        preview(frame)
                        last_preview = now
                        status("found" if codes else "scanning",
                               "QR détecté. Vérifiez son contenu avant de l’utiliser." if codes else
                               "Aperçu caméra en direct." if preview_only else
                               "Présentez le QR et ajustez la distance jusqu’à obtenir une image nette.", codes)
                    if codes:
                        return
                    time.sleep(0.12)
                status("timeout", "Aperçu terminé. Relancez-le pour continuer." if preview_only else
                       "Aucun QR lu pendant cet essai. Ajustez la distance et l’éclairage, puis réessayez.")
            finally:
                camera.stop()
    except Exception:
        traceback.print_exc()
        status("error", "La caméra est indisponible. Vérifiez son raccordement et fermez les autres applications qui l’utilisent.")


def photograph(directory):
    from picamera2 import Picamera2
    def status(state, message):
        temporary = directory / "status.next"
        temporary.write_text(json.dumps({"state": state, "message": message, "frames": 1 if state == "found" else 0,
                                        "codes": [], "model": model}))
        os.replace(temporary, directory / "status.json")
    model = ""
    try:
        status("starting", "Prise de photo…")
        with Picamera2(0) as camera:
            model = str(camera.camera_properties.get("Model", "Caméra Raspberry Pi"))
            camera.configure(camera.create_still_configuration(main={"size": (2592, 1944), "format": "RGB888"}))
            configure_image(camera, directory)
            camera.start(); time.sleep(2)
            image = camera.capture_image("main")
            image.save(directory / "photo.jpg", format="JPEG", quality=90)
            image.thumbnail((960, 720)); image.save(directory / "preview.jpg", format="JPEG", quality=85)
        status("found", "Photo prête. Vérifiez son cadrage avant l’analyse.")
    except Exception:
        traceback.print_exc()
        status("error", "La photo n’a pas pu être prise. Vérifiez la caméra puis réessayez.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--list"]:
        from picamera2 import Picamera2
        print(json.dumps({"cameras": [{"model": str(info.get("Model", "Caméra Raspberry Pi")), "index": info.get("Num", index)}
                                      for index, info in enumerate(Picamera2.global_camera_info())]}))
    elif sys.argv[1:] == ["--controls"]:
        from picamera2 import Picamera2
        with Picamera2(0) as camera:
            print(json.dumps({"model": str(camera.camera_properties["Model"]),
                              "controls": image_controls(camera.camera_controls)}))
    elif len(sys.argv) == 3 and sys.argv[1] == "--photo":
        photograph(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--preview":
        run(Path(sys.argv[2]), float(sys.argv[3]), preview_only=True)
    else:
        run(Path(sys.argv[1]), float(sys.argv[2]))
