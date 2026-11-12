import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from test_phase1 import server
import task_api

AGENT = '22222222-2222-4222-8222-222222222222'
ISSUE = '33333333-3333-4333-8333-333333333333'
headers = {'X-Jarvis-Token': server.hud_token()}


def transport(monkeypatch, handler):
    def init(self):
        self.company, self.project, self.agent = 'company', 'project', AGENT
        self.http = httpx.AsyncClient(base_url='http://paperclip/api/', transport=httpx.MockTransport(handler))
    monkeypatch.setattr(task_api.Paperclip, '__init__', init)


@pytest.mark.parametrize('method,path', [('GET', '/api/tasks'), ('GET', '/api/tasks/' + ISSUE),
    ('GET', '/api/agents'), ('POST', '/api/tasks')])
def test_task_routes_require_auth(method, path):
    with TestClient(server.app) as client:
        assert client.request(method, path).status_code == 401


def test_submission_nonce_reaches_authoritative_store_and_replays(monkeypatch):
    created = {}
    def handler(request):
        if request.url.path.endswith('/agents'):
            return httpx.Response(200, json=[{'id': AGENT, 'lifecycleState': 'ready'}])
        body = json.loads(request.content)
        assert body['allowDuplicate'] is True
        key = body['idempotencyKey']
        created.setdefault(key, {**body, 'id': ISSUE, 'identifier': 'JAR-99', 'companyId': 'company'})
        return httpx.Response(201, json=created[key])
    transport(monkeypatch, handler)
    body = {'input': 'Retrieve the real model inventory', 'request_id': str(uuid4())}
    with TestClient(server.app) as client:
        first = client.post('/api/tasks', json=body, headers=headers)
        replay = client.post('/api/tasks', json=body, headers=headers)
        assert first.status_code == replay.status_code == 201
        assert first.json()['id'] == replay.json()['id'] == ISSUE
        assert len(created) == 1
        assert not any('key' in key.lower() for key in first.json())


def test_run_errors_and_comments_are_returned_without_false_completion(monkeypatch):
    def handler(request):
        if request.url.path.endswith('/comments'):
            return httpx.Response(200, json=[{'id': 'comment', 'body': 'Actual progress'}])
        if request.url.path.endswith('/runs'):
            return httpx.Response(200, json=[{'runId': 'run', 'status': 'failed', 'error': 'Gateway unavailable'}])
        return httpx.Response(200, json={'id': ISSUE, 'companyId': 'company', 'projectId': 'project', 'status': 'in_progress'})
    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        data = client.get('/api/tasks/' + ISSUE, headers=headers).json()
    assert data['status'] == 'in_progress'
    assert data['runs'][0]['error'] == 'Gateway unavailable'
    assert data['comments'][0]['body'] == 'Actual progress'


def test_other_project_is_not_exposed(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={'companyId': 'other', 'projectId': 'other'}))
    with TestClient(server.app) as client:
        assert client.get('/api/tasks/' + ISSUE, headers=headers).status_code == 404


def test_unreachable_paperclip_is_a_clear_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError('sensitive internal detail', request=request)
    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        response = client.get('/api/tasks', headers=headers)
    assert response.status_code == 502
    assert 'Cannot reach Paperclip' in response.json()['detail']
    assert 'sensitive' not in response.text


def test_cookie_auth_cannot_submit_cross_origin():
    with TestClient(server.app) as client:
        client.cookies.set('jarvis_token', server.hud_token())
        assert client.post('/api/tasks', headers={'Origin': 'https://evil.example'},
            json={'input': 'test', 'request_id': str(uuid4())}).status_code == 403


def test_tasks_fail_closed_if_hud_auth_is_unconfigured(monkeypatch):
    monkeypatch.delenv('JARVIS_HUD_TOKEN', raising=False)
    with TestClient(server.app) as client:
        assert client.get('/api/tasks').status_code == 401
