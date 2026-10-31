"""Start the local kiosk after the desktop and OpenPrintTag are ready."""
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


URL = "http://127.0.0.1:8765/"


def connection():
    path = os.getenv("OPENPRINTTAG_HTTPS_CONFIG")
    if not path:
        return URL, None
    record = json.loads(Path(path).read_text())
    # The kiosk always connects through loopback, so it retains local rights.
    if record.get("kiosk_url") != "https://localhost":
        raise ValueError("Adresse HTTPS locale invalide.")
    return record["kiosk_url"] + "/", ssl.create_default_context(cafile=record["ca_cert"])


def start_from_desktop():
    # The XDG autostart process has the new session's actual display socket.
    names = [name for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP")
             if os.environ.get(name)]
    if names:
        subprocess.run(["systemctl", "--user", "import-environment", *names], check=True)
    subprocess.run(["systemctl", "--user", "start", "openprinttag-display.service"], check=True)


def display():
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        raise SystemExit("La session graphique n’est pas encore disponible.")
    deadline = time.monotonic() + 90
    while True:
        try:
            url, context = connection()
            with urlopen(url + "api/status", timeout=2, context=context) as response:
                status = json.load(response)
            if status.get("version") and status.get("mode") in {"simulation", "hardware"}:
                break
        except (OSError, URLError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise SystemExit("OPT Station n’a pas répondu pendant le démarrage.")
        time.sleep(0.5)
    os.environ["MOZ_ENABLE_WAYLAND"] = "1" if os.environ.get("WAYLAND_DISPLAY") else "0"
    os.execv("/usr/bin/firefox", ["firefox", "--kiosk", url])


if __name__ == "__main__":
    if sys.argv[1:] == ["--session-start"]:
        start_from_desktop()
    elif not sys.argv[1:]:
        display()
    else:
        raise SystemExit("Option de lancement inconnue.")
