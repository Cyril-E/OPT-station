"""Unprivileged request/status interface to the installed system updater.

The web process never runs sudo or accepts a command, URL or source path.
The root worker independently fetches and verifies the selected public release.
"""
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid

from .updates import DEFAULT_REPOSITORY

DIRECTORY = Path('/var/lib/opt-station-updater')
PENDING = {'queued', 'checking', 'downloading', 'preparing', 'dependencies', 'python', 'backup', 'activating', 'https', 'verifying'}
MESSAGES = {
    'idle': 'La mise à jour peut être lancée depuis cette application.',
    'queued': 'Mise à jour demandée. Attente du service système…',
    'checking': 'Vérification de la version publiée…',
    'downloading': 'Téléchargement et vérification de l’archive…',
    'preparing': 'Préparation de la nouvelle version…',
    'dependencies': 'Préparation des dépendances système…',
    'python': 'Préparation des dépendances de l’application…',
    'backup': 'Sauvegarde de la station avant la mise à jour…',
    'activating': 'Installation de la nouvelle version. L’interface va se reconnecter…',
    'https': 'Vérification du service HTTPS…',
    'verifying': 'Vérification de la nouvelle version…',
    'complete': 'Mise à jour terminée. La station est prête.',
    'failed': 'La mise à jour a échoué. La version précédente est conservée ou restaurée. Consultez le journal système avant de réessayer.',
    'recovery_required': 'La mise à jour a été interrompue ou sa restauration n’a pas été confirmée. Conservez la sauvegarde et consultez le journal système avant de reprendre.',
}


class InstallError(ValueError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


class UpdateInstaller:
    def __init__(self, enabled=False, directory=DIRECTORY, clock=time.time):
        self.directory, self.enabled, self.clock = Path(directory), enabled, clock
        self.lock = threading.RLock()

    def supported(self):
        try:
            info = self.directory / 'info.json'
            metadata = info.stat()
            record = json.loads(info.read_bytes())
            incoming = self.directory / 'incoming'
            return bool(self.enabled and metadata.st_uid == 0 and not metadata.st_mode & 0o022
                        and record == {'protocol': 1, 'uid': os.getuid()}
                        and incoming.is_dir() and incoming.stat().st_uid == os.getuid())
        except (OSError, ValueError, TypeError):
            return False

    def snapshot(self):
        result = {'supported': self.supported(), 'phase': 'idle', 'pending': False, 'id': None,
                  'tag': None, 'percent': 0, 'started_at': None, 'finished_at': None}
        try:
            record = json.loads((self.directory / 'state.json').read_bytes())
            if (record.get('phase') in MESSAGES and type(record.get('percent')) is int
                    and 0 <= record['percent'] <= 100):
                result.update({key: record.get(key) for key in result if key not in {'supported', 'pending'}})
        except (OSError, ValueError, TypeError, KeyError):
            pass
        try:
            request = self.directory / 'incoming/request.json'
            if request.is_file():
                record = json.loads(request.read_bytes())
                result.update(id=record['id'], tag=record['tag'], phase='queued', percent=0)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        result['pending'] = result['phase'] in PENDING
        result['message'] = (MESSAGES[result['phase']] if result['supported'] else
                             'Le service de mise à jour doit être installé une fois sur le Pi. Voir le guide de mise à jour.')
        return result

    def pending(self):
        return self.snapshot()['pending']

    def start(self, monitor, tag, revision, busy=lambda: False):
        with self.lock, monitor.lock:
            if not self.supported():
                raise InstallError(self.snapshot()['message'], 503)
            if self.snapshot()['phase'] == 'recovery_required':
                raise InstallError(MESSAGES['recovery_required'])
            if self.pending() or busy():
                raise InstallError('Une opération est en cours. Terminez-la avant de lancer la mise à jour.')
            status = monitor.snapshot()
            if (revision != status['revision'] or not status['enabled'] or status['checking']
                    or status['stale'] or status['error_code'] or not status['update_available']
                    or status['repository'].casefold() != DEFAULT_REPOSITORY.casefold()
                    or not status['latest'] or tag != status['latest']['tag']
                    or not re.fullmatch(r'v\d+\.\d+\.\d+(?:-rc\.\d+)?', tag)):
                raise InstallError('La version proposée a changé ou n’est pas installable. Vérifiez à nouveau les mises à jour.')
            incoming = self.directory / 'incoming'
            record = {'id': str(uuid.uuid4()), 'tag': tag, 'requested_at': self.clock()}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=incoming, delete=False) as stream:
                    temporary = Path(stream.name)
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(json.dumps(record).encode())
                    stream.flush(); os.fsync(stream.fileno())
                # Atomic create without replacing another process's request.
                os.link(temporary, incoming / 'request.json')
                descriptor = os.open(incoming, os.O_RDONLY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
            except FileExistsError:
                raise InstallError('Une mise à jour est déjà demandée. Attendez son résultat.') from None
            except OSError:
                raise InstallError('La demande de mise à jour n’a pas pu être enregistrée.', 503) from None
            finally:
                if temporary: temporary.unlink(missing_ok=True)
            return self.snapshot()
