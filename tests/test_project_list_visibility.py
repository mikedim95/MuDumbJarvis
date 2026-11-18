"""Removing a project row persists visibility without deleting work/history."""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from test_phase1 import server
import task_api

CEO='11111111-1111-4111-8111-111111111111'
WORKER='22222222-2222-4222-8222-222222222222'
ISSUE='33333333-3333-4333-8333-333333333333'
HEADERS={'X-Jarvis-Token':server.hud_token()}


@pytest.fixture
def native(monkeypatch):
    state=SimpleNamespace(issue={'id':ISSUE,'companyId':'company','projectId':'project',
        'assigneeAgentId':CEO,'parentId':None,'status':'done','hiddenAt':None},calls=[],confirm=True,jobs=[])
    def handle(request):
        body=json.loads(request.content) if request.content else None
        state.calls.append((request.method,request.url.path,body))
        if request.url.path=='/api/companies/company/routines':return httpx.Response(200,json=state.jobs)
        if request.url.path.startswith('/api/routines/'):
            row=next(j for j in state.jobs if j['id']==request.url.path.split('/')[-1]);row.update(body);return httpx.Response(200,json=row)
        assert request.url.path=='/api/issues/'+ISSUE
        if request.method=='GET':return httpx.Response(200,json=state.issue)
        assert request.method=='PATCH' and set(body)=={'hiddenAt'}
        if state.confirm:state.issue.update(body)
        return httpx.Response(200,json=state.issue)
    def init(self):
        self.company='company';self.project='project';self.ceo=CEO;self.workforce=True
        self.http=httpx.AsyncClient(base_url='http://paperclip/api/',transport=httpx.MockTransport(handle))
    monkeypatch.setattr(task_api.Paperclip,'__init__',init)
    return state


def test_project_removal_and_restore_require_auth_and_same_origin_before_native_calls(native):
    with TestClient(server.app) as client:
        assert client.delete('/api/projects/'+ISSUE).status_code==401
        client.cookies.set('jarvis_token',server.hud_token())
        assert client.delete('/api/projects/'+ISSUE,headers={'Origin':'https://foreign.example'}).status_code==403
        assert client.post('/api/projects/'+ISSUE+'/restore',headers={'Origin':'https://foreign.example'}).status_code==403
    assert native.calls==[]


@pytest.mark.parametrize('status',['done','blocked','in_progress','todo','cancelled'])
def test_delete_from_list_only_updates_native_visibility_not_execution_or_history(native,status):
    native.issue['status']=status
    with TestClient(server.app) as client:
        response=client.delete('/api/projects/'+ISSUE,headers=HEADERS)
    assert response.status_code==200
    assert response.json()['removed'] is True and response.json()['history_preserved'] is True
    writes=[c for c in native.calls if c[0]!='GET'];assert len(writes)==1
    assert writes[0][0]=='PATCH' and set(writes[0][2])=={'hiddenAt'}
    assert writes[0][2]['hiddenAt'].endswith('Z') and native.issue['status']==status


def test_remove_and_undo_are_idempotent_with_saved_context_preserved(native):
    with TestClient(server.app) as client:
        removed=client.delete('/api/projects/'+ISSUE,headers=HEADERS).json()
        assert client.delete('/api/projects/'+ISSUE,headers=HEADERS).json()==removed
        restored=client.post('/api/projects/'+ISSUE+'/restore',headers=HEADERS)
        assert restored.status_code==200 and restored.json()['removed'] is False
        assert restored.json()['hidden_at'] is None
        assert client.post('/api/projects/'+ISSUE+'/restore',headers=HEADERS).json()==restored.json()
    assert len([c for c in native.calls if c[0]=='PATCH'])==2
    assert native.issue['status']=='done'


@pytest.mark.parametrize('field,value,status',[('companyId','another-company',404),
    ('parentId',ISSUE,409),('assigneeAgentId',WORKER,409)])
def test_only_current_company_top_level_ceo_projects_can_be_removed(native,field,value,status):
    native.issue[field]=value
    with TestClient(server.app) as client:
        assert client.delete('/api/projects/'+ISSUE,headers=HEADERS).status_code==status
    assert all(c[0]=='GET' for c in native.calls)


def test_failed_native_confirmation_keeps_the_project_in_the_list(native):
    native.confirm=False
    with TestClient(server.app) as client:
        assert client.delete('/api/projects/'+ISSUE,headers=HEADERS).status_code==502
    assert native.issue['hiddenAt'] is None


def test_archiving_a_mission_pauses_its_jobs_and_preserves_general_work(native):
    import work_scope
    native.jobs=[{'id':'local','companyId':'company','assigneeAgentId':CEO,'status':'active','variables':work_scope.variables([],'project',ISSUE)},
        {'id':'general','companyId':'company','assigneeAgentId':CEO,'status':'active','variables':work_scope.variables([],'general')},
        {'id':'other','companyId':'company','assigneeAgentId':CEO,'status':'active','variables':work_scope.variables([],'project','other-mission')}]
    with TestClient(server.app) as client:assert client.delete('/api/projects/'+ISSUE,headers=HEADERS).status_code==200
    assert [j['status'] for j in native.jobs]==['paused','active','active']
