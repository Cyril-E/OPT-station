"""Stable stock numbers and versioned notes, independent of material/NFC data."""
from concurrent.futures import ThreadPoolExecutor
import copy
import io
import json
import sqlite3
import threading
import uuid

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import spool_snapshot
from openprinttag_app.spool_qr import decode_spool
from openprinttag_app.storage import Store, ConflictError, MAX_NOTES_LENGTH

MAIN = {"material_class": "FFF", "brand_name": "Example", "material_type": "PLA", "nominal_netto_full_weight": 1000}
TEXT = "Bobine vide : 234 g (mesuré).\nTare indicative pour le modèle noir : à vérifier."
HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}


@pytest.fixture
def station(tmp_path):
    app = create_app(Settings(tmp_path, network_enabled=True))
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        yield app, client


def packaged(client):
    r = client.post('/api/inventory/packaged', json={'main': MAIN, 'aux': {}})
    assert r.status_code == 200, r.text
    return r.json()


def rpc(client, name, arguments=None):
    r=client.post('/mcp', headers=HEADERS, json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':arguments or {}}})
    assert r.status_code==200,r.text
    return r.json()['result']


def content(result):
    assert not result.get('isError'),result
    return result.get('structuredContent') or json.loads(result['content'][0]['text'])


def test_numbers_start_at_zero_and_models_do_not_consume_them(station):
    app, client = station
    a = packaged(client)
    assert a['spool_number'] == 'B0000'
    client.post('/api/favorites', json={'name':'Product','kind':'model','main':MAIN})
    client.post('/api/favorites', json={'name':'Favorite','main':MAIN})
    b = packaged(client)
    assert b['spool_number'] == 'B0001' and a['instance_uuid'] != b['instance_uuid']
    assert app.state.store.get_spool('b1') == b
    assert client.get('/api/inventory/B0000').json() == a
    assert client.get('/api/inventory?search=B0001').json()['items'] == [b]
    app.state.store.save_spool_notes(a['id'], 'Utiliser la tare de B0001 comme référence indicative.', 0)
    assert client.get('/api/inventory?search=b1').json()['items'] == [b]
    assert Store(app.state.settings.database).get_spool(a['id'])['spool_number'] == 'B0000'
    for bad in ('B999999999999999999999999999999', 'B-1', 'B1.0', 'B１２', 'B0 or 1=1'):
        assert client.get('/api/inventory/' + bad).status_code == 404


def test_failed_duplicate_or_insert_does_not_advance_sequence(tmp_path):
    s=Store(tmp_path/'stock.sqlite3')
    a=s.create_packaged(MAIN,{})
    with pytest.raises(ConflictError): s.create_packaged(a['main'],{})
    assert s.create_packaged(MAIN,{})['spool_number']=='B0001'
    with s.connect() as db:
        db.execute("CREATE TRIGGER refuse_new_spool BEFORE INSERT ON spools BEGIN SELECT RAISE(ABORT,'failure'); END")
    with pytest.raises(ConflictError): s.create_packaged(MAIN,{})
    with s.connect() as db: db.execute('DROP TRIGGER refuse_new_spool')
    assert s.create_packaged(MAIN,{})['spool_number']=='B0002'


def test_concurrent_creations_across_independent_stores_are_unique(tmp_path):
    path=tmp_path/'stock.sqlite3';Store(path)
    barrier=threading.Barrier(8)
    def create(i):
        s=Store(path);barrier.wait(timeout=10)
        if i%2:
            snapshot=spool_snapshot(MAIN,{})
            snapshot['uid']='E00401'+f'{i:010X}'
            return s.add(snapshot)
        return s.create_packaged(MAIN,{})
    with ThreadPoolExecutor(max_workers=8) as pool: items=list(pool.map(create,range(8)))
    assert {x['spool_number'] for x in items}=={f'B{i:04d}' for i in range(8)}
    assert Store(path).create_packaged(MAIN,{})['spool_number']=='B0008'


def test_sequence_continues_after_9999_without_reusing_removed_or_archived_numbers(tmp_path):
    s=Store(tmp_path/'stock.sqlite3')
    with s.connect() as db:db.execute("UPDATE metadata SET value='9999' WHERE key='next_spool_number'")
    a=s.create_packaged(MAIN,{});b=s.create_packaged(MAIN,{})
    assert a['spool_number']=='B9999' and b['spool_number']=='B10000'
    s.complete(a['id'],a['version']);s.remove(b['id'],b['version'])
    assert Store(s.path).create_packaged(MAIN,{})['spool_number']=='B10001'
    assert s.get_spool('B10000')['id']==b['id']


def test_numbers_cannot_be_changed_and_are_not_accepted_from_api(station):
    app,client=station
    a=packaged(client)
    with pytest.raises(sqlite3.IntegrityError):
        with app.state.store.connect() as db:db.execute('UPDATE spools SET sequence_number=123 WHERE id=?',(a['id'],))
    assert client.post('/api/inventory/packaged',json={'main':MAIN,'aux':{},'spool_number':'B1234'}).status_code==422
    assert client.get('/api/inventory/'+a['id']).json()==a


def v3_database(path):
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO metadata VALUES('schema_version','3');
            CREATE TABLE spools(id TEXT PRIMARY KEY,instance_uuid TEXT NOT NULL UNIQUE,uid TEXT UNIQUE,
                in_stock INTEGER NOT NULL DEFAULT 1,snapshot TEXT NOT NULL,last_seen_at TEXT,version INTEGER NOT NULL DEFAULT 1,
                added_at TEXT,label_state TEXT NOT NULL DEFAULT 'rfid',completed_at TEXT);
            CREATE TABLE favorites(id TEXT PRIMARY KEY,name TEXT NOT NULL COLLATE NOCASE UNIQUE,main TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'favorite');""")
        for identifier,date,stock,ended in [('unknown',None,1,None),('recent','2026-10-20T10:00:00+00:00',1,None),('old','2026-09-01T10:00:00+00:00',0,'2026-10-10T10:00:00+00:00')]:
            item=spool_snapshot(MAIN,{})
            db.execute('INSERT INTO spools VALUES(?,?,?,?,?,?,?,?,?,?)',(identifier,item['instance_uuid'],None,stock,json.dumps(item),'2026-10-20T11:00:00+00:00',7,date,'qr',ended))
        db.execute('INSERT INTO favorites VALUES(?,?,?,?,?,?)',('model','Keep model',json.dumps(MAIN),4,'2026-10-20T11:00:00+00:00','model'))
        return db.execute('SELECT * FROM spools ORDER BY id').fetchall(),db.execute('SELECT * FROM favorites').fetchall()


def test_v3_migration_assigns_numbers_without_rewriting_old_data(tmp_path):
    path=tmp_path/'old.sqlite3';before,models=v3_database(path)
    s=Store(path)
    assert [s.get_spool(x)['spool_number'] for x in ('old','recent','unknown')]==['B0000','B0001','B0002']
    with s.connect() as db:
        old_columns='id,instance_uuid,uid,in_stock,snapshot,last_seen_at,version,added_at,label_state,completed_at'
        assert [tuple(r) for r in db.execute('SELECT '+old_columns+' FROM spools ORDER BY id')]==before
        assert [tuple(r) for r in db.execute('SELECT * FROM favorites')]==models
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]=='5'
    assert s.get_spool('unknown')['added_at'] is None
    assert s.completed_count()==1 and s.inventory_notes()=={'text':'','revision':0,'updated_at':None}
    assert all(x['notes']=='' and x['notes_revision']==0 for x in s.list_spools(include_removed=True))
    assert Store(path).create_packaged(MAIN,{})['spool_number']=='B0003'


def test_concurrent_startups_migrate_once(tmp_path):
    for attempt in range(5):
        path=tmp_path/f'old-{attempt}.sqlite3';v3_database(path)
        barrier=threading.Barrier(8)
        def open_store(_):
            barrier.wait(timeout=5)
            return [(x['id'],x['spool_number']) for x in Store(path).list_spools(include_removed=True)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            snapshots=list(pool.map(open_store,range(8)))
        assert all(x==snapshots[0] for x in snapshots)


def test_failed_v3_migration_rolls_back_every_column_and_counter(tmp_path):
    path=tmp_path/'old.sqlite3';before,_=v3_database(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER fail_migration BEFORE UPDATE ON metadata WHEN NEW.key='schema_version' BEGIN SELECT RAISE(ABORT,'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM spools ORDER BY id').fetchall()==before
        assert 'sequence_number' not in {r[1] for r in db.execute('PRAGMA table_info(spools)')}
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]=='3'
        assert db.execute("SELECT value FROM metadata WHERE key='next_spool_number'").fetchone() is None
        assert db.execute("SELECT name FROM sqlite_master WHERE name='inventory_notes'").fetchone() is None


def test_notes_preserve_whitespace_unicode_and_do_not_touch_tag_data(station,monkeypatch):
    app,client=station
    a=packaged(client)
    def no_io(*args,**kwargs):pytest.fail('Notes must not access hardware')
    monkeypatch.setattr(app.state.reader,'read',no_io);monkeypatch.setattr(app.state.reader,'write',no_io)
    monkeypatch.setattr(app.state.label_printer,'print',no_io)
    common=client.put('/api/inventory/notes',json={'text':TEXT,'revision':0})
    assert common.status_code==200 and common.json()['text']==TEXT and common.json()['revision']==1
    updated=client.put('/api/inventory/'+a['id']+'/notes',json={'text':TEXT,'revision':0}).json()
    assert updated['notes']==TEXT and updated['notes_revision']==1 and updated['notes_updated_at']
    for key in ('main','aux','version','spool_number','uid','instance_uuid','added_at','in_stock'):
        assert updated[key]==a[key]
    assert client.get('/api/inventory?search=indicative').json()['items']==[updated]
    assert Store(app.state.settings.database).get_spool(a['id'])==updated
    assert Store(app.state.settings.database).inventory_notes()==common.json()
    assert not app.state.store.favorites()
    assert client.put('/api/inventory/notes',json={'text':TEXT,'revision':1}).json()==common.json()
    assert client.put('/api/inventory/'+a['id']+'/notes',json={'text':TEXT,'revision':1}).json()==updated


def test_notes_revisions_are_independent_of_rfid_readings_and_archives(station):
    app,client=station
    tag=client.get('/api/reader/tag').json()
    a=client.post('/api/inventory/add',json={'expected_uid':tag['uid'],'expected_revision':tag['revision']}).json()
    for _ in range(3):client.get('/api/reader/tag')
    updated=client.put('/api/inventory/'+a['id']+'/notes',json={'text':TEXT,'revision':0})
    assert updated.status_code==200 and updated.json()['notes_revision']==1
    b=updated.json();assert b['version']>a['version'] and b['spool_number']==a['spool_number']
    removed=client.post('/api/inventory/'+a['id']+'/remove',json={'version':b['version']}).json()
    restored=client.post('/api/inventory/'+a['id']+'/restore',json={'version':removed['version']}).json()
    ended=client.post('/api/inventory/'+a['id']+'/complete',json={'version':restored['version']}).json()
    assert ended['notes']==TEXT and ended['spool_number']==a['spool_number']
    edited=client.put('/api/inventory/'+a['id']+'/notes',json={'text':'Archives : conserver la tare.','revision':1})
    assert edited.status_code==200 and edited.json()['completed_at']==ended['completed_at']
    assert app.state.store.completed_count()==1


@pytest.mark.parametrize('personal',[False,True])
def test_notes_stale_versions_do_not_overwrite(station,personal):
    app,client=station;a=packaged(client)
    url='/api/inventory/'+a['id']+'/notes' if personal else '/api/inventory/notes'
    first=client.put(url,json={'text':'First','revision':0});assert first.status_code==200
    assert client.put(url,json={'text':'Stale','revision':0}).status_code==409
    assert client.put(url,json={'text':'First','revision':0}).status_code==409
    current=client.get('/api/inventory/'+a['id']).json()['notes'] if personal else client.get(url).json()['text']
    assert current=='First'


@pytest.mark.parametrize('personal',[False,True])
def test_two_clients_cannot_silently_overwrite_notes(station,personal):
    app,client=station;a=packaged(client);barrier=threading.Barrier(2)
    def save(text):
        barrier.wait(timeout=5)
        try:
            if personal:app.state.store.save_spool_notes(a['id'],text,0)
            else:app.state.store.save_inventory_notes(text,0)
            return True
        except ConflictError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(save,['one','two']))==[False,True]


@pytest.mark.parametrize('body',[{'text':'x','revision':True},{'text':'x','revision':'0'},{'text':'x','revision':-1},{'text':3,'revision':0},{'text':'x'},{'text':'x','revision':0,'spool_number':'B0123'},{'text':'\x00','revision':0},{'text':'x'*(MAX_NOTES_LENGTH+1),'revision':0}])
def test_invalid_notes_cannot_change_either_notebook(station,body):
    app,client=station;a=packaged(client)
    assert client.put('/api/inventory/notes',json=body).status_code==422
    assert client.put('/api/inventory/'+a['id']+'/notes',json=body).status_code==422
    assert app.state.store.get_spool(a['id'])==a and app.state.store.inventory_notes()['revision']==0


def test_missing_spool_and_json_origin_host_and_power_checks(station):
    app,client=station;a=packaged(client)
    assert client.put('/api/inventory/missing/notes',json={'text':'x','revision':0}).status_code==404
    for url in ('/api/inventory/notes','/api/inventory/'+a['id']+'/notes'):
        assert client.put(url,json={'text':'x','revision':0},headers={'Origin':'http://evil.invalid'}).status_code==403
        assert client.put(url,json={'text':'x','revision':0},headers={'Host':'evil.invalid'}).status_code==400
        assert client.put(url,content='{}',headers={'Content-Type':'text/plain'}).status_code==415
    app.state.station_power.phase='requested'
    assert client.put('/api/inventory/notes',json={'text':'x','revision':0}).status_code==503
    assert client.put('/api/inventory/'+a['id']+'/notes',json={'text':'x','revision':0}).status_code==503
    assert app.state.store.get_spool(a['id'])==a and app.state.store.inventory_notes()['revision']==0


def test_inventory_mode_can_edit_notes_and_disabled_mode_cannot_read_them(station):
    app,local=station;a=packaged(local)
    with TestClient(app,client=('192.0.2.42',1)) as remote:
        assert remote.put('/api/inventory/notes',json={'text':TEXT,'revision':0}).status_code==200
        assert remote.put('/api/inventory/'+a['id']+'/notes',json={'text':TEXT,'revision':0}).status_code==200
        local.put('/api/configuration/network',json={'mode':'disabled'})
        for url in ('/api/inventory/notes','/api/inventory/'+a['id']):assert remote.get(url).status_code==403
        assert remote.put('/api/inventory/notes',json={'text':'bad','revision':1}).status_code==403
        assert remote.get('/api/status').json()['inventory_notes_revision'] is None
        assert remote.get('/api/status').json()['inventory_revision'] is None
        assert local.get('/api/inventory/notes').json()['text']==TEXT


def test_mcp_reads_both_notes_and_number_without_exposing_note_writes(station,monkeypatch):
    app,client=station;a=packaged(client)
    app.state.store.save_inventory_notes(TEXT,0)
    b=app.state.store.save_spool_notes(a['id'],'<script>do not execute</script>\nIndicatif : 250 g.',0)
    config=client.get('/api/configuration/mcp').json()
    client.put('/api/configuration/mcp',json={'enabled':True,'revision':config['revision']})
    monkeypatch.setattr(app.state.reader,'read',lambda:pytest.fail('MCP must not read hardware'))
    assert content(rpc(client,'get_inventory_notes'))['text']==TEXT
    assert content(rpc(client,'get_spool',{'identifier':'B0000'}))==b
    assert content(rpc(client,'list_inventory',{'search':'B0000'}))['items']==[b]
    assert content(rpc(client,'list_inventory',{'search':'Indicatif'}))['items']==[b]
    for tool in ('set_inventory_notes','update_spool_notes','write_notes'):
        assert rpc(client,tool).get('isError')
    assert app.state.store.favorites()==[]


def test_prepare_from_inventory_without_qr_preserves_number_notes_and_full_precision(station,monkeypatch):
    app,client=station
    a=client.post('/api/inventory/packaged',json={'main':MAIN,'aux':{'purchase_time':2**53+11}}).json()
    b=app.state.store.save_spool_notes(a['id'],TEXT,0)
    tag=client.post('/api/simulator/blank',json={}).json()
    def no_qr(*args,**kwargs):pytest.fail('Direct inventory preparation must not render, scan or encode a QR')
    monkeypatch.setattr('openprinttag_app.app.encode_spool',no_qr)
    monkeypatch.setattr(app.state.label_printer,'preview',no_qr)
    prepared=client.post('/api/reader/prepare',json={'mode':'create','main':{},'aux':{},'expected_uid':tag['uid'],'expected_revision':tag['revision'],'inventory_id':a['id'],'inventory_version':a['version']})
    assert prepared.status_code==200,prepared.text
    # A note edited after preview must neither invalidate NFC data nor be lost.
    b=app.state.store.save_spool_notes(a['id'],TEXT+'\nNote après préparation.',1)
    written=client.post('/api/reader/write',json={'preview_id':prepared.json()['preview_id']})
    assert written.status_code==200,written.text
    current=app.state.store.get_spool(a['id'])
    assert current['label_state']=='rfid' and current['uid']==tag['uid']
    for key in ('id','instance_uuid','spool_number','added_at','main','aux','notes','notes_revision'):
        assert current[key]==b[key]
    assert current['aux']['purchase_time']==2**53+11
    assert len(app.state.store.list_spools())==1
    assert 'notes' not in written.json()['tag']['main'] and 'notes' not in written.json()['tag']['aux']


@pytest.mark.parametrize('personal',[False,True])
def test_notes_accept_the_documented_unicode_length_boundary(station,personal):
    app,client=station;a=packaged(client)
    text='🧵'*MAX_NOTES_LENGTH
    url='/api/inventory/'+a['id']+'/notes' if personal else '/api/inventory/notes'
    response=client.put(url,json={'text':text,'revision':0})
    assert response.status_code==200,response.text
    assert response.json()['notes' if personal else 'text']==text


def test_direct_preparation_rejects_wrong_identity_stale_version_and_completed_stock(station):
    app,client=station;a=packaged(client)
    tag=client.post('/api/simulator/blank',json={}).json()
    base={'mode':'create','main':{},'aux':{},'expected_uid':tag['uid'],'expected_revision':tag['revision'],'inventory_id':a['id'],'inventory_version':a['version']}
    assert client.post('/api/reader/prepare',json={**base,'inventory_version':2}).status_code==409
    assert client.post('/api/reader/prepare',json={**base,'main':{'instance_uuid':str(uuid.uuid4())}}).status_code==409
    client.post('/api/inventory/'+a['id']+'/complete',json={'version':a['version']})
    assert client.post('/api/reader/prepare',json={**base,'inventory_version':2}).status_code==409
    assert client.get('/api/reader/tag').json()['blank']


def test_label_has_readable_number_and_the_same_complete_qr(station,tmp_path,monkeypatch):
    app,client=station;a=packaged(client)
    a=app.state.store.save_spool_notes(a['id'],TEXT,0)
    from PIL import ImageDraw
    observed=[];original=ImageDraw.ImageDraw.text
    def draw(self,xy,text,*args,**kwargs):observed.append(text);return original(self,xy,text,*args,**kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw,'text',draw)
    preview=app.state.label_printer.preview(a)
    assert 'B0000' in observed
    zxing=pytest.importorskip('zxingcpp')
    barcode=zxing.read_barcode(Image.open(io.BytesIO(preview['png'])))
    assert barcode and barcode.text==preview['text']
    decoded=decode_spool(barcode.text)
    assert decoded['main']==a['main'] and decoded['aux']==a['aux']
    assert 'notes' not in decoded and 'spool_number' not in decoded
