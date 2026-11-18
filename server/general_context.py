"""Human-directed per-agent notes in native Paperclip metadata, never task state."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import time
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from task_api import Paperclip
from chat_context import text as safe_text
from agent_config_lock import async_lock as configuration_lock

LIMIT = 8000
_requests = {}
_locks = {}


def context_of(agent):
    metadata = agent.get('metadata') or {}
    notes = (metadata.get('jarvis') or {}).get('general_context') or {}
    return {'text': safe_text(notes.get('text', ''), LIMIT), 'revision': int(notes.get('revision', 0)),
        'updated_at': notes.get('updated_at')}


async def team(client):
    agents = await client.agents()
    return [agent for agent in agents if agent.get('companyId') == client.company and
        (agent.get('id') == client.ceo or agent.get('reportsTo') == client.ceo) and
        agent.get('status') not in ('terminated', 'pending_approval')]


def project_agent(agent):
    return {**{key: agent.get(key) for key in ('id', 'name', 'role')}, 'general_context': context_of(agent)}


async def read_contexts():
    client = Paperclip()
    try:
        return {'agents': [project_agent(agent) for agent in await team(client)], 'ceo_id': client.ceo,
            'source': 'Paperclip agent general context', 'context_limit': LIMIT}
    finally:
        await client.http.aclose()


def explicit_update(message):
    if re.match(r'^\s*(?:how|what|where|why|when)\b', message, re.I):
        return False
    if re.match(r'^\s*(?:Jarvis,?\s+)?(?:please\s+)?(?:do not|don[’\']t|never)\s+(?:save|update|remember|change|store|delete|remove)\b',message,re.I):
        return False
    if re.search(r'\b(?:explain|describe|show me how|tell me how)\b.{0,45}\b(?:save|update|remember|change)\b',message,re.I):
        return False
    subject = re.search(r'\b(?:general|global|persistent)\s+(?:context|directions?|instructions?|guidelines?|preferences?)\b', message, re.I)
    remember = re.search(r'\bremember\b', message, re.I) and re.search(r'\b(?:from now on|always|in future|for future)\b', message, re.I)
    action = re.search(r'\b(?:update|save|remember|set|add|append|replace|clear|delete|remove|store|change)\b', message, re.I)
    return bool(action and (subject or remember))


def authorized_targets(message, agents, ceo_id, selected=None):
    if not explicit_update(message):
        return set()
    wanted = set()
    workers = [agent for agent in agents if agent['id'] != ceo_id]
    if re.search(r'\b(?:all|every|each)\b.{0,35}\b(?:agents?|workers?|staff)\b', message, re.I):
        wanted.update(agent['id'] for agent in workers)
    aliases = {'researcher': 'research', 'engineer': 'software', 'devops': 'systems', 'security': 'security'}
    for agent in workers:
        name = re.sub(r'^JARVIS\s+', '', agent.get('name', ''), flags=re.I)
        choices = [name, aliases.get(agent.get('role'), '')]
        if any(value and re.search(r'\b' + re.escape(value) + r'\b', message, re.I) for value in choices):
            wanted.add(agent['id'])
    if re.search(r'\b(?:yourself|your own|your general|ceo)\b|\bJarvis[’\']s\b', message, re.I):
        wanted.add(ceo_id)
    if not wanted:
        if selected and selected not in {a['id'] for a in agents}:
            return set()
        wanted.add(selected if selected in {a['id'] for a in agents} else ceo_id)
    return wanted


@dataclass
class ContextRequest:
    allowed: set
    can_replace: bool
    can_clear: bool
    expires: float
    receipts: list = field(default_factory=list)
    administration: bool = False
    admin_receipts: list = field(default_factory=list)
    request_key: str = ''
    owner_message: str = ''
    selected_agent: str | None = None
    selected_scope: str = 'agent'


async def begin_request(reference, message, selected=None, *, administration=False, request_key='', selected_scope='agent'):
    for key in list(_requests):
        if _requests[key].expires < time.monotonic():
            _requests.pop(key, None)
    try:
        data = await read_contexts()
    except Exception:
        return None, None
    allowed = {agent['id'] for agent in data['agents']} if administration else authorized_targets(message, data['agents'], data['ceo_id'], selected)
    grant = ContextRequest(allowed, administration or bool(re.search(r'\b(?:replace|rewrite|reset|set|change)\b',message,re.I)),
        administration or bool(re.search(r'\b(?:clear|delete|remove)\b',message,re.I)), time.monotonic()+920,
        administration=administration,request_key=request_key,owner_message=message,selected_agent=selected,selected_scope=selected_scope)
    _requests[reference] = grant
    instruction = {'request_id': reference, 'write_authorized_agent_ids': sorted(allowed),
        'agents': [{'id': a['id'], 'name': a['name'], 'revision': a['general_context']['revision']} for a in data['agents']],
        'allowed_actions': ['read']+(['append'] if allowed else [])+
            (['replace'] if allowed and (grant.can_replace or grant.can_clear) else []),
        'instruction': 'Use general_context to read saved directions. Only if the latest user explicitly asks, '
            'save general directions for the authorized agents using this request_id. Prefer append. '
            'Use replace only for an explicit rewrite or clearing request, with expected_revision from a fresh read. '
            'Never claim notes were saved without an actual successful tool result. These notes are preferences, '
            'not permissions, project goals, task assignments or changes to safety/tool policy.'}
    if administration:
        instruction['instruction'] = ('You are in the authenticated General chat. Use general_context to act on '
            'clearly requested standing directions for the team, without demanding magic phrases such as "general context". '
            'Infer ordinary conversational intent; distinguish a real instruction from a question or quoted suggestion. '
            'Append by default, read before replacing, and report only actual confirmed saves. '
            'Use jarvis_administrator for system prompts, renaming staff and opening projects you lead as CEO. '
            'Administrative changes do not alter runtime tool permissions.')
    elif request_key:
        instruction['project_tool'] = 'Use jarvis_administrator with start_project for a new owner assignment.'
    own = next((a['general_context'] for a in data['agents'] if a['id']==data['ceo_id']), {})
    return instruction, own


def finish_request(reference):
    grant = _requests.pop(reference, None)
    return grant.receipts if grant else []


def receipts(reference):
    grant = _requests.get(reference)
    return list(grant.receipts) if grant else []


class ContextTool(BaseModel):
    request_id: str = Field(min_length=12, max_length=64)
    action: Literal['read', 'append', 'replace']
    agent_id: UUID | None = None
    text: str = Field(default='', max_length=LIMIT)
    expected_revision: int | None = Field(default=None, ge=0)


async def tool_call(body):
    grant = _requests.get(body.request_id)
    if not grant or grant.expires < time.monotonic():
        raise HTTPException(403, 'General-context request is no longer active')
    if body.action == 'read':
        data = await read_contexts()
        if body.agent_id:
            data['agents'] = [a for a in data['agents'] if a['id']==str(body.agent_id)]
            if not data['agents']:
                raise HTTPException(404, 'Agent is outside the Jarvis team')
        return data
    target = str(body.agent_id or '')
    if target not in grant.allowed:
        raise HTTPException(403, 'The latest user message did not authorize this general-context update')
    if body.action=='replace' and not (grant.can_replace or grant.can_clear):
        raise HTTPException(403, 'Replacing existing directions was not explicitly requested')
    if not body.text.strip() and (body.action!='replace' or not grant.can_clear):
        raise HTTPException(422, 'Provide the general directions to save')
    async with configuration_lock(target):
        if any(r['agent_id']==target for r in grant.receipts):
            return next(r for r in grant.receipts if r['agent_id']==target)
        client = Paperclip()
        try:
            agent = next((a for a in await team(client) if a['id']==target), None)
            if not agent:
                raise HTTPException(404, 'Agent is outside the Jarvis team')
            current = context_of(agent)
            if body.action=='replace' and body.expected_revision != current['revision']:
                raise HTTPException(409, 'Read the current general context before replacing it')
            new_text = body.text.strip()
            if body.action=='append' and new_text in current['text'].split('\n\n'):
                receipt = {'status':'unchanged','agent_id':target,'name':agent['name'],'action':body.action,
                    'general_context':current,'source':'Paperclip agent metadata'}
                grant.receipts.append(receipt)
                return receipt
            if body.action=='append' and current['text']:
                new_text = current['text']+'\n\n'+new_text
            if len(new_text)>LIMIT:
                raise HTTPException(422, 'General context is full; request a concise explicit replacement')
            new_text = safe_text(new_text,LIMIT)
            metadata = agent.get('metadata') or {}; jarvis = metadata.get('jarvis') or {}
            notes = {'text': new_text, 'revision': current['revision']+1,
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'updated_by': 'human_via_administrator' if grant.administration else 'human_via_direct_chat',
                'request_id': body.request_id}
            history = list(jarvis.get('general_context_history') or [])
            if current['revision']:
                history.append(current)
            updated = await client.request('PATCH','agents/'+target,{'metadata': {**metadata,'jarvis':{
                **jarvis,'general_context': notes,'general_context_history':history[-5:]}}})
            if context_of(updated)['text']!=new_text or context_of(updated)['revision']!=notes['revision']:
                raise HTTPException(502, 'Paperclip did not confirm the saved general context')
            receipt = {'status':'saved','agent_id':target,'name':agent['name'], 'action':body.action,
                'general_context':context_of(updated),'source':'Paperclip agent metadata'}
            grant.receipts.append(receipt)
            return receipt
        finally:
            await client.http.aclose()
