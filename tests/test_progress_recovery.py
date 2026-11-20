"""An unfinished mission needs a live run or an explicit owner intervention."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_phase1 import server
from test_employee_guard import employee
import agent_work
import blocker_delivery

ROOT = 'mission'
CHILD = 'worker-task'


def native():
    root = {'id': ROOT, 'companyId': 'co', 'projectId': 'project', 'assigneeAgentId': 'ceo',
            'status': 'blocked', 'updatedAt': '2026-01-01T00:00:00Z'}
    child = {**root, 'id': CHILD, 'parentId': ROOT, 'assigneeAgentId': 'worker'}
    state = SimpleNamespace(records={ROOT: root, CHILD: child}, questions=[], approvals=[], holds=[], runs=[], comments=[], calls=[])

    async def request(method, path, body=None):
        state.calls.append((method, path, body))
        if method=='GET' and path=='issues/'+ROOT:
            return deepcopy(state.records[ROOT])
        if path.endswith('/interactions'):
            return state.questions
        if path.endswith('/approvals'):
            return state.approvals
        if '/tree-holds?' in path:
            return state.holds
        if path.endswith('/runs'):
            return state.runs
        if path.endswith('/comments'):
            if method=='POST':state.comments.append({'body':body['body'],'authorUserId':'owner','createdAt':'2026-03-01T00:00:00Z'})
            return state.comments
        assert method == 'POST' and path == 'agents/ceo/wakeup'
        return {'status': 'queued'}

    state.client = SimpleNamespace(company='co', ceo='ceo', request=request)
    return state


def test_answered_question_resumes_ceo_with_durable_idempotency(monkeypatch):
    state = native()
    monkeypatch.setattr(agent_work, 'issue_index', AsyncMock(side_effect=lambda _: deepcopy(state.records)))
    for _ in range(2):
        asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    posts = [body for method, path, body in state.calls if method == 'POST' and path=='agents/ceo/wakeup']
    assert len(posts) == 1
    assert posts[0]['payload']['issueId'] == ROOT
    assert posts[0]['idempotencyKey'].startswith('jarvis-progress:')
    state.records[ROOT]['updatedAt'] = '2026-02-01T00:00:00Z'
    asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    assert len([1 for method,path,_ in state.calls if method=='POST' and path=='agents/ceo/wakeup'])==1
    assert len(state.comments)==1 and state.comments[0]['body'].startswith(blocker_delivery.PROGRESS)


def test_real_owner_input_allows_another_progress_review_without_self_wakeup_loop(monkeypatch):
    state=native();monkeypatch.setattr(agent_work,'issue_index',AsyncMock(side_effect=lambda _:deepcopy(state.records)))
    asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    state.comments.append({'authorUserId':'owner','createdAt':'2026-03-02T00:00:00Z','body':'Please apply my updated scope.'})
    asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    posts=[body for method,path,body in state.calls if method=='POST' and path=='agents/ceo/wakeup']
    assert len(posts)==2 and posts[0]['idempotencyKey']!=posts[1]['idempotencyKey']


def test_failed_native_execution_is_never_repeated_by_progress_polling(monkeypatch):
    state=native();state.records[ROOT]['executionBlocker']={'canRetry':True,'runId':'failed-run'}
    monkeypatch.setattr(agent_work,'issue_index',AsyncMock(return_value=state.records))
    asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    assert not any(method=='POST' for method,_,_ in state.calls)


@pytest.mark.parametrize('condition', ['running', 'queued', 'question', 'approval', 'hold', 'retry', 'archived', 'done'])
def test_progress_checks_respect_real_activity_and_owner_waits(monkeypatch, condition):
    state = native()
    if condition in ('running', 'queued'):
        state.records[CHILD]['activeRun'] = {'status': condition}
    elif condition == 'question':
        state.questions = [{'id':'q', 'kind':'ask_user_questions', 'issueId':ROOT, 'createdByAgentId':'ceo',
            'status':'pending', 'idempotencyKey':'jarvis-blocker:child', 'payload':{'questionSet':{'questions':[
                {'id':'child-worker-task', 'answerMode':'text', 'prompt':'Which source should the worker use?'}]}}}]
    elif condition == 'approval':
        state.approvals = [{'status':'pending'}]
    elif condition == 'hold':
        state.holds = [{'status':'active'}]
    elif condition == 'retry':
        state.runs = [{'status':'scheduled_retry'}]
    elif condition == 'archived':
        state.records[ROOT]['hiddenAt'] = '2026-02-01T00:00:00Z'
    else:
        state.records[ROOT]['status'] = 'done'
    monkeypatch.setattr(agent_work, 'issue_index', AsyncMock(return_value=state.records))
    asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    assert not any(method == 'POST' for method, _, _ in state.calls)


def test_a_dependency_without_a_live_execution_is_a_blocker():
    row = {'status':'blocked', 'blockerAttention':{
        'sampleBlockerIdentifier':'JAR-76', 'blockingTreeLive':False}}
    assert agent_work.issue_condition(row)[0] == 'blocked'
    row['blockerAttention']['blockingTreeLive'] = True
    assert agent_work.issue_condition(row)[0] == 'waiting'
    row['unblockDescriptor'] = {'action':'Waiting for your decision. Which source should we use?'}
    assert agent_work.issue_condition(row)[0] == 'blocked'


@pytest.mark.parametrize('label', ['Blocked on retrieval', 'Blocked by retrieval limits'])
def test_explicit_worker_blocker_cannot_be_reported_as_done(employee, monkeypatch, label):
    turn = {'session':'issue-session', 'issue':'issue', 'run':'run', 'company':'company',
            'agent':'22222222-2222-4222-8222-222222222222', 'needs_inventory':False,
            'inventory_verified':False, 'needs_artifact':True, 'needs_report':True,
            'response':label + ': primary evidence is unavailable.',
            'artifacts':{'receipt':{'id':'receipt', 'originalFilename':'report.txt'}},
            'employee_execution':[{'tool':'research_sources', 'tool_call_id':'read', 'success':True,
                                   'args':{}, 'result':{'source':'primary'}}]}
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', 'test-signing-key')
    monkeypatch.setitem(employee.reporting._turns, ('issue-session', 'turn'), turn)
    calls = []
    monkeypatch.setattr(employee.reporting, 'api', lambda *args: calls.append(args))
    employee.reporting.finish(session_id='issue-session', turn_id='turn', completed=True)
    payload = calls[-1][2]
    proof = json.loads(payload['comment'].split('JARVIS_EXECUTION_EVIDENCE=')[1])
    assert payload['status'] == proof['task_status'] == 'blocked'


@pytest.mark.parametrize('review_record', ['ceo_report', 'skipped_question'])
def test_confirmed_blocker_stays_quiet_until_new_input(monkeypatch, review_record):
    state = native()
    monkeypatch.setattr(agent_work, 'issue_index', AsyncMock(side_effect=lambda _: deepcopy(state.records)))
    action = 'Blocked on JAR-101 — The named software is unavailable.'
    state.records[ROOT]['unblockDescriptor'] = {'action': action}
    reviewed = '2026-03-01T12:00:00.000Z'
    if review_record == 'ceo_report':
        state.comments.append({'authorAgentId':'ceo','body':action,'createdAt':reviewed})
    else:
        state.questions.append({'id':'prior','status':'cancelled','resolvedByUserId':'owner',
            'createdByAgentId':'ceo','result':{'outcome':'skipped','reason':action},'resolvedAt':reviewed})
    asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    assert not any(method == 'POST' for method, _, _ in state.calls)
    if review_record == 'ceo_report':
        state.records[CHILD]['updatedAt'] = '2026-03-02T00:00:00Z'
    else:
        state.comments.append({'authorUserId':'owner','body':'Use the new project scope.','createdAt':'2026-03-02T00:00:00Z'})
    asyncio.run(blocker_delivery.continue_stalled_projects(state.client))
    assert sum(path == 'agents/ceo/wakeup' and method == 'POST' for method,path,_ in state.calls) == 1
