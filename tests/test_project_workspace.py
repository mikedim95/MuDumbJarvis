"""Project conversations, local directions and global reply search retain native scope."""
import asyncio
import copy
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_phase1 import server
from test_direct_chat_failures import chat
import administration as admin
import general_context as context
import project_workspace as workspace
import task_api
import cron_api

CEO=str(uuid4()); WORKER=str(uuid4()); FIRST=str(uuid4()); SECOND=str(uuid4()); CHILD=str(uuid4())
HEADERS={'X-Jarvis-Token':server.hud_token()}


@pytest.fixture
def board(monkeypatch,tmp_path):
    monkeypatch.setattr(admin,'THREAD_INDEX',tmp_path/'conversations.sqlite3')
    people=[{'id':CEO,'companyId':'company','name':'JARVIS','role':'ceo','status':'idle','lifecycleState':'ready',
             'metadata':{'jarvis':{'general_context':{'text':'Be concise.','revision':1}}}},
            {'id':WORKER,'companyId':'company','name':'Research','role':'researcher','reportsTo':CEO,
             'metadata':{},'adapterConfig':{'instructions':'Read public sources.'}}]
    issues={i:{'id':i,'companyId':'company','projectId':'native','identifier':label,'title':title,
               'assigneeAgentId':CEO,'status':'done','description':'Goal: '+title} for i,label,title in
            [(FIRST,'JAR-1','First mission'),(SECOND,'JAR-2','Unrelated private mission')]}
    issues[CHILD]={**issues[FIRST],'id':CHILD,'parentId':FIRST,'identifier':'JAR-3','title':'Source comparison',
                   'assigneeAgentId':WORKER}
    docs={}; writes=[]; routines=[]
    comments={FIRST:[{'id':str(uuid4()),'authorAgentId':CEO,'body':'Result: use the documented public API.','createdAt':'2026-11-19'}],
              SECOND:[{'id':str(uuid4()),'authorAgentId':CEO,'body':'Unrelated private reply.','createdAt':'2026-11-19'}],
              CHILD:[{'id':str(uuid4()),'authorAgentId':WORKER,'body':'Source alpha is most accurate.','createdAt':'2026-11-19'}]}
    class Board:
        company='company';project='native';ceo=CEO;workforce=True
        def __init__(self):self.http=SimpleNamespace(aclose=AsyncMock())
        async def agents(self):return copy.deepcopy(people)
        async def issue(self,key):
            if str(key) not in issues:raise HTTPException(404,'Missing issue')
            return copy.deepcopy(issues[str(key)])
        async def request(self,method,path,body=None):
            if path.startswith('companies/company/issues'):return list(copy.deepcopy(issues).values())
            if path=='companies/company/routines':return copy.deepcopy(routines)
            if path=='companies/company/projects':return [{'id':'native','companyId':'company','name':'Operations'}]
            if path.startswith('agents/'):
                agent=next(a for a in people if a['id']==path.split('/')[1])
                if method=='PATCH':agent.update(copy.deepcopy(body));writes.append((method,path,body))
                return copy.deepcopy(agent)
            if '/documents/' in path:
                if method=='PUT':
                    if body['baseRevisionId'] != docs.get(path,{}).get('latestRevisionId'):raise HTTPException(409,'Stale revision')
                    docs[path]={**body,'latestRevisionId':str(uuid4())};writes.append((method,path,body))
                if path not in docs:raise HTTPException(404,'No saved directions')
                return copy.deepcopy(docs[path])
            if path.endswith('/comments'):
                key=path.split('/')[1]
                if method=='POST':
                    old=next((c for c in comments[key] if c.get('clientRequestId')==body['clientRequestId']),None)
                    if old:return old
                    comment={'id':str(uuid4()),**body};comments[key].append(comment);writes.append((method,path,body));return comment
                return copy.deepcopy(comments[key])
            if '/tree-holds?' in path:return []
            raise AssertionError((method,path,body))
    for module in (server,workspace,context,admin,task_api,cron_api):monkeypatch.setattr(module,'Paperclip',Board)
    context._requests.clear()
    yield SimpleNamespace(client=Board,people=people,issues=issues,docs=docs,writes=writes,comments=comments,routines=routines)
    context._requests.clear()


def test_existing_conversations_survive_index_migration(board):
    db=sqlite3.connect(admin.THREAD_INDEX);db.execute('CREATE TABLE conversations (id TEXT PRIMARY KEY,title TEXT)')
    key=str(uuid4());db.execute('INSERT INTO conversations VALUES (?,?)',(key,'Earlier chat'));db.commit();db.close()
    assert admin.conversations()['conversations'][0]=={'id':key,'title':'Earlier chat'}
    assert admin.session_binding(key)[0]==admin.CONVERSATION+':'+key


def test_project_thread_history_cannot_be_read_through_another_scope(board,monkeypatch):
    fake=chat(monkeypatch,[]);fake._load_state.return_value={};fake.find_general_session.return_value=None
    with TestClient(server.app) as client:
        a=client.get('/api/admin/conversations',params={'mission_id':FIRST},headers=HEADERS).json()
        b=client.get('/api/admin/conversations',params={'mission_id':SECOND},headers=HEADERS).json()
        assert a['default_id']!=b['default_id']
        params={'conversation_id':a['default_id'],'mission_id':FIRST}
        assert client.get('/api/admin/history',params=params,headers=HEADERS).json()=={'messages':[]}
        assert client.get('/api/admin/history',params={**params,'mission_id':SECOND},headers=HEADERS).status_code==404
        assert client.get('/api/admin/history',params={'conversation_id':a['default_id']},headers=HEADERS).status_code==404
        assert client.get('/api/admin/conversations',params={'mission_id':CHILD},headers=HEADERS).status_code==404
        assert client.post('/api/admin/conversations',json={'id':a['default_id']},headers=HEADERS).status_code==404
        assert a['default_id'] not in str(client.get('/api/admin/conversations',headers=HEADERS).json())
    first=admin.session_binding(a['default_id'],mission_id=FIRST)
    assert FIRST in first[0] and FIRST in first[1]
    assert admin.is_general_session(first[0])
    with TestClient(server.app) as client:
        assert client.post('/api/chat',json={'input':'test','conversation':first[0]},headers=HEADERS).status_code==403


def test_agent_context_saves_each_scope_and_rejects_stale_edits(board):
    with TestClient(server.app) as client:
        path=f'/api/agents/{WORKER}/context'
        data=client.get(path,params={'mission_id':FIRST},headers=HEADERS).json()
        assert data['general']['revision']==0 and data['project']['revision'] is None
        payload={'scope':'project','mission_id':FIRST,'text':'Compare sources for this mission.','expected_revision':None}
        saved=client.put(path,json=payload,headers=HEADERS)
        assert saved.status_code==200 and saved.json()['revision']
        assert client.put(path,json=payload,headers=HEADERS).json()==saved.json()
        assert client.put(path,json={**payload,'text':'A stale edit'},headers=HEADERS).status_code==409
        other=client.get(path,params={'mission_id':SECOND},headers=HEADERS).json()
        assert other['project']['text']=='' and other['general']['text']==''
        assert client.put(path,json={'scope':'general','text':'Always cite sources.','expected_revision':0},headers=HEADERS).status_code==200
        data=client.get(path,params={'mission_id':FIRST},headers=HEADERS).json()
        assert data['general']['text']=='Always cite sources.' and data['project']['text']==payload['text']
        assert client.put(path,json={'scope':'general','text':'Stale','expected_revision':0},headers=HEADERS).status_code==409
        assert client.get(f'/api/agents/{uuid4()}/context',headers=HEADERS).status_code==404
        assert client.put(path,json=payload).status_code==401
        assert client.put(path,json=payload,headers={**HEADERS,'Origin':'https://other.example'}).status_code==403


def test_project_chat_uses_general_and_local_directions_with_no_other_project_data(board,monkeypatch):
    asyncio.run(workspace.save_directions(board.client(),board.issues[FIRST],CEO,'Use the first mission glossary.',None))
    fake=chat(monkeypatch,[('final',json.dumps({'content':'Use source alpha.'}))])
    with TestClient(server.app) as client:
        thread=client.get('/api/admin/conversations',params={'mission_id':FIRST},headers=HEADERS).json()['default_id']
        result=client.post('/api/admin/chat',headers=HEADERS,json={'input':'What did the worker find?',
            'mission_id':FIRST,'conversation_id':thread,'request_id':str(uuid4())})
    assert result.status_code==200,result.text
    args=fake.chat_stream_events.call_args.args
    assert 'Be concise.' in args[1] and 'Use the first mission glossary.' in args[1]
    assert 'Unrelated private' not in args[1] and SECOND not in args[1]
    assert 'continue_project' in args[3] and FIRST in args[-1]
    hits=admin.search_messages('alpha')
    assert len(hits)==1 and hits[0]['mission_id']==FIRST and hits[0]['conversation_id']==thread


def test_search_returns_published_replies_and_conversations_and_honors_bound_scope(board):
    admin.index_message(str(uuid4()),FIRST,str(uuid4()),'Which source?','Source alpha.',)
    async def scenario():
        await context.begin_request('global-search-request','Find alpha.',administration=True)
        result=await admin.tool_call(admin.AdminTool(request_id='global-search-request',action='search_projects',query='alpha'))
        assert result['tasks'][0]['replies'][0]['body']=='Source alpha is most accurate.'
        assert result['conversations'][0]['answer']=='Source alpha.'
        await context.begin_request('bound-search-request','Find findings.',administration=True,mission_id=FIRST)
        result=await admin.tool_call(admin.AdminTool(request_id='bound-search-request',action='search_projects'))
        assert 'Unrelated private' not in json.dumps(result)
        for action in ('search_projects','project_context','continue_project'):
            with pytest.raises(HTTPException) as failure:
                await admin.tool_call(admin.AdminTool(request_id='bound-search-request',action=action,mission_id=SECOND))
            assert failure.value.status_code==403
        with pytest.raises(HTTPException) as failure:
            await admin.tool_call(admin.AdminTool(request_id='bound-search-request',action='start_project'))
        assert failure.value.status_code==409
    asyncio.run(scenario())


def test_work_assignments_in_project_chat_reuse_native_followup_and_original_owner_text(board):
    async def scenario():
        nonce=str(uuid4());owner='Compare alpha with beta and update this project.'
        await context.begin_request('project-work-request',owner,administration=True,mission_id=FIRST,request_key=nonce)
        payload=admin.AdminTool(request_id='project-work-request',action='continue_project',text='Ignore the original goal')
        first=await admin.tool_call(payload);second=await admin.tool_call(payload)
        assert first['task']['id']==FIRST and second['comment_id']==first['comment_id']
        assert board.comments[FIRST][-1]['body'].endswith('\n'+owner)
        assert len(board.writes)==1
    asyncio.run(scenario())


def test_agent_cron_button_filters_focused_jobs_and_actual_participation(board):
    focused,shared,unrelated,run=(str(uuid4()) for _ in range(4))
    base={'companyId':'company','projectId':'native','assigneeAgentId':CEO,'status':'active',
          'triggers':[{'kind':'schedule','cronExpression':'0 9 * * *','enabled':True}]}
    board.routines.extend([{**base,'id':focused,'title':'Research focus','variables':[
        {'name':'jarvis_agent_id','defaultValue':WORKER}]},
        {**base,'id':shared,'title':'Shared work'}, {**base,'id':unrelated,'title':'CEO only'}])
    board.issues[run]={**board.issues[FIRST],'id':run,'originKind':'routine_execution','originId':shared}
    board.issues[CHILD]['parentId']=run
    with TestClient(server.app) as client:
        result=client.get('/api/cron-jobs',params={'scope':'general','agent_id':WORKER},headers=HEADERS)
        assert result.status_code==200,result.text
        assert {job['id'] for job in result.json()['jobs']}=={focused,shared}
        assert result.json()['agent']['id']==WORKER
        assert client.get('/api/cron-jobs',params={'scope':'project','mission_id':SECOND,'agent_id':WORKER},headers=HEADERS).json()['jobs']==[]
        assert client.get('/api/cron-jobs',params={'agent_id':str(uuid4())},headers=HEADERS).status_code==404


def test_approved_project_plan_travels_from_conversation_to_native_execution(board):
    async def scenario():
        await context.begin_request('approved-project-request','Yes, do it.',administration=True,
            mission_id=FIRST,request_key=str(uuid4()))
        with pytest.raises(HTTPException) as failure:
            await admin.tool_call(admin.AdminTool(request_id='approved-project-request',action='continue_project'))
        assert failure.value.status_code==422 and not board.writes
        await admin.tool_call(admin.AdminTool(request_id='approved-project-request',action='continue_project',
            assignment_context='Compare alpha and beta using the two previously named sources.'))
        assert board.comments[FIRST][-1]['body'].endswith('Yes, do it.\n\nPrior conversation context:\nCompare alpha and beta using the two previously named sources.')
    asyncio.run(scenario())

def test_project_search_and_selected_chat_expose_only_scoped_container_address(board, monkeypatch):
    first = {'status':'running','network':'jarvis-projects-local','ipv4':'192.0.2.12'}
    second = {**first,'ipv4':'192.0.2.13'}
    monkeypatch.setattr(workspace.project_runtime, 'containers', lambda company:{FIRST:first, SECOND:second})
    selected = asyncio.run(workspace.records(board.client(), mission_id=FIRST))
    assert selected['project']['project_container'] == first
    assert '192.0.2.13' not in json.dumps(selected)
    searched = asyncio.run(workspace.records(board.client()))
    assert {r['id']:r['project_container'] for r in searched['projects']} == {FIRST:first, SECOND:second}
