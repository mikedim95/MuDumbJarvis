"""Brief public work activity, projected from scoped native records only."""
import asyncio
import re

from fastapi import HTTPException

from chat_context import text
from csi_events import public_body
from task_brief import caption


PUBLIC_MARKERS = ('[JARVIS CEO PLAN', '[JARVIS CEO REVIEW]', '[JARVIS CEO WAITING]',
                  '[JARVIS CEO RESULTS READY]')
REPORT_FIELD = re.compile(r'^\s*(?:STATUS|VERIFIED EVIDENCE|ARTIFACT REFERENCES|LIMITATIONS|REMAINING BLOCKERS):', re.M)


def published_summary(body):
    """Summarize published prose, never private model reasoning or raw receipts."""
    body = public_body(body)
    if body.startswith('[JARVIS '):
        if not body.startswith(PUBLIC_MARKERS):
            return ''
        body = body.partition('\n')[2]
    # Versioned worker reports often include a verification wrapper. Prefer the
    # substantive RESULT over STATUS and evidence-envelope boilerplate.
    result = re.search(r'^\s*RESULT:\s*', body, re.M)
    if result:
        body = REPORT_FIELD.split(body[result.end():], maxsplit=1)[0]
    return text(caption(body, max_sentences=1), 240)


def tool_summary(tool):
    """Describe an observed operation without exposing arguments or payloads."""
    name = tool.get('tool')
    labels = {
        'terminal': ('Ran a workspace command.', 'A workspace command failed.'),
        'read_file': ('Read a workspace file.', 'A workspace file could not be read.'),
        'write_file': ('Wrote a workspace file.', 'A workspace file could not be written.'),
        'patch': ('Updated a workspace file.', 'A workspace edit failed.'),
        'publish_artifact': ('Saved a work artifact.', 'An artifact could not be saved.'),
        'read_worker_artifacts': ('Read worker artifact records.', 'Worker artifact access failed.'),
        'research_sources': ('Retrieved research evidence.', 'Research evidence retrieval failed.'),
        'request_action_approval': ('Requested an approval.', 'An approval request failed.'),
    }
    if name not in labels or not isinstance(tool.get('success'), bool):
        return ''
    result = tool.get('result')
    if name == 'terminal' and isinstance(result, dict):
        code = result.get('exit_code')
        if isinstance(code, int) and code != 0:
            return f'A workspace command failed (exit {code}).'
    if tool['success'] is not True:
        return labels[name][1]
    if name == 'research_sources':
        args = tool.get('args') if isinstance(tool.get('args'), dict) else {}
        return {
            'fetch': 'Retrieved public source documentation.',
            'search': 'Searched public research sources.',
            'knowledge': 'Retrieved relevant saved knowledge.',
            'records': 'Read saved research records.',
        }.get(args.get('action'), labels[name][0])
    return labels[name][0]


def current_work(agent):
    """A native assignment is current work; it is not proof of a running tool."""
    for state in ('active', 'blocked', 'waiting', 'queued'):
        job = next((j for j in agent['work'] if j['state'] == state), None)
        if job:
            return {**{k: job.get(k) for k in ('id', 'identifier', 'state', 'mission', 'cron_job', 'next_actor')},
                    'title': text(job.get('title'), 180), 'reason': text(job.get('reason'), 240)}
    return None


async def latest_activity(client, agent, issues):
    """Only read history for the clicked agent, after mission isolation is applied."""
    from task_monitor import evidence

    jobs = [j for j in agent['work'] + agent['past_work']
            if not (j.get('mission') or {}).get('hiddenAt')]
    jobs.sort(key=lambda j: issues[j['id']].get('updatedAt') or issues[j['id']].get('createdAt') or '', reverse=True)
    # Bound native reads even when an employee has a long execution history.
    selected = {j['id']: j for j in jobs[:3]}
    current = agent.get('current_work')
    if current:
        selected[current['id']] = next(j for j in jobs if j['id'] == current['id'])
    candidates = []
    for review in agent.get('package_decisions', []):
        if review.get('resolved_at') and review['decision'] in ('accepted', 'rejected'):
            decision = 'approved' if review['decision'] == 'accepted' else 'declined'
            candidates.append({'summary': f"You {decision} {review['package']} for {review['child']}.",
                'kind': 'owner_decision', 'at': review['resolved_at'], 'task': review['task'],
                'mission': review['mission'], 'cron_job': None})
            install = review.get('installation') or {}
            if install.get('status') == 'ready' and install.get('verified_at'):
                candidates.append({'summary':f"Verified {review['package']} {install['version']} from {review['child']}.",
                    'kind':'package_verification', 'at':install['verified_at'], 'task':review['task'],
                    'mission':review['mission'], 'cron_job':None})
    unavailable = False

    async def read(job):
        nonlocal unavailable
        try:
            comments, runs = await asyncio.gather(*(
                client.request('GET', f"issues/{job['id']}/{kind}") for kind in ('comments', 'runs')))
        except HTTPException:
            unavailable = True
            return
        issue = issues[job['id']]
        for comment in comments:
            if comment.get('authorAgentId') != agent['id']:
                continue
            summary = published_summary(comment.get('body'))
            kind = 'published_update'
            # A completion envelope repeats old tools. Only a signed tool-event
            # journal establishes when an individual operation was recorded.
            for receipt in evidence(comment, issue, runs, client.company):
                if not receipt.get('verified') or receipt.get('kind') != 'tool_event':
                    continue
                observed = [tool_summary(t) for t in receipt['tools'] if isinstance(t, dict)]
                if any(observed):
                    summary = next(s for s in reversed(observed) if s)
                    kind = 'tool_result'
            if job.get('next_actor') == 'runtime_operator' and summary.startswith('Waiting for your decision.'):
                continue
            if not summary:
                continue
            candidates.append({'summary': summary, 'kind': kind, 'at': comment.get('createdAt'),
                'task': {k: job.get(k) for k in ('id', 'identifier')},
                'mission': job.get('mission'), 'cron_job': job.get('cron_job')})

    await asyncio.gather(*(read(job) for job in selected.values()))
    if unavailable:
        # Do not silently call an older observation the latest after a failed read.
        return {'latest': None, 'available': False}
    latest = max(candidates, key=lambda c: c.get('at') or '', default=None)
    return {'latest': latest, 'available': True}
