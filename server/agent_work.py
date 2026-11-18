"""Read-only staff assignments and their native mission and routine links."""
import asyncio

from fastapi import HTTPException

import work_scope


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
    if status in ('backlog', 'todo'):
        return 'queued', None
    return 'waiting', None


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
    scoped = [job for job in routines if not project or job.get('projectId') == project]
    links = WorkLinks(client.company, client.ceo, issues, scoped)
    agents = {person['id']: {**{key: person.get(key) for key in ('id', 'name', 'title', 'role', 'status', 'reportsTo')},
                             'work': [], 'past_work': [], 'schedules': []} for person in people}
    for row in sorted(issues.values(), key=lambda i: i.get('updatedAt') or '', reverse=True):
        state, executor = engagement(row)
        assignee = row.get('assigneeAgentId')
        for agent_id in {assignee, executor} & agents.keys():
            job_state = 'waiting' if state == 'active' and executor != agent_id else state
            entry = {**reference(row), 'status': row.get('status'), 'state': job_state, 'assigneeAgentId': assignee,
                     'active_agent_id': executor, **links.for_issue(row)}
            agents[agent_id]['past_work' if state == 'closed' else 'work'].append(entry)
    for job in links.jobs.values():
        owner = job.get('assigneeAgentId')
        if owner in agents and job.get('status') != 'archived':
            agents[owner]['schedules'].append(links.schedule(job))
    return {'ceo_id': client.ceo, 'agents': list(agents.values())}
