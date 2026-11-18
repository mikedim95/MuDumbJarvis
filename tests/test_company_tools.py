"""Bounded native company management, with real CEO scope checks and mocked REST."""
import importlib.util
import json
import sys

import pytest

from test_ceo_tools import plugin, COMPANY, CEO, ROOT, PROJECT, WORKER, CHILD

OTHER_PROJECT = '77777777-7777-4777-8777-777777777777'
APPROVAL = '88888888-8888-4888-8888-888888888888'


@pytest.fixture
def company(plugin, monkeypatch):
    directory = plugin.tools.__file__.rsplit('/', 1)[0]
    name = plugin.tools.__package__ + '.company_tools'
    spec = importlib.util.spec_from_file_location(name, directory + '/company_tools.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module); spec.loader.exec_module(module)
    plugin.company = module
    plugin.turn['inference_configuration'] = {'version': 3}
    plugin.projects = [{'id': PROJECT, 'companyId': COMPANY, 'name': 'General Operations', 'status': 'in_progress'}]
    plugin.project_nonces = {}
    original_api = plugin.reporting.api
    def api(method, path, body=None, run_id=None):
        if method == 'GET' and path == '/companies/' + COMPANY + '/projects':
            plugin.calls.append((method, path, body, run_id)); return plugin.projects
        if method == 'POST' and path == '/companies/' + COMPANY + '/projects':
            plugin.calls.append((method, path, body, run_id))
            project = plugin.project_nonces.setdefault(body['idempotencyKey'],
                {**body, 'id': OTHER_PROJECT, 'companyId': COMPANY})
            if not any(p['id'] == project['id'] for p in plugin.projects): plugin.projects.append(project)
            return project
        if method == 'POST' and path == '/companies/' + COMPANY + '/approvals':
            plugin.calls.append((method, path, body, run_id))
            approval = {**body, 'id': APPROVAL, 'companyId': COMPANY, 'status': 'pending'}
            plugin.approvals.append(approval); return approval
        if method == 'PATCH' and path == '/issues/' + ROOT and 'projectId' in body:
            plugin.calls.append((method, path, body, run_id)); plugin.issue.update(body); return plugin.issue
        return original_api(method, path, body, run_id)
    monkeypatch.setattr(plugin.reporting, 'api', api)
    return plugin


def operation(state, args):
    return json.loads(state.company.manage(args))


def writes(state):
    return [call for call in state.calls if call[0] != 'GET']


@pytest.mark.parametrize('version', [None, 1, 2])
def test_company_operations_require_workforce_v3_not_readonly_demo(company, version):
    company.turn['inference_configuration'] = {'version': version}
    with pytest.raises(PermissionError, match='workforce policy'):
        operation(company, {'action': 'context'})
    assert writes(company) == []
    assert not any(path.endswith('/projects') for _, path, _, _ in company.calls)


@pytest.mark.parametrize('change', ['worker-runtime', 'wrong-native-role', 'different-assignee', 'foreign-company', 'different-run'])
def test_company_management_reuses_authenticated_ceo_scope_before_any_company_write(company, monkeypatch, change):
    if change == 'worker-runtime': monkeypatch.setenv('JARVIS_AGENT_ROLE', 'research')
    elif change == 'wrong-native-role': company.me['role'] = 'researcher'
    elif change == 'different-assignee': company.issue['assigneeAgentId'] = WORKER
    elif change == 'foreign-company': company.issue['companyId'] = 'foreign'
    else: company.issue['executionRunId'] = 'unrelated-run'
    with pytest.raises(PermissionError): operation(company, {'action': 'create_project', 'name': 'Review'})
    assert writes(company) == []


def test_company_context_contains_only_native_company_direct_reports_and_redacted_fields(company):
    company.projects.append({'id': OTHER_PROJECT, 'companyId': 'foreign', 'name': 'Private foreign project'})
    company.employees[0]['metadata'] = {'jarvis': {'profile': 'research'}}
    company.employees.extend([
        {'id': 'foreign', 'companyId': 'foreign', 'reportsTo': CEO, 'name': 'Foreign private employee'},
        {'id': 'other-manager', 'companyId': COMPANY, 'reportsTo': WORKER, 'name': 'Unrelated employee'}])
    company.approvals = [{'id': APPROVAL, 'type': 'hire_agent', 'status': 'pending',
        'payload': {'apiKey': 'private-test-credential'}}]
    data = operation(company, {'action': 'context'})
    assert [p['id'] for p in data['projects']] == [PROJECT]
    assert [a['id'] for a in data['employees']] == [WORKER]
    assert data['employees'][0]['profile'] == 'research'
    assert data['approvals'] == [{'id': APPROVAL, 'type': 'hire_agent', 'status': 'pending', 'decisionNote': None}]
    assert 'private-test-credential' not in json.dumps(data)
    assert writes(company) == []


def test_project_creation_records_native_plan_and_reuses_company_name_without_duplicate(company):
    args = {'action': 'create_project', 'name': '  Incident Research  ',
        'description': 'A bounded native project.', 'repository_url': 'https://github.com/example/repository'}
    first = operation(company, args)
    replay = operation(company, {**args, 'name': 'incident research'})
    assert first['created'] is True and first['host_workspace_mounted'] is False
    assert replay['created'] is False and replay['project_id'] == first['project_id']
    creations = [call for call in writes(company) if call[1].endswith('/projects')]
    assert len(creations) == 1 and len(company.project_nonces) == 1
    body = creations[0][2]
    assert body['idempotencyKey'].startswith('jarvis-project:') and body['status'] == 'planned'
    assert body['repositoryUrls'] == ['https://github.com/example/repository']
    assert creations[0][3] == company.turn['run']
    plan = next(i for i, call in enumerate(writes(company)) if '[JARVIS CEO PLAN decision=self]' in (call[2] or {}).get('comment', ''))
    create = next(i for i, call in enumerate(writes(company)) if call[1].endswith('/projects'))
    assert plan < create


def test_project_idempotency_key_is_company_scoped_and_stable_across_retried_creation(company):
    operation(company, {'action': 'create_project', 'name': 'Stable Project'})
    first = next(call[2]['idempotencyKey'] for call in writes(company) if call[1].endswith('/projects'))
    # Simulate the uncertain client read before the listing reflects the native creation.
    company.projects[:] = [company.projects[0]]
    operation(company, {'action': 'create_project', 'name': 'STABLE PROJECT'})
    creations = [call for call in writes(company) if call[1].endswith('/projects')]
    assert creations[1][2]['idempotencyKey'] == first and len(company.project_nonces) == 1


@pytest.mark.parametrize('url', ['http://github.com/owner/repo', 'https://private.example/owner/repo',
    'https://user:secret@github.com/owner/repo', 'https://github.com/owner/repo?token=private',
    'https://github.com/owner/repo#branch', 'https://github.com:4444/owner/repo',
    'https://github.com/../repo', 'https://github.com/owner/..', 'https://github.com/owner/re\npo',
    'https://github.com/owner/repo/extra', 'https://github.com/owner\\repo',
    'file:///etc/passwd', 'git@github.com:owner/repo'])
def test_project_repository_metadata_rejects_unsafe_urls_without_creating_or_fetching(company, url):
    with pytest.raises(ValueError, match='Repository'):
        operation(company, {'action': 'create_project', 'name': 'New Project', 'repository_url': url})
    assert not any(path.endswith('/projects') and method == 'POST' for method, path, _, _ in company.calls)
    assert not any('github.com' in path or '/terminate' in path for _, path, _, _ in company.calls)


def test_existing_project_name_in_other_company_is_never_reused(company):
    company.projects.append({'id': 'foreign', 'companyId': 'foreign', 'name': 'Same Name'})
    result = operation(company, {'action': 'create_project', 'name': 'Same Name'})
    assert result['created'] is True and result['project_id'] != 'foreign'


def test_project_assignment_is_native_and_requires_no_existing_child_tree(company):
    company.projects.append({'id': OTHER_PROJECT, 'companyId': COMPANY, 'name': 'Managed'})
    result = operation(company, {'action': 'set_project', 'project_id': OTHER_PROJECT})
    assert result['associated'] is True and result['issue_id'] == ROOT
    assert company.turn['project'] == company.issue['projectId'] == OTHER_PROJECT
    changes = [call for call in writes(company) if 'projectId' in (call[2] or {})]
    assert changes == [('PATCH', '/issues/' + ROOT, {'projectId': OTHER_PROJECT}, company.turn['run'])]


@pytest.mark.parametrize('failure', ['foreign-project', 'existing-child'])
def test_project_assignment_cannot_move_foreign_project_or_existing_task_history(company, failure):
    company.projects.append({'id': OTHER_PROJECT, 'companyId': 'foreign' if failure == 'foreign-project' else COMPANY, 'name': 'Other'})
    if failure == 'existing-child': company.children = [{'id': CHILD, 'parentId': ROOT, 'companyId': COMPANY, 'projectId': PROJECT}]
    with pytest.raises(PermissionError if failure == 'foreign-project' else ValueError):
        operation(company, {'action': 'set_project', 'project_id': OTHER_PROJECT})
    assert company.turn['project'] == PROJECT
    assert not any('projectId' in (body or {}) for _, _, body, _ in writes(company))


def test_staff_removal_only_requests_native_approval_and_never_terminates_from_agent(company):
    reason = 'The human requested removal of this employee while retaining historical results.'
    data = operation(company, {'action': 'request_termination', 'agent_id': WORKER, 'reason': reason})
    replay = operation(company, {'action': 'request_termination', 'agent_id': WORKER, 'reason': reason})
    assert data['executed'] is replay['executed'] is False
    assert data['approval_id'] == replay['approval_id'] == APPROVAL and data['status'] == 'pending'
    approvals = [call for call in writes(company) if call[1].endswith('/approvals')]
    assert len(approvals) == 1
    body = approvals[0][2]
    assert body['type'] == 'request_board_approval' and body['requestedByAgentId'] == CEO
    assert body['issueIds'] == [ROOT]
    assert body['payload']['kind'] == 'jarvis_staff_termination' and body['payload']['agentId'] == WORKER
    assert company.turn['action_approval'] == {'id': APPROVAL, 'status': 'pending'}
    assert company.employees[0]['status'] == 'idle'
    assert not any(method == 'DELETE' or '/terminate' in path or '/approve' in path for method, path, _, _ in company.calls)


@pytest.mark.parametrize('change', ['self', 'other-manager', 'foreign-company', 'missing-agent'])
def test_termination_proposal_must_target_native_company_direct_report(company, change):
    target = WORKER
    if change == 'self':
        target = CEO; company.employees.append({**company.me, 'reportsTo': CEO})
    elif change == 'other-manager': company.employees[0]['reportsTo'] = WORKER
    elif change == 'foreign-company': company.employees[0]['companyId'] = 'foreign'
    else: target = CHILD
    with pytest.raises(PermissionError):
        operation(company, {'action': 'request_termination', 'agent_id': target, 'reason': 'Human requested removal with history preserved.'})
    assert company.approvals == []
    assert not any('/terminate' in path or method == 'DELETE' for method, path, _, _ in company.calls)


def test_already_terminated_employee_history_remains_visible_without_new_mutation(company):
    company.employees[0]['status'] = 'terminated'
    data = operation(company, {'action': 'request_termination', 'agent_id': WORKER})
    assert data['status'] == 'terminated' and data['history_preserved'] is True
    assert company.employees[0]['id'] == WORKER and company.approvals == []
    assert not any('/agents/' in path and method in ('POST', 'PATCH', 'DELETE') for method, path, _, _ in company.calls)


def test_requested_team_rename_is_confirmed_and_retries_do_not_write_again(company, monkeypatch):
    original_api = company.reporting.api
    def api(method, path, body=None, run_id=None):
        if method == 'PATCH' and path == '/agents/' + WORKER:
            company.calls.append((method, path, body, run_id))
            assert body == {'name': 'JARVIS Research'} and run_id == company.turn['run']
            company.employees[0].update(body)
            return company.employees[0]
        return original_api(method, path, body, run_id)
    monkeypatch.setattr(company.reporting, 'api', api)
    args = {'action':'rename_agent', 'agent_id':WORKER, 'name':'JARVIS Research'}
    assert operation(company, args) == {'agent_id':WORKER, 'name':'JARVIS Research', 'renamed':True}
    assert operation(company, args)['renamed'] is False
    assert len([c for c in writes(company) if c[1].startswith('/agents/')]) == 1
    assert not company.approvals
    with pytest.raises(PermissionError):
        operation(company, {**args, 'agent_id':OTHER_PROJECT})
    with pytest.raises(ValueError):
        operation(company, {**args, 'name':'name\ninvalid'})


def test_rename_of_an_osint_agent_named_research_uses_the_management_receipt(company, monkeypatch):
    original_api = company.reporting.api
    def api(method,path,body=None,run_id=None):
        if method=='PATCH' and path=='/agents/'+WORKER:
            company.employees[0].update(body)
            return company.employees[0]
        return original_api(method,path,body,run_id)
    monkeypatch.setattr(company.reporting,'api',api)
    company.turn.update(needs_research=True,needs_inventory=False,response='Renamed the agent to JARVIS Research.')
    operation(company,{'action':'rename_agent','agent_id':WORKER,'name':'JARVIS Research'})
    company.tools.finalize(company.turn,completed=True)
    patch=[c for c in company.calls if c[0]=='PATCH' and c[1]=='/issues/'+ROOT][-1]
    assert patch[2]['status']=='done'
