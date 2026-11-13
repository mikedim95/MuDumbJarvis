import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from test_phase1 import server
import task_api

AGENT = '22222222-2222-4222-8222-222222222222'
ISSUE = '33333333-3333-4333-8333-333333333333'
CEO = '44444444-4444-4444-8444-444444444444'
CHILD = '55555555-5555-4555-8555-555555555555'
headers = {'X-Jarvis-Token': server.hud_token()}


def transport(monkeypatch, handler, ceo=CEO):
    def init(self):
        self.company, self.project, self.agent = 'company', 'project', AGENT
        self.ceo = ceo
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
        assert body['workspaceSelection'] == {'kind': 'task_directory'}
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
        if request.url.path == '/api/companies/company/issues':
            return httpx.Response(200, json=[])
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


@pytest.mark.parametrize('selected', [None, CEO])
def test_objectives_route_to_configured_ceo(monkeypatch, selected):
    observed = []
    def handler(request):
        if request.url.path.endswith('/agents'):
            return httpx.Response(200, json=[{'id': AGENT, 'lifecycleState': 'ready'},
                {'id': CEO, 'role': 'ceo', 'lifecycleState': 'ready'}])
        body = json.loads(request.content)
        observed.append(body)
        return httpx.Response(201, json={**body, 'id': ISSUE, 'identifier': 'JAR-100'})
    transport(monkeypatch, handler)
    body = {'input': 'Produce a technical inventory report', 'request_id': str(uuid4()), 'objective': True}
    if selected:
        body['agent_id'] = selected
    with TestClient(server.app) as client:
        response = client.post('/api/tasks', json=body, headers=headers)
    assert response.status_code == 201
    assert observed[0]['assigneeAgentId'] == CEO
    assert response.json()['assigneeAgentId'] == CEO
    assert observed[0]['idempotencyKey'] == 'jarvis:' + body['request_id']


@pytest.mark.parametrize('ceo,selected,status', [(CEO, AGENT, 409), ('', None, 503)])
def test_objective_cannot_fall_back_to_another_worker(monkeypatch, ceo, selected, status):
    def handler(request):
        raise AssertionError('Invalid objective assignment reached Paperclip')
    transport(monkeypatch, handler, ceo=ceo)
    body = {'input': 'Objective', 'request_id': str(uuid4()), 'objective': True}
    if selected:
        body['agent_id'] = selected
    with TestClient(server.app) as client:
        response = client.post('/api/tasks', json=body, headers=headers)
    assert response.status_code == status


def test_agent_discovery_exposes_ceo_relationship_without_adapter_secrets(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json=[
        {'id': CEO, 'name': 'CEO', 'role': 'ceo', 'reportsTo': None,
         'adapterConfig': {'apiKey': 'sensitive'}},
        {'id': AGENT, 'name': 'JARVIS-01', 'role': 'general', 'reportsTo': CEO}]))
    with TestClient(server.app) as client:
        response = client.get('/api/agents', headers=headers)
    assert response.status_code == 200
    assert response.json()['ceo_id'] == CEO
    assert response.json()['agents'][1]['reportsTo'] == CEO
    assert response.json()['agents'][0]['role'] == 'ceo'
    assert 'sensitive' not in response.text and 'adapterConfig' not in response.text


def test_task_children_are_authoritative_and_scoped_before_detail_reads(monkeypatch):
    root = {'id': ISSUE, 'companyId': 'company', 'projectId': 'project',
        'parentId': None, 'status': 'in_progress', 'assigneeAgentId': CEO}
    valid = {'id': CHILD, 'companyId': 'company', 'projectId': 'project',
        'parentId': ISSUE, 'status': 'done', 'assigneeAgentId': AGENT}
    excluded = [
        {**valid, 'id': 'wrong-company', 'companyId': 'other'},
        {**valid, 'id': 'wrong-project', 'projectId': 'other'},
        {**valid, 'id': 'wrong-parent', 'parentId': 'different'}]
    reads = []
    def handler(request):
        path = request.url.path
        reads.append(path)
        if path == '/api/companies/company/issues':
            assert request.url.params['projectId'] == 'project'
            return httpx.Response(200, json=[root, valid, *excluded])
        if path == '/api/issues/' + ISSUE:
            return httpx.Response(200, json=root)
        if path in ('/api/issues/' + ISSUE + '/comments', '/api/issues/' + ISSUE + '/runs'):
            return httpx.Response(200, json=[])
        if path == '/api/issues/' + CHILD + '/comments':
            return httpx.Response(200, json=[{'id': 'worker-result', 'body': 'Verified inventory',
                'authorAgentId': AGENT}])
        if path == '/api/issues/' + CHILD + '/runs':
            return httpx.Response(200, json=[{'runId': 'worker-run', 'status': 'succeeded'}])
        raise AssertionError('Out-of-scope child was read: ' + path)
    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        response = client.get('/api/tasks/' + ISSUE, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'in_progress', 'Child completion must not invent parent completion'
    assert data['parentId'] is None
    assert len(data['children']) == 1
    child = data['children'][0]
    assert child['id'] == CHILD and child['parentId'] == ISSUE
    assert child['assigneeAgentId'] == AGENT and child['status'] == 'done'
    assert child['comments'][0]['body'] == 'Verified inventory'
    assert child['runs'][0] == {'runId': 'worker-run', 'status': 'succeeded',
        'startedAt': None, 'finishedAt': None, 'errorCode': None, 'error': None}
    assert not any('wrong-' in path for path in reads)


def test_history_filters_upstream_company_and_project_results(monkeypatch):
    valid = {'id': ISSUE, 'companyId': 'company', 'projectId': 'project', 'parentId': None}
    transport(monkeypatch, lambda request: httpx.Response(200, json=[valid,
        {**valid, 'id': 'other-company', 'companyId': 'other'},
        {**valid, 'id': 'other-project', 'projectId': 'other'}]))
    with TestClient(server.app) as client:
        response = client.get('/api/tasks', headers=headers)
    assert response.status_code == 200
    assert [task['id'] for task in response.json()['tasks']] == [ISSUE]
