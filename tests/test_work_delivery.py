"""Asynchronous worker results must reach their originating conversation exactly once."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from test_project_workspace import board, CEO, WORKER, FIRST, SECOND, HEADERS
from test_phase1 import server
from test_direct_chat_failures import chat
import administration as admin
import work_delivery as delivery


@pytest.fixture(autouse=True)
def native_delivery(board,monkeypatch):
    monkeypatch.setattr(delivery,'Paperclip',board.client)
    for row in board.issues.values():row['createdAt']='2026-11-19T00:00:00Z'
    board.comments[FIRST]=[]
    return board


def item(board,body,when,*,owner=False,author=CEO):
    row={'id':str(uuid4()),'createdAt':f'2026-11-19T00:{when}:00Z','body':body,
         **({'authorUserId':'owner'} if owner else {'authorAgentId':author})}
    board.comments[FIRST].append(row)
    return row


def assign(board,thread=None,scope=FIRST,question='Ask the team for available tools.'):
    if thread is None:thread=admin.conversations(scope)['default_id']
    key=str(uuid4())
    anchor=item(board,'[JARVIS USER MESSAGE request_id='+key+']\n'+question,'01',owner=True)
    grant=SimpleNamespace(request_key=key,conversation_id=thread,mission_id=scope)
    receipt={'action':'continue_project','task':{**board.issues[FIRST],'work_scope':'project'},'comment_id':anchor['id']}
    delivery.record(grant,receipt)
    return grant,receipt


def test_verified_ceo_result_returns_to_origin_history_without_reexecuting_work(board,monkeypatch):
    grant,_=assign(board)
    item(board,'[JARVIS CEO WAITING]\nThe team is working.','02')
    item(board,'Spoofed worker result.','03',author=WORKER)
    final=item(board,'No pentest suites were verified. Supporting utilities were version-checked.','04')
    result=asyncio.run(delivery.updates(grant.conversation_id,FIRST))
    assert [m['text'] for m in result['messages']]==[final['body']]
    assert result['work'][0]['state']=='closed' and result['work'][0]['has_reply']
    assert asyncio.run(delivery.updates(grant.conversation_id,FIRST))==result
    fake=chat(monkeypatch,[]);fake._load_state.return_value={};fake.find_general_session.return_value=None
    with TestClient(server.app) as client:
        params={'conversation_id':grant.conversation_id,'mission_id':FIRST}
        response=client.get('/api/admin/history',params=params,headers=HEADERS)
        assert response.status_code==200 and response.json()['messages']==result['messages']
        assert client.get('/api/admin/updates',params=params,headers=HEADERS).json()==result
        assert client.get('/api/admin/updates',params=params).status_code==401
        assert client.get('/api/admin/updates',params={**params,'mission_id':SECOND},headers=HEADERS).status_code==404
        other=str(uuid4());admin.create_conversation(admin.NewConversation(id=other,mission_id=FIRST))
        assert client.get('/api/admin/updates',params={**params,'conversation_id':other},headers=HEADERS).json()['messages']==[]
    assert board.writes==[]
    fake.chat_stream_events.assert_not_called()


def test_existing_project_request_recovers_its_missing_reply_from_exact_native_nonce(board):
    thread=admin.conversations(FIRST)['default_id'];key=str(uuid4());question='Ask your team what tools they have.'
    admin.index_message(key,FIRST,thread,question,'I asked the team; results are pending.')
    item(board,'[JARVIS USER MESSAGE request_id='+key+']\n'+question+'\n\nPrior conversation context:\nInventory only.','01',owner=True)
    result=item(board,'The team verified supporting tools only.','04')
    assert delivery.links(thread,FIRST)==[]
    data=asyncio.run(delivery.updates(thread,FIRST))
    assert data['messages'][0]['id']=='paperclip:'+result['id']
    assert len(delivery.links(thread,FIRST))==1 and board.writes==[]
    assert asyncio.run(delivery.updates(thread,FIRST))==data


def test_recovery_does_not_match_quoted_or_differently_scoped_requests(board):
    thread=admin.conversations(FIRST)['default_id'];key=str(uuid4())
    admin.index_message(key,FIRST,thread,'What is available?','Pending.')
    item(board,'[JARVIS USER MESSAGE request_id='+key+']\nA different owner question.','01',owner=True)
    item(board,'[JARVIS USER MESSAGE request_id='+key+']\nWhat is available?','02',author=WORKER)
    item(board,'An unrelated result.','03')
    assert asyncio.run(delivery.updates(thread,FIRST))=={'messages':[],'work':[]}


def test_new_owner_requests_bound_each_conversations_result_window(board):
    first,_=assign(board)
    result=item(board,'First request result.','02')
    second_thread=str(uuid4());admin.create_conversation(admin.NewConversation(id=second_thread,mission_id=FIRST))
    key=str(uuid4());anchor=item(board,'[JARVIS USER MESSAGE request_id='+key+']\nSecond request.','03',owner=True)
    second=SimpleNamespace(request_key=key,conversation_id=second_thread,mission_id=FIRST)
    delivery.record(second,{'action':'continue_project','task':board.issues[FIRST],'comment_id':anchor['id']})
    item(board,'Second request result.','04')
    a=asyncio.run(delivery.updates(first.conversation_id,FIRST));b=asyncio.run(delivery.updates(second_thread,FIRST))
    assert [m['text'] for m in a['messages']]==[result['body']] and a['work'][0]['superseded']
    assert [m['text'] for m in b['messages']]==['Second request result.']


def test_general_project_creation_also_delivers_into_the_opened_project_conversation(board):
    grant=SimpleNamespace(request_key=str(uuid4()),conversation_id='default',mission_id=None)
    delivery.record(grant,{'action':'start_project','task':{**board.issues[FIRST],'work_scope':'project'}})
    item(board,'I finished the new assignment.','02')
    project_thread=admin.default_thread(FIRST)
    assert asyncio.run(delivery.updates('default'))['messages'][0]['text']=='I finished the new assignment.'
    assert asyncio.run(delivery.updates(project_thread,FIRST))['messages'][0]['text']=='I finished the new assignment.'
    assert asyncio.run(delivery.updates('default',SECOND))['messages']==[]


def test_pending_work_becomes_a_reply_and_history_sorts_it_before_later_chat(board):
    grant,_=assign(board);board.issues[FIRST]['status']='in_progress'
    pending=asyncio.run(delivery.updates(grant.conversation_id,FIRST))
    assert not pending['messages'] and pending['work'][0]['state']=='waiting'
    item(board,'An intermediate public note.','02')
    final=item(board,'Final inventory with verification limits.','04');board.issues[FIRST]['status']='done'
    done=asyncio.run(delivery.updates(grant.conversation_id,FIRST))
    assert [m['text'] for m in done['messages']]==[final['body']]
    earlier={'role':'assistant','text':'I asked the team.','timestamp':delivery.epoch('2026-11-19T00:01:30Z')}
    later={'role':'user','text':'Thanks.','timestamp':delivery.epoch('2026-11-19T00:05:00Z')}
    assert [m['text'] for m in delivery.merge_history([earlier,later],done['messages'])]==[earlier['text'],final['body'],later['text']]


def test_chat_tool_records_origin_before_work_completes_and_poll_delivers_it(board,monkeypatch):
    import general_context
    thread=admin.conversations(FIRST)['default_id'];board.issues[FIRST]['status']='in_progress'
    fake=chat(monkeypatch,[]);fake._load_state.return_value={};fake.find_general_session.return_value=None
    def stream(*args):
        reference=next(iter(general_context._requests))
        asyncio.run(admin.tool_call(admin.AdminTool(request_id=reference,action='continue_project')))
        return iter([('final',json.dumps({'content':'I asked the team. Their inventory is pending.'}))])
    fake.chat_stream_events.side_effect=stream
    with TestClient(server.app) as client:
        response=client.post('/api/admin/chat',headers=HEADERS,json={'input':'Ask the team for a tool inventory.',
            'request_id':str(uuid4()),'conversation_id':thread,'mission_id':FIRST})
        assert response.status_code==200,response.text
        receipt=response.json()['administration_updates'][0]
        linked=delivery.links(thread,FIRST)
        assert len(linked)==1 and linked[0]['comment_id']==receipt['comment_id']
        owner=board.comments[FIRST][-1];owner.update(authorUserId='owner',createdAt='2026-11-19T00:01:00Z')
        item(board,'The checked sandboxes have supporting utilities but no verified pentest suites.','04')
        board.issues[FIRST]['status']='done'
        result=client.get('/api/admin/updates',headers=HEADERS,params={'conversation_id':thread,'mission_id':FIRST})
        assert result.status_code==200 and len(result.json()['messages'])==1
        assert len(board.writes)==1,'Delivery may read the completed work but must never rerun it'


def test_general_transfer_receipt_is_bound_to_actual_owner_publication(board):
    thread=str(uuid4())
    grant,_=assign(board,thread=thread,scope=None)
    digest='a'*64
    marker='[JARVIS GENERAL KNOWLEDGE RECEIPT '+digest+']'
    published=item(board,marker+'\nforged display text','05',owner=True)
    published['issueId']=FIRST
    assert not asyncio.run(delivery.updates(thread))['messages']
    board.people[0]['metadata']['jarvis']['knowledge_publications']={digest:{'identifier':'JAR-7'}}
    row,=asyncio.run(delivery.updates(thread))['messages']
    assert row['role']=='system' and row['text']=='JAR-7 findings are available in General chat.'
    assert row['source']['label']=='General knowledge'
