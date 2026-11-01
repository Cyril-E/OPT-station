"""Label proposals use controlled API replies, never hardware or paid requests."""
import base64
from copy import deepcopy
import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.assistant import (AssistantError, LabelAssistant, MAX_IMAGE, NoRedirect,
                                       normalized_image, openai_request, proposal, public_url)
from openprinttag_app.backups import decrypt
from openprinttag_app.config import Settings

KEY = 'sk-FICTITIOUS_API_KEY_FOR_CONTROLLED_TESTS_ONLY'
URL = 'https://manufacturer.example/filament/petg'


def photo():
    target = io.BytesIO(); Image.new('RGB', (80, 60), 'white').save(target, 'PNG'); return target.getvalue()


def field(name='material_type', value='PETG', origin='label', source_url=None):
    return {'field': name, 'value': value, 'origin': origin, 'source_url': source_url, 'evidence': 'Printed PETG'}


def reply(fields=None, recognized=True):
    record = {'recognized': recognized, 'title': 'Label', 'visible_text': 'PETG 1.75 mm',
              'fields': fields if fields is not None else [field(), field('filament_diameter', 1.75)], 'warnings': []}
    return {'status': 'completed', 'output': [
        {'type': 'web_search_call', 'action': {'sources': [{'url': URL, 'title': 'Manufacturer'}]}},
        {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(record), 'annotations': []}]}]}


def configure(client, **changes):
    current = client.get('/api/configuration/assistant').json()
    body = {k: current[k] for k in ['revision', 'enabled', 'model', 'web_search']}
    body.update({'enabled': True, 'api_key': KEY, **changes})
    return client.put('/api/configuration/assistant', json=body)


@pytest.fixture
def station(tmp_path):
    fetch = Mock(return_value=reply())
    app = create_app(Settings(tmp_path, network_enabled=True), assistant_fetch=fetch)
    with TestClient(app, client=('127.0.0.1', 1)) as client:
        yield app, client, fetch


def test_configuration_access_key_masking_revision_clear_and_disabled(station):
    app, client, fetch = station
    assert client.post('/api/assistant/analyse', json={'image': base64.b64encode(photo()).decode()}).status_code == 409
    fetch.assert_not_called()
    assert configure(client).status_code == 200
    assert app.state.assistant.path.stat().st_mode & 0o777 == 0o600
    assert KEY not in client.get('/api/status').text
    assert KEY not in client.get('/api/configuration/assistant').text
    response = configure(client, api_key=None); assert response.status_code == 200
    assert app.state.assistant.record['api_key'] == KEY
    assert client.put('/api/configuration/assistant', json={'revision': 0, 'enabled': True, 'model': 'gpt-5.4-mini', 'web_search': True}).status_code == 409
    assert configure(client, api_key=None, clear_key=True, enabled=False).json()['key_saved'] is False
    assert configure(client, api_key='bad\r\n'+KEY).status_code == 422
    assert KEY not in configure(client, api_key=KEY+'!').text


@pytest.mark.parametrize('language', ['fr', 'en', 'es', 'de'])
def test_analysis_is_only_a_proposal_and_does_not_touch_stock_or_nfc(station, language):
    app, client, fetch = station; configure(client)
    with app.state.store.connect() as db:
        before = list(db.iterdump())
    response = client.post('/api/assistant/analyse', json={'image': 'data:image/png;base64,'+base64.b64encode(photo()).decode(), 'language': language})
    assert response.status_code == 200, response.text
    result = response.json(); assert result['main'] == {'material_type': 'PETG', 'filament_diameter': 1.75}
    assert result['aux'] == {} and 'empty_container_weight' not in result['main']
    with app.state.store.connect() as db:
        assert list(db.iterdump()) == before
    payload, key = fetch.call_args.args
    assert key == KEY and payload['store'] is False
    assert payload['tools'][0]['type'] == 'web_search'
    assert payload['text']['format']['strict'] is True and f'Output language: {language}' in payload['instructions']
    assert KEY not in json.dumps(result)


def test_remote_inventory_origin_content_type_and_image_limits(station):
    app, client, fetch = station; configure(client)
    with TestClient(app, client=('192.0.2.42', 1)) as remote:
        assert remote.get('/api/configuration/assistant').status_code == 403
        assert remote.post('/api/assistant/analyse', json={'image': 'AA=='}).status_code == 403
        assert remote.post('/api/assistant/photo', json={}).status_code == 403
        client.put('/api/configuration/network', json={'mode': 'full'})
        assert remote.get('/api/configuration/assistant').status_code == 200
    assert client.post('/api/assistant/analyse', json={'image': 'AA=='}, headers={'Origin': 'https://evil.invalid'}).status_code == 403
    assert client.post('/api/assistant/analyse', content='{}', headers={'Content-Type': 'text/plain'}).status_code == 415
    assert client.post('/api/assistant/analyse', json={'image': 'AA==', 'scan_id': 'both'}).status_code == 422
    assert client.post('/api/assistant/analyse', json={'image': 'data:image/svg+xml;base64,AA=='}).status_code == 422
    assert client.post('/api/assistant/analyse', json={'image': '***'}).status_code == 422
    assert client.post('/api/assistant/analyse', content=b'x'*6_100_001, headers={'Content-Type': 'application/json'}).status_code == 413
    fetch.assert_not_called()


def test_evidence_unknown_values_conflicts_and_web_disabled():
    fields = [field(), field('brand_name', 'Invented', 'web', 'https://unseen.example/'),
              field('min_print_temperature', 260), field('max_print_temperature', 240),
              field('nominal_netto_full_weight', 1000), field('nominal_netto_full_weight', 500),
              field('primary_color', '#112233', 'web', URL), field('filament_diameter', -2)]
    result = proposal(reply(fields), True)
    assert result['main'] == {'material_type': 'PETG', 'primary_color': '#112233'}
    assert len(result['warnings']) >= 3
    assert proposal(reply(fields), False)['main'] == {'material_type': 'PETG'}
    assert proposal(reply(fields, recognized=False), True)['main'] == {}
    with pytest.raises(AssistantError): proposal(reply([field('consumed_weight', 0)]), True)
    with pytest.raises(AssistantError): proposal({'status': 'incomplete', 'output': []}, True)
    with pytest.raises(AssistantError): proposal({'status': 'completed', 'output': []}, True)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'http://manufacturer.example/', 'https://user:pass@manufacturer.example/',
                              'https://127.0.0.1/', 'https://192.168.1.1/', 'https://printer.local/', 'https://localhost/'])
def test_sources_never_link_to_scripts_credentials_or_private_hosts(url):
    assert public_url(url) is None
    assert public_url(URL) == URL


def test_photo_format_limits_and_metadata_removal():
    for content in [b'not an image', b'<svg/>', b'x'*(MAX_IMAGE+1)]:
        with pytest.raises(AssistantError): normalized_image(content)
    jpeg = normalized_image(photo())
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.format == 'JPEG' and not image.getexif()


def test_settings_changes_discard_a_running_analysis_and_concurrency_is_bounded(tmp_path):
    assistant = LabelAssistant(tmp_path)
    assistant.save({'revision': 0, 'enabled': True, 'api_key': KEY})
    def fetch(*_):
        with pytest.raises(AssistantError, match='déjà en cours'): assistant.analyse(photo())
        assistant.save({'revision': 1, 'enabled': False})
        return reply()
    assistant.fetch = fetch
    with pytest.raises(AssistantError, match='changé pendant'): assistant.analyse(photo())
    assert not assistant.analysis_lock.locked()


def test_one_formatting_retry_preserves_sources_without_another_web_search(tmp_path):
    broken = reply([field('min_print_temperature', 230, 'web', URL)])
    broken['output'][1]['content'][0]['text'] = '{"recognized":true,broken'
    corrected = reply([field('min_print_temperature', 230, 'web', URL)])
    corrected['output'] = corrected['output'][1:]
    fetch = Mock(side_effect=[broken, corrected])
    assistant = LabelAssistant(tmp_path, fetch=fetch)
    assistant.record.update(enabled=True, api_key=KEY)
    assert assistant.analyse(photo())['main'] == {'min_print_temperature': 230}
    assert fetch.call_count == 2
    second = fetch.call_args_list[1].args[0]
    assert 'tools' not in second and 'input_image' not in json.dumps(second)
    assert second['store'] is False


def test_formatting_retry_does_not_loop_or_invent_a_missing_schema(tmp_path):
    broken = reply(); broken['output'][1]['content'][0]['text'] = 'not JSON'
    fetch = Mock(return_value=broken); assistant = LabelAssistant(tmp_path, fetch=fetch)
    assistant.record.update(enabled=True, api_key=KEY)
    with pytest.raises(AssistantError): assistant.analyse(photo())
    assert fetch.call_count == 2 and not assistant.analysis_lock.locked()


def test_ai_settings_are_backed_up_validated_and_reloaded_on_restore(station):
    app, client, fetch = station; configure(client)
    archive = client.post('/api/backups/download', json={'scope': 'configuration'}).content
    assert decrypt(archive)['configuration']['ai-settings.json']['api_key'] == KEY
    configure(client, enabled=False)
    preview = client.post('/api/backups/restore/preview', json={'content': base64.b64encode(archive).decode()})
    assert preview.status_code == 200, preview.text
    response = client.post('/api/backups/restore/commit', json={'preview_id': preview.json()['preview_id'], 'confirmed': True})
    assert response.status_code == 200
    assert app.state.assistant.public()['enabled'] and app.state.assistant.record['api_key'] == KEY
    assert KEY not in client.get('/api/configuration/assistant').text


@pytest.mark.parametrize('code', [400, 401, 403, 429, 500])
def test_transport_failures_never_echo_keys(monkeypatch, code):
    import openprinttag_app.assistant as module
    opener = Mock(); opener.open.side_effect = HTTPError('https://api.openai.com/v1/responses', code, KEY, {}, None)
    monkeypatch.setattr(module, 'build_opener', Mock(return_value=opener))
    with pytest.raises(AssistantError) as caught: openai_request({}, KEY)
    assert KEY not in str(caught.value)
    request = opener.open.call_args.args[0]
    assert request.full_url == 'https://api.openai.com/v1/responses'
    assert NoRedirect().redirect_request(None, None, None, None, None, None) is None
