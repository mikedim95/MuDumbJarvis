"""Owner-published reference notes for General chat, stored independently of missions."""
import hashlib
import json
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi import HTTPException

from agent_config_lock import async_lock
from chat_context import text
from csi_events import public_body
import work_scope

_spec = spec_from_file_location('jarvis_publication_notes', Path(__file__).resolve().parents[1] /
                                'hermes-plugin/jarvis_readonly/publication_notes.py')
_notes = module_from_spec(_spec)
_spec.loader.exec_module(_notes)
FIELD, publications, overview = _notes.FIELD, _notes.publications, _notes.overview
_store_spec = spec_from_file_location('jarvis_finding_store', Path(_spec.origin).with_name('finding_store.py'))
_store = module_from_spec(_store_spec)
_store_spec.loader.exec_module(_store)
MAX_BODY = 14000
MAX_LIBRARY = 240000


def project_findings(company, query, mission=None):
    from administration import THREAD_INDEX
    return _store.search(THREAD_INDEX, company, query, mission)


def transfer_clause(message):
    """Identify the owner's affirmative transfer clause; quoted history cannot select a source."""
    for clause in re.split(r'[.!?;\n]|\bbut\b', message, flags=re.I):
        clause = clause.lower().strip()
        if not re.match(r"^(?:jarvis,?\s+)?(?:please\s+)?(?:(?:can|could|would) you\s+|i (?:want|need)(?: you)? to\s+)?"
                        r"(?:take|copy|transfer|promote|import|publish|save|store|put|add|keep|learn|share|reuse)\b"
                        r"|^i want (?:it|this|that|the (?:findings|knowledge|lessons)) (?:as|in|saved|shared|published)\b", clause):
            continue
        if not re.search(r'\b(?:knowledge|findings|lessons|results)\b', clause):
            continue
        if not re.search(r"\b(?:jar-\d+|from (?:it|this|that|the|our|my)|(?:project|mission)(?:['’]s)?"
                         r"|these|those|existing|already|it as|this as|this in|what (?:we|you|the team) learned)\b", clause):
            continue
        destination = re.search(r'\b(?:global knowledge|general chat|general knowledge|shared knowledge|(?:in|into|to) general(?=[ ,]|$)|better in general|across (?:all )?(?:projects|missions))\b', clause)
        if destination and not re.search(r"\b(?:not|never|except|outside|without)\b", clause[:destination.start()]):
            return clause
    return ''


async def save(client, issue, content, evidence):
    if issue.get('companyId') != client.company or issue.get('assigneeAgentId') != client.ceo or issue.get('parentId'):
        raise HTTPException(403, 'Knowledge source is outside the CEO workspace')
    if not content.strip() or len(content) > MAX_BODY:
        raise HTTPException(422, 'Provide a bounded reference note')
    body = text(content.strip(), MAX_BODY)
    key = hashlib.sha256((issue['id'] + '\n' + body).encode()).hexdigest()
    entry = {'source_id':issue['id'], 'identifier':issue['identifier'], 'body':body, 'evidence':evidence}
    async with async_lock(client.ceo):
        path = 'agents/' + client.ceo
        agent = await client.request('GET', path)
        if agent.get('companyId') != client.company or agent.get('id') != client.ceo:
            raise HTTPException(403, 'General knowledge belongs to the configured company')
        existing = publications(agent)
        if key not in existing:
            library = {**existing, key:entry}
            if len(json.dumps(library)) > MAX_LIBRARY:
                raise HTTPException(409, 'General library is full')
            metadata = agent.get('metadata') or {}
            updated = await client.request('PATCH', path, {'metadata':{**metadata, 'jarvis':{
                **(metadata.get('jarvis') or {}), FIELD:library}}})
            if publications(updated).get(key) != entry:
                raise HTTPException(502, 'Paperclip did not confirm the General publication')
    return {'action':'publish_knowledge', 'status':'saved', 'scope':'general',
            'identifier':issue['identifier'], 'publication_id':key}


async def transfer(client, grant, body):
    from agent_work import issue_index
    from work_delivery import INTERNAL
    rows = (await issue_index(client)).values()
    sources = [i for i in rows if i.get('assigneeAgentId') == client.ceo and not i.get('parentId')
               and not i.get('hiddenAt') and i.get('originKind') != 'routine_execution'
               and work_scope.classify(i).get('mission_id') == i['id']]
    labels = set(re.findall(r'\b[A-Z][A-Z0-9]*-\d+\b', transfer_clause(grant.owner_message).upper()))
    if labels:
        sources = [i for i in sources if i['identifier'] in labels]
    elif not grant.mission_id:
        sources = [i for i in sources if not work_scope.closed(i)]
    if grant.mission_id:
        sources = [i for i in sources if i['id'] == grant.mission_id]
    if len(sources) != 1 or (body.mission_id and sources[0]['id'] != str(body.mission_id)):
        raise HTTPException(409, 'Name the source project in the owner message to publish its knowledge in General')
    issue = sources[0]
    if not body.expected_revision:
        # Retries and later conversations can use a previously committed publication.
        agent = await client.request('GET', 'agents/'+client.ceo)
        if agent.get('id') == client.ceo and agent.get('companyId') == client.company:
            matches = [k for k,v in publications(agent).items() if v['source_id'] == issue['id']]
            if matches:
                return {'action':'publish_knowledge','status':'available','scope':'general',
                        'identifier':issue['identifier'],'publication_id':matches[-1],
                        'existing_publications':len(matches), 'detail':'Previously saved material only. Check newer findings separately.'}
        raise HTTPException(422, 'Use search_projects for this mission. Pass a published CEO reply ID as expected_revision and a verbatim reusable paragraph as text to start_general_work. Repeat for other findings.')
    replies = await client.request('GET', 'issues/'+issue['id']+'/comments')
    source = next((c for c in replies if c['id'] == str(body.expected_revision)
                   and c.get('authorAgentId') == client.ceo and not INTERNAL.match(c.get('body') or '')
                   and c.get('issueId',issue['id']) == issue['id']), None)
    quote = body.text.strip()
    if not source or not quote or quote not in public_body(source['body']):
        raise HTTPException(422, 'Supply an exact excerpt of the selected project’s published CEO reply')
    return await save(client, issue, quote, [{'comment_id':source['id']}])
