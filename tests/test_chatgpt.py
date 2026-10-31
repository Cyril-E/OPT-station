"""Controlled SIWC identity, consent, renewal and inference; no real accounts or billing."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen
from unittest.mock import Mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from openprinttag_app.app import create_app
from openprinttag_app.chatgpt import (ChatGPTConnection, ChatGPTError, ISSUER, DISCOVERY, JWKS, TOKEN,
                                    REVOKE, RESOURCE, DIRECT, completed_stream, failure)
from openprinttag_app.config import Settings


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Provider:
    now = 1_800_000_000
    subject = "test-user"
    scopes = "openid email profile offline_access resource.invoke " + DIRECT
    override = None
    refresh_error = None
    revoke_error = False

    def __init__(self, signing_key):
        self.key = signing_key
        numbers = signing_key.public_key().public_numbers()
        self.keys = {"keys": [{"kid": "fixture-key", "kty": "RSA", "alg": "RS256", "use": "sig",
                              "e": encoded(numbers.e.to_bytes(3, "big")), "n": encoded(numbers.n.to_bytes(256, "big"))}]}
        self.calls = []
        self.connection = None

    def jwt(self, client, nonce):
        header = encoded(json.dumps({"alg": "RS256", "kid": "fixture-key"}).encode())
        claims = {"iss": ISSUER, "sub": self.subject, "aud": client, "nonce": nonce, "exp": self.now + 3600,
                  "iat": self.now, "email": "fixture@example.com", "name": "Fixture"}
        claims.update(self.override or {})
        body = encoded(json.dumps(claims).encode()); signing = (header + "." + body).encode()
        return header + "." + body + "." + encoded(self.key.sign(signing, padding.PKCS1v15(), hashes.SHA256()))

    def __call__(self, method, url, body=None, token=None, stream=False):
        self.calls.append((method, url, deepcopy(body), token, stream))
        if url == DISCOVERY:
            return {"issuer": ISSUER, "jwks_uri": JWKS, "revocation_endpoint": REVOKE}
        if url == JWKS:
            return self.keys
        if url == TOKEN:
            if body["grant_type"] == "refresh_token":
                if self.refresh_error:
                    raise ChatGPTError("Controlled refresh failure", 503, self.refresh_error)
                return {"access_token": "renewed-access", "refresh_token": "rotated-refresh", "expires_in": 3600,
                        "token_type": "Bearer", "scope": self.scopes}
            pending = next(a for a in self.connection.pending.values() if a["status"] == "exchanging")
            return {"access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600,
                    "id_token": self.jwt(body["client_id"], pending["nonce"]), "token_type": "Bearer", "scope": self.scopes}
        if url == RESOURCE + "/models":
            return {"models": [{"slug": "vision-test", "display_name": "Vision fixture", "visibility": "list"},
                               {"slug": "hidden", "display_name": "Hidden", "visibility": "hidden"}]}
        if url == RESOURCE + "/responses":
            assert token in {"fixture-access", "renewed-access"} and stream
            assert body["store"] is False and body["stream"] is True and isinstance(body["input"], list)
            assert not {"max_output_tokens", "max_tool_calls"} & set(body)
            return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "recognized": True, "title": "PETG", "visible_text": "PETG", "warnings": [], "fields": [
                    {"field": "material_type", "value": "PETG", "origin": "label", "source_url": None, "evidence": "PETG"}]})}]}]}
        if url == REVOKE:
            if self.revoke_error:
                raise ChatGPTError("Controlled revoke failure", 503)
            return {}
        raise AssertionError("Unexpected provider operation")


@pytest.fixture
def connection(tmp_path, signing_key):
    provider = Provider(signing_key)
    instance = ChatGPTConnection(tmp_path, fetch=provider, clock=lambda: provider.now)
    provider.connection = instance
    yield instance, provider
    instance.close()


def authenticate(connection, profile_id=None, client="oaiapp_fixture", **changes):
    started = connection.start(profile_id)
    query = {"code": "fixture-code", "client_id": client, "state": parse_qs(urlsplit(started["authorization_url"]).query)["state"][0], **changes}
    connection.complete(started["attempt_id"], started["callback_uri"] + "?" + urlencode(query))
    return started


def test_pkce_dynamic_registration_persistence_public_redaction_and_returning_account(connection):
    c, provider = connection
    started = authenticate(c)
    parsed = parse_qs(urlsplit(started["authorization_url"]).query)
    assert parsed["client_id"] == ["dynamic_agent_client"] and parsed["agent_name_hint"] == ["OPT Station"]
    attempt = c.pending[started["attempt_id"]]
    import hashlib
    assert parsed["code_challenge"] == [encoded(hashlib.sha256(attempt["verifier"].encode()).digest())]
    assert parsed["redirect_uri"][0].startswith("http://127.0.0.1:") and parsed["redirect_uri"][0].endswith("/auth/callback")
    public = c.public(); assert public["connected"] and public["plan_enabled"]
    assert not any(secret in json.dumps(public) for secret in ["fixture-access", "fixture-refresh", attempt["verifier"], "id_token"])
    assert c.path.stat().st_mode & 0o777 == 0o600
    restarted = ChatGPTConnection(c.path.parent, fetch=provider, clock=lambda: provider.now)
    assert restarted.record == c.record
    host = c.record["host_id"]
    again = c.start(public["active"])
    query = parse_qs(urlsplit(again["authorization_url"]).query)
    assert query["client_id"] == ["oaiapp_fixture"] and query["ext_agent_host_id"] == [host]
    assert "agent_name_hint" not in query and "id_token_hint" not in query
    c.cancel(again["attempt_id"])


@pytest.mark.parametrize("claims", [{"nonce": "wrong"}, {"aud": "other-client"}, {"iss": "https://other.invalid"}, {"exp": 1}, {"sub": ""}, {"nbf": 1_900_000_000}])
def test_invalid_signed_identity_does_not_replace_credentials(connection, claims):
    c, provider = connection; provider.override = claims
    with pytest.raises(ChatGPTError):
        authenticate(c)
    assert not c.public()["connected"] and c.record["profiles"] == []


def test_state_callback_replay_denied_scope_and_client_mismatch(connection):
    c, provider = connection
    started = c.start(); attempt = c.pending[started["attempt_id"]]
    with pytest.raises(ChatGPTError):
        c.complete(started["attempt_id"], started["callback_uri"] + "?" + urlencode({"state": "wrong", "code": "c", "client_id": "oaiapp_fixture"}))
    assert provider.calls == []
    c.cancel(started["attempt_id"])
    provider.scopes = "openid email profile"
    authenticate(c)
    assert c.public()["connected"] and not c.public()["plan_enabled"]
    with pytest.raises(ChatGPTError):
        c.models()
    profile = c.record["active"]
    with pytest.raises(ChatGPTError):
        authenticate(c, profile_id=profile, client="oaiapp_wrong")


def test_renewal_rotates_tokens_and_temporary_failure_preserves_them(connection):
    c, provider = connection; authenticate(c); c.models()
    provider.now += 3550
    c.infer({"model": "vision-test", "input": "Fixture", "max_output_tokens": 10})
    assert c._profile()["tokens"]["refresh_token"] == "rotated-refresh"
    assert c._profile()["tokens"]["access_token"] == "renewed-access"
    provider.now += 3600; provider.refresh_error = "temporary_failure"
    with pytest.raises(ChatGPTError):
        c.models()
    assert c._profile()["tokens"]["refresh_token"] == "rotated-refresh"
    provider.refresh_error = "invalid_grant"
    with pytest.raises(ChatGPTError):
        c.models()
    assert c._profile()["tokens"] == {} and not c.public()["connected"]


def test_multiple_same_email_registrations_and_disconnect_retains_host(connection):
    c, provider = connection; authenticate(c); first = c.record["active"]
    authenticate(c, client="oaiapp_workspace_two"); second = c.record["active"]
    assert first != second and len(c.public()["profiles"]) == 2
    assert c.public()["profiles"][0]["label"] != c.public()["profiles"][1]["label"]
    host = c.record["host_id"]
    c.select(first); provider.revoke_error = True
    assert not c.disconnect(first)["revocation_confirmed"]
    assert not c.public()["connected"] and c.record["host_id"] == host
    c.select(second); provider.revoke_error = False
    assert c.disconnect(second)["revocation_confirmed"]


@pytest.mark.parametrize("event", ["response.failed", "response.incomplete", "truncated", "error"])
def test_stream_failure_is_not_a_success(event):
    payload = b"data: " + json.dumps({"type": event, "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}}).encode() + b"\n\n"
    with pytest.raises(ChatGPTError):
        completed_stream(BytesIO(payload))


def test_stream_completed_and_error_body_variants():
    result = {"status": "completed", "output": []}
    stream = b": heartbeat\n\ndata: " + json.dumps({"type": "response.completed", "response": result}).encode() + b"\n\n"
    assert completed_stream(BytesIO(stream)) == result
    assert failure(400, {"error": "invalid_grant"}).code == "invalid_grant"
    assert "fixture-access" not in str(failure(401, {"detail": "fixture-access"}))


def test_app_permissions_analysis_preserves_inventory_and_backup_excludes_credentials(tmp_path, signing_key):
    provider = Provider(signing_key); api = Mock(side_effect=AssertionError("No implicit API billing fallback"))
    app = create_app(Settings(tmp_path, network_enabled=True), chatgpt_fetch=provider, assistant_fetch=api)
    provider.connection = c = app.state.assistant.chatgpt; c.clock = lambda: provider.now
    with TestClient(app, client=("127.0.0.1", 1)) as local:
        with TestClient(app, client=("192.0.2.42", 1)) as remote:
            assert remote.post('/api/assistant/chatgpt/signin', json={}).status_code == 403
            assert remote.get('/api/assistant/chatgpt/signin').status_code == 403
            assert remote.post('/api/assistant/chatgpt/models', json={}).status_code == 403
        authenticate(c); c.models()
        settings = local.get('/api/configuration/assistant').json()
        body = {k: settings[k] for k in ['revision', 'model', 'web_search']}
        body.update(enabled=True, provider='chatgpt', chatgpt_model='vision-test', web_search=False)
        assert local.put('/api/configuration/assistant', json=body).status_code == 200
        with app.state.store.connect() as db:before = list(db.iterdump())
        image = BytesIO(); Image.new('RGB', (40, 30), 'white').save(image, 'PNG')
        reply = local.post('/api/assistant/analyse', json={'image': base64.b64encode(image.getvalue()).decode()})
        assert reply.status_code == 200, reply.text
        assert reply.json()['main'] == {'material_type': 'PETG'} and reply.json()['provider'] == 'chatgpt'
        api.assert_not_called()
        with app.state.store.connect() as db:assert list(db.iterdump()) == before
        backup = app.state.backups.collect('all')
        assert 'chatgpt-credentials.json' not in backup['configuration']
        assert not any(value in json.dumps(backup) for value in ['fixture-access', 'fixture-refresh', 'id_token'])
        assert local.post('/api/assistant/chatgpt/signin', json={}, headers={'Origin':'https://other.invalid'}).status_code == 403


def test_pending_login_is_blocked_if_station_access_is_revoked(connection):
    c, provider = connection
    allowed = [True]; started = c.start(authorize=lambda: allowed[0]); allowed[0] = False
    callback = started['callback_uri'] + '?' + urlencode({'state':c.pending[started['attempt_id']]['state'], 'client_id':'oaiapp_fixture', 'code':'c'})
    with pytest.raises(ChatGPTError):c.complete(started['attempt_id'], callback)
    assert provider.calls == [] and not c.public()['connected']


def test_http_loopback_callback_and_replay(connection):
    c, provider = connection
    started = c.start(); query = parse_qs(urlsplit(started['authorization_url']).query)
    url = started['callback_uri'] + '?' + urlencode({'state':query['state'][0], 'client_id':'oaiapp_fixture', 'code':'fixture'})
    with urlopen(url, timeout=5) as response:
        assert response.status == 200 and response.headers['Referrer-Policy'] == 'no-referrer'
        assert b'OPT Station' in response.read()
    assert c.public()['connected']
    with pytest.raises(ChatGPTError):c.complete(started['attempt_id'],url)


def test_invalid_signature_is_not_persisted(connection, signing_key):
    c, provider = connection
    another = rsa.generate_private_key(public_exponent=65537,key_size=2048).public_key().public_numbers()
    provider.keys['keys'][0]['n'] = encoded(another.n.to_bytes(256,'big'))
    with pytest.raises(ChatGPTError):authenticate(c)
    assert c.record['profiles'] == [] and 'fixture-access' not in c.path.read_text()


def test_cancellation_during_exchange_cannot_connect_an_account(connection):
    c, provider = connection
    original = c.fetch
    def interrupted(method,url,body=None,**kwargs):
        result=original(method,url,body,**kwargs)
        if url==TOKEN and body['grant_type']=='authorization_code':
            c.cancel(next(iter(c.pending)))
        return result
    c.fetch=interrupted
    with pytest.raises(ChatGPTError):authenticate(c)
    assert not c.public()['connected'] and c.record['profiles']==[]


def test_pending_signin_can_be_resumed_without_secrets_and_cancelled(connection):
    c, provider = connection
    started = c.start()
    assert c.resume() == {"pending": started}
    assert provider.calls == []
    assert c.pending[started['attempt_id']]['verifier'] not in json.dumps(c.resume())
    assert 'authorization_url' not in json.dumps(c.public())
    c.cancel(started['attempt_id'])
    assert c.resume() == {"pending": None}
    authenticate(c)
    assert c.resume() == {"pending": None} and c.public()['connected']


def test_pending_signin_expires_or_loses_access_without_blocking_new_login(connection):
    c, provider = connection
    allowed = [True]
    started = c.start(authorize=lambda: allowed[0])
    allowed[0] = False
    assert c.resume() == {"pending": None}
    assert c.pending[started['attempt_id']]['status'] == 'cancelled'
    again = c.start()
    provider.now += 601
    assert c.resume() == {"pending": None}
    assert c.pending[again['attempt_id']]['status'] == 'expired'
    assert provider.calls == []


def test_resume_endpoint_recovers_the_same_attempt_and_keeps_api_provider(tmp_path, signing_key):
    provider = Provider(signing_key)
    app = create_app(Settings(tmp_path), chatgpt_fetch=provider)
    provider.connection = c = app.state.assistant.chatgpt
    c.clock = lambda: provider.now
    with TestClient(app, client=('127.0.0.1', 1)) as local:
        started = local.post('/api/assistant/chatgpt/signin', json={}).json()
        assert local.get('/api/assistant/chatgpt/signin').json() == {'pending': started}
        assert local.post('/api/assistant/chatgpt/signin', json={}).status_code == 409
        assert local.get('/api/configuration/assistant').json()['provider'] == 'api'
        assert local.request('DELETE', '/api/assistant/chatgpt/signin/' + started['attempt_id'], json={}).status_code == 200
        assert local.get('/api/assistant/chatgpt/signin').json() == {'pending': None}
        assert provider.calls == []
