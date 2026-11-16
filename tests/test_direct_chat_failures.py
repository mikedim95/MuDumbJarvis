import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_phase1 import server


class SSE:
    def __init__(self, events):
        self.events = events

    def iter_lines(self, **kwargs):
        for kind, body in self.events:
            yield 'event: ' + kind
            yield 'data: ' + json.dumps(body)
            yield ''


def test_saved_route_failure_is_a_safe_message_not_a_truncated_runtime_dump():
    payload = {'session_id': 'api_example', 'completed': False, 'api_key': 'private-upstream-credential',
        'runtime': {'provider': '', 'model': '', 'route_source': 'session_model_lock',
                    'requested': {'provider': 'custom', 'api_key': 'another-private-value'}}}
    with pytest.raises(server.HermesChatError) as failure:
        list(server.HermesAPI._parse_sse(SSE([('error', payload)])))
    assert failure.value.code == 'model_route_unavailable'
    assert 'saved model connection' in str(failure.value)
    assert 'runtime' not in str(failure.value) and 'private' not in str(failure.value)
    assert 'api_key' not in json.dumps(failure.value.diagnostic)


def test_failed_stream_does_not_turn_partial_output_into_a_completed_reply():
    events = [('assistant.delta', {'delta': 'unfinished output'}), ('run.failed', {'error': 'private details'})]
    stream = server.HermesAPI._parse_sse(SSE(events))
    assert next(stream) == ('text', 'unfinished output')
    with pytest.raises(server.HermesChatError): next(stream)


@pytest.mark.parametrize('status', [401, 403, 404, 429, 502])
def test_http_failure_does_not_read_or_expose_upstream_body(monkeypatch, status):
    response = Mock(status_code=status)
    monkeypatch.setattr(server.requests, 'post', Mock(return_value=response))
    api = server.HermesAPI({})
    monkeypatch.setattr(api, 'headers', lambda: {})
    with pytest.raises(server.HermesChatError) as failure:
        list(api.chat_stream_events('api_example', 'message', 5))
    assert failure.value.status_code == status
    assert 'private' not in str(failure.value)
    response.close.assert_called_once()


def chat(monkeypatch, events):
    fake = Mock()
    fake.get_session_id.return_value = 'api_preserved'
    fake.chat_stream_events.side_effect = lambda *args: iter(events)
    monkeypatch.setattr(server, 'HERMES', fake)
    return fake


@pytest.mark.parametrize('events', [[], [('text', 'partial only')],
    [('final', json.dumps({'content': 'interrupted answer', 'interrupted': True}))]])
def test_ended_or_interrupted_chat_cannot_report_success(monkeypatch, events):
    fake = chat(monkeypatch, events)
    with TestClient(server.app) as client:
        response = client.post('/api/chat', json={'input': 'hello'}, headers={'X-Jarvis-Token': server.hud_token()})
    assert response.status_code == 502 and response.json()['error_code'] == 'incomplete_reply'
    assert 'text' not in response.json() and response.json()['reference']
    fake.chat_stream_events.assert_called_once()


def test_unknown_exception_is_redacted_and_not_retried_from_a_404_in_its_text(monkeypatch, caplog):
    fake = chat(monkeypatch, [])
    fake.chat_stream_events.side_effect = RuntimeError('404 Bearer private-upstream-credential')
    with TestClient(server.app) as client:
        response = client.post('/api/chat', json={'input': 'hello'}, headers={'X-Jarvis-Token': server.hud_token()})
    body = response.json()
    assert response.status_code == 502 and body['error_code'] == 'hermes_chat_failed'
    assert 'private' not in response.text and 'private' not in caplog.text
    assert '404' not in response.text and body['reference']
    fake.get_session_id.assert_called_once()
    fake.chat_stream_events.assert_called_once()


def test_only_actual_missing_session_recreates_once_and_returns_the_real_reply(monkeypatch):
    fake = chat(monkeypatch, [])
    fake.get_session_id.side_effect = ['api_missing', 'api_recreated']
    fake.chat_stream_events.side_effect = [server.HermesChatError('Session unavailable', status_code=404),
        iter([('run', 'run_real'), ('final', json.dumps({'content': 'READY', 'interrupted': False}))])]
    with TestClient(server.app) as client:
        response = client.post('/api/chat', json={'input': 'hello','conversation':'jarvis-main'}, headers={'X-Jarvis-Token': server.hud_token()})
    assert response.status_code == 200 and response.json()['text'] == 'READY'
    assert response.json()['run_id'] == 'run_real'
    assert fake.get_session_id.call_args_list[1].kwargs == {'force_new': True}
