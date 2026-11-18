#!/usr/bin/env python3
"""Read-only native/runtime audit of the retained four-specialist HUD workflow.

This verifies existing work only. It never submits, retries, resumes, approves,
provisions or changes a service. Only the final sanitized evidence file is written.
"""
import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import urllib.parse
import urllib.request

import staffing

PROFILES = ('research', 'software_development', 'system_administration', 'security_analysis')
REQUIRED = {'research': {'research_sources'}, 'software_development': {'terminal', 'read_worker_artifacts'},
    'system_administration': {'local_ollama_models', 'terminal'}, 'security_analysis': {'terminal', 'read_worker_artifacts'}}
REPORTS = {'research': 'workforce-research.md', 'software_development': 'workforce-software.md',
    'system_administration': 'workforce-systems.md', 'security_analysis': 'workforce-security.md'}


def utc(value):
    return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def inspect_container(name):
    result = subprocess.run(['docker', 'inspect', name], text=True, capture_output=True, timeout=20)
    require(result.returncode == 0, 'Required container is unavailable: ' + name)
    return json.loads(result.stdout)[0]


def inspect_network(name):
    result = subprocess.run(['docker', 'network', 'inspect', name], text=True, capture_output=True, timeout=20)
    require(result.returncode == 0, 'Required private execution network is unavailable')
    return json.loads(result.stdout)[0]


def container_python(name, source):
    result = subprocess.run(['docker', 'exec', '-i', name, '/opt/hermes/.venv/bin/python', '-'],
        input=source, text=True, capture_output=True, timeout=30)
    require(result.returncode == 0, 'Read-only runtime probe failed: ' + name)
    return json.loads(result.stdout)


def runtime_usage(name, hermes_id):
    require(bool(re.fullmatch(r'run_[a-f0-9]+', hermes_id)), 'Invalid native Hermes execution reference')
    return container_python(name, 'import json,os,urllib.request\n'
        'r=urllib.request.Request("http://127.0.0.1:8642/v1/runs/' + hermes_id + '",'
        'headers={"Authorization":"Bearer "+os.environ["API_SERVER_KEY"]})\n'
        'd=json.load(urllib.request.urlopen(r,timeout=10))\n'
        'print(json.dumps({k:d.get(k) for k in ("run_id","status","usage")}))\n')


def protected_preservation(root, baseline):
    unchanged = []
    for name, before in baseline['protected'].items():
        observed = inspect_container(name)
        canonical = {'config': observed['Config'], 'host': observed['HostConfig'],
            'mounts': sorted(observed['Mounts'], key=lambda mount: mount['Destination']),
            'networks': sorted(observed['NetworkSettings']['Networks'])}
        require(observed['Id'] == before['id'] and observed['State']['StartedAt'] == before['started_at'] and
            digest(json.dumps(canonical, sort_keys=True).encode()) == before['sha256'],
            'Protected service identity/configuration changed: ' + name)
        unchanged.append(name)
    require(digest((Path.home() / '.codex/auth.json').read_bytes()) == baseline['source_login_sha256'],
        'Source server Codex CLI login changed')
    current = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10))['models']
    original = json.loads((root / '.runtime/csi-before-models.json').read_text())['models']
    require({m['name']: m['digest'] for m in original} == {m['name']: m['digest'] for m in current},
        'Existing Ollama model inventory/digests changed')
    return unchanged, current


def runtime_configuration(root, name, home, profile=None):
    observed = inspect_container(name)
    require(observed['State']['Running'] and not observed['HostConfig'].get('Privileged') and
        observed['HostConfig'].get('NetworkMode') != 'host', 'Inference runtime is unavailable or has unrestricted host mode')
    config = staffing.yaml.safe_load((home / 'config.yaml').read_text())
    require(config['model']['provider'] == 'openai-codex' and config['model']['default'] == 'gpt-6.1-sol' and
        config['model']['base_url'] == staffing.inference_policy.CODEX_ENDPOINT and
        config.get('fallback_model') is None and config.get('fallback_providers') == [] and
        not config.get('providers') and not config.get('custom_providers') and not config.get('fallback_models'),
        'Runtime permits an unexpected provider or fallback: ' + name)
    require(config.get('compression', {}).get('enabled') is False and
        config.get('compression', {}).get('prepare_ahead') is False and
        config.get('memory', {}).get('memory_enabled') is False and
        config.get('memory', {}).get('user_profile_enabled') is False and
        config.get('auxiliary', {}).get('title_generation', {}).get('enabled') is False and
        config.get('auxiliary', {}).get('title_generation', {}).get('model_upgrade_enabled') is False,
        'An auxiliary inference feature bypasses the shared slot: ' + name)
    own_auth = home / 'auth.json'
    if own_auth.exists():
        store = json.loads(own_auth.read_text())
        require(all(not (store.get(section) or {}).get('openai-codex') for section in ('providers', 'credential_pool')),
            'Profile shadows the shared Codex rotating credential store')
    env = dict(item.split('=', 1) for item in observed['Config']['Env'] if '=' in item)
    suffix = 'employee' if profile else ('ceo' if name == 'jarvis-hermes-ceo' else 'chat')
    expected_home = '/opt/jarvis-codex/profiles/' + suffix
    require(env.get('HERMES_HOME') == expected_home and
        env.get('JARVIS_INFERENCE_LOCK') == '/opt/jarvis-codex/inference.lock', 'Runtime lacks the common auth root or inference lock')
    mounts = {mount['Destination']: mount for mount in observed['Mounts']}
    require(mounts.get('/opt/jarvis-codex', {}).get('Source') == str(root / '.runtime/codex-shared') and
        mounts.get(expected_home, {}).get('Source') == str(home), 'Runtime does not mount its own nested profile')
    for mount in observed['Mounts']:
        source = mount.get('Source', '')
        require(source not in ('/', '/var/run/docker.sock', '/run/docker.sock', str(root / '.runtime')),
            'Runtime exposes an unrestricted host mount')
        if '/.runtime/employees/' in source:
            require(source == str(home) or source.startswith(str(home) + '/'), 'Another employee profile is mounted')
    require(not any(mount.get('Destination', '').endswith('docker.sock') for mount in observed['Mounts']), 'Docker socket is exposed')
    if profile:
        expected = staffing.registry.profile(profile)
        require(config['platform_toolsets']['api_server'] == expected['toolsets'], 'Worker toolsets differ from its frozen capability profile')
    auth = container_python(name, 'import json\nfrom urllib.parse import urlsplit\n'
        'from hermes_cli.auth import resolve_codex_runtime_credentials\n'
        'c=resolve_codex_runtime_credentials(read_only=True)\n'
        'print(json.dumps({"endpoint_host":urlsplit(c["base_url"]).hostname,"resolved":bool(c)}))\n')
    require(auth['resolved'] and auth['endpoint_host'] == 'chatgpt.com', 'Native shared-root Codex credentials did not resolve')
    return observed


def sandbox_configuration(root, agent, profile):
    item = staffing.registry.profile(profile)
    if not item['sandbox']:
        return None
    meta = agent['metadata']['jarvis']; name = 'jarvis-sandbox-' + meta['runtime_id']
    sandbox = inspect_container(name); host = sandbox['HostConfig']
    require(sandbox['Config'].get('User') == '1000:1000' and host.get('ReadonlyRootfs') is True and
        host.get('Privileged') is False and 'ALL' in (host.get('CapDrop') or []) and
        any('no-new-privileges' in setting for setting in host.get('SecurityOpt') or []) and
        0 < host.get('Memory', 0) <= item['limits']['memory_mb'] * 1024 ** 2 and
        0 < host.get('NanoCpus', 0) <= item['limits']['cpus'] * 10 ** 9 and
        0 < host.get('PidsLimit', 0) <= item['limits']['pids'], 'Sandbox identity, resource bounds or host isolation changed')
    require(set(m['Destination'] for m in sandbox['Mounts']) == {'/workspace', '/run/jarvis-ssh'}, 'Unexpected sandbox host mount')
    workspace = root / '.runtime/employees' / agent['id'] / 'workspace'
    require(any(m['Destination'] == '/workspace' and m['Source'] == str(workspace) for m in sandbox['Mounts']), 'Sandbox workspace belongs to another employee')
    networks = sandbox['NetworkSettings']['Networks']
    require(bool(networks) and host.get('NetworkMode') != 'host', 'Sandbox has no private execution network')
    for network in networks:
        current = inspect_network(network)
        require(current.get('Internal') and current.get('Options', {}).get('com.docker.network.bridge.gateway_mode_ipv4') == 'isolated',
            'Sandbox can use an external/default host route')
    return {'container': name, 'uid': 1000, 'private_workspace': True, 'external_network': False,
        'read_only_root': True, 'resource_limits_verified': True}


def slot_audit(homes, cutoff):
    events = []; contexts = []; owner = None; peak = 0
    for name, home in homes.items():
        events.extend({**row, 'container': name} for row in rows(home / 'logs/inference-slot.jsonl') if row['timestamp'] >= cutoff)
        contexts.extend({**row, 'container': name} for row in rows(home / 'logs/model-context.jsonl') if row['timestamp'] >= cutoff)
    require(bool(events), 'No actual shared-slot execution events were recorded')
    groups = {}
    for event in events:
        key = (event['container'], event.get('session_id'), event.get('api_request_id'))
        require(key[-1], 'Inference event has no actual API request correlation ID')
        groups.setdefault(key, []).append(event)
        require(event.get('provider') == 'openai-codex' and event.get('model') == 'gpt-6.1-sol', 'A shared-slot request used another model/provider')
    attempts = {}
    for key, group in groups.items():
        ordered = [event['event'] for event in sorted(group, key=lambda event: event['timestamp'])]
        count = ordered.count('inference_slot.acquired'); attempts[key] = count
        require(count > 0 and ordered == ['inference_slot.queued', 'inference_slot.acquired', 'inference_slot.released'] * count,
            'A provider request was denied, abandoned, duplicated or left its slot unreleased')
    for event in sorted(events, key=lambda row: (row['timestamp'], 0 if row['event'] == 'inference_slot.released' else 1)):
        key = (event['container'], event.get('session_id'), event.get('api_request_id'))
        if event['event'] == 'inference_slot.acquired':
            require(owner is None, 'Overlapping inference requests violated the single shared slot')
            owner = key; peak = max(peak, 1)
        elif event['event'] == 'inference_slot.released':
            require(owner == key, 'Inference release does not match the actual slot owner')
            owner = None
    require(owner is None, 'An inference request is still active')
    by_request = {}
    for row in contexts:
        by_request.setdefault((row['container'], row['session_id'], row['api_request_id']), []).append(row)
    for row in contexts:
        key = (row['container'], row['session_id'], row['api_request_id'])
        require(key in groups and row.get('complete_context_present') is True and
            row.get('provider') == 'openai-codex' and row.get('model') == 'gpt-6.1-sol' and
            row.get('endpoint_host') == 'chatgpt.com' and re.fullmatch(r'[a-f0-9]{64}', str(row.get('context_sha256', ''))),
            'Actual provider request lacks the complete authenticated Paperclip context or shared-slot admission')
    for key in groups:
        if str(key[1]).startswith('paperclip:'):
            # Pinned Hermes reuses api_request_id when it retries an HTTP
            # attempt. Count paired admissions/observations, not unique IDs.
            require(key in by_request and len(by_request[key]) == attempts[key],
                'Paperclip inference passed the provider without observed authenticated context')
    return {'slots': 1, 'observed_peak': peak, 'provider_call_admissions': sum(attempts.values()),
        'authenticated_paperclip_requests': len(contexts), 'balanced_releases': True,
        'unregistered_provider_requests': 0, 'scope': 'Main provider execution middleware; automatic auxiliary inference is disabled'}, contexts


def authentic(proof, comment, task, run, master):
    unsigned = {key: value for key, value in proof.items() if key != 'signature'}
    key = hmac.new(master.encode(), ('jarvis-employee-proof-v3:' + task['assigneeAgentId']).encode(), hashlib.sha256).hexdigest()
    expected = hmac.new(key.encode(), json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
    return (proof.get('version') == 3 and proof.get('kind') == 'execution' and proof.get('task_status') == 'done' and
        proof.get('agent_id') == task['assigneeAgentId'] == comment.get('authorAgentId') and
        proof.get('company_id') == task['companyId'] and proof.get('issue_id') == task['id'] and
        proof.get('paperclip_run_id') == run['id'] == comment.get('createdByRunId') and
        proof.get('session_id') == f"paperclip:company:{task['companyId']}:agent:{task['assigneeAgentId']}:issue:{task['id']}" and
        hmac.compare_digest(expected, str(proof.get('signature', ''))))


def main():
    root = staffing.ROOT; env = staffing.settings(); board = staffing.Board(env)
    company, ceo_id = env['PAPERCLIP_COMPANY_ID'], env['PAPERCLIP_CEO_AGENT_ID']
    private = root / '.runtime/codex-workforce'
    baseline = json.loads((private / 'baseline.json').read_text())
    receipt = json.loads((root / '.runtime/codex-workforce-task.json').read_text())
    require(receipt.get('id') and receipt.get('state') == 'completed', 'The retained HUD workflow/follow-up is not complete')
    cutoff = utc(baseline['checked_at']).timestamp()
    setup = json.loads((private / 'setup.json').read_text())
    team = setup['team']; require(set(team) == set(PROFILES), 'Native setup does not identify the four authorized specialist roles')
    roster = board.api('GET', '/companies/' + company + '/agents'); people = {agent['id']: agent for agent in roster}
    selected_ids = {ceo_id, *team.values()}
    require(all(agent['status'] in ('terminated', 'paused') for agent in roster if agent['id'] not in selected_ids), 'Unexpected active employee exists')
    require(all(people[identifier]['status'] == 'idle' and people[identifier]['lifecycleState'] == 'ready' for identifier in selected_ids), 'A selected employee is not idle/ready')
    require(not board.api('GET', '/companies/' + company + '/live-runs'), 'Native execution is still active or queued')
    require(board.api('GET', '/companies/' + company).get('requireBoardApprovalForNewAgents') is True, 'Future native hiring no longer requires human approval')
    preserved, models = protected_preservation(root, baseline)
    shared = root / '.runtime/codex-shared'
    require((shared / 'auth.json').exists() and stat.S_IMODE((shared / 'auth.json').stat().st_mode) == 0o600, 'Shared root credential store is absent or not private')
    for directory in (shared / 'profiles').iterdir():
        require(directory.is_dir() and not any(directory.iterdir()), 'Shared root contains sibling profile data')
    homes = {'jarvis-hermes': root / '.runtime/hermes', 'jarvis-hermes-ceo': root / '.runtime/hermes-ceo'}
    runtime_configuration(root, 'jarvis-hermes', homes['jarvis-hermes'])
    runtimes = {}; sandboxes = {}
    for identifier in selected_ids:
        agent = people[identifier]; meta = agent.get('metadata', {}).get('jarvis', {})
        record = staffing.inference_policy.validate(meta['inference_configuration'], company, env['JARVIS_EXECUTION_PROOF_KEY'])
        profile = 'ceo' if identifier == ceo_id else next(p for p, aid in team.items() if aid == identifier)
        require(record['version'] == 3 and record['agent_id'] == identifier and record['profile'] == profile, 'Native signed workforce policy has the wrong employee/profile')
        require(agent['adapterType'] == 'hermes_gateway' and agent['adapterConfig'].get('sessionKeyStrategy') == 'issue' and
            isinstance(agent['adapterConfig'].get('apiKey'), dict) and agent['adapterConfig']['apiKey'].get('type') == 'secret_ref', 'Native adapter does not use issue sessions and managed secrets')
        heartbeat = agent.get('runtimeConfig', {}).get('heartbeat', {})
        require(heartbeat.get('enabled') is False and heartbeat.get('maxConcurrentRuns') == 1, 'Employee can bypass dormant/native concurrency policy')
        name = 'jarvis-hermes-ceo' if profile == 'ceo' else meta['runtime_name']
        home = homes[name] if profile == 'ceo' else root / '.runtime/employees' / identifier
        homes[name] = home; runtimes[identifier] = name
        runtime_configuration(root, name, home, None if profile == 'ceo' else profile)
        if profile != 'ceo':
            require(agent.get('reportsTo') == ceo_id and meta.get('provisioned') is True and
                meta.get('profile_sha256') == staffing.registry.profile(profile)['sha256'], 'Worker hierarchy or frozen capability changed')
            sandboxes[profile] = sandbox_configuration(root, agent, profile)
    slot, contexts = slot_audit(homes, cutoff)
    task = board.api('GET', '/issues/' + receipt['id'])
    require(task['companyId'] == company and task['assigneeAgentId'] == ceo_id and not task.get('parentId') and task['status'] == 'done', 'The native root is not the completed CEO objective')
    all_issues = board.api('GET', '/companies/' + company + '/issues')
    children = [item for item in all_issues if item.get('parentId') == task['id'] and item.get('companyId') == company]
    require(len(children) == 4 and {item['assigneeAgentId'] for item in children} == set(team.values()), 'The native workflow does not have exactly four approved specialist children')
    require(all(item.get('projectId') == task.get('projectId') and item['status'] == 'done' for item in children), 'Native child state/project scope differs')
    original_states = {item['id']: item['status'] for item in baseline['issues']}
    require(all(item['status'] == original_states[item['id']] for item in all_issues if item['id'] in original_states), 'An older native task changed state')
    held = []
    for old in json.loads((private / 'old-holds.json').read_text()):
        current = board.api('GET', '/issues/' + old['id'] + '/tree-holds?status=active')
        current = current.get('holds', []) if isinstance(current, dict) else current
        require({hold['id'] for hold in old['holds']} <= {hold['id'] for hold in current if hold.get('status') == 'active'}, 'An old native task hold was released')
        held.append(old['id'])

    def hud(path):
        request = urllib.request.Request('http://127.0.0.1:8765/api/' + path, headers={'X-Jarvis-Token': env['JARVIS_HUD_TOKEN']})
        with urllib.request.urlopen(request, timeout=30) as response: return response.read()

    execution = []; artifacts = []; worker_proofs = {}; run_index = {}; signed = {}; artifact_data = {}
    for item in [task, *children]:
        runs = board.api('GET', '/issues/' + item['id'] + '/runs')
        owned = [run for run in runs if run.get('agentId') == item['assigneeAgentId']]
        require(bool(owned) and max(owned, key=lambda run: run.get('startedAt') or run.get('createdAt') or '')['status'] == 'succeeded', 'Latest assigned employee execution has not succeeded')
        for reference in owned:
            run = board.api('GET', '/heartbeat-runs/' + reference['runId']); run_index[run['id']] = run
            require(run['agentId'] == item['assigneeAgentId'] and (run.get('issueId') or run.get('contextSnapshot', {}).get('issueId')) == item['id'], 'Native execution correlation differs')
            if reference['status'] != 'succeeded': continue
            hermes_id = run['resultJson']['run_id']; observed = runtime_usage(runtimes[item['assigneeAgentId']], hermes_id)
            require(observed['status'] == 'completed' and observed['run_id'] == hermes_id and
                observed['usage'].get('input_tokens', 0) > 0 and observed['usage'].get('output_tokens', 0) > 0, 'Hermes did not execute a real completed inference turn')
            requests = [row for row in contexts if row.get('issue_id') == item['id'] and row.get('paperclip_run_id') == run['id']]
            require(bool(requests), 'Succeeded native execution has no observed actual provider request')
            execution.append({'task_id': item['id'], 'agent_id': item['assigneeAgentId'], 'paperclip_run_id': run['id'],
                'hermes_run_id': hermes_id, 'status': 'succeeded', 'provider': 'openai-codex', 'model': 'gpt-6.1-sol',
                'endpoint_host': 'chatgpt.com', 'provider_request_ids': [row['api_request_id'] for row in requests],
                'authenticated_context_sha256': sorted({row['context_sha256'] for row in requests}),
                'input_tokens': observed['usage']['input_tokens'], 'output_tokens': observed['usage']['output_tokens']})
        comments = board.api('GET', '/issues/' + item['id'] + '/comments')
        if item['id'] != task['id']:
            latest = max(owned, key=lambda run: run.get('startedAt') or run.get('createdAt') or '')
            run = run_index[latest['runId']]; proof = None
            for comment in comments:
                for line in comment.get('body', '').splitlines():
                    if line.startswith('JARVIS_EXECUTION_EVIDENCE='):
                        candidate = json.loads(line.split('=', 1)[1])
                        if authentic(candidate, comment, item, run, env['JARVIS_EXECUTION_PROOF_KEY']): proof = candidate
            require(proof is not None, 'Latest worker run lacks authentic task/agent/run-bound completion evidence')
            profile = next(p for p, aid in team.items() if aid == item['assigneeAgentId']); spec = staffing.registry.profile(profile)
            require(staffing.inference_policy.proof_model(proof, people[item['assigneeAgentId']], spec['model'], env['JARVIS_EXECUTION_PROOF_KEY']) == 'gpt-6.1-sol' and
                proof.get('profile') == profile and proof.get('profile_sha256') == spec['sha256'], 'Signed worker capability/model receipt differs')
            tools = proof.get('tool_calls', []); allowed = set(spec['tools']) | {'agent_identity'}
            require(all(call.get('tool') in allowed or (call.get('success') is False and call.get('result', {}).get('policy_denied') is True) for call in tools), 'A worker executed a tool outside its frozen capability')
            require(REQUIRED[profile] <= {call['tool'] for call in tools if call.get('success') is True}, 'Required role execution tools are missing')
            signed[profile] = proof
            worker_proofs[profile] = {'task_id': item['id'], 'identifier': item['identifier'], 'agent_id': item['assigneeAgentId'],
                'paperclip_run_id': run['id'], 'profile_sha256': spec['sha256'],
                'successful_tools': sorted({call['tool'] for call in tools if call.get('success') is True})}
            if profile == 'system_administration':
                require({model['name']: model['size_bytes'] for model in proof.get('inventory', [])} == {model['name']: model['size'] for model in models}, 'Signed Systems inventory differs from the live Ollama metadata API')
        attachments = board.api('GET', '/issues/' + item['id'] + '/attachments')
        expected_name = 'workforce-readiness.md' if item['id'] == task['id'] else REPORTS[next(p for p, aid in team.items() if aid == item['assigneeAgentId'])]
        accepted_runs = {run['runId'] for run in owned if run['status'] == 'succeeded'} if item['id'] == task['id'] else {latest['runId']}
        require(any(artifact['originalFilename'] == expected_name and artifact.get('originatingRunId') in accepted_runs
            for artifact in attachments), 'Required native report is absent from the accepted execution')
        for artifact in attachments:
            require(artifact.get('createdByAgentId') == item['assigneeAgentId'] and artifact.get('originatingRunId') in run_index,
                'Artifact is not authored by its assigned succeeded execution')
            data = hud('tasks/' + item['id'] + '/artifacts/' + artifact['id'])
            require(len(data) == artifact['byteSize'] and digest(data) == artifact['sha256'], 'Native artifact bytes differ from their receipt')
            artifact_data[artifact['id']] = {'metadata': artifact, 'bytes': data, 'task_id': item['id']}
            artifacts.append({key: artifact.get(key) for key in ('id', 'originalFilename', 'byteSize', 'sha256', 'createdByAgentId', 'originatingRunId')})
    require(set(worker_proofs) == set(PROFILES), 'All four scoped worker proofs are required')
    for dependent, source in [('software_development', 'research'), ('security_analysis', 'software_development')]:
        native = board.api('GET', '/issues/' + worker_proofs[dependent]['task_id'])
        require(worker_proofs[source]['task_id'] in {link['id'] for link in native.get('blockedBy', [])}, 'A required native dependency is absent')
        reads = [call for call in signed[dependent]['tool_calls'] if call.get('tool') == 'read_worker_artifacts' and call.get('success')]
        retrieved = [artifact for call in reads for artifact in call.get('result', {}).get('artifacts', [])]
        require(any(artifact.get('issue_id') == worker_proofs[source]['task_id'] and
            artifact.get('artifact_id') in artifact_data and
            artifact.get('sha256') == artifact_data[artifact['artifact_id']]['metadata']['sha256'] for artifact in retrieved),
            'Dependent worker did not retrieve the real prerequisite artifact bytes')
    software_tools = signed['software_development']['tool_calls']
    require(any(call.get('tool') == 'terminal' and call.get('success') and
        re.search(r'\bpython(?:3(?:\.[0-9]+)?)?\b|\bunittest\b', str(call.get('args', {}).get('command', ''))) and
        re.search(r'Ran\s+2\s+tests?[\s\S]*\bOK\b', str(call.get('result', {}).get('output', '')))
        for call in software_tools), 'Software lacks an actual Python invocation with two passing tests')
    software_sources = [artifact for artifact in artifact_data.values() if artifact['task_id'] == worker_proofs['software_development']['task_id'] and
        artifact['metadata'].get('originatingRunId') == worker_proofs['software_development']['paperclip_run_id'] and
        artifact['metadata']['originalFilename'] in ('validator.py', 'test_validator.py')]
    require({artifact['metadata']['originalFilename'] for artifact in software_sources} == {'validator.py', 'test_validator.py'}, 'Accepted software source/test artifact bytes are missing')
    security_tools = signed['security_analysis']['tool_calls']
    security_reads = [artifact for call in security_tools if call.get('tool') == 'read_worker_artifacts' and call.get('success')
        for artifact in call.get('result', {}).get('artifacts', [])]
    require(any(artifact.get('artifact_id') in {source['metadata']['id'] for source in software_sources} for artifact in security_reads),
        'Security did not retrieve the accepted actual source/test artifacts')
    require(any(call.get('tool') == 'terminal' and call.get('success') and
        re.search(r'\bpython(?:3(?:\.[0-9]+)?)?\b|\bunittest\b|\bpytest\b', str(call.get('args', {}).get('command', ''))) and
        re.search(r'Ran\s+[1-9][0-9]*\s+tests?[\s\S]*\bOK\b|[1-9][0-9]* passed|AST_PARSE_OK', str(call.get('result', {}).get('output', '')))
        for call in security_tools), 'Security lacks real independent Python/test execution evidence')
    system_diagnostics = []
    for call in signed['system_administration']['tool_calls']:
        if call.get('tool') != 'terminal' or not call.get('success'): continue
        for line in str(call.get('result', {}).get('output', '')).splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and all(key in value for key in ('uid', 'platform', 'python_version')):
                system_diagnostics.append(value)
    require(any(value['uid'] == 1000 and value['platform'] and value['python_version'] for value in system_diagnostics),
        'Systems did not retrieve the actual non-root sandbox diagnostic data')
    final_comments = board.api('GET', '/issues/' + task['id'] + '/comments')
    followup = receipt['followup']
    require(any(c['id'] == followup['comment_id'] and c.get('authorUserId') for c in final_comments) and
        any(c['id'] == followup['ceo_comment_id'] and c.get('authorAgentId') == ceo_id for c in final_comments), 'The human follow-up and new CEO response are not persisted')
    result = {'status': 'passed', 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'task_id': task['id'], 'identifier': task['identifier'], 'ceo_agent_id': ceo_id,
        'workers': worker_proofs, 'executions': execution, 'artifacts': artifacts, 'shared_inference': slot,
        'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'endpoint_host': 'chatgpt.com',
        'native_issue_scoped_sessions': True, 'managed_adapter_secrets': True, 'all_selected_employees_idle': True,
        'future_hiring_requires_human_approval': True, 'shared_root_auth_resolves': True,
        'profile_credentials_do_not_shadow_root': True, 'source_cli_login_unchanged': True,
        'automatic_auxiliary_inference_disabled': True, 'local_fallback_disabled': True,
        'independent_private_profiles': True, 'sandboxes': sandboxes, 'old_native_holds_preserved': held,
        'older_task_states_preserved': True, 'protected_services_unchanged': preserved,
        'original_ollama_model_digests_preserved': True, 'ollama_model_count': len(models),
        'followup': {'human_comment_id': followup['comment_id'], 'ceo_comment_id': followup['ceo_comment_id'], 'same_objective': True},
        'scope': 'Existing native task/run/proof/artifact verification; no task creation, inference or service changes'}
    destination = root / 'docs/evidence/codex-workforce-execution.json'
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Avoid exception representations containing URLs, headers or private data.
        print(json.dumps({'status': 'failed', 'error': str(error) if isinstance(error, AssertionError) else type(error).__name__}))
        raise SystemExit(1)
