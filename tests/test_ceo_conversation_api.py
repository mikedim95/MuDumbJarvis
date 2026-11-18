"""Native CEO conversation and human-control boundaries; no model calls."""
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from test_phase1 import server
import task_api

CEO = '11111111-1111-4111-8111-111111111111'
WORKER = '22222222-2222-4222-8222-222222222222'
ISSUE = '33333333-3333-4333-8333-333333333333'
CHILD = '44444444-4444-4444-8444-444444444444'
APPROVAL = '55555555-5555-4555-8555-555555555555'
HEADERS = {'X-Jarvis-Token': server.hud_token()}


def transport(monkeypatch, handler, workforce=True):
    def initialize(self):
        self.company, self.project, self.agent, self.ceo = 'company', 'general', WORKER, CEO
        self.workforce = workforce
        self.http = httpx.AsyncClient(base_url='http://paperclip/api/', transport=httpx.MockTransport(handler))
    monkeypatch.setattr(task_api.Paperclip, '__init__', initialize)


@pytest.fixture
def native(monkeypatch):
    state = SimpleNamespace(issue={'id': ISSUE, 'identifier': 'JAR-CEO', 'companyId': 'company',
        'projectId': 'managed-project', 'parentId': None, 'assigneeAgentId': CEO, 'status': 'done'},
        holds=[], calls=[], comments={}, lose_ack=False)
    def handler(request):
        path = request.url.path; body = json.loads(request.content) if request.content else None
        state.calls.append((request.method, path, body))
        if request.method == 'GET' and path == '/api/issues/' + ISSUE:
            return httpx.Response(200, json=state.issue)
        if request.method == 'GET' and path == '/api/issues/' + ISSUE + '/tree-holds':
            assert request.url.params['status'] == 'active'
            return httpx.Response(200, json=state.holds)
        if request.method == 'POST' and path == '/api/issues/' + ISSUE + '/comments':
            key = body['clientRequestId']
            state.comments.setdefault(key, {'id': 'native-comment-' + key, 'body': body['body'], 'authorUserId': 'board-user'})
            if body.get('reopen') and state.issue['status'] == 'done': state.issue['status'] = 'todo'
            if state.lose_ack:
                state.lose_ack = False
                raise httpx.ReadTimeout('Uncertain native acknowledgement', request=request)
            return httpx.Response(201, json=state.comments[key])
        raise AssertionError('Unexpected native request: ' + request.method + ' ' + path)
    transport(monkeypatch, handler)
    return state


def test_messages_require_auth_and_cookie_origin_before_native_reads(native):
    body = {'input': 'Continue the reviewed objective.', 'request_id': str(uuid4())}
    with TestClient(server.app) as client:
        assert client.post(f'/api/tasks/{ISSUE}/messages', json=body).status_code == 401
        client.cookies.set('jarvis_token', server.hud_token())
        assert client.post(f'/api/tasks/{ISSUE}/messages', json=body, headers={'Origin': 'https://foreign.example'}).status_code == 403
    assert native.calls == []


@pytest.mark.parametrize('status', ['done', 'in_progress', 'in_review', 'blocked', 'todo'])
def test_human_message_uses_native_request_id_and_reopens_or_resumes_same_objective(native, status):
    native.issue['status'] = status
    request_id = str(uuid4()); text = '  Add a scoped follow-up using the existing team.  '
    with TestClient(server.app) as client:
        response = client.post(f'/api/tasks/{ISSUE}/messages', json={'input': text, 'request_id': request_id}, headers=HEADERS)
    assert response.status_code == 200
    posts = [(path, body) for method, path, body in native.calls if method == 'POST']
    assert len(posts) == 1 and posts[0][0] == f'/api/issues/{ISSUE}/comments'
    assert posts[0][1] == {'body': f'[JARVIS USER MESSAGE request_id={request_id}]\n' + text.strip(),
        'clientRequestId': request_id, 'reopen': True, 'resume': True}
    result = response.json()
    assert result['task']['id'] == ISSUE and result['task']['assigneeAgentId'] == CEO
    assert result['comment_id'] == 'native-comment-' + request_id
    assert result['task']['status'] == ('todo' if status == 'done' else status)


def test_uncertain_ack_retries_exact_native_payload_without_creating_second_message(native):
    native.lose_ack = True
    body = {'input': 'Review this additional requirement with the existing team.', 'request_id': str(uuid4())}
    with TestClient(server.app) as client:
        first = client.post(f'/api/tasks/{ISSUE}/messages', json=body, headers=HEADERS)
        replay = client.post(f'/api/tasks/{ISSUE}/messages', json=body, headers=HEADERS)
    assert first.status_code == 502 and replay.status_code == 200
    posts = [payload for method, _, payload in native.calls if method == 'POST']
    assert len(posts) == 2 and posts[0] == posts[1]
    assert len(native.comments) == 1
    assert replay.json()['task']['id'] == ISSUE


def test_reused_message_nonce_cannot_claim_different_text(native):
    request_id = str(uuid4())
    with TestClient(server.app) as client:
        assert client.post(f'/api/tasks/{ISSUE}/messages', json={'input': 'Original request.', 'request_id': request_id}, headers=HEADERS).status_code == 200
        response = client.post(f'/api/tasks/{ISSUE}/messages', json={'input': 'Changed request.', 'request_id': request_id}, headers=HEADERS)
    assert response.status_code == 409 and len(native.comments) == 1


@pytest.mark.parametrize('change,status', [({'parentId': CHILD}, 409), ({'assigneeAgentId': WORKER}, 409),
    ({'companyId': 'foreign'}, 404), ({'status': 'cancelled'}, 409)])
def test_messages_cannot_address_children_foreign_companies_or_other_ceos(native, change, status):
    native.issue.update(change)
    with TestClient(server.app) as client:
        response = client.post(f'/api/tasks/{ISSUE}/messages', json={'input': 'Resume.', 'request_id': str(uuid4())}, headers=HEADERS)
    assert response.status_code == status
    assert not any(method != 'GET' for method, _, _ in native.calls)


@pytest.mark.parametrize('holds', [[{'id': 'hold', 'mode': 'cancel'}], {'holds': [{'id': 'hold', 'mode': 'pause'}]}])
def test_chat_cannot_release_native_stop_hold(native, holds):
    native.holds = holds
    with TestClient(server.app) as client:
        response = client.post(f'/api/tasks/{ISSUE}/messages', json={'input': 'Continue.', 'request_id': str(uuid4())}, headers=HEADERS)
    assert response.status_code == 409 and 'hold' in response.text
    assert native.comments == {}


def test_messages_do_not_enable_workforce_mode_implicitly(native, monkeypatch):
    original = task_api.Paperclip.__init__
    def initialize(self): original(self); self.workforce = False; self.project = 'managed-project'
    monkeypatch.setattr(task_api.Paperclip, '__init__', initialize)
    with TestClient(server.app) as client:
        response = client.post(f'/api/tasks/{ISSUE}/messages', json={'input': 'Continue.', 'request_id': str(uuid4())}, headers=HEADERS)
    assert response.status_code == 409 and native.comments == {}


@pytest.mark.parametrize('input', ['', '  ', 'x' * 8001])
def test_empty_and_oversized_messages_do_not_persist(native, input):
    with TestClient(server.app) as client:
        response = client.post(f'/api/tasks/{ISSUE}/messages', json={'input': input, 'request_id': str(uuid4())}, headers=HEADERS)
    assert response.status_code == 422 and native.comments == {}


@pytest.mark.parametrize('workforce', [False, True])
def test_history_scope_expands_only_to_configured_company(monkeypatch, workforce):
    issues = [{'id': ISSUE, 'companyId': 'company', 'projectId': 'general'},
        {'id': CHILD, 'companyId': 'company', 'projectId': 'managed-project'},
        {'id': 'foreign', 'companyId': 'foreign', 'projectId': 'general'}]
    def handler(request):
        assert request.url.path == '/api/companies/company/issues'
        assert dict(request.url.params) == ({} if workforce else {'projectId': 'general'})
        return httpx.Response(200, json=issues)
    transport(monkeypatch, handler, workforce)
    with TestClient(server.app) as client: response = client.get('/api/tasks', headers=HEADERS)
    assert response.status_code == 200
    assert {item['id'] for item in response.json()['tasks']} == ({ISSUE, CHILD} if workforce else {ISSUE})


@pytest.mark.parametrize('workforce', [False, True])
def test_cross_project_detail_keeps_its_own_child_scope(monkeypatch, workforce):
    root = {'id': ISSUE, 'companyId': 'company', 'projectId': 'managed-project', 'assigneeAgentId': CEO}
    valid = {'id': CHILD, 'companyId': 'company', 'projectId': 'managed-project', 'parentId': ISSUE}
    calls = []
    def handler(request):
        path = request.url.path; calls.append(path)
        if path == f'/api/issues/{ISSUE}': return httpx.Response(200, json=root)
        if path == '/api/companies/company/routines':
            return httpx.Response(200, json=[])
        if path == '/api/companies/company/issues':
            assert request.url.params['projectId'] == 'managed-project'
            return httpx.Response(200, json=[valid, {**valid, 'id': 'foreign', 'companyId': 'foreign'},
                {**valid, 'id': 'wrong-project', 'projectId': 'general'}])
        if path in [f'/api/issues/{i}/{kind}' for i in (ISSUE, CHILD) for kind in ('comments', 'runs')]:
            return httpx.Response(200, json=[])
        raise AssertionError('An unrelated child was read')
    transport(monkeypatch, handler, workforce)
    with TestClient(server.app) as client: response = client.get(f'/api/tasks/{ISSUE}', headers=HEADERS)
    assert response.status_code == (200 if workforce else 404)
    if workforce: assert [child['id'] for child in response.json()['children']] == [CHILD]
    else: assert calls == [f'/api/issues/{ISSUE}']


@pytest.mark.parametrize('decision', ['approve', 'reject'])
def test_native_human_decision_is_only_path_to_employee_termination(monkeypatch, decision):
    approval = {'id': APPROVAL, 'companyId': 'company', 'type': 'request_board_approval', 'status': 'pending',
        'requestedByAgentId': CEO, 'payload': {'kind': 'jarvis_staff_termination', 'agentId': WORKER, 'reason': 'Human requested staff removal.'}}
    employee = {'id': WORKER, 'companyId': 'company', 'reportsTo': CEO, 'status': 'idle'}
    calls = []
    def handler(request):
        path = request.url.path; calls.append((request.method, path))
        if request.method == 'GET':
            if path == f'/api/approvals/{APPROVAL}': return httpx.Response(200, json=approval)
            if path == f'/api/approvals/{APPROVAL}/issues': return httpx.Response(200, json=[{'id': ISSUE, 'companyId': 'company', 'projectId': 'managed-project'}])
            if path == '/api/companies/company/agents': return httpx.Response(200, json=[employee])
        if request.method == 'POST' and path == f'/api/approvals/{APPROVAL}/{decision}':
            assert json.loads(request.content) == {'decisionNote': 'Reviewed human decision.'}
            approval['status'] = 'approved' if decision == 'approve' else 'rejected'
            return httpx.Response(200, json=approval)
        if request.method == 'POST' and path == f'/api/agents/{WORKER}/terminate':
            assert approval['status'] == 'approved' and json.loads(request.content) == {}
            employee['status'] = 'terminated'; return httpx.Response(200, json=employee)
        raise AssertionError('Unexpected or destructive native operation')
    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        payload = {'decision': decision, 'note': 'Reviewed human decision.'}
        assert client.post(f'/api/approvals/{APPROVAL}/decision', json=payload).status_code == 401
        response = client.post(f'/api/approvals/{APPROVAL}/decision', json=payload, headers=HEADERS)
        replay = client.post(f'/api/approvals/{APPROVAL}/decision', json=payload, headers=HEADERS)
    assert response.status_code == replay.status_code == 200
    terminations = [path for method, path in calls if method == 'POST' and path.endswith('/terminate')]
    assert len(terminations) == (1 if decision == 'approve' else 0)
    if decision == 'approve': assert response.json()['execution']['history_preserved'] is True
    assert not any(method == 'DELETE' for method, _ in calls)


@pytest.mark.parametrize('invalid', ['workforce-disabled', 'wrong-requester', 'other-manager', 'foreign-employee', 'self-removal', 'foreign-linked-issue'])
def test_approved_staff_change_still_requires_current_ceo_company_and_direct_hierarchy(monkeypatch, invalid):
    approval = {'id': APPROVAL, 'companyId': 'company', 'type': 'request_board_approval', 'status': 'approved',
        'requestedByAgentId': WORKER if invalid == 'wrong-requester' else CEO,
        'payload': {'kind': 'jarvis_staff_termination', 'agentId': CEO if invalid == 'self-removal' else WORKER}}
    employee = {'id': approval['payload']['agentId'], 'companyId': 'foreign' if invalid == 'foreign-employee' else 'company',
        'reportsTo': WORKER if invalid == 'other-manager' else CEO, 'status': 'idle'}
    writes = []
    def handler(request):
        path = request.url.path
        if request.method != 'GET': writes.append(path); raise AssertionError('An out-of-scope employee was changed')
        if path == f'/api/approvals/{APPROVAL}': return httpx.Response(200, json=approval)
        if path == f'/api/approvals/{APPROVAL}/issues':
            return httpx.Response(200, json=[{'id': ISSUE, 'companyId': 'foreign' if invalid == 'foreign-linked-issue' else 'company', 'projectId': 'general'}])
        if path == '/api/companies/company/agents': return httpx.Response(200, json=[employee])
        raise AssertionError('Unexpected scope read')
    transport(monkeypatch, handler, workforce=invalid != 'workforce-disabled')
    with TestClient(server.app) as client:
        response = client.post(f'/api/approvals/{APPROVAL}/decision', json={'decision': 'approve', 'note': 'Reviewed.'}, headers=HEADERS)
    assert response.status_code == (404 if invalid == 'foreign-linked-issue' else 409)
    assert writes == [] and employee['status'] == 'idle'
