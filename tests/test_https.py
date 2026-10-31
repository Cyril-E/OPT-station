"""HTTPS access boundaries, public trust material and installation persistence."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.config import Settings
from openprinttag_app.https import HTTPSConfiguration, https_url

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('https_installer', ROOT / 'deploy/install-https.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def https_config(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'OPT Station test CA')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30)).add_extension(x509.BasicConstraints(ca=True, path_length=1), True)
            .sign(key, hashes.SHA256()))
    ca = tmp_path / 'root.crt'; ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    path = tmp_path / 'https.json'
    path.write_text(json.dumps({'version':1, 'url':'https://station.local', 'aliases':['https://192.0.2.10'], 'ca_cert':str(ca)}))
    return path, ca


def proxied(app, address='192.0.2.42', scheme='https'):
    base_scheme = scheme if scheme in {'http', 'https'} else 'https'
    return TestClient(app, base_url=f'{base_scheme}://station.local', client=('127.0.0.1', 1234),
                      headers={'X-Forwarded-For':address, 'X-Forwarded-Proto':scheme})


def test_inventory_full_disabled_and_local_kiosk_keep_distinct_rights(https_config, tmp_path):
    path, ca = https_config
    app = create_app(Settings(tmp_path / 'data', https_config=path))
    with proxied(app) as remote, proxied(app, '127.0.0.1') as kiosk:
        status = remote.get('/api/status').json()
        assert not status['local_station'] and not status['station_access']
        assert status['network']['url'] == 'https://station.local'
        assert remote.get('/api/reader/tag').status_code == 403
        assert kiosk.get('/api/status').json()['local_station']
        assert kiosk.get('/api/reader/tag').status_code == 200
        assert remote.get('/api/configuration/mcp').json()['endpoint'] == 'https://station.local/mcp'
        response = remote.put('/api/configuration/network',json={'mode':'full'},headers={'Origin':'https://station.local'})
        assert response.status_code == 200
        assert remote.get('/api/reader/tag').status_code == 200
        remote.put('/api/configuration/network',json={'mode':'disabled'}).raise_for_status()
        assert remote.get('/api/inventory').status_code == 403
        for route in ('/https', '/https/certificate', '/api/configuration/https'):
            assert remote.get(route).status_code == 200
        assert kiosk.get('/api/inventory').status_code == 200
    reopened = create_app(Settings(tmp_path / 'data', https_config=path))
    with proxied(reopened) as client:
        assert client.get('/api/status').json()['network']['mode'] == 'disabled'
        assert client.get('/api/reader/tag').status_code == 403


def test_untrusted_direct_client_cannot_spoof_loopback_or_protocol(https_config,tmp_path):
    path,_=https_config
    app=create_app(Settings(tmp_path/'data',https_config=path))
    with TestClient(app,base_url='http://station.local',client=('192.0.2.42',1),headers={
            'X-Forwarded-For':'127.0.0.1','X-Forwarded-Proto':'https'}) as client:
        status=client.get('/api/status').json()
        assert not status['local_station'] and not status['station_access']
        assert not client.get('/api/configuration/https').json()['secure']
        assert client.get('/api/reader/tag').status_code==403


@pytest.mark.parametrize('forwarded,protocol',[
    ('127.0.0.1, 192.0.2.42','https'),('unknown','https'),('', 'https'),
    ('[::1]','https'),('192.0.2.42','https,http'),('192.0.2.42','ftp')])
def test_ambiguous_forwarded_headers_fail_closed(https_config,tmp_path,forwarded,protocol):
    app=create_app(Settings(tmp_path/'data',https_config=https_config[0]))
    with proxied(app,forwarded,protocol) as client:
        assert client.get('/api/reader/tag').status_code==400


def test_origins_match_external_scheme_and_host_and_mcp_boundary(https_config,tmp_path):
    app=create_app(Settings(tmp_path/'data',https_config=https_config[0]))
    with proxied(app) as client:
        for origin in ('http://station.local','https://other.local','null'):
            assert client.put('/api/configuration/network',json={'mode':'full'},headers={'Origin':origin}).status_code==403
        client.put('/api/configuration/network',json={'mode':'full'},headers={'Origin':'https://station.local'}).raise_for_status()
        client.put('/api/configuration/mcp',json={'enabled':True,'revision':0}).raise_for_status()
        assert client.post('/mcp',json={},headers={'Origin':'http://station.local'}).status_code==403
        assert client.get('/api/status',headers={'Host':'unlisted.invalid'}).status_code==400


def test_public_certificate_and_fingerprint_never_expose_paths_or_keys(https_config,tmp_path):
    path,ca=https_config
    app=create_app(Settings(tmp_path/'data',https_config=path))
    with proxied(app,scheme='http') as client:
        info=client.get('/api/configuration/https').json()
        assert info['enabled'] and not info['secure'] and info['certificate_available']
        assert info['certificate_name'] == 'OPT Station test CA'
        assert info['fingerprint_sha256'] and str(tmp_path) not in json.dumps(info)
        response=client.get('/https/certificate')
        assert response.content==ca.read_bytes() and b'PRIVATE KEY' not in response.content
        assert 'attachment' in response.headers['content-disposition']
        assert response.headers['cache-control']=='no-store'
        assert 'https.js?v=' in client.get('/https').text
        ca.write_text(ca.read_text()+'\n-----BEGIN PRIVATE KEY-----\nprivate-test-placeholder\n')
        assert not client.get('/api/configuration/https').json()['certificate_available']
        assert client.get('/https/certificate').status_code==503
        ca.unlink()
        assert client.get('/https/certificate').status_code==503


@pytest.mark.parametrize('url', ['http://station.local','https://user:pass@station.local','https://station.local/path',
    'https://station.local?x=1','https://*.local','https://station.local:0','https://a..local','https://station.local\\evil'])
def test_invalid_https_deployment_url_is_rejected(url):
    with pytest.raises(ValueError):https_url(url)


@pytest.mark.parametrize('record', [{"version":1}, [], "invalid", True])
def test_invalid_config_does_not_fall_back_to_http_or_create_database(tmp_path, record):
    config=tmp_path/'https.json';config.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='HTTPS'):
        create_app(Settings(tmp_path/'data',https_config=config))
    assert not (tmp_path/'data/inventory.sqlite3').exists()
    with pytest.raises(ValueError):HTTPSConfiguration.load(tmp_path/'missing.json')
    assert https_url('https://Station.local:443/')=='https://station.local'


def test_cli_https_binds_only_loopback_and_advertises_external_url(https_config,monkeypatch):
    import uvicorn
    from openprinttag_app.__main__ import main
    captured={}
    monkeypatch.setattr(uvicorn,'run',lambda *args,**kwargs:captured.update(kwargs))
    monkeypatch.setattr(sys,'argv',['opt-station','--https-config',str(https_config[0])])
    for key in ('OPENPRINTTAG_HTTPS_CONFIG','OPENPRINTTAG_NETWORK','OPENPRINTTAG_NETWORK_URL','OPENPRINTTAG_ALLOWED_HOSTS','OPENPRINTTAG_MODE'):
        # Track the original value and leave the CLI's defaults genuinely unset.
        monkeypatch.setenv(key, 'test-placeholder')
        monkeypatch.delenv(key,raising=False)
    main()
    assert captured['host']=='127.0.0.1' and not captured['proxy_headers']
    assert captured['timeout_graceful_shutdown']==20
    settings=Settings.from_env()
    assert settings.network_url=='https://station.local' and settings.network_enabled
    assert 'station.local' in settings.allowed_hosts and settings.https_config==https_config[0]
    monkeypatch.setattr(sys,'argv',['opt-station','--https-config',str(https_config[0]),'--host','0.0.0.0'])
    with pytest.raises(SystemExit) as exc:main()
    assert exc.value.code==2


def test_installer_hostname_input_policy_merge_and_existing_state_are_preserved(tmp_path):
    assert installer.addresses('Station',['192.0.2.10','192.0.2.10'])==['station.local','192.0.2.10','localhost','127.0.0.1']
    for name in ('bad\nhost','bad/host','*.local'):
        with pytest.raises(ValueError):installer.addresses(name,[])
    with pytest.raises(ValueError):installer.addresses('station',['8.8.8.8'])
    before=json.dumps({'policies':{'OtherPolicy':True,'Certificates':{'Install':['existing.crt']}}})
    merged=installer.firefox_policy(before,'/etc/opt-station/root-ca.crt')
    assert merged==installer.firefox_policy(merged,'/etc/opt-station/root-ca.crt')
    assert json.loads(merged)['policies']['OtherPolicy'] is True
    assert json.loads(merged)['policies']['Certificates']['Install']==['existing.crt','/etc/opt-station/root-ca.crt']
    config=installer.caddyfile(['station.local','192.0.2.10'])
    assert 'X-Forwarded-For {http.request.remote.host}' in config and 'tls internal' in config
    original=tmp_path/'original'; original.write_text('before');original.chmod(0o640)
    created=tmp_path/'created'
    files=installer.Files(tmp_path/'backup')
    files.write(original,'after');files.write(created,'new')
    files.restore()
    assert original.read_text()=='before' and original.stat().st_mode & 0o777==0o640
    assert not created.exists()
