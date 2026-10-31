#!/usr/bin/env python3
"""Unprivileged release discovery, integrity check and safe source extraction.

Only standard-library modules: a stock Raspberry Pi OS image can run this file.
The release's installer is run with sudo only after all validation succeeds.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "Cyril-E/OPT-station"
API = f"https://api.github.com/repos/{REPOSITORY}/releases"
MINIMUM = (0, 17, 0, 1, 0)
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXTRACTED = 256 * 1024 * 1024
REQUIRED = ("pyproject.toml", "requirements.lock", "requirements-camera.lock", "deploy/bootstrap.py", "deploy/install-station.py",
            "deploy/install-https.py", "deploy/openprinttag.service", "deploy/openprinttag-display.service",
            "deploy/openprinttag.desktop.in", "deploy/openprinttag-display.py", "deploy/opt-station-https.service",
            "openprinttag_app/__init__.py", "openprinttag_app/__main__.py", "openprinttag_app/app.py",
            "openprinttag_app/https.py", "openprinttag_app/installation.py")
PI_MODEL = Path("/proc/device-tree/model")


def version_key(tag):
    match = re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-rc\.(0|[1-9][0-9]*))?", tag or "")
    if not match:
        raise ValueError("Version non reconnue (exemple : v0.17.0).")
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), 1 if rc is None else 0, int(rc or 0)


def supported_platform():
    if sys.platform != "linux" or platform.machine() not in {"aarch64", "arm64"}:
        raise ValueError("Utilisez Raspberry Pi OS 64 bits Trixie sur un Raspberry Pi.")
    release = platform.freedesktop_os_release()
    model = PI_MODEL
    if (release.get("VERSION_CODENAME") != "trixie" or not model.is_file()
            or not model.read_bytes().startswith(b"Raspberry Pi")):
        raise ValueError("Ce parcours prend en charge Raspberry Pi OS 64 bits Trixie uniquement.")


def allowed_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in {
        "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
    } and not parsed.username and not parsed.password and parsed.port in {None, 443})


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError("Redirection du téléchargement non autorisée.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit, target=None):
    if not allowed_url(url):
        raise ValueError("Adresse de téléchargement non autorisée.")
    request = Request(url, headers={"User-Agent": "OPT-Station-installer", "Accept": "application/vnd.github+json"})
    result, size = bytearray(), 0
    deadline = time.monotonic() + 180
    with build_opener(Redirects()).open(request, timeout=30) as response:
        if int(response.headers.get("Content-Length", "0")) > limit:
            raise ValueError("Téléchargement trop volumineux.")
        while block := response.read(65536):
            size += len(block)
            if size > limit or time.monotonic() > deadline:
                raise ValueError("Téléchargement trop volumineux ou trop lent.")
            if target:
                target.write(block)
            else:
                result.extend(block)
    return bytes(result)


def select_release(rows, requested=None):
    if not isinstance(rows, list):
        raise ValueError("Réponse GitHub non reconnue.")
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or row.get("draft"):
            continue
        tag = row.get("tag_name")
        try:
            key = version_key(tag)
        except (ValueError, TypeError):
            continue
        if key < MINIMUM or (requested and tag != requested):
            continue
        assets = row.get("assets", [])
        names = [a.get("name") for a in assets if isinstance(a, dict)]
        filename = f"opt-station-{tag}.tar.gz"
        if names.count(filename) == names.count(filename + ".sha256") == 1:
            candidates.append((key, row))
    if not candidates:
        raise ValueError("Aucune release installable trouvée (v0.17.0 ou ultérieure, avec archive et SHA-256).")
    # Releases currently include prereleases; /releases/latest would omit them.
    return max(candidates, key=lambda item: item[0])[1]


def verify_checksum(archive, raw, filename, digest=None):
    text = raw.decode("ascii").strip()
    match = re.fullmatch(r"([a-fA-F0-9]{64})[ \t]+\*?" + re.escape(filename), text)
    if not match:
        raise ValueError("Le fichier SHA-256 doit désigner exactement l’archive téléchargée.")
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != match[1].lower() or (digest is not None and digest != "sha256:" + actual):
        raise ValueError("SHA-256 incorrect : l’archive ne sera pas exécutée.")
    return actual


def extract_sources(archive, destination, tag):
    """No extractall: reject links, devices, duplicates and traversal before writing."""
    with tarfile.open(archive, "r:gz") as package:
        members, expanded = [], 0
        seen = set()
        for member in package:
            members.append(member)
            expanded += member.size
            if len(members) > 10000 or expanded > MAX_EXTRACTED or member.size < 0:
                raise ValueError("Archive décompressée trop volumineuse.")
            path = PurePosixPath(member.name)
            if (not member.name or path.is_absolute() or ".." in path.parts or "\\" in member.name
                    or any(ord(c) < 32 for c in member.name) or path.as_posix() != member.name.rstrip("/")
                    or not path.parts or path.parts[0] in {".git", ".venv", ".agents", ".codex", "var"}
                    or re.fullmatch(r"\.git [0-9]+", path.parts[0])
                    or path.as_posix() in seen
                    or not (member.isfile() or member.isdir())):
                raise ValueError("Archive non sûre ou chemin en double.")
            seen.add(path.as_posix())
        for name in REQUIRED:
            if not any(member.name == name and member.isfile() for member in members):
                raise ValueError(f"Archive incomplète : {name}")
        for member in members:
            path = destination / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with package.extractfile(member) as incoming, path.open("xb") as output:
                    shutil.copyfileobj(incoming, output)
                path.chmod(0o700 if member.mode & 0o111 else 0o600)
    version = tomllib.loads((destination / "pyproject.toml").read_text())["project"]["version"]
    expected = tag[1:].replace("-rc.", "rc")
    if version != expected:
        raise ValueError("La version des sources ne correspond pas à la release.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Installer la dernière release d’OPT Station, sans compte GitHub.")
    parser.add_argument("--version", help="Version publiée précise (exemple : v0.17.0)")
    parser.add_argument("--no-kiosk", action="store_true", help="Installation sans écran, compatible Raspberry Pi OS Lite")
    parser.add_argument("--no-camera", action="store_true", help="Ne pas activer la caméra QR")
    parser.add_argument("--dry-run", action="store_true", help="Vérifier la release et afficher le plan sans installation")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("Lancez la commande avec le compte ordinaire du Pi, sans sudo.")
    supported_platform()
    if args.version and version_key(args.version) < MINIMUM:
        parser.error("Cette version ne contient pas encore l’installateur complet.")
    endpoint = API + ("/tags/" + args.version if args.version else "?per_page=100")
    rows = json.loads(fetch(endpoint, 4 * 1024 * 1024))
    release = select_release([rows] if args.version else rows, args.version)
    tag = release["tag_name"]
    filename = f"opt-station-{tag}.tar.gz"
    asset = next(a for a in release["assets"] if a.get("name") == filename)
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    with tempfile.TemporaryDirectory(prefix="opt-station-download-") as temporary:
        folder = Path(temporary)
        archive = folder / filename
        print(f"Téléchargement de {tag} et vérification SHA-256…", flush=True)
        with archive.open("wb") as output:
            fetch(base + filename, MAX_ARCHIVE, target=output)
        digest = verify_checksum(archive, fetch(base + filename + ".sha256", 1024), filename, asset.get("digest"))
        extracted = folder / "source"
        extracted.mkdir(mode=0o700)
        extract_sources(archive, extracted, tag)
        source = extracted
        if not args.dry_run:
            apps = home / "apps"
            apps.mkdir(mode=0o700, exist_ok=True)
            source = Path(tempfile.mkdtemp(prefix=f"opt-station-{tag}-{digest[:10]}-", dir=apps))
            # The temporary download may be on a different filesystem.
            shutil.copytree(extracted, source, dirs_exist_ok=True)
        arguments = ["python3", str(source / "deploy/install-station.py"), "--user", pwd.getpwuid(os.getuid()).pw_name,
                     "--source", str(source), "--archive-sha256", digest]
        for flag in ("no_kiosk", "no_camera", "dry_run"):
            if getattr(args, flag):
                arguments.append("--" + flag.replace("_", "-"))
        if not args.dry_run:
            print("Installation système : sudo peut demander le mot de passe dans ce terminal.", flush=True)
            arguments.insert(0, "sudo")
        subprocess.run(arguments, check=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"Installation interrompue : {exc}", file=sys.stderr)
        sys.exit(1)
