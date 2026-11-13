"""Authenticated Paperclip REST integration. No local task database or scheduler."""
import asyncio
import os
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


class TaskSubmission(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    request_id: UUID
    agent_id: UUID | None = None
    objective: bool = False


class Paperclip:
    def __init__(self):
        self.company = os.environ.get('PAPERCLIP_COMPANY_ID', '')
        self.project = os.environ.get('PAPERCLIP_PROJECT_ID', '')
        self.agent = os.environ.get('PAPERCLIP_AGENT_ID', '')
        self.ceo = os.environ.get('PAPERCLIP_CEO_AGENT_ID', '')
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
        if issue['companyId'] != self.company or issue.get('projectId') != self.project:
            raise HTTPException(404, 'Task not found in General Operations')
        return issue


def project_issue(issue):
    return {key: issue.get(key) for key in ('id', 'identifier', 'title', 'description', 'status',
        'assigneeAgentId', 'parentId', 'createdAt', 'updatedAt', 'completedAt', 'executionRunId', 'unblockDescriptor')}


def build_router(require_auth):
    router = APIRouter(prefix='/api', dependencies=[Depends(require_auth)])

    async def client():
        upstream = Paperclip()
        try:
            yield upstream
        finally:
            await upstream.http.aclose()

    @router.get('/agents')
    async def agents(p: Paperclip = Depends(client)):
        return {'ceo_id': p.ceo or None,
            'agents': [{k: a.get(k) for k in ('id', 'name', 'title', 'role', 'reportsTo', 'adapterType', 'status',
                'lifecycleState', 'lifecycleError', 'capabilities')} for a in await p.agents()]}

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
        return project_issue(issue)

    @router.get('/tasks')
    async def history(p: Paperclip = Depends(client)):
        issues = await p.request('GET', f'companies/{p.company}/issues?projectId={p.project}')
        return {'tasks': sorted([project_issue(i) for i in issues
            if i.get('companyId') == p.company and i.get('projectId') == p.project],
            key=lambda i: i.get('createdAt') or '', reverse=True)}

    @router.get('/tasks/{task_id}')
    async def task(task_id: UUID, p: Paperclip = Depends(client)):
        issue = await p.issue(task_id)
        async def details(item):
            comments, runs = await asyncio.gather(
                p.request('GET', f"issues/{item['id']}/comments"),
                p.request('GET', f"issues/{item['id']}/runs"))
            result = project_issue(item)
            result['comments'] = [{k: c.get(k) for k in ('id', 'body', 'createdAt', 'authorAgentId', 'authorUserId')} for c in comments]
            result['runs'] = [{k: r.get(k) for k in ('runId', 'status', 'startedAt', 'finishedAt', 'errorCode', 'error')} for r in runs]
            return result

        # Paperclip owns the hierarchy. Filter every child before reading its
        # comments/runs; never infer ownership from a supplied parentId alone.
        issues = await p.request('GET', f'companies/{p.company}/issues?projectId={p.project}')
        children = [item for item in issues if item.get('parentId') == str(task_id)
            and item.get('companyId') == p.company and item.get('projectId') == p.project]
        limit = asyncio.Semaphore(4)

        async def child_details(item):
            async with limit:
                return await details(item)

        result = await details(issue)
        result['children'] = await asyncio.gather(*(child_details(item) for item in children))
        return result

    return router
