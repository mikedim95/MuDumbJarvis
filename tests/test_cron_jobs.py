"""Schedules are native, CEO-scoped, persistent and do not become local timers."""
import copy
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_phase1 import server
import task_api

CEO='11111111-1111-4111-8111-111111111111';PROJECT='22222222-2222-4222-8222-222222222222'
JOB='33333333-3333-4333-8333-333333333333';TRIGGER='44444444-4444-4444-8444-444444444444'
HEADERS={'X-Jarvis-Token':server.hud_token()}
BODY={'title':'Daily OSINT research','description':'Extend the native OSINT tools knowledge base.',
    'cron_expression':'0 9 * * *','timezone':'Europe/Athens','project_id':PROJECT}


@pytest.fixture
def native(monkeypatch):
    state=SimpleNamespace(jobs=[],calls=[],runs={},issues=[],holds=[])
    def handle(request):
        path=request.url.path;method=request.method;body=__import__('json').loads(request.content) if request.content else None
        state.calls.append((method,path,copy.deepcopy(body)))
        if path=='/api/companies/company/projects':return httpx.Response(200,json=[{'id':PROJECT,'companyId':'company','name':'OSINT knowledge'}])
        if path=='/api/companies/company/issues':return httpx.Response(200,json=state.issues)
        if path.startswith('/api/issues/'):
            if path.endswith('/tree-holds'):return httpx.Response(200,json=state.holds)
            row=next((i for i in state.issues if i['id']==path.split('/')[-1]),None)
            return httpx.Response(200,json=row) if row else httpx.Response(404,json={})
        if path=='/api/companies/company/routines':
            if method=='GET':return httpx.Response(200,json=state.jobs)
            row={'id':JOB if not state.jobs else str(uuid4()),'companyId':'company','triggers':[],**body,'env':{'PRIVATE':'NEVER_INCLUDE'}};state.jobs.append(row);return httpx.Response(201,json=row)
        if path.startswith('/api/routines/') and not path.endswith(('/triggers','/run')):
            row=next(j for j in state.jobs if j['id']==path.split('/')[-1])
            if method=='PATCH':row.update(body)
            return httpx.Response(200,json=row)
        if path.endswith('/triggers'):
            job=next(j for j in state.jobs if j['id']==path.split('/')[-2])
            row={'id':TRIGGER if not any(j['triggers'] for j in state.jobs) else str(uuid4()),'nextRunAt':'2026-11-18T07:00:00Z',**body};job['triggers'].append(row);return httpx.Response(201,json={'trigger':row})
        if path.startswith('/api/routine-triggers/'):
            row=next(t for j in state.jobs for t in j['triggers'] if t['id']==path.split('/')[-1]);row.update(body);return httpx.Response(200,json=row)
        if path.endswith('/run'):
            state.runs.setdefault(body['idempotencyKey'],{'id':'native-run','status':'issue_created','linkedIssueId':'native-issue'})
            return httpx.Response(202,json=state.runs[body['idempotencyKey']])
        raise AssertionError((method,path,body))
    def initialize(self):
        self.company='company';self.project=PROJECT;self.ceo=CEO
        self.http=httpx.AsyncClient(base_url='http://paperclip/api/',transport=httpx.MockTransport(handle))
    monkeypatch.setattr(task_api.Paperclip,'__init__',initialize)
    return state


def test_auth_and_origin_guard_every_schedule_mutation(native):
    with TestClient(server.app) as client:
        assert client.get('/api/cron-jobs').status_code==401
        assert client.post('/api/cron-jobs',headers={**HEADERS,'Origin':'https://other.example'},json=BODY).status_code==403
    assert native.calls==[]


def test_create_and_replay_reuse_native_routine_and_one_schedule_without_exposing_env(native):
    with TestClient(server.app) as client:
        first=client.post('/api/cron-jobs',headers=HEADERS,json=BODY);assert first.status_code==200
        second=client.post('/api/cron-jobs',headers=HEADERS,json=BODY);assert second.status_code==200
        data=client.get('/api/cron-jobs',headers=HEADERS)
    assert len(native.jobs)==1 and len(native.jobs[0]['triggers'])==1
    assert first.json()['assigneeAgentId']==CEO and first.json()['concurrencyPolicy']=='skip_if_active'
    assert first.json()['triggers'][0]['timezone']=='Europe/Athens'
    assert 'NEVER_INCLUDE' not in data.text and 'env' not in data.text


def test_pause_edit_resume_and_run_keep_native_scope_and_idempotency(native):
    with TestClient(server.app) as client:
        client.post('/api/cron-jobs',headers=HEADERS,json=BODY)
        assert client.patch('/api/cron-jobs/'+JOB,headers=HEADERS,json={'status':'paused'}).status_code==200
        assert client.put('/api/cron-jobs/'+JOB,headers=HEADERS,json={**BODY,'cron_expression':'0 10 * * *'}).json()['status']=='paused'
        assert client.post('/api/cron-jobs/'+JOB+'/run',headers=HEADERS,json={'request_id':str(uuid4())}).status_code==409
        client.patch('/api/cron-jobs/'+JOB,headers=HEADERS,json={'status':'active'})
        nonce=str(uuid4())
        for _ in range(2):assert client.post('/api/cron-jobs/'+JOB+'/run',headers=HEADERS,json={'request_id':nonce}).status_code==200
        native.jobs[0]['companyId']='foreign'
        assert client.patch('/api/cron-jobs/'+JOB,headers=HEADERS,json={'status':'paused'}).status_code==404
    assert len(native.runs)==1


def test_scheduled_execution_waiting_requires_an_actual_active_child(native):
    with TestClient(server.app) as client:
        client.post('/api/cron-jobs',headers=HEADERS,json=BODY)
        native.jobs[0]['lastRun']={'linkedIssueId':'ceo-issue','status':'failed','failureReason':'Execution issue moved to blocked'}
        native.issues=[{'id':'ceo-issue','identifier':'JAR-71','companyId':'company','assigneeAgentId':CEO,
            'status':'blocked','unblockDescriptor':{'action':'Await completion of JAR-72'}},
            {'id':'worker-issue','companyId':'company','parentId':'ceo-issue','status':'in_progress'}]
        job=client.get('/api/cron-jobs',headers=HEADERS).json()['jobs'][0]
        assert job['execution']['status']=='blocked' and job['execution']['display_status']=='waiting_for_workers'
        assert job['last_run']['failureReason']=='Execution issue moved to blocked'
        native.issues[1]['status']='blocked'
        assert client.get('/api/cron-jobs',headers=HEADERS).json()['jobs'][0]['execution']['display_status']=='blocked'


@pytest.mark.parametrize('changes',[{'cron_expression':'not cron'},{'timezone':'Invalid/Place'},{'project_id':'55555555-5555-4555-8555-555555555555'}])
def test_invalid_schedule_or_foreign_project_never_creates_work(native,changes):
    with TestClient(server.app) as client:response=client.post('/api/cron-jobs',headers=HEADERS,json={**BODY,**changes})
    assert response.status_code in (404,422) and not native.jobs


def test_general_and_mission_jobs_with_same_title_stay_separate_and_scope_cannot_be_reassigned(native):
    mission=str(uuid4());native.issues=[{'id':mission,'identifier':'JAR-M','companyId':'company','projectId':PROJECT,
        'status':'in_progress','assigneeAgentId':CEO,'parentId':None}]
    local={**BODY,'work_scope':'project','mission_id':mission}
    with TestClient(server.app) as client:
        general=client.post('/api/cron-jobs',headers=HEADERS,json=BODY);assert general.status_code==200
        project=client.post('/api/cron-jobs',headers=HEADERS,json=local);assert project.status_code==200
        assert general.json()['id']!=project.json()['id']
        assert len(client.get('/api/cron-jobs?scope=general',headers=HEADERS).json()['jobs'])==1
        scoped=client.get('/api/cron-jobs?scope=project&mission_id='+mission,headers=HEADERS).json()['jobs']
        assert len(scoped)==1 and scoped[0]['mission_id']==mission
        assert client.put('/api/cron-jobs/'+project.json()['id'],headers=HEADERS,json=BODY).status_code==409
        native.issues[0]['status']='done'
        assert client.patch('/api/cron-jobs/'+project.json()['id'],headers=HEADERS,json={'status':'active'}).status_code==409
        assert client.post('/api/cron-jobs/'+project.json()['id']+'/run',headers=HEADERS,json={'request_id':str(uuid4())}).status_code==409
        assert client.post('/api/cron-jobs/'+general.json()['id']+'/run',headers=HEADERS,json={'request_id':str(uuid4())}).status_code==200


def test_mission_job_requires_an_active_unheld_mission(native):
    mission=str(uuid4());native.issues=[{'id':mission,'companyId':'company','projectId':PROJECT,'status':'in_progress','assigneeAgentId':CEO}]
    with TestClient(server.app) as client:
        assert client.post('/api/cron-jobs',headers=HEADERS,json={**BODY,'work_scope':'project'}).status_code==422
        native.holds=[{'id':'native-stop-hold'}]
        assert client.post('/api/cron-jobs',headers=HEADERS,json={**BODY,'work_scope':'project','mission_id':mission}).status_code==409
    assert not native.jobs
