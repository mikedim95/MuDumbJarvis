import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from test_phase1 import server
from test_tasks import transport, headers, ISSUE, CHILD, CEO, AGENT
import task_monitor as monitor

RUN = '66666666-6666-4666-8666-666666666666'
ARTIFACT = '77777777-7777-4777-8777-777777777777'
APPROVAL = '88888888-8888-4888-8888-888888888888'
ROOT = {'id': ISSUE, 'companyId': 'company', 'projectId': 'project', 'status': 'blocked', 'assigneeAgentId': AGENT}


@pytest.mark.parametrize('method,path', [('GET', '/api/monitor'), ('GET', f'/api/tasks/{ISSUE}/monitor'),
    ('GET', f'/api/tasks/{ISSUE}/runs/{RUN}/log'), ('GET', f'/api/tasks/{ISSUE}/artifacts/{ARTIFACT}'),
    ('POST', f'/api/tasks/{ISSUE}/cancel-preview'), ('POST', f'/api/tasks/{ISSUE}/cancel'),
    ('POST', f'/api/tasks/{ISSUE}/retry'), ('POST', f'/api/approvals/{APPROVAL}/decision')])
def test_monitor_routes_require_auth(method, path):
    with TestClient(server.app) as c:
        assert c.request(method, path).status_code == 401


@pytest.mark.parametrize('path,body', [(f'/api/tasks/{ISSUE}/cancel', {'reason': 'Human request'}),
    (f'/api/tasks/{ISSUE}/retry', {'request_id': str(uuid4()), 'observed_run_id': RUN}),
    (f'/api/approvals/{APPROVAL}/decision', {'decision': 'approve', 'note': 'Human review'})])
def test_monitor_mutations_preserve_csrf(path, body):
    with TestClient(server.app) as c:
        c.cookies.set('jarvis_token', server.hud_token())
        assert c.post(path, json=body, headers={'Origin': 'https://evil.example'}).status_code == 403


def sign(proof, key):
    derived = hmac.new(key.encode(), ('jarvis-employee-proof-v3:' + proof['agent_id']).encode(), hashlib.sha256).hexdigest()
    signature = hmac.new(derived.encode(), json.dumps(proof, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
    return {**proof, 'signature': signature}


def test_evidence_signature_authorship_scope_and_tamper(monkeypatch):
    key = 'private-test-proof-key'
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', key)
    proof = {'version': 3, 'kind': 'tool_event', 'agent_id': AGENT, 'company_id': 'company',
        'issue_id': ISSUE, 'paperclip_run_id': RUN, 'session_id': f'paperclip:company:company:agent:{AGENT}:issue:{ISSUE}',
        'tool': 'terminal', 'success': True, 'result': {'output': 'Ran 2 tests\nOK'}}
    comment = {'id': 'c', 'authorAgentId': AGENT, 'body': 'JARVIS_TOOL_EVENT=' + json.dumps(sign(proof, key))}
    runs = [{'runId': RUN, 'status': 'running'}]
    result = monitor.evidence(comment, ROOT, runs, 'company')[0]
    assert result['verified'] and result['run_status'] == 'running'
    assert result['tools'][0]['result']['output'] == 'Ran 2 tests\nOK'
    for changed in ({**comment, 'authorAgentId': CEO}, {**comment, 'body': comment['body'].replace('2 tests', '9 tests')}):
        assert not monitor.evidence(changed, ROOT, runs, 'company')[0]['verified']
    assert not monitor.evidence(comment, {**ROOT, 'id': CHILD}, runs, 'company')[0]['verified']
    assert not monitor.evidence(comment, ROOT, [], 'company')[0]['verified']
    monkeypatch.delenv('JARVIS_EXECUTION_PROOF_KEY')
    assert not monitor.evidence(comment, ROOT, runs, 'company')[0]['verified']


def test_log_requires_native_run_task_company_before_read(monkeypatch):
    reads = []
    def handler(r):
        reads.append(r.url.path)
        if r.url.path == '/api/issues/' + ISSUE: return httpx.Response(200, json=ROOT)
        if r.url.path == '/api/heartbeat-runs/' + RUN:
            return httpx.Response(200, json={'companyId': 'company', 'contextSnapshot': {'issueId': CHILD}})
        raise AssertionError('Out-of-scope log read')
    transport(monkeypatch, handler)
    with TestClient(server.app) as c:
        assert c.get(f'/api/tasks/{ISSUE}/runs/{RUN}/log', headers=headers).status_code == 404
    assert len(reads) == 2


def test_log_redacts_known_secrets_and_omits_internal_storage(monkeypatch):
    monkeypatch.setenv('PAPERCLIP_API_KEY', 'known-private-board-key')
    def handler(r):
        if r.url.path == '/api/issues/' + ISSUE: return httpx.Response(200, json=ROOT)
        if r.url.path.endswith('/log'):
            assert r.url.params['limitBytes'] == '32768'
            return httpx.Response(200, json={'content': 'call known-private-board-key; Bearer private-unknown-token123', 'logRef': '/private/file', 'nextOffset': 123})
        return httpx.Response(200, json={'companyId': 'company', 'contextSnapshot': {'issueId': ISSUE}})
    transport(monkeypatch, handler)
    with TestClient(server.app) as c:
        r = c.get(f'/api/tasks/{ISSUE}/runs/{RUN}/log', headers=headers)
    assert r.status_code == 200
    assert 'private' not in r.text and 'logRef' not in r.text
    assert r.json()['next_offset'] == 123


@pytest.mark.parametrize('bad_hash', [False, True])
def test_artifact_download_checks_native_membership_size_and_hash(monkeypatch, bad_hash):
    raw = b'print("actual bytes")\n'
    def handler(r):
        if r.url.path == '/api/issues/' + ISSUE: return httpx.Response(200, json=ROOT)
        if r.url.path.endswith('/attachments'):
            return httpx.Response(200, json=[{'id': ARTIFACT, 'originalFilename': '../unsafe\".py', 'byteSize': len(raw),
                'sha256': '0' * 64 if bad_hash else hashlib.sha256(raw).hexdigest()}])
        return httpx.Response(200, content=raw)
    transport(monkeypatch, handler)
    with TestClient(server.app) as c:
        r = c.get(f'/api/tasks/{ISSUE}/artifacts/{ARTIFACT}', headers=headers)
    if bad_hash:
        assert r.status_code == 502 and 'integrity' in r.text
    else:
        assert r.status_code == 200 and r.content == raw
        assert r.headers['content-type'] == 'application/octet-stream'
        assert '../' not in r.headers['content-disposition']
        assert r.headers['x-content-type-options'] == 'nosniff'


def test_artifact_foreign_receipt_never_downloaded(monkeypatch):
    def handler(r):
        if r.url.path == '/api/issues/' + ISSUE: return httpx.Response(200, json=ROOT)
        if r.url.path.endswith('/attachments'): return httpx.Response(200, json=[])
        raise AssertionError('Foreign artifact fetched')
    transport(monkeypatch, handler)
    with TestClient(server.app) as c:
        assert c.get(f'/api/tasks/{ISSUE}/artifacts/{ARTIFACT}', headers=headers).status_code == 404


def test_native_retry_preserves_idempotency_and_observed_run(monkeypatch):
    sent = []
    def handler(r):
        if r.url.path == '/api/issues/' + ISSUE: return httpx.Response(200, json=ROOT)
        assert r.url.path == f'/api/issues/{ISSUE}/retry'
        sent.append(json.loads(r.content))
        return httpx.Response(202, json={'accepted': True, 'requestId': 'same-native-receipt'})
    transport(monkeypatch, handler)
    nonce = str(uuid4())
    with TestClient(server.app) as c:
        for _ in range(2):
            assert c.post(f'/api/tasks/{ISSUE}/retry', headers=headers,
                json={'request_id': nonce, 'observed_run_id': RUN}).status_code == 200
    assert sent == [{'idempotencyKey': nonce, 'observedRunId': RUN}] * 2


def test_cancel_checks_entire_native_subtree_before_mutation(monkeypatch):
    def handler(r):
        if r.url.path == '/api/issues/' + ISSUE: return httpx.Response(200, json=ROOT)
        if r.url.path.endswith('/tree-control/preview'):
            assert json.loads(r.content) == {'mode': 'cancel'}
            return httpx.Response(200, json={'issues': [{'id': ISSUE}, {'id': CHILD}]})
        if r.url.path == '/api/issues/' + CHILD: return httpx.Response(200, json={**ROOT, 'id': CHILD, 'projectId': 'foreign'})
        raise AssertionError('Cross-project tree was cancelled')
    transport(monkeypatch, handler)
    with TestClient(server.app) as c:
        assert c.post(f'/api/tasks/{ISSUE}/cancel', headers=headers, json={'reason': 'Stop tree'}).status_code == 404


def approval():
    data = monitor.catalog()
    spec = {**data['profiles']['software_development'], 'id': 'software_development', 'version': data['version'], 'model': data['model']}
    sha = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    runtime = {'heartbeat': {'enabled': False, 'maxConcurrentRuns': 1, 'wakeOnAssignment': True, 'wakeOnDemand': True}}
    return {'id': APPROVAL, 'companyId': 'company', 'type': 'hire_agent', 'status': 'pending', 'requestedByAgentId': CEO,
        'payload': {'name': 'Proposed scoped worker', 'reportsTo': CEO, 'adapterType': 'hermes_gateway', 'adapterConfig': {},
            'runtimeConfig': runtime, 'requestedConfigurationSnapshot': {'adapterType': 'hermes_gateway',
                'adapterConfig': {}, 'runtimeConfig': runtime, 'desiredSkills': []},
            'metadata': {'jarvis': {'managed': True, 'profile': spec['id'], 'profile_sha256': sha,
                'model': data['model'], 'limits': spec['limits'], 'source_issue_id': ISSUE}}}}


@pytest.mark.parametrize('decision', ['approve', 'reject'])
def test_human_decision_native_scope_and_redacted_projection(monkeypatch, decision):
    a = approval()
    def handler(r):
        if r.url.path.endswith('/issues'): return httpx.Response(200, json=[ROOT])
        if r.method == 'GET': return httpx.Response(200, json=a)
        assert r.url.path.endswith('/' + decision)
        assert json.loads(r.content) == {'decisionNote': 'Human tested reviewed profile'}
        return httpx.Response(200, json={**a, 'status': 'approved' if decision == 'approve' else 'rejected'})
    transport(monkeypatch, handler)
    with TestClient(server.app) as c:
        r = c.post(f'/api/approvals/{APPROVAL}/decision', headers=headers,
            json={'decision': decision, 'note': 'Human tested reviewed profile'})
    assert r.status_code == 200 and r.json()['status'] in ('approved', 'rejected')
    assert 'adapterConfig' not in r.text and 'metadata' not in r.text


@pytest.mark.parametrize('kind', ['changed-profile', 'other-project', 'opposite-decision', 'changed-snapshot'])
def test_hire_approval_rejects_changed_scope_or_snapshot(monkeypatch, kind):
    a = approval()
    if kind == 'changed-profile': a['payload']['metadata']['jarvis']['model'] = 'unreviewed-model'
    if kind == 'opposite-decision': a['status'] = 'rejected'
    if kind == 'changed-snapshot': a['payload']['requestedConfigurationSnapshot']['adapterConfig'] = {'apiBaseUrl': 'https://unreviewed.invalid'}
    def handler(r):
        assert r.method == 'GET', 'Unsafe approval reached native mutation'
        return httpx.Response(200, json=[{**ROOT, 'projectId': 'foreign' if kind == 'other-project' else 'project'}]
            if r.url.path.endswith('/issues') else a)
    transport(monkeypatch, handler)
    with TestClient(server.app) as c:
        r = c.post(f'/api/approvals/{APPROVAL}/decision', headers=headers,
            json={'decision': 'approve', 'note': 'Reviewed hire'})
    assert r.status_code == (404 if kind == 'other-project' else 409)


def test_dashboard_omits_credentials_preserves_real_queue_and_inference_error(monkeypatch):
    async def unavailable(): return {'available': False, 'error': 'Local inference status unavailable', 'loaded_models': []}
    monkeypatch.setattr(monitor, 'inference', unavailable)
    def handler(r):
        if r.url.path.endswith('/agents'): return httpx.Response(200, json=[{'id': AGENT, 'adapterConfig': {'apiKey': 'hidden'},
            'metadata': {'jarvis': {'profile': 'research', 'provisioned': True}}}])
        if r.url.path.endswith('/issues'): return httpx.Response(200, json=[ROOT, {**ROOT, 'id': CHILD, 'projectId': 'foreign'}])
        if r.url.path.endswith('/live-runs'): return httpx.Response(200, json=[{'id': RUN, 'issueId': ISSUE, 'status': 'queued'},
            {'id': 'foreign', 'issueId': CHILD, 'status': 'running'}])
        return httpx.Response(200, json=[])
    transport(monkeypatch, handler)
    with TestClient(server.app) as c: r = c.get('/api/monitor', headers=headers)
    data = r.json()
    assert r.status_code == 200 and data['task_counts']['blocked'] == 1
    assert data['live_runs'] == [{'id': RUN, 'status': 'queued', 'issueId': ISSUE, 'agentId': None, 'agentName': None,
        'startedAt': None, 'createdAt': None, 'livenessState': None, 'lastUsefulActionAt': None, 'nextAction': None}]
    assert not data['inference']['available'] and data['agents'][0]['capability']['tools']
    assert 'apiKey' not in r.text and 'adapterConfig' not in r.text
