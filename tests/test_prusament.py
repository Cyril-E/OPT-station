"""Prusament URL -> explicit manufacturer values -> reviewed stock entry."""
from copy import deepcopy
from datetime import datetime
from email.message import Message
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app import prusament

# Fictitious spool identity; all page responses are mocked.
URL = "https://prusament.com/spool/12345/012345abcd/"
DATA = {"ff_goods_id":12345,"country":"CZ","diameter_avg":0.06,
        "filament":{"color_name":"Jet Black","color_rgb":"#232323","material":"TPU 95A",
                    "name":"Prusament TPU 95A Jet Black 500g","he_min":220,"he_max":240,"hb_min":55,"hb_max":75},
        "length":171,"manufacture_date":"2026-07-28T15:17:37+02:00","weight":510,"spool_weight":0}


def page(data=None):
    return "<script>var spoolData = '"+json.dumps(DATA if data is None else data)+"'; var spoolFound = true;</script><div>Diameter<br><strong>1.75 mm</strong></div>"


def test_actual_spool_values_units_and_unknown_tare_consumption():
    report=prusament.resolve_prusament(URL.rstrip('/'),fetch=lambda url:page())
    main=report['main']
    assert report['raw']==URL.rstrip('/') and report['source_url']==URL and report['kind']=='prusament'
    assert main['material_type']=='TPU' and main['material_class']=='FFF' and main['brand_name']=='Prusament'
    assert main['material_name']==DATA['filament']['name'] and main['primary_color']=='#232323'
    assert main['nominal_netto_full_weight']==500 and main['actual_netto_full_weight']==510
    assert main['actual_full_length']==171000 and main['filament_diameter']==1.75  # Not diameter_avg.
    assert main['country_of_origin']=='CZ' and main['brand_specific_instance_id']=='012345abcd'
    assert main['manufactured_date']==int(datetime.fromisoformat(DATA['manufacture_date']).timestamp())
    assert [main[k] for k in ('min_print_temperature','max_print_temperature','min_bed_temperature','max_bed_temperature')]==[220,240,55,75]
    assert 'empty_container_weight' not in main and 'instance_uuid' not in main
    assert report['aux']=={} and len(report['warnings'])==1


def test_explicit_tare_and_kilograms_in_product_title():
    data=deepcopy(DATA);data['spool_weight']=278;data['filament']['name']='Prusament PETG Black 1kg';data['filament']['material']='PETG'
    report=prusament.parse_page(page(data),URL)
    assert report['main']['empty_container_weight']==278 and report['main']['nominal_netto_full_weight']==1000
    assert not report['warnings']


@pytest.mark.parametrize('url', [
    'http://prusament.com/spool/12345/012345abcd','https://www.prusament.com/spool/12345/012345ABCD/',
    '  '+URL+'\r\n'])
def test_normalizes_to_one_known_https_origin(url):
    fetch=Mock(return_value=page());prusament.resolve_prusament(url,fetch=fetch);fetch.assert_called_once_with(URL)


@pytest.mark.parametrize('url', [
    'https://example.com/spool/12345/012345abcd/', 'https://prusament.com.evil.invalid/spool/12345/012345abcd/',
    'https://127.0.0.1/spool/12345/012345abcd/', 'file:///etc/passwd',
    'https://user:password@prusament.com/spool/12345/012345abcd/', URL+'?secret=value', URL+'#fragment',
    'https://prusament.com:443/spool/12345/012345abcd/', 'https://prusament.com/spool/../012345abcd/',
    'https://prusament.com/spool/12345/%3012345abcd/', 'https://prusament.com/products/'])
def test_arbitrary_urls_never_fetched(url):
    fetch=Mock();assert prusament.resolve_prusament(url,fetch=fetch) is None;fetch.assert_not_called()


@pytest.mark.parametrize('html', ['<h1>Unavailable</h1>', '<script>var spoolData = dangerous();</script>',
    page().replace('true','false'), page()+page(), page({'ff_goods_id':17786,'filament':{'name':'Wrong product'}}),
    page({'ff_goods_id':12345,'filament':{}}), 'x'*(prusament.MAX_PAGE+1)])
def test_changed_or_invalid_pages_fail_explicitly_without_executing_scripts(html):
    with pytest.raises(prusament.PrusamentError,match='illisible'):prusament.parse_page(html,URL)


def test_missing_values_are_not_guessed_and_json_is_never_executed():
    data={'ff_goods_id':12345,'filament':{'name':'Prusament example','material':'Unknown grade'},'weight':None}
    html=page(data).replace('<div>Diameter<br><strong>1.75 mm</strong></div>','')
    main=prusament.parse_page(html,URL)['main']
    assert not {'actual_netto_full_weight','nominal_netto_full_weight','filament_diameter','material_type','manufactured_date'}&main.keys()
    for value in ('NaN','Infinity','true','-1'):
        result=prusament.parse_page(html.replace('"weight": null','"weight": '+value),URL)
        assert 'actual_netto_full_weight' not in result['main']


def test_transport_is_bounded_https_without_proxies_redirects_or_page_assets(monkeypatch):
    headers=Message();headers['Content-Type']='text/html; charset=utf-8'
    response=Mock();response.headers=headers;response.read.return_value=page().encode();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    opener=Mock();opener.open.return_value=response;factory=Mock(return_value=opener);monkeypatch.setattr(prusament,'build_opener',factory)
    assert prusament.fetch_page(URL)==page()
    handlers=factory.call_args.args
    assert handlers[0].proxies=={} and isinstance(handlers[1],prusament.NoRedirect)
    request=opener.open.call_args.args[0];assert request.full_url==URL and opener.open.call_args.kwargs['timeout']==8
    response.read.assert_called_once_with(prusament.MAX_PAGE+1)
    response.read.return_value=b'x'*(prusament.MAX_PAGE+1)
    with pytest.raises(prusament.PrusamentError):prusament.fetch_page(URL)
    assert handlers[1].redirect_request(None,None,302,'Moved',{},'http://127.0.0.1/') is None


@pytest.mark.parametrize('code,expected', [(404,404),(403,502),(429,502),(302,502)])
def test_transport_errors_do_not_echo_remote_content(monkeypatch,code,expected):
    opener=Mock();opener.open.side_effect=HTTPError(URL,code,'REMOTE CONTENT',{},None);monkeypatch.setattr(prusament,'build_opener',lambda *args:opener)
    with pytest.raises(prusament.PrusamentError) as error:prusament.fetch_page(URL)
    assert error.value.status_code==expected and 'REMOTE CONTENT' not in str(error.value)


def test_offline_is_an_explicit_retryable_error(monkeypatch):
    opener=Mock();opener.open.side_effect=URLError('private diagnostic');monkeypatch.setattr(prusament,'build_opener',lambda *args:opener)
    with pytest.raises(prusament.PrusamentError,match='injoignable') as error:prusament.fetch_page(URL)
    assert error.value.status_code==503 and 'private diagnostic' not in str(error.value)


def test_inspection_does_not_add_stock_and_saving_reviewed_values_is_offline(tmp_path):
    fetch=Mock(return_value=page());app=create_app(Settings(tmp_path,network_enabled=True),prusament_fetch=fetch)
    with TestClient(app,client=('192.0.2.42',1)) as client:
        report=client.post('/api/qr/inspect',json={'text':URL}).json();assert report['kind']=='prusament'
        assert client.get('/api/inventory').json()['items']==[]
        main=report['main'];main['empty_container_weight']=220  # User-reviewed value, never invented by importer.
        fetch.side_effect=AssertionError('Saving must not contact Prusament again')
        result=client.post('/api/inventory/packaged',json={'main':main,'aux':{},'qr_raw':URL})
        assert result.status_code==200,result.text
        item=result.json();assert item['main']['empty_container_weight']==220 and item['remaining_weight'] is None
        assert len(client.get('/api/inventory').json()['items'])==1
        raw=client.get(f"/api/inventory/{item['id']}/qr?version={item['version']}").json()['text']
        again=client.post('/api/qr/inspect',json={'text':raw}).json()
        assert again['kind']=='opt_station' and again['main']==item['main'] and again['aux']=={}
        fetch.assert_called_once_with(URL)
