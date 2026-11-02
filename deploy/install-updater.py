#!/usr/bin/env python3
"""Install the fixed public-release worker; no general sudo grant is created."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess

ROOT = Path('/')
FILES = ('/usr/local/lib/opt-station-updater/update-worker.py',
         '/usr/local/lib/opt-station-updater/bootstrap.py',
         '/usr/local/lib/opt-station-updater/install-station.py',
         '/usr/local/lib/opt-station-updater/install-files.py',
         '/etc/opt-station/updater.json', '/var/lib/opt-station-updater/info.json',
         '/etc/systemd/system/opt-station-update.service', '/etc/systemd/system/opt-station-update.path',
         '/etc/systemd/system/multi-user.target.wants/opt-station-update.service',
         '/etc/systemd/system/multi-user.target.wants/opt-station-update.path')


def configure(source, account, transaction, runner=subprocess.run, reset_recovery=False):
    base = ROOT / 'var/lib/opt-station-updater'
    base.mkdir(parents=True, exist_ok=True, mode=0o755)
    if base.is_symlink() or base.stat().st_uid != os.geteuid():
        raise ValueError('Le dossier du service de mise à jour doit appartenir au système.')
    base.chmod(0o755)
    incoming = base / 'incoming'
    incoming.mkdir(mode=0o700, exist_ok=True)
    if incoming.is_symlink(): raise ValueError('Dossier de demandes non reconnu.')
    os.chown(incoming, account.pw_uid, account.pw_gid); incoming.chmod(0o700)
    for name in ('update-worker.py', 'bootstrap.py', 'install-station.py', 'install-files.py'):
        transaction.write(ROOT / 'usr/local/lib/opt-station-updater' / name,
                          (source / 'deploy' / name).read_text(), mode=0o644)
    transaction.write(ROOT / 'etc/opt-station/updater.json', json.dumps({'user': account.pw_name}) + '\n')
    transaction.write(base / 'info.json', json.dumps({'protocol': 1, 'uid': account.pw_uid}) + '\n', mode=0o644)
    state = base / 'state.json'
    if reset_recovery and state.exists() and json.loads(state.read_bytes()).get('phase') == 'recovery_required':
        transaction.write(state, json.dumps({'phase':'idle','id':None,'tag':None,'percent':0,
                          'started_at':None,'finished_at':None}) + '\n', mode=0o644)
    transaction.write(ROOT / 'etc/systemd/system/opt-station-update.service', '''# Managed by OPT Station installer
[Unit]
Description=OPT Station verified public release installer
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I /usr/local/lib/opt-station-updater/update-worker.py
ExecStopPost=/usr/bin/python3 -I /usr/local/lib/opt-station-updater/update-worker.py --recover
WorkingDirectory=/
Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin
UMask=0077
TimeoutStartSec=45min
[Install]
WantedBy=multi-user.target
''', mode=0o644)
    transaction.write(ROOT / 'etc/systemd/system/opt-station-update.path', '''# Managed by OPT Station installer
[Unit]
Description=OPT Station update request
[Path]
PathExists=/var/lib/opt-station-updater/incoming/request.json
Unit=opt-station-update.service
[Install]
WantedBy=multi-user.target
''', mode=0o644)
    runner(['systemctl', 'daemon-reload'], check=True)
    runner(['systemctl', 'enable', 'opt-station-update.service'], check=True)
    runner(['systemctl', 'enable', '--now', 'opt-station-update.path'], check=True)


def main():
    parser = argparse.ArgumentParser(description='Activer une fois la mise à jour depuis OPT Station.')
    parser.add_argument('--user', default=os.getenv('SUDO_USER'))
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    if os.geteuid() != 0: parser.error('Cette installation initiale nécessite sudo sur le Pi.')
    account = pwd.getpwnam(args.user or '')
    if account.pw_uid == 0: parser.error('Indiquez le compte ordinaire de la station.')
    import importlib.util
    spec = importlib.util.spec_from_file_location('updater_installation', args.source / 'deploy/install-station.py')
    installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
    with installer.installation_lock():
        transaction = installer.Transaction(ROOT / 'var/lib/opt-station-install-backups' /
            ('before-updater-' + __import__('datetime').datetime.now().strftime('%Y%m%dT%H%M%S-%f')) / 'files', account)
        for path in FILES: transaction.capture(ROOT / path.lstrip('/'))
        try: configure(args.source, account, transaction)
        except BaseException:
            subprocess.run(['systemctl', 'stop', 'opt-station-update.path'], check=False)
            transaction.restore()
            subprocess.run(['systemctl', 'daemon-reload'], check=False)
            if (ROOT / 'etc/systemd/system/opt-station-update.path').exists():
                subprocess.run(['systemctl', 'start', 'opt-station-update.path'], check=False)
            raise
    subprocess.run(['systemctl', 'start', 'opt-station-update.service'], check=True)
    print('Mise à jour depuis l’application activée. Aucun mot de passe ne sera demandé pour les prochaines mises à jour.')


if __name__ == '__main__': main()
