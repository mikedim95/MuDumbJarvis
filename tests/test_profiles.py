import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'hermes-plugin/jarvis_readonly/profile_registry.py'
spec = importlib.util.spec_from_file_location('profiles_test', path)
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)


def test_hire_portraits_are_persisted_reusable_catalog_choices():
    turn = {'company':'company', 'issue':'issue'}
    def hire(roster=(), choice=None):
        return profiles.hire_body(turn, {'id':'ceo'}, 'research', 'Analyst', 'Document source evidence',
                                  choice, roster)['metadata']['jarvis']['portrait_id']
    assert hire() == hire()
    assert hire(choice='halo') == 'halo'
    used = []
    for _ in profiles.HIRE_PORTRAITS:
        selected = hire(used)
        assert selected not in [a['metadata']['jarvis']['portrait_id'] for a in used]
        used.append({'metadata':{'jarvis':{'portrait_id':selected}}})
    assert hire(used) in profiles.HIRE_PORTRAITS
    with pytest.raises(ValueError):
        hire(choice='../avatar')


def test_catalog_is_templates_and_preserves_single_model_slot():
    data = profiles.catalog()
    assert set(data['profiles']) == {'research', 'software_development', 'system_administration', 'documentation', 'security_analysis'}
    assert data['inference_slots'] == 1
    assert all('employees' not in item for item in data['profiles'].values())


def test_hire_snapshot_is_bounded_and_deterministic():
    turn = {'company': 'company', 'issue': 'issue'}
    body = profiles.hire_body(turn, {'id': 'ceo'}, 'software_development', 'Developer', 'Essential isolated code and tests')
    assert body['adapterType'] == 'hermes_gateway' and body['adapterConfig'] == {}
    assert body['sourceIssueId'] == 'issue' and body['reportsTo'] == 'ceo'
    assert body['permissions'] == {'canCreateAgents': False, 'canCreateSkills': False}
    assert body['runtimeConfig']['heartbeat']['enabled'] is False
    assert body['metadata']['jarvis']['provisioned'] is False
    assert body['metadata']['jarvis']['runtime_id'] == profiles.hire_body(turn, {'id': 'ceo'}, 'software_development', 'Other title', 'Another reason')['metadata']['jarvis']['runtime_id']
    assert body['metadata']['jarvis']['profile_sha256'] == profiles.profile('software_development')['sha256']


@pytest.mark.parametrize('status', ['pending_approval', 'paused', 'terminated'])
def test_inactive_or_unapproved_employee_cannot_receive_work(status):
    assert not profiles.ready_employee({'status': status, 'lifecycleState': 'ready'})


def test_native_ready_does_not_bypass_managed_runtime_provisioning():
    agent = {'status': 'idle', 'lifecycleState': 'ready', 'metadata': {'jarvis': {'managed': True}}}
    assert not profiles.ready_employee(agent)
    agent['metadata']['jarvis']['provisioned'] = True
    assert profiles.ready_employee(agent)


def test_unregistered_profile_does_not_grant_arbitrary_tools():
    with pytest.raises(ValueError):
        profiles.profile('unrestricted_host')


def test_provisioner_requires_matching_human_approval_and_frozen_authority():
    path = Path(__file__).resolve().parents[1] / 'deploy/staffing.py'
    spec = importlib.util.spec_from_file_location('staffing_test', path)
    staffing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(staffing)
    env = {'PAPERCLIP_COMPANY_ID': 'company', 'PAPERCLIP_CEO_AGENT_ID': 'ceo', 'PAPERCLIP_AGENT_ID': 'old-worker'}
    body = profiles.hire_body({'company': 'company', 'issue': 'issue'}, {'id': 'ceo'}, 'software_development', 'Developer', 'Essential isolated development')
    agent = {**body, 'id': '11111111-1111-4111-8111-111111111111', 'companyId': 'company', 'status': 'idle'}
    approval = {'type': 'hire_agent', 'status': 'pending', 'requestedByAgentId': 'ceo',
        'payload': {'agentId': agent['id'], 'metadata': body['metadata']}}
    assert staffing.validate_agent(agent, [approval], env) is None
    approval['status'] = 'rejected'
    assert staffing.validate_agent(agent, [approval], env) is None
    approval['status'] = 'approved'
    assert staffing.validate_agent(agent, [approval], env)['id'] == 'software_development'
    agent['status'] = 'paused'
    assert staffing.validate_agent(agent, [approval], env)['id'] == 'software_development'
    agent['pauseReason'] = 'manual'
    assert staffing.validate_agent(agent, [approval], env) is None
    agent.pop('pauseReason')
    agent['metadata']['jarvis']['provisioned'] = True
    assert staffing.validate_agent(agent, [approval], env) is None
    agent['status'] = 'idle'
    agent['metadata']['jarvis']['profile_sha256'] = 'changed-authority'
    with pytest.raises(ValueError, match='capability snapshot'):
        staffing.validate_agent(agent, [approval], env)


def test_existing_worker_exception_cannot_grant_an_unapproved_coding_profile():
    path = Path(__file__).resolve().parents[1] / 'deploy/staffing.py'
    spec = importlib.util.spec_from_file_location('staffing_test_two', path)
    staffing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(staffing)
    body = profiles.hire_body({'company': 'company', 'issue': 'issue'}, {'id': 'ceo'}, 'software_development', 'Developer', 'Essential code')
    body['metadata']['jarvis']['origin'] = 'existing_worker'
    agent = {**body, 'id': '11111111-1111-4111-8111-111111111111', 'companyId': 'company', 'status': 'idle'}
    env = {'PAPERCLIP_COMPANY_ID': 'company', 'PAPERCLIP_CEO_AGENT_ID': 'ceo', 'PAPERCLIP_AGENT_ID': agent['id']}
    assert staffing.validate_agent(agent, [], env) is None
    assert staffing.same_runtime_config({'model': 'local', '_config_version': 1}, {'model': 'local'})
    assert not staffing.same_runtime_config({'model': 'remote', '_config_version': 1}, {'model': 'local'})
    assert not staffing.same_runtime_config({'model': 'local', 'extra_tools': ['host']}, {'model': 'local'})
