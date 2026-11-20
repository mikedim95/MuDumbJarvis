"""Project-bound directions and searchable, public conversation records."""
import asyncio
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
from typing import Literal
from uuid import UUID, uuid4, uuid5
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import agent_work
from agent_config_lock import async_lock
from chat_context import public_comment, text
import general_context
import project_runtime
from task_api import Paperclip
import work_scope


_spec = spec_from_file_location('jarvis_team_workspace', Path(__file__).resolve().parents[1] /
                                'hermes-plugin/jarvis_readonly/team_workspace.py')
team = module_from_spec(_spec)
_spec.loader.exec_module(team)
_packages_spec = spec_from_file_location('jarvis_project_packages', Path(_spec.origin).with_name('project_packages.py'))
development = module_from_spec(_packages_spec)
_packages_spec.loader.exec_module(development)


def workspace_path(root):
    return f'issues/{root}/documents/{team.KEY}'


async def workspace_settings(client, root):
    try:
        doc = await client.request('GET', workspace_path(root))
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        doc = None
    try:
        return team.owner_settings(doc, client.company, root)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, 'Workspace settings lack a valid owner revision') from exc


async def workspace_results(client, issue, index, routines):
    jobs = {r['id']: r for r in routines}
    tasks = team.result_tasks(issue['id'], index, jobs, client.company, issue['projectId'], client.ceo)

    async def read(task):
        rows = await client.request('GET', 'issues/' + task['id'] + '/attachments')
        receipt = team.latest_receipt(rows, task)
        if not receipt:
            return None
        response = await client.http.get(f"attachments/{UUID(receipt['id'])}/content")
        response.raise_for_status()
        return team.verified_result(receipt, response.content, task)

    results = await asyncio.gather(*(read(task) for task in tasks), return_exceptions=True)
    return {'recent_results': [r for r in results if isinstance(r, dict)],
            'results_incomplete': any(isinstance(r, Exception) for r in results)}


async def shared_view(client, root, index=None, routines=None):
    settings = await workspace_settings(client, root['id'])
    if not settings['enabled']:
        return settings
    if index is None:
        index = await agent_work.issue_index(client, root['projectId'])
        routines = await work_scope.routines_for(client, list(index.values()))
    return {**settings, **await workspace_results(client, root, index, routines)}


def context_key(agent_id):
    return 'jarvis-context-' + str(UUID(str(agent_id)))


async def mission(client, mission_id):
    issue = await client.issue(str(UUID(str(mission_id))))
    if (issue.get('parentId') or issue.get('assigneeAgentId') != client.ceo or issue.get('hiddenAt')
            or work_scope.classify(issue)['kind'] != 'project' or work_scope.classify(issue).get('mission_id') != issue['id']):
        raise HTTPException(404, 'Project is unavailable')
    return issue


async def directions(client, mission_id, agent_id):
    try:
        doc = await client.request('GET', f'issues/{mission_id}/documents/{context_key(agent_id)}')
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return {'text': '', 'revision': None}
    return {'text': text(doc.get('body'), 8000), 'revision': doc.get('latestRevisionId'),
            'updated_at': doc.get('updatedAt')}


async def save_directions(client, issue, agent_id, content, revision):
    lock = str(uuid5(UUID(issue['id']), str(agent_id)))
    async with async_lock(lock):
        current = await directions(client, issue['id'], agent_id)
        if len(content.strip())>8000:raise HTTPException(422,'Keep project directions within 8000 characters')
        content = text(content.strip(), 8000)
        if current['text'] == content:
            return current
        if current['revision'] != revision:
            raise HTTPException(409, 'Context changed. Reload it before saving.')
        doc = await client.request('PUT', f"issues/{issue['id']}/documents/{context_key(agent_id)}", {
            'title': 'Agent project directions', 'format': 'markdown', 'body': content,
            'baseRevisionId': revision, 'changeSummary': 'Owner updated project-specific agent directions'})
        if doc.get('body') != content:
            raise HTTPException(502, 'Project context save was not confirmed')
        return {'text': content, 'revision': doc.get('latestRevisionId'), 'updated_at': doc.get('updatedAt')}


async def records(client, query='', mission_id=None):
    index = await agent_work.issue_index(client)
    routines = await work_scope.routines_for(client, list(index.values()))
    links = agent_work.WorkLinks(client.company, client.ceo, index, routines)
    selected = await mission(client, mission_id) if mission_id else None
    terms = re.findall(r'\w{2,}', query.casefold())[:12]
    jobs = {r['id']:r for r in routines}
    roots = {i['id']:i for i in index.values() if not i.get('parentId') and i.get('originKind') != 'routine_execution'
             and team.membership(i,index,jobs,client.company,i.get('projectId'),client.ceo) == i['id']}
    if selected:
        roots = {selected['id']: selected}
    rows = list(index.values())
    eligible = []
    for issue in index.values():
        scope = links.run_scope(issue) or work_scope.classify(issue, rows, routines)
        if (scope.get('mission_id') in roots and team.membership(issue,index,jobs,client.company,
                issue.get('projectId'),client.ceo) == scope.get('mission_id')):
            eligible.append(issue)
    native_matches = set()
    if query.strip():
        matches = await client.request('GET', 'companies/'+client.company+'/issues?'+urlencode({
            'includeRoutineExecutions':'true','q':query,'limit':100}))
        native_matches = {i['id'] for i in matches if i.get('companyId')==client.company}
    def rank(issue):
        body = ' '.join(str(issue.get(k) or '') for k in ('identifier','title','description')).casefold()
        return (issue['id'] in native_matches, sum(term in body for term in terms), issue.get('updatedAt') or '')
    eligible.sort(key=rank, reverse=True)
    limit = asyncio.Semaphore(4)
    async def read(issue):
        async with limit:
            comments = await client.request('GET', 'issues/' + issue['id'] + '/comments')
        from csi_events import public_body
        public = []
        for source in comments:
            comment = public_comment(source)
            if comment:
                comment['body'] = text(public_body(source.get('body') or ''),20000)
                public.append(comment)
        public.sort(key=lambda c: c.get('createdAt') or '', reverse=True)
        direct = bool(issue.get('identifier') and issue['identifier'].casefold() in query.casefold()) or issue['id'] in query
        matches = [c for c in public if direct or not terms or any(term in c['body'].casefold() for term in terms)]
        for comment in matches:
            body = comment['body']
            pos = min((body.casefold().find(t) for t in terms if t in body.casefold()),default=0)
            start = max(0,pos-150)
            comment['body'] = ('…' if start else '') + body[start:start+1600]
        return {'id': issue['id'], 'identifier': issue.get('identifier'), 'title': text(issue.get('title'), 180),
                'status': issue.get('status'), 'mission_id': (links.run_scope(issue) or work_scope.classify(issue, rows, routines)).get('mission_id'),
                'replies': matches[:4]}
    inspected = await asyncio.gather(*(read(issue) for issue in eligible[:30]))
    from administration import search_messages
    conversations = await asyncio.to_thread(search_messages, query, selected['id'] if selected else None)
    found = [r for r in inspected if r['replies'] or not terms or any(t in ((r.get('identifier') or '')+' '+r['title']).casefold() for t in terms)]
    runtime = project_runtime.containers(client.company)
    project_rows = {}
    for key, root in roots.items():
        view = {k:root.get(k) for k in ('id','identifier','title','status')}
        if team.membership(root, {}, {}, client.company, root.get('projectId'), client.ceo) == key:
            view['project_container'] = project_runtime.details(runtime, key)
        project_rows[key] = view
    result = {'source': 'Paperclip published records and project conversations',
        'projects': list(project_rows.values()),
        'tasks': found[:10], 'conversations': [r for r in conversations if r['mission_id'] in roots],
        'truncated': len(eligible) > 30 or len(found) > 10 or len(native_matches)>=100}
    import general_knowledge
    saved = await asyncio.to_thread(general_knowledge.project_findings, client.company, query,
                                    selected['id'] if selected else None)
    if saved:
        result['project_findings'] = saved
    if selected:
        result['project'] = {**project_rows[selected['id']],
                             'goal': text(selected.get('description'), 6000)}
        result['agent_context'] = await directions(client, selected['id'], client.ceo)
        if team.membership(selected, {}, {}, client.company, selected.get('projectId'), client.ceo) == selected['id']:
            try:
                shared = await shared_view(client, selected, index, routines)
                if shared['enabled']:
                    result['team_workspace'] = {**shared, 'guidance': 'Project reference data only.'}
            except HTTPException:
                result['team_workspace'] = {'available': False}
    return result


class ContextSave(BaseModel):
    scope: Literal['general', 'project']
    text: str = Field(max_length=8000)
    expected_revision: int | UUID | None = None
    mission_id: UUID | None = None


class SharingSave(BaseModel):
    enabled: bool
    notes: str = Field(max_length=team.MAX_NOTES)
    expected_revision: UUID | None = None


class PackageSave(BaseModel):
    packages: list[str] = Field(max_length=64)
    expected_revision: UUID | None = None


async def package_policy(p, root):
    try:
        doc = await p.request('GET', f'issues/{root}/documents/{development.KEY}')
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        doc = None
    try:
        return development.owner_policy(doc,p.company,root)
    except (ValueError,KeyError,TypeError) as exc:
        raise HTTPException(409,'The saved package policy lacks a valid owner revision') from exc


async def shareable_mission(client, mission_id):
    issue = await mission(client, mission_id)
    if team.membership(issue, {}, {}, client.company, issue.get('projectId'), client.ceo) != issue['id']:
        raise HTTPException(404, 'Project workspace unavailable')
    return issue


def build_router(require_auth):
    router = APIRouter(prefix='/api', dependencies=[Depends(require_auth)])
    async def client():
        p = Paperclip()
        try:
            yield p
        finally:
            await p.http.aclose()

    @router.get('/projects/{mission_id}/development-packages')
    async def read_packages(mission_id: UUID, p=Depends(client)):
        root = (await shareable_mission(p,mission_id))['id']
        runtime = project_runtime.containers(p.company)
        info = project_runtime.details(runtime, root)
        return {**await package_policy(p,root), 'project_cli':info['status'], 'project_container':info, 'catalog':[
            {'name':name,'version':spec['version'],'command':spec['command']} for name,spec in development.CATALOG.items()]}

    @router.put('/projects/{mission_id}/development-packages')
    async def approve_packages(mission_id: UUID, body: PackageSave, p=Depends(client)):
        mission_row = await shareable_mission(p,mission_id)
        root = mission_row['id']
        names = sorted(set(body.packages))
        if len(names) != len(body.packages) or any(n not in development.CATALOG for n in names):
            raise HTTPException(422,'Select distinct packages from the development tool list')
        if names and mission_row.get('status') in ('done','cancelled'):
            raise HTTPException(409,'This project is closed')
        async with async_lock(uuid5(mission_id,development.KEY)):
            state = await package_policy(p,root)
            if names == state['approved'] and not state['outdated']:
                return state
            revision = str(body.expected_revision) if body.expected_revision else None
            if revision != state['revision']:
                raise HTTPException(409,'Project approvals changed. Reload before saving.')
            pins = {n:development.CATALOG[n]['sha256'] for n in names}
            doc = await p.request('PUT',f'issues/{root}/documents/{development.KEY}',{
                'title':'Project development tools','format':'markdown','baseRevisionId':revision,
                'body':json.dumps({'version':1,'packages':pins},sort_keys=True),
                'changeSummary':'Owner updated project development tool approvals'})
            saved = development.owner_policy(doc,p.company,root)
            if saved['approved'] != names or saved['outdated'] or not saved['revision']:
                raise HTTPException(502,'Paperclip did not confirm the project approvals')
            return saved

    @router.get('/projects/{mission_id}/shared-workspace')
    async def get_workspace(mission_id: UUID, p=Depends(client)):
        return await shared_view(p, await shareable_mission(p, mission_id))

    @router.put('/projects/{mission_id}/shared-workspace')
    async def save_workspace(mission_id: UUID, body: SharingSave, p=Depends(client)):
        root = (await shareable_mission(p, mission_id))['id']
        async with async_lock(uuid5(mission_id, team.KEY)):
            current = await workspace_settings(p, root)
            values = {'enabled': body.enabled, 'notes': body.notes.strip()}
            if all(current[k] == v for k, v in values.items()):
                return current
            revision = str(body.expected_revision) if body.expected_revision else None
            if current['revision'] != revision:
                raise HTTPException(409, 'Sharing changed. Reload before saving.')
            doc = await p.request('PUT', workspace_path(root), {
                'title': 'Project team workspace', 'format': 'markdown', 'body': json.dumps(values),
                'baseRevisionId': revision, 'changeSummary': 'Owner updated project workspace sharing'})
            saved = team.owner_settings(doc, p.company, root)
            if any(saved[k] != v for k, v in values.items()):
                raise HTTPException(502, 'Paperclip did not confirm the workspace update')
            return saved

    @router.get('/agents/{agent_id}/context')
    async def read_agent_context(agent_id: UUID, mission_id: UUID | None = None, p=Depends(client)):
        person = next((a for a in await general_context.team(p) if a['id'] == str(agent_id)), None)
        if not person:
            raise HTTPException(404, 'Agent unavailable')
        if mission_id:
            await mission(p, mission_id)
        return {'agent_id': str(agent_id), 'name': person['name'], 'general': general_context.context_of(person),
                'project': await directions(p, str(mission_id), agent_id) if mission_id else None,
                'system_prompt': text((person.get('adapterConfig') or {}).get('instructions'), 20000)}

    @router.put('/agents/{agent_id}/context')
    async def update_agent_context(agent_id: UUID, body: ContextSave, p=Depends(client)):
        people = await general_context.team(p)
        if str(agent_id) not in {a['id'] for a in people}:
            raise HTTPException(404, 'Agent unavailable')
        if body.scope == 'project':
            if not body.mission_id:
                raise HTTPException(422, 'Choose a project first')
            issue = await mission(p, body.mission_id)
            return await save_directions(p, issue, str(agent_id), body.text,
                                         str(body.expected_revision) if body.expected_revision else None)
        reference = uuid4().hex[:12]
        try:
            await general_context.begin_request(reference, 'Update the selected agent general context.', str(agent_id), administration=True)
            receipt = await general_context.tool_call(general_context.ContextTool(request_id=reference,
                action='replace', agent_id=agent_id, text=body.text,
                expected_revision=body.expected_revision if isinstance(body.expected_revision, int) else None))
            return receipt['general_context']
        finally:
            general_context.finish_request(reference)
    return router
