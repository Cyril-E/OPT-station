#!/usr/bin/env python3
"""Build the complete, flat release archive consumed by the public installer.

Only files from a Git commit are packaged, never untracked files or history.
This command does not publish anything.
"""
import argparse
import gzip
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent


def build(raw, output):
    spec = importlib.util.spec_from_file_location("release_bootstrap", ROOT / "deploy/bootstrap.py")
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        version = tomllib.loads(archive.extractfile("pyproject.toml").read().decode())["project"]["version"]
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:rc\d+)?", version):
            raise ValueError("Finalisez la version avant de construire une release.")
        tag = "v" + re.sub(r"rc(\d+)$", r"-rc.\1", version)
        filename = f"opt-station-{tag}.tar.gz"
        initialized = archive.extractfile("openprinttag_app/__init__.py").read().decode()
        if f'__version__ = "{version}"' not in initialized:
            raise ValueError("Les deux versions de l’application doivent correspondre.")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / filename
    checksum = output / (filename + ".sha256")
    if destination.exists() or checksum.exists():
        raise ValueError("Les fichiers de cette release existent déjà; choisir un dossier neuf.")
    with tempfile.TemporaryDirectory(prefix="opt-release-check-", dir=output) as temporary:
        folder = Path(temporary)
        compressed = folder / filename
        with compressed.open("wb") as target, gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as stream:
            stream.write(raw)
        extracted = folder / "sources"; extracted.mkdir()
        bootstrap.extract_sources(compressed, extracted, tag)
        with compressed.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        os.replace(compressed, destination)
        checksum.write_text(digest + "  " + filename + "\n")
    return destination, checksum


def main():
    parser = argparse.ArgumentParser(description="Préparer les deux assets GitHub d’une release d’OPT Station.")
    parser.add_argument("--ref", default="HEAD", help="Commit ou tag Git à publier")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", args.ref):
        parser.error("Indiquez un nom de branche, un tag ou un identifiant de commit.")
    commit = subprocess.check_output(["git", "rev-parse", "--verify", args.ref + "^{commit}"], cwd=ROOT, text=True).strip()
    raw = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=ROOT)
    for path in build(raw, args.output.resolve()):
        print(path)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Archive non publiée : {exc}")
