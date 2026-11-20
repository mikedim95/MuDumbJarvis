"""Owner recovery is visible, scoped, evidence-based, and uses native controls."""
import copy
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from test_phase1 import server
from test_tasks import transport, headers, ISSUE, CHILD, CEO, AGENT
from test_monitor import RUN
from agent_work import recovery_view

ACTION='99999999-9999-4999-8999-999999999999'


def failure(run=RUN):
    return {'recoveryActionId':ACTION,'runId':run,'canRetry':True,
        'cause':'legacy_execution_requires_reconciliation','nextAction':'Review and continue the stopped run.',
        'runError':'Hermes gateway HTTP 502; private-credential-must-not-cross-this-view'}


def test_recovery_projection_is_small_and_does_not_expose_raw_failure_or_configuration():
    result=recovery_view({'status':'blocked','executionBlocker':failure()})
    assert result['can_retry'] and result['needs_reconciliation'] and result['action_id']==ACTION
    assert result['run_id']==RUN and 'HTTP 502' in result['reason']
    assert 'private-credential' not in json.dumps(result)
    assert not recovery_view({'status':'done','executionBlocker':failure()})['can_retry']
    assert not recovery_view({'status':'blocked','executionBlocker':failure(),'executionRunId':'active'})['can_retry']


@pytest.fixture
def recovery(monkeypatch):
    state={'issue':{'id':ISSUE,'identifier':'JAR-84','companyId':'company','projectId':'project',
        'assigneeAgentId':CEO,'status':'blocked','executionBlocker':failure()},
        'runs':[{'runId':RUN,'status':'failed','startedAt':'2026-11-19T08:41:26Z'}],
        'holds':[],'writes':[]}
    def handler(request):
        path=request.url.path
        if path=='/api/issues/'+ISSUE:return httpx.Response(200,json=state['issue'])
        if path.endswith('/tree-holds'):return httpx.Response(200,json=state['holds'])
        if path.endswith('/runs'):return httpx.Response(200,json=state['runs'])
        assert request.method=='POST' and path=='/api/issues/'+ISSUE+'/recovery-actions/resolve'
        body=json.loads(request.content);state['writes'].append(body)
        state['issue'].update(status='todo',executionBlocker=None)
        return httpx.Response(200,json={'issue':state['issue'],'recoveryAction':{'id':ACTION,'status':'resolved'}})
    transport(monkeypatch,handler)
    state['body']={'observed_run_id':RUN,'action_id':ACTION,'provider_stopped':True,'action_outcome':'mixed',
        'evidence':'The previous execution stopped. Its published report is preserved; continue from that verified evidence.'}
    return state


def test_owner_resolution_uses_exact_native_evidence_contract_without_marking_work_done(recovery):
    with TestClient(server.app) as c:
        assert c.post('/api/tasks/'+ISSUE+'/resolve-execution',json=recovery['body']).status_code==401
        r=c.post('/api/tasks/'+ISSUE+'/resolve-execution',json=recovery['body'],headers=headers)
    assert r.status_code==200 and r.json()['resolution_saved']
    assert r.json()['task']['status']=='todo'
    call,=recovery['writes']
    assert call['actionId']==ACTION and call['outcome']=='restored' and call['sourceIssueStatus']=='todo'
    assert call['executionReconciliation']=={'runId':RUN,'providerStopped':True,'actionOutcome':'mixed',
        'outcomeEvidence':recovery['body']['evidence']}


@pytest.mark.parametrize('condition',['foreign','active','hold','newer-run','running-run','wrong-action','not-stopped','blank-evidence'])
def test_resolution_cannot_bypass_scope_stop_holds_activity_or_unverified_outcomes(recovery,condition):
    if condition=='foreign':recovery['issue']['companyId']='foreign'
    elif condition=='active':recovery['issue']['executionRunId']='active'
    elif condition=='hold':recovery['holds']=[{'status':'active'}]
    elif condition=='newer-run':recovery['runs'].append({'runId':str(uuid4()),'status':'failed','startedAt':'2026-11-19T09:00:00Z'})
    elif condition=='running-run':recovery['runs'][0]['status']='running'
    elif condition=='wrong-action':recovery['body']['action_id']=str(uuid4())
    elif condition=='not-stopped':recovery['body']['provider_stopped']=False
    else:recovery['body']['evidence']=' '*25
    with TestClient(server.app) as c:
        r=c.post('/api/tasks/'+ISSUE+'/resolve-execution',json=recovery['body'],headers=headers)
    assert r.status_code in (404,409,422) and recovery['writes']==[]


def test_resolution_keeps_existing_cookie_csrf_protection(recovery):
    with TestClient(server.app) as c:
        c.cookies.set('jarvis_token',server.hud_token())
        assert c.post('/api/tasks/'+ISSUE+'/resolve-execution',json=recovery['body'],
            headers={'Origin':'https://other.example'}).status_code==403
    assert recovery['writes']==[]


def test_todo_worker_retry_with_completed_dependency_is_visible_in_profile_and_tree(monkeypatch):
    root={'id':ISSUE,'identifier':'JAR-84','companyId':'company','projectId':'project','status':'blocked',
        'assigneeAgentId':CEO,'unblockDescriptor':{'action':'Await completion of JAR-86.'}}
    child={**root,'id':CHILD,'identifier':'JAR-86','parentId':ISSUE,'assigneeAgentId':AGENT,'status':'todo',
        'blockedBy':[{'id':'source','status':'done'}],'unblockDescriptor':None}
    listed=[root,child];people=[{'id':CEO,'name':'JARVIS','companyId':'company','status':'idle'},
        {'id':AGENT,'name':'Security','companyId':'company','status':'error','reportsTo':CEO}]
    def handler(request):
        path=request.url.path
        if path.endswith('/agents'):value=people
        elif path.endswith('/issues'):value=listed
        elif path.endswith('/routines') or path.endswith('/interactions') or path.endswith('/comments') or path.endswith('/runs'):value=[]
        elif path=='/api/issues/'+ISSUE:value=root
        elif path=='/api/issues/'+CHILD:value={**child,'executionBlocker':failure()}
        else:raise AssertionError(path)
        return httpx.Response(200,json=copy.deepcopy(value))
    transport(monkeypatch,handler,workforce=True)
    with TestClient(server.app) as c:
        profile=c.get('/api/agents/work?mission_id='+ISSUE,headers=headers).json()
        tree=c.get('/api/tasks/'+ISSUE,headers=headers).json()
    worker=next(a for a in profile['agents'] if a['id']==AGENT)
    assert worker['activity']=='blocked' and worker['work'][0]['recovery']['needs_reconciliation']
    task,=tree['children']
    assert task['state']=='blocked' and task['recovery']['run_id']==RUN
    assert 'HTTP 502' in task['brief']['progress']
    assert 'private-credential' not in json.dumps(profile)+json.dumps(tree)
