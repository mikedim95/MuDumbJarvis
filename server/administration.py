"""Scoped owner administration: actual prompts, staff names and CEO project requests."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from uuid import UUID
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

import general_context
from agent_config_lock import async_lock as configuration_lock
from task_api import Paperclip, project_issue
import work_scope

CONVERSATION = 'jarvis-administrator-v1'
SESSION_KEY = 'jarvis:administrator:chat'
DEFAULT_THREAD = 'default'
THREAD_INDEX = Path(__file__).resolve().parent / 'logs' / 'general_conversations.sqlite3'
CHAT_REPLY_STYLE = ('Lead with the answer or confirmed outcome and stop once the request is answered. '
    'One sentence is enough for routine status or confirmations. Include only requested details and '
    'facts needed to understand or act on the result, including any material blocker. '
    'Match the requested format and give full detail when asked. Skip process narration, restatements and closing offers.')
CEO_CHAT_ROLE = ('You are JARVIS, the CEO. Address the owner in the first person and take responsibility for the work. '
    'Interpret the latest owner message in conversation context. When the owner assigns a new task with a deliverable, '
    'call jarvis_administrator with start_project and the active request_id, even when phrased politely as a question. '
    'For example, “can you research these tools?” assigns research. “What tools do we already use?” asks for an answer. '
    'The owner need not say “project”. Start one mission for the assignment. Answer factual, capability and status '
    'questions directly. Keep instructions for an existing mission with that mission, standing directions in general_context, '
    'and explicit shared-knowledge work and recurrence in General. Only act on the latest owner instruction. '
    'When it refers back to an earlier decision, supply the relevant earlier goal in assignment_context. '
    'Report a project opening only after a successful creation receipt. Speak as its CEO (“I opened JAR-…”) '
    'and only claim delegation, execution or completion when native records confirm it.')
DEFAULT_DIRECT_PROMPT = ('You are JARVIS, the CEO. Answer the user naturally. '
    'Use current facts and actual tool results. Treat legitimate requests constructively; do not invent '
    'authorization requirements or give unsolicited lectures. Direct Chat can read Paperclip details and save '
    'explicit standing directions, and open a project for a new assignment. Staff/system-prompt changes belong in the '
    'General area; explain that briefly when needed. Do not claim unavailable actions.')
DEFAULT_ADMIN_PROMPT = ('You are JARVIS, the CEO, in the owner\'s General workspace for durable team direction and shared knowledge. '
    'Act on clear requests through your available tools: inspect/edit system prompts, rename existing staff, '
    'save standing directions, open projects and schedule recurring work using the existing team. '
    'Use start_project for new assignments. Use start_general_work when the owner explicitly wants shared '
    'team knowledge across projects. For recurring shared work use schedule_project with work_scope=general. '
    'Mission schedules require work_scope=project and mission_id; mission findings remain local. '
    'Saving preferences does not initiate work. '
    'Be helpful and action-oriented. '
    'Infer ordinary conversational intent instead of requiring exact phrases or an additional mode switch. '
    'Do not add blanket restrictions to benign tool/method research or invent reasons to refuse. '
    'Ask only for material missing details. Distinguish ordinary questions from instructions to change settings. '
    'Use jarvis_administrator and general_context with the current request_id. Inspect current prompts before '
    'replacing them. Use confirmed native receipts before claiming a change. Do not expose credentials, '
    'claim unsupported tool access, invent worker progress, or alter execution permissions. '
    'Hiring and sensitive-action approvals continue through existing Paperclip processes.')
_locks = general_context._locks


class NewConversation(BaseModel):
    id: UUID
    title: str = Field(default='', max_length=120)


def _threads():
    # Only the sidebar lives here. Transcripts remain in their own Hermes sessions.
    THREAD_INDEX.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(THREAD_INDEX)
    db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT)')
    return db


def conversations():
    with closing(_threads()) as db:
        rows = db.execute('SELECT id, title FROM conversations ORDER BY rowid DESC').fetchall()
    return {'default_id': DEFAULT_THREAD,
            'conversations': [{'id': i, 'title': t or 'New conversation'} for i, t in rows] +
                             [{'id': DEFAULT_THREAD, 'title': 'General chat'}]}


def create_conversation(body):
    thread_id = str(body.id)
    title = ' '.join(body.title.split()) or None
    with closing(_threads()) as db, db:
        db.execute('INSERT INTO conversations (id,title) VALUES (?,?) ON CONFLICT(id) DO NOTHING', (thread_id, title))
        title = db.execute('SELECT title FROM conversations WHERE id=?', (thread_id,)).fetchone()[0]
    return {'id': thread_id, 'title': title or 'New conversation'}


def session_binding(thread_id, first_message=''):
    if thread_id == DEFAULT_THREAD:
        return CONVERSATION, SESSION_KEY
    try:
        thread_id = str(UUID(str(thread_id)))
    except ValueError:
        raise HTTPException(422, 'Invalid General conversation ID')
    with closing(_threads()) as db, db:
        if not db.execute('SELECT 1 FROM conversations WHERE id=?', (thread_id,)).fetchone():
            raise HTTPException(404, 'General conversation not found')
        if first_message:
            db.execute('UPDATE conversations SET title=? WHERE id=? AND title IS NULL',
                       (' '.join(first_message.split())[:80], thread_id))
    return CONVERSATION + ':' + thread_id, SESSION_KEY + ':' + thread_id


def is_general_session(name):
    return isinstance(name, str) and (name == CONVERSATION or name.startswith(CONVERSATION + ':'))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def effective_prompt(agent, scope):
    if scope == 'agent':
        return str((agent.get('adapterConfig') or {}).get('instructions') or '')
    saved = (((agent.get('metadata') or {}).get('jarvis') or {}).get('system_prompts') or {}).get(scope) or {}
    return saved.get('text') or (DEFAULT_ADMIN_PROMPT if scope == 'administrator' else DEFAULT_DIRECT_PROMPT)


async def configuration():
    client = Paperclip()
    try:
        people = await general_context.team(client)
        ceo = next(a for a in people if a['id']==client.ceo)
        return {'ceo_id':client.ceo,'agents':[{
            **{key:a.get(key) for key in ('id','name','role','title')},
            'scope':'agent','system_prompt':effective_prompt(a,'agent'),
            'prompt_sha256':digest(effective_prompt(a,'agent')),
            'general_context':general_context.context_of(a)} for a in people],
            'chat_prompts':[{'scope':scope,'agent_id':client.ceo,'name':'Chat' if scope=='direct' else 'General chat',
                'system_prompt':effective_prompt(ceo,scope),'prompt_sha256':digest(effective_prompt(ceo,scope))}
                for scope in ('direct','administrator')], 'source':'Paperclip agent configuration'}
    finally:
        await client.http.aclose()


async def chat_instructions(scope):
    client = None
    try:
        client=Paperclip()
        agent=await client.request('GET','agents/'+client.ceo)
        return effective_prompt(agent,scope)
    except Exception:
        return DEFAULT_ADMIN_PROMPT if scope=='administrator' else DEFAULT_DIRECT_PROMPT
    finally:
        if client is not None:await client.http.aclose()


class AdminTool(BaseModel):
    request_id: str = Field(min_length=12,max_length=64)
    action: Literal['read','rename_agent','set_system_prompt','start_project','start_general_work','schedule_project','set_schedule_status','list_schedules']
    agent_id: UUID | None = None
    scope: Literal['agent','direct','administrator'] = 'agent'
    name: str = Field(default='',max_length=80)
    text: str = Field(default='',max_length=20000)
    assignment_context: str = Field(default='',max_length=3000)
    expected_sha256: str | None = None
    title: str = Field(default='',max_length=120)
    cron_expression:str=Field(default='0 9 * * *',max_length=100)
    timezone:str=Field(default='Europe/Athens',max_length=100)
    project_id:UUID|None=None
    work_scope:Literal['general','project']='general'
    mission_id:UUID|None=None
    job_id:UUID|None=None
    status:Literal['active','paused','archived']='paused'


# The model interprets the conversational intent. A shared-work write also needs
# evidence of shared scope in the owner message, independent of model-authored text.
SHARED_SCOPE = re.compile(
    r"\b(?:in(?:to)?|to|under|build|curate|update|expand|maintain|populate|grow)\s+"
    r"(?:(?:the|a|our|your|reusable|new)\s+)*(?:shared|general|team(?:[- ]wide|['’]s)?)\s+"
    r"(?:knowledge(?:\s+base)?|library|catalog(?:ue)?|playbook|research index|wiki)\b"
    r"|\b(?:under|in(?:to)?|to|as)\s+(?:the\s+)?(?:general\s+(?:area|workspace|library|knowledge|work)|(?-i:General))\b"
    r"|\b(?:across|between)\s+(?:(?:our|all|future|different|multiple)\s+)*(?:projects|missions)\b"
    r"|\bfor\s+(?:all|future|every)\s+(?:projects?|missions?)\b"
    r"|\b(?:share|save|store|record|archive|publish|document|keep|make available)\b[^.!?;\n]{0,160}?"
    r"\b(?:for|with|to)\s+(?:(?:the|our)\s+(?:(?:whole|entire)\s+)?team|"
    r"(?:everyone|everybody)\s+on\s+(?:the|our)\s+team|all\s+(?:the\s+)?agents)\b"
    r"|\b(?:save|record|add|store|put|keep)\b[^.!?;\n]{0,160}?\b(?:under|in(?:to)?|to)\s+general\b(?=[.!?;\n]|$)", re.I)


def shared_work_requested(message):
    for match in SHARED_SCOPE.finditer(message):
        clause = re.split(r'[.!?;,\n]', message[:match.start()])[-1]
        if not re.search(r"\b(?:not|never|don['’]t|avoid|without|exclude|except)\b", clause, re.I):
            return True
    return False


async def tool_call(body):
    grant=general_context._requests.get(body.request_id)
    if not grant or grant.expires < time.monotonic():
        raise HTTPException(403,'An active owner chat request is required')
    if not grant.administration and not (body.action == 'start_project' and grant.request_key):
        raise HTTPException(403,'This action requires General chat')
    if body.action=='read':return await configuration()
    client=Paperclip()
    try:
        people=await general_context.team(client)
        if body.action=='list_schedules':
            import cron_api
            rows=await client.request('GET','companies/'+client.company+'/routines')
            projects=await client.request('GET','companies/'+client.company+'/projects')
            return {'jobs':[cron_api.projection(r) for r in rows if r.get('companyId')==client.company and r.get('assigneeAgentId')==client.ceo],
                'projects':[{k:p.get(k) for k in ('id','name')} for p in projects if p.get('companyId')==client.company]}
        if body.action in ('schedule_project','set_schedule_status'):
            import cron_api
            if body.action=='schedule_project':
                job=await cron_api.save(client,cron_api.Job(title=body.title,description=body.text,
                    cron_expression=body.cron_expression,timezone=body.timezone,project_id=body.project_id,
                    work_scope=body.work_scope,mission_id=body.mission_id),body.job_id)
            else:
                if not body.job_id:raise HTTPException(422,'Provide the native cron job ID')
                current=await cron_api.scoped(client,body.job_id)
                scope=work_scope.routine_scope(current)
                if body.status=='active' and scope['kind']=='project':await cron_api.mission(client,scope['mission_id'],active=True)
                await client.request('PATCH','routines/'+str(body.job_id),{'status':body.status})
                job=cron_api.projection(await cron_api.scoped(client,body.job_id))
            receipt={'action':body.action,'status':'saved','job':job,'source':'Paperclip native routine'}
            grant.admin_receipts.append(receipt);return receipt
        if body.action in ('start_project','start_general_work'):
            action = body.action
            if action == 'start_general_work' and not shared_work_requested(grant.owner_message):
                action = 'start_project'
            owner_goal = grant.owner_message.strip()
            if work_scope.clean_description(owner_goal) != owner_goal:
                owner_goal = 'Owner assignment:\n' + owner_goal
            context_heading = '\n\nPrior conversation context:\n'
            prior_context = body.assignment_context.strip()
            if not prior_context and re.fullmatch(
                    r'(?:yes[, ]+)?(?:please\s+)?(?:do (?:it|that)|go ahead|proceed|start it|yes)[!. ]*', owner_goal, re.I):
                raise HTTPException(422,'Include the prior goal the owner approved in assignment_context')
            objective = owner_goal + (context_heading + prior_context if prior_context else '')
            if not owner_goal or len(objective) > 20000:
                raise HTTPException(422,'Provide a goal and context within 20000 characters')
            ceo=next((a for a in people if a['id']==client.ceo),None)
            if not ceo or ceo.get('lifecycleState')!='ready':raise HTTPException(409,'The CEO is not ready')
            request_key = ('jarvis-admin:' if grant.administration else 'jarvis-chat:') + grant.request_key
            async with _locks.setdefault(request_key,asyncio.Lock()):
                existing=next((r for r in grant.admin_receipts if r['action'] in ('start_project','start_general_work')),None)
                if existing:
                    if existing['action'] != action:raise HTTPException(409,'This message already started different work; use a new message')
                    return existing
                description=work_scope.description(objective,'general') if action=='start_general_work' else objective
                task=await client.request('POST','companies/'+client.company+'/issues',{
                    'title':body.title.strip() or objective[:120],'description':description,'status':'todo','priority':'medium',
                    'projectId':client.project,'assigneeAgentId':client.ceo,'workspaceSelection':{'kind':'task_directory'},
                    'idempotencyKey':request_key,'allowDuplicate':True})
                saved = project_issue(task)
                if (not (saved['description'] == owner_goal or saved['description'].startswith(owner_goal + context_heading))
                        or saved['work_scope'] != ('general' if action=='start_general_work' else 'project')
                        or task.get('assigneeAgentId')!=client.ceo):
                    raise HTTPException(409,'The saved request belongs to a different project')
                receipt={'action':action,'status':'created','task':saved,'source':'Paperclip CEO objective'}
                grant.admin_receipts.append(receipt);return receipt
        target=str(body.agent_id or grant.selected_agent or client.ceo)
        agent=next((a for a in people if a['id']==target),None)
        if not agent:raise HTTPException(404,'Agent is outside the Jarvis team')
        async with configuration_lock(target):
            agent=await client.request('GET','agents/'+target)
            if agent.get('companyId')!=client.company or not (agent['id']==client.ceo or agent.get('reportsTo')==client.ceo):
                raise HTTPException(404,'Agent is outside the Jarvis team')
            metadata=agent.get('metadata') or {};jarvis=metadata.get('jarvis') or {}
            stamp=datetime.now(timezone.utc).isoformat()
            if body.action=='rename_agent':
                name=body.name.strip()
                if not name or any(ord(c)<32 for c in name):raise HTTPException(422,'Provide a plain agent name')
                if any(a['id']!=target and a.get('name','').casefold()==name.casefold() for a in people):
                    raise HTTPException(409,'Another team member already has that name')
                old=agent['name']
                if old!=name:
                    history=list(jarvis.get('name_history') or [])
                    history.append({'name':old,'replaced_at':stamp,'request_key':grant.request_key})
                    agent=await client.request('PATCH','agents/'+target,{'name':name,
                        'metadata':{**metadata,'jarvis':{**jarvis,'name_history':history[-20:]}}})
                if agent.get('name')!=name:raise HTTPException(502,'Native agent rename was not confirmed')
                receipt={'action':body.action,'status':'saved','agent_id':target,'previous_name':old,'name':name,
                    'source':'Paperclip agent record'}
            else:
                scope=body.scope
                if scope!='agent' and target!=client.ceo:raise HTTPException(409,'Chat prompts belong to Jarvis')
                prompt=body.text.strip()
                if not prompt:raise HTTPException(422,'Provide the system prompt text')
                current=effective_prompt(agent,scope)
                if digest(current)!=body.expected_sha256 and current!=prompt:
                    raise HTTPException(409,'Read the current prompt before replacing it')
                saved_prompt=(jarvis.get('system_prompts') or {}).get(scope) or {}
                if current!=prompt or saved_prompt.get('text')!=prompt:
                    history=list(jarvis.get('system_prompt_history') or [])
                    if current!=prompt:
                        history.append({'scope':scope,'text':current,'sha256':digest(current),'replaced_at':stamp})
                    newmeta={**metadata,'jarvis':{**jarvis,'system_prompt_history':history[-10:]}}
                    patch={'metadata':newmeta}
                    prompts={**(jarvis.get('system_prompts') or {}),scope:{'text':prompt,'sha256':digest(prompt),'updated_at':stamp}}
                    newmeta['jarvis']['system_prompts']=prompts
                    if scope=='agent':
                        patch['adapterConfig']={**(agent.get('adapterConfig') or {}),'instructions':prompt}
                    agent=await client.request('PATCH','agents/'+target,patch)
                if effective_prompt(agent,scope)!=prompt:raise HTTPException(502,'Native prompt save was not confirmed')
                receipt={'action':body.action,'status':'saved','agent_id':target,'name':agent['name'],'scope':scope,
                    'prompt_sha256':digest(prompt),'characters':len(prompt),'applies':'next turn','source':'Paperclip agent configuration'}
            grant.admin_receipts.append(receipt);return receipt
    finally:
        await client.http.aclose()
