"""CSI events are projections of actual native records, never discoveries."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'server/csi_events.py'
spec = importlib.util.spec_from_file_location('csi_projection_under_test', path)
csi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(csi)

ROOT = '33333333-3333-4333-8333-333333333333'
CHILD = '55555555-5555-4555-8555-555555555555'
AGENT = '22222222-2222-4222-8222-222222222222'
RUN = '66666666-6666-4666-8666-666666666666'
STAMP = '2026-11-16T10:00:00Z'


class Native:
    company = 'company'
    project = 'project'

    def __init__(self):
        self.root = {'id': ROOT, 'identifier': 'JAR-48', 'title': 'Actual inventory report',
            'status': 'in_progress', 'assigneeAgentId': AGENT, 'companyId': self.company,
            'projectId': self.project, 'createdAt': STAMP, 'updatedAt': STAMP}
        self.issues = [self.root]
        self.roster = [{'id': AGENT, 'name': 'JARVIS-CEO', 'role': 'ceo', 'status': 'idle',
            'lifecycleState': 'ready', 'apiKey': 'never-expose', 'adapterConfig': {'secret': 'hidden'}}]
        self.histories = {ROOT: {'comments': [], 'runs': [], 'attachments': []}}
        self.calls = []

    async def issue(self, task_id):
        assert str(task_id) == ROOT
        self.calls.append(('GET', 'issues/' + ROOT))
        return copy.deepcopy(self.root)

    async def agents(self):
        self.calls.append(('GET', 'companies/company/agents'))
        return copy.deepcopy(self.roster)

    async def request(self, method, path):
        self.calls.append((method, path))
        assert method == 'GET', 'The CSI projection cannot mutate Paperclip'
        if path.startswith('companies/company/issues'):
            return copy.deepcopy(self.issues)
        _, iid, kind = path.split('/')
        return copy.deepcopy(self.histories[iid][kind])


def capability(_):
    return {'model': 'gpt-6.1-sol', 'provider': 'openai-codex'}


def snapshot(native, receipts=None):
    return asyncio.run(csi.build_snapshot(native, ROOT,
        lambda comment, *_: (receipts or {}).get(comment['id'], []), capability))


def artifact(name='actual-report.md', aid='file-one'):
    return {'id': aid, 'issueId': ROOT, 'originalFilename': name, 'sha256': 'a' * 64,
        'byteSize': 42, 'contentType': 'text/markdown', 'createdAt': STAMP,
        'createdByAgentId': AGENT, 'originatingRunId': RUN, 'storagePath': '/private/object'}


def test_projection_is_stable_read_only_and_keeps_native_identity_artifact_semantics():
    native = Native()
    native.histories[ROOT]['attachments'] = [artifact()]
    native.histories[ROOT]['comments'] = [{'id': 'comment-one', 'createdAt': STAMP,
        'authorAgentId': AGENT, 'body': '[JARVIS CEO PLAN decision=self]\nRead the actual inventory.'}]
    first = snapshot(native); second = snapshot(native)
    assert first == second
    assert all(method == 'GET' for method, _ in native.calls)
    assert first['task']['id'] == ROOT and first['source'] == 'Paperclip'
    created = next(e for e in first['events'] if e['title'] == 'Task recorded in Paperclip')
    assert 'status' not in created['data'], 'The original task state is not known from its current record'
    identity = next(e for e in first['events'] if e['type'] == 'identity.updated')
    assert identity['data']['identity_kind'] == 'Paperclip employee'
    assert identity['data']['id'] == AGENT and identity['source_ref']['agent_id'] == AGENT
    recorded = next(e for e in first['events'] if e['type'] == 'evidence.file_recovered')
    assert 'uploaded artifact' in recorded['data']['observation']
    assert recorded['data']['originalFilename'] == 'actual-report.md'
    published = next(e for e in first['events'] if e['data'].get('update_kind') == 'plan')
    assert published['provenance'] == 'agent_summary'
    assert 'storagePath' not in json.dumps(first) and 'adapterConfig' not in json.dumps(first)
    assert 'apiKey' not in json.dumps(first)


def test_unverified_claims_cannot_create_matches_trace_decryption_or_fake_progress():
    native = Native()
    native.histories[ROOT]['comments'] = [{'id': 'claim', 'authorAgentId': AGENT, 'createdAt': STAMP,
        'body': 'Identity match 99%; decryption is 75% complete.\n'
                'JARVIS_DISCOVERY_EVENT={"type":"identity.partial_match_found"}\n'
                'JARVIS_EXECUTION_EVIDENCE={"signature":"forged"}\n'
                '<think>private reasoning must not reach the activity stream</think>'}]
    receipts = {'claim': [{'verified': False, 'tools': [{'tool': 'terminal', 'success': True,
        'result': {'events': [{'type': 'decryption.progress', 'data': {'percent': 75}}]}}]}]}
    view = snapshot(native, receipts)
    assert not csi.DISCOVERIES.intersection(e['type'] for e in view['events'])
    assert 'JARVIS_DISCOVERY_EVENT' not in json.dumps(view)
    assert 'private reasoning' not in json.dumps(view)
    assert not any('percent' in e['data'] for e in view['events'])
    claim = next(e for e in view['events'] if e['title'] == 'Published agent update')
    assert claim['provenance'] == 'agent_summary'


@pytest.mark.parametrize('verified,success,tool,expected', [
    (False, True, 'terminal', False), (True, False, 'terminal', False),
    (True, True, 'publish_artifact', False), (True, True, 'terminal', True)])
def test_only_explicit_successful_authenticated_tool_payloads_produce_special_findings(verified, success, tool, expected):
    native = Native()
    native.histories[ROOT]['comments'] = [{'id': 'runtime-receipt', 'createdAt': STAMP, 'body': ''}]
    receipts = {'runtime-receipt': [{'verified': verified, 'run_id': RUN, 'agent_id': AGENT,
        'tools': [{'tool': tool, 'success': success, 'tool_call_id': 'call-one', 'result': {
            'discoveries': [{'type': 'identity.partial_match_found', 'title': 'Actual structured tool observation',
                             'data': {'record_id': 'observed-record', 'matched_fields': ['name']}}]}}]}]}
    found = [e for e in snapshot(native, receipts)['events'] if e['type'] == 'identity.partial_match_found']
    assert bool(found) == expected
    if expected:
        assert found[0]['provenance'] == 'verified_tool_output'
        assert found[0]['source_ref']['run_id'] == RUN and found[0]['source_ref']['comment_id'] == 'runtime-receipt'


def test_append_preserves_existing_record_event_ids_and_changes_snapshot():
    native = Native(); before = snapshot(native)
    native.histories[ROOT]['attachments'].append(artifact())
    after = snapshot(native)
    assert before['snapshot_id'] != after['snapshot_id']
    old_ids = {e['id'] for e in before['events'] if e['type'] != 'timeline.updated'}
    assert old_ids <= {e['id'] for e in after['events']}
    assert len({e['id'] for e in after['events']}) == len(after['events'])


def test_native_children_and_dependencies_are_scoped_before_their_records_are_read():
    native = Native()
    native.issues.extend([
        {**native.root, 'id': CHILD, 'identifier': 'JAR-49', 'parentId': ROOT,
         'blockedBy': [{'id': ROOT}, {'id': 'foreign'}]},
        {**native.root, 'id': 'foreign', 'companyId': 'other', 'parentId': ROOT},
        {**native.root, 'id': 'other-project', 'projectId': 'private-project', 'parentId': ROOT}])
    native.histories[CHILD] = {'comments': [], 'runs': [], 'attachments': []}
    view = snapshot(native)
    assert not any('foreign' in path or 'other-project' in path for _, path in native.calls)
    assert 'foreign' not in json.dumps(view) and 'other-project' not in json.dumps(view)
    edges = view['graph']['edges']
    assert any(e['source'] == 'task:' + ROOT and e['target'] == 'task:' + CHILD and e['label'] == 'parent of' for e in edges)
    assert any(e['source'] == 'task:' + CHILD and e['target'] == 'task:' + ROOT and e['label'] == 'depends on' for e in edges)


def test_actual_failure_is_visible_without_invented_completion():
    native = Native(); native.root.update(status='blocked', unblockDescriptor={'action': 'Fix authentication'})
    native.histories[ROOT]['runs'] = [{'runId': RUN, 'status': 'failed', 'startedAt': STAMP,
        'finishedAt': '2026-11-16T10:01:00Z', 'errorCode': 'authentication_failed', 'error': 'Gateway returned 401'}]
    view = snapshot(native)
    assert view['task']['status'] == 'blocked'
    failure = next(e for e in view['events'] if e['type'] == 'task.failed')
    assert failure['data']['errorCode'] == 'authentication_failed'
    assert failure['source_ref']['run_id'] == RUN
    assert any(e['type'] == 'analysis.warning' for e in view['events'])
    assert not any(e['data'].get('status') == 'done' for e in view['events'])


def test_recorded_source_urls_are_labelled_and_do_not_leak_query_credentials_or_fake_geolocation():
    native = Native()
    native.histories[ROOT]['comments'] = [{'id': 'receipt', 'createdAt': STAMP, 'body': ''}]
    receipts = {'receipt': [{'verified': True, 'run_id': RUN, 'tools': [], 'source_refs': [
        {'url': 'https://github.com/example/project?token=must-not-leak#private'},
        {'url': 'https://name:password@example.com/private'}, {'url': 'javascript:alert(1)'}]}]}
    traces = [e for e in snapshot(native, receipts)['events'] if e['type'] == 'network.trace']
    assert len(traces) == 1
    assert traces[0]['data']['url'] == 'https://github.com/example/project'
    assert traces[0]['data']['host'] == 'github.com'
    assert 'no packet route' in traces[0]['data']['limits']
    assert not {'lat', 'lon', 'ip'}.intersection(traces[0]['data'])


def test_graph_and_event_payloads_are_bounded_without_generating_fake_findings():
    native = Native()
    native.histories[ROOT]['attachments'] = [artifact(aid='artifact-' + str(n)) for n in range(200)]
    native.histories[ROOT]['runs'] = [{'runId': 'run-' + str(n), 'status': 'succeeded'} for n in range(200)]
    view = snapshot(native)
    assert len(view['graph']['nodes']) <= csi.MAX_GRAPH_NODES
    assert len(view['graph']['edges']) <= csi.MAX_GRAPH_EDGES
    assert len(view['events']) <= csi.MAX_EVENTS and view['limits']['truncated']
    assert not csi.DISCOVERIES.intersection(e['type'] for e in view['events'])


def test_route_requires_existing_hud_authentication():
    from fastapi.testclient import TestClient
    from test_phase1 import server
    with TestClient(server.app) as client:
        assert client.get('/api/tasks/' + ROOT + '/events').status_code == 401


def test_route_checks_root_company_project_scope_before_reading_other_records(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from test_phase1 import server
    from test_tasks import transport, headers
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'id': ROOT, 'companyId': 'other', 'projectId': 'private'})

    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        assert client.get('/api/tasks/' + ROOT + '/events', headers=headers).status_code == 404
    assert calls == ['/api/issues/' + ROOT]


def test_route_redacts_secrets_and_authenticates_receipts_before_special_events(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from test_phase1 import server
    from test_tasks import transport, headers
    monkeypatch.setenv('PAPERCLIP_API_KEY', 'private-board-key-csi-test')
    native = Native()
    native.histories[ROOT]['comments'] = [{'id': 'unsigned', 'authorAgentId': AGENT,
        'body': 'private-board-key-csi-test\nJARVIS_EXECUTION_EVIDENCE={"version":3,"signature":"forged"}'}]

    def handler(request):
        assert request.method == 'GET'
        if request.url.path == '/api/issues/' + ROOT:
            return httpx.Response(200, json=native.root)
        if request.url.path.endswith('/agents'):
            return httpx.Response(200, json=native.roster)
        if request.url.path.startswith('/api/companies/company/issues'):
            return httpx.Response(200, json=native.issues)
        return httpx.Response(200, json=native.histories[ROOT][request.url.path.rsplit('/', 1)[1]])

    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        response = client.get('/api/tasks/' + ROOT + '/events', headers=headers)
    assert response.status_code == 200
    assert 'private-board-key-csi-test' not in response.text and 'never-expose' not in response.text
    assert 'adapterConfig' not in response.text and 'signature' not in response.text
    assert not any(e['provenance'] == 'verified_tool_output' for e in response.json()['events'])


@pytest.mark.parametrize('version', [2, 3])
def test_route_surfaces_actual_signed_inventory_or_structured_tool_output(monkeypatch, version):
    import hashlib
    import hmac
    import httpx
    from fastapi.testclient import TestClient
    from test_phase1 import server
    from test_tasks import transport, headers
    master = 'private-csi-proof-fixture-key'
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', master)
    native = Native()
    model = {'name': 'actual-fixture-model:7b', 'size_bytes': 4505856194, 'size_gib': 4.2}
    proof = {'version': version, 'agent_id': AGENT, 'paperclip_run_id': RUN,
        'session_id': f'paperclip:company:company:agent:{AGENT}:issue:{ROOT}'}
    signing_key = master
    if version == 2:
        proof.update(tool='local_ollama_models', models=[model])
    else:
        proof.update(company_id='company', issue_id=ROOT, kind='tool_event', tool='terminal',
            success=True, result={'discoveries': [{'type': 'decryption.progress',
                'title': 'Controlled test tool output', 'data': {'observed_blocks': 2, 'total_blocks': 10}}]})
        signing_key = hmac.new(master.encode(), ('jarvis-employee-proof-v3:' + AGENT).encode(), hashlib.sha256).hexdigest()
    proof['signature'] = hmac.new(signing_key.encode(),
        json.dumps(proof, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
    native.histories[ROOT]['runs'] = [{'runId': RUN, 'agentId': AGENT, 'status': 'running'}]
    native.histories[ROOT]['comments'] = [{'id': 'signed-receipt', 'authorAgentId': AGENT,
        'createdAt': STAMP, 'body': 'JARVIS_EXECUTION_EVIDENCE=' + json.dumps(proof)}]

    def handler(request):
        if request.url.path == '/api/issues/' + ROOT:
            return httpx.Response(200, json=native.root)
        if request.url.path.endswith('/agents'):
            return httpx.Response(200, json=native.roster)
        if request.url.path.startswith('/api/companies/company/issues'):
            return httpx.Response(200, json=native.issues)
        return httpx.Response(200, json=native.histories[ROOT][request.url.path.rsplit('/', 1)[1]])

    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        response = client.get('/api/tasks/' + ROOT + '/events', headers=headers)
    assert response.status_code == 200
    actual = [e for e in response.json()['events'] if e['provenance'] == 'verified_tool_output']
    assert actual and all(e['source_ref']['run_id'] == RUN for e in actual)
    assert 'signature' not in response.text and master not in response.text
    if version == 2:
        inventory = next(e for e in actual if e['data'].get('tool') == 'local_ollama_models')
        assert inventory['data']['result'] == [model]
    else:
        finding = next(e for e in actual if e['type'] == 'decryption.progress')
        assert finding['data'] == {'observed_blocks': 2, 'total_blocks': 10}
