"""Operator-signed inference selection, separate from employee authority.

Hiring approvals and frozen capability hashes retain their original meaning.
A model-only operator change cannot expand tools, credentials or resource limits.
"""
import hashlib
import hmac
import json
import os
import re

DOMAIN = b'jarvis-local-inference-v1:'
CODEX_DOMAIN = b'jarvis-codex-demo-v2:'
CODEX_WORKFORCE_DOMAIN = b'jarvis-codex-workforce-v3:'
CODEX_ENDPOINT = 'https://chatgpt.com/backend-api/codex'
WORKFORCE_ROLES = {'ceo': 'ceo', 'research': 'researcher',
    'software_development': 'engineer', 'system_administration': 'devops',
    'documentation': 'general', 'security_analysis': 'security'}


def _workforce_policy(record):
    """Validate the signed scope without granting any additional runtime tools."""
    profile = record.get('profile')
    ceo = profile == 'ceo'
    if (not isinstance(profile, str) or profile not in WORKFORCE_ROLES or
            record.get('provider') != 'openai-codex' or record.get('model') != 'gpt-6.1-sol' or
            record.get('endpoint') != CODEX_ENDPOINT or
            record.get('source') != 'operator_authorized_codex_workforce' or
            not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', str(record.get('agent_id', ''))) or
            record.get('context_length') != 65536 or record.get('inference_slots') != 1 or
            record.get('fallback_allowed') is not False or record.get('user_authorized') is not True or
            record.get('hiring_approval_required') is not True or
            record.get('sensitive_action_approval_required') is not True or
            record.get('authority_scope') != ('ceo_orchestration' if ceo else 'approved_capability_profile') or
            (ceo and record.get('profile_sha256') is not None) or
            (not ceo and not re.fullmatch(r'[a-f0-9]{64}', str(record.get('profile_sha256', ''))))):
        raise PermissionError('Codex workforce selection has an invalid role or authority scope')


def _workforce_identity(record, agent):
    """Bind inference to the native employee and its frozen capability profile."""
    _workforce_policy(record)
    profile = record['profile']
    meta = ((agent.get('metadata') or {}).get('jarvis') or {})
    if (record.get('agent_id') != agent.get('id') or
            agent.get('role') != WORKFORCE_ROLES[profile] or
            (profile != 'ceo' and (meta.get('profile') != profile or
                                  meta.get('profile_sha256') != record['profile_sha256']))):
        raise PermissionError('Codex workforce selection does not match the native employee capability')


def signature(record, key):
    unsigned = {k: v for k, v in record.items() if k != 'signature'}
    raw = json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode()
    domain = {2: CODEX_DOMAIN, 3: CODEX_WORKFORCE_DOMAIN}.get(record.get('version'), DOMAIN)
    return hmac.new(key.encode(), domain + raw, hashlib.sha256).hexdigest()


def validate(record, company, key):
    if isinstance(record, dict) and record.get('version') == 3:
        _workforce_policy(record)
        if (record.get('company_id') != company or not key or
                not hmac.compare_digest(str(record.get('signature', '')), signature(record, key))):
            raise PermissionError('Codex workforce selection is not an authenticated operator policy')
        return record
    if isinstance(record, dict) and record.get('version') == 2:
        if (record.get('company_id') != company or record.get('provider') != 'openai-codex' or
                record.get('source') != 'operator_authorized_codex_demo' or
                record.get('model') != 'gpt-6.1-sol' or record.get('endpoint') != CODEX_ENDPOINT or
                not re.fullmatch(r'[a-f0-9-]{36}', str(record.get('agent_id', ''))) or
                record.get('context_length') != 65536 or record.get('inference_slots') != 1 or
                record.get('authority_scope') != 'ceo_readonly_demo' or
                record.get('fallback_allowed') is not False or record.get('user_authorized') is not True or
                not key or not hmac.compare_digest(str(record.get('signature', '')), signature(record, key))):
            raise PermissionError('Codex demo selection is not an authenticated operator policy')
        return record
    if (not isinstance(record, dict) or record.get('version') != 1 or
            record.get('company_id') != company or record.get('provider') != 'local_ollama' or
            record.get('source') != 'operator_model_selection' or
            not re.fullmatch(r'jarvis-[A-Za-z0-9._-]+:[A-Za-z0-9._-]+', str(record.get('model', ''))) or
            not re.fullmatch(r'[a-f0-9]{64}', str(record.get('model_digest', ''))) or
            record.get('inference_slots') != 1 or record.get('cpu_threads') != 24 or
            record.get('context_length') != 65536 or not key or
            not hmac.compare_digest(str(record.get('signature', '')), signature(record, key))):
        raise PermissionError('Local inference selection is not an authenticated operator policy')
    return record


def agent_record(agent):
    return ((agent.get('metadata') or {}).get('jarvis') or {}).get('inference_configuration')


def runtime_selection(agent, base_model):
    selected = os.environ.get('JARVIS_RUNTIME_MODEL') or base_model
    raw = os.environ.get('JARVIS_INFERENCE_CONFIGURATION', '')
    if not raw:
        if selected != base_model or agent_record(agent):
            raise PermissionError('Model override requires its immutable operator configuration')
        return base_model, None
    try:
        expected = json.loads(raw)
    except (TypeError, ValueError):
        raise PermissionError('Runtime inference configuration must be an operator record') from None
    if (not isinstance(expected, dict) or expected != agent_record(agent) or
            selected != expected.get('model') or expected.get('company_id') != agent['companyId']):
        raise PermissionError('Runtime and native inference configuration differ')
    if expected.get('version') == 2 and expected.get('agent_id') != agent.get('id'):
        raise PermissionError('Codex demo is restricted to its selected employee')
    if expected.get('version') == 3:
        _workforce_identity(expected, agent)
        profile = expected['profile']
        if ((profile == 'ceo' and os.environ.get('JARVIS_PROFILE')) or
                (profile != 'ceo' and os.environ.get('JARVIS_PROFILE') != profile)):
            raise PermissionError('Codex workforce runtime has a different capability profile')
    master = os.environ.get('JARVIS_EXECUTION_PROOF_KEY')
    if master:
        validate(expected, agent['companyId'], master)
    # Employees lack the company master key. Their immutable container env is
    # operator-populated after signature verification; it must match native data.
    return selected, expected


def proof_model(proof, agent, base_model, key):
    record = proof.get('inference_configuration')
    if not record:
        return base_model  # Historical approved-profile results remain valid.
    validate(record, agent['companyId'], key)
    if record.get('version') == 2 and (record.get('agent_id') != agent.get('id') or
            proof.get('agent_id', agent.get('id')) != agent.get('id')):
        raise PermissionError('Codex model receipt has a different employee identity')
    if record.get('version') == 3:
        _workforce_identity(record, agent)
        if proof.get('agent_id', agent.get('id')) != agent.get('id'):
            raise PermissionError('Codex model receipt has a different employee identity')
    meta = ((agent.get('metadata') or {}).get('jarvis') or {})
    known = [meta.get('inference_configuration'), *meta.get('inference_configuration_history', [])]
    if record not in known:
        raise PermissionError('Inference selection is absent from native configuration history')
    return record['model']


def demo_tool_allowed(record, tool_name, args):
    """Only v2 is a read-only demo; v3 keeps native CEO/profile tool guards.

    A workforce inference record never replaces the existing employee tool,
    workspace, approval or CEO scope checks with a provider-based allowlist.
    """
    if not isinstance(record, dict) or record.get('version') != 2:
        return True
    if tool_name in ('paperclip_context', 'publish_artifact', 'local_ollama_models'):
        return True
    return tool_name == 'paperclip_ceo' and (
        args.get('action') == 'review' or
        (args.get('action') == 'plan' and args.get('decision') == 'self'))
