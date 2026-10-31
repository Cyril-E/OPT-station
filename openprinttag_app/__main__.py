import argparse
import os
import socket

from . import APP_NAME
from .network import lan_host
from .https import HTTPSConfiguration


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — lecteur NFC et inventaire")
    parser.add_argument("--host", help="Adresse d’écoute; 127.0.0.1 par défaut, 0.0.0.0 avec --lan")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--mode", choices=["simulation", "hardware"], default=os.getenv("OPENPRINTTAG_MODE", "simulation"))
    parser.add_argument("--data-dir", help="Répertoire de données persistantes")
    parser.add_argument("--allowed-host", action="append", default=[], help="Nom/IP supplémentaire autorisé pour l’accès réseau, sans port")
    parser.add_argument("--camera", action="store_true", help="Activer la capture QR avec la caméra du Raspberry Pi")
    parser.add_argument("--https-config", default=os.getenv("OPENPRINTTAG_HTTPS_CONFIG"), help="Configuration de la passerelle HTTPS locale")
    parser.add_argument("--lan", action="store_true", default=os.getenv("OPENPRINTTAG_NETWORK", "0").lower() in {"1", "true", "yes"},
                        help="Accès réseau configurable : inventaire et modèles, ou accès complet persistant sans code")
    args = parser.parse_args()
    try:
        https = HTTPSConfiguration.load(args.https_config)
    except ValueError as exc:
        parser.error(str(exc))
    if https.url:
        if args.host and args.host != "127.0.0.1":
            parser.error("Avec HTTPS, le serveur interne doit écouter sur 127.0.0.1 uniquement.")
        args.host, args.lan = "127.0.0.1", True
        os.environ["OPENPRINTTAG_HTTPS_CONFIG"] = str(args.https_config)
    args.host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    os.environ["OPENPRINTTAG_MODE"] = args.mode
    if args.camera:
        os.environ["OPENPRINTTAG_CAMERA"] = "1"
    if args.data_dir:
        os.environ["OPENPRINTTAG_DATA_DIR"] = args.data_dir
    hosts = {"127.0.0.1", "localhost", "[::1]", *args.allowed_host}
    hosts.update(https.hosts)
    os.environ["OPENPRINTTAG_NETWORK"] = "1" if args.lan else "0"
    if args.lan:
        address = next((host for host in args.allowed_host if host not in {"127.0.0.1", "localhost", "[::1]"}), None) or lan_host()
        hosts.update({address, socket.gethostname(), socket.gethostname().split(".")[0] + ".local"})
        url_host = f"[{address}]" if ":" in address and not address.startswith("[") else address
        os.environ["OPENPRINTTAG_NETWORK_URL"] = https.url or f"http://{url_host}:{args.port}"
        print(f"Accès réseau : {os.environ['OPENPRINTTAG_NETWORK_URL']} — partage réglable dans Configuration")
    else:
        os.environ.pop("OPENPRINTTAG_NETWORK_URL", None)
    if args.host not in {"0.0.0.0", "::"}:
        hosts.add(args.host)
    os.environ["OPENPRINTTAG_ALLOWED_HOSTS"] = ",".join(sorted(hosts))
    print(f"{APP_NAME} — mode {args.mode.upper()} — http://{args.host}:{args.port}")
    if args.mode == "simulation":
        print("Les tags et les écritures sont simulés. La base d’essai est distincte du futur stock réel.")
    import uvicorn
    # Les flux d'événements ouverts ne doivent pas retenir indéfiniment un arrêt du service.
    uvicorn.run("openprinttag_app.app:create_app", factory=True, host=args.host, port=args.port,
                proxy_headers=False, workers=1, timeout_graceful_shutdown=20)


if __name__ == "__main__":
    main()
