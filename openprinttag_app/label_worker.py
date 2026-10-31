"""One short-lived USB process per detection or explicit single-label job."""
import base64
import io
import json
import sys

from PIL import Image

from .labels import validate_settings
from .niimbot import Niimbot


def main():
    printer = None
    action = None
    try:
        request = json.loads(sys.stdin.read(1_000_001))
        action = request["action"]
        if action not in {"probe", "print"}:
            raise ValueError("Action inconnue.")
        config = validate_settings(request["configuration"])
        printer = Niimbot(config["port"])
        if action == "probe":
            result = {"status": "identified", **printer.identify()}
        else:
            image = Image.open(io.BytesIO(base64.b64decode(request["png"], validate=True)))
            if image.width > 576 or image.height > 1200 or image.mode != "1":
                raise ValueError("Format d’étiquette incorrect.")
            result = printer.print_image(image, config["model"], config["density"])
    except Exception as exc:
        result = {"status": "uncertain" if printer and printer.print_started else "failed", "detail": str(exc)[:300] or "Communication USB interrompue."}
    finally:
        if printer:
            printer.close()
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
