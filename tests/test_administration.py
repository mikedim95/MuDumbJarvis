"""Administrator actions persist natively and remain separate from conversational chat."""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from test_phase1 import server
from test_direct_chat_failures import chat
import administration as admin
import general_context as context

CEO='11111111-1111-4111-8111-111111111111'
WORKER='22222222-2222-4222-8222-222222222222'
FOREIGN='33333333-3333-4333-8333-333333333333'
HEADERS={'X-Jarvis-Token':server.hud_token()}


@pytest.fixture
def native(monkeypatch, tmp_path):
    monkeypatch.setattr(admin, 'THREAD_INDEX', tmp_path / 'general.sqlite3')
    people=[{'id':CEO,'name':'JARVIS','role':'ceo','companyId':'company','lifecycleState':'ready',
        'adapterConfig':{'instructions':'Original CEO prompt','apiKey':{'type':'secret_ref','id':'private-reference'}},
        'metadata':{'jarvis':{'inference_configuration':{'signature':'keep'},'general_context':{'text':'Existing directions','revision':1}}}},
        {'id':WORKER,'name':'JARVIS Research','role':'researcher','companyId':'company','reportsTo':CEO,
         'adapterConfig':{'instructions':'Original worker prompt','baseUrl':'http://worker'},
         'metadata':{'jarvis':{'profile':'research','profile_sha256':'frozen'}}},
        {'id':FOREIGN,'name':'Foreign','role':'general','companyId':'elsewhere','metadata':{}}]
    calls=[];projects={}
    class Client:
        company='company';ceo=CEO;project='general'
        def __init__(self):self.http=SimpleNamespace(aclose=AsyncMock())
        async def agents(self):return copy.deepcopy(people)
        async def request(self,method,path,body=None):
            calls.append((method,path,copy.deepcopy(body)))
            if path.startswith('agents/'):
                agent=next(a for a in people if a['id']==path.split('/')[1])
                if method=='PATCH':agent.update(copy.deepcopy(body))
                return copy.deepcopy(agent)
            assert method=='POST' and path=='companies/company/issues'
            key=body['idempotencyKey']
            projects.setdefault(key,{'id':str(uuid4()),'identifier':'JAR-100','companyId':'company',**body})
            return copy.deepcopy(projects[key])
    monkeypatch.setattr(context,'Paperclip',Client);monkeypatch.setattr(admin,'Paperclip',Client)
    context._requests.clear();context._locks.clear()
    return SimpleNamespace(people=people,calls=calls,projects=projects)


async def grant(reference='admin-request-001',key=None,selected=CEO,message='Please configure the team.'):
    return await context.begin_request(reference,message,selected,
        administration=True,request_key=key or str(uuid4()))


def call(action,reference='admin-request-001',**fields):
    return admin.tool_call(admin.AdminTool(request_id=reference,action=action,**fields))


def test_configuration_shows_actual_prompts_without_adapter_credentials(native):
    data=asyncio.run(admin.configuration())
    assert len(data['agents'])==2 and len(data['chat_prompts'])==2
    assert data['agents'][0]['system_prompt']=='Original CEO prompt'
    assert data['agents'][1]['prompt_sha256']==admin.digest('Original worker prompt')
    assert 'private-reference' not in json.dumps(data) and 'apiKey' not in json.dumps(data)
    assert all(a['id']!=FOREIGN for a in data['agents'])


def test_direct_request_cannot_turn_itself_into_an_administrator(native):
    async def scenario():
        await context.begin_request('direct-request-01','Rename Research to OSINT')
        with pytest.raises(HTTPException) as exc:
            await call('rename_agent','direct-request-01',agent_id=WORKER,name='JARVIS OSINT')
        assert exc.value.status_code==403
    asyncio.run(scenario());assert native.calls==[]


def test_general_learning_creates_native_general_work_without_a_mission_context(native):
    async def scenario():
        goal='Build reusable team knowledge about documented tools.'
        await grant(message=goal)
        receipt=await call('start_general_work',title='Reusable methods',text=goal)
        assert receipt['task']['work_scope']=='general' and receipt['task']['mission_id'] is None
        assert receipt['task']['description']=='Build reusable team knowledge about documented tools.'
        saved=next(iter(native.projects.values()))
        assert saved['description'].startswith('[JARVIS GENERAL WORK]\n')
        assert (await call('start_general_work',title='Reusable methods',text='Build reusable team knowledge about documented tools.'))['task']['id']==receipt['task']['id']
        assert len(native.projects)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('endpoint,operation', [
    ('/api/chat', 'start_project'), ('/api/admin/chat', 'start_general_work')])
def test_assigned_research_opens_a_ceo_mission_and_preserves_the_owner_request(native,monkeypatch,endpoint,operation):
    goal = 'Can you research public tool documentation and compare the available options?'
    fake = chat(monkeypatch, [])
    def stream(session_id, chat_input, timeout, instructions, session_key):
        assert 'You are JARVIS, the CEO.' in instructions
        grant_id = next(iter(context._requests))
        receipt = asyncio.run(call(operation, grant_id, title='Compare public tools',
            text='Produce a team-wide shared knowledge base instead.'))
        return iter([('final',json.dumps({'content':'I opened '+receipt['task']['identifier']+'.'}))])
    fake.chat_stream_events.side_effect = stream
    with TestClient(server.app) as client:
        message = {'input':goal,'request_id':str(uuid4())}
        result=client.post(endpoint,headers=HEADERS,json=message)
        retry=client.post(endpoint,headers=HEADERS,json=message)
    assert result.status_code==retry.status_code==200
    receipt, = result.json()['administration_updates']
    assert retry.json()['administration_updates']==[receipt] and len(native.projects)==1
    assert (receipt['action'], receipt['status']) == ('start_project','created')
    task=receipt['task']
    assert task['description']==goal and task['work_scope']=='project' and task['mission_id']==task['id']
    assert task['status']=='todo' and task['assigneeAgentId']==CEO


def test_direct_project_permission_needs_authenticated_nonce_and_excludes_other_actions(native):
    async def scenario():
        reference='direct-mission-request'
        await context.begin_request(reference,'Research the tools.')
        with pytest.raises(HTTPException) as exc:
            await call('start_project', reference)
        assert exc.value.status_code==403
        await context.begin_request(reference,'Research the tools.',request_key=str(uuid4()))
        for action in ('read','rename_agent','set_system_prompt','start_general_work','schedule_project','set_schedule_status','list_schedules'):
            with pytest.raises(HTTPException) as exc:
                await call(action,reference)
            assert exc.value.status_code==403
    asyncio.run(scenario())
    with TestClient(server.app) as client:
        payload={'input':'Research the tools.','request_id':str(uuid4())}
        assert client.post('/api/chat',headers={**HEADERS,'Origin':'https://elsewhere.test'},json=payload).status_code==403
        assert client.post('/api/chat',json=payload).status_code==401
        assert client.post('/api/chat',headers=HEADERS,json={**payload,'request_id':'x'}).status_code==422
    assert not native.projects


@pytest.mark.parametrize('message,shared', [
    ('Save the comparison in General.',True), ('Save this for the whole team.',True),
    ('Build a methods catalog across all projects.',True), ('Add the table to our shared library.',True),
    ('Document the shared library.',False), ('Save the table in general.',True),
    ('Compare documentation software for the whole team.',False), ('Share the findings with the team.',True),
    ('Explain in general how the service works.',False), ('Research the tools for this project.',False),
    ('Research these tools. Do not put the results in our shared knowledge base.',False)])
def test_shared_scope_must_come_from_owner(message,shared):
    assert admin.shared_work_requested(message) is shared


def test_confirming_earlier_work_uses_prior_context_and_creates_one_project(native):
    async def scenario():
        await grant(message='Yes, do it.')
        with pytest.raises(HTTPException) as exc:
            await call('start_project')
        assert exc.value.status_code==422 and not native.projects
        prior='Compare the three documentation tools discussed above.'
        receipt = await call('start_general_work',assignment_context=prior)
        assert receipt['action']=='start_project'
        assert receipt['task']['description']=='Yes, do it.\n\nPrior conversation context:\n'+prior
        assert await call('start_project',assignment_context='Another summary of the same conversation.')==receipt
    asyncio.run(scenario())


def test_rename_preserves_capability_and_historical_identity(native):
    async def scenario():
        await grant()
        receipt=await call('rename_agent',agent_id=WORKER,name='JARVIS OSINT')
        assert receipt['status']=='saved'
        worker=native.people[1]
        assert worker['name']=='JARVIS OSINT' and worker['metadata']['jarvis']['profile_sha256']=='frozen'
        assert worker['metadata']['jarvis']['name_history'][0]['name']=='JARVIS Research'
        await call('rename_agent',agent_id=WORKER,name='JARVIS OSINT')
        assert len([c for c in native.calls if c[0]=='PATCH'])==1
        for fields in [{'agent_id':FOREIGN,'name':'Other'},{'agent_id':WORKER,'name':'JARVIS'}]:
            with pytest.raises(HTTPException):await call('rename_agent',**fields)
    asyncio.run(scenario())


def test_prompt_edit_is_native_preserves_secret_refs_and_requires_fresh_version(native):
    async def scenario():
        await grant()
        with pytest.raises(HTTPException) as exc:
            await call('set_system_prompt',agent_id=CEO,text='New system prompt',expected_sha256='outdated')
        assert exc.value.status_code==409
        receipt=await call('set_system_prompt',agent_id=CEO,text='New system prompt',expected_sha256=admin.digest('Original CEO prompt'))
        assert receipt['applies']=='next turn'
        ceo=native.people[0]
        assert ceo['adapterConfig']=={'instructions':'New system prompt','apiKey':{'type':'secret_ref','id':'private-reference'}}
        assert ceo['metadata']['jarvis']['inference_configuration']=={'signature':'keep'}
        assert ceo['metadata']['jarvis']['general_context']['text']=='Existing directions'
        assert ceo['metadata']['jarvis']['system_prompt_history'][0]['text']=='Original CEO prompt'
        assert ceo['metadata']['jarvis']['system_prompts']['agent']['text']=='New system prompt'
        assert (await admin.configuration())['agents'][0]['system_prompt']=='New system prompt'
        # Idempotent receipt is allowed if a retry has the same complete replacement.
        await call('set_system_prompt',agent_id=CEO,text='New system prompt',expected_sha256=admin.digest('Original CEO prompt'))
        assert len([c for c in native.calls if c[0]=='PATCH'])==1
    asyncio.run(scenario())


@pytest.mark.parametrize('scope',['direct','administrator'])
def test_saved_chat_prompt_is_loaded_on_next_turn_and_cannot_target_worker(native,scope):
    async def scenario():
        await grant()
        old=await admin.chat_instructions(scope)
        await call('set_system_prompt',agent_id=CEO,scope=scope,text='Be constructive and concise.',expected_sha256=admin.digest(old))
        assert await admin.chat_instructions(scope)=='Be constructive and concise.'
        assert native.people[0]['adapterConfig']['instructions']=='Original CEO prompt'
        with pytest.raises(HTTPException):
            await call('set_system_prompt',agent_id=WORKER,scope=scope,text='wrong target')
    asyncio.run(scenario())


def test_standing_directions_in_admin_accept_ordinary_owner_requests(native):
    async def scenario():
        instruction,_=await grant()
        assert set(instruction['write_authorized_agent_ids'])=={CEO,WORKER}
        saved=await context.tool_call(context.ContextTool(request_id='admin-request-001',action='append',
            agent_id=WORKER,text='Keep a record of which tools work best.'))
        assert saved['general_context']['text']=='Keep a record of which tools work best.'
        assert native.people[1]['metadata']['jarvis']['general_context']['updated_by']=='human_via_administrator'
    asyncio.run(scenario())


def test_project_creation_is_native_ceo_scoped_and_idempotent_across_chat_retries(native):
    async def scenario():
        key=str(uuid4())
        goal='Build reusable source-backed knowledge of public tools.'
        await grant(key=key,message=goal)
        one=await call('start_project',title='Tool knowledge',text=goal)
        assert one['task']['assigneeAgentId']==CEO and one['task']['status']=='todo'
        assert await call('start_project',text=one['task']['description'])==one
        context.finish_request('admin-request-001')
        await grant('admin-request-002',key=key,message=goal)
        two=await call('start_project','admin-request-002',text='Different model wording.')
        assert one['task']['id']==two['task']['id'] and len(native.projects)==1
        await grant('admin-request-003',key=key,message='A different project objective entirely.')
        with pytest.raises(HTTPException):await call('start_project','admin-request-003')
    asyncio.run(scenario())


def test_runtime_callback_requires_admin_grant_and_browser_writes_check_origin(native,monkeypatch):
    monkeypatch.setenv('API_SERVER_KEY','synthetic-runtime')
    runtime={'Authorization':'Bearer synthetic-runtime'}
    with TestClient(server.app) as client:
        assert client.get('/api/admin/config',headers=runtime).status_code==401
        assert client.post('/api/admin/chat',headers=runtime,json={}).status_code==401
        assert client.post('/api/admin/tool',headers=runtime,json={'request_id':'unknown-request','action':'read'}).status_code==403
        assert client.post('/api/admin/tool',headers=HEADERS,json={'request_id':'unknown-request','action':'read'}).status_code==401
        assert client.get('/api/admin/config',headers=HEADERS).status_code==200
        assert client.post('/api/admin/chat',headers={**HEADERS,'Origin':'https://other.example'},json={}).status_code==403


def test_admin_chat_gets_separate_session_prompt_and_grant_without_mutating_on_a_question(native,monkeypatch):
    fake=chat(monkeypatch,[('final',json.dumps({'content':'The agent system prompts are saved in Paperclip.'}))])
    with TestClient(server.app) as client:
        response=client.post('/api/admin/chat',headers=HEADERS,json={'input':'Where are system prompts saved?',
            'request_id':str(uuid4()),'general_context_agent_id':WORKER,'prompt_scope':'agent','conversation':'jarvis-main'})
    assert response.status_code==200 and response.json()['surface']=='administrator'
    fake.get_session_id.assert_called_once_with(admin.CONVERSATION)
    args=fake.chat_stream_events.call_args.args
    assert args[1].endswith('LATEST_ADMIN_MESSAGE:\nWhere are system prompts saved?')
    assert args[3]=='\n\n'.join((admin.DEFAULT_ADMIN_PROMPT,admin.CEO_CHAT_ROLE,admin.CHAT_REPLY_STYLE)) and args[4]==admin.SESSION_KEY
    assert 'General chat' in args[1] and context._requests=={}
    assert 'Existing directions' in args[1] and 'saved preferences' in args[1]
    assert not any(c[0] in ('PATCH','POST') for c in native.calls)


def test_direct_cannot_select_reserved_admin_session_and_gets_its_saved_system_prompt(native,monkeypatch):
    saved = 'Use the terms from our engineering handbook.'
    native.people[0]['metadata']['jarvis']['system_prompts'] = {'direct': {'text': saved}}
    fake=chat(monkeypatch,[('final',json.dumps({'content':'Hello.'}))])
    with TestClient(server.app) as client:
        assert client.post('/api/chat',headers=HEADERS,json={'input':'Hello','conversation':admin.CONVERSATION}).status_code==403
        detail_request = 'Give the full list of engineering terms with their definitions.'
        assert client.post('/api/chat',headers=HEADERS,json={'input':detail_request}).status_code==200
    assert fake.chat_stream_events.call_args.args[1].endswith(detail_request)
    assert fake.chat_stream_events.call_args.args[3]=='\n\n'.join((saved,admin.CEO_CHAT_ROLE,admin.CHAT_REPLY_STYLE))
    assert fake.chat_stream_events.call_args.args[4] is None


def test_history_reads_only_fixed_admin_session_and_strips_prompt_scaffolding(native,monkeypatch):
    fake=Mock();fake._load_state.return_value={admin.CONVERSATION:'api_admin','jarvis-main':'api_direct'}
    fake.base='http://runtime';fake.headers.return_value={}
    monkeypatch.setattr(server,'HERMES',fake)
    get=Mock(return_value=SimpleNamespace(status_code=200,ok=True,json=lambda:{'data':[
        {'role':'user','content':'GENERAL_CONTEXT_TOOL_REQUEST: private\nLATEST_ADMIN_MESSAGE:\nRename Research to OSINT'},
        {'role':'assistant','content':'Checking first','tool_calls':[{}]},
        {'role':'tool','content':'private tool receipt'},
        {'role':'assistant','content':'Renamed JARVIS Research to JARVIS OSINT.'}]}))
    monkeypatch.setattr(server.requests,'get',get)
    with TestClient(server.app) as client:
        result=client.get('/api/admin/history',headers=HEADERS)
    assert result.json()=={'messages':[{'role':'user','text':'Rename Research to OSINT'},
        {'role':'assistant','text':'Renamed JARVIS Research to JARVIS OSINT.'}]}
    assert get.call_args.args==('http://runtime/api/sessions/api_admin/messages',)
    fake.get_session_id.assert_not_called()


def test_chat_client_sends_instructions_and_admin_session_key_without_changing_global_defaults(monkeypatch):
    api=server.HermesAPI({});monkeypatch.setattr(api,'headers',lambda:{'X-Hermes-Session-Key':'direct'})
    monkeypatch.delenv('JARVIS_CHAT_MODEL',raising=False);monkeypatch.delenv('JARVIS_CHAT_PROVIDER',raising=False)
    response=Mock(status_code=200);response.iter_lines.return_value=[]
    post=Mock(return_value=response);monkeypatch.setattr(server.requests,'post',post)
    list(api.chat_stream_events('api_admin','message',5,'Real system prompt',admin.SESSION_KEY))
    assert post.call_args.kwargs['json']=={'input':'message','instructions':'Real system prompt'}
    assert post.call_args.kwargs['headers']['X-Hermes-Session-Key']==admin.SESSION_KEY
    assert api.headers()['X-Hermes-Session-Key']=='direct'


def test_concurrent_initial_chats_retain_both_named_sessions(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(server,'STATE_PATH',tmp_path/'sessions.json')
    api=server.HermesAPI({});monkeypatch.setattr(api,'headers',lambda:{})
    monkeypatch.setattr(api,'find_general_session',lambda name:None)
    def created(url,**kwargs):
        name=kwargs['json']['title']
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'id':'api_'+name})
    post=Mock(side_effect=created);monkeypatch.setattr(server.requests,'post',post)
    names=['direct',admin.CONVERSATION]*10
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(api.get_session_id,names))
    assert result==['api_'+name for name in names]
    assert api._load_state()=={name:'api_'+name for name in names} and post.call_count==2


def test_general_thread_index_idempotent_creation_and_first_message_titles(native):
    first, second = str(uuid4()), str(uuid4())
    with TestClient(server.app) as client:
        url = '/api/admin/conversations'
        initial = client.get(url, headers=HEADERS).json()
        assert initial == {'default_id':'default', 'conversations':[{'id':'default','title':'General chat'}]}
        assert client.get(url).status_code == 401
        assert client.post(url, headers={**HEADERS,'Origin':'https://elsewhere.test'}, json={'id':first}).status_code == 403
        assert client.post(url, headers=HEADERS, json={'id':first}).json() == {'id':first,'title':'New conversation'}
        client.post(url, headers=HEADERS, json={'id':second,'title':'Tools'})
        admin.session_binding(first, 'Compare the tools')
        admin.session_binding(first, 'A later topic')
        admin.session_binding(second, 'A different question')
        assert client.post(url, headers=HEADERS, json={'id':first}).json() == {'id':first,'title':'Compare the tools'}
    with TestClient(server.app) as client:
        rows = client.get(url, headers=HEADERS).json()['conversations']
        assert rows == [{'id':second,'title':'Tools'}, {'id':first,'title':'Compare the tools'}, *initial['conversations']]


def test_general_conversations_isolate_history_and_request_keys(native, monkeypatch):
    first, second = str(uuid4()), str(uuid4())
    threads = [first, second, 'default']
    for thread in (first, second):
        admin.create_conversation(admin.NewConversation(id=thread))
    bindings = [admin.session_binding(i) for i in threads]
    assert len({key for _, key in bindings}) == len(bindings)
    fake = chat(monkeypatch, [])
    state = {name:'api_'+str(i) for i,(name,_) in enumerate(bindings)}
    state['jarvis-main'] = 'api_direct'
    fake._load_state.return_value = state
    fake.get_session_id.side_effect = state.__getitem__
    fake.headers.return_value = {}
    fake.base = 'http://runtime'
    scopes = []
    def stream(sid, *args):
        scopes.append((sid,args[-1],next(iter(context._requests.values())).request_key))
        return iter([('final',json.dumps({'content':'Confirmed.'}))])
    fake.chat_stream_events.side_effect = stream
    def history(url, **kwargs):
        sid = url.split('/')[-2]
        return SimpleNamespace(status_code=200, ok=True, json=lambda:{'data':[
            {'role':'assistant','content':'History for '+sid}]})
    monkeypatch.setattr(server.requests, 'get', history)
    message_id = str(uuid4())
    with TestClient(server.app) as client:
        for index,thread in enumerate(threads+[first]):
            response = client.post('/api/admin/chat', headers=HEADERS,
                json={'input':'Confirm','conversation_id':thread,'request_id':message_id})
            assert response.status_code == 200 and response.json()['conversation_id'] == thread
            sid = state[bindings[index % 3][0]]
            assert scopes[-1][:2] == (sid,bindings[index % 3][1])
            assert client.get('/api/admin/history', headers=HEADERS,
                params={'conversation_id':thread}).json() == {'messages':[{'role':'assistant','text':'History for '+sid}]}
        assert len({key for _,_,key in scopes}) == 3 and scopes[0] == scopes[-1] and scopes[2][2] == message_id
        for name,_ in bindings:
            assert client.post('/api/chat', headers=HEADERS, json={'input':'Test','conversation':name}).status_code == 403
        for thread,status in ((str(uuid4()),404),('jarvis-main',422)):
            assert client.get('/api/admin/history',headers=HEADERS,params={'conversation_id':thread}).status_code == status
            assert client.post('/api/admin/chat',headers=HEADERS,
                json={'input':'Test','request_id':message_id,'conversation_id':thread}).status_code == status


def test_recover_general_binding_and_concurrent_stale_retry(tmp_path,monkeypatch):
    api=server.HermesAPI({})
    monkeypatch.setattr(server,'STATE_PATH',tmp_path/'sessions.json')
    monkeypatch.setattr(api,'headers',lambda:{})
    name=admin.CONVERSATION+':'+str(uuid4())
    remote=Mock(return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'data':[
        {'id':'api_direct','title':'other'}, {'id':'api_recovered','title':name}]}))
    monkeypatch.setattr(server.requests,'get',remote)
    post=Mock();monkeypatch.setattr(server.requests,'post',post)
    assert api.get_session_id(name)=='api_recovered'
    assert api.get_session_id(name,force_new=True,stale_id='api_stale')=='api_recovered'
    assert api._load_state()=={name:'api_recovered'}
    assert remote.call_args.kwargs['params']['title']==name and remote.call_count==1
    post.assert_not_called()
