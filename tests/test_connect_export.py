"""Warehouse exports use isolated stocks and a stateful cloud double."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from unittest.mock import Mock
import uuid

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.connect_export import WarehouseExporter, export_data
from openprinttag_app.prusa_connect import (ConnectError, ConnectMonitor, ConnectConfiguration,
    CREATE_WAREHOUSE_MUTATION, RENAME_WAREHOUSE_MUTATION, CREATE_MATERIAL_MUTATION, WAREHOUSE_MATERIALS_QUERY)
from openprinttag_app.storage import Store
from test_prusa_connect import Cloud, MAIN, add, configure, TOKEN


class ExportCloud(Cloud):
    def __init__(self, item):
        super().__init__(item)
        self.created = 0
        self.renamed = 0
        self.after_create_error = False
        self.hidden = False
        self.corrupt_identity = False
        self.rejected = False
        # Connect stores inline spool snapshots separately from the material
        # catalogue that powers the warehouse shown in its web interface.
        self.materials = {}
        self.registered = 0
        self.registration_response_lost = False
        self.registration_missing = False
        self.catalogue_count = None

    def __call__(self, url, headers, body):
        request = json.loads(body)
        query, variables = request['query'], request.get('variables', {})
        if query == CREATE_MATERIAL_MUTATION:
            self.calls.append((url, headers, request))
            material = deepcopy(variables['material'])
            self.registered += 1
            if not self.registration_missing:
                assert material['uuid'] not in self.materials
                self.materials[material['uuid']] = material
            if self.registration_response_lost:
                raise ConnectError('network', 'Private transport details must not be returned')
            return 200, json.dumps({'data': {'warehouse': {'createCustomMaterial': {'id': material['uuid'], 'createdAt': '2026-11-01T12:00:00Z'}}}}).encode()
        if query == WAREHOUSE_MATERIALS_QUERY:
            self.calls.append((url, headers, request))
            material = self.materials.get(variables['materialUuid'][0])
            nodes = []
            if material:
                count = sum(row['materialPackageInstance']['package']['material']['uuid'] == material['uuid'] for row in self.warehouse)
                nodes = [{'uuid': material['uuid'], 'material': material,
                          'spoolCount': (count or None) if self.catalogue_count is None else self.catalogue_count}]
            return 200, json.dumps({'data': {'warehouse': {'materials': {'totalCount': len(nodes),
                'totalSpoolCount': sum(x['spoolCount'] or 0 for x in nodes), 'totalRemainingWeight': 0,
                'pageInfo': {'hasNextPage': False, 'endCursor': None}, 'nodes': nodes}}}}).encode()
        if query == CREATE_WAREHOUSE_MUTATION:
            self.calls.append((url, headers, request))
            if self.rejected:
                return 200, b'{"data":{"warehouse":{"createItems":{"__typename":"WarehouseServiceError","errorCode":"QUOTA_EXCEEDED"}}}}'
            payload = variables['input']
            assert payload['quantity'] == 1
            instance = deepcopy(payload['materialPackageInstance'])
            if self.corrupt_identity:
                instance['uuid'] = str(uuid.uuid4())
            initial = instance.get('actualNettoFullWeight', instance['package']['nominalNettoFullWeight'])
            row = {'id': str(uuid.uuid4()), 'name': instance['package']['material']['name'],
                   'consumedWeight': instance['dynamicData']['consumedWeight'],
                   'remainingWeight': initial - instance['dynamicData']['consumedWeight'],
                   'nominalNettoFullWeight': instance['package']['nominalNettoFullWeight'],
                   'materialPackageInstance': instance, 'materialPackageInstanceUuidSource': 'nfc',
                   'note': payload.get('note'), 'location': payload.get('location'), 'archived': False}
            self.warehouse.append(row)
            self.created += 1
            if self.after_create_error:
                raise ConnectError('network', 'Private transport details must not be returned')
            data = {'warehouse': {'createItems': {'__typename': 'WarehouseCreateItemsSuccess', 'items': [{'id': row['id'], 'name': row['name']}]}}}
            return 200, json.dumps({'data': data}).encode()
        if query == RENAME_WAREHOUSE_MUTATION:
            self.calls.append((url, headers, request))
            assert set(variables['input']) == {'name'}
            row = next(x for x in self.warehouse if x['id'] == variables['uuid'])
            row['name'] = variables['input']['name']; self.renamed += 1
            return 200, json.dumps({'data': {'warehouse': {'updateItem': {'__typename': 'WarehouseMutateItemSuccess', 'item': {'id': row['id'], 'name': row['name']}}}}}).encode()
        if self.hidden and 'OptStationWarehouse' in query:
            return 200, b'{"data":{"warehouse":{"items":{"totalCount":0,"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}'
        return super().__call__(url, headers, body)


def setup(tmp_path, kind='qr'):
    store = Store(tmp_path / 'inventory.sqlite3')
    item = add(store, kind)
    item = store.patch_spool(item['id'], item['version'], main={'brand_name': 'Fixture brand', 'material_name': 'Fixture PETG',
        'filament_diameter': 1.75, 'primary_color': '#102030', 'density': 1.27})['item']
    item = store.save_spool_notes(item['id'], 'Empty spool weighed: 278 g', 0)
    cfg = ConnectConfiguration(tmp_path); configure(cfg)
    cloud = ExportCloud(item)
    monitor = ConnectMonitor(cfg, store, fetch=cloud)
    return store, item, cfg, cloud, WarehouseExporter(monitor)


def preview(exporter, item):
    return exporter.preview(item['id'], item['version'], item['notes_revision'])


def send(exporter, item, value):
    return exporter.export(item['id'], item['version'], item['notes_revision'], value['fingerprint'])


@pytest.mark.parametrize('kind', ['qr', 'rfid'])
def test_export_rereads_full_data_and_repeated_concurrent_sends_create_one_spool(tmp_path, kind):
    store, item, cfg, cloud, exporter = setup(tmp_path, kind)
    original = deepcopy(item)
    value = preview(exporter, item)
    assert cloud.created == 0 and value['disposition'] == 'create' and TOKEN not in json.dumps(value)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: send(exporter, item, value), range(4)))
    assert sum(x['created'] for x in results) == 1 and all(x['verified'] for x in results)
    assert cloud.created == cloud.renamed == len(cloud.warehouse) == 1
    assert cloud.registered == len(cloud.materials) == 1
    writes = [r['query'] for _, _, r in cloud.calls if r['query'].startswith('mutation ')]
    assert writes == [CREATE_MATERIAL_MUTATION, CREATE_WAREHOUSE_MUTATION, RENAME_WAREHOUSE_MUTATION]
    remote = cloud.warehouse[0]
    assert remote['materialPackageInstance']['uuid'] == item['instance_uuid']
    assert remote['name'] == value['name'] and remote['name'].startswith(item['spool_number'])
    assert remote['consumedWeight'] == 100 and remote['remainingWeight'] == 925
    assert remote['materialPackageInstance']['package']['filamentDiameter'] == 1750
    assert remote['materialPackageInstance']['package']['nominalFullLength'] == MAIN['nominal_full_length']
    assert remote['note'] == item['notes']
    assert store.get_spool(item['id']) == original and store.operations() == []


def test_lost_success_response_is_reconciled_after_process_restart_without_second_creation(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    value = preview(exporter, item); cloud.after_create_error = True
    with pytest.raises(ConnectError) as error:
        send(exporter, item, value)
    assert error.value.code == 'uncertain' and 'Private' not in str(error.value)
    assert cloud.created == 1
    restarted = WarehouseExporter(ConnectMonitor(ConnectConfiguration(tmp_path), Store(store.path), fetch=cloud))
    cfg = restarted.configuration
    # A settings revision after reconnecting does not discard the durable record.
    configure(cfg)
    result = send(restarted, item, preview(restarted, item))
    assert result['status'] == 'reconciled' and not result['created'] and result['verified']
    assert cloud.created == 1 and cloud.renamed == 1 and store.get_spool(item['id']) == item


@pytest.mark.parametrize('corrupt', [False, True])
def test_unconfirmed_or_replaced_identity_prevents_blind_retries(tmp_path, corrupt):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    value = preview(exporter, item)
    cloud.corrupt_identity = corrupt
    if not corrupt:
        cloud.after_create_error = True
    with pytest.raises(ConnectError):send(exporter, item, value)
    cloud.hidden = True
    with pytest.raises(ConnectError, match='seconde création'):preview(exporter, item)
    assert cloud.created == 1
    cloud.hidden = False
    if corrupt:
        with pytest.raises(ConnectError):preview(exporter, item)
    else:
        assert send(exporter, item, preview(exporter, item))['verified']
    assert cloud.created == 1 and store.get_spool(item['id']) == item


def test_existing_cloud_record_is_not_overwritten_and_duplicates_are_refused(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    send(exporter, item, preview(exporter, item))
    cloud.warehouse[0]['note'] = 'Separate cloud notes'
    cloud.warehouse[0]['consumedWeight'] = 250
    before = deepcopy(cloud.warehouse)
    result = send(exporter, item, preview(exporter, item))
    assert result['status'] == 'already_present' and 'note' in result['differences'] and not result['verified']
    assert cloud.warehouse == before and cloud.created == 1 and cloud.renamed == 1
    cloud.warehouse.append({**cloud.warehouse[0], 'id': str(uuid.uuid4())})
    with pytest.raises(ConnectError, match='Plusieurs'):preview(exporter, item)
    assert cloud.created == 1


def test_old_invisible_export_registers_its_material_without_recreating_or_overwriting_spool(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    title, payload = export_data(item, cfg.read()['organization_id'])
    old = exporter.client.create_warehouse_item(payload)
    exporter.client.name_warehouse_item(cfg.read()['organization_id'], old['id'], title)
    before = deepcopy(cloud.warehouse)
    key = exporter._key(cfg.read()['organization_id'], item['instance_uuid'])
    # The earlier version recorded raw item presence as a verified export.
    exporter._save(key, {'version': 1, 'phase': 'verified', 'warehouse_id': old['id']})
    value = preview(exporter, item)
    assert value['disposition'] == 'repair' and value['warehouse_id'] == old['id']
    assert cloud.registered == 0
    result = send(exporter, item, value)
    assert result['status'] == 'repaired' and result['visible_in_connect'] and result['verified']
    assert not result['created'] and cloud.created == cloud.renamed == cloud.registered == 1
    assert cloud.warehouse == before and store.get_spool(item['id']) == item
    again = send(exporter, item, preview(exporter, item))
    assert again['status'] == 'already_present' and cloud.registered == cloud.created == 1


def test_raw_item_presence_without_visible_catalogue_count_is_not_success(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    cloud.catalogue_count = 0
    with pytest.raises(ConnectError, match='visibilité'):
        send(exporter, item, preview(exporter, item))
    assert cloud.created == 1 and cloud.registered == 1
    with pytest.raises(ConnectError, match='visibilité'):
        send(exporter, item, preview(exporter, item))
    cloud.catalogue_count = None
    assert send(exporter, item, preview(exporter, item))['visible_in_connect']
    assert cloud.created == cloud.registered == 1


def test_lost_material_registration_response_reconciles_by_read_without_second_write(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    cloud.registration_response_lost = True
    assert send(exporter, item, preview(exporter, item))['verified']
    assert cloud.registered == cloud.created == 1


def test_unconfirmed_material_registration_stays_journalled_without_blind_retry(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    cloud.registration_missing = True
    with pytest.raises(ConnectError, match='matériau Connect'):
        send(exporter, item, preview(exporter, item))
    restarted = WarehouseExporter(ConnectMonitor(ConnectConfiguration(tmp_path), Store(store.path), fetch=cloud))
    with pytest.raises(ConnectError, match='matériau Connect'):
        send(restarted, item, preview(restarted, item))
    assert cloud.registered == 1 and cloud.created == 0
    _, payload = export_data(item, cfg.read()['organization_id'])
    material = payload['materialPackageInstance']['package']['material']
    cloud.materials[material['uuid']] = material
    assert send(restarted, item, preview(restarted, item))['verified']
    assert cloud.registered == cloud.created == 1


def test_preview_cannot_be_used_after_local_edit_or_configuration_change(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    value = preview(exporter, item)
    configure(cfg, poll_seconds=60)
    with pytest.raises(ConnectError, match='aperçu'):send(exporter, item, value)
    value = preview(exporter, item)
    store.save_spool_notes(item['id'], 'Changed after preview', item['notes_revision'])
    with pytest.raises(ConnectError, match='fiche a changé'):send(exporter, item, value)
    assert cloud.created == 0


def test_known_rejection_allows_corrected_retry_and_unknown_values_are_not_invented(tmp_path):
    store, item, cfg, cloud, exporter = setup(tmp_path)
    cloud.rejected = True
    with pytest.raises(ConnectError, match='limite'):send(exporter, item, preview(exporter, item))
    assert cloud.created == 0
    cloud.rejected = False
    assert send(exporter, item, preview(exporter, item))['verified']
    for patch in ({'aux': {}}, {'main': {**item['main'], 'nominal_netto_full_weight': None}}, {'main': {**item['main'], 'brand_name': ''}}):
        with pytest.raises(ConnectError):export_data({**item, **patch}, cfg.read()['organization_id'])
    explicit_zero = {**item, 'aux': {'consumed_weight': 0}}
    assert export_data(explicit_zero, cfg.read()['organization_id'])[1]['materialPackageInstance']['dynamicData']['consumedWeight'] == 0


def test_http_export_requires_full_access_and_never_uses_hardware(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path / 'data', network_enabled=True))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        app.state.connect_monitor.close()
        item = app.state.store.create_packaged({**MAIN, 'brand_name': 'Fixture brand', 'filament_diameter': 1.75}, {'consumed_weight': 100})
        cloud = ExportCloud(item);app.state.connect_monitor.client.fetch = cloud
        configure(app.state.connect_configuration)
        for obj, name in ((app.state.reader, 'read'), (app.state.reader, 'write'), (app.state.label_printer, 'print')):
            monkeypatch.setattr(obj, name, Mock(side_effect=AssertionError('No hardware')))
        route = '/api/inventory/' + item['id'] + '/connect/'
        body = {'version': item['version'], 'notes_revision': item['notes_revision']}
        response = client.post(route + 'preview', json=body)
        assert response.status_code == 200 and TOKEN not in response.text
        response = client.post(route + 'export', json={**body, 'fingerprint': response.json()['fingerprint']})
        assert response.status_code == 200 and response.json()['verified'] and TOKEN not in response.text
        assert app.state.store.get_spool(item['id']) == item
    with TestClient(app, client=('192.0.2.8', 1)) as remote:
        assert remote.post(route + 'preview', json=body).status_code == 403
        assert remote.post(route + 'export', json={**body, 'fingerprint': '0'*64}).status_code == 403
    assert cloud.created == 1


def test_export_values_can_fill_missing_nominal_without_changing_consumption_notes_or_identity(tmp_path):
    app = create_app(Settings(tmp_path / 'data', network_enabled=True))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        app.state.connect_monitor.close()
        main = {k: v for k, v in MAIN.items() if k != 'nominal_netto_full_weight'}
        main.update(actual_netto_full_weight=1000, brand_name='Fixture brand')
        item = app.state.store.create_packaged(main, {'consumed_weight': 500})
        item = app.state.store.save_spool_notes(item['id'], 'Tare measured separately', 0)
        cloud = ExportCloud(item); app.state.connect_monitor.client.fetch = cloud
        configure(app.state.connect_configuration)
        route = '/api/inventory/' + item['id'] + '/connect/'
        preview_body = {'version': item['version'], 'notes_revision': item['notes_revision']}
        response = client.post(route + 'preview', json=preview_body)
        assert response.status_code == 422 and 'nominal' in response.json()['detail']
        body = {'version': item['version'], 'nominal_initial_weight': 1000, 'consumed_weight': 500}
        response = client.post(route + 'values', json=body)
        assert response.status_code == 200 and response.json()['updated']
        changed = response.json()['item']
        assert response.json()['rfid_written'] is False
        assert changed['remaining_weight'] == 500 and changed['aux'] == item['aux']
        assert changed['main'] == {**item['main'], 'nominal_netto_full_weight': 1000}
        for key in ('id', 'uid', 'instance_uuid', 'spool_number', 'notes', 'notes_revision', 'added_at', 'last_seen_at'):
            assert changed[key] == item[key]
        assert client.post(route + 'values', json=body).status_code == 409
        same = client.post(route + 'values', json={**body, 'version': changed['version']}).json()
        assert not same['updated'] and same['item'] == changed
        value = client.post(route + 'preview', json={**preview_body, 'version': changed['version']})
        assert value.status_code == 200 and value.json()['consumed_weight'] == 500
        assert value.json()['remaining_weight'] == 500 and cloud.created == 0
        assert app.state.store.operations() == []
    with TestClient(app, client=('192.0.2.8', 1)) as remote:
        assert remote.post(route + 'values', json={**body, 'version': changed['version']}).status_code == 403


@pytest.mark.parametrize('patch', [
    {'nominal_initial_weight': 0}, {'nominal_initial_weight': True}, {'nominal_initial_weight': None},
    {'actual_initial_weight': -1}, {'consumed_weight': None}, {'consumed_weight': True},
    {'consumed_weight': -1}, {'consumed_weight': 2000},
])
def test_export_value_validation_never_turns_unknown_or_invalid_values_into_zero(tmp_path, patch):
    app = create_app(Settings(tmp_path))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        app.state.connect_monitor.close()
        item = app.state.store.create_packaged(MAIN, {})
        body = {'version': item['version'], 'nominal_initial_weight': 1000, 'consumed_weight': 500, **patch}
        response = client.post('/api/inventory/' + item['id'] + '/connect/values', json=body)
        assert response.status_code in (400, 422)
        assert app.state.store.get_spool(item['id']) == item


def test_explicit_consumption_correction_sets_the_existing_manual_sync_hold(tmp_path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        app.state.connect_monitor.close()
        item = add(app.state.store)
        from test_prusa_connect import sample
        app.state.store.sync_connect_consumption(sample(item, 130), '2026-11-01T12:00:00Z', apply=True)
        item = app.state.store.get_spool(item['id'])
        result = client.post('/api/inventory/' + item['id'] + '/connect/values', json={
            'version': item['version'], 'nominal_initial_weight': 1000, 'consumed_weight': 150})
        assert result.status_code == 200
        changed = result.json()['item']
        assert changed['aux']['consumed_weight'] == 150 and changed['remaining_weight'] == 875
        assert changed['connect_sync']['manual_hold'] is True


def test_backup_restore_keeps_interrupted_export_and_reloads_its_configuration(tmp_path):
    import base64
    app = create_app(Settings(tmp_path / 'data'))
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        app.state.connect_monitor.close()
        item = app.state.store.create_packaged({**MAIN, 'brand_name': 'Fixture brand'}, {'consumed_weight': 100})
        cloud = ExportCloud(item);cloud.after_create_error = True
        app.state.connect_monitor.client.fetch = cloud
        configure(app.state.connect_configuration)
        route = '/api/inventory/' + item['id'] + '/connect/'
        body = {'version': item['version'], 'notes_revision': item['notes_revision']}
        value = client.post(route + 'preview', json=body).json()
        assert client.post(route + 'export', json={**body, 'fingerprint': value['fingerprint']}).status_code == 503
        backup = client.post('/api/backups/download', json={'scope': 'all'})
        assert backup.status_code == 200
        restore = client.post('/api/backups/restore/preview', json={'content': base64.b64encode(backup.content).decode()})
        assert restore.status_code == 200
        assert client.post('/api/backups/restore/commit', json={'preview_id': restore.json()['preview_id'], 'confirmed': True}).status_code == 200
        assert app.state.connect_exporter.configuration is app.state.connect_configuration
        assert not app.state.connect_exporter.configuration.read()['enabled']
        configure(app.state.connect_configuration)
        item = app.state.store.get_spool(item['id']);body = {'version': item['version'], 'notes_revision': item['notes_revision']}
        value = client.post(route + 'preview', json=body)
        assert value.status_code == 200 and value.json()['disposition'] == 'resume'
        result = client.post(route + 'export', json={**body, 'fingerprint': value.json()['fingerprint']})
        assert result.status_code == 200 and result.json()['verified'] and not result.json()['created']
        assert cloud.created == 1
