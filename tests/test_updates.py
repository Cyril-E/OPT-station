"""GitHub detection uses fake responses; no tokens or releases are created."""
from copy import deepcopy
import json
from pathlib import Path
import threading
from urllib.error import HTTPError, URLError
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.backups import decrypt
from openprinttag_app.config import Settings
from openprinttag_app.storage import ConflictError
from openprinttag_app.updates import (ReleaseMonitor, UpdateConfiguration, UpdateFailure, DEFAULT_REPOSITORY,
                                    MAX_NOTES, github_request, next_page, release, version)

TOKEN = 'github_pat_FICTITIOUS_READ_ONLY_TOKEN'
BASE = 'https://api.github.com/repos/Cyril-E/OPT-station/releases?per_page=100&page=1'
PAGE2 = BASE[:-1]+'2'


def row(tag='v0.10.0', prerelease=False, **changes):
    return {'tag_name':tag, 'draft':False, 'prerelease':prerelease, 'published_at':'2026-10-26T18:40:42Z',
            'html_url':f'https://github.com/{DEFAULT_REPOSITORY}/releases/tag/{tag}', 'name':'Une version', **changes}


def reply(rows=None, headers=None, code=200):
    return code, headers or {}, json.dumps([row()] if rows is None else rows).encode()


def save(monitor, **changes):
    body={k:v for k,v in monitor.configuration.record.items() if k not in {'version','token'}}
    body.update({'enabled':True,'token':TOKEN,'clear_token':False,**changes})
    return monitor.save(body)


def test_semantic_order_drafts_prereleases_and_non_version_tags(tmp_path):
    fetch=Mock(return_value=reply([row('v0.9.0'),row('v0.10.0'),row('v0.11.0rc1'),row('v2.0.0',draft=True),row('nightly'),row('v5.0.0',published_at=None)]))
    m=ReleaseMonitor(tmp_path,fetch=fetch,installed='0.9.0');save(m,include_prereleases=False);m.tick()
    s=m.snapshot();assert s['latest']['tag']=='v0.10.0' and s['update_available']
    save(m,include_prereleases=True,token='github_pat_DIFFERENT_FICTITIOUS_TOKEN');m.tick()
    assert m.snapshot()['latest']['tag']=='v0.11.0rc1'
    assert version('0.10.0')>version('0.9.0') and version('0.10.0+custom')==version('v0.10.0')
    assert version('not a version') is None


@pytest.mark.parametrize('installed,tag,available,comparison', [('0.10.0','v0.10.0',False,'current'),('0.11.0.dev0','v0.10.0',False,'ahead'),('0.10.0','v0.11.0',True,None),('0.10.0+local','v0.10.0',False,'current')])
def test_equal_newer_and_development_versions(tmp_path,installed,tag,available,comparison):
    m=ReleaseMonitor(tmp_path,fetch=Mock(return_value=reply([row(tag)])),installed=installed)
    save(m);m.tick();s=m.snapshot()
    assert s['update_available'] is available and s['comparison']==comparison


def test_prerelease_flag_filters_final_tags_and_never_claims_up_to_date_for_empty_list(tmp_path):
    m=ReleaseMonitor(tmp_path,fetch=Mock(return_value=reply([row(prerelease=True)])))
    save(m,include_prereleases=False);m.tick()
    assert m.snapshot()['phase']=='ok' and m.snapshot()['latest'] is None and m.snapshot()['update_available'] is None


def test_pagination_each_page_etag_restart_and_recomputed_installed_version(tmp_path):
    clock=[1000000.]
    fetch=Mock(side_effect=[reply([row('v0.9.0')],{'ETag':'"first"','Link':f'<{PAGE2}>; rel="next"'}),reply([row('v0.10.0')],{'ETag':'"second"'})])
    m=ReleaseMonitor(tmp_path,fetch=fetch,installed='0.9.0',clock=lambda:clock[0]);save(m);m.tick()
    assert m.snapshot()['latest']['tag']=='v0.10.0'
    cached=ReleaseMonitor(tmp_path,fetch=Mock(side_effect=[(304,{},b''),(304,{},b'')]),installed='0.10.0',clock=lambda:clock[0])
    assert cached.snapshot()['update_available'] is False
    clock[0]+=21601;cached.tick()
    assert cached.fetch.call_count==2
    assert cached.fetch.call_args_list[0].args[1]['If-None-Match']=='"first"'
    assert cached.fetch.call_args_list[1].args[1]['If-None-Match']=='"second"'
    assert TOKEN not in json.dumps(cached.settings()) and TOKEN not in cached.path.read_text()
    assert cached.configuration.path.stat().st_mode & 0o777==0o600
    assert cached.path.stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('status,headers,code',[(401,{},'token'),(404,{},'access'),(403,{},'permissions'),(429,{'Retry-After':'3600'},'rate_limit'),(403,{'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'1007200'},'rate_limit'),(500,{},'network'),(301,{'Location':'https://evil.invalid/'},'moved')])
def test_failures_never_claim_up_to_date_or_echo_credentials(tmp_path,status,headers,code):
    m=ReleaseMonitor(tmp_path,fetch=Mock(return_value=(status,headers,b'secret response '+TOKEN.encode())),clock=lambda:1000000.)
    save(m);m.tick();s=m.snapshot()
    assert s['phase']=='error' and s['error_code']==code and s['update_available'] is None
    assert TOKEN not in json.dumps(s) and 'secret response' not in json.dumps(s)
    with pytest.raises(ConflictError):m.request_check()


def test_rate_limit_survives_restart_manual_requests_and_settings_save(tmp_path):
    clock=[1000000.];fetch=Mock(return_value=(429,{'Retry-After':'3600'},b''))
    m=ReleaseMonitor(tmp_path,fetch=fetch,clock=lambda:clock[0]);save(m);m.tick()
    save(m,include_prereleases=False)
    m.tick();assert fetch.call_count==1
    restarted=ReleaseMonitor(tmp_path,fetch=fetch,clock=lambda:clock[0]);restarted.tick();assert fetch.call_count==1
    clock[0]+=3601;restarted.tick();assert fetch.call_count==2


def test_offline_preserves_known_update_with_stale_flag_and_date(tmp_path):
    clock=[1000000.];fetch=Mock(side_effect=[reply([row('v0.12.0')]),UpdateFailure('network')])
    m=ReleaseMonitor(tmp_path,fetch=fetch,installed='0.10.0',clock=lambda:clock[0]);save(m);m.tick()
    checked=m.snapshot()['checked_at'];clock[0]+=21601;m.tick();s=m.snapshot()
    assert s['update_available'] and s['stale'] and s['checked_at']==checked and s['error_code']=='network'


@pytest.mark.parametrize('bad', ['https://evil.invalid/releases?page=2&per_page=100','http://api.github.com/repos/Cyril-E/OPT-station/releases?page=2&per_page=100','https://api.github.com/repos/other/repo/releases?page=2&per_page=100',BASE])
def test_pagination_rejects_credential_exfiltration_and_loops(tmp_path,bad):
    fetch=Mock(return_value=reply([row()],{'Link':f'<{bad}>; rel="next"'}))
    m=ReleaseMonitor(tmp_path,fetch=fetch);save(m);m.tick()
    assert m.snapshot()['phase']=='error' and fetch.call_count==1


def test_metadata_safe_links_and_json_failures(tmp_path):
    assert release(row(html_url='javascript:alert(1)'),DEFAULT_REPOSITORY) is None
    assert release(row(html_url='https://evil.invalid/'),DEFAULT_REPOSITORY) is None
    assert release(row(html_url='https://github.com.evil.invalid/Cyril-E/OPT-station/releases/tag/v0.10.0'),DEFAULT_REPOSITORY) is None
    assert release(row(name='<script>untrusted</script>'),DEFAULT_REPOSITORY)['name']=='<script>untrusted</script>'
    for body in (b'not JSON', b'{}', b'x'*(2*1024*1024+1)):
        m=ReleaseMonitor(tmp_path,fetch=Mock(return_value=(200,{},body)));save(m,token='github_pat_NEW_FICTITIOUS_TOKEN_'+str(len(body)));m.tick()
        assert m.snapshot()['phase']=='error'


def test_release_notes_are_plain_text_normalized_and_bounded():
    notes = '  ## Nouveautés\r\n- Sans mot de passe\r\n<script>untrusted</script>\x00  '
    result = release(row(body=notes), DEFAULT_REPOSITORY)
    assert result['notes'] == '## Nouveautés\n- Sans mot de passe\n<script>untrusted</script>'
    long = release(row(body='a' * (MAX_NOTES + 100)), DEFAULT_REPOSITORY)['notes']
    assert len(long) == MAX_NOTES and long.endswith('\n…')


@pytest.mark.parametrize('body', [None, 42, {'unexpected': 'object'}])
def test_missing_or_non_text_release_notes_remain_compatible(body):
    assert release(row(body=body), DEFAULT_REPOSITORY)['notes'] == ''
    assert release(row(), DEFAULT_REPOSITORY)['notes'] == ''


def test_latest_release_notes_survive_restart_conditional_fetch_and_offline(tmp_path):
    clock = [1000000.]
    notes = '- Sauvegardes sans mot de passe\n- Nouveautés dans la station'
    fetch = Mock(return_value=reply([row('v0.10.0', body='Anciennes notes'), row('v0.11.0', body=notes)], {'ETag': '"notes"'}))
    monitor = ReleaseMonitor(tmp_path, fetch=fetch, installed='0.9.0', clock=lambda: clock[0])
    save(monitor); monitor.tick()
    assert monitor.snapshot()['latest']['notes'] == notes
    cached = ReleaseMonitor(tmp_path, fetch=Mock(side_effect=[(304, {}, b''), UpdateFailure('network')]), clock=lambda: clock[0])
    assert cached.snapshot()['latest']['notes'] == notes
    clock[0] += 21601; cached.tick()
    assert cached.snapshot()['latest']['notes'] == notes
    clock[0] += 21601; cached.tick()
    assert cached.snapshot()['stale'] and cached.snapshot()['latest']['notes'] == notes


def test_previous_cache_without_notes_loads_and_refreshes(tmp_path):
    clock = [1000000.]
    monitor = ReleaseMonitor(tmp_path, fetch=Mock(return_value=reply()), clock=lambda: clock[0])
    save(monitor); monitor.tick()
    cached = json.loads(monitor.path.read_text())
    cached['latest'].pop('notes')
    for page in cached['pages'].values():
        for item in page['items']:
            item.pop('notes', None)
    monitor.path.write_text(json.dumps(cached))
    reloaded = ReleaseMonitor(tmp_path, fetch=Mock(return_value=reply([row(body='Notes désormais disponibles')])), clock=lambda: clock[0])
    assert reloaded.snapshot()['latest']['notes'] == ''
    clock[0] += 21601; reloaded.tick()
    assert reloaded.snapshot()['latest']['notes'] == 'Notes désormais disponibles'


def test_only_one_check_and_discard_old_result_after_settings_change(tmp_path):
    started,finish=threading.Event(),threading.Event()
    def fetch(*_):started.set();assert finish.wait(5);return reply([row('v0.12.0')])
    m=ReleaseMonitor(tmp_path,fetch=fetch);save(m)
    thread=threading.Thread(target=m.tick);thread.start();assert started.wait(2)
    assert m.snapshot()['checking'];m.tick()
    save(m,enabled=False);finish.set();thread.join(5)
    assert not m.snapshot()['enabled'] and m.state.get('latest') is None


def test_disabled_due_interval_power_gate_and_bad_cache(tmp_path):
    clock=[1000000.];fetch=Mock(return_value=reply())
    m=ReleaseMonitor(tmp_path,fetch=fetch,clock=lambda:clock[0]);m.tick();fetch.assert_not_called()
    save(m);m.allowed=lambda:False;m.tick();fetch.assert_not_called()
    m.allowed=lambda:True;m.tick();assert fetch.call_count==1
    clock[0]+=61;m.tick();assert fetch.call_count==1
    m.request_check();m.tick();assert fetch.call_count==2
    m.path.write_text('{"revision":1,"next_at":"invalid"}')
    reloaded=ReleaseMonitor(tmp_path,fetch=fetch);assert reloaded.state=={}


def test_settings_clear_token_repository_change_conflicts_and_restart(tmp_path):
    m=ReleaseMonitor(tmp_path);save(m)
    first=deepcopy(m.configuration.record)
    with pytest.raises(ConflictError):m.save({'revision':0})
    save(m,token=None,interval_hours=12);assert m.configuration.record['token']==TOKEN
    save(m,token=None,repository='Other/repo');assert not m.configuration.record['token']
    save(m,clear_token=True);assert not m.configuration.record['token']
    assert ReleaseMonitor(tmp_path).settings()['interval_hours']==12
    for change in ({'repository':'../bad'},{'repository':'x/..'},{'token':'bad\r\nheader'},{'interval_hours':0},{'interval_hours':True}):
        with pytest.raises(ValueError):save(m,**change)


@pytest.fixture
def station(tmp_path,monkeypatch):
    # Keep the simulated update newer than the installed application release.
    fetch=Mock(return_value=reply([row('v999.0.0', body='Nouveautés visibles depuis le réseau')]))
    app=create_app(Settings(tmp_path,network_enabled=True),updates_fetch=fetch)
    monkeypatch.setattr(app.state.updates,'start',lambda:None)
    with TestClient(app,client=('127.0.0.1',1)) as client:yield app,client,fetch


def test_api_full_access_secret_masking_status_visibility_host_origin_power(station):
    app,client,fetch=station;m=app.state.updates
    payload={'revision':0,'enabled':True,'repository':DEFAULT_REPOSITORY,'interval_hours':6,'include_prereleases':True,'token':TOKEN}
    response=client.put('/api/configuration/updates',json=payload)
    assert response.status_code==200 and TOKEN not in response.text and response.json()['token_saved']
    m.tick()
    with TestClient(app,client=('192.0.2.42',1)) as remote:
        assert remote.get('/api/configuration/updates').status_code==403
        public=remote.get('/api/status').json()['updates'];assert public['update_available'] and TOKEN not in json.dumps(public)
        assert public['latest']['notes'] == 'Nouveautés visibles depuis le réseau'
        assert remote.post('/api/updates/check',json={}).status_code==403
        client.put('/api/configuration/network',json={'mode':'full'})
        assert remote.get('/api/configuration/updates').status_code==200
        client.put('/api/configuration/network',json={'mode':'disabled'})
        assert remote.get('/api/status').json()['updates'] is None
    assert client.post('/api/updates/check',json={},headers={'Origin':'http://evil.invalid'}).status_code==403
    assert client.post('/api/updates/check',content='{}',headers={'Content-Type':'text/plain'}).status_code==415
    app.state.station_power.phase='requested'
    assert client.post('/api/updates/check',json={}).status_code==503


def test_updates_settings_in_encrypted_backups_and_restore_reloads_monitor(station):
    import base64
    app,client,fetch=station;m=app.state.updates;save(m)
    password='backup-password-for-tests'
    archive=client.post('/api/backups/download',json={'scope':'configuration','password':password})
    assert archive.status_code==200
    raw=decrypt(archive.content,password);assert raw['configuration']['updates-settings.json']['token']==TOKEN
    save(m,enabled=False,clear_token=True)
    p=client.post('/api/backups/restore/preview',json={'content':base64.b64encode(archive.content).decode(),'password':password})
    assert p.status_code==200,p.text
    result=client.post('/api/backups/restore/commit',json={'preview_id':p.json()['preview_id'],'confirmed':True})
    assert result.status_code==200,result.text
    assert app.state.updates.configuration.record['token']==TOKEN
    assert app.state.updates.configuration.record['enabled'] and app.state.updates.settings()['token_saved']
    assert TOKEN not in client.get('/api/configuration/updates').text


def test_transport_uses_fixed_https_no_proxy_or_redirect_and_bounded_body(monkeypatch):
    import openprinttag_app.updates as module
    response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.status=200;response.headers={'ETag':'"safe"'};response.read.return_value=b'[]'
    opener=Mock();opener.open.return_value=response
    builder=Mock(return_value=opener);monkeypatch.setattr(module,'build_opener',builder)
    status,headers,body=github_request(BASE,{'Authorization':'Bearer '+TOKEN},8)
    assert status==200 and body==b'[]'
    sent=opener.open.call_args.args[0]
    assert sent.full_url==BASE and sent.get_header('Authorization')=='Bearer '+TOKEN
    assert module.NoRedirect().redirect_request(None,None,302,'moved',{},'https://evil.invalid/') is None
    assert builder.call_args.args[0].proxies=={}
    response.read.assert_called_once_with(module.MAX_BODY+1)
    opener.open.side_effect=HTTPError(BASE,401,'rejected',{},None)
    assert github_request(BASE,{},8)==(401,{},b'')
    opener.open.side_effect=URLError('untrusted '+TOKEN)
    with pytest.raises(UpdateFailure) as caught:github_request(BASE,{},8)
    assert caught.value.code=='network' and TOKEN not in str(caught.value)


def test_worker_starts_checks_in_background_and_stops(tmp_path):
    finished=threading.Event()
    def fetch(*_):finished.set();return reply()
    m=ReleaseMonitor(tmp_path,fetch=fetch);save(m);m.start();assert finished.wait(2)
    m.close();assert not m.worker.is_alive()


def test_corrupt_cache_and_rate_limit_headers_cannot_leak_urls_or_break_status(tmp_path):
    m=ReleaseMonitor(tmp_path,fetch=Mock(return_value=(429,{'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'inf'},b'')),clock=lambda:1000000.)
    save(m);m.tick();assert m.snapshot()['error_code']=='rate_limit'
    state=deepcopy(m.state);state['latest']={'tag':'v0.12.0','version':'0.12.0','name':'fake','prerelease':False,'published_at':'2026-10-26T18:40:42Z','url':'https://evil.invalid/'}
    m.path.write_text(json.dumps(state))
    assert ReleaseMonitor(tmp_path).snapshot()['latest'] is None


def test_empty_conditional_response_without_cached_page_is_not_success(tmp_path):
    m=ReleaseMonitor(tmp_path,fetch=Mock(return_value=(304,{},b'')));save(m);m.tick()
    assert m.snapshot()['error_code']=='response' and m.snapshot()['update_available'] is None


def test_pagination_limit_never_reports_up_to_date_with_partial_results(tmp_path):
    index=[1]
    def fetch(*_):
        index[0]+=1
        url=BASE[:-1]+str(index[0])
        return reply([row()],{'Link':f'<{url}>; rel="next"'})
    m=ReleaseMonitor(tmp_path,fetch=fetch);save(m);m.tick()
    assert m.snapshot()['error_code']=='incomplete' and m.snapshot()['update_available'] is None


def test_cached_state_is_invalidated_when_restored_configuration_changes(station):
    app,client,fetch=station;m=app.state.updates;save(m);m.tick()
    assert m.snapshot()['latest']
    m.configuration.path.unlink();m.reload()
    assert not m.snapshot()['enabled'] and m.snapshot()['latest'] is None and not m.settings()['token_saved']
