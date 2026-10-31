"""Pi-only capture process. Started and supervised by CameraScanner."""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def run(directory: Path, seconds: float):
    from picamera2 import Picamera2
    from PIL import Image
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

    def preview(gray):
        image = Image.fromarray(gray)
        image.thumbnail((960, 720))
        temporary = directory / "preview.next"
        image.save(temporary, format="JPEG", quality=80)
        os.replace(temporary, directory / "preview.jpg")

    try:
        status("starting", "Ouverture de la caméra…")
        with Picamera2(0) as camera:
            model = str(camera.camera_properties.get("Model", "Caméra Raspberry Pi"))
            config = camera.create_still_configuration(
                main={"size": (2592, 1944), "format": "YUV420"}, buffer_count=3,
                controls={"FrameDurationLimits": (100000, 100000)})
            camera.configure(config)
            camera.start()
            try:
                time.sleep(1.5)
                deadline = time.monotonic() + seconds
                last_preview = 0
                status("scanning", "Présentez le QR et ajustez la distance jusqu’à obtenir une image nette.")
                while time.monotonic() < deadline:
                    request = camera.capture_request()
                    try:
                        gray = request.make_array("main")[:1944, :2592].copy()
                    finally:
                        request.release()
                    frames += 1
                    readings = zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormat.QRCode,
                                                     text_mode=zxingcpp.TextMode.Plain)
                    codes = []
                    seen = set()
                    for item in readings:
                        if item.text not in seen:
                            if not item.text or len(item.text) > 8192:
                                preview(gray)
                                status("error", "Ce QR dépasse le format texte pris en charge. Utilisez un autre code.")
                                return
                            seen.add(item.text)
                            codes.append({"text": item.text, "format": "QR Code"})
                            if len(codes) == 4:
                                break
                    now = time.monotonic()
                    if codes or now - last_preview >= 0.4:
                        preview(gray)
                        last_preview = now
                        status("found" if codes else "scanning",
                               "QR détecté. Vérifiez son contenu avant de l’utiliser." if codes else "Présentez le QR et ajustez la distance jusqu’à obtenir une image nette.", codes)
                    if codes:
                        return
                    time.sleep(0.12)
                status("timeout", "Aucun QR lu pendant cet essai. Ajustez la distance et l’éclairage, puis réessayez.")
            finally:
                camera.stop()
    except Exception:
        traceback.print_exc()
        status("error", "La caméra est indisponible. Vérifiez son raccordement et fermez les autres applications qui l’utilisent.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--list"]:
        from picamera2 import Picamera2
        print(json.dumps({"cameras": [{"model": str(info.get("Model", "Caméra Raspberry Pi")), "index": info.get("Num", index)}
                                      for index, info in enumerate(Picamera2.global_camera_info())]}))
    else:
        run(Path(sys.argv[1]), float(sys.argv[2]))
