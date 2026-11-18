from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from test_tasks import AGENT as WORKER, CEO, headers as HEADERS, transport
from test_phase1 import server


@pytest.mark.parametrize('action,attention,state', [
    ('Await completion of the assigned research.', {'reason': 'active_child'}, 'waiting'),
    ('Pending human approval of the requested change.', {}, 'waiting'),
    ('Review and approve the change.', {}, 'waiting'),
    ('Waiting for required credentials to verify the source.', {'sampleBlockerIdentifier': 'R-4'}, 'blocked'),
    ('Waiting for R-4 and for missing credentials.', {'sampleBlockerIdentifier': 'R-4'}, 'blocked'),
    ('Waiting for access denied by policy to be restored.', {}, 'blocked'),
    ('No mentions could be verified from accessible sources.', {'state': 'needs_attention'}, 'blocked'),
    ('R-4 could not verify the source. Review its evidence.', {'sampleBlockerIdentifier': 'R-4'}, 'waiting'),
    ('R-4 could not verify the source. Required credentials for this job are missing.',
     {'sampleBlockerIdentifier': 'R-4'}, 'blocked'),
])
def test_waiting_and_substantive_blockers(action, attention, state):
    import agent_work
    task = {'status':'blocked', 'unblockDescriptor':{'action':action}, 'blockerAttention':attention}
    assert agent_work.engagement(task) == (state, None)
    assert action in agent_work.work_reason(task, state)


def test_actual_runtime_recovery_and_agent_reason_precedence():
    import agent_work
    task = {'status': 'in_progress', 'executionBlocker': {'cause': 'credentials_revoked', 'nextAction': 'Review the expired credentials.'}}
    assert agent_work.engagement(task) == ('blocked', None)
    reason = agent_work.work_reason(task, 'blocked')
    assert reason == 'Review the expired credentials.'
    jobs = [{'state': 'waiting', 'reason': 'Waiting for review.'}, {'state':'blocked', 'reason':reason}]
    assert agent_work.staff_condition({}, jobs) == ('blocked', reason)
    assert agent_work.staff_condition({}, []) == ('idle', 'No open assignments.')
    assert agent_work.staff_condition({}, [{'state':'active', 'reason':'Running.'}, *jobs])[0] == 'active'


def test_assigned_portrait_and_native_avatar_are_scoped(monkeypatch):
    import agent_work
    asset = str(uuid4())
    worker = {'companyId':'company', 'id':WORKER, 'reportsTo':CEO, 'role':'engineer',
              'metadata':{'jarvis':{'portrait_id':'relay'}}}
    path = f'/api/agents/{WORKER}/portrait/{asset}'
    assert agent_work.portrait_url(worker, CEO) == '/hud/portraits/relay.webp'
    assert agent_work.portrait_url({**worker, 'metadata':{'jarvis':{'portrait_id':'../outside'}}}, CEO) == '/hud/portraits/software.webp'
    person = {**worker, 'appearance':{'customAvatarAssetId':asset}}
    assert agent_work.portrait_url(person, CEO) == path
    image = b'\x89PNG\r\n\x1a\n' + b'fixture'
    fetched = []
    def handler(req):
        if req.url.path.endswith('/agents'):
            return httpx.Response(200,json=[person])
        assert req.url.path == f'/api/assets/{asset}/content'
        fetched.append(asset)
        return httpx.Response(200,headers={'Content-Type':'image/png'},content=image)
    transport(monkeypatch, handler)
    with TestClient(server.app) as client:
        assert client.get(path).status_code == 401
        assert client.get(f'/api/agents/{WORKER}/portrait/{uuid4()}', headers=HEADERS).status_code == 404
        assert client.get(f'/api/agents/{uuid4()}/portrait/{asset}', headers=HEADERS).status_code == 404
        assert fetched == []
        response = client.get(path, headers=HEADERS)
        assert response.content == image and response.headers['content-type'] == 'image/png'


def test_agent_work_links_match_native_executors_and_project_schedules(monkeypatch):
    from agent_work import engagement
    assert engagement({'status': 'done', 'activeRun': {'agentId': CEO, 'status': 'running'}}) == ('closed', None)
    assert engagement({'status': 'in_progress', 'executionRunId': 'stale'}) == ('waiting', None)
    assert engagement({'status': 'todo', 'activeRun': {'agentId': WORKER, 'status': 'queued'}}) == ('queued', None)

    project, mission, cron, run, nested, other = (str(uuid4()) for _ in range(6))
    idle, gone, paused, future = (str(uuid4()) for _ in range(4))
    a = {'companyId': 'company', 'reportsTo': CEO, 'role': 'operator', 'status': 'idle',
         'adapterConfig': {'key': 'never-show'}}
    agents = [{**a, 'id': CEO, 'reportsTo': None}, {**a, 'id': WORKER}, {**a, 'id': idle}, {**a, 'id': paused},
              {**a, 'id': gone, 'status': 'terminated'}, {**a, 'id': 'unrelated', 'reportsTo': None},
              {**a, 'id': 'other-org', 'companyId': 'other'}]
    i = {'companyId': 'company', 'projectId': project, 'status': 'in_progress', 'assigneeAgentId': CEO,
         'executionPolicy': {'secret': 'never-show'}}
    root = {**i, 'id': mission, 'identifier': 'M-1', 'title': 'Project X'}
    routine_run = {**i, 'id': run, 'identifier': 'M-2', 'title': 'A check', 'originKind': 'routine_execution', 'originId': cron,
                   'description': f'[JARVIS MISSION {mission}]\nCheck X', 'status': 'blocked'}
    child = {**i, 'id': nested, 'parentId': run, 'assigneeAgentId': WORKER, 'identifier': 'M-3', 'title': 'Inspect measurements',
             'activeRun': {'status': 'running', 'agentId': WORKER}}
    issues = [root, routine_run, child,
              {**i, 'id': 'past', 'status': 'done', 'assigneeAgentId': WORKER, 'parentId': run},
              {**i, 'id': 'queued', 'parentId': mission, 'assigneeAgentId': paused, 'status': 'todo'},
              {**i, 'id': 'reassigned', 'parentId': mission, 'assigneeAgentId': CEO,
               'activeRun': {'status': 'running', 'agentId': WORKER}},
              {**i, 'id': 'general-run', 'originKind': 'routine_execution', 'originId': 'general', 'status': 'done'},
              {**i, 'id': 'foreign', 'companyId': 'other', 'title': 'never-show'},
              {**i, 'id': 'outsider', 'assigneeAgentId': gone, 'title': 'never-show'},
              {**i, 'id': other, 'originKind': 'routine_execution', 'originId': cron, 'projectId': 'different'},
              {**i, 'id': 'old-job', 'parentId': run, 'originKind': 'manual', 'originRunId': 'not-a-cron'}]
    job = {'id': cron, 'title': 'Daily check', 'companyId': 'company', 'projectId': project, 'assigneeAgentId': CEO,
           'status': 'active', 'triggers': [{'kind': 'schedule', 'enabled': True}], 'env': {'key': 'never-show'},
           'variables': [{'name': 'jarvis_work_scope', 'defaultValue': 'project'},
                         {'name': 'jarvis_mission_id', 'defaultValue': mission}]}
    routines = [job, {**job, 'id': future, 'title': 'Weekly read', 'assigneeAgentId': paused, 'status': 'paused'},
                {**job, 'id': 'general', 'variables': []},
                {**job, 'id': 'outsider-schedule', 'companyId': 'other', 'title': 'never-show'},
                {**job, 'id': 'webhook', 'triggers': [{'kind': 'webhook'}]}]

    def handler(request):
        path = request.url.path
        assert request.method == 'GET'
        if path == '/api/companies/company/agents':
            return httpx.Response(200, json=agents)
        if path == '/api/companies/company/routines':
            return httpx.Response(200, json=routines)
        if path == '/api/companies/company/issues':
            return httpx.Response(200, json=issues)
        if path == f'/api/issues/{mission}':
            return httpx.Response(200, json=root)
        if path.endswith(('/comments', '/runs')):
            return httpx.Response(200, json=[])
        raise AssertionError(path)

    transport(monkeypatch, handler, workforce=True)
    with TestClient(server.app) as client:
        assert client.get('/api/agents/work').status_code == 401
        response = client.get('/api/agents/work', headers=HEADERS)
        assert response.status_code == 200 and 'never-show' not in response.text
        roster = {row['id']: row for row in response.json()['agents']}
        tree = client.get('/api/tasks/' + mission, headers=HEADERS).json()
    assert set(roster) == {CEO, WORKER, paused, idle}
    assert roster[idle]['work'] == roster[idle]['past_work'] == roster[idle]['schedules'] == []
    worker = next(row for row in roster[WORKER]['work'] if row['id'] == nested)
    assert worker['state'] == 'active' and worker['mission']['id'] == mission
    assert worker['work_scope'] == 'project' and worker['mission']['hiddenAt'] is None
    assert worker['cron_job'] == {'id': cron, 'title': 'Daily check'} and worker['run_issue']['id'] == run
    assert [row['id'] for row in roster[WORKER]['past_work']] == ['past'] and roster[WORKER]['schedules'] == []
    assert roster[paused]['work'][0]['state'] == 'queued'
    assert roster[paused]['schedules'][0]['mission']['id'] == mission and not roster[paused]['schedules'][0]['enabled']
    assert {row['id'] for row in tree['schedules']} == {cron, future}
    assert next(row for row in tree['schedules'] if row['id'] == cron)['enabled']
    assert {row['id'] for row in tree['scheduled_runs']} == {run}
    children = {row['id']: row for row in tree['scheduled_runs'][0]['children']}
    assert children[nested]['state'] == 'active' and children[nested]['cron_job'] == worker['cron_job']
    assert children['old-job']['run_issue'] == worker['run_issue']
    assert next(row for row in roster[CEO]['work'] if row['id'] == 'reassigned')['state'] == 'waiting'
    assert next(row for row in roster[WORKER]['work'] if row['id'] == 'reassigned')['state'] == 'active'
    assert next(row for row in roster[CEO]['work'] if row['id'] == other)['cron_job'] is None
    finished = next(row for row in roster[CEO]['past_work'] if row['id'] == 'general-run')
    assert finished['mission'] is None and finished['work_scope'] == 'general'


def test_legacy_routine_links_and_unchanged_historical_scope():
    import agent_work
    from work_scope import description
    mission = str(uuid4())
    other = str(uuid4())
    i = {'companyId': 'co', 'projectId': 'p', 'assigneeAgentId': CEO}
    rows = {row['id']: row for row in [{**i, 'id': mission}, {**i, 'id': other},
            {**i, 'id': 'delegated', 'parentId': mission}, {**i, 'id': 'run'},
            {**i, 'id': 'child', 'parentId': 'run'},
            {**i, 'id': 'stamped', 'originKind': 'routine_execution', 'originId': 'timer',
             'description': description('Prior mission', 'project', other)}]}
    routine = {'id': 'timer', 'title': 'Old timer', 'companyId': 'co', 'projectId': 'p',
               'assigneeAgentId': CEO, 'parentIssueId': 'delegated', 'status': 'active',
               'triggers': [{'kind': 'schedule', 'enabled': True}], 'lastRun': {'linkedIssueId': 'run'}}
    links = agent_work.WorkLinks('co', CEO, rows, [routine])
    assert links.schedule(routine)['mission_id'] == mission
    assert links.run_scope(rows['run'])['mission_id'] == mission
    assert links.for_issue(rows['child'])['mission']['id'] == mission
    assert links.for_issue(rows['child'])['run_issue']['id'] == 'run'
    assert links.for_issue(rows['stamped'])['mission']['id'] == other
    forced_general = {**routine, 'variables': [{'name': 'jarvis_work_scope', 'defaultValue': 'general'}]}
    assert links.schedule(forced_general)['mission'] is None
