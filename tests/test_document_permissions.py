import asyncio
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from test_record_artifact_access import native, read
from test_public_sources import sources
from test_employee_work import work, COMPANY, PROJECT, AGENT, ARTIFACT, ISSUE
from test_project_workspace import board, FIRST, CHILD, WORKER, HEADERS, server
import document_permissions as permissions


def test_request_grant_deny_revocation_and_verified_bytes(native,monkeypatch):
    src=native['sources']; target=native['row']['id'];native['row']['projectId']=PROJECT
    from urllib.error import HTTPError
    doc={}; approvals=[]; base=src.module.reporting.api
    def api(method,path,*args):
        if '/documents/' in path:
            if not doc:raise HTTPError('',404,'missing',{},None)
            return doc
        if path.endswith('/approvals'):
            if method=='POST':
                row={'id':str(uuid4()),'companyId':COMPANY,'status':'pending',**args[0]}
                approvals.append(row);return row
            return approvals
        return base(method,path,*args)
    monkeypatch.setattr(src.module.reporting,'api',api)
    def req(mode):return json.loads(read(native,query=mode+' document '+ARTIFACT))
    with pytest.raises(PermissionError):req('read')
    assert len(approvals)==0 and req('request')['status']==req('request')['status']=='pending' and len(approvals)==1
    with pytest.raises(PermissionError):req('read')
    approvals[0].update(status='approved',decidedByUserId='board-owner')
    assert req('read')['artifact']['sha256']==native['artifacts'][0]['sha256']
    assert 'workspace_path' not in req('read')['artifact']
    row={'agent':AGENT,'source':target,'artifact':ARTIFACT,'name':'native.json','sha256':native['artifacts'][0]['sha256'],'state':'revoked'}
    doc.update(companyId=COMPANY,issueId=ISSUE,key=permissions.access.KEY,updatedByUserId='owner',body=json.dumps([row]))
    for op in ('request','read'):
        with pytest.raises(PermissionError,match='revoked'):req(op)
    approvals[0]['status']='rejected'
    doc['updatedByAgentId']=AGENT
    with pytest.raises(PermissionError):req('read')
    doc['updatedByAgentId']=None;doc['body']='[]'
    assert req('request')['status']=='rejected'
    row['state']='allowed';doc['body']=json.dumps([row])
    assert req('read')['artifact']['artifact_id']==ARTIFACT
    native['row']['projectId']='another-project'
    with pytest.raises(PermissionError):req('read')


def test_owner_control_checks_assignment_and_persists_native_decision(board,monkeypatch):
    import task_api
    original=board.client.request
    aid=str(uuid4());sha='1'*64
    async def request(self,method,path,body=None):
        if path.endswith('/attachments'):
            return [{'id':aid,'companyId':'company','issueId':FIRST,'originalFilename':'assessment.txt',
                     'byteSize':80,'sha256':sha,'createdByAgentId':WORKER}]
        if path.endswith('/approvals'):return []
        if '/documents/' in path and method=='PUT':
            body={**body,'companyId':'company','issueId':CHILD,'key':permissions.access.KEY,'updatedByUserId':'owner'}
        return await original(self,method,path,body)
    board.people[1]['metadata']={'jarvis':{'profile':'research'}}
    monkeypatch.setattr(board.client,'request',request)
    path='/api/tasks/'+CHILD+'/document-permissions'
    with TestClient(server.app) as c:
        assert c.get(path).status_code==401
        body={'state':'allowed','agent_id':WORKER,'source_id':FIRST,'artifact_id':aid,'sha256':sha,'request_id':str(uuid4())}
        assert c.get(path,params={'source_id':FIRST},headers=HEADERS).json()['documents'][0]['id']==aid
        assert c.post(path,headers=HEADERS,json={**body,'agent_id':str(uuid4())}).status_code==409
        assert c.post(path,headers=HEADERS,json={**body,'sha256':'bad'}).status_code==409
        assert c.post(path,headers=HEADERS,json=body).json()['state']=='allowed'
        assert c.get(path,headers=HEADERS).json()['permissions'][0]['state']=='allowed'
        assert c.post(path,headers=HEADERS,json={**body,'state':'revoked','request_id':str(uuid4())}).status_code==409
        revision=c.get(path,headers=HEADERS).json()['revision']
        assert c.post(path,headers=HEADERS,json={**body,'state':'revoked','expected_revision':revision,'request_id':str(uuid4())}).json()['state']=='revoked'


def test_software_document_control_offers_only_siblings_and_records_private_delivery(board,monkeypatch):
    source, artifact = str(uuid4()), str(uuid4())
    board.issues[source] = {**board.issues[CHILD], 'id':source, 'status':'blocked', 'identifier':'JAR-94'}
    board.people[1]['metadata'] = {'jarvis':{'profile':'software_development'}}
    original = board.client.request
    async def request(self,method,path,body=None):
        if path.endswith('/approvals'):
            return []
        if path == 'issues/'+source+'/attachments':
            return [{'id':artifact, 'originalFilename':'summary.txt', 'companyId':'company',
                     'issueId':source, 'createdByAgentId':'publisher', 'byteSize':3, 'sha256':'a'*64}]
        if method=='PUT' and '/documents/' in path:
            body = {**body, 'companyId':'company','issueId':CHILD,'key':permissions.access.KEY,'updatedByUserId':'owner'}
        return await original(self,method,path,body)
    monkeypatch.setattr(board.client,'request',request)
    endpoint = '/api/tasks/'+CHILD+'/document-permissions'
    with TestClient(server.app) as c:
        view = c.get(endpoint,headers=HEADERS).json()
        assert view['private_sibling_inputs'] and [r['id'] for r in view['sources']]==[source]
        assert c.get(endpoint,params={'source_id':FIRST},headers=HEADERS).status_code==404
        body = {'state':'allowed','agent_id':WORKER,'source_id':source,'artifact_id':artifact,
                'sha256':'a'*64,'request_id':str(uuid4())}
        saved = c.post(endpoint,json=body,headers=HEADERS)
        assert saved.status_code==200 and saved.json()==c.post(endpoint,json=body,headers=HEADERS).json()
        row, = json.loads(next(iter(board.docs.values()))['body'])
        assert row['delivery']=='private_input' and row['source']==source


@pytest.fixture
def unfinished_sibling(work,monkeypatch):
    source, publisher = str(uuid4()), str(uuid4())
    raw = b'original research\n'
    sibling = {**work.issue, 'id':source, 'identifier':'JAR-94', 'assigneeAgentId':publisher, 'status':'blocked'}
    artifact = {'id':ARTIFACT,'companyId':COMPANY,'issueId':source,'createdByAgentId':publisher,
                'originatingRunId':'published','originalFilename':'summary.txt','byteSize':len(raw),
                'sha256':work.module.digest(raw)}
    grant = {'source':source,'artifact':ARTIFACT,'sha256':artifact['sha256'],'agent':AGENT,
             'state':'allowed','delivery':'private_input'}
    doc = {'issueId':ISSUE,'companyId':COMPANY,'key':permissions.access.KEY,'updatedByUserId':'owner'}
    run = {'runId':'published','agentId':publisher,'status':'succeeded'}
    fetches = []
    def api(method,path,*args):
        assert method=='GET'
        if path=='/issues/'+ISSUE:return work.issue
        if path.endswith('/issues'):return [work.issue,sibling]
        if path.endswith('/documents/'+permissions.access.KEY):return {**doc,'body':json.dumps([grant])}
        if path=='/issues/'+source+'/attachments':return [artifact,{**artifact,'id':str(uuid4())}]
        if path=='/issues/'+source+'/runs':
            return [run,{'runId':'later-review','agentId':publisher,'status':'succeeded','startedAt':'2026-11-20'}]
        pytest.fail(path)
    monkeypatch.setattr(work.module.reporting,'api',api)
    monkeypatch.setattr(work.module,'attachment_bytes',lambda aid:fetches.append(aid) or raw)
    return work.module.read_worker_artifacts, grant, sibling, run, doc, raw, fetches


def test_granted_sibling_reads_checked_private_bytes_without_completing_source(unfinished_sibling,work):
    reader, grant, sibling, run, doc, raw, fetches = unfinished_sibling
    receipt, = json.loads(reader({}))['artifacts']
    assert receipt['source_task_status']=='blocked' and receipt['access']=='granted_input' and not fetches
    view = json.loads(reader({'issue_id':sibling['id'],'artifact_id':ARTIFACT}))['artifact']
    assert view['source_run_status']=='succeeded' and view['sha256']==grant['sha256']
    assert work.module.read_workspace(work.turn,view['workspace_path'])==raw and fetches==[ARTIFACT]
    assert sibling['status']=='blocked'
    sibling['status']='done'
    assert json.loads(reader({'artifact_id':ARTIFACT}))['artifact']['source_task_status']=='done'
    assert sum(a['artifact_id']==ARTIFACT for a in json.loads(reader({}))['artifacts'])==1
    grant.pop('delivery')
    assert 'workspace_path' not in json.loads(reader({'artifact_id':ARTIFACT}))['artifact']
    work.monkeypatch.setattr(work.module,'attachment_bytes',lambda _:b'tampered bytes')
    with pytest.raises(ValueError,match='hash/size'):reader({'artifact_id':ARTIFACT})


@pytest.mark.parametrize(('section','key','value'),[
    (0,'state','revoked'),(0,'state','denied'),(0,'agent','wrong'),(0,'sha256','0'*64),
    (1,'projectId','foreign'),(1,'parentId','wrong'),(1,'hiddenAt','yesterday'),
    (1,'assigneeAgentId','another-worker'),(2,'status','failed'),(3,'updatedByAgentId','forged')])
def test_sibling_grant_cannot_cross_scope_or_outlive_a_revocation(unfinished_sibling,section,key,value):
    reader, grant, sibling, run, doc, raw, fetches = unfinished_sibling
    (grant,sibling,run,doc)[section][key]=value
    with pytest.raises(PermissionError):reader({'artifact_id':ARTIFACT})
    assert fetches==[]
