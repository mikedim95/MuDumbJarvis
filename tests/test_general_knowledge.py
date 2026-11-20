import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_project_workspace import board, FIRST, SECOND, CEO, HEADERS, server
from test_direct_chat_failures import chat
import administration as admin
import general_knowledge as knowledge
import general_context as context


@pytest.mark.parametrize('message,expected', [
    ('there is 1 active project. take all the knowledge from it to become better in general', True),
    ('I opened JAR-91. But i want it as a general chat global knowledge, not another scoped project', True),
    ('Can you save the lessons from JAR-84 in General knowledge?', True),
    ('Do not share JAR-84 findings in General chat.', False),
    ('Did you save existing findings in General knowledge?', False),
    ('Copy the project findings locally, not in General knowledge.', False),
    ('Build reusable team knowledge about documented tools.', False),
    ('Research a new project about global knowledge management.', False),
    ('Tell me how to publish the findings from this project in General knowledge.',False),
])
def test_transfer_intent(message, expected):
    assert bool(knowledge.transfer_clause(message)) is expected


def test_transfer_reaches_new_general_conversation_without_creating_a_task(board,monkeypatch):
    async def scenario():
        await context.begin_request('general-publish-123','Save the findings from JAR-1 in General knowledge.',
            administration=True,request_key=str(uuid4()))
        reply = board.comments[FIRST][0]
        def call(**fields):
            return admin.tool_call(admin.AdminTool(request_id='general-publish-123',action='start_project', **fields))
        with pytest.raises(HTTPException):
            await call(mission_id=SECOND, expected_revision=board.comments[SECOND][0]['id'], text='Unrelated private reply.')
        with pytest.raises(HTTPException):
            await call(mission_id=FIRST, expected_revision=reply['id'],text='invented')
        saved=await call(mission_id=FIRST,expected_revision=reply['id'],text=reply['body'])
        assert saved['action']=='publish_knowledge'
        assert await call(mission_id=FIRST,expected_revision=reply['id'],text=reply['body'])==saved
        assert (await call(mission_id=FIRST))['status']=='available'
        assert len(board.writes)==1 and board.writes[0][1]=='agents/'+CEO
        assert board.people[0]['metadata']['jarvis']['general_context']['text']=='Be concise.'
        return reply['body']
    fact=asyncio.run(scenario())
    # Archiving the source cannot remove the independent General publication.
    board.issues[FIRST]['hiddenAt']='2026-11-19'
    fake=chat(monkeypatch,[])
    async def snapshot(*_):return {'source':'Paperclip','selected_tasks':[]}
    monkeypatch.setattr(server,'paperclip_chat_snapshot',snapshot)
    def stream(sid,prompt,timeout,instructions,session_key):
        facts=json.loads(prompt.split('<PAPERCLIP_SNAPSHOT>\n')[1].split('\n</PAPERCLIP_SNAPSHOT>')[0])
        assert facts['general_knowledge']['excerpts']==[{'source':'JAR-1','text':fact}]
        assert 'Unrelated private reply' not in json.dumps(facts)
        return iter([('final',json.dumps({'content':'Received the documented finding.'}))])
    fake.chat_stream_events.side_effect=stream
    with TestClient(server.app) as c:
        thread=c.post('/api/admin/conversations',headers=HEADERS,json={'id':str(uuid4())}).json()['id']
        data=c.post('/api/admin/chat',headers=HEADERS,json={'input':'Which API?', 'request_id':str(uuid4()),'conversation_id':thread})
        assert data.status_code==200 and data.json()['text']=='Received the documented finding.'


def test_implicit_source_requires_one_active_mission_and_ignores_quoted_issue_ids(board):
    async def scenario():
        board.issues[FIRST]['status']=board.issues[SECOND]['status']='in_progress'
        message='Earlier JAR-2 was discussed. Take all the knowledge from it to become better in general.'
        await context.begin_request('general-publish-234',message,administration=True,request_key=str(uuid4()))
        reply=board.comments[FIRST][0]
        args=admin.AdminTool(request_id='general-publish-234',action='start_general_work',
            expected_revision=reply['id'],text=reply['body'])
        with pytest.raises(HTTPException) as error:await admin.tool_call(args)
        assert error.value.status_code==409 and not board.writes
        board.issues[SECOND]['status']='done'
        assert (await admin.tool_call(args))['identifier']=='JAR-1'
    asyncio.run(scenario())


def test_project_bound_transfer_uses_only_its_source_and_cannot_save_as_directions(board):
    async def scenario():
        await context.begin_request('bound-publish-123','Save the findings from this project in General knowledge.',
            administration=True,mission_id=FIRST,request_key=str(uuid4()))
        with pytest.raises(HTTPException):
            await context.tool_call(context.ContextTool(request_id='bound-publish-123',action='append',agent_id=CEO,text='Make this an instruction'))
        async def use(mission,reply):
            return await admin.tool_call(admin.AdminTool(request_id='bound-publish-123',action='continue_project',
                mission_id=mission,expected_revision=reply['id'],text=reply['body']))
        with pytest.raises(HTTPException):await use(SECOND,board.comments[SECOND][0])
        assert (await use(FIRST,board.comments[FIRST][0]))['scope']=='general'
        assert len(board.writes)==1
    asyncio.run(scenario())
