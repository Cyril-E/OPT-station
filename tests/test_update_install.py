"""In-app updates: narrow request boundary, permissions, concurrency and recovery."""
import json
import os
from pathlib import Path
import time
import uuid

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.update_install import InstallError, UpdateInstaller
from openprinttag_app.updates import ReleaseMonitor, DEFAULT_REPOSITORY


def offered(monitor):
    monitor.configuration.record.update(enabled=True, revision=4, repository=DEFAULT_REPOSITORY)
    monitor.state = {'phase': 'ok', 'latest': {'tag': 'v999.0.0', 'version': '999.0.0', 'name': 'Release',
        'url': 'https://github.com/Cyril-E/OPT-station/releases/tag/v999.0.0',
        'published_at': '2026-11-02T08:00:00Z', 'prerelease': True, 'notes': 'Release notes'}}


@pytest.fixture
def updater(tmp_path):
    base = tmp_path / 'system-updater'; (base / 'incoming').mkdir(parents=True)
    backend = UpdateInstaller(directory=base, enabled=True)
    backend.supported = lambda: True
    return backend


def test_request_is_atomic_private_and_contains_no_executable_or_url(updater, tmp_path):
    monitor = ReleaseMonitor(tmp_path); offered(monitor)
    result = updater.start(monitor, 'v999.0.0', 4)
    assert result['pending'] and result['phase'] == 'queued'
    path = updater.directory / 'incoming/request.json'
    record = json.loads(path.read_bytes())
    assert set(record) == {'id', 'tag', 'requested_at'} and str(uuid.UUID(record['id'])) == record['id']
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob('tmp*'))
    with pytest.raises(InstallError): updater.start(monitor, 'v999.0.0', 4)
    assert json.loads(path.read_bytes()) == record


@pytest.mark.parametrize('change', ['revision', 'repository', 'stale', 'disabled', 'not_newer', 'busy', 'tag'])
def test_changed_or_unavailable_releases_never_create_a_request(updater, tmp_path, change):
    monitor = ReleaseMonitor(tmp_path); offered(monitor)
    revision, tag = 4, 'v999.0.0'
    if change == 'revision': revision = 3
    if change == 'repository': monitor.configuration.record['repository'] = 'other/project'
    if change == 'stale': monitor.state['error'] = 'network'
    if change == 'disabled': monitor.configuration.record['enabled'] = False
    if change == 'not_newer': monitor.installed = '999.0.0'
    if change == 'tag': tag = 'v999.0.1'
    with pytest.raises(InstallError): updater.start(monitor, tag, revision, busy=lambda: change == 'busy')
    assert not (updater.directory / 'incoming/request.json').exists()


def test_missing_system_service_is_not_replaced_by_a_sudo_command(tmp_path):
    backend = UpdateInstaller(directory=tmp_path)
    monitor = ReleaseMonitor(tmp_path); offered(monitor)
    assert not backend.snapshot()['supported']
    with pytest.raises(InstallError): backend.start(monitor, 'v999.0.0', 4)
    assert not (tmp_path / 'incoming').exists()


def test_remote_inventory_cannot_install_and_pending_update_blocks_writes(updater, tmp_path):
    app = create_app(Settings(tmp_path / 'data', network_enabled=True), update_installer=updater)
    with TestClient(app, client=('192.0.2.4', 1)) as client:
        app.state.updates.close(); offered(app.state.updates)
        payload = {'revision': 4, 'tag': 'v999.0.0'}
        assert client.post('/api/updates/install', json=payload).status_code == 403
        assert not updater.pending()
        app.state.network.set_mode('full')
        assert client.post('/api/updates/install', json=payload, headers={'Origin': 'https://foreign.example'}).status_code == 403
        assert client.post('/api/updates/install', content='anything').status_code == 415
        response = client.post('/api/updates/install', json=payload)
        assert response.status_code == 202 and response.json()['pending']
        assert client.post('/api/updates/install', json=payload).status_code == 503
        assert client.post('/api/updates/check', json={}).status_code == 503
        assert client.post('/api/system/power/prepare', json={'action': 'reboot'}).status_code == 503
        assert client.get('/api/reader/tag').status_code == 503
        assert client.get('/api/status').json()['updates']['installation']['pending']
        assert client.get('/api/inventory').status_code == 200
        assert client.get('/api/configuration/updates').status_code == 200
        # The root installer must still be able to inspect hardware readiness.
        assert client.get('/api/system/power').status_code == 200


def test_hardware_operation_in_progress_refuses_the_update(updater, tmp_path):
    app = create_app(Settings(tmp_path / 'data'), update_installer=updater)
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        app.state.updates.close(); offered(app.state.updates)
        with app.state.reader.lock:
            # A different thread owns the simulated reader during the request.
            assert client.post('/api/updates/install', json={'revision':4,'tag':'v999.0.0'}).status_code == 409
        assert not updater.pending()


def test_progress_is_readable_after_restart_without_private_log_fields(updater):
    record = {'id':str(uuid.uuid4()), 'phase':'complete', 'tag':'v999.0.0', 'percent':100,
              'started_at':'2026-11-02T08:00:00Z', 'finished_at':'2026-11-02T08:02:00Z',
              'log':'private secret', 'backup':'private path'}
    (updater.directory / 'state.json').write_text(json.dumps(record))
    restarted = UpdateInstaller(directory=updater.directory); restarted.supported = lambda: True
    state = restarted.snapshot()
    assert state['phase'] == 'complete' and not state['pending'] and state['percent'] == 100
    assert 'private' not in json.dumps(state)
