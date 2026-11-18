import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_ceo_tools import plugin, child_with_evidence, COMPANY, ROOT, CHILD, PROJECT, CEO, WORKER
from test_ceo_conversation_api import server, task_api, HEADERS
import blocker_delivery


def form(owner, root, child, question='Which approved source can we use?'):
    return {'id': str(uuid4()), 'issueId': root, 'createdByAgentId': owner, 'kind': 'ask_user_questions',
            'idempotencyKey': 'jarvis-blocker:' + child, 'status': 'pending',
            'payload': {'questionSet': {'questions': [{'id': 'child-' + child, 'answerMode': 'text', 'prompt': question}]}}}


def test_child_reports_once_to_its_own_supervisor(plugin):
    child = {'id': CHILD, 'identifier': 'JAR-101', 'parentId': ROOT}
    turn = {'reports_to': CEO, 'agent': WORKER, 'run': 'native-run', 'company': COMPANY, 'project': PROJECT}
    parent = {'assigneeAgentId': CEO, 'companyId': COMPANY, 'projectId': PROJECT, 'status': 'blocked'}
    comments = []
    def api(method, path, body=None, run_id=None):
        if path == '/issues/' + ROOT:
            return parent
        assert path == '/issues/' + ROOT + '/comments'
        if method == 'GET':
            return comments
        assert run_id == 'native-run'
        comments.append({**body, 'authorAgentId': WORKER})
    review = plugin.tools.blocker_review
    for _ in range(2):
        review.report(api, turn, child, 'The source was unavailable.')
    assert len(comments) == 1 and 'source was unavailable' in comments[0]['body']
    parent['projectId'] = 'foreign'
    review.report(api, {**turn, 'run': 'new-run'}, child, 'Do not deliver')
    assert len(comments) == 1


def test_blocked_prose_creates_one_real_question_and_preserves_same_child(plugin, monkeypatch):
    child_with_evidence(plugin, status='blocked')
    child = plugin.children[0]
    child['description'] = '[JARVIS REQUEST initial]\nVerify the public source.'
    child['unblockDescriptor'] = {'action': 'The publication is unavailable.'}
    native = []
    real_api = plugin.reporting.api
    def api(method, path, body=None, run_id=None):
        if path.endswith('/interactions'):
            assert path == '/issues/' + ROOT + '/interactions'
            if method == 'POST':
                assert body['continuationPolicy'] == 'wake_assignee' and body['resolverPolicy'] == 'human_only'
                assert body['addresseeUserId'] == 'owner' and run_id == 'ceo-run'
                native.append({**body, 'id': str(uuid4()), 'issueId': ROOT, 'createdByAgentId': CEO, 'status': 'pending'})
                return native[-1]
            return native
        return real_api(method, path, body, run_id)
    plugin.issue['responsibleUserId'] = 'owner'
    monkeypatch.setattr(plugin.reporting, 'api', api)
    plugin.turn.update(inference_configuration={'version': 3}, plan_decision='delegate',
        response='The publication is unavailable. Which public source should the worker use?')
    plugin.tools.prepare_turn_context(plugin.turn, issue=plugin.issue, comments=[])
    plugin.tools.finalize(plugin.turn, completed=True)
    assert len(native) == 1
    assert plugin.calls[-1][2]['unblockDescriptor']['action'] == 'Waiting for your decision. Which public source should the worker use?'
    plugin.tools.finalize(plugin.turn, completed=True)
    assert len(native) == 1
    native[0].update(status='answered', resolvedByUserId='owner', result={'answers': [
        {'questionId': 'child-' + CHILD, 'optionIds': [], 'otherText': 'Use the public archive.'}]})
    plugin.turn.pop('owner_question')
    ctx = plugin.tools.prepare_turn_context(plugin.turn, issue=plugin.issue, comments=[])
    assert 'Use the public archive.' in ctx and plugin.tools.children(plugin.turn)[0]['id'] == CHILD


def test_hud_answer_retries_without_opening_new_work(monkeypatch):
    decision = form(CEO, ROOT, CHILD)
    issue = {'id': ROOT, 'companyId': COMPANY, 'projectId': PROJECT, 'assigneeAgentId': CEO, 'status': 'blocked'}
    posts = []
    async def request(self, method, path, body=None):
        if method == 'POST':
            assert path.endswith('/' + decision['id'] + '/respond')
            posts.append(body)
            decision.update(status='answered', resolvedByUserId='owner', result=body)
            return decision
        if path.endswith('/interactions'):
            return [decision]
        if '/tree-holds' in path:
            return []
        assert path == 'issues/' + ROOT
        return issue
    def init(p):
        p.company,p.project,p.ceo,p.workforce,p.http = COMPANY,PROJECT,CEO,True,AsyncMock()
    monkeypatch.setattr(task_api.Paperclip, '__init__', init)
    monkeypatch.setattr(task_api.Paperclip, 'request', request)
    data = {'input':'Use the public archive.', 'request_id':str(uuid4()), 'interaction_id':decision['id']}
    with TestClient(server.app) as client:
        for _ in range(2):
            r = client.post('/api/tasks/'+ROOT+'/messages', json=data, headers=HEADERS)
            assert r.status_code == 200 and r.json()['interaction_id'] == decision['id']
        assert client.post('/api/tasks/'+ROOT+'/messages', json={**data,'input':'Different reply'}, headers=HEADERS).status_code == 409
        assert client.post('/api/tasks/'+ROOT+'/messages', json={**data,'interaction_id':str(uuid4())}, headers=HEADERS).status_code == 409
    assert len(posts) == 1 and posts[0]['answers'][0]['questionId'] == 'child-' + CHILD


def test_interrupted_reporting_recovers_from_native_worker_record():
    child = {'id': CHILD, 'parentId': ROOT, 'status': 'blocked', 'assigneeAgentId': WORKER,
             'identifier':'JAR-101', 'updatedAt':'2026-01-01T00:00:00Z','projectId':PROJECT,'companyId':COMPANY}
    parent = {'id':ROOT,'assigneeAgentId':CEO,'status':'blocked','projectId':PROJECT,'companyId':COMPANY}
    posted = []
    async def request(method, path, body=None):
        if path.endswith('/tree-holds?status=active'):
            return []
        if path == 'issues/' + CHILD + '/comments':
            return [{'authorAgentId': WORKER, 'createdByRunId':'run-7','body':'Blocked.\nJARVIS_EXECUTION_EVIDENCE={}' }]
        assert path == 'issues/' + ROOT + '/comments'
        if method == 'POST':
            posted.append(body)
        return posted
    p=SimpleNamespace(ceo=CEO,issue=AsyncMock(side_effect=lambda key: parent if key==ROOT else child),request=request)
    assert asyncio.run(blocker_delivery.forward(p,child,'The test failed.'))
    assert asyncio.run(blocker_delivery.forward(p,child,'The test failed.'))
    assert len(posted) == 1 and 'run-7' in posted[0]['body']


def test_ceo_repairs_same_assignment_then_escalates_repeated_cause(plugin, monkeypatch):
    child_with_evidence(plugin, status='blocked')
    original = plugin.children[0]
    original.update(description='[JARVIS REQUEST initial]\nCheck the document.', unblockDescriptor={'action':'Missing source.'})
    plugin.turn.update(inference_configuration={'version':3}, plan_decision='delegate')
    api = plugin.reporting.api
    def patch(method, path, body=None, run_id=None):
        if path.endswith('/tree-holds?status=active'):
            return []
        if method == 'PATCH' and path.endswith(CHILD):
            plugin.child_comments[CHILD].append({'authorAgentId':CEO,'body':body['comment']})
        return api(method,path,body,run_id)
    monkeypatch.setattr(plugin.reporting, 'api', patch)
    args={'action':'request_correction','child_id':CHILD,'text':'Use the publisher archive to verify the document and return the citation.'}
    plugin.tools.manage(args)
    assert original['status']=='todo' and original['assigneeAgentId']==WORKER and original['unblockDescriptor'] is None
    original.update(status='blocked', unblockDescriptor={'action':'Missing source.'})
    with pytest.raises(ValueError,match='same correction cycle'):
        plugin.tools.manage({**args,'text':'Retry that archive lookup and submit the result to the CEO.'})
    assert len(plugin.children)==1


def test_worker_wakeup_restores_original_request_without_replacing_newer_chat(plugin):
    review=plugin.tools.blocker_review
    latest={'id':str(uuid4()),'body':'New question'}
    child={'id':CHILD,'identifier':'JAR-101','companyId':COMPANY,'projectId':PROJECT,'parentId':ROOT,
           'assigneeAgentId':WORKER,'description':'[JARVIS REQUEST initial]\nOriginal assignment'}
    report={'id':'native-comment','authorAgentId':WORKER,'body':'[JARVIS WORKER BLOCKER run]\nJAR-101 needs CEO review.'}
    native={'contextSnapshot':{'issueId':ROOT,'wakeCommentId':'native-comment'}}
    assert review.wake_request(lambda *_: native,plugin.turn,[report],[latest],[child]) is None
    native['contextSnapshot']['wakeCommentId']='different-comment'
    assert review.wake_request(lambda *_: native,plugin.turn,[report],[latest],[child])==latest
