#!/usr/bin/env python3
"""System-owned worker for one fixed public repository, independent of the UI.

Only a UUID, a release tag and a recent timestamp cross the request boundary.
Downloaded Python stays system-owned; only its venv is writable by the station.
Logs and recovery paths stay private, while progress contains no credentials.
"""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import pwd
import stat
import sys
from types import SimpleNamespace
import uuid
import time

BASE = Path('/var/lib/opt-station-updater')
LIB = Path('/usr/local/lib/opt-station-updater')
CONFIG = Path('/etc/opt-station/updater.json')
PHASES = {'checking': 3, 'downloading': 10, 'preparing': 20, 'dependencies': 30, 'python': 45,
          'backup': 60, 'activating': 70, 'https': 85, 'verifying': 95, 'complete': 100}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def write(path, record, mode=0o600):
    temporary = path.with_name('.' + path.name + '-' + str(uuid.uuid4()))
    try:
        with temporary.open('x') as output:
            os.fchmod(output.fileno(), mode)
            json.dump(record, output); output.write('\n'); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def request(account, now):
    path = BASE / 'incoming/request.json'
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != account.pw_uid or info.st_size > 1024:
            raise ValueError('Invalid update request file')
        raw = os.read(descriptor, 1025)
    finally:
        os.close(descriptor)
    body = json.loads(raw)
    if (not isinstance(body, dict) or set(body) != {'id', 'tag', 'requested_at'}
            or str(uuid.UUID(body['id'])) != body['id']
            or type(body['requested_at']) not in {int, float} or not math.isfinite(body['requested_at'])
            or not 0 <= now - body['requested_at'] <= 180):
        raise ValueError('Invalid or expired update request')
    return body


def readable_sources(source, account):
    for path in [source, *source.rglob('*')]:
        path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    venv = source / '.venv'; venv.mkdir(mode=0o700)
    os.chown(venv, account.pw_uid, account.pw_gid)


def perform(body, account, bootstrap, baseline, emit, fetch=None):
    fetch = fetch or bootstrap.fetch
    tag = body['tag']
    if bootstrap.version_key(tag) < bootstrap.version_key('v0.26.0'):
        raise ValueError('This release predates managed updates')
    stable = Path(account.pw_dir) / 'apps/openprinttag-station'
    old_source = stable.resolve(strict=True)
    old_version, old_key = baseline.version(old_source / 'pyproject.toml')
    # Installer and bootstrap share the same numeric ordering for final/rc.
    target_version = tag[1:].replace('-rc.', 'rc')
    probe = BASE / 'target-version.toml'
    probe.write_text('[project]\nversion=' + json.dumps(target_version) + '\n')
    try: newer = baseline.version(probe)[1] > old_key
    finally: probe.unlink(missing_ok=True)
    if not newer: raise ValueError('The requested version is not newer than the installed version')
    emit('checking')
    row = json.loads(fetch(bootstrap.API + '/tags/' + tag, 4 * 1024 * 1024))
    release = bootstrap.select_release([row], tag)
    if not release.get('published_at'): raise ValueError('Release is not published')
    name = f'opt-station-{tag}.tar.gz'
    asset = next(x for x in release['assets'] if x.get('name') == name)
    digest = asset.get('digest')
    import re
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('GitHub did not provide the archive digest')
    releases = BASE / 'releases'; releases.mkdir(exist_ok=True, mode=0o755); releases.chmod(0o755)
    folder = releases / body['id']; folder.mkdir(mode=0o755); folder.chmod(0o755)
    archive = folder / name
    emit('downloading')
    base = f'https://github.com/{bootstrap.REPOSITORY}/releases/download/{tag}/'
    with archive.open('xb') as output: fetch(base + name, bootstrap.MAX_ARCHIVE, target=output)
    actual = bootstrap.verify_checksum(archive, fetch(base + name + '.sha256', 1024), name, digest)
    source = folder / 'source'; source.mkdir(mode=0o755)
    bootstrap.extract_sources(archive, source, tag)
    # Import only from the root-owned, checksum-verified tree; never from home.
    module = load('verified_update_installer', source / 'deploy/install-station.py')
    if getattr(module, 'MANAGED_UPDATE_PROTOCOL', None) != 1:
        raise ValueError('The release does not support managed installation')
    readable_sources(source, account)
    args = SimpleNamespace(source=source, no_camera=False, no_kiosk=False,
                           archive_sha256=actual, managed_update=True)
    installer = module.Installer(args, account)
    emit('preparing')

    def progress(phase):
        if hasattr(installer, 'backup'):
            write(BASE / 'recovery.json', {'backup': str(installer.backup), 'previous_source': str(old_source),
                                          'new_source': str(source), 'id': body['id']})
        emit(phase)

    installer.report = progress
    try:
        # Allow the acknowledged HTTP request to release its operation guard.
        for attempt in range(30):
            readiness = baseline.read_json('http://127.0.0.1:8766/api/system/power')
            if not readiness.get('busy', True) and not readiness.get('pending'): break
            time.sleep(0.1)
        else: raise ValueError('The station is busy')
        installer.apply()
    except BaseException:
        # A rollback command alone is not proof that the previous app returned.
        try:
            state = baseline.read_json('http://127.0.0.1:8766/api/status')
            restored = stable.resolve() == old_source and state.get('version') == old_version
        except Exception:
            restored = False
        emit('failed' if restored else 'recovery_required')
        raise
    emit('complete')


def main(recover_only=False):
    if os.geteuid() != 0: raise SystemExit('System service required')
    os.umask(0o077)
    account = pwd.getpwnam(json.loads(CONFIG.read_bytes())['user'])
    if account.pw_uid == 0: raise ValueError('Station account required')
    bootstrap = load('owned_update_bootstrap', LIB / 'bootstrap.py')
    baseline = load('owned_update_installation', LIB / 'install-station.py')
    bootstrap.supported_platform()
    state_path = BASE / 'state.json'
    incoming = BASE / 'incoming/request.json'
    with (BASE / 'worker.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if recover_only or (not incoming.exists() and not incoming.is_symlink()):
            if state_path.exists():
                state = json.loads(state_path.read_bytes())
                if state.get('phase') in PHASES and state['phase'] != 'complete':
                    state.update(phase='recovery_required', finished_at=datetime.now(timezone.utc).isoformat())
                    write(state_path, state, 0o644)
            return
        state = {'id': None, 'tag': None, 'phase': 'checking', 'percent': 0,
                 'started_at': datetime.now(timezone.utc).isoformat(), 'finished_at': None}

        def emit(phase):
            state.update(phase=phase, percent=PHASES.get(phase, state['percent']))
            if phase in {'complete', 'failed', 'recovery_required'}:
                state['finished_at'] = datetime.now(timezone.utc).isoformat()
            write(state_path, state, 0o644)

        try:
            body = request(account, time.time())
            bootstrap.version_key(body['tag'])
            previous = json.loads(state_path.read_bytes()) if state_path.exists() else {}
            if previous.get('id') == body['id']:
                state = previous
                if state.get('phase') in PHASES and state['phase'] != 'complete': emit('recovery_required')
                incoming.unlink()
                return
            state.update(id=body['id'], tag=body['tag']); emit('checking')
            incoming.unlink()
            with (BASE / 'worker.log').open('w') as log:
                os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
                with baseline.installation_lock(): perform(body, account, bootstrap, baseline, emit)
        except BaseException:
            incoming.unlink(missing_ok=True)
            if state['phase'] not in {'failed', 'recovery_required'}: emit('failed')
            raise


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--recover']): raise SystemExit('Unsupported worker option')
    main(recover_only=sys.argv[1:] == ['--recover'])
