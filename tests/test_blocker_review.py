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


@pytest.mark.parametrize('vote,endpoint,status',[
    ('Yes','accept','accepted'),('No','reject','rejected'),('Approve','accept','accepted'),('Decline','reject','rejected')])
def test_legacy_worker_report_reaches_ceo_and_owner_decision_is_idempotent(monkeypatch,vote,endpoint,status):
    reason = 'Operator must provision compatible jq and dependencies inside this sandbox.'
    child = {'id': CHILD,'parentId': ROOT,'assigneeAgentId': WORKER,'companyId':COMPANY,'projectId':PROJECT,
             'identifier':'JAR-101','status':'blocked','updatedAt':'2026-11-19T00:00:00Z',
             'unblockDescriptor':{'action':'CEO review requested. Worker reports incomplete work: blocked. ' + reason}}
    root = {'id':ROOT,'assigneeAgentId':CEO,'companyId':COMPANY,'projectId':PROJECT,'status':'blocked'}
    rows, votes, notes = [], [], {}
    async def request(self, method, path, body=None):
        if '/tree-holds?' in path: return []
        if path == 'issues/'+CHILD+'/comments': return [
            {'authorAgentId':WORKER,'createdByRunId':'worker-run','body':reason+'\nJARVIS_EXECUTION_EVIDENCE={}'}]
        if path == 'issues/'+ROOT+'/interactions':
            if method == 'GET': return rows
            assert body['resolverPolicy']=='human_only' and body['continuationPolicy']=='none'
            row = {**body, 'id':str(uuid4()),'issueId':ROOT,'createdByUserId':'board','status':'pending'}
            rows.append(row)
            return row
        if path == 'issues/'+ROOT: return root
        if path == 'issues/'+CHILD: return child
        if path == 'issues/'+ROOT+'/comments':
            if method=='GET': return list(notes.values())
            assert body['resume'] is False and body['reopen'] is False
            return notes.setdefault(body['clientRequestId'], {**body,'issueId':ROOT,'id':str(uuid4()),'authorUserId':'owner'})
        assert path == 'issues/'+ROOT+'/interactions/'+rows[0]['id']+'/'+endpoint
        votes.append(body)
        rows[0].update(status=status,resolvedByUserId='owner')
        return rows[0]
    def setup(self):
        self.company,self.project,self.ceo,self.workforce,self.http=COMPANY,PROJECT,CEO,True,AsyncMock()
    monkeypatch.setattr(task_api.Paperclip,'__init__',setup)
    monkeypatch.setattr(task_api.Paperclip,'request',request)
    p=task_api.Paperclip()
    assert asyncio.run(blocker_delivery.forward(p,child,reason))
    assert asyncio.run(blocker_delivery.forward(p,child,reason)) and len(rows)==1
    projected = asyncio.run(blocker_delivery.owner_decisions(p,ROOT))[0]
    assert projected['package']=='jq' and projected['child_id']==CHILD
    data={'input':vote,'interaction_id':rows[0]['id'],'request_id':str(uuid4())}
    path='/api/tasks/'+ROOT+'/messages'
    with TestClient(server.app) as client:
        child['assigneeAgentId']=CEO
        assert client.post(path,json=data,headers=HEADERS).status_code==409
        assert client.post(path,json={**data,'reply_mode':'feedback'},headers=HEADERS).status_code==409
        assert not notes
        child['assigneeAgentId']=WORKER
        feedback = {**data, 'input':'Yes', 'reply_mode':'feedback','request_id':str(uuid4())}
        for _ in range(2):
            sent=client.post(path,json=feedback,headers=HEADERS)
            assert sent.status_code==200 and sent.json().get('feedback_id') and 'decision' not in sent.json()
        assert len(notes)==1 and rows[0]['status']=='pending' and not votes
        assert client.post(path,json={**feedback,'input':'Different text'},headers=HEADERS).status_code==409
        for note in ('Why this package?', 'What about disk space?'):
            legacy={**data,'input':note,'request_id':data['interaction_id']}
            assert client.post(path,json=legacy,headers=HEADERS).json().get('feedback_id')
        assert len(notes)==3 and rows[0]['status']=='pending' and not votes
        for _ in range(2):
            r=client.post(path,json=data,headers=HEADERS)
            assert r.status_code==200 and r.json()['decision']==status
        assert client.post(path,json={**data,'input':'Yes' if endpoint=='reject' else 'No'},headers=HEADERS).status_code==409
        assert client.post(path,json=feedback,headers=HEADERS).json().get('feedback_id')
        assert client.post(path,json={**feedback,'request_id':str(uuid4())},headers=HEADERS).status_code==409
    assert asyncio.run(blocker_delivery.forward(p,child,reason)) and len(rows)==1 and len(votes)==1
    assert child['status']=='blocked'


def test_ceo_uses_package_confirmation_before_generic_question(plugin):
    review = plugin.tools.blocker_review
    child={'id':CHILD,'identifier':'JAR-101','assigneeAgentId':WORKER}
    plugin.turn['worker_package_requests']={CHILD:['jq']}
    rows=[]
    def api(method,path,body=None,run=None):
        assert path=='/issues/'+ROOT+'/interactions'
        if method=='GET': return rows
        assert run==plugin.turn['run']
        row={**body,'id':str(uuid4()),'issueId':ROOT,'createdByAgentId':CEO,'status':'pending'}
        rows.append(row)
        return row
    decision=review.ask(api,plugin.turn,plugin.issue,child,review.GENERIC_QUESTION,'')
    assert decision['package']=='jq' and plugin.turn['owner_question']['id']==rows[0]['id']
    assert review.ask(api,plugin.turn,plugin.issue,child,'','')==decision and len(rows)==1


def test_ceo_repairs_same_assignment_then_escalates_repeated_cause(plugin, monkeypatch):
    child_with_evidence(plugin, status='blocked')
    original = plugin.children[0]
    original.update(description='[JARVIS REQUEST initial]\nCheck the document.', unblockDescriptor={'action':'Missing source.'})
    plugin.turn.update(inference_configuration={'version':3}, plan_decision='delegate')
    api = plugin.reporting.api
    def patch(method, path, body=None, run_id=None):
        if path.endswith('/tree-holds?status=active'):
            raise AssertionError('The native tree-holds endpoint requires board credentials')
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


def test_an_explicitly_incomplete_objective_cannot_be_completed_with_partial_reports(plugin, monkeypatch):
    child_with_evidence(plugin, status='done')
    plugin.children[0]['description'] = '[JARVIS REQUEST initial]\nCollect verified sources.'
    plugin.turn.update(inference_configuration={'version':3}, plan_decision='delegate', needs_inventory=False,
        response='The partial catalog is ready.\n\nCompleting attribution requires a public-video metadata reader. The overall task remains incomplete.')
    original_api = plugin.reporting.api
    created = []
    def api(method, path, body=None, run_id=None):
        if path.endswith('/interactions'):
            if method == 'GET': return created
            row = {**body, 'id':str(uuid4()), 'issueId':ROOT, 'createdByAgentId':CEO, 'status':'pending'}
            created.append(row)
            return row
        return original_api(method,path,body,run_id)
    monkeypatch.setattr(plugin.reporting,'api',api)
    plugin.tools.finalize(plugin.turn,completed=True)
    assert plugin.calls[-1][2]['status']=='blocked'
    assert not created
    assert 'metadata reader' in plugin.calls[-1][2]['unblockDescriptor']['action']


def test_review_retains_package_block_without_inventing_owner_decision(plugin, monkeypatch):
    child_with_evidence(plugin, status='blocked')
    child = plugin.children[0]
    child.update(description='[JARVIS REQUEST initial]\nUse the named utility.',
                 unblockDescriptor={'action': 'CEO review requested. Worker reports incomplete work: blocked. The utility is missing.'})
    review = plugin.tools.blocker_review
    previous = form(CEO, ROOT, CHILD, 'Keep the named utility?')
    previous.update(status='answered', resolvedByUserId='owner', result={'answers': [
        {'questionId':'child-' + CHILD, 'otherText':'Yes. Keep the original scope.'}]})
    original = plugin.reporting.api
    def api(method, path, *args):
        if path.endswith('/interactions'):
            assert method == 'GET'
            return [previous]
        return original(method, path, *args)
    monkeypatch.setattr(plugin.reporting, 'api', api)
    plugin.turn.update(inference_configuration={'version': 3}, plan_decision='delegate',
                       response='The utility is missing. ' + review.GENERIC_QUESTION)
    plugin.tools.prepare_turn_context(plugin.turn, issue=plugin.issue, comments=[])
    plugin.tools.finalize(plugin.turn, completed=True)
    update = plugin.calls[-1][2]
    assert update['status'] == 'blocked'
    assert update['unblockDescriptor']['action'] == update['comment'] == f"Blocked on {child['identifier']} — The utility is missing."
    assert not any(method == 'POST' and path.endswith('/interactions') for method, path, *_ in plugin.calls)
    with pytest.raises(ValueError, match='specific decision'):
        review.ask(None, plugin.turn, plugin.issue, child, review.GENERIC_QUESTION, 'The utility is missing.')


def test_approved_operator_provisioning_is_not_a_new_owner_decision(plugin):
    from unittest.mock import patch
    review = plugin.tools.blocker_review
    child = {'id':'child','identifier':'JAR-test','assigneeAgentId':'worker','status':'blocked'}
    decision = {'id':'approval','child_id':'child','agent_id':'worker','package':'nmap','answer':'accepted'}
    text = 'Can the runtime operator provide a scan-capable Nmap executable under the existing approval?'
    assert review.approved_operator_request(text, child, [decision]) == decision
    assert not review.approved_operator_request('Would you change the project scope for Nmap?', child, [decision])
    assert not review.approved_operator_request(text, {**child, 'assigneeAgentId':'another'}, [decision])
    turn = {'agent':'ceo'}
    with patch.object(review, 'decisions', return_value=[decision]):
        def api(method, path):
            assert method == 'GET'
            return []
        assert review.ask(api, turn, {'id':'parent'}, child, text, 'Operator provisioning is required.')['next_actor'] == 'runtime_operator'
    assert 'owner_question' not in turn


def test_terminal_repair_is_operator_work_and_owner_choices_keep_the_reply_field(plugin):
    review = plugin.tools.blocker_review
    child = {'id':CHILD, 'identifier':'JAR-103', 'status':'blocked'}
    issue = {'id':ROOT,'identifier':'JAR-100'}
    text = 'Can the runtime operator restore authenticated project-terminal scope for the authorized task?'
    turn = {'agent':CEO,'run':'run'}
    assert review.ask(None, turn, issue, child, text, 'The worker reported a terminal error.') == {'next_actor':'runtime_operator'}
    assert 'owner_question' not in turn
    maintenance = 'Can the runtime operator provide a supported writable, administratively authorized package-maintenance execution path for the same project container?'
    assert review.ask(None, turn, issue, child, maintenance, 'The package database is read-only.') == {'next_actor':'runtime_operator'}
    assert 'preserving project files' in turn['operator_blocker']
    assert review.project_operator_request(maintenance[:-1] + ', or should we prepare a replacement?') is None
    def api(method, path, body=None, run=None):
        if method == 'GET':
            return []
        prompt = body['payload']['questionSet']['questions'][0]['prompt']
        assert prompt == 'Would you approve replacing the container for JAR-103 in project JAR-100?'
        return {**body,'id':'question','status':'pending','issueId':ROOT,'createdByAgentId':CEO}
    decision = review.ask(api, {'agent':CEO,'run':'run'}, issue, child,
        f'Would you approve replacing the container for JAR-103 ({CHILD}) in project {ROOT}?',
        'Replacing the live container requires a decision.')
    assert decision['id'] == 'question'
