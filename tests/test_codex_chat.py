import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_phase1 import server
from test_direct_chat_failures import SSE, chat


def route(monkeypatch):
    monkeypatch.setenv('JARVIS_CHAT_PROVIDER', 'openai-codex')
    monkeypatch.setenv('JARVIS_CHAT_MODEL', 'gpt-6.1-sol')


def test_every_chat_request_overrides_stale_local_session_lock_with_codex(monkeypatch):
    route(monkeypatch)
    response = Mock(status_code=200)
    response.iter_lines.return_value = []
    post = Mock(return_value=response)
    monkeypatch.setattr(server.requests, 'post', post)
    api = server.HermesAPI({})
    monkeypatch.setattr(api, 'headers', lambda: {})
    list(api.chat_stream_events('api_existing_history', 'hello', 10))
    assert post.call_args.kwargs['json'] == {'input': 'hello', 'provider': 'openai-codex',
        'model': 'gpt-6.1-sol', 'require_model_lock': True}
    assert '/api_existing_history/' in post.call_args.args[0]


def test_incomplete_operator_route_never_falls_back(monkeypatch):
    route(monkeypatch); monkeypatch.delenv('JARVIS_CHAT_MODEL')
    post = Mock(); monkeypatch.setattr(server.requests, 'post', post)
    with pytest.raises(server.HermesChatError):
        list(server.HermesAPI({}).chat_stream_events('api_existing', 'hello', 10))
    post.assert_not_called()


def test_success_metadata_exposes_only_verified_provider_fields_not_credentials():
    payload = {'content': 'Actual reply', 'runtime': {'provider': 'openai-codex', 'model': 'gpt-6.1-sol',
        'route_source': 'raw_request', 'api_key': 'never-show', 'requested': {'api_key': 'never-show'}}}
    kind, raw = next(server.HermesAPI._parse_sse(SSE([('assistant.completed', payload)])))
    assert kind == 'final'
    assert json.loads(raw)['runtime'] == {'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'route_source': 'raw_request'}
    assert 'never-show' not in raw and 'api_key' not in raw


@pytest.mark.parametrize('runtime', [{}, {'provider': 'custom', 'model': 'jarvis-hermes-aigoat24:3b'},
    {'provider': 'openai-codex', 'model': 'wrong-model'}])
def test_local_or_unknown_inference_cannot_be_accepted_in_codex_mode(monkeypatch, runtime):
    route(monkeypatch)
    fake = chat(monkeypatch, [('final', json.dumps({'content': 'A reply is not provider evidence', 'runtime': runtime}))])
    with TestClient(server.app) as client:
        response = client.post('/api/chat', json={'input': 'hello'}, headers={'X-Jarvis-Token': server.hud_token()})
    assert response.status_code == 502 and response.json()['error_code'] == 'chat_provider_mismatch'
    assert 'text' not in response.json()
    fake.chat_stream_events.assert_called_once()


def test_confirmed_codex_reply_is_returned_and_displayed_as_codex(monkeypatch):
    route(monkeypatch)
    runtime = {'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'model_lock': 'confirmed'}
    chat(monkeypatch, [('final', json.dumps({'content': 'Actual Codex reply', 'runtime': runtime}))])
    with TestClient(server.app) as client:
        response = client.post('/api/chat', json={'input': 'hello'}, headers={'X-Jarvis-Token': server.hud_token()})
        usage = client.get('/api/usage', headers={'X-Jarvis-Token': server.hud_token()}).json()
    assert response.status_code == 200 and response.json()['runtime'] == runtime
    assert usage['runtime']['provider'] == 'openai-codex' and usage['runtime']['model'] == 'gpt-6.1-sol'


@pytest.mark.parametrize('preliminary', [{'completed': False}, {}])
def test_native_auth_failure_wins_over_preliminary_reply_with_no_model(monkeypatch, preliminary):
    route(monkeypatch)
    failed = {'completed': False, 'turn_exit_reason': 'auth_permanent',
              'runtime': {'provider': '', 'model': '', 'api_key': 'private-detail'}}
    stream = SSE([('assistant.completed', dict(preliminary, content='private-detail')),
                  ('run.failed', failed), ('done', {})])
    fake = chat(monkeypatch, [])
    fake.chat_stream_events.side_effect = lambda *args: server.HermesAPI._parse_sse(stream)
    with TestClient(server.app) as client:
        response = client.post('/api/chat', json={'input': 'hello'}, headers={'X-Jarvis-Token': server.hud_token()})
    assert response.status_code == 502 and response.json()['error_code'] == 'chat_provider_auth_failed'
    assert 'sign-in' in response.json()['error'] and 'private-detail' not in response.text
    assert 'text' not in response.json()
    fake.chat_stream_events.assert_called_once()


def test_failed_native_final_with_a_verified_model_and_lost_error_event_is_incomplete(monkeypatch):
    route(monkeypatch)
    fake = chat(monkeypatch, [])
    payload = {'content': 'partial data', 'completed': False, 'partial': True,
               'runtime': {'provider': 'openai-codex', 'model': 'gpt-6.1-sol'}}
    fake.chat_stream_events.side_effect = lambda *args: server.HermesAPI._parse_sse(SSE([('assistant.completed', payload)]))
    with TestClient(server.app) as client:
        response = client.post('/api/chat', json={'input': 'hello'}, headers={'X-Jarvis-Token': server.hud_token()})
    assert response.status_code == 502 and response.json()['error_code'] == 'incomplete_reply'
    assert 'partial data' not in response.text


def test_real_tool_hook_broadcasts_only_to_authenticated_hud_socket(monkeypatch):
    route(monkeypatch)
    runtime = {'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'model_lock': 'confirmed'}
    chat(monkeypatch, [('tool', json.dumps({'name': 'local_ollama_models', 'preview': 'read metadata'})),
        ('final', json.dumps({'content': 'Retrieved actual metadata', 'runtime': runtime}))])
    with TestClient(server.app) as client:
        client.cookies.set('jarvis_token', server.hud_token())
        with client.websocket_connect('/ws', headers={'origin': 'http://localhost:8765'}) as socket:
            assert socket.receive_json()['type'] == 'status'
            response = client.post('/api/chat', json={'input': 'List installed models'})
            first, last = socket.receive_json(), socket.receive_json()
    assert response.status_code == 200
    assert first['type'] == last['type'] == 'chat_activity'
    assert first['kind'] == 'tool' and first['tool']['name'] == 'local_ollama_models'
    assert last['kind'] == 'reply' and last['runtime'] == runtime
    assert first['request_id'] == last['request_id'] == response.json()['request_id']


@pytest.mark.parametrize('credential', [None, 'wrong-token', 'valid'])
def test_no_origin_socket_still_requires_authentication(credential):
    from starlette.websockets import WebSocketDisconnect
    headers = {} if credential is None else {'X-Jarvis-Token':
        server.hud_token() if credential == 'valid' else credential}
    with TestClient(server.app) as client:
        if credential == 'valid':
            with client.websocket_connect('/ws', headers=headers) as socket:
                assert socket.receive_json()['type'] == 'status'
        else:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect('/ws', headers=headers):
                    pass


def test_socket_token_cannot_bypass_bad_browser_origin():
    from starlette.websockets import WebSocketDisconnect
    with TestClient(server.app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', headers={
                'origin': 'https://evil.example', 'X-Jarvis-Token': server.hud_token()}):
                pass
