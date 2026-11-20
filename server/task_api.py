"""Authenticated Paperclip REST integration. No local task database or scheduler."""
import asyncio
import os
import socket
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid5

import httpx
import work_scope
import agent_work
import blocker_delivery
from task_brief import job_brief
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field


def notify_project_change():
    # The operator reads native Paperclip state. This datagram only shortens the periodic reconcile delay.
    endpoint = os.environ.get('JARVIS_PROJECT_LIFECYCLE_SOCKET')
    if not endpoint:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.sendto(b'projects', endpoint)
    except OSError:
        pass


class TaskSubmission(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    request_id: UUID
    agent_id: UUID | None = None
    objective: bool = False


class TaskMessage(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    request_id: UUID
    interaction_id: UUID | None = None
    reply_mode: Literal['feedback'] | None = None


class Paperclip:
    def __init__(self):
        self.company = os.environ.get('PAPERCLIP_COMPANY_ID', '')
        self.project = os.environ.get('PAPERCLIP_PROJECT_ID', '')
        self.agent = os.environ.get('PAPERCLIP_AGENT_ID', '')
        self.ceo = os.environ.get('PAPERCLIP_CEO_AGENT_ID', '')
        self.workforce = os.environ.get('JARVIS_CEO_WORKFORCE') == 'true'
        key = os.environ.get('PAPERCLIP_API_KEY', '')
        if not all((self.company, self.project, self.agent, key)):
            raise HTTPException(503, 'Paperclip integration is not configured')
        self.http = httpx.AsyncClient(base_url=os.environ.get('PAPERCLIP_URL', 'http://paperclip:3100') + '/api/',
            headers={'Authorization': 'Bearer ' + key}, timeout=httpx.Timeout(20, connect=3))

    async def request(self, method, path, body=None):
        # Native issue idempotency makes a POST retry safe, but leave uncertain
        # submissions to the caller to retry with the SAME request_id.
        for attempt in range(2 if method == 'GET' else 1):
            try:
                response = await self.http.request(method, path, json=body)
                if response.status_code >= 500 and method == 'GET' and attempt == 0:
                    await asyncio.sleep(.2)
                    continue
                if response.status_code == 404:
                    raise HTTPException(404, 'Paperclip resource not found')
                if response.status_code == 409:
                    raise HTTPException(409, 'Paperclip reports a task conflict')
                if not response.is_success:
                    raise HTTPException(502, f'Paperclip request failed (HTTP {response.status_code})')
                return response.json()
            except (httpx.RequestError, ValueError):
                if method == 'GET' and attempt == 0:
                    await asyncio.sleep(.2)
                    continue
                raise HTTPException(502, 'Cannot reach Paperclip. Retry with the same submission ID.') from None

    async def agents(self):
        return await self.request('GET', f'companies/{self.company}/agents')

    async def issue(self, issue_id):
        issue = await self.request('GET', 'issues/' + str(issue_id))
        if issue['companyId'] != self.company or (not getattr(self, 'workforce', False) and issue.get('projectId') != self.project):
            raise HTTPException(404, 'Task not found in General Operations')
        if getattr(self, 'workforce', False) and issue.get('projectId'):
            self.project = issue['projectId']
        return issue


def project_issue(issue,scope=None):
    result={key: issue.get(key) for key in ('id', 'identifier', 'title', 'description', 'status', 'projectId',
        'assigneeAgentId', 'parentId', 'createdAt', 'updatedAt', 'completedAt', 'executionRunId', 'unblockDescriptor', 'hiddenAt','originKind','originId')}
    resolved=scope or work_scope.classify(issue)
    result.update(work_scope=resolved['kind'],mission_id=resolved.get('mission_id'))
    result['description']=work_scope.clean_description(result.get('description'))
    result['recovery'] = agent_work.recovery_view(issue)
    if issue.get('status') == 'blocked' or issue.get('executionBlocker'):
        result['state'] = agent_work.engagement(issue)[0]
    return result


def build_router(require_auth):
    router = APIRouter(prefix='/api', dependencies=[Depends(require_auth)])

    async def client():
        upstream = Paperclip()
        try:
            yield upstream
        finally:
            await upstream.http.aclose()

    from document_permissions import routes as permission_routes
    permission_routes(router, client)

    @router.get('/agents')
    async def agents(p: Paperclip = Depends(client)):
        return {'ceo_id': p.ceo or None,
            'agents': [{k: a.get(k) for k in ('id', 'name', 'title', 'role', 'reportsTo', 'adapterType', 'status',
                'lifecycleState', 'lifecycleError', 'capabilities')} for a in await p.agents()]}

    @router.get('/agents/work')
    async def staff_assignments(mission_id: UUID | None = None, agent_id: UUID | None = None,
                                p: Paperclip = Depends(client)):
        if mission_id:
            from project_workspace import mission
            await mission(p, mission_id)
        return await agent_work.overview(p, str(mission_id) if mission_id else None,
                                         str(agent_id) if agent_id else None)

    @router.get('/agents/{agent_id}/portrait/{asset_id}')
    async def staff_portrait(agent_id: UUID, asset_id: UUID, p: Paperclip = Depends(client)):
        from general_context import team
        person = next((a for a in await team(p) if a['id'] == str(agent_id)), None)
        if not person or agent_work.custom_asset(person) != str(asset_id):
            raise HTTPException(404, 'Agent portrait not found')
        # Paperclip re-encodes custom agent avatars as a single PNG, at most 512 x 512.
        try:
            async with p.http.stream('GET', f'assets/{asset_id}/content') as upstream:
                if upstream.status_code == 404:
                    raise HTTPException(404, 'Agent portrait not found')
                if upstream.status_code != 200 or upstream.headers.get('content-type', '').split(';')[0] != 'image/png':
                    raise HTTPException(502, 'The portrait could not be loaded')
                payload = bytearray()
                async for chunk in upstream.aiter_bytes():
                    if len(payload) + len(chunk) > 2 * 1024 * 1024:
                        raise HTTPException(502, 'Invalid agent portrait')
                    payload.extend(chunk)
        except httpx.RequestError:
            raise HTTPException(502, 'The portrait could not be loaded') from None
        if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
            raise HTTPException(502, 'Invalid agent portrait')
        return Response(content=bytes(payload), media_type='image/png',
                        headers={'Cache-Control': 'private, max-age=300', 'X-Content-Type-Options':'nosniff'})

    async def project_visibility(task_id, p, hidden):
        issue = await p.issue(task_id)
        if issue.get('parentId') or not p.ceo or issue.get('assigneeAgentId') != p.ceo:
            raise HTTPException(409, 'Only CEO-owned projects can be removed from this list')
        if bool(issue.get('hiddenAt')) != hidden:
            stamp = datetime.now(timezone.utc).isoformat().replace('+00:00','Z') if hidden else None
            issue = await p.request('PATCH', f'issues/{task_id}', {'hiddenAt': stamp})
        if issue.get('id') != str(task_id) or bool(issue.get('hiddenAt')) != hidden:
            raise HTTPException(502, 'Paperclip did not confirm project visibility')
        if hidden:
            import cron_api
            await cron_api.pause_mission(p,str(task_id))
        notify_project_change()
        return {'id': str(task_id), 'hidden_at': issue.get('hiddenAt'), 'removed': hidden,
            'history_preserved': True, 'task': project_issue(issue)}

    @router.delete('/projects/{task_id}')
    async def remove_project(task_id: UUID, p: Paperclip = Depends(client)):
        return await project_visibility(task_id, p, True)

    @router.post('/projects/{task_id}/restore')
    async def restore_project(task_id: UUID, p: Paperclip = Depends(client)):
        return await project_visibility(task_id, p, False)

    @router.post('/tasks', status_code=201)
    async def create_task(body: TaskSubmission, p: Paperclip = Depends(client)):
        text = body.input.strip()
        if not text:
            raise HTTPException(422, 'Task input cannot be blank')
        if body.objective:
            if not p.ceo:
                raise HTTPException(503, 'CEO objective integration is not configured')
            if body.agent_id and str(body.agent_id) != p.ceo:
                raise HTTPException(409, 'Objectives must be assigned to the configured CEO')
            agent_id = p.ceo
        else:
            agent_id = str(body.agent_id) if body.agent_id else p.agent
        agent = next((a for a in await p.agents() if a['id'] == agent_id), None)
        if not agent or agent.get('lifecycleState') != 'ready':
            raise HTTPException(409, 'Selected agent is not ready')
        issue = await p.request('POST', f'companies/{p.company}/issues', {
            'title': text[:120], 'description': text, 'status': 'todo', 'priority': 'medium',
            'projectId': p.project, 'assigneeAgentId': agent_id,
            'workspaceSelection': {'kind': 'task_directory'},
            'idempotencyKey': 'jarvis:' + str(body.request_id), 'allowDuplicate': True})
        if issue.get('description') != text or issue.get('assigneeAgentId') != agent_id:
            raise HTTPException(409, 'Submission ID already belongs to another task')
        if agent_id == p.ceo:
            notify_project_change()
        return project_issue(issue)

    @router.get('/tasks')
    async def history(p: Paperclip = Depends(client)):
        query = '' if getattr(p, 'workforce', False) else f'?projectId={p.project}'
        issues = await p.request('GET', f'companies/{p.company}/issues' + query)
        routines=await work_scope.routines_for(p,issues)
        return {'tasks': sorted([project_issue(i,work_scope.classify(i,issues,routines)) for i in issues
            if i.get('companyId') == p.company and (getattr(p, 'workforce', False) or i.get('projectId') == p.project)],
            key=lambda i: i.get('createdAt') or '', reverse=True)}

    @router.post('/tasks/{task_id}/messages')
    async def message(task_id: UUID, body: TaskMessage, p: Paperclip = Depends(client)):
        return await post_followup(p, task_id, body)

    @router.get('/tasks/{task_id}')
    async def task(task_id: UUID, p: Paperclip = Depends(client)):
        issue = await p.issue(task_id)
        # Parentage and scheduled-run membership both come from Paperclip. Exclude
        # other companies/projects before any request for comments or execution history.
        issues, routines = await asyncio.gather(
            agent_work.issue_index(p, p.project),
            p.request('GET', f'companies/{p.company}/routines'))
        current = issues.get(issue['id'], {})
        issue = {**current, **issue}
        if 'activeRun' in current:
            issue['activeRun'] = current['activeRun']
        issues[issue['id']] = issue
        rows = list(issues.values())
        routines = [job for job in routines if job.get('companyId') == p.company and job.get('projectId') == p.project]
        links = agent_work.WorkLinks(p.company, p.ceo, issues, routines)
        root_scope = links.run_scope(issue) or work_scope.classify(issue, rows, routines)
        by_parent = defaultdict(list)
        scheduled = []
        for row in sorted(rows, key=lambda record: (record.get('createdAt') or '', record['id'])):
            if row['id'] == issue['id']:
                continue
            if row.get('parentId'):
                by_parent[row['parentId']].append(row)
            elif root_scope['mission_id'] == issue['id']:
                scope = links.run_scope(row)
                if scope and scope['kind'] == 'project' and scope['mission_id'] == issue['id']:
                    scheduled.append(row)

        limit = asyncio.Semaphore(4)

        async def details(item, scope):
            async with limit:
                if item['id'] != issue['id'] and item.get('status') in ('todo','blocked') and not item.get('executionRunId') and not item.get('activeRun'):
                    native = await p.issue(item['id'])
                    if (native.get('companyId'),native.get('projectId'),native.get('parentId')) != (
                            item.get('companyId'),item.get('projectId'),item.get('parentId')):
                        raise HTTPException(409,'The assignment changed scope; refresh the project')
                    item = {**item,**native}
                comments, runs = await asyncio.gather(
                    p.request('GET', f"issues/{item['id']}/comments"),
                    p.request('GET', f"issues/{item['id']}/runs"))
            result = project_issue(item, scope)
            result['comments'] = [{k: c.get(k) for k in ('id', 'body', 'createdAt', 'authorAgentId', 'authorUserId')} for c in comments]
            result['runs'] = [{k: r.get(k) for k in ('runId', 'status', 'startedAt', 'finishedAt', 'errorCode', 'error')} for r in runs]
            result['children'] = []
            result['state'], result['active_agent_id'] = agent_work.engagement(item, runs)
            association = links.for_issue(item)
            result.update(cron_job=association['cron_job'], run_issue=association['run_issue'])
            return result

        # A linked schedule is part of the mission, but preserves its real (null)
        # parentId. De-duplicate the reachable tree before fetching per-issue data.
        visits = [(issue, root_scope, None, None)]
        seen = {issue['id']}
        for item, parent_scope, _, _ in visits:
            branches = [('children', by_parent[item['id']])]
            if item['id'] == issue['id']:
                branches.append(('scheduled_runs', scheduled))
            for relation, children in branches:
                for child in children:
                    if child['id'] in seen:
                        continue
                    scope = links.run_scope(child) or parent_scope
                    if (scope['kind'], scope['mission_id']) != (root_scope['kind'], root_scope['mission_id']):
                        continue
                    visits.append((child, scope, item['id'], relation))
                    seen.add(child['id'])

        results = await asyncio.gather(*(details(item, scope) for item, scope, _, _ in visits))
        by_id = {row['id']: row for row in results}
        root = results[0]
        package_progress = {}
        if getattr(p, 'workforce', False) and not issue.get('parentId') and issue.get('assigneeAgentId') == p.ceo and any(
                item.get('status') == 'blocked' for item in rows if item.get('parentId') == issue['id']):
            decisions = await blocker_delivery.owner_decisions(p, issue['id'])
            await blocker_delivery.load_package_receipts(p, root, by_id, decisions)
            package_progress = blocker_delivery.package_blockers(root, by_id, decisions)
            root['owner_question'] = next(({'id': d['id'], 'question': d['question'],
                    **({'kind':'package_review'} if d.get('package') else {})} for d in decisions if d['status'] == 'pending'), None)
        root['scheduled_runs'] = []
        root['schedules'] = links.by_mission.get(root['id'], [])
        for row, (_, _, parent, relation) in zip(results[1:], visits[1:]):
            by_id[parent][relation].append(row)
        for row in results:
            row['brief'] = job_brief(row)
            if row['id'] in package_progress and row['state'] == 'blocked' and not row.get('recovery'):
                row['brief'].update(package_progress[row['id']])
        if root.get('owner_question'):
            root['brief']['progress'] = 'Jarvis needs your decision. ' + root['owner_question']['question']
        return root

    from task_monitor import add_routes
    add_routes(router, Paperclip)
    return router


async def post_followup(p, task_id, body):
    issue = await p.issue(task_id)
    if not getattr(p, 'workforce', False):
        raise HTTPException(409, 'CEO conversation mode is not enabled')
    if issue.get('parentId') or issue.get('assigneeAgentId') != p.ceo:
        raise HTTPException(409, 'Messages must address a CEO-owned top-level objective')
    if issue.get('status') == 'cancelled':
        raise HTTPException(409, 'Cancelled objectives cannot be resumed through chat')
    holds = await p.request('GET', f'issues/{task_id}/tree-holds?status=active')
    if isinstance(holds, dict):
        holds = holds.get('holds', [])
    if holds:
        raise HTTPException(409, 'This objective has a native stop hold; chat cannot release it')
    text = body.input.strip()
    if not text:
        raise HTTPException(422, 'Message cannot be blank')
    if body.reply_mode and not body.interaction_id:
        raise HTTPException(422, 'Select the approval request to send feedback.')
    if body.interaction_id:
        decisions = await blocker_delivery.owner_decisions(p, issue['id'])
        decision = next((d for d in decisions if d['id'] == str(body.interaction_id)), None)
        if not decision:
            raise HTTPException(409, 'This question does not belong to the selected CEO objective.')
        if body.reply_mode and not decision.get('package'):
            raise HTTPException(409, 'This question takes a direct reply.')
        if decision.get('package'):
            choices = {'yes': ('accept', 'accepted'), 'approve': ('accept', 'accepted'),
                       'no': ('reject', 'rejected'), 'decline': ('reject', 'rejected')}
            choice = None if body.reply_mode else choices.get(text.casefold())
            if decision['status'] == 'pending':
                child = await p.issue(decision['child_id'])
                if (issue.get('hiddenAt') or issue.get('status') == 'done' or child.get('hiddenAt')
                        or child.get('status') != 'blocked' or child.get('parentId') != issue['id']
                        or child.get('companyId') != issue['companyId'] or child.get('projectId') != issue.get('projectId')
                        or child.get('assigneeAgentId') != decision['agent_id']):
                    raise HTTPException(409, 'The package request no longer matches this assignment.')
            if not choice:
                # Older HUDs used the question ID for every reply. Give each
                # distinct legacy note a stable comment ID for safe retries.
                nonce = str(uuid5(body.interaction_id, text) if body.request_id == body.interaction_id else body.request_id)
                note = f"Owner feedback on {decision['package']} request {decision['id']} (decision pending)\n{text}"
                path = f'issues/{task_id}/comments'
                if decision['status'] == 'pending':
                    comment = await p.request('POST', path, {'clientRequestId':nonce, 'body':note, 'resume':False, 'reopen':False})
                else:
                    comment = next((c for c in await p.request('GET', path) if c.get('clientRequestId') == nonce), {})
                if not (comment.get('id') and comment.get('body') == note and comment.get('issueId') == issue['id']
                        and comment.get('authorUserId') and not comment.get('authorAgentId')):
                    raise HTTPException(409, 'Feedback was not confirmed for this request.')
                return {'task':project_issue(issue), 'interaction_id':decision['id'], 'feedback_id':comment['id']}
            action, expected = choice
            if decision['status'] != 'pending':
                if decision['answer'] != expected:
                    raise HTTPException(409, 'This package request already has a different disposition.')
            else:
                try:
                    await p.request('POST', f'issues/{task_id}/interactions/{body.interaction_id}/{action}', {})
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                saved = await blocker_delivery.owner_decisions(p, issue['id'])
                if not any(d['id'] == decision['id'] and d['answer'] == expected for d in saved):
                    raise HTTPException(409, 'Paperclip did not confirm your package decision.')
            return {'task': project_issue(issue), 'interaction_id': decision['id'], 'decision':expected}
        if decision['status'] == 'pending':
            try:
                await p.request('POST', f'issues/{task_id}/interactions/{body.interaction_id}/respond',
                    {'answers': [{'questionId': 'child-' + decision['child_id'], 'optionIds': [], 'otherText': text}]})
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                decisions = await blocker_delivery.owner_decisions(p, issue['id'])
                if not any(d['id'] == decision['id'] and d['status'] == 'answered' and d['answer'] == text for d in decisions):
                    raise
        elif decision['status'] != 'answered' or decision['answer'] != text:
            raise HTTPException(409, 'This question has already been closed or answered differently.')
        return {'task': project_issue(await p.issue(task_id)), 'interaction_id': decision['id']}
    marker = '[JARVIS USER MESSAGE request_id=' + str(body.request_id) + ']\n'
    comment = await p.request('POST', f'issues/{task_id}/comments', {
        'body': marker + text, 'clientRequestId': str(body.request_id),
        'reopen': True, 'resume': True})
    if comment.get('body') != marker + text:
        raise HTTPException(409, 'Message request ID already belongs to different text')
    return {'task': project_issue(await p.issue(task_id)), 'comment_id': comment['id']}
