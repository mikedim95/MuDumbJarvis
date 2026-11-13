"""Read projections and authenticated controls over native Paperclip records.

Only host CPU sampling lives in memory. Tasks, approvals, dependencies, logs and
artifacts are always read from Paperclip; this module never schedules work.
"""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field


class RetryRequest(BaseModel):
    request_id: UUID
    observed_run_id: UUID | None


class Decision(BaseModel):
    decision: str = Field(pattern='^(approve|reject)$')
    note: str = Field(min_length=1, max_length=2000)


class Cancellation(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


def catalog():
    return json.loads((Path(__file__).resolve().parents[1] /
        'hermes-plugin/jarvis_readonly/profiles.json').read_text())


def capability(agent):
    meta = ((agent.get('metadata') or {}).get('jarvis') or {})
    item = catalog()['profiles'].get(meta.get('profile'), {})
    return {**{k: meta.get(k) for k in ('profile', 'model', 'limits', 'workspace', 'profile_sha256', 'provisioned')},
        'tools': item.get('tools', []), 'skills': item.get('skills', []),
        'authority': item.get('authority'), 'dormancy': meta.get('dormancy')}


def redact(value):
    """Defense in depth for logs/text; authority-bearing configs are omitted."""
    secrets = [v for k, v in os.environ.items() if len(v) >= 12 and
        any(word in k.upper() for word in ('TOKEN', 'PASSWORD', 'SECRET', 'API_KEY', 'SERVER_KEY', 'PROOF_KEY'))]
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}', r'\1[REDACTED]', value)
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {k: '[REDACTED]' if re.search(r'(?i)(password|secret|token|api.?key|authorization)', k)
                else redact(v) for k, v in value.items()}
    return value


def evidence(comment, issue, runs, company):
    """Authenticate a runtime receipt before labelling its tool data verified."""
    master = os.environ.get('JARVIS_EXECUTION_PROOF_KEY', '')
    found = []
    for line in (comment.get('body') or '').splitlines():
        prefixes = ('JARVIS_EXECUTION_EVIDENCE=', 'JARVIS_TOOL_EVENT=')
        if not line.startswith(prefixes):
            continue
        try:
            proof = json.loads(line.split('=', 1)[1])
            unsigned = {k: v for k, v in proof.items() if k != 'signature'}
            agent, run_id = proof.get('agent_id'), proof.get('paperclip_run_id')
            session = f"paperclip:company:{company}:agent:{agent}:issue:{issue['id']}"
            if proof.get('version') == 3:
                key = hmac.new(master.encode(), ('jarvis-employee-proof-v3:' + str(agent)).encode(), hashlib.sha256).hexdigest()
                scoped = proof.get('company_id') == company and proof.get('issue_id') == issue['id']
            elif proof.get('version') == 2:
                key, scoped = master, True
            else:
                continue
            expected = hmac.new(key.encode(), json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
            run = next((r for r in runs if r.get('runId') == run_id), {})
            verified = bool(master and scoped and agent == comment.get('authorAgentId') and
                proof.get('session_id') == session and run and
                (not run.get('agentId') or run.get('agentId') == agent) and
                hmac.compare_digest(expected, str(proof.get('signature', ''))))
            # A running journal is progress, never proof that the task completed.
            tools = proof.get('tool_calls', [proof] if proof.get('kind') == 'tool_event' else [])
            if proof.get('version') == 2:
                tools = [{'tool': proof.get('tool'), 'success': True, 'result': proof.get('models')}]
            found.append(redact({'verified': verified, 'verification':
                'Signed runtime tool data; generated content still requires review' if verified else 'Unverified receipt',
                'run_id': run_id, 'run_status': run.get('status'), 'agent_id': agent,
                'kind': proof.get('kind', 'inventory'), 'task_status': proof.get('task_status'),
                'completion_verified': bool(verified and proof.get('task_status') == 'done' and
                    run.get('status') == 'succeeded' and issue.get('status') == 'done'),
                'model': proof.get('model'), 'tools': tools, 'artifacts': proof.get('artifacts', []),
                'source_refs': proof.get('source_refs', []), 'framework_evaluations': proof.get('framework_evaluations', []),
                'runtime_deliveries': proof.get('runtime_deliveries', []), 'comment_id': comment.get('id')}))
        except (ValueError, TypeError, AttributeError):
            found.append({'verified': False, 'verification': 'Malformed execution receipt', 'tools': []})
    return found


_cpu_sample = None


def host_metrics():
    global _cpu_sample
    result = {'scope': 'Read-only host /proc counters; load includes other applications',
        'cpu_count': os.cpu_count(), 'load_average': list(os.getloadavg()), 'cpu_busy_percent': None}
    try:
        fields = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        sample = (sum(fields), fields[3] + fields[4])
        if _cpu_sample and sample[0] > _cpu_sample[0]:
            result['cpu_busy_percent'] = round(100 * (1 - (sample[1] - _cpu_sample[1]) / (sample[0] - _cpu_sample[0])), 1)
        _cpu_sample = sample
        mem = dict((line.split(':')[0], int(line.split()[1]) * 1024) for line in
            Path('/proc/meminfo').read_text().splitlines() if line.split(':')[0] in ('MemTotal', 'MemAvailable'))
        result.update(memory_total_bytes=mem.get('MemTotal'), memory_available_bytes=mem.get('MemAvailable'))
    except (OSError, ValueError, IndexError):
        result['metrics_error'] = 'Some host counters unavailable'
    return result


async def inference():
    result = {'provider': 'local Ollama', 'inference_slots': 1, 'configured_cpu_threads': 24,
        'scope': 'Loaded models are observed; Paperclip runs may wait for the shared slot.'}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3, connect=1), trust_env=False) as client:
            r = await client.get(os.environ.get('JARVIS_OLLAMA_URL', 'http://ollama-models:11434') + '/api/ps')
            r.raise_for_status()
            result.update(available=True, loaded_models=[{k: m.get(k) for k in
                ('name', 'model', 'size', 'size_vram', 'context_length', 'expires_at')} for m in r.json()['models']])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        result.update(available=False, error='Local inference status unavailable', loaded_models=[])
    return result


def add_routes(router, Paperclip):
    async def client():
        p = Paperclip()
        try:
            yield p
        finally:
            await p.http.aclose()

    async def scoped_approval(p, approval_id):
        approval = await p.request('GET', 'approvals/' + str(approval_id))
        if approval.get('companyId') != p.company:
            raise HTTPException(404, 'Approval not found')
        linked = await p.request('GET', f'approvals/{approval_id}/issues')
        if not linked or any(i.get('companyId') != p.company or i.get('projectId') != p.project for i in linked):
            raise HTTPException(404, 'Approval not linked exclusively to General Operations')
        return approval, linked

    def approval_view(a):
        body = a.get('payload') or {}
        meta = ((body.get('metadata') or {}).get('jarvis') or {})
        return redact({**{k: a.get(k) for k in ('id', 'type', 'status', 'requestedByAgentId', 'createdAt', 'decidedAt', 'decisionNote')},
            'proposal': {k: body.get(k) for k in ('name', 'role', 'title', 'summary', 'reason', 'recommendedAction', 'risks', 'scope', 'reportsTo', 'capabilities', 'agentId')},
            'capability': capability({'metadata': {'jarvis': meta}}),
            'hiring_reason': meta.get('hiring_reason'), 'source_issue_id': meta.get('source_issue_id')})

    @router.get('/monitor')
    async def dashboard(p=Depends(client)):
        agents, issues, live, approvals, model = await asyncio.gather(p.agents(),
            p.request('GET', f'companies/{p.company}/issues?projectId={p.project}'),
            p.request('GET', f'companies/{p.company}/live-runs'),
            p.request('GET', f'companies/{p.company}/approvals'), inference())
        tasks = [i for i in issues if i.get('companyId') == p.company and i.get('projectId') == p.project]
        ids = {i['id'] for i in tasks}
        # Full approval payloads and adapter configs never cross this boundary.
        views = []
        for a in sorted(approvals, key=lambda a: a.get('createdAt') or '', reverse=True)[:25]:
            try:
                valid, linked = await scoped_approval(p, a['id'])
                views.append({**approval_view(valid), 'issue_ids': [i['id'] for i in linked]})
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        return redact({'updated_at': time.time(), 'task_counts': {s: sum(i.get('status') == s for i in tasks)
            for s in ('backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled')},
            'agents': [{**{k: a.get(k) for k in ('id', 'name', 'title', 'role', 'reportsTo', 'status', 'lifecycleState', 'lifecycleError')},
                'capability': capability(a)} for a in agents],
            'live_runs': [{k: r.get(k) for k in ('id', 'status', 'agentId', 'agentName', 'issueId', 'startedAt', 'createdAt', 'livenessState', 'lastUsefulActionAt', 'nextAction')}
                for r in live if r.get('issueId') in ids],
            'approvals': views, 'inference': model, 'resources': host_metrics()})

    @router.get('/tasks/{task_id}/monitor')
    async def task_monitor(task_id: UUID, p=Depends(client)):
        issue = await p.issue(task_id)
        comments, runs, artifacts = await asyncio.gather(
            p.request('GET', f'issues/{task_id}/comments'), p.request('GET', f'issues/{task_id}/runs'),
            p.request('GET', f'issues/{task_id}/attachments'))
        receipts = [receipt for c in comments for receipt in evidence(c, issue, runs, p.company)]
        plans = [{k: c.get(k) for k in ('id', 'body', 'createdAt', 'authorAgentId')} for c in comments
            if c.get('authorAgentId') == p.ceo and (c.get('body') or '').startswith('[JARVIS CEO PLAN')]
        deps = {}
        for name in ('blockedBy', 'blocks'):
            deps[name] = [{k: i.get(k) for k in ('id', 'identifier', 'title', 'status')} for i in issue.get(name) or []]
        return redact({'task_id': str(task_id), **deps, 'plans': plans, 'plan_document': issue.get('planDocument'),
            'execution_blocker': issue.get('executionBlocker'), 'recovery': issue.get('activeRecoveryAction'),
            'interruption': issue.get('interruption'), 'evidence': receipts,
            'artifacts': [{k: a.get(k) for k in ('id', 'originalFilename', 'contentType', 'byteSize', 'sha256', 'createdByAgentId', 'originatingRunId', 'createdAt')} for a in artifacts]})

    @router.get('/tasks/{task_id}/runs/{run_id}/log')
    async def run_log(task_id: UUID, run_id: UUID, offset: int = Query(0, ge=0), p=Depends(client)):
        await p.issue(task_id)
        run = await p.request('GET', f'heartbeat-runs/{run_id}')
        if run.get('companyId') != p.company or (run.get('contextSnapshot') or {}).get('issueId') != str(task_id):
            raise HTTPException(404, 'Execution not found on this task')
        log = await p.request('GET', f'heartbeat-runs/{run_id}/log?offset={offset}&limitBytes=32768')
        return redact({'run_id': str(run_id), 'content': log.get('content', ''), 'next_offset': log.get('nextOffset')})

    @router.get('/tasks/{task_id}/artifacts/{artifact_id}')
    async def download(task_id: UUID, artifact_id: UUID, p=Depends(client)):
        await p.issue(task_id)
        items = await p.request('GET', f'issues/{task_id}/attachments')
        native = next((a for a in items if a.get('id') == str(artifact_id)), None)
        if not native:
            raise HTTPException(404, 'Artifact not found on this task')
        if not isinstance(native.get('byteSize'), int) or not 0 < native['byteSize'] <= 1024 * 1024:
            raise HTTPException(422, 'Artifact exceeds the HUD download limit')
        try:
            async with p.http.stream('GET', f'attachments/{artifact_id}/content') as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise HTTPException(502, 'Artifact is larger than its receipt')
        except httpx.HTTPError:
            raise HTTPException(502, 'Cannot retrieve native artifact') from None
        if len(data) != native['byteSize'] or hashlib.sha256(data).hexdigest() != native.get('sha256'):
            raise HTTPException(502, 'Native artifact integrity check failed')
        filename = re.sub(r'[^A-Za-z0-9_.-]', '_', native.get('originalFilename') or 'artifact.txt')[:120]
        return Response(bytes(data), media_type='application/octet-stream', headers={
            'Content-Disposition': f'attachment; filename="{filename}"', 'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'no-store', 'X-Artifact-SHA256': native['sha256']})

    @router.post('/tasks/{task_id}/retry')
    async def retry(task_id: UUID, body: RetryRequest, p=Depends(client)):
        await p.issue(task_id)
        receipt = await p.request('POST', f'issues/{task_id}/retry', {'idempotencyKey': str(body.request_id),
            'observedRunId': str(body.observed_run_id) if body.observed_run_id else None})
        return redact(receipt)

    async def cancellation_preview(p, task_id):
        await p.issue(task_id)
        preview = await p.request('POST', f'issues/{task_id}/tree-control/preview', {'mode': 'cancel'})
        for item in preview.get('issues', []):
            await p.issue(UUID(item['id']))
        return preview

    @router.post('/tasks/{task_id}/cancel-preview')
    async def preview(task_id: UUID, p=Depends(client)):
        return redact(await cancellation_preview(p, task_id))

    @router.post('/tasks/{task_id}/cancel')
    async def cancel(task_id: UUID, body: Cancellation, p=Depends(client)):
        await cancellation_preview(p, task_id)
        return redact(await p.request('POST', f'issues/{task_id}/tree-holds',
            {'mode': 'cancel', 'reason': body.reason, 'metadata': {'source': 'jarvis-human-hud'}}))

    @router.post('/approvals/{approval_id}/decision')
    async def decide(approval_id: UUID, body: Decision, p=Depends(client)):
        a, linked = await scoped_approval(p, approval_id)
        wanted = 'approved' if body.decision == 'approve' else 'rejected'
        if a.get('status') == wanted:
            return approval_view(a)  # Safe replay of an acknowledged decision.
        if a.get('status') not in ('pending', 'revision_requested'):
            raise HTTPException(409, 'Approval already has a different decision')
        if body.decision == 'approve' and a.get('type') == 'hire_agent':
            proposed = a.get('payload') or {}
            meta = ((proposed.get('metadata') or {}).get('jarvis') or {})
            data = catalog()
            spec = data['profiles'].get(meta.get('profile'))
            item = {**(spec or {}), 'id': meta.get('profile'), 'version': data['version'], 'model': data['model']}
            sha = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            snapshot = proposed.get('requestedConfigurationSnapshot') or {}
            heartbeat = (proposed.get('runtimeConfig') or {}).get('heartbeat') or {}
            if (not spec or not meta.get('managed') or meta.get('profile_sha256') != sha or
                    meta.get('model') != data['model'] or meta.get('limits') != spec['limits'] or
                    proposed.get('reportsTo') != p.ceo or a.get('requestedByAgentId') != p.ceo or
                    proposed.get('adapterType') != 'hermes_gateway' or proposed.get('adapterConfig') not in ({}, None) or
                    snapshot.get('adapterType') != 'hermes_gateway' or snapshot.get('adapterConfig') != {} or
                    snapshot.get('runtimeConfig') != proposed.get('runtimeConfig') or
                    snapshot.get('desiredSkills') not in (None, []) or
                    heartbeat.get('enabled') is not False or heartbeat.get('maxConcurrentRuns') != 1 or
                    heartbeat.get('wakeOnAssignment') is not True or heartbeat.get('wakeOnDemand') is not True):
                raise HTTPException(409, 'Hire differs from the reviewed capability template; review it in Paperclip')
        result = await p.request('POST', f'approvals/{approval_id}/{body.decision}', {'decisionNote': body.note})
        return approval_view(result)
