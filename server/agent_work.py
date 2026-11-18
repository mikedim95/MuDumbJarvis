"""Read-only staff assignments and their native mission and routine links."""
import asyncio
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

import blocker_delivery
import work_scope


_portraits = json.loads((Path(__file__).resolve().parents[1] / 'hermes-plugin' / 'jarvis_readonly' / 'portraits.json').read_text())
_portrait_ids = {*_portraits['roles'].values(), *_portraits['hires']}


def safe_text(value, limit):
    from chat_context import text
    return text(value, limit)


def custom_asset(person):
    try:
        asset = str(UUID((person.get('appearance') or {}).get('customAvatarAssetId') or ''))
    except (ValueError, TypeError, AttributeError):
        return None
    return asset


def portrait_url(person, ceo):
    asset = custom_asset(person)
    if asset:
        return f"/api/agents/{person['id']}/portrait/{asset}"
    meta = (person.get('metadata') or {}).get('jarvis') or {}
    chosen = meta.get('portrait_id')
    if not isinstance(chosen, str) or chosen not in _portrait_ids:
        role = 'ceo' if person['id'] == ceo else person.get('role')
        chosen = _portraits['roles'].get(role)
    if not chosen:
        seed = hashlib.sha256(person['id'].encode()).digest()
        chosen = _portraits['hires'][int.from_bytes(seed[:4], 'big') % len(_portraits['hires'])]
    return f'/hud/portraits/{chosen}.webp'


def specialization(person):
    title = person.get('title') or ''
    if title.casefold() == 'research' and ((person.get('metadata') or {}).get('jarvis') or {}).get('profile') == 'research':
        return 'Public-source research'
    return safe_text(title or (person.get('role') or 'Team member').replace('_', ' ').title(), 140)


_ordinary_wait = re.compile(r'^(?:await(?:ing)?|wait(?:ing)? (?:for|on)|pending)\b', re.I)
_approval_wait = re.compile(r'\b(?:pending (?:human |board )?(?:approval|review|decision)|'
                            r'(?:approval|review) (?:is )?(?:pending|required)|review and approve)\b', re.I)
_hard_stop = re.compile(
    r'\b(?:guardrail|access denied|permission denied|access was denied|authorization failed|'
    r'(?:missing|required|invalid|expired|revoked) (?:access|credentials?|permissions?|authorization)|'
    r'(?:await(?:ing)?|wait(?:ing)? for) (?:valid |the )?credentials?\b|'
    r'(?:credentials?|permission|authorization) (?:is |are )?(?:missing|invalid|expired|revoked)|'
    r'(?:policy|guardrail) (?:denies|forbids|prohibits|blocks)|approval (?:was )?(?:rejected|denied)|'
    r'(?:missing|required|insufficient|unavailable|unverified) evidence|(?:cannot|could not|unable to) verify|'
    r'could (?:not|never) be verified|execution error|execution failed|runtime failure)\b', re.I)


def issue_condition(issue):
    """Classify Paperclip's various blocked states into a dependency wait or a problem needing action."""
    recovery = issue.get('executionBlocker') or {}
    action = safe_text((issue.get('unblockDescriptor') or {}).get('action'), 285)
    attention = issue.get('blockerAttention') or {}
    dependency = safe_text(attention.get('sampleBlockerIdentifier'), 65)
    if recovery:
        detail = safe_text(recovery.get('nextAction'), 285)
        cause = safe_text(recovery.get('cause'), 90).replace('_', ' ')
        return 'blocked', detail or (f'Execution stopped because of {cause}.' if cause else 'Execution recovery requires attention.')
    if action.startswith(blocker_delivery.WAITING):
        return 'blocked', action
    if attention.get('state') == 'stalled':
        return 'blocked', action or (f'{dependency} has stalled and needs attention.' if dependency else 'The review has stalled and needs attention.')
    if _hard_stop.search(action):
        # A parent's recorded action can describe its child's failure. Keep the
        # problem on that job unless this job has an independent hard stop.
        own_condition = action
        if dependency:
            subject = re.compile(r'^(?:(?:task|worker|job|child)\s+)?' + re.escape(dependency) + r'\b', re.I)
            own_condition = ' '.join(clause for clause in re.split(r'(?<=[.!?;,])\s+|\s+(?:and|but)\s+', action)
                                     if not subject.match(clause))
        if _hard_stop.search(own_condition):
            return 'blocked', action
    if dependency and attention.get('blockingTreeLive') is False:
        return 'blocked', action or f'{dependency} is blocked. Jarvis must resolve it or request your intervention.'
    if (attention.get('reason') in ('active_child', 'active_dependency') or dependency
            or _ordinary_wait.match(action) or _approval_wait.search(action)):
        wait = f'Waiting for {dependency}.' if dependency else 'Waiting for the dependent work to finish.'
        if action and dependency and dependency not in action:
            return 'waiting', f'{wait} {action}'
        return 'waiting', action or wait
    if action or attention.get('state') == 'needs_attention':
        return 'blocked', action or 'Paperclip requires intervention. No further reason was recorded.'
    return 'waiting', 'Paperclip is holding this job. No specific cause was recorded.'


def reference(issue):
    return {key: issue.get(key) for key in ('id', 'identifier', 'title')} if issue else None


async def issue_index(client, project_id=None):
    """Include routine issues and their ordinary descendants on every native page."""
    size = 500
    path = (f'companies/{client.company}/issues?includeRoutineExecutions=true'
            f'&sortField=id&sortDir=asc&limit={size}')
    if project_id:
        path += '&projectId=' + project_id
    issues = {}
    cursor = None
    while True:
        batch = await client.request('GET', path + (f'&afterId={cursor}' if cursor else ''))
        for row in batch:
            if row.get('companyId') == client.company and (not project_id or row.get('projectId') == project_id):
                issues[row['id']] = row
        if len(batch) < size:
            return issues
        next_id = batch[-1]['id']
        if next_id == cursor:
            raise HTTPException(502, 'Paperclip did not advance the issue list')
        cursor = next_id


def engagement(issue, runs=()):
    """A live execution is distinct from a native assignment or an enabled timer."""
    status = issue.get('status')
    if status in ('done', 'cancelled'):
        return 'closed', None
    run = issue.get('activeRun') or {}
    if not run and runs:
        run = next((r for r in runs if r.get('runId') == issue.get('executionRunId') and r.get('runId')), {})
    if run.get('status') == 'running':
        return 'active', run.get('agentId') or issue.get('assigneeAgentId')
    if run.get('status') == 'queued':
        return 'queued', None
    if status == 'blocked' or issue.get('executionBlocker'):
        return issue_condition(issue)[0], None
    if status in ('backlog', 'todo'):
        return 'queued', None
    return 'waiting', None


def work_reason(issue, state, executor=None):
    if state == 'closed':
        return ''
    if state == 'active':
        return 'The agent is executing this assignment.'
    if executor:
        return 'Another agent is executing the current run.'
    if state == 'queued':
        return 'The job is in the backlog.' if issue.get('status') == 'backlog' else 'The assignment is queued for execution.'
    if issue.get('status') == 'blocked' or state == 'blocked':
        return issue_condition(issue)[1]
    if issue.get('status') == 'in_review':
        return 'The assignment is awaiting review.'
    return 'The assignment is open. No run is currently executing.'


def staff_condition(person, jobs):
    if person.get('status') == 'error' or person.get('lifecycleState') in ('error', 'failed'):
        return 'blocked', safe_text(person.get('errorReason') or person.get('lifecycleError'), 285) or 'The agent runtime reported an error.'
    if person.get('status') == 'paused':
        return 'paused', 'The agent is paused in Paperclip.'
    if person.get('status') == 'running' and not any(j['state'] == 'active' for j in jobs):
        return 'active', 'Paperclip reports a running agent. No linked assignment was supplied.'
    for state in ('active','blocked','waiting','queued'):
        primary = next((j for j in jobs if j['state'] == state), None)
        if primary:
            return state, primary['reason']
    return 'idle', 'No open assignments.'


class WorkLinks:
    def __init__(self, company, ceo, issues, routines):
        self.issues = issues
        self.jobs = {}
        self.missions = {}
        self.links = {}
        self.run_jobs = {}
        self.by_mission = {}
        for job in routines:
            if job.get('companyId') != company:
                continue
            timers = [t for t in job.get('triggers') or [] if t.get('kind') == 'schedule']
            last = job.get('lastRun') or {}
            if not timers and last.get('source') != 'schedule':
                continue
            self.jobs[job['id']] = job
            # Some older issues have no origin. Exact native routine references are
            # usable only when a single timer owns that execution issue.
            for issue_id in {(job.get('activeIssue') or {}).get('id'), last.get('linkedIssueId')} - {None}:
                self.run_jobs.setdefault(issue_id, set()).add(job['id'])
        for issue_id, row in issues.items():
            if row.get('parentId') or row.get('assigneeAgentId') != ceo or row.get('originKind') == 'routine_execution' or self.run_job(row):
                continue
            scope = work_scope.classify(row)
            if scope['kind'] == 'project' and scope['mission_id'] == issue_id:
                self.missions[issue_id] = row
        for job in self.jobs.values():
            summary = self.schedule(job)
            if summary['mission'] and job.get('status') != 'archived':
                self.by_mission.setdefault(summary['mission_id'], []).append(summary)

    def run_job(self, issue):
        origin = issue.get('originId') if issue.get('originKind') == 'routine_execution' else None
        if not origin:
            possible = self.run_jobs.get(issue['id'], ())
            if len(possible) == 1:
                origin = next(iter(possible))
        job = self.jobs.get(origin)
        return job if job and job.get('projectId') == issue.get('projectId') else None

    def mission(self, issue_id, project):
        row = self.missions.get(issue_id)
        if row and row.get('projectId') == project:
            return {**reference(row), 'hiddenAt': row.get('hiddenAt')}
        return None

    def routine_scope(self, job):
        scope = work_scope.routine_scope(job)
        if any(v.get('name') == 'jarvis_work_scope' for v in job.get('variables') or []):
            return scope
        stamp = work_scope.description_scope(job.get('description'))
        if stamp:
            return stamp
        # Native routines may be attached to a mission or one of its delegated jobs
        # without custom Jarvis variables. An explicit General scope takes priority.
        parent = self.issues.get(job.get('parentIssueId'))
        seen = set()
        while parent and parent['id'] not in seen and parent.get('projectId') == job.get('projectId'):
            if parent['id'] in self.missions:
                return {'kind': 'project', 'mission_id': parent['id'], 'routine_id': job['id']}
            seen.add(parent['id'])
            parent = self.issues.get(parent.get('parentId'))
        return scope

    def run_scope(self, issue):
        job = self.run_job(issue)
        if not job and issue.get('originKind') != 'routine_execution':
            return None
        stamp = work_scope.description_scope(issue.get('description'))
        return stamp or (self.routine_scope(job) if job else work_scope.classify(issue))

    def schedule(self, job):
        scope = self.routine_scope(job)
        mission = self.mission(scope['mission_id'], job.get('projectId')) if scope['kind'] == 'project' else None
        enabled = job.get('status') == 'active' and any(
            t.get('kind') == 'schedule' and t.get('enabled') for t in job.get('triggers') or [])
        return {**{key: job.get(key) for key in ('id', 'title', 'status', 'assigneeAgentId')},
                'enabled': enabled, 'work_scope': scope['kind'], 'mission_id': mission['id'] if mission else None,
                'mission': mission}

    def for_issue(self, issue):
        """Only follow same-project ancestors. A schedule run anchors every job it delegated."""
        row = issue
        trail = set()
        kind = mission = cron = execution = None
        while row and row['id'] not in trail:
            if row['id'] in self.links:
                kind, mission, cron, execution = self.links[row['id']]
                break
            trail.add(row['id'])
            job = self.run_job(row)
            if job or row.get('originKind') == 'routine_execution':
                scope = self.run_scope(row)
                kind = scope['kind']
                mission = self.mission(scope['mission_id'], row.get('projectId')) if scope['kind'] == 'project' else None
                cron = {key: job.get(key) for key in ('id', 'title')} if job else None
                execution = reference(row)
                break
            if row['id'] in self.missions:
                kind = 'project'
                mission = self.mission(row['id'], row.get('projectId'))
                break
            if not row.get('parentId'):
                kind = (work_scope.description_scope(row.get('description')) or {}).get('kind')
                break
            parent = self.issues.get(row.get('parentId'))
            row = parent if parent and parent.get('projectId') == issue.get('projectId') else None
        for issue_id in trail:
            self.links[issue_id] = kind, mission, cron, execution
        return {'work_scope': kind, 'mission': mission, 'cron_job': cron, 'run_issue': execution}


async def overview(client):
    from general_context import team
    project = None if getattr(client, 'workforce', False) else client.project
    people, issues, routines = await asyncio.gather(
        team(client), issue_index(client, project), client.request('GET', f'companies/{client.company}/routines'))
    # Hidden parents are omitted from the issue list while their children remain.
    # Read those ancestors so archived work cannot appear to be an active wait.
    missing = {row['parentId'] for row in issues.values()
               if row.get('parentId') and row['parentId'] not in issues and row.get('status') not in ('done', 'cancelled')}
    checked = set()
    while missing:
        parent_id = missing.pop()
        if parent_id in checked:
            continue
        checked.add(parent_id)
        try:
            parent = await client.request('GET', 'issues/' + parent_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        if parent.get('companyId') != client.company or (project and parent.get('projectId') != project):
            continue
        issues[parent_id] = parent
        if parent.get('parentId') and parent['parentId'] not in issues:
            missing.add(parent['parentId'])
    scoped = [job for job in routines if not project or job.get('projectId') == project]
    links = WorkLinks(client.company, client.ceo, issues, scoped)
    agents = {person['id']: {**{key: person.get(key) for key in ('id', 'name', 'title', 'role', 'status', 'reportsTo')},
                             'portrait_url': portrait_url(person, client.ceo), 'specialization': specialization(person),
                             'work': [], 'past_work': [], 'schedules': [], 'questions': []} for person in people}
    # Paperclip's list omits the execution recovery detail on older failed runs.
    # Read it only when the list supplies neither the necessary action nor a dependency.
    limit = asyncio.Semaphore(4)
    async def recovery_detail(row):
        async with limit:
            try:
                detail = await client.request('GET', 'issues/' + row['id'])
            except HTTPException as exc:
                if exc.status_code == 404:
                    return
                raise
        if (detail.get('companyId'), detail.get('projectId'), detail.get('status'), detail.get('assigneeAgentId')) == (
                client.company, row.get('projectId'), row.get('status'), row.get('assigneeAgentId')):
            row['executionBlocker'] = detail.get('executionBlocker')

    async def pending_questions(row):
        async with limit:
            try:
                decisions = await blocker_delivery.owner_decisions(client, row['id'])
                if row.get('status') == 'in_review':
                    approvals = await client.request('GET', 'issues/' + row['id'] + '/approvals')
                    if any(a.get('status') in ('pending', 'revision_requested') for a in approvals):
                        row['_owner_wait'] = 'Jarvis needs your approval before continuing.'
            except HTTPException as exc:
                if exc.status_code == 404:
                    return
                raise
        agents[row['assigneeAgentId']]['questions'].extend(
            {'id': decision['id'], 'question': decision['question'], 'created': decision['created'],
             'task': reference(row), 'mission': links.for_issue(row)['mission']}
            for decision in decisions if decision['status'] == 'pending')

    lookups = [recovery_detail(row) for row in issues.values()
        if row.get('assigneeAgentId') in agents and not row.get('executionBlocker')
        and not row.get('executionRunId') and not row.get('activeRun')
        and not row.get('hiddenAt') and row.get('status') not in ('backlog', 'done', 'cancelled')
        and (row.get('assigneeAgentId') == client.ceo or
             ((row.get('blockerAttention') or {}).get('state') == 'needs_attention'
              and not (row.get('unblockDescriptor') or {}).get('action')
              and not (row.get('blockerAttention') or {}).get('sampleBlockerIdentifier')))]
    if getattr(client, 'workforce', False) and client.ceo in agents:
        blocked_parents = {row.get('parentId') for row in issues.values() if row.get('status') == 'blocked'}
        lookups.extend(pending_questions(row) for row in issues.values()
            if row.get('assigneeAgentId') == client.ceo and not row.get('parentId')
            and not row.get('hiddenAt')
            and row.get('status') not in ('done', 'cancelled')
            and (row.get('status') in ('blocked', 'in_review') or row['id'] in blocked_parents
                 or ((row.get('unblockDescriptor') or {}).get('action') or '').startswith(blocker_delivery.WAITING)))
    await asyncio.gather(*lookups)
    for row in sorted(issues.values(), key=lambda i: i.get('updatedAt') or '', reverse=True):
        state, executor = engagement(row)
        if row.get('_owner_wait') and state != 'active':
            state = 'blocked'
        assignee = row.get('assigneeAgentId')
        for agent_id in {assignee, executor} & agents.keys():
            job_state = 'waiting' if state == 'active' and executor != agent_id else state
            entry = {**reference(row), 'status': row.get('status'), 'state': job_state,
                     'reason': row.get('_owner_wait') if job_state == 'blocked' and row.get('_owner_wait') else work_reason(row, job_state, executor),
                     'assigneeAgentId': assignee,
                     'active_agent_id': executor, **links.for_issue(row)}
            archived = (entry.get('mission') or {}).get('hiddenAt')
            if archived and state != 'closed':
                entry.update(state='paused', reason='This project was archived. Its saved assignments are paused.')
            agents[agent_id]['past_work' if state == 'closed' or archived else 'work'].append(entry)
    for job in links.jobs.values():
        owner = job.get('assigneeAgentId')
        if owner in agents and job.get('status') != 'archived':
            agents[owner]['schedules'].append(links.schedule(job))
    for person in people:
        agent = agents[person['id']]
        agent['activity'], agent['status_reason'] = staff_condition(person, agent['work'])
        agent['questions'].sort(key=lambda question: (question['created'], question['id']), reverse=True)
    return {'ceo_id': client.ceo, 'agents': list(agents.values())}
