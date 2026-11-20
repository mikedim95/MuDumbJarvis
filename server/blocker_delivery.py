"""Recover direct reports interrupted between the child disposition and the parent notification."""
import asyncio
import logging
import importlib.util
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

_path = Path(__file__).resolve().parents[1] / 'hermes-plugin' / 'jarvis_readonly' / 'blocker_review.py'
_spec = importlib.util.spec_from_file_location('jarvis_blocker_review', _path)
_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_review)
decisions = _review.decisions
approved_operator_request = _review.approved_operator_request
_apt_spec = importlib.util.spec_from_file_location('jarvis_apt_receipts', _path.with_name('apt_receipts.py'))
_apt = importlib.util.module_from_spec(_apt_spec)
_apt_spec.loader.exec_module(_apt)
PREFIX = _review.REPORT
WAITING = _review.WAITING
PROGRESS = '[JARVIS PROGRESS CHECK '


def has_package_blocker(child):
    return bool(_review.blocker_packages((child.get('unblockDescriptor') or {}).get('action') or ''))


async def owner_decisions(client, issue_id):
    rows = await client.request('GET', f'issues/{issue_id}/interactions')
    result = decisions(rows, issue_id, client.ceo)
    for review in result:
        if review.get('package'):
            review['usage'] = _apt.usage(review['package'])
    return result


async def load_package_receipts(client, root, issues, reviews):
    docs = {}
    for review in reviews:
        child = issues.get(review['child_id'])
        if not (review.get('package') and review.get('answer') == 'accepted' and child and not child.get('hiddenAt')
                and child.get('parentId') == root['id'] and child.get('assigneeAgentId') == review['agent_id']
                and child.get('projectId') == root.get('projectId')):
            continue
        if child['id'] not in docs:
            try:
                rows = await client.request('GET', 'issues/' + child['id'] + '/documents')
                docs[child['id']] = {d.get('key'): d for d in rows}
            except HTTPException:
                docs[child['id']] = None
        if docs[child['id']] is None:
            review['installation'] = {'status':'unconfirmed', 'detail':'The installation receipt could not be read.'}
            continue
        scope = _apt.binding(client.company, root['projectId'], root['id'], child['id'], review['agent_id'],
                             review['package'], review['id'])
        receipt = _apt.read(docs[child['id']].get(_apt.key(review['id'])), scope)
        if receipt:
            review['installation'] = receipt


def package_blockers(parent, issues, reviews):
    """Describe the next step only while the same assignment has the same package blocker."""
    if parent.get('hiddenAt') or parent.get('status') in ('done', 'cancelled'):
        return {}
    by_child = {}
    for review in reviews:
        name = review.get('package')
        child = issues.get(review['child_id'])
        if not (name and child and review.get('answer') in ('accepted', 'rejected')
                and child.get('parentId') == parent['id'] and child.get('projectId') == parent.get('projectId')
                and child.get('assigneeAgentId') == review['agent_id'] and child.get('status') == 'blocked'
                and not child.get('hiddenAt')):
            continue
        action = (child.get('unblockDescriptor') or {}).get('action') or ''
        if name in _review.blocker_packages(action):
            by_child.setdefault(child['id'], {})[name] = review

    progress = {}
    parent_action = (parent.get('unblockDescriptor') or {}).get('action') or ''
    for child_id, packages in by_child.items():
        child = issues[child_id]
        if any(r['child_id'] == child_id and r['status'] == 'pending' for r in reviews):
            continue
        identifier = child.get('identifier') or child_id
        parts = []
        next_actor = None
        for name, review in sorted(packages.items()):
            install = review.get('installation') or {}
            if review['answer'] == 'rejected':
                parts.append(f'You declined {name} for {identifier}.')
            elif install.get('status') == 'ready':
                if name == 'nmap':
                    parts.append(f"{identifier} has Nmap {install['version']} for offline version checks. Network scans are disabled.")
                else:
                    parts.append(f"{name} {install['version']} is ready for {identifier}.")
            elif install:
                parts.append(f"{identifier} package setup for {name}: {install['detail']}")
            else:
                parts.append(f'{identifier} is waiting for the package service to install {name}.')
                next_actor = 'package_service'
        progress[child_id] = {'progress': ' '.join(parts), 'next_actor': next_actor}
        prefix = f'{_review.BLOCKED_ON}{identifier} — '
        package_reference = parent_action.startswith(prefix) and any(
            re.search(r'(?<![\w.+-])' + re.escape(name) + r'(?![\w+-]|\.[\w])', parent_action[len(prefix):], re.I)
            for name in packages)
        if parent.get('status') == 'blocked' and not any(r['status'] == 'pending' for r in reviews) and (
                package_reference or
                any(parent_action == WAITING + r['question'] for r in reviews
                    if r.get('child_id') == child_id and r.get('package') in packages)):
            progress[parent['id']] = progress[child_id]
    return progress


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
        # List projections can omit failed-execution holds. A normal wakeup
        # cannot reconcile those; leave them for an explicit native owner retry.
        detail = await p.request('GET','issues/'+root['id'])
        if detail.get('executionBlocker') or detail.get('executionRunId'):
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
        latest_user = max((c.get('createdAt') or '' for c in comments if c.get('authorUserId') and
            not (c.get('body') or '').startswith(PROGRESS)), default='')
        action = (detail.get('unblockDescriptor') or {}).get('action') or ''
        package_reviews = [r for r in decisions(interactions, root['id'], p.ceo) if r.get('package')
            and r.get('answer') == 'accepted' and r['child_id'] in records
            and records[r['child_id']].get('status') == 'blocked'
            and r['package'] in _review.blocker_packages(
                (records[r['child_id']].get('unblockDescriptor') or {}).get('action') or '')]
        if package_reviews:
            await load_package_receipts(p, root, records, package_reviews)
        ready = [r for r in package_reviews if (r.get('installation') or {}).get('status') == 'ready']
        # A ready receipt can precede a worker's final stale PATH check. Deliver it once even in that order.
        if ready:
            receipts = sorted((r['id'], r['installation']['output_sha256']) for r in ready)
            fingerprint = hashlib.sha256(json.dumps([root['id'], receipts]).encode()).hexdigest()
            marker = PROGRESS + 'packages ' + fingerprint + ']'
            if not any((c.get('body') or '').startswith(marker) for c in comments):
                probes = [records[r['child_id']]['identifier'] + ' ' + r['installation']['command'] + ' ' +
                          ('--version' if r['package'] in ('jq', 'nmap') else '--package-version') for r in ready]
                note = 'Operator verified these assignment commands. Have the existing workers run the probe from their private task directories: ' + ', '.join(probes)
                await p.request('POST', 'agents/' + p.ceo + '/wakeup', {'source':'on_demand',
                    'reason':'issue_commented', 'idempotencyKey':'jarvis-package-ready:' + fingerprint,
                    'payload':{'issueId':root['id'], 'source':'jarvis.package_ready', 'message':note}})
                await p.request('POST', 'issues/' + root['id'] + '/comments', {'body':marker + '\n' + note,
                    'clientRequestId':str(uuid5(NAMESPACE_URL, marker))})
                continue
        if action.startswith(_review.BLOCKED_ON):
            # An unchanged, reviewed blocker needs no idle wake. Owner messages,
            # later resolutions and changes to child work still trigger review.
            reviews = [c.get('createdAt') for c in comments if c.get('authorAgentId') == p.ceo
                       and c.get('body') == action]
            reviews.extend(d.get('resolvedAt') for d in interactions if d.get('createdByAgentId') == p.ceo
                           and d.get('resolvedByUserId') and d.get('status') == 'cancelled'
                           and (d.get('result') or {}).get('outcome') == 'skipped'
                           and (d.get('result') or {}).get('reason') == action)
            reviewed = max(filter(None, reviews), default='')
            changes = [latest_user, *(at or '' for _, _, at in evidence),
                       *(a.get('decidedAt') or a.get('createdAt') or '' for a in approvals),
                       *(d.get('resolvedAt') or d.get('createdAt') or '' for d in interactions
                         if not _review.package_decision(d, root['id'], p.ceo))]
            if reviewed and max(changes) <= reviewed:
                continue
        fingerprint = hashlib.sha256(json.dumps([root['id'], sorted(evidence), sorted(answers), latest_user], sort_keys=True).encode()).hexdigest()
        marker = PROGRESS + fingerprint + ']'
        if any((c.get('body') or '').startswith(marker) for c in comments):
            continue
        await p.request('POST', 'agents/' + p.ceo + '/wakeup', {
            'source': 'on_demand', 'reason': 'issue_commented', 'idempotencyKey': 'jarvis-progress:' + fingerprint,
            'payload': {'issueId': root['id'], 'source': 'jarvis.progress_check',
                        'message': 'No run, queued execution, pending owner question or approval is keeping this project moving. '
                                   'Apply recorded owner answers and resolve the current blocker. Resume the existing worker '
                                   'with a concrete correction, or ask the owner for the specific intervention you require.'}})
        await p.request('POST','issues/'+root['id']+'/comments',{'body':marker+
            '\nA CEO progress review was requested for this unchanged work state. Paperclip owns continuation.'})


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
    if (child.get('hiddenAt') or parent.get('parentId') or parent.get('assigneeAgentId') != p.ceo or parent.get('companyId') != child.get('companyId')
            or parent.get('projectId') != child.get('projectId') or parent.get('hiddenAt')
            or parent.get('status') in ('done', 'cancelled')):
        return False
    updates = await p.request('GET', 'issues/' + child['id'] + '/comments')
    names = _review.worker_package_requests(child, updates)
    if names:
        # The normal CEO review can create the confirmation itself. When the
        # CEO is idle, its board relay preserves the worker's existing request
        # on the CEO issue without starting another execution.
        if parent.get('executionBlocker') or parent.get('executionRunId'):
            return False
        holds = await p.request('GET', 'issues/' + parent['id'] + '/tree-holds?status=active')
        if (holds.get('holds', []) if isinstance(holds, dict) else holds):
            return False
        current = await p.issue(child['id'])
        if any(current.get(k) != child.get(k) for k in ('status','updatedAt','assigneeAgentId','parentId','projectId')):
            return False
        path = 'issues/' + parent['id'] + '/interactions'
        previous = {d['key'] for d in decisions(await p.request('GET', path), parent['id'], p.ceo)}
        for name in names:
            form = _review.package_confirmation(child, name, parent.get('responsibleUserId') or parent.get('createdByUserId'))
            if form['idempotencyKey'] not in previous:
                saved = await p.request('POST', path, form)
                if not _review.package_decision(saved, parent['id'], p.ceo):
                    raise HTTPException(502, 'Paperclip did not confirm the package review')
        return True
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
