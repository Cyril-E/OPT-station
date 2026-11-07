#!/usr/bin/env python3
"""Prepare and check the local Matter controller with the station account."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

NODE_VERSION = "24.22.2"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-linux-arm64.tar.xz"
NODE_SHA256 = "eb187837a2230d4047161ac0be008584e16b46f726e9c9490ee35dc6b17d9ba8"
DEPLOY = Path(__file__).resolve().parent


def check_runtime(runtime):
    node = runtime / "node/bin/node"
    server = runtime / "node_modules/.bin/matter-server"
    node_version = subprocess.check_output([node, "--version"], text=True, timeout=15).strip()
    server_version = subprocess.check_output([node, server, "--version"], text=True, timeout=15).strip()
    manifest = json.loads((DEPLOY / "matter/package.json").read_text())
    if node_version != f"v{NODE_VERSION}" or server_version != manifest["dependencies"]["matter-server"]:
        raise ValueError(f"Versions de Node.js ou Matter Server inattendues dans {runtime}.")
    print(f"Node.js {node_version} et Matter Server {server_version} prêts.", flush=True)


def prepare(runtime):
    if runtime.exists() or runtime.is_symlink():
        check_runtime(runtime)
        return
    runtime.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".opt-matter-", dir=runtime.parent) as temporary:
        work = Path(temporary)
        archive = work / NODE_ARCHIVE
        subprocess.run(["/usr/bin/curl", "--disable", "--fail", "--silent", "--show-error", "--location",
                        "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2", "--retry", "2",
                        "--connect-timeout", "15", "--max-time", "120", "--max-filesize", str(64 * 1024**2),
                        "--output", archive, f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}"], check=True)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != NODE_SHA256:
                raise ValueError("Empreinte SHA-256 de Node.js incorrecte.")
        with tarfile.open(archive, "r:xz") as package:
            package.extractall(work, filter="data")
        staged = work / "runtime"
        staged.mkdir(mode=0o700)
        (work / f"node-v{NODE_VERSION}-linux-arm64").rename(staged / "node")
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(DEPLOY / "matter" / name, staged / name)
        bin_dir = staged / "node/bin"
        env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin",
               "npm_config_userconfig": str(work / "user.npmrc"),
               "npm_config_globalconfig": str(work / "global.npmrc")}
        subprocess.run([bin_dir / "npm", "ci", "--ignore-scripts", "--engine-strict",
                        "--no-audit", "--no-fund", "--cache", work / "npm-cache",
                        "--registry", "https://registry.npmjs.org"],
                       cwd=staged, env=env, check=True, timeout=300)
        check_runtime(staged)
        staged.rename(runtime)


def verify():
    # The verified release contains the same client used by the station.
    sys.path.insert(0, str(DEPLOY.parent))
    from openprinttag_app.matter import MatterControl, MatterError, socket_path

    controller = MatterControl(".", socket_path(), None)
    deadline = time.monotonic() + 30
    while True:
        try:
            controller.discovery()
        except MatterError as exc:
            if time.monotonic() >= deadline:
                raise ValueError(f"Le contrôleur Matter ne répond pas. Vérifiez son service. {exc}") from exc
            time.sleep(1)
        else:
            print("Le contrôleur Matter répond sur sa socket locale.", flush=True)
            return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify"))
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Utilisez le compte ordinaire de la station.")
    try:
        if args.action == "prepare":
            prepare(Path.home() / ".local/opt-station-matter-runtime")
        else:
            verify()
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        sys.exit(f"Installation Matter interrompue. {exc}")
