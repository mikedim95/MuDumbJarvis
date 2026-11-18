import importlib.util
import hashlib
import hmac
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'hermes-plugin/jarvis_readonly/inference_policy.py'
spec = importlib.util.spec_from_file_location('model_policy_under_test', path)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
KEY = 'test-operator-key'
BASE = 'jarvis-hermes-aigoat24:3b'


def record():
    data = {'version': 1, 'company_id': 'company', 'provider': 'local_ollama',
        'model': 'jarvis-hermes-qwen24:7b', 'model_digest': 'a' * 64, 'inference_slots': 1,
        'cpu_threads': 24, 'context_length': 65536, 'source': 'operator_model_selection', 'selected_at': '2026-11-13'}
    return {**data, 'signature': policy.signature(data, KEY)}


@pytest.mark.parametrize('field,value', [('model', 'cloud-model'), ('company_id', 'other'),
    ('inference_slots', 24), ('model_digest', 'b' * 64), ('provider', 'cloud')])
def test_model_selection_cannot_be_forged_or_cross_company(field, value):
    current = record()
    assert policy.validate(current, 'company', KEY) == current
    with pytest.raises(PermissionError): policy.validate({**current, field: value}, 'company', KEY)


def test_employee_matches_immutable_configuration_without_master_key(monkeypatch):
    r = record(); agent = {'companyId': 'company', 'metadata': {'jarvis': {'inference_configuration': r}}}
    monkeypatch.delenv('JARVIS_EXECUTION_PROOF_KEY', raising=False)
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', r['model'])
    monkeypatch.setenv('JARVIS_INFERENCE_CONFIGURATION', json.dumps(r))
    assert policy.runtime_selection(agent, BASE) == (r['model'], r)
    agent['metadata']['jarvis']['inference_configuration'] = {**r, 'model': 'unreviewed'}
    with pytest.raises(PermissionError): policy.runtime_selection(agent, BASE)


def test_frozen_historical_model_proof_remains_valid_after_operator_selection():
    r = record(); agent = {'companyId': 'company', 'metadata': {'jarvis': {'inference_configuration': r}}}
    assert policy.proof_model({}, agent, BASE, KEY) == BASE
    assert policy.proof_model({'inference_configuration': r}, agent, BASE, KEY) == r['model']
    agent['metadata']['jarvis'] = {'inference_configuration_history': [r]}
    assert policy.proof_model({'inference_configuration': r}, agent, BASE, KEY) == r['model']
    agent['metadata']['jarvis'] = {}
    with pytest.raises(PermissionError): policy.proof_model({'inference_configuration': r}, agent, BASE, KEY)


def test_unrecorded_override_does_not_silently_change_runtime(monkeypatch):
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', 'jarvis-hermes-qwen24:7b')
    monkeypatch.delenv('JARVIS_INFERENCE_CONFIGURATION', raising=False)
    with pytest.raises(PermissionError): policy.runtime_selection({'companyId': 'company'}, BASE)


def cloud_record():
    data = {'version': 2, 'company_id': 'company', 'agent_id': '11111111-1111-4111-8111-111111111111',
        'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'endpoint': policy.CODEX_ENDPOINT,
        'context_length': 65536, 'inference_slots': 1, 'fallback_allowed': False,
        'user_authorized': True, 'source': 'operator_authorized_codex_demo', 'authority_scope': 'ceo_readonly_demo'}
    return {**data, 'signature': policy.signature(data, KEY)}


@pytest.mark.parametrize('field,value', [('provider', 'local_ollama'), ('model', 'other'),
    ('endpoint', 'https://untrusted.example/v1'), ('user_authorized', False), ('fallback_allowed', True),
    ('company_id', 'foreign'), ('inference_slots', 2)])
def test_explicit_codex_demo_does_not_authorize_other_providers_routes_or_permissions(field, value):
    good = cloud_record()
    assert policy.validate(good, 'company', KEY) == good
    bad = {**good, field: value}
    bad['signature'] = policy.signature(bad, KEY)
    with pytest.raises(PermissionError): policy.validate(bad, 'company', KEY)


def test_cloud_demo_is_bound_to_one_employee_and_keeps_old_evidence_valid(monkeypatch):
    r = cloud_record()
    agent = {'id': r['agent_id'], 'companyId': 'company', 'metadata': {'jarvis': {'inference_configuration': r}}}
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', r['model'])
    monkeypatch.setenv('JARVIS_INFERENCE_CONFIGURATION', json.dumps(r))
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', KEY)
    assert policy.runtime_selection(agent, BASE) == (r['model'], r)
    assert policy.proof_model({'agent_id': agent['id'], 'inference_configuration': r}, agent, BASE, KEY) == r['model']
    assert policy.proof_model({}, agent, BASE, KEY) == BASE
    with pytest.raises(PermissionError): policy.runtime_selection({**agent, 'id': 'another'}, BASE)
    with pytest.raises(PermissionError):
        policy.proof_model({'agent_id': 'another', 'inference_configuration': r}, agent, BASE, KEY)


@pytest.mark.parametrize('tool,args', [('request_employee', {}), ('terminal', {'command':'id'}),
    ('request_action_approval', {}), ('paperclip_ceo', {'action':'delegate'}),
    ('paperclip_ceo', {'action':'request_hire'}), ('paperclip_ceo', {'action':'request_correction'}),
    ('paperclip_ceo', {'action':'plan','decision':'hire'})])
def test_codex_demo_cannot_expand_hiring_execution_or_host_access(tool, args):
    assert not policy.demo_tool_allowed(cloud_record(), tool, args)
    assert policy.demo_tool_allowed(record(), tool, args), 'Old local authority remains separately governed'


def test_codex_demo_keeps_real_reads_self_plan_and_internal_deliverables():
    r=cloud_record()
    for tool in ['paperclip_context','publish_artifact','local_ollama_models']:
        assert policy.demo_tool_allowed(r,tool,{})
    assert policy.demo_tool_allowed(r,'paperclip_ceo',{'action':'plan','decision':'self'})


def workforce_record(profile='ceo'):
    data = {'version': 3, 'company_id': 'company', 'agent_id': '11111111-1111-4111-8111-111111111111',
        'profile': profile, 'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'endpoint': policy.CODEX_ENDPOINT,
        'context_length': 65536, 'inference_slots': 1, 'fallback_allowed': False,
        'user_authorized': True, 'source': 'operator_authorized_codex_workforce',
        'authority_scope': 'ceo_orchestration' if profile == 'ceo' else 'approved_capability_profile',
        'hiring_approval_required': True, 'sensitive_action_approval_required': True}
    if profile != 'ceo':
        data['profile_sha256'] = 'a' * 64
    return {**data, 'signature': policy.signature(data, KEY)}


def workforce_agent(r):
    meta = {'inference_configuration': r}
    if r['profile'] != 'ceo':
        meta.update(profile=r['profile'], profile_sha256=r['profile_sha256'])
    return {'id': r['agent_id'], 'companyId': 'company', 'role': policy.WORKFORCE_ROLES[r['profile']],
        'metadata': {'jarvis': meta}}


@pytest.mark.parametrize('profile', list(policy.WORKFORCE_ROLES))
def test_workforce_roles_use_agent_bound_codex_without_changing_frozen_capabilities(monkeypatch, profile):
    r = workforce_record(profile); agent = workforce_agent(r)
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', r['model'])
    monkeypatch.setenv('JARVIS_INFERENCE_CONFIGURATION', json.dumps(r))
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', KEY)
    if profile == 'ceo':
        monkeypatch.delenv('JARVIS_PROFILE', raising=False)
    else:
        monkeypatch.setenv('JARVIS_PROFILE', profile)
    assert policy.validate(r, 'company', KEY) == r
    assert policy.runtime_selection(agent, BASE) == (r['model'], r)
    assert policy.proof_model({'agent_id': agent['id'], 'inference_configuration': r}, agent, BASE, KEY) == r['model']
    assert policy.proof_model({}, agent, BASE, KEY) == BASE
    assert agent['metadata']['jarvis'].get('profile_sha256') == r.get('profile_sha256')


@pytest.mark.parametrize('field,value', [('provider', 'local_ollama'), ('model', BASE),
    ('endpoint', 'http://127.0.0.1:11434/v1'), ('company_id', 'foreign'), ('agent_id', 'not-a-uuid'),
    ('profile', 'unrestricted'), ('profile', []), ('profile', 'research'),
    ('profile_sha256', 'a' * 64), ('authority_scope', 'ceo_readonly_demo'),
    ('source', 'operator_authorized_codex_demo'), ('context_length', 8192), ('inference_slots', 2),
    ('fallback_allowed', True), ('user_authorized', False), ('hiring_approval_required', False),
    ('sensitive_action_approval_required', False)])
def test_even_signed_workforce_policy_cannot_enable_fallback_or_expand_authority(field, value):
    r = {**workforce_record(), field: value}
    r['signature'] = policy.signature(r, KEY)
    with pytest.raises(PermissionError):
        policy.validate(r, 'company', KEY)


def test_workforce_signature_is_separate_from_historical_demo_and_local_domains():
    r = workforce_record()
    unsigned = {k: v for k, v in r.items() if k != 'signature'}
    raw = json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode()
    for old_domain in (policy.DOMAIN, policy.CODEX_DOMAIN):
        old_signature = hmac.new(KEY.encode(), old_domain + raw, hashlib.sha256).hexdigest()
        with pytest.raises(PermissionError):
            policy.validate({**r, 'signature': old_signature}, 'company', KEY)
    with pytest.raises(PermissionError):
        policy.validate({**r, 'signature': '0' * 64}, 'company', KEY)


@pytest.mark.parametrize('field,value', [('id', '22222222-2222-4222-8222-222222222222'),
    ('role', 'ceo'), ('profile', 'system_administration'), ('profile_sha256', 'b' * 64)])
def test_workforce_cannot_swap_employee_role_or_capability_hash(monkeypatch, field, value):
    r = workforce_record('research'); agent = workforce_agent(r)
    if field in ('profile', 'profile_sha256'):
        agent['metadata']['jarvis'][field] = value
    else:
        agent[field] = value
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', r['model'])
    monkeypatch.setenv('JARVIS_INFERENCE_CONFIGURATION', json.dumps(r))
    monkeypatch.delenv('JARVIS_EXECUTION_PROOF_KEY', raising=False)
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    with pytest.raises(PermissionError):
        policy.runtime_selection(agent, BASE)
    with pytest.raises(PermissionError):
        policy.proof_model({'inference_configuration': r}, agent, BASE, KEY)


def test_worker_runtime_configuration_is_not_reusable_as_another_tool_profile(monkeypatch):
    r = workforce_record('research'); agent = workforce_agent(r)
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', r['model'])
    monkeypatch.setenv('JARVIS_INFERENCE_CONFIGURATION', json.dumps(r))
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', KEY)
    monkeypatch.setenv('JARVIS_PROFILE', 'software_development')
    with pytest.raises(PermissionError): policy.runtime_selection(agent, BASE)
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', BASE)
    with pytest.raises(PermissionError): policy.runtime_selection(agent, BASE)


def test_workforce_proof_requires_native_configuration_history_and_exact_employee():
    old = record(); demo = cloud_record(); r = workforce_record(); agent = workforce_agent(r)
    agent['metadata']['jarvis']['inference_configuration_history'] = [old, demo]
    for frozen in (old, demo, r):
        assert policy.proof_model({'inference_configuration': frozen}, agent, BASE, KEY) == frozen['model']
    with pytest.raises(PermissionError):
        policy.proof_model({'agent_id': 'another', 'inference_configuration': r}, agent, BASE, KEY)
    agent['metadata']['jarvis']['inference_configuration'] = demo
    with pytest.raises(PermissionError):
        policy.proof_model({'inference_configuration': r}, agent, BASE, KEY)
    agent['metadata']['jarvis']['inference_configuration_history'].append(r)
    assert policy.proof_model({'inference_configuration': r}, agent, BASE, KEY) == r['model']


def test_workforce_does_not_inherit_readonly_demo_restrictions():
    # This helper only applies the additional v2 restriction. Native CEO scope
    # and employee profile guards remain responsible for tool authorization.
    for action in ('delegate', 'review', 'request_hire', 'request_correction', 'plan'):
        assert policy.demo_tool_allowed(workforce_record(), 'paperclip_ceo', {'action': action})
    assert not policy.demo_tool_allowed(cloud_record(), 'paperclip_ceo', {'action': 'delegate'})


@pytest.mark.parametrize('raw', ['[]', 'null', '{broken'])
def test_malformed_runtime_policy_is_denied_without_starting_inference(monkeypatch, raw):
    monkeypatch.setenv('JARVIS_RUNTIME_MODEL', BASE)
    monkeypatch.setenv('JARVIS_INFERENCE_CONFIGURATION', raw)
    with pytest.raises(PermissionError): policy.runtime_selection({'companyId': 'company'}, BASE)
