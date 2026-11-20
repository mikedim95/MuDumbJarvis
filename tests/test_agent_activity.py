"""Clicked profiles use scoped published records and authenticated tool events."""
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from test_phase1 import server
from test_tasks import AGENT, CEO, CHILD, ISSUE, headers, transport
from test_monitor import sign


RUN = '66666666-6666-4666-8666-666666666666'


@pytest.fixture
def board(monkeypatch):
    root = {'id': ISSUE, 'companyId': 'company', 'projectId': 'project', 'assigneeAgentId': CEO,
            'identifier': 'JAR-84', 'title': 'Research mission', 'status': 'in_progress'}
    job = {**root, 'id': CHILD, 'parentId': ISSUE, 'assigneeAgentId': AGENT,
           'identifier': 'JAR-87', 'title': 'Compare reconnaissance tools',
           'updatedAt': '2026-11-19T10:00:00Z', 'activeRun': {'status': 'running', 'agentId': AGENT}}
    people = [{'id': CEO, 'name': 'Jarvis', 'companyId': 'company'},
              {'id': AGENT, 'name': 'Research', 'companyId': 'company', 'reportsTo': CEO}]
    data = {'issues': [root, job], 'comments': {}, 'runs': {}, 'calls': [], 'unavailable': set()}
    def handler(request):
        assert request.method == 'GET', 'Profiles must never execute or schedule work'
        path = request.url.path
        data['calls'].append(path)
        if path in data['unavailable']:
            return httpx.Response(503)
        if path.endswith('/agents'):
            return httpx.Response(200, json=people)
        if path.endswith('/routines'):
            return httpx.Response(200, json=[])
        if path == '/api/companies/company/issues':
            return httpx.Response(200, json=data['issues'])
        _, _, _, iid, *kind = path.split('/')
        if kind:
            return httpx.Response(200, json=data.get(kind[0], {}).get(iid, []))
        return httpx.Response(200, json=next(i for i in data['issues'] if i['id'] == iid))
    transport(monkeypatch, handler, workforce=True)
    return data


def profile(client, *, mission=None, agent=AGENT):
    params = {'agent_id': agent}
    if mission:
        params['mission_id'] = mission
    response = client.get('/api/agents/work', params=params, headers=headers)
    assert response.status_code == 200, response.text
    return next(a for a in response.json()['agents'] if a['id'] == agent)


def test_clicked_profile_has_current_assignment_and_substantive_last_result(board):
    board['comments'][CHILD] = [{'id': 'result', 'authorAgentId': AGENT, 'createdAt': '2026-11-19T10:01:00Z',
        'body': 'STATUS: blocked\n\nRESULT: Ten tools are documented; independent verification is pending.\n\n'
                'VERIFIED EVIDENCE: Do not dump this appendix.\n'
                '<think>Private reasoning is never activity.</think>',
        'reasoning_content': 'Another private model field.'}]
    with TestClient(server.app) as client:
        assert client.get('/api/agents/work?agent_id=' + AGENT).status_code == 401
        agent = profile(client)
    assert agent['current_work']['id'] == CHILD and agent['current_work']['state'] == 'active'
    assert agent['current_work']['mission']['id'] == ISSUE
    latest = agent['recent_activity']['latest']
    assert latest['summary'] == 'Ten tools are documented; independent verification is pending.'
    assert latest['kind'] == 'published_update' and latest['task']['identifier'] == 'JAR-87'
    assert 'private' not in json.dumps(agent).lower() and 'appendix' not in json.dumps(agent)


@pytest.mark.parametrize('valid,exit_code,summary', [
    (True, 0, 'Ran a workspace command.'), (True, 2, 'A workspace command failed (exit 2).'),
    (False, 0, None),
])
def test_only_authenticated_actual_tool_actions_are_displayed(board, monkeypatch, valid, exit_code, summary):
    key = 'fixture-proof-key'
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', key)
    proof = {'version': 3, 'kind': 'tool_event', 'company_id': 'company', 'issue_id': CHILD,
        'agent_id': AGENT, 'paperclip_run_id': RUN,
        'session_id': f'paperclip:company:company:agent:{AGENT}:issue:{CHILD}',
        'tool': 'terminal', 'success': True, 'args': {'command': 'secret command'},
        'result': {'exit_code': exit_code, 'output': 'private raw output'}}
    signed = sign(proof, key)
    if not valid:
        signed['success'] = False
    board['runs'][CHILD] = [{'runId': RUN, 'agentId': AGENT, 'status': 'running'}]
    board['comments'][CHILD] = [{'id': 'action', 'authorAgentId': AGENT,
        'createdAt': '2026-11-19T10:02:00Z', 'body': '[JARVIS TOOL EVENT]\nJARVIS_TOOL_EVENT=' + json.dumps(signed)}]
    with TestClient(server.app) as client:
        agent = profile(client)
    latest = agent['recent_activity']['latest']
    assert (latest['summary'] if latest else None) == summary
    if latest:
        assert latest['kind'] == 'tool_result'
    assert 'secret command' not in json.dumps(agent) and 'raw output' not in json.dumps(agent)


def test_recent_finished_work_is_not_hidden_by_an_old_waiting_assignment(board):
    waiting = board['issues'][1]
    waiting.pop('activeRun')
    waiting['updatedAt'] = '2026-11-18T10:00:00Z'
    finished = {**waiting, 'id': str(uuid4()), 'identifier': 'JAR-86', 'status': 'done',
                'updatedAt': '2026-11-19T12:00:00Z'}
    board['issues'].append(finished)
    board['comments'][CHILD] = [{'id': 'old', 'authorAgentId': AGENT, 'createdAt': '2026-11-18T10:00:00Z', 'body': 'Waiting for review.'}]
    board['comments'][finished['id']] = [{'id': 'new', 'authorAgentId': AGENT, 'createdAt': '2026-11-19T12:00:00Z', 'body': 'RESULT: Verified all ten entries.'}]
    with TestClient(server.app) as client:
        agent = profile(client)
    assert agent['current_work']['id'] == CHILD
    assert agent['recent_activity']['latest']['summary'] == 'Verified all ten entries.'


def test_project_isolation_precedes_history_reads_and_unselected_profiles_do_not_read_history(board):
    other = {**board['issues'][0], 'id': str(uuid4()), 'title': 'Private other mission'}
    foreign = {**board['issues'][1], 'id': str(uuid4()), 'parentId': other['id'],
               'updatedAt': '2026-11-19T15:00:00Z'}
    board['issues'].extend([other, foreign])
    board['comments'][foreign['id']] = [{'authorAgentId': AGENT, 'body': 'Other mission secret.'}]
    with TestClient(server.app) as client:
        client.get('/api/agents/work', headers=headers)
        assert not any(p.endswith(('/comments', '/runs')) for p in board['calls'])
        agent = profile(client, mission=ISSUE)
        assert foreign['id'] not in json.dumps(agent) and 'Other mission secret' not in json.dumps(agent)
        assert not any(foreign['id'] in p for p in board['calls'])
        board['calls'].clear()
        assert client.get('/api/agents/work?agent_id=' + str(uuid4()), headers=headers).status_code == 404
        assert not any(p.endswith(('/comments', '/runs')) for p in board['calls'])


def test_failed_history_read_does_not_present_stale_activity_as_current(board):
    board['unavailable'].add(f'/api/issues/{CHILD}/comments')
    with TestClient(server.app) as client:
        agent = profile(client)
    assert agent['current_work']['id'] == CHILD
    assert agent['recent_activity'] == {'latest': None, 'available': False}


@pytest.mark.parametrize('vote,progress,activity', [
    ('accepted', 'JAR-87 is waiting for the package service to install jq.', 'You approved jq for JAR-87.'),
    ('rejected', 'You declined jq for JAR-87.', 'You declined jq for JAR-87.'),
])
def test_resolved_manual_request_in_agent_and_project_views(board, vote, progress, activity):
    root, child = board['issues']
    root.update(status='blocked', unblockDescriptor={'action':'Blocked on JAR-87 — jq is missing.'})
    child.pop('activeRun')
    action = 'CEO review requested. Requested operator provisioning for sandbox package jq'
    child.update(status='blocked', unblockDescriptor={'action':action})
    board['comments'][ISSUE] = [{'authorAgentId':CEO, 'createdAt':'2026-11-18T07:00:00Z',
                                 'body':'Waiting for your decision.'}]
    review = {'id':str(uuid4()), 'issueId':ISSUE, 'createdByUserId':'board',
              'kind':'request_confirmation', 'resolverPolicy':'human_only', 'continuationPolicy':'none',
              'idempotencyKey':f'jarvis-package-review:{CHILD}:{AGENT}:jq', 'payload':{'prompt':'Provide jq?'},
              'status':vote, 'resolvedByUserId':'owner', 'resolvedAt':'2026-11-19T07:00:00Z'}
    board['interactions'] = {ISSUE:[review]}
    with TestClient(server.app) as client:
        for mission in (None, ISSUE):
            ceo = profile(client, mission=mission, agent=CEO)
            assert ceo['questions'] == []
            assert ceo['current_work']['reason'] == progress
            assert ceo['current_work']['next_actor'] == ('package_service' if vote == 'accepted' else None)
            latest = ceo['recent_activity']['latest']
            assert (latest['summary'], latest['kind'], latest['at']) == (activity, 'owner_decision', review['resolvedAt'])
        assert profile(client, mission=ISSUE)['current_work']['reason'] == progress
        project = client.get('/api/tasks/' + ISSUE, headers=headers).json()
        assert project['brief']['progress'] == project['children'][0]['brief']['progress'] == progress
        assert project['status'] == project['children'][0]['status'] == 'blocked'
        if vote == 'accepted':
            from deploy import approved_packages as apt
            import base64
            import hashlib
            data = b'jq-1.7\n'
            scope = apt.receipts.binding('company', 'project', ISSUE, CHILD, AGENT, 'jq', review['id'])
            doc = {'key':apt.receipts.key(review['id']), 'issueId':CHILD, 'companyId':'company', 'updatedByUserId':'operator',
                   'body':json.dumps({'scope':scope,'status':'ready','command':'./.jarvis-bin/jq','version':'1.7',
                       'usage':apt.receipts.usage('jq'), 'stdout_base64':base64.b64encode(data).decode(),
                       'output_sha256':hashlib.sha256(data).hexdigest(), 'image':'sha256:'+'1'*64,
                       'verified_at':'2026-11-19T09:00:00+00:00'})}
            board['documents'] = {CHILD:[doc]}
            agent = profile(client, mission=ISSUE, agent=CEO)
            assert agent['current_work']['reason'] == 'jq 1.7 is ready for JAR-87.'
            assert agent['recent_activity']['latest']['kind'] == 'package_verification'
            done = client.get('/api/tasks/' + ISSUE, headers=headers).json()
            assert done['children'][0]['brief']['progress'] == done['brief']['progress'] == agent['current_work']['reason']
            doc['updatedByAgentId'] = AGENT
            assert profile(client, agent=CEO)['current_work']['reason'] == progress
        board['comments'][ISSUE].append({'authorAgentId':CEO, 'createdAt':'2026-11-20T07:00:00Z',
                                         'body':'The operator is reviewing the request.'})
        assert profile(client, agent=CEO)['recent_activity']['latest']['kind'] == 'published_update'
        child['unblockDescriptor']['action'] = 'Disk full.'
        assert profile(client, agent=AGENT)['current_work']['reason'] == 'Disk full.'
        assert profile(client, agent=CEO)['current_work']['reason'] != progress
        child['unblockDescriptor']['action'] = action
        review.pop('resolvedByUserId')
        assert profile(client, agent=CEO)['current_work']['reason'] != progress
        assert not profile(client, agent=CEO)['package_decisions']


def test_read_budget_is_bounded_for_long_histories_and_preserves_the_current_assignment(board):
    for index in range(8):
        board['issues'].append({**board['issues'][1], 'id': str(uuid4()), 'status': 'done',
                                'updatedAt': f'2026-11-19T12:0{index}:00Z'})
    with TestClient(server.app) as client:
        agent = profile(client)
    reads = [p for p in board['calls'] if p.endswith(('/comments', '/runs'))]
    assert len(reads) == 8 and f'/api/issues/{CHILD}/comments' in reads
    assert agent['current_work']['id'] == CHILD
