"""Recover direct reports interrupted between the child disposition and the parent notification."""
import asyncio
import logging
import importlib.util
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

_path = Path(__file__).resolve().parents[1] / 'hermes-plugin' / 'jarvis_readonly' / 'blocker_review.py'
_spec = importlib.util.spec_from_file_location('jarvis_blocker_review', _path)
_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_review)
decisions = _review.decisions
PREFIX = _review.REPORT
WAITING = _review.WAITING


async def owner_decisions(client, issue_id):
    rows = await client.request('GET', f'issues/{issue_id}/interactions')
    return decisions(rows, issue_id, client.ceo)


async def continue_stalled_projects(p):
    from agent_work import issue_index
    records = await issue_index(p)
    for root in records.values():
        if (root.get('assigneeAgentId') != p.ceo or root.get('parentId') or root.get('hiddenAt')
                or root.get('status') in ('backlog', 'done', 'cancelled')):
            continue
        tree = [root]
        seen = {root['id']}
        for parent in tree:
            for child in records.values():
                if (child.get('parentId') == parent['id'] and child.get('projectId') == root.get('projectId')
                        and child['id'] not in seen):
                    seen.add(child['id'])
                    tree.append(child)
        if any(row.get('executionRunId') or (row.get('activeRun') or {}).get('status') in ('running', 'queued') for row in tree):
            continue
        latest_change = max(row.get('updatedAt') or root['updatedAt'] for row in tree)
        if datetime.fromisoformat(latest_change) > datetime.now(timezone.utc) - timedelta(seconds=15):
            continue
        interactions = await p.request('GET', 'issues/' + root['id'] + '/interactions')
        if any(d.get('status') == 'pending' and not d.get('addresseeAgentId') for d in interactions):
            continue
        approvals = await p.request('GET', 'issues/' + root['id'] + '/approvals')
        if any(a.get('status') in ('pending', 'revision_requested') for a in approvals):
            continue
        holds = await p.request('GET', 'issues/' + root['id'] + '/tree-holds?status=active')
        if isinstance(holds, dict):
            holds = holds.get('holds', [])
        if holds:
            continue
        runs = await p.request('GET', 'issues/' + root['id'] + '/runs')
        if any(r.get('status') in ('running', 'queued', 'scheduled_retry') for r in runs):
            continue
        # Durable native idempotency allows one recovery for an unchanged situation.
        # CEO comments and failed review turns cannot produce an automatic retry loop.
        evidence = [(row['id'], row.get('status'), row.get('updatedAt')) for row in tree if row['id'] != root['id']]
        answers = [(d['id'], d['status'], d.get('result')) for d in interactions]
        comments = await p.request('GET', 'issues/' + root['id'] + '/comments')
        latest_user = max((c.get('createdAt') or '' for c in comments if c.get('authorUserId')), default='')
        fingerprint = hashlib.sha256(json.dumps([root['id'], sorted(evidence), sorted(answers), latest_user], sort_keys=True).encode()).hexdigest()
        await p.request('POST', 'agents/' + p.ceo + '/wakeup', {
            'source': 'on_demand', 'reason': 'issue_commented', 'idempotencyKey': 'jarvis-progress:' + fingerprint,
            'payload': {'issueId': root['id'], 'source': 'jarvis.progress_check',
                        'message': 'No run, queued execution, pending owner question or approval is keeping this project moving. '
                                   'Apply recorded owner answers and resolve the current blocker. Resume the existing worker '
                                   'with a concrete correction, or ask the owner for the specific intervention you require.'}})


async def reconcile(p, delivered):
    path = (f'companies/{p.company}/issues?status=blocked'
            '&includeRoutineExecutions=true&sortField=id&sortDir=asc&limit=100')
    cursor = ''
    workers = None
    observed = set()
    while True:
        page = await p.request('GET', path + cursor)
        for child in page:
            action = (child.get('unblockDescriptor') or {}).get('action') or ''
            key = (child['id'], child.get('updatedAt'))
            if not (child.get('companyId') == p.company
                    and child.get('parentId') and child.get('status') == 'blocked' and action.startswith(PREFIX)):
                continue
            observed.add(key)
            if key in delivered or not key[1] or child.get('executionRunId'):
                continue
            if datetime.fromisoformat(key[1]) > datetime.now(timezone.utc) - timedelta(minutes=1):
                continue  # Give the worker's immediate report time to reach the parent.
            if workers is None:
                workers = {a['id'] for a in await p.agents() if a.get('reportsTo') == p.ceo and a.get('companyId') == p.company}
            if child.get('assigneeAgentId') not in workers:
                continue
            try:
                if await forward(p, child, action[len(PREFIX):]):
                    delivered.add(key)
            except HTTPException:
                logging.exception('Could not deliver worker blocker for %s', child['id'])
        if len(page) < 100:
            break
        next_cursor = '&afterId=' + page[-1]['id']
        if next_cursor == cursor:
            raise RuntimeError('Paperclip did not advance the blocker list')
        cursor = next_cursor
    delivered.intersection_update(observed)


async def forward(p, child, reason):
    parent = await p.issue(child['parentId'])
    if (parent.get('assigneeAgentId') != p.ceo or parent.get('companyId') != child.get('companyId')
            or parent.get('projectId') != child.get('projectId') or parent.get('hiddenAt')
            or parent.get('status') in ('done', 'cancelled')):
        return False
    updates = await p.request('GET', 'issues/' + child['id'] + '/comments')
    reports = [c for c in updates if c.get('authorAgentId') == child['assigneeAgentId'] and c.get('createdByRunId')
               and '\nJARVIS_EXECUTION_EVIDENCE=' in (c.get('body') or '')]
    if not reports:
        return False
    latest = max(reports, key=lambda c: c.get('createdAt') or '')
    marker = '[JARVIS WORKER BLOCKER ' + latest['createdByRunId'] + ']'
    path = 'issues/' + parent['id'] + '/comments'
    comments = await p.request('GET', path)
    nonce = str(uuid5(NAMESPACE_URL, child['id'] + ':' + marker))
    if any((c.get('authorAgentId') == child['assigneeAgentId'] or c.get('clientRequestId') == nonce)
           and (c.get('body') or '').startswith(marker) for c in comments):
        return True
    if parent.get('executionBlocker') or parent.get('executionRunId'):
        return False
    holds = await p.request('GET', 'issues/' + parent['id'] + '/tree-holds?status=active')
    if isinstance(holds, dict):
        holds = holds.get('holds', [])
    if holds:
        return False
    current = await p.issue(child['id'])
    if current.get('updatedAt') != child.get('updatedAt') or current.get('status') != 'blocked':
        return False
    await p.request('POST', path, {'body': marker + '\nForwarded worker report from ' + child['identifier'] +
                                   '. CEO review requested. ' + reason[:1200], 'clientRequestId': nonce})
    return True


async def monitor(client):
    delivered = set()
    while True:
        p = None
        try:
            p = client()
            await reconcile(p, delivered)
            await continue_stalled_projects(p)
        except Exception:
            logging.exception('Worker blocker delivery will retry')
        finally:
            if p is not None:
                await p.http.aclose()
        await asyncio.sleep(15)
