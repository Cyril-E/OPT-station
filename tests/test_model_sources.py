"""Reusable models from decoded QR and NFC sources, never copies of a spool."""
from copy import deepcopy
import json
from unittest.mock import Mock
import uuid

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.domain import DomainError, TagImage, reusable_profile, spool_snapshot
from openprinttag_app.prusament import PrusamentError
from openprinttag_app.readers import ReaderUnavailable
from openprinttag_app.spool_qr import encode_spool

MAIN = {'material_class':'FFF','material_type':'PETG','brand_name':'Exemple','material_name':'PETG test',
        'primary_color':'#123456','nominal_netto_full_weight':1000,'empty_container_weight':245,
        'filament_diameter':1.75,'min_print_temperature':230,'max_print_temperature':250,
        'actual_netto_full_weight':1025,'actual_full_length':335000,'brand_specific_instance_id':'LOT-UNIQUE',
        'manufactured_date':1775012345,'expiration_date':1806548345}
AUX = {'consumed_weight':637,'storage_location':'Atelier','workgroup':'Perso'}
EXCLUDED = {'instance_uuid','brand_specific_instance_id','actual_netto_full_weight','actual_full_length',
            'manufactured_date','expiration_date','write_protection'}


@pytest.fixture
def station(tmp_path):
    app=create_app(Settings(tmp_path,network_enabled=True))
    with TestClient(app,client=('127.0.0.1',1)) as client:yield app,client


def test_projection_preserves_known_reusable_values_and_does_not_invent_missing_ones():
    main={**MAIN,'instance_uuid':str(uuid.uuid4()),'package_uuid':str(uuid.uuid4()),'write_protection':'not copied'}
    before=deepcopy(main),deepcopy(AUX)
    result=reusable_profile(main,AUX)
    assert result['main']=={k:v for k,v in main.items() if k not in EXCLUDED}
    assert result['main']['empty_container_weight']==245 and result['main']['nominal_netto_full_weight']==1000
    assert result['suggested_name']=='PETG test'
    assert set(result['excluded_fields'])=={f'main.{k}' for k in main if k in EXCLUDED}|{f'aux.{k}' for k in AUX}
    assert (main,AUX)==before
    partial=reusable_profile({'brand_name':'Inconnu','material_type':'PLA'}, {})
    assert partial['main']=={'brand_name':'Inconnu','material_type':'PLA'}
    assert 'empty_container_weight' not in partial['main']


@pytest.mark.parametrize('main',[{}, {'actual_netto_full_weight':1000}, {'instance_uuid':str(uuid.uuid4())}])
def test_blank_or_individual_only_data_cannot_create_an_empty_model(main):
    with pytest.raises(DomainError,match='aucune donnée réutilisable'):reusable_profile(main,AUX)


def test_rfid_preview_is_read_only_and_saved_model_retains_user_edits(station,monkeypatch):
    app,client=station
    record=app.state.reader.read()
    image=TagImage.create(record['uid'],MAIN,AUX).to_bytes()
    with app.state.store.connect() as db:db.execute('UPDATE simulated_tags SET image=?,main_locked=1 WHERE uid=?',(image,record['uid']))
    tag=client.get('/api/reader/tag').json()
    client.post('/api/inventory/add',json={'expected_uid':tag['uid'],'expected_revision':tag['revision']}).raise_for_status()
    before=app.state.store.list_spools(include_removed=True)
    monkeypatch.setattr(app.state.reader,'write',Mock(side_effect=AssertionError('No RFID write')))
    monkeypatch.setattr(app.state.store,'observe',Mock(side_effect=AssertionError('No inventory observation')))
    response=client.post('/api/library/model-source',json={'source':'rfid','expected_uid':tag['uid'],'expected_revision':tag['revision']})
    assert response.status_code==200,response.text
    result=response.json();assert result['source']=='rfid' and not result['matches']
    assert not EXCLUDED&result['main'].keys() and 'aux' not in result
    assert result['main']['empty_container_weight']==245 and result['main']['nominal_netto_full_weight']==1000
    assert client.get('/api/favorites').json()['items']==[]
    assert app.state.store.list_spools(include_removed=True)==before and app.state.reader.read()['image']==image
    result['main']['empty_container_weight']=250
    saved=client.post('/api/favorites',json={'name':'Modèle RFID','kind':'model','main':result['main']})
    assert saved.status_code==200 and saved.json()['main']['empty_container_weight']==250
    assert saved.json()['kind']=='model' and app.state.store.list_spools(include_removed=True)==before
    assert app.state.reader.read()['image']==image


def test_changed_tag_is_rejected_instead_of_copying_another_spool(station):
    _,client=station
    tag=client.get('/api/reader/tag').json()
    client.post('/api/simulator/select',json={'uid':'E004010000000002'}).raise_for_status()
    response=client.post('/api/library/model-source',json={'source':'rfid','expected_uid':tag['uid'],'expected_revision':tag['revision']})
    assert response.status_code==409
    assert not client.get('/api/favorites').json()['items']


def test_blank_and_unavailable_rfid_have_explicit_errors(station,monkeypatch):
    app,client=station
    client.post('/api/simulator/blank',json={}).raise_for_status()
    assert client.post('/api/library/model-source',json={'source':'rfid'}).status_code==422
    monkeypatch.setattr(app.state.reader,'read',Mock(side_effect=ReaderUnavailable('Présentez un tag.')))
    assert client.post('/api/library/model-source',json={'source':'rfid'}).status_code==503
    assert not client.get('/api/favorites').json()['items']


def test_opt_qr_projection_is_offline_and_independent_from_spool_lifecycle(station,monkeypatch):
    app,client=station
    item=client.post('/api/inventory/packaged',json={'main':MAIN,'aux':AUX}).json()
    raw=encode_spool(item)
    client.post(f"/api/inventory/{item['id']}/complete",json={'version':item['version']}).raise_for_status()
    before=app.state.store.list_spools(include_removed=True)
    monkeypatch.setattr(app.state.reader,'read',Mock(side_effect=AssertionError('QR does not read hardware')))
    result=client.post('/api/library/model-source',json={'source':'qr','text':raw})
    assert result.status_code==200,result.text
    profile=result.json()['main'];assert not EXCLUDED&profile.keys()
    assert profile['material_name']=='PETG test' and profile['empty_container_weight']==245
    assert app.state.store.list_spools(include_removed=True)==before
    assert not client.get('/api/favorites').json()['items']


def test_prusament_preview_keeps_nominal_weight_and_omits_real_weight_and_dates(tmp_path):
    data={'ff_goods_id':12345,'country':'CZ','filament':{'name':'Prusament TPU 95A Jet Black 500g','material':'TPU 95A','color_rgb':'#232323'},
          'weight':510,'spool_weight':0,'length':171,'manufacture_date':'2026-07-28T15:17:37+02:00'}
    page='<script>var spoolData = \''+json.dumps(data)+"';</script>"
    fetch=Mock(return_value=page);app=create_app(Settings(tmp_path,network_enabled=True),prusament_fetch=fetch)
    with TestClient(app,client=('127.0.0.1',1)) as client:
        result=client.post('/api/library/model-source',json={'source':'qr','text':'https://prusament.com/spool/12345/012345abcd'}).json()
        assert result['main']['nominal_netto_full_weight']==500 and result['main']['material_type']=='TPU'
        assert not EXCLUDED&result['main'].keys() and 'empty_container_weight' not in result['main']
        assert len(result['warnings'])==1
        fetch.side_effect=PrusamentError('Indisponible',503)
        assert client.post('/api/library/model-source',json={'source':'qr','text':'https://prusament.com/spool/12345/012345abcd'}).status_code==503
        assert not client.get('/api/favorites').json()['items']


def test_unique_gtin_auto_profile_and_ambiguous_gtin_require_choice(station):
    _,client=station
    unique=client.post('/api/library/model-source',json={'source':'qr','text':'8594173672666'}).json()
    assert unique['main']['material_name']=='PLA CMYK Cyan' and not unique['matches']
    ambiguous=client.post('/api/library/model-source',json={'source':'qr','text':'8594173675292'}).json()
    assert ambiguous['main']=={} and len(ambiguous['matches'])==2
    for candidate in ambiguous['matches']:
        assert candidate['label'] and candidate['main']['material_name']=='PLA Prusa Orange'
        assert not EXCLUDED&candidate['main'].keys()
    assert not client.get('/api/favorites').json()['items']


@pytest.mark.parametrize('body',[
    {'source':'unknown'}, {'source':'qr'}, {'source':'qr','text':'   '},
    {'source':'qr','text':'x'*8193}, {'source':'rfid','text':'QR'},
    {'source':'rfid','expected_uid':'E004010000000001'},
    {'source':'qr','text':'8594173672666','expected_revision':'anything'},
    {'source':'qr','text':'QR','main':MAIN}, {'source':'qr','text':'https://example.com/spool/123'}])
def test_invalid_source_or_nonmapped_qr_never_access_hardware_or_save(station,monkeypatch,body):
    app,client=station;reader=Mock(side_effect=AssertionError('No read for malformed request'));monkeypatch.setattr(app.state.reader,'read',reader)
    result=client.post('/api/library/model-source',json=body)
    assert result.status_code==422,result.text
    reader.assert_not_called();assert not client.get('/api/favorites').json()['items']


def test_remote_inventory_can_import_qr_but_cannot_read_rfid(station,monkeypatch):
    app,local=station
    local.put('/api/configuration/network',json={'mode':'inventory'}).raise_for_status()
    read=Mock(side_effect=AssertionError('No remote hardware read'));monkeypatch.setattr(app.state.reader,'read',read)
    with TestClient(app,client=('192.0.2.42',1)) as remote:
        assert remote.post('/api/library/model-source',json={'source':'rfid'}).status_code==403
        assert remote.post('/api/library/model-source',json={'source':'qr','text':'8594173672666'}).status_code==200
        local.put('/api/configuration/network',json={'mode':'disabled'}).raise_for_status()
        assert remote.post('/api/library/model-source',json={'source':'qr','text':'8594173672666'}).status_code==403
    read.assert_not_called()


def test_source_preview_obeys_origin_json_and_power_guards(station,monkeypatch):
    app,client=station;read=Mock(side_effect=AssertionError('No read'));monkeypatch.setattr(app.state.reader,'read',read)
    assert client.post('/api/library/model-source',content='{}').status_code==415
    assert client.post('/api/library/model-source',json={'source':'rfid'},headers={'Origin':'https://other.example'}).status_code==403
    app.state.station_power.phase='requested'
    assert client.post('/api/library/model-source',json={'source':'rfid'}).status_code==503
    read.assert_not_called()


def test_existing_model_is_never_overwritten_by_saving_an_import_with_same_name(station):
    _,client=station
    original=client.post('/api/favorites',json={'name':'Unique model','kind':'model','main':{'brand_name':'Original'}}).json()
    profile=client.post('/api/library/model-source',json={'source':'qr','text':'8594173672666'}).json()
    assert client.post('/api/favorites',json={'name':'Unique model','kind':'model','main':profile['main']}).status_code==409
    assert client.get('/api/favorites').json()['items']==[original]
