"""Sealed stock -> self-contained printed QR -> verified NFC, never real I/O."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import sqlite3
import uuid
import zlib

import cbor2
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import DomainError, TagImage, spool_snapshot
from openprinttag_app.labels import DEFAULTS, render_label, validate_settings
from openprinttag_app.niimbot import Niimbot, LabelError, packet
from openprinttag_app.spool_qr import encode_spool, decode_spool
from openprinttag_app.storage import Store

MAIN = {"material_class": "FFF", "brand_name": "Essai", "material_type": "PETG",
        "material_name": "Bobine fermée", "nominal_netto_full_weight": 1000,
        "actual_netto_full_weight": 1025, "empty_container_weight": 278,
        "primary_color": "#3b353a", "filament_diameter": 1.75,
        "min_print_temperature": 255, "max_print_temperature": 275}
AUX = {"consumed_weight": 0, "storage_location": "Atelier"}


@pytest.fixture
def station(tmp_path):
    calls = []
    def runner(action, config, png=None):
        calls.append((action, config, png))
        if action == "probe":
            return {"status": "identified", "model_id": 272, "model": "b3s_p", "name": "NIIMBOT B3S_P"}
        return {"status": "complete", "detail": "Étiquette terminée."}
    app = create_app(Settings(tmp_path, network_enabled=True), label_runner=runner)
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        yield app, client, calls


def add(client, main=None, aux=None):
    response = client.post('/api/inventory/packaged', json={'main': main or MAIN, 'aux': aux if aux is not None else AUX})
    assert response.status_code == 200, response.text
    return response.json()


def identity(tag):
    return {'expected_uid': tag['uid'], 'expected_revision': tag['revision']}


def prepare(client, item):
    raw = client.get(f"/api/inventory/{item['id']}/qr?version={item['version']}").json()['text']
    tag = client.post('/api/simulator/blank', json={}).json()
    response = client.post('/api/reader/prepare', json={**identity(tag), 'mode':'create', 'main':{}, 'aux':{},
        'qr_raw':raw, 'inventory_id':item['id'], 'inventory_version':item['version']})
    assert response.status_code == 200, response.text
    return response.json(), raw


def label(client, item):
    result = client.get(f"/api/inventory/{item['id']}/label?version={item['version']}")
    assert result.status_code == 200, result.text
    return result.json()


def print_body(preview):
    return {'version': preview['item']['version'], 'settings_revision': preview['settings_revision'],
            'image_sha256': preview['image_sha256'], 'request_id':str(uuid.uuid4())}


def enable(client):
    result = client.put('/api/configuration/labels', json={**DEFAULTS,'port':'/dev/ttyACM0','enabled':True})
    assert result.status_code == 200, result.text
    return result.json()


def test_arrival_without_tag_and_distinct_physical_spools(station):
    app, client, calls = station
    a, b = add(client), add(client)
    assert a['id'] != b['id'] and a['instance_uuid'] != b['instance_uuid']
    assert a['uid'] is None and a['last_seen_at'] is None and a['label_state'] == 'qr'
    assert a['age_days'] == 0 and a['added_at'] and a['remaining_weight'] == 1025
    assert len(client.get('/api/inventory').json()['items']) == 2 and not calls
    unknown = add(client, aux={})
    assert unknown['remaining_weight'] is None
    assert 'consumed_weight' not in unknown['aux']


def test_printable_qr_decodes_all_fields_without_catalogue_or_network(station, monkeypatch):
    _, client, _ = station
    item = add(client)
    preview = label(client, item)
    png = base64.b64decode(preview['image'].split(',')[1])
    image = Image.open(io.BytesIO(png))
    assert image.size == (560, 320) and image.mode == '1'
    assert preview['module_pixels'] >= 3
    zxing = pytest.importorskip('zxingcpp')
    result = zxing.read_barcode(image)
    assert result is not None and result.text == preview['text']
    decoded = decode_spool(result.text)
    assert decoded['main'] == item['main'] and decoded['aux'] == item['aux']
    assert decoded['added_at'] == item['added_at']
    from openprinttag_app import qr
    monkeypatch.setattr(qr, '_load_catalogue', lambda: pytest.fail('Aucun catalogue requis'))
    inspected = client.post('/api/qr/inspect', json={'text':result.text}).json()
    assert inspected['kind'] == 'opt_station' and inspected['inventory']['id'] == item['id']


def test_codec_preserves_large_integers_float_precision_absence_and_all_value_types():
    main = {**MAIN, 'instance_uuid':str(uuid.uuid4()), 'package_uuid':str(uuid.uuid4()),
            'brand_specific_instance_id':'lot-étiquette', 'manufactured_date':1775012345,
            'density':1.2345678901234567, 'primary_color_lab':[15.125,-2.5,1.75], 'tags':['contains_carbon_fiber']}
    # The field definitions, rather than a hand-picked minimal label schema, govern all data.
    from openprinttag_app.domain import get_schema
    tag_option = next(f for f in get_schema()['main'] if f['name']=='tags')['options'][0]['value']
    main['tags'] = [tag_option]
    item = spool_snapshot(main, {'purchase_time':2**53 + 11})
    encoded = encode_spool(item)
    decoded = decode_spool(encoded)
    assert decoded['main'] == item['main'] and decoded['aux'] == item['aux']
    assert decoded['aux']['purchase_time'] == 2**53 + 11
    assert decoded['remaining_weight'] is None
    assert encode_spool(decoded) == encoded


@pytest.mark.parametrize('damage', ['checksum','truncated','future','bomb','trailing'])
def test_corrupt_or_unbounded_qr_is_rejected(damage):
    text = encode_spool(spool_snapshot(MAIN, AUX))
    if damage == 'checksum': text = text[:-1] + ('0' if text[-1]!='0' else '1')
    elif damage == 'truncated': text = text[:-12]
    elif damage == 'future': text = text.replace('OPT1:','OPT2:')
    else:
        data = b'x' * 100000 if damage == 'bomb' else cbor2.dumps({0:1}) + b'x'
        text = 'OPT1:' + base64.b32encode(zlib.compress(data)).decode().rstrip('=') + '.' + hashlib.sha256(data).hexdigest()[:16].upper()
    with pytest.raises(DomainError): decode_spool(text)


def test_verified_nfc_association_preserves_identity_date_and_stock_count(station):
    app, client, _ = station
    item = add(client)
    preview, raw = prepare(client, item)
    assert client.get('/api/inventory').json()['items'][0]['label_state'] == 'qr'
    result = client.post('/api/reader/write', json={'preview_id':preview['preview_id']})
    assert result.status_code == 200, result.text
    observed = result.json()['tag']
    current = client.get(f"/api/inventory/{item['id']}").json()
    assert current['label_state'] == 'rfid' and current['uid'] == observed['uid']
    assert current['instance_uuid'] == item['instance_uuid'] and current['added_at'] == item['added_at']
    assert current['main'] == item['main'] and current['aux'] == item['aux']
    assert len(client.get('/api/inventory').json()['items']) == 1
    assert client.post('/api/qr/inspect', json={'text':raw}).status_code == 409
    consumed = client.post('/api/simulator/consume', json={'amount_g':100})
    assert consumed.status_code == 200
    client.get('/api/reader/tag')
    assert client.post('/api/qr/inspect', json={'text':raw}).status_code == 409
    assert client.get(f"/api/inventory/{item['id']}").json()['aux']['consumed_weight'] == 100


def test_stock_changed_after_preview_refuses_write_before_touching_tag(station):
    _, client, _ = station
    item = add(client)
    preview, _ = prepare(client, item)
    assert client.post(f"/api/inventory/{item['id']}/remove",json={'version':item['version']}).status_code == 200
    result = client.post('/api/reader/write',json={'preview_id':preview['preview_id']})
    assert result.status_code == 409
    assert client.get('/api/reader/tag').json()['blank']


def test_uncertain_write_does_not_mark_rfid_and_recovery_reads_without_rewriting(station, monkeypatch):
    app, client, _ = station
    item = add(client)
    preview, _ = prepare(client, item)
    original = app.state.reader.write
    def interrupted(image):
        original(image)
        raise RuntimeError('liaison interrompue après écriture')
    monkeypatch.setattr(app.state.reader,'write',interrupted)
    result = client.post('/api/reader/write',json={'preview_id':preview['preview_id']})
    assert result.status_code == 503
    assert client.get(f"/api/inventory/{item['id']}").json()['label_state'] == 'qr'
    tag = client.get('/api/reader/tag').json()
    assert not tag['blank']
    result = client.post(f"/api/inventory/{item['id']}/associate",json={**identity(tag),'version':item['version']})
    assert result.status_code == 200, result.text
    assert result.json()['label_state'] == 'rfid' and result.json()['added_at'] == item['added_at']


def test_full_qr_does_not_lose_unsafe_javascript_integer_during_write(station):
    _, client, _ = station
    item = add(client, main={'material_class':'FFF'}, aux={'purchase_time':2**53+11})
    preview, _ = prepare(client, item)
    assert preview['tag']['aux']['purchase_time'] == 2**53+11


def test_qr_can_rebuild_arrival_on_a_second_station_and_not_duplicate(station, tmp_path):
    _, client, _ = station
    item = add(client)
    raw = client.get(f"/api/inventory/{item['id']}/qr?version=1").json()['text']
    second = create_app(Settings(tmp_path/'second'))
    with TestClient(second,client=('127.0.0.1',1)) as other:
        result = other.post('/api/inventory/packaged',json={'main':{},'qr_raw':raw})
        assert result.status_code == 200,result.text
        copy = result.json()
        assert copy['main'] == item['main'] and copy['aux'] == item['aux'] and copy['added_at'] == item['added_at']
        assert other.post('/api/inventory/packaged',json={'main':{},'qr_raw':raw}).status_code == 409


def test_legacy_migration_keeps_data_without_fabricating_arrival_and_sort_is_fifo(tmp_path):
    path = tmp_path/'inventory.sqlite3'
    snapshot = TagImage.create('E004015023456789',MAIN,AUX).snapshot()
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); INSERT INTO metadata VALUES('schema_version','1'); CREATE TABLE spools(id TEXT PRIMARY KEY,instance_uuid TEXT NOT NULL UNIQUE,uid TEXT NOT NULL UNIQUE,in_stock INTEGER NOT NULL DEFAULT 1,snapshot TEXT NOT NULL,last_seen_at TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);")
        db.execute('INSERT INTO spools VALUES(?,?,?,?,?,?,?)',('old',snapshot['instance_uuid'],snapshot['uid'],1,json.dumps(snapshot),'2026-10-20T10:00:00+00:00',7))
    store = Store(path)
    legacy = store.get_spool('old')
    assert legacy['added_at'] is None and legacy['age_days'] is None and legacy['version'] == 7
    assert legacy['main'] == snapshot['main'] and legacy['label_state'] == 'rfid'
    older_date = (datetime.now(timezone.utc)-timedelta(days=40)).isoformat()
    a = store.create_packaged(MAIN,AUX,older_date)
    b = store.create_packaged(MAIN,AUX)
    assert [x['id'] for x in store.list_spools(sort='oldest')] == [a['id'],b['id'],'old']
    assert Store(path).get_spool(a['id'])['added_at'] == older_date
    store.observe(snapshot)
    assert store.get_spool('old')['added_at'] is None
    removed = store.remove('old',store.get_spool('old')['version'])
    store.add(snapshot)
    assert store.get_spool('old')['added_at'] is None


def test_label_config_print_dedup_and_no_stock_or_nfc_mutation(station):
    app, client, calls = station
    enable(client)
    item = add(client)
    preview = label(client,item)
    body = print_body(preview)
    assert client.post('/api/labels/probe',json={}).json()['model_id'] == 272
    result = client.post(f"/api/inventory/{item['id']}/print",json=body)
    assert result.status_code == 200 and result.json()['status'] == 'complete'
    assert client.post(f"/api/inventory/{item['id']}/print",json=body).json() == result.json()
    assert sum(x[0]=='print' for x in calls) == 1
    assert client.get(f"/api/inventory/{item['id']}").json() == item
    assert (app.state.settings.data_dir/'label-printer-settings.json').stat().st_mode & 0o777 == 0o600
    assert client.put('/api/configuration/labels',json={**DEFAULTS,'port':'/dev/ttyACM0'}).status_code == 409
    bad = {**body,'image_sha256':'f'*64}
    assert client.post(f"/api/inventory/{item['id']}/print",json=bad).status_code == 409


def test_old_preview_settings_or_picture_cannot_print(station):
    _, client, calls = station
    enable(client); item = add(client); preview = label(client,item)
    settings = {**DEFAULTS,'revision':1,'enabled':True,'port':'/dev/ttyACM0','height_mm':50}
    assert client.put('/api/configuration/labels',json=settings).status_code == 200
    assert client.post(f"/api/inventory/{item['id']}/print",json=print_body(preview)).status_code == 409
    fresh = label(client,item); body = print_body(fresh); body['image_sha256'] = 'f'*64
    assert client.post(f"/api/inventory/{item['id']}/print",json=body).status_code == 409
    assert not calls


def test_print_exception_is_uncertain_and_not_repeated_after_restart(station):
    app, client, _ = station
    enable(client); item=add(client); preview=label(client,item); body=print_body(preview)
    def broken(*args): raise TimeoutError()
    app.state.label_printer.runner = broken
    result=client.post(f"/api/inventory/{item['id']}/print",json=body)
    assert result.json()['status'] == 'uncertain'
    restarted=create_app(app.state.settings,label_runner=lambda *args:pytest.fail('Pas de répétition'))
    with TestClient(restarted,client=('127.0.0.1',1)) as fresh:
        assert fresh.post(f"/api/inventory/{item['id']}/print",json=body).json()['status'] == 'uncertain'


def test_remote_inventory_can_create_qr_but_hardware_needs_full_access(station):
    app, _, calls = station
    with TestClient(app,client=('192.0.2.42',1)) as remote:
        item=add(remote); preview=label(remote,item)
        assert remote.get('/api/configuration/labels').status_code == 403
        assert remote.post('/api/labels/probe',json={}).status_code == 403
        assert remote.post(f"/api/inventory/{item['id']}/print",json=print_body(preview)).status_code == 403
        assert remote.put('/api/configuration/network',json={'mode':'full'}).status_code == 200
        enable(remote)
        assert remote.post('/api/labels/probe',json={}).status_code == 200
        remote.put('/api/configuration/network',json={'mode':'disabled'})
        assert remote.post('/api/inventory/packaged',json={'main':MAIN}).status_code == 403


def test_dense_qr_or_unknown_fields_never_drop_information():
    item=spool_snapshot(MAIN,AUX)
    item['unknown_fields']['main']=[99]
    with pytest.raises(DomainError): encode_spool(item)
    item=spool_snapshot(MAIN,AUX)
    with pytest.raises(DomainError): render_label(item,{**DEFAULTS,'width_mm':20,'height_mm':20})
    for port in ('/etc/passwd','/dev/serial/by-id/../../secret','/dev/ttyAMA10'):
        with pytest.raises(DomainError): validate_settings({**DEFAULTS,'port':port})


class FakeUSB:
    def __init__(self, model_id=272):
        self.pending=bytearray();self.writes=[];self.model_id=model_id;self.ended=False
    def write(self,wire):
        length=len(wire)
        if wire.startswith(b"\x03\x55\x55"): wire=wire[1:]
        self.writes.append(wire)
        command=wire[2]
        replies={0xC1:(0xC2,b'\x03'),0x15:(0x16,b'\x01'),0x40:(0x48,self.model_id.to_bytes(2,'big')),0x21:(0x31,b'\x01'),0x23:(0x33,b'\x01'),0x01:(0x02,b'\x01'),0x03:(0x04,b'\x01'),0x13:(0x14,b'\x01\x00'),0xE3:(0xE4,b'\x01'),0xF3:(0xF4,b'\x01')}
        if command == 0xE3:
            self.ended=True;self.pending.extend(packet(0xE0,b'\0\x01'))
        if command == 0xA3:
            self.pending.extend(packet(0xB3,b'\0\x01\x64\x64' if self.ended else b'\0\0\0\0'))
        elif command in replies: self.pending.extend(packet(*replies[command]))
        return length
    def read(self,n):
        part=self.pending[:3];del self.pending[:3];return bytes(part)
    def close(self): pass


def test_niimbot_identification_and_single_page_frames_with_split_responses():
    transport=FakeUSB();printer=Niimbot('',transport=transport)
    image=Image.new('1',(560,8),1);image.putpixel((3,2),0)
    result=printer.print_image(image,'b3s_p')
    assert result['status']=='complete'
    assert sum(w[2]==0x01 for w in transport.writes)==1
    size=next(w for w in transport.writes if w[2]==0x13)
    assert size[4:-3] == b'\0\x08\x02\x30'
    bitmap=next(w for w in transport.writes if w[2]==0x85 and w[4:6]==b'\0\x02')
    assert bitmap[4:10] == b'\0\x02\0\x01\0\x01'
    assert bitmap[10] == 0x10
    assert packet(0x40,b'\x08') == bytes.fromhex('555540010849aaaa')
    transport=FakeUSB(model_id=4096);printer=Niimbot('',transport=transport)
    with pytest.raises(LabelError): printer.print_image(image,'b3s_p')
    assert not any(w[2]==0x01 for w in transport.writes)


def test_recovery_retains_explicit_changes_from_confirmed_proposal(station, monkeypatch):
    app, client, _ = station
    item=add(client)
    blank=client.post('/api/simulator/blank',json={}).json()
    raw=client.get(f"/api/inventory/{item['id']}/qr?version=1").json()['text']
    proposal=client.post('/api/reader/prepare',json={**identity(blank),'mode':'create','main':{'brand_name':'Corrigée'},'qr_raw':raw,'inventory_id':item['id'],'inventory_version':1}).json()
    original=app.state.reader.write
    def interrupted(image): original(image); raise TimeoutError()
    monkeypatch.setattr(app.state.reader,'write',interrupted)
    assert client.post('/api/reader/write',json={'preview_id':proposal['preview_id']}).status_code == 503
    tag=client.get('/api/reader/tag').json()
    assert tag['main']['brand_name']=='Corrigée'
    result=client.post(f"/api/inventory/{item['id']}/associate",json={**identity(tag),'version':1})
    assert result.status_code==200,result.text
    assert result.json()['main']['brand_name']=='Corrigée' and result.json()['added_at']==item['added_at']


def test_removed_qr_can_be_restocked_without_new_identity_or_arrival(station):
    _, client, _=station
    item=add(client)
    raw=client.get(f"/api/inventory/{item['id']}/qr?version=1").json()['text']
    removed=client.post(f"/api/inventory/{item['id']}/remove",json={'version':1}).json()
    report=client.post('/api/qr/inspect',json={'text':raw}).json()
    assert report['inventory']['in_stock'] is False and report['inventory']['id']==item['id']
    restored=client.post(f"/api/inventory/{item['id']}/restore",json={'version':removed['version']})
    assert restored.status_code==200
    assert restored.json()['added_at']==item['added_at'] and restored.json()['instance_uuid']==item['instance_uuid']
    assert len(client.get('/api/inventory').json()['items'])==1


def test_qr_identity_cannot_be_reused_as_unbound_manual_creation(station):
    _,client,_=station
    item=add(client)
    blank=client.post('/api/simulator/blank',json={}).json()
    result=client.post('/api/reader/prepare',json={**identity(blank),'mode':'create','main':item['main'],'aux':item['aux']})
    assert result.status_code==409
    assert client.get('/api/reader/tag').json()['blank']


def test_pending_label_job_is_marked_uncertain_after_app_restart(station):
    app,client,_=station
    enable(client);item=add(client);preview=label(client,item);body=print_body(preview)
    app.state.store.begin_label_job(body['request_id'],item,preview['settings_revision'],preview['image_sha256'])
    restarted=create_app(app.state.settings,label_runner=lambda *args:pytest.fail('Pas de répétition après interruption'))
    with TestClient(restarted,client=('127.0.0.1',1)) as fresh:
        response=fresh.post(f"/api/inventory/{item['id']}/print",json=body)
        assert response.json()['status']=='uncertain'


@pytest.mark.parametrize('payload',[b'\x9b'+b'\xff'*8,b'\x81'*20+b'\x00',b'\xc0\x00'])
def test_qr_checks_declared_cbor_sizes_depth_and_tags_before_decoding(payload):
    text='OPT1:'+base64.b32encode(zlib.compress(payload)).decode().rstrip('=')+'.'+hashlib.sha256(payload).hexdigest()[:16].upper()
    with pytest.raises(DomainError):decode_spool(text)
