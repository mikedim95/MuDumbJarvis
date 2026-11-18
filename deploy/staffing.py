#!/usr/bin/env python3
"""Provision approved Paperclip employees. Never creates, schedules or completes tasks.

Paperclip is the only employee/approval/task authority. This operator-owned
runtime reconciler manages labeled containers and reports runtime readiness.
No Docker socket or board credential is given to an AI runtime or sandbox.
"""
import argparse
import copy
import datetime
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from uuid import UUID

import yaml

ROOT = Path(__file__).resolve().parents[1]
_lock_spec=importlib.util.spec_from_file_location('jarvis_agent_config_lock',ROOT/'server/agent_config_lock.py')
_configuration_lock=importlib.util.module_from_spec(_lock_spec)
_lock_spec.loader.exec_module(_configuration_lock)
spec = importlib.util.spec_from_file_location('jarvis_profiles', ROOT / 'hermes-plugin/jarvis_readonly/profile_registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)
inference_spec = importlib.util.spec_from_file_location('jarvis_inference_policy', ROOT / 'hermes-plugin/jarvis_readonly/inference_policy.py')
inference_policy = importlib.util.module_from_spec(inference_spec)
inference_spec.loader.exec_module(inference_policy)
HERMES_IMAGE = 'nousresearch/hermes-agent:v0.23.1@sha256:1a355ebc8981a4b72a28f4e47e347ba4f0f172b43dc876e5768d175a07c67b22'
SANDBOX_IMAGE = 'jarvis-command-center:employee-sandbox-v3'
MANAGED = 'io.jarvis.employee'
RUNTIME_SPEC = 'phase12-v1'
CODEX_ROOT = '/opt/jarvis-codex'
CODEX_PROFILE_HOME = CODEX_ROOT + '/profiles/employee'
WORKFORCE_AUTHORIZATION = 'user_requested_jarvis_ceo_four_codex_staff_20261116'
WORKFORCE_HIRING_REASON = ('Operator applying the explicit human request in this session: '
    'MAKE JARVIS THE CEO, with at least four specialist agents, all using Codex. '
    'This approves the initial missing roles only. Future hires and sensitive actions require human approval.')


def settings():
    result = {}
    for line in (ROOT / 'deploy/.env').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            result[key] = value.strip().strip('"\'')
    return result


class Board:
    def __init__(self, env):
        self.env = env
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(self, method, path, body=None):
        request = urllib.request.Request('http://127.0.0.1:3100/api' + path, method=method,
            headers={'Authorization': 'Bearer ' + self.env['PAPERCLIP_API_KEY'], 'Content-Type': 'application/json'},
            data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError('Paperclip ' + method + ' failed: HTTP ' + str(error.code)) from None


def run(argv, *, data=None, check=True):
    result = subprocess.run(argv, input=data, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=180)
    if check and result.returncode:
        raise RuntimeError('Runtime operation failed: ' + argv[0] + ' (exit ' + str(result.returncode) + ')')
    return result


def inspect(kind, name):
    result = run(['docker', kind, 'inspect', name], check=False)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Private configuration must not be a symlink')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(value)


def same_runtime_config(observed, expected):
    # The pinned official entrypoint adds this schema receipt on first boot.
    # Every authority-bearing setting still has to match exactly.
    return {key: value for key, value in observed.items() if key != '_config_version'} == expected


def codex_config(config):
    """Change inference only; retain the frozen tools, isolation and limits."""
    config = copy.deepcopy(config)
    config['model'] = {'provider': 'openai-codex', 'default': 'gpt-6.1-sol',
        'base_url': inference_policy.CODEX_ENDPOINT, 'context_length': 65536, 'streaming': False}
    for name in ('providers', 'custom_providers', 'fallback_models'):
        config.pop(name, None)
    config.update(fallback_model=None, fallback_providers=[])
    config['compression'] = {'enabled': False, 'prepare_ahead': False}
    config.setdefault('memory', {}).update(memory_enabled=False, user_profile_enabled=False)
    config.setdefault('auxiliary', {})['title_generation'] = {'enabled': False, 'model_upgrade_enabled': False}
    # These named profiles run in separate containers behind the existing TLS
    # gateway. Pinned Hermes requires its supported standalone compatibility flag.
    config.setdefault('gateway', {})['standalone'] = True
    return config


def selected_inference(agent, item, env):
    meta = (agent.get('metadata') or {}).get('jarvis') or {}
    record = meta.get('inference_configuration')
    if isinstance(record, dict) and record.get('version') == 3:
        inference_policy.validate(record, env['PAPERCLIP_COMPANY_ID'], env['JARVIS_EXECUTION_PROOF_KEY'])
        inference_policy._workforce_identity(record, agent)
        if record['profile'] != item['id']:
            raise ValueError('Codex role differs from its approved capability')
        return record['model'], record
    model = env.get('JARVIS_RUNTIME_MODEL') or item['model']
    record = json.loads(env['JARVIS_INFERENCE_CONFIGURATION']) if env.get('JARVIS_INFERENCE_CONFIGURATION') else None
    if record:
        inference_policy.validate(record, env['PAPERCLIP_COMPANY_ID'], env['JARVIS_EXECUTION_PROOF_KEY'])
        if record != meta.get('inference_configuration') or model != record['model']:
            raise ValueError('Native employee and operator inference selection differ')
    elif model != item['model']:
        raise ValueError('A model-only override requires its signed operator selection')
    return model, record


def workforce_record(agent, env, item=None):
    profile = item['id'] if item else 'ceo'
    prior = inference_policy.agent_record(agent)
    if isinstance(prior, dict) and prior.get('version') == 3:
        inference_policy.validate(prior, env['PAPERCLIP_COMPANY_ID'], env['JARVIS_EXECUTION_PROOF_KEY'])
        inference_policy._workforce_identity(prior, agent)
        return prior
    record = {'version': 3, 'company_id': env['PAPERCLIP_COMPANY_ID'], 'agent_id': agent['id'],
        'profile': profile, 'provider': 'openai-codex', 'model': 'gpt-6.1-sol',
        'endpoint': inference_policy.CODEX_ENDPOINT, 'context_length': 65536,
        'inference_slots': 1, 'fallback_allowed': False, 'user_authorized': True,
        'source': 'operator_authorized_codex_workforce',
        'authority_scope': 'ceo_orchestration' if item is None else 'approved_capability_profile',
        'hiring_approval_required': True, 'sensitive_action_approval_required': True,
        'selected_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if item:
        record['profile_sha256'] = item['sha256']
    record['signature'] = inference_policy.signature(record, env['JARVIS_EXECUTION_PROOF_KEY'])
    inference_policy.validate(record, env['PAPERCLIP_COMPANY_ID'], env['JARVIS_EXECUTION_PROOF_KEY'])
    inference_policy._workforce_identity(record, agent)
    return record


def stage_workforce_employee(board, agent, item):
    """After native approval, provision future hires with a fresh identity-bound grant."""
    if not (ROOT / 'deploy/codex-workforce.env').exists():
        return agent
    record = workforce_record(agent, board.env, item)
    if inference_policy.agent_record(agent) == record:
        return agent
    meta = (agent.get('metadata') or {}).get('jarvis') or {}
    history = list(meta.get('inference_configuration_history') or [])
    if meta.get('inference_configuration'):
        history.append(meta['inference_configuration'])
    board.api('POST', '/agents/' + agent['id'] + '/pause', {})
    runtime_patch(board,agent['id'],jarvis_updates={'inference_configuration':record,
        'inference_configuration_history':history,'provisioned':False,'operator_inference_upgrade_pending':True})
    return board.api('GET', '/agents/' + agent['id'])


def validate_agent(agent, approvals, env):
    meta = (agent.get('metadata') or {}).get('jarvis') or {}
    if not meta.get('managed'):
        return None
    UUID(agent['id'])
    if agent.get('companyId') != env['PAPERCLIP_COMPANY_ID'] or agent.get('reportsTo') != env['PAPERCLIP_CEO_AGENT_ID']:
        raise ValueError('Managed employee company/hierarchy mismatch')
    item = registry.profile(meta.get('profile'))
    if meta.get('profile_sha256') != item['sha256'] or not re.fullmatch(r'[a-f0-9]{24}', meta.get('runtime_id', '')):
        raise ValueError('Approved capability snapshot or runtime identifier differs')
    if agent.get('status') in ('pending_approval', 'terminated'):
        return None
    upgrading = meta.get('operator_inference_upgrade_pending') is True and not meta.get('provisioned')
    if upgrading:
        inference_policy.validate(meta.get('inference_configuration'), env['PAPERCLIP_COMPANY_ID'], env['JARVIS_EXECUTION_PROOF_KEY'])
    if agent.get('status') == 'paused' and not upgrading and (meta.get('provisioned') or agent.get('pauseReason') not in (None, 'setup')):
        return None
    if (meta.get('origin') == 'existing_worker' and agent['id'] == env['PAPERCLIP_AGENT_ID']
            and item['id'] == 'research'):
        return item
    def approved_request(approval):
        if (approval.get('type') != 'hire_agent' or approval.get('status') != 'approved'
                or (approval.get('payload') or {}).get('agentId') != agent['id']):
            return False
        if approval.get('requestedByAgentId') == env['PAPERCLIP_CEO_AGENT_ID']:
            return True
        # Initial staffing is explicitly requested by the human, not invented
        # as an autonomous CEO hire. Keep native operator attribution truthful.
        snapshot = (((approval.get('payload') or {}).get('metadata') or {}).get('jarvis') or {})
        if (approval.get('requestedByAgentId') is None and approval.get('requestedByUserId')
                and approval.get('decidedByUserId')
                and meta.get('origin') == snapshot.get('origin') == 'operator_authorized_workforce'
                and meta.get('hiring_reason') == snapshot.get('hiring_reason') == WORKFORCE_HIRING_REASON
                and (meta.get('bootstrap_request') is None or
                     meta.get('bootstrap_request') == snapshot.get('bootstrap_request') == WORKFORCE_AUTHORIZATION)):
            # Older setup metadata used a key containing "authorization";
            # Paperclip redacts that value in both native response snapshots.
            # Bind truthful operator provenance and the exact approved reason,
            # then verify the signed employee/profile selection instead.
            selected_inference(agent, item, env)
            return True
        return False
    approved = next((a for a in approvals if approved_request(a)), None)
    if not approved:
        return None
    snapshot = ((approved['payload'].get('metadata') or {}).get('jarvis') or {})
    if any(snapshot.get(k) != meta.get(k) for k in ('profile', 'profile_sha256', 'runtime_id', 'source_issue_id')):
        raise ValueError('Employee configuration differs from human-approved snapshot')
    return item


def container(name, argv, runtime_id, refresh=False):
    existing = inspect('container', name)
    if existing:
        if (existing['Config'].get('Labels') or {}).get(MANAGED) != runtime_id:
            raise ValueError('Container name belongs to an unmanaged resource')
        if refresh or (existing['Config'].get('Labels') or {}).get('io.jarvis.runtime-spec') != RUNTIME_SPEC:
            if not refresh:
                raise ValueError('Reviewed runtime upgrade requires --refresh-idle-runtimes')
            # Caller holds the operator lock and has checked native live runs.
            if existing['State']['Running']:
                run(['docker', 'stop', '--time', '60', name])
            run(['docker', 'rm', name])
            existing = None
    if existing:
        if not existing['State']['Running']:
            run(['docker', 'start', name])
        return
    run(['docker', 'create', '--name', name, '--label', MANAGED + '=' + runtime_id,
        '--label', 'io.jarvis.runtime-spec=' + RUNTIME_SPEC,
        '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3'] + argv)
    run(['docker', 'start', name])


def verify_adapter(board, agent_id, adapter):
    """Retry the native health probe while a new private DNS route settles."""
    result = None
    for attempt in range(8):
        result = board.api('POST', '/companies/' + board.env['PAPERCLIP_COMPANY_ID'] +
            '/adapters/hermes_gateway/test-environment', {'agentId': agent_id, 'adapterConfig': adapter})
        if result.get('status') == 'pass':
            return result
        if attempt < 7:
            time.sleep(2)
    return result


def stop_terminated_employee(board, agent):
    """Retire owned compute only; Paperclip and private state retain history."""
    meta = (agent.get('metadata') or {}).get('jarvis') or {}
    if agent.get('status') != 'terminated' or not meta.get('managed'):
        return False
    if agent.get('companyId') != board.env['PAPERCLIP_COMPANY_ID']:
        raise ValueError('Terminated employee belongs to another company')
    UUID(agent['id'])
    rid = meta.get('runtime_id', '')
    if not re.fullmatch(r'[a-f0-9]{24}', rid):
        raise ValueError('Terminated employee has no valid managed runtime identifier')
    stopped = []
    for prefix in ('jarvis-employee-', 'jarvis-sandbox-'):
        name = prefix + rid
        observed = inspect('container', name)
        if not observed:
            continue
        if (observed['Config'].get('Labels') or {}).get(MANAGED) != rid:
            raise ValueError('Terminated employee resource is not operator-owned')
        if observed['State']['Running']:
            run(['docker', 'stop', '--timeout', '30', name])
            stopped.append(name)
    print(json.dumps({'agent_id': agent['id'], 'status': 'terminated',
        'stopped_owned_containers': stopped, 'history_deleted': False}))
    return True


def configured_agent_prompt(agent, default):
    saved=(((agent.get('metadata') or {}).get('jarvis') or {}).get('system_prompts') or {}).get('agent')
    if saved is None:
        return default
    text=saved.get('text')
    if not isinstance(text,str) or not 1<=len(text)<=20000 or hashlib.sha256(text.encode()).hexdigest()!=saved.get('sha256'):
        raise ValueError('Saved owner system prompt is invalid; review before reconciling')
    return text


def runtime_patch(board, agent_id, *, fields=None, jarvis_updates=None):
    """Merge only runtime-owned fields under the same cross-process lock as chat edits."""
    with _configuration_lock.lock(agent_id):
        current=board.api('GET','/agents/'+agent_id)
        patch=copy.deepcopy(fields or {})
        if 'adapterConfig' in patch:
            patch['adapterConfig']['instructions']=configured_agent_prompt(current,patch['adapterConfig']['instructions'])
            patch['adapterConfig']={**(current.get('adapterConfig') or {}),**patch['adapterConfig']}
        if jarvis_updates:
            metadata=current.get('metadata') or {}
            patch['metadata']={**metadata,'jarvis':{**(metadata.get('jarvis') or {}),**jarvis_updates}}
        return board.api('PATCH','/agents/'+agent_id,patch)


def provision(board, agent, item, refresh=False, allow_resume=True):
    env, meta = board.env, agent['metadata']['jarvis']
    rid = meta['runtime_id']
    home = ROOT / '.runtime/employees' / agent['id']
    home.mkdir(parents=True, exist_ok=True)
    if home.is_symlink():
        raise ValueError('Employee state must not be a symlink')
    private = ROOT / '.runtime/provisioning' / (agent['id'] + '.json')
    if private.exists():
        credentials = json.loads(private.read_text())
    else:
        token = board.api('POST', '/agents/' + agent['id'] + '/keys', {'name': 'Isolated JARVIS employee callbacks'})['token']
        credentials = {'api_key': secrets.token_hex(32), 'paperclip_key': token}
        write_private(private, json.dumps(credentials))
    stored = board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/secrets')
    secret_name = 'hermes-employee-' + rid
    secret = next((s for s in stored if s['name'] == secret_name), None)
    if not secret:
        secret = board.api('POST', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/secrets',
            {'name': secret_name, 'value': credentials['api_key']})
    config = yaml.safe_load((ROOT / 'deploy/hermes.config.example.yaml').read_text())
    runtime_model, inference_record = selected_inference(agent, item, env)
    codex = bool(inference_record and inference_record.get('version') == 3)
    config['model']['default'] = runtime_model
    config['agent']['max_turns'] = item['limits']['max_turns']
    config['agent']['gateway_timeout'] = item['limits']['timeout_seconds']
    config['agent']['disabled_toolsets'] = [name for name in config['agent']['disabled_toolsets'] if name not in item['toolsets']]
    config['platform_toolsets'] = {'cli': item['toolsets'], 'api_server': item['toolsets']}
    config['terminal'] = {'env_type': 'ssh', 'backend': 'ssh', 'ssh_host': 'jarvis-sandbox-' + rid,
        'ssh_port': 2222, 'ssh_user': 'employee', 'ssh_key': '/opt/data/.ssh/id_ed25519',
        'cwd': '/workspace', 'timeout': 120, 'env_passthrough': [], 'credential_files': []}
    if codex:
        config = codex_config(config)
    config_path = home / 'config.yaml'
    if not config_path.exists():
        write_private(config_path, yaml.safe_dump(config, sort_keys=False))
    elif not same_runtime_config(yaml.safe_load(config_path.read_text()), config):
        observed = yaml.safe_load(config_path.read_text())
        observed.pop('_config_version', None)
        observed.setdefault('terminal', {})['backend'] = 'ssh'
        # An explicit idle-runtime refresh may add the reviewed hook output
        # bound. Never replace a different operator hook configuration.
        if refresh and 'hooks' not in observed:
            observed['hooks'] = config['hooks']
        if (refresh and not codex and observed.get('model', {}).get('provider') == 'custom'
                and observed['model'].get('base_url') == 'http://ollama-models:11434/v1'
                and not observed.get('providers') and not observed.get('custom_providers')):
            observed['model']['provider'] = config['model']['provider']
            observed['providers'] = config['providers']
        if inference_record and refresh:
            observed['model']['default'] = runtime_model
        if codex and refresh:
            observed = codex_config(observed)
        if not refresh or observed != config:
            raise ValueError('Existing employee runtime configuration differs; review before changing authority')
        write_private(config_path, yaml.safe_dump(config, sort_keys=False))
    soul = ('You are ' + agent['name'] + ', the ' + item['name'] + ' employee reporting to JARVIS, the CEO.\n'
        'Paperclip owns your assigned issue, dependencies and execution evidence.\n' + item['authority'] + '\n'
        'Use only your assigned issue context. Never use internal subagents. Do not perform host or external changes.\n'
        'Use actual tools, publish deliverables with publish_artifact, and report real tests/errors. Do not invent evidence.\n')
    if codex:
        soul += ('Your inference is OpenAI Codex through the configured Hermes provider and shared slot. '
            'Do not call an LLM provider directly from fixture code or shell commands. '
            'Restrictions on cloud providers in test fixtures do not prohibit your authorized Codex runtime.\n')
    (home / 'SOUL.md').write_text(soul)
    for skill in item['skills']:
        directory = home / 'skills' / skill
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'SKILL.md').write_text('---\nname: ' + skill + '\ndescription: Scoped ' + item['name'] + ' workflow\n---\n'
            + item['authority'] + '\nRead the assigned Paperclip objective, retrieve actual evidence, and publish artifacts. '
            'Distinguish retrieved facts from interpretation. Test generated code in the isolated workspace. '
            'Use only the authenticated current issue workspace, not another task directory. '
            + ('The sandbox includes Python unittest and promptfoo 0.125.1 for offline echo/deterministic-assertion demos. '
            'Never call cloud providers or remote generation from fixture code, or use model-graded assertions. '
            'Use promptfoo eval --no-cache --max-concurrency 1 with a JSON output file when a real framework demonstration is needed; '
            'also run actual Python unittest checks. ' if 'terminal' in item['tools'] else '') +
            'Publish the actual source/config/results as Paperclip attachments.\n')
    network = 'jarvis-exec-' + rid
    if item['sandbox']:
        if not inspect('image', SANDBOX_IMAGE):
            raise ValueError('Build the reviewed employee sandbox image before provisioning')
        existing_network = inspect('network', network)
        if existing_network and (not existing_network.get('Internal') or
                (existing_network.get('Labels') or {}).get(MANAGED) != rid or
                (existing_network.get('Options') or {}).get('com.docker.network.bridge.gateway_mode_ipv4') != 'isolated'):
            raise ValueError('Execution network is not an owned internal sandbox network')
        if not existing_network:
            run(['docker', 'network', 'create', '--internal', '--opt',
                'com.docker.network.bridge.gateway_mode_ipv4=isolated', '--label', MANAGED + '=' + rid, network])
        workspace = home / 'workspace'
        workspace.mkdir(exist_ok=True)
        ssh_dir = home / '.ssh'
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        ssh_key = ssh_dir / 'id_ed25519'
        if not ssh_key.exists():
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(ssh_key)])
        server_keys = home / 'sandbox-ssh'
        server_keys.mkdir(exist_ok=True)
        host_key = server_keys / 'host_key'
        if not host_key.exists():
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(host_key)])
        (server_keys / 'authorized_keys').write_text((ssh_dir / 'id_ed25519.pub').read_text())
        container('jarvis-sandbox-' + rid, ['--network', network, '--dns', '127.0.0.1', '--user', '1000:1000', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--pids-limit', '128',
            '--cpus', str(item['limits']['cpus']), '--memory', str(item['limits']['memory_mb']) + 'm',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=256m', '--tmpfs', '/home/employee:rw,nosuid,uid=1000,gid=1000,size=64m',
            '-v', str(workspace) + ':/workspace:rw', '-v', str(server_keys) + ':/run/jarvis-ssh:ro', SANDBOX_IMAGE], rid, refresh)
    runtime_env = {'API_SERVER_KEY': credentials['api_key'], 'HERMES_PAPERCLIP_AGENT_KEY': credentials['paperclip_key'],
        'JARVIS_AGENT_PROOF_KEY': hmac.new(env['JARVIS_EXECUTION_PROOF_KEY'].encode(),
            ('jarvis-employee-proof-v3:' + agent['id']).encode(), hashlib.sha256).hexdigest(), 'API_SERVER_ENABLED': 'true',
        'API_SERVER_HOST': '0.0.0.0', 'API_SERVER_PORT': '8642', 'HERMES_DASHBOARD': 'false',
        'HERMES_UID': '1000', 'HERMES_GID': '1000', 'OPENAI_API_KEY': '' if codex else 'ollama-local-only',
        'HERMES_API_TIMEOUT': str(item['limits']['timeout_seconds']), 'JARVIS_OLLAMA_URL': 'http://ollama-models:11434',
        'JARVIS_AGENT_ROLE': item['id'], 'JARVIS_PAPERCLIP_AGENT_ID': agent['id'], 'JARVIS_PROFILE': item['id']}
    if inference_record:
        runtime_env.update({'JARVIS_RUNTIME_MODEL': runtime_model,
            'JARVIS_INFERENCE_CONFIGURATION': json.dumps(inference_record, sort_keys=True, separators=(',', ':'))})
    if codex:
        shared = ROOT / '.runtime/codex-shared'
        if not (shared / 'auth.json').exists():
            raise ValueError('Stage the shared Codex credential root before provisioning')
        runtime_env.update(HERMES_HOME=CODEX_PROFILE_HOME,
            JARVIS_INFERENCE_LOCK=CODEX_ROOT + '/inference.lock')
    if item['sandbox']:
        runtime_env.update({'TERMINAL_ENV': 'ssh', 'TERMINAL_SSH_HOST': 'jarvis-sandbox-' + rid,
            'TERMINAL_SSH_USER': 'employee', 'TERMINAL_SSH_PORT': '2222',
            'TERMINAL_SSH_KEY': '/opt/data/.ssh/id_ed25519', 'TERMINAL_CWD': '/workspace'})
    env_file = home / 'runtime.env'
    write_private(env_file, '\n'.join(k + '=' + v for k, v in runtime_env.items()) + '\n')
    args = ['--network', 'jarvis-command-center_agent-private', '--restart', 'unless-stopped',
        '--security-opt', 'no-new-privileges:true', '--cap-drop', 'NET_RAW', '--pids-limit', str(item['limits']['pids']),
        '--cpus', str(item['limits']['cpus']), '--memory', str(item['limits']['memory_mb']) + 'm',
        '--env-file', str(env_file), '--tmpfs', '/workspace:rw,nosuid,nodev,noexec,size=1m,mode=0755', '-v', str(home) + ':/opt/data']
    plugin_home = '/opt/data'
    if codex:
        args += ['-v', str(shared) + ':' + CODEX_ROOT,
                 '-v', str(home) + ':' + CODEX_PROFILE_HOME]
        plugin_home = CODEX_PROFILE_HOME
    args += ['-v', str(ROOT / 'hermes-plugin/jarvis_readonly') + ':' + plugin_home + '/plugins/jarvis_readonly:ro',
        HERMES_IMAGE, 'gateway', 'run']
    runtime_name = 'jarvis-employee-' + rid
    container(runtime_name, args, rid, refresh)
    if item['sandbox']:
        state = inspect('container', runtime_name)
        if network not in state['NetworkSettings']['Networks']:
            run(['docker', 'network', 'connect', network, runtime_name])
    if codex or 'research_sources' in item['tools']:
        state = inspect('container', runtime_name)
        if 'jarvis-command-center_default' not in state['NetworkSettings']['Networks']:
            run(['docker', 'network', 'connect', 'jarvis-command-center_default', runtime_name])
    health = "import urllib.request,os; r=urllib.request.Request('http://127.0.0.1:8642/health',headers={'Authorization':'Bearer '+os.environ['API_SERVER_KEY']}); urllib.request.urlopen(r,timeout=3).read()"
    healthy = False
    for attempt in range(25 if refresh else 1):
        if not run(['docker', 'exec', runtime_name, 'python3', '-c', health], check=False).returncode:
            healthy = True
            break
        if refresh:
            time.sleep(2)
    if not healthy:
        print(json.dumps({'agent_id': agent['id'], 'profile': item['id'], 'runtime': 'starting'}))
        return False
    # Container checks may take seconds. Reread native owner edits before deciding
    # whether the adapter needs reconciliation; runtime_patch rereads under lock.
    agent=board.api('GET','/agents/'+agent['id'])
    meta=(agent.get('metadata') or {}).get('jarvis') or {}
    adapter = {'apiBaseUrl': 'https://hermes-tls:8645/runtimes/' + rid,
        'apiKey': {'type': 'secret_ref', 'secretId': secret['id'], 'version': 'latest'},
        'paperclipApiUrl': 'http://paperclip:3100', 'sessionKeyStrategy': 'issue',
        'timeoutSec': item['limits']['timeout_seconds'], 'instructions': configured_agent_prompt(agent,soul),
        'payloadTemplate': {'input': 'Execute the current Paperclip assignment supplied by the authenticated preflight context. Use actual approved tools, then return the completed result or real blocker. The runtime persists actual deliverables; never claim an unexecuted tool call.', 'conversation_history': [
            {'role': 'user', 'content': 'Where is authoritative task context?'},
            {'role': 'assistant', 'content': 'Paperclip. I use only the current authenticated issue and approved tools.'}]}}
    runtime_updates = {'provisioned': True, 'runtime_name': runtime_name, 'dormancy': 'No timer heartbeats or inference while idle',
        'operator_inference_upgrade_pending': False}
    capabilities = ', '.join(item['capabilities']) + '. ' + item['authority']
    if (not meta.get('provisioned') or any(agent.get('adapterConfig', {}).get(key) != value for key, value in adapter.items())
            or agent.get('capabilities') != capabilities or agent.get('role') != item['role']):
        updated=runtime_patch(board,agent['id'],fields={'adapterConfig':adapter,
            'role':item['role'],'title':item['name'],'capabilities':capabilities},
            jarvis_updates={**runtime_updates,'provisioned':False})
        adapter=updated['adapterConfig']
        tested = verify_adapter(board, agent['id'], adapter)
        if tested.get('status') != 'pass':
            print(json.dumps({'agent_id': agent['id'], 'runtime': 'awaiting_native_verification'}))
            return
        current = board.api('GET', '/agents/' + agent['id'])
        if current.get('status') == 'paused' and allow_resume:
            board.api('POST', '/agents/' + agent['id'] + '/resume', {})
        runtime_patch(board,agent['id'],jarvis_updates=runtime_updates)
    source = meta.get('source_issue_id')
    if source and not meta.get('ready_notice_sent') and not meta.get('suppress_historical_readiness_notice'):
        comments = board.api('GET', '/issues/' + source + '/comments')
        marker = '[JARVIS RUNTIME READY ' + rid + ']'
        if not any(c.get('body', '').startswith(marker) for c in comments):
            board.api('POST', '/issues/' + source + '/comments', {'body': marker + '\nHuman-approved ' +
                item['name'] + ' employee ' + agent['name'] + ' (' + agent['id'] + ') has an authenticated isolated Hermes runtime. Reuse this employee for the approved capability. No task was assigned by the runtime provisioner.'})
        runtime_patch(board,agent['id'],jarvis_updates={'ready_notice_sent':True})
    print(json.dumps({'agent_id': agent['id'], 'profile': item['id'], 'runtime': 'ready', 'inference_slots': 1}))
    return True


def adopt(board, profile_id):
    """Explicit operator migration of the one pre-existing, authorized employee."""
    agent = board.api('GET', '/agents/' + board.env['PAPERCLIP_AGENT_ID'])
    if agent['companyId'] != board.env['PAPERCLIP_COMPANY_ID'] or agent.get('reportsTo') != board.env['PAPERCLIP_CEO_AGENT_ID']:
        raise ValueError('Existing worker identity mismatch')
    if ((agent.get('metadata') or {}).get('jarvis') or {}).get('managed'):
        raise ValueError('Existing worker already has a managed capability; no implicit permission change')
    item = registry.profile(profile_id)
    rid = hashlib.sha256((agent['companyId'] + ':' + agent['id'] + ':' + profile_id).encode()).hexdigest()[:24]
    board.api('PATCH', '/agents/' + agent['id'], {'role': item['role'], 'title': item['name'],
        'capabilities': ', '.join(item['capabilities']) + '. ' + item['authority'],
        'metadata': {**(agent.get('metadata') or {}), 'jarvis': {'managed': True, 'provisioned': False,
            'origin': 'existing_worker', 'runtime_id': rid, 'profile': profile_id, 'profile_sha256': item['sha256'],
            'model': item['model'], 'limits': item['limits']}}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--adopt-existing', choices=['research'])
    parser.add_argument('--refresh-idle-runtimes', action='store_true', help='Explicit reviewed runtime upgrade; never interrupts native live/queued work')
    parser.add_argument('--agent-id', type=lambda value: str(UUID(value)), help='Restrict operator reconciliation to one existing native employee')
    parser.add_argument('--leave-paused', action='store_true', help='Verify runtimes without resuming employees; useful for an atomic team rollout')
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({'action': 'plan_only', 'profiles': list(registry.catalog()['profiles']), 'employees_created': 0}))
        return
    board = Board(settings())
    lock_path = ROOT / '.runtime/employee-runtime.lock'
    with lock_path.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.adopt_existing:
            adopt(board, args.adopt_existing)
        company = board.env['PAPERCLIP_COMPANY_ID']
        agents = board.api('GET', '/companies/' + company + '/agents')
        approvals = board.api('GET', '/companies/' + company + '/approvals')
        for agent in agents:
            if args.agent_id and agent['id'] != args.agent_id:
                continue
            if stop_terminated_employee(board, agent):
                continue
            item = validate_agent(agent, approvals, board.env)
            if item:
                agent = stage_workforce_employee(board, agent, item)
                live = board.api('GET', '/companies/' + company + '/live-runs')
                owned = [r for r in live if r['agentId'] == agent['id'] and r['status'] in ('queued', 'running')]
                if owned and ((agent.get('metadata') or {}).get('jarvis', {}).get('provisioned') or
                        any(r['status'] == 'running' for r in owned) or args.refresh_idle_runtimes):
                    print(json.dumps({'agent_id': agent['id'], 'runtime': 'busy_configuration_deferred'}))
                    continue
                if args.refresh_idle_runtimes:
                    # Native pause holds assignments while the reviewed runtime
                    # restarts. It is used only after confirming no live work.
                    board.api('POST', '/agents/' + agent['id'] + '/pause', {})
                ready = provision(board, agent, item, args.refresh_idle_runtimes, allow_resume=not args.leave_paused)
                if args.refresh_idle_runtimes and ready:
                    current = board.api('GET', '/agents/' + agent['id'])
                    tested = verify_adapter(board, agent['id'], current['adapterConfig'])
                    if tested.get('status') != 'pass':
                        raise ValueError('Reviewed upgrade remains paused: native adapter verification failed')
                    if current.get('status') == 'paused' and not args.leave_paused:
                        board.api('POST', '/agents/' + agent['id'] + '/resume', {})


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'runtime_provisioning': 'failed', 'error_type': type(error).__name__,
            'detail': str(error) if isinstance(error, (ValueError, RuntimeError)) else 'Inspect operator log; credentials omitted'}))
        raise SystemExit(1)
