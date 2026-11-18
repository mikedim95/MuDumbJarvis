"""Recover direct reports interrupted between the child disposition and the parent notification."""
import asyncio
import logging
import importlib.util
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
        except Exception:
            logging.exception('Worker blocker delivery will retry')
        finally:
            if p is not None:
                await p.http.aclose()
        await asyncio.sleep(45)
