"""Finished spools retain their identity/data and are counted exactly once."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import TagImage
from openprinttag_app.storage import ConflictError, Store

MAIN = {"material_class": "FFF", "material_type": "PETG", "brand_name": "Essai", "material_name": "Ma bobine", "actual_netto_full_weight": 1000}
UID = "E004015023456789"


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


def packaged(client, aux=None):
    response = client.post('/api/inventory/packaged', json={"main": MAIN, "aux": aux or {}})
    assert response.status_code == 200, response.text
    return response.json()


def finish(client, item):
    return client.post(f"/api/inventory/{item['id']}/complete", json={"version": item['version']})


def test_finish_preserves_unknown_data_and_identity_without_hardware(station, monkeypatch):
    app, client = station
    item = packaged(client)
    def no_hardware(*args):
        pytest.fail('Completing stock must not read/write NFC or print')
    monkeypatch.setattr(app.state.reader, 'read', no_hardware)
    monkeypatch.setattr(app.state.reader, 'write', no_hardware)
    monkeypatch.setattr(app.state.label_printer, 'print', no_hardware)
    result = finish(client, item)
    assert result.status_code == 200
    archived = result.json()
    assert archived['completed_at'] and not archived['in_stock']
    assert archived['version'] == item['version'] + 1
    for key in ('id', 'instance_uuid', 'main', 'aux', 'uid', 'added_at', 'last_seen_at', 'label_state'):
        assert archived[key] == item[key]
    assert archived['remaining_weight'] is None and 'consumed_weight' not in archived['aux']
    assert client.get('/api/inventory').json()['items'] == []
    assert client.get('/api/inventory?include_removed=true').json()['items'] == [archived]
    assert client.get('/api/inventory/' + item['id']).json() == archived
    assert client.get('/api/status').json()['completed_spools_count'] == 1


def test_repeated_finish_is_idempotent_even_with_old_version(station):
    app, client = station
    item = packaged(client, {'consumed_weight': 20})
    first = finish(client, item).json()
    assert finish(client, item).json() == first
    assert finish(client, first).json() == first
    assert app.state.store.completed_count() == 1
    assert first['aux']['consumed_weight'] == 20 and first['remaining_weight'] == 980


def test_simple_removal_is_not_consumption_and_can_still_be_restored(station):
    _, client = station
    item = packaged(client)
    removed = client.post(f"/api/inventory/{item['id']}/remove", json={'version': item['version']}).json()
    assert removed['completed_at'] is None and not removed['in_stock']
    assert client.get('/api/status').json()['completed_spools_count'] == 0
    restored = client.post(f"/api/inventory/{item['id']}/restore", json={'version': removed['version']}).json()
    assert restored['in_stock'] and restored['completed_at'] is None
    assert client.get('/api/status').json()['completed_spools_count'] == 0
    assert finish(client, restored).status_code == 200


def test_archived_spool_cannot_return_to_stock_through_existing_routes(station):
    app, client = station
    item = packaged(client)
    archived = finish(client, item).json()
    for action in ('restore', 'remove'):
        assert client.post(f"/api/inventory/{item['id']}/{action}", json={'version': archived['version']}).status_code == 409
    assert client.post('/api/inventory/packaged', json={'main': archived['main'], 'aux': archived['aux']}).status_code == 409
    with pytest.raises(ConflictError):
        app.state.store.pending(item['id'], archived['version'])
    assert app.state.store.get_spool(item['id']) == archived


def test_rereading_completed_rfid_preserves_archive_and_refuses_readdition(station):
    app, client = station
    snapshot = TagImage.create(UID, MAIN, {'consumed_weight': 990}).snapshot()
    item = app.state.store.add(snapshot)
    archived = finish(client, item).json()
    changed = TagImage.create(UID, snapshot['main'], {'consumed_weight': 1000}).snapshot()
    assert app.state.store.observe(changed) == archived
    with pytest.raises(ConflictError, match='terminée'):
        app.state.store.add(changed)
    assert app.state.store.completed_count() == 1
    assert app.state.store.get_spool(item['id']) == archived


def test_stale_unfinished_record_conflicts_without_counting(station):
    app, client = station
    snapshot = TagImage.create(UID, MAIN, {'consumed_weight': 0}).snapshot()
    item = app.state.store.add(snapshot)
    updated = app.state.store.observe(snapshot)
    assert finish(client, item).status_code == 409
    assert app.state.store.completed_count() == 0
    assert finish(client, updated).status_code == 200


def test_old_qr_finds_archived_record_without_offering_stock_return(station):
    app, client = station
    item = packaged(client)
    text = client.get(f"/api/inventory/{item['id']}/qr?version={item['version']}").json()['text']
    archived = finish(client, item).json()
    found = client.post('/api/qr/inspect', json={'text': text})
    assert found.status_code == 200
    assert found.json()['inventory'] == archived
    assert 'archivée' in found.json()['message']
    assert app.state.store.completed_count() == 1


def test_concurrent_retries_archive_once_across_independent_stores(tmp_path):
    path = tmp_path / 'stock.sqlite3'
    store = Store(path)
    item = store.create_packaged(MAIN, {})
    # Independent connections exercise SQLite locking, not an application mutex.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.complete(item['id'], item['version']), range(16)))
    assert all(value == results[0] for value in results)
    assert results[0]['version'] == item['version'] + 1
    assert Store(path).completed_count() == 1
    assert Store(path).get_spool(item['id']) == results[0]


def test_two_physical_spools_count_separately_and_count_survives_restart(station):
    app, client = station
    a, b = packaged(client), packaged(client)
    assert a['instance_uuid'] != b['instance_uuid']
    finish(client, a)
    finish(client, b)
    assert app.state.store.completed_count() == 2
    assert Store(app.state.settings.database).completed_count() == 2


def test_status_notifies_other_clients_and_inventory_mode_allows_completion(station):
    app, client = station
    item = packaged(client)
    with TestClient(app, client=('192.0.2.42', 1)) as remote:
        assert remote.get('/api/status').json()['completed_spools_count'] == 0
        assert not remote.get('/api/status').json()['station_access']
        assert finish(remote, item).status_code == 200
        assert client.get('/api/status').json()['completed_spools_count'] == 1
        assert remote.get('/api/status').json()['completed_spools_count'] == 1
        assert len(remote.get('/api/inventory?include_removed=true').json()['items']) == 1
        client.put('/api/configuration/network', json={'mode': 'disabled'})
        assert remote.get('/api/status').json()['completed_spools_count'] is None
        assert finish(remote, item).status_code == 403


@pytest.mark.parametrize('body', [{}, {'version': True}, {'version': '1'}, {'version': 0}, {'version': 1, 'consumed_weight': 1000}])
def test_invalid_completion_requests_cannot_change_stock(station, body):
    app, client = station
    item = packaged(client)
    response = client.post(f"/api/inventory/{item['id']}/complete", json=body)
    assert response.status_code == 422
    assert app.state.store.get_spool(item['id']) == item and app.state.store.completed_count() == 0


def test_unknown_id_origin_and_pending_power_do_not_archive(station):
    app, client = station
    item = packaged(client)
    assert finish(client, {**item, 'id':'unknown'}).status_code == 404
    assert client.post(f"/api/inventory/{item['id']}/complete", json={'version': item['version']}, headers={'Origin':'http://other-host'}).status_code == 403
    app.state.station_power.phase = 'requested'
    assert finish(client, item).status_code == 503
    assert app.state.store.completed_count() == 0


def legacy_database(path):
    snapshot = TagImage.create(UID, MAIN, {'consumed_weight':1000}).snapshot()
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO metadata VALUES('schema_version','2');
            CREATE TABLE spools(id TEXT PRIMARY KEY,instance_uuid TEXT NOT NULL UNIQUE,uid TEXT UNIQUE,in_stock INTEGER NOT NULL DEFAULT 1,snapshot TEXT NOT NULL,last_seen_at TEXT,version INTEGER NOT NULL DEFAULT 1,added_at TEXT,label_state TEXT NOT NULL DEFAULT 'rfid');""")
        db.execute('INSERT INTO spools VALUES(?,?,?,?,?,?,?,?,?)', ('old',snapshot['instance_uuid'],UID,0,json.dumps(snapshot),'2026-10-20T10:00:00+00:00',7,'2026-10-01T10:00:00+00:00','rfid'))
    return snapshot


def test_v2_migration_never_counts_old_removed_or_empty_spools_as_completed(tmp_path):
    path = tmp_path/'legacy.sqlite3'
    snapshot = legacy_database(path)
    store = Store(path)
    old = store.get_spool('old')
    assert old['completed_at'] is None and not old['in_stock'] and old['version'] == 7
    assert old['main'] == snapshot['main'] and old['aux'] == snapshot['aux']
    assert old['remaining_weight'] == 0 and old['added_at']=='2026-10-01T10:00:00+00:00'
    assert store.completed_count() == 0
    with store.connect() as db:
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]=='5'
    assert Store(path).get_spool('old') == old
    assert store.restore('old', 7)['in_stock']


def test_failed_migration_rolls_back_column_and_preserves_v2_data(tmp_path):
    path = tmp_path/'legacy.sqlite3'
    snapshot = legacy_database(path)
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TRIGGER refuse_schema_change BEFORE UPDATE ON metadata WHEN NEW.key='schema_version' BEGIN SELECT RAISE(ABORT,'simulated storage failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]=='2'
        assert 'completed_at' not in {row[1] for row in db.execute('PRAGMA table_info(spools)')}
        assert json.loads(db.execute('SELECT snapshot FROM spools').fetchone()[0]) == snapshot


def test_mcp_can_read_archives_without_exposing_completion(station):
    app, client = station
    item = packaged(client)
    archived = finish(client,item).json()
    config = client.get('/api/configuration/mcp').json()
    assert client.put('/api/configuration/mcp',json={'enabled':True,'revision':config['revision']}).status_code==200
    headers={'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
    def rpc(method, params):
        return client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':method,'params':params}).json()['result']
    tools=rpc('tools/list',{})['tools']
    assert len(tools)==13 and not any('complete' in t['name'] for t in tools)
    def inventory(arguments):
        result=rpc('tools/call',{'name':'list_inventory','arguments':arguments})
        return result.get('structuredContent') or json.loads(result['content'][0]['text'])
    assert inventory({})['items']==[]
    result=inventory({'include_removed':True})
    assert result['completed_count']==1 and result['items']==[archived]
