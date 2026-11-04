"""Bulk exports verify absence afresh and reuse single-spool write safeguards."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from unittest.mock import Mock
import uuid

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.connect_export import export_data
from openprinttag_app.prusa_connect import ConnectError, WAREHOUSE_QUERY, WAREHOUSE_MATERIALS_QUERY
from test_connect_export import ExportCloud, setup, preview, send
from test_prusa_connect import MAIN, TOKEN, configure


def new_spool(store, **patch):
    return store.create_packaged({**MAIN, 'brand_name': 'Fixture brand', **patch}, {'consumed_weight': 0})


def row_for(result, item):
    return next(row for row in result['items'] if row['id'] == item['id'])


def send_missing(exporter, row):
    return exporter.export(row['id'], row['version'], row['notes_revision'], row['fingerprint'], missing_only=True)


def test_shared_preview_covers_all_active_spools_and_is_strictly_read_only(tmp_path):
    store, present, cfg, cloud, exporter = setup(tmp_path)
    send(exporter, present, preview(exporter, present))
    # Cloud presence takes priority even if the local card needs corrections.
    present = store.patch_spool(present['id'], present['version'], main={'brand_name': None})['item']
    ready = new_spool(store)
    unknown = store.create_packaged({**MAIN, 'brand_name': 'Fixture brand'}, {})
    brand_missing = new_spool(store, brand_name=None)
    archived = new_spool(store)
    store.complete(archived['id'], archived['version'])
    removed = new_spool(store)
    store.remove(removed['id'], removed['version'])
    before = deepcopy(store.list_spools(include_removed=True))
    with store.connect() as db:
        state_before = [tuple(row) for row in db.execute('SELECT * FROM state ORDER BY key')]
    calls_before = len(cloud.calls)
    result = exporter.preview_missing()
    assert result['counts'] == {'total': 4, 'missing': 3, 'ready': 1, 'present': 1, 'blocked': 2}
    assert result['organization'] == 'Test team' and result['checked_at']
    assert row_for(result, present)['disposition'] == 'present'
    assert row_for(result, ready)['disposition'] == 'create'
    assert row_for(result, unknown)['presence'] == 'absent'
    assert row_for(result, unknown)['error'] == 'export_data'
    assert row_for(result, brand_missing)['error'] == 'export_data'
    assert all('fingerprint' not in row for row in result['items'] if row['disposition'] != 'create')
    reads = [call[2]['query'] for call in cloud.calls[calls_before:]]
    assert len(reads) == 2 and reads.count(WAREHOUSE_QUERY) == 1
    assert all(query.startswith('query ') for query in reads)
    assert store.list_spools(include_removed=True) == before and store.operations() == []
    with store.connect() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM state ORDER BY key')] == state_before
    assert TOKEN not in json.dumps(result)
    assert 'notes' not in row_for(result, present)
    assert send_missing(exporter, row_for(result, ready))['created']
    assert store.list_spools(include_removed=True) == before
    assert cloud.created == 2


def test_already_present_after_preview_is_skipped_without_repair_or_overwrite(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    row = row_for(exporter.preview_missing(), item)
    title, payload = export_data(item, cfg.read()['organization_id'])
    # Another client creates it after the shared preview, with distinct data
    # and no material catalogue entry. The group must not repair that entry.
    response = exporter.client.create_warehouse_item(payload)
    cloud.warehouse[0]['note'] = 'Remote user note'
    cloud.warehouse[0]['consumedWeight'] = 250
    before = deepcopy(cloud.warehouse)
    calls_before = len(cloud.calls)
    result = send_missing(exporter, row)
    assert result['status'] == 'already_present' and not result['created']
    assert result['warehouse_id'] == response['id']
    assert cloud.warehouse == before and cloud.registered == cloud.renamed == 0
    assert all(call[2]['query'].startswith('query ') for call in cloud.calls[calls_before:])
    assert not any(call[2]['query'] == WAREHOUSE_MATERIALS_QUERY for call in cloud.calls[calls_before:])
    assert exporter._journal(exporter._key(cfg.read()['organization_id'], item['instance_uuid'])) is None
    assert store.get_spool(item['id']) == item


def test_concurrent_group_requests_and_repeat_preview_do_not_duplicate(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    row = row_for(exporter.preview_missing(), item)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: send_missing(exporter, row), range(4)))
    assert sum(result['created'] for result in results) == 1
    assert cloud.created == cloud.registered == cloud.renamed == len(cloud.warehouse) == 1
    again = exporter.preview_missing()
    assert again['counts']['ready'] == 0 and again['counts']['present'] == 1
    assert 'fingerprint' not in again['items'][0] and store.get_spool(item['id']) == item


@pytest.mark.parametrize('change', ['version', 'notes', 'configuration', 'archive'])
def test_group_preview_is_invalidated_by_changed_card_or_settings(tmp_path, change):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    row = row_for(exporter.preview_missing(), item)
    if change == 'version':
        store.patch_spool(item['id'], item['version'], main={'material_name': 'Corrected name'})
    elif change == 'notes':
        store.save_spool_notes(item['id'], 'New note', item['notes_revision'])
    elif change == 'configuration':
        configure(cfg, poll_seconds=60)
    else:
        store.complete(item['id'], item['version'])
    with pytest.raises(ConnectError) as error:
        send_missing(exporter, row)
    assert error.value.code == 'export_changed'
    assert cloud.created == cloud.registered == cloud.renamed == 0


def test_group_preserves_uncertain_write_and_does_not_retry_creation(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    row = row_for(exporter.preview_missing(), item)
    cloud.after_create_error = True
    with pytest.raises(ConnectError):
        send_missing(exporter, row)
    assert cloud.created == 1
    cloud.hidden = True
    blocked = exporter.preview_missing()['items'][0]
    assert blocked['disposition'] == 'blocked' and blocked['error'] == 'export_uncertain'
    with pytest.raises(ConnectError):
        send_missing(exporter, row)
    assert cloud.created == 1
    cloud.hidden = False
    assert exporter.preview_missing()['items'][0]['disposition'] == 'present'
    assert send_missing(exporter, row)['status'] == 'already_present'
    assert cloud.created == 1 and cloud.renamed == 0


def test_ambiguous_uuid_or_same_number_never_becomes_exportable(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    send(exporter, item, preview(exporter, item))
    cloud.warehouse.append({**deepcopy(cloud.warehouse[0]), 'id': str(uuid.uuid4())})
    blocked = exporter.preview_missing()['items'][0]
    assert blocked['disposition'] == 'blocked' and blocked['presence'] == 'unknown'
    assert blocked['error'] == 'export_duplicate'
    cloud.warehouse.pop()
    cloud.warehouse[0]['materialPackageInstance']['uuid'] = str(uuid.uuid4())
    with store.connect() as db:
        db.execute('DELETE FROM state WHERE key LIKE ?', ('connect-warehouse-export:%',))
    blocked = exporter.preview_missing()['items'][0]
    assert blocked['disposition'] == 'blocked' and blocked['presence'] == 'absent'
    assert blocked['error'] == 'export_duplicate'
    assert cloud.created == 1


@pytest.mark.parametrize('malformed', [None, {}, {'id': str(uuid.uuid4()), 'materialPackageInstance': {}},
                                     {'id': 'not-an-id', 'materialPackageInstance': {'uuid': str(uuid.uuid4())}}])
def test_unidentifiable_cloud_list_cannot_establish_absence(tmp_path, malformed):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    cloud.warehouse.append(malformed)
    with pytest.raises(ConnectError) as error:
        exporter.preview_missing()
    assert error.value.code == 'contract'
    assert cloud.created == 0 and store.get_spool(item['id']) == item


def test_failed_cloud_read_never_falls_back_to_inventory_presence_cache(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    exporter.monitor._warehouse_presence = {'instances': set()}
    cloud.fail = True
    with pytest.raises(ConnectError):
        exporter.preview_missing()
    assert cloud.created == 0 and store.get_spool(item['id']) == item


def test_missing_export_rechecks_local_version_after_network_reads(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    row = row_for(exporter.preview_missing(), item)
    fetch = exporter.client.fetch
    def edit_during_read(url, headers, body):
        result = fetch(url, headers, body)
        if json.loads(body)['query'] == WAREHOUSE_QUERY:
            store.patch_spool(item['id'], item['version'], main={'material_name': 'Edited concurrently'})
        return result
    exporter.client.fetch = edit_during_read
    with pytest.raises(ConnectError) as error:
        send_missing(exporter, row)
    assert error.value.code == 'export_changed' and cloud.created == cloud.registered == 0


def test_group_http_requires_full_access_and_does_not_touch_hardware(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path / 'data', network_enabled=True))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        app.state.connect_monitor.close()
        item = new_spool(app.state.store)
        cloud = ExportCloud(item)
        app.state.connect_monitor.client.fetch = cloud
        configure(app.state.connect_configuration)
        for device, operation in ((app.state.reader, 'read'), (app.state.reader, 'write'), (app.state.label_printer, 'print')):
            monkeypatch.setattr(device, operation, Mock(side_effect=AssertionError('No hardware access')))
        response = client.post('/api/inventory/connect/preview', json={})
        assert response.status_code == 200 and TOKEN not in response.text
        row = row_for(response.json(), item)
        route = '/api/inventory/' + item['id'] + '/connect/export-missing'
        body = {key: row[key] for key in ('version', 'notes_revision', 'fingerprint')}
        response = client.post(route, json=body)
        assert response.status_code == 200 and response.json()['created'] and TOKEN not in response.text
        assert client.post(route, json=body).json()['status'] == 'already_present'
        assert app.state.store.get_spool(item['id']) == item
        assert app.state.store.operations() == []
    with TestClient(app, client=('192.0.2.8', 1)) as remote:
        assert remote.post('/api/inventory/connect/preview', json={}).status_code == 403
        assert remote.post(route, json=body).status_code == 403
    assert cloud.created == 1
