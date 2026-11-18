import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy'))
import staffing
import configure_codex_workforce as workforce

COMPANY = '11111111-1111-4111-8111-111111111111'
CEO = '22222222-2222-4222-8222-222222222222'
EMPLOYEE = '33333333-3333-4333-8333-333333333333'
ENV = {'PAPERCLIP_COMPANY_ID': COMPANY, 'PAPERCLIP_CEO_AGENT_ID': CEO,
    'PAPERCLIP_AGENT_ID': '44444444-4444-4444-8444-444444444444',
    'JARVIS_EXECUTION_PROOF_KEY': 'unit-test-workforce-signing-key',
    'JARVIS_RUNTIME_MODEL': 'old-local-model'}


def employee(profile='security_analysis'):
    body = workforce.bootstrap_hire_body(COMPANY, CEO, profile)
    agent = {**body, 'id': EMPLOYEE, 'companyId': COMPANY, 'status': 'idle', 'lifecycleState': 'ready'}
    agent['metadata']['jarvis']['inference_configuration'] = staffing.workforce_record(
        agent, ENV, staffing.registry.profile(profile))
    return agent


def approval(agent):
    return {'type': 'hire_agent', 'status': 'approved', 'requestedByAgentId': None,
        'requestedByUserId': 'actual-human', 'decidedByUserId': 'actual-human',
        'payload': {'agentId': agent['id'], 'metadata': copy.deepcopy(agent['metadata'])}}


def test_initial_staff_reuses_existing_roles_without_adding_an_unneeded_team():
    first, second = employee('research'), employee('software_development')
    second['id'] = '55555555-5555-4555-8555-555555555555'
    selected = workforce.choose_team([first, second], CEO)
    assert selected['research'] is first and selected['software_development'] is second
    assert [p for p, a in selected.items() if a is None] == ['system_administration', 'security_analysis']
    with pytest.raises(ValueError, match='duplicate'):
        workforce.choose_team([first, copy.deepcopy(first)], CEO)


def test_bootstrap_hire_has_true_operator_provenance_and_no_fake_source_issue():
    body = workforce.bootstrap_hire_body(COMPANY, CEO, 'system_administration')
    assert 'sourceIssueId' not in body and 'source_issue_id' not in body['metadata']['jarvis']
    assert body['metadata']['jarvis']['origin'] == 'operator_authorized_workforce'
    assert body['permissions'] == {'canCreateAgents': False, 'canCreateSkills': False}
    assert body['runtimeConfig']['heartbeat']['enabled'] is False
    assert body['runtimeConfig']['heartbeat']['maxConcurrentRuns'] == 1
    assert body['metadata']['jarvis']['profile_sha256'] == staffing.registry.profile('system_administration')['sha256']


def test_operator_bootstrap_needs_native_approved_human_decision_and_signed_role():
    agent = employee(); native = approval(agent)
    assert staffing.validate_agent(agent, [native], ENV)['id'] == 'security_analysis'
    for field, value in [('status', 'pending'), ('status', 'rejected'), ('requestedByUserId', None),
                         ('decidedByUserId', None), ('requestedByAgentId', 'unrelated-agent')]:
        changed = copy.deepcopy(native); changed[field] = value
        assert staffing.validate_agent(agent, [changed], ENV) is None
    changed = copy.deepcopy(agent)
    changed['metadata']['jarvis']['inference_configuration']['agent_id'] = CEO
    with pytest.raises(PermissionError):
        staffing.validate_agent(changed, [native], ENV)


def test_native_redacted_legacy_bootstrap_marker_keeps_exact_approved_scope():
    agent = employee(); agent['metadata']['jarvis'].pop('bootstrap_request')
    agent['metadata']['jarvis']['bootstrap_authorization'] = '[REDACTED]'
    native = approval(agent)
    assert staffing.validate_agent(agent, [native], ENV)['id'] == 'security_analysis'
    changed = copy.deepcopy(agent)
    changed['metadata']['jarvis']['hiring_reason'] = 'Someone requested some staff'
    assert staffing.validate_agent(changed, [native], ENV) is None
    changed = copy.deepcopy(native)
    changed['payload']['metadata']['jarvis']['runtime_id'] = 'a' * 24
    with pytest.raises(ValueError, match='human-approved snapshot'):
        staffing.validate_agent(agent, [changed], ENV)


def test_codex_selection_cannot_borrow_another_employees_authority():
    agent = employee(); item = staffing.registry.profile('security_analysis')
    model, record = staffing.selected_inference(agent, item, ENV)
    assert model == 'gpt-6.1-sol' and record['agent_id'] == EMPLOYEE
    changed = copy.deepcopy(agent); changed['id'] = CEO
    with pytest.raises(PermissionError):
        staffing.selected_inference(changed, item, ENV)


def test_codex_config_keeps_scoped_tool_authority_and_disables_auxiliary_inference():
    source = {'model': {'provider': 'custom'}, 'providers': {'local': {}},
        'agent': {'disabled_toolsets': ['browser', 'delegation'], 'max_turns': 12},
        'platform_toolsets': {'api_server': ['file', 'jarvis_employee']},
        'terminal': {'backend': 'ssh', 'ssh_host': 'private-sandbox'}}
    actual = staffing.codex_config(source)
    assert actual['agent'] == source['agent'] and actual['platform_toolsets'] == source['platform_toolsets']
    assert actual['terminal'] == source['terminal'] and source['model']['provider'] == 'custom'
    assert actual['model']['provider'] == 'openai-codex' and 'providers' not in actual
    assert actual['fallback_model'] is None and actual['fallback_providers'] == []
    assert actual['compression'] == {'enabled': False, 'prepare_ahead': False}
    assert actual['auxiliary']['title_generation'] == {'enabled': False, 'model_upgrade_enabled': False}


def test_shared_oauth_migration_removes_only_codex_shadow_grant(tmp_path):
    auth = tmp_path / 'auth.json'
    auth.write_text(json.dumps({'providers': {'openai-codex': {'tokens': 'old-copy'}, 'other': {'value': 'retain'}},
        'credential_pool': {'openai-codex': ['old-copy'], 'other': ['retain']}}))
    workforce.migrate_profile_auth(auth)
    actual = json.loads(auth.read_text())
    assert actual['providers'] == {'other': {'value': 'retain'}}
    assert actual['credential_pool'] == {'other': ['retain']}
    assert auth.stat().st_mode & 0o777 == 0o600


def test_future_native_approved_hire_gets_fresh_identity_bound_codex_record(tmp_path, monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(staffing, 'ROOT', tmp_path)
    (tmp_path / 'deploy').mkdir(); (tmp_path / 'deploy/codex-workforce.env').write_text('enabled')
    agent = employee(); agent['metadata']['jarvis'].pop('inference_configuration')
    board = Mock(env=ENV)
    board.api.return_value = agent
    staffing.stage_workforce_employee(board, agent, staffing.registry.profile('security_analysis'))
    calls = board.api.call_args_list
    assert calls[0].args[:2] == ('POST', '/agents/' + EMPLOYEE + '/pause')
    patch=next(call for call in calls if call.args[0]=='PATCH')
    record = patch.args[2]['metadata']['jarvis']['inference_configuration']
    assert record['agent_id'] == EMPLOYEE and record['profile'] == 'security_analysis'
    staffing.inference_policy.validate(record, COMPANY, ENV['JARVIS_EXECUTION_PROOF_KEY'])


def test_termination_stops_only_matching_owned_compute_and_keeps_state(monkeypatch):
    from unittest.mock import Mock
    agent = employee(); agent['status'] = 'terminated'
    rid = agent['metadata']['jarvis']['runtime_id']
    board = Mock(env=ENV)
    inspect = Mock(return_value={'Config': {'Labels': {staffing.MANAGED: rid}}, 'State': {'Running': True}})
    run = Mock(); monkeypatch.setattr(staffing, 'inspect', inspect); monkeypatch.setattr(staffing, 'run', run)
    assert staffing.stop_terminated_employee(board, agent)
    assert [call.args[0] for call in run.call_args_list] == [
        ['docker', 'stop', '--timeout', '30', 'jarvis-employee-' + rid],
        ['docker', 'stop', '--timeout', '30', 'jarvis-sandbox-' + rid]]
    board.api.assert_not_called()
    assert all('rm' not in call.args[0] for call in run.call_args_list)


def test_termination_cannot_stop_unmanaged_or_paused_resources(monkeypatch):
    from unittest.mock import Mock
    board = Mock(env=ENV); run = Mock(); monkeypatch.setattr(staffing, 'run', run)
    agent = employee(); agent['status'] = 'paused'
    assert not staffing.stop_terminated_employee(board, agent)
    agent['status'] = 'terminated'
    monkeypatch.setattr(staffing, 'inspect', Mock(return_value={
        'Config': {'Labels': {staffing.MANAGED: 'someone-else'}}, 'State': {'Running': True}}))
    with pytest.raises(ValueError, match='not operator-owned'):
        staffing.stop_terminated_employee(board, agent)
    run.assert_not_called()
