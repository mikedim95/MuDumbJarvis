#!/usr/bin/env python3
"""Opt-in, real Paperclip worker timing; not a HUD-submission acceptance test.

Operator creates one fresh persistent issue through Paperclip's documented API.
JARVIS's authenticated read endpoints verify the same issue and execution result.
No agent defaults, services, model files, or product APIs are modified.

Offline plan (no network/artifacts):
  python3 tests/agent_speed.py --profile control4 --model jarvis-hermes:3b
Create ONLY after all other inference is idle and both aliases already exist:
  python3 tests/agent_speed.py --profile control4 --model jarvis-hermes:3b --create
  python3 tests/agent_speed.py --profile candidate24 --model jarvis-hermes-aigoat24:3b --create --compare docs/evidence/agent-speed-control4.json
Resume a known issue without POST or new inference:
  python3 tests/agent_speed.py --profile control4 --model jarvis-hermes:3b --resume ISSUE_UUID
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
PROMPT = 'Use local_ollama_models to retrieve installed Ollama models. Report the total count and exact name and byte size of the first three models returned. Keep prose under 60 words.'
SECRET_NAMES = ('JARVIS_HUD_TOKEN', 'PAPERCLIP_API_KEY', 'JARVIS_EXECUTION_PROOF_KEY')
API_CALL = re.compile(r'API call #(\d+): model=(\S+) provider=(\S+) in=(\d+) out=(\d+) total=(\d+) latency=([\d.]+)s')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def date(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def settings(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                name, value = line.split('=', 1)
                values[name.strip()] = value.strip().strip('"\'')
    return {**values, **os.environ}


class Client:
    def __init__(self, base, headers=None):
        url = urllib.parse.urlsplit(base)
        require(url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password
                and not url.query and not url.fragment, 'Endpoint cannot contain embedded credentials/query/fragment')
        self.base, self.headers = base.rstrip('/'), headers or {}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method, path, body=None, attempts=1):
        for attempt in range(attempts):
            request = urllib.request.Request(self.base + path, method=method,
                headers={**self.headers, 'Content-Type': 'application/json'},
                data=None if body is None else json.dumps(body).encode())
            try:
                with self.opener.open(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt + 1 == attempts:
                    raise RuntimeError(f'{method} {path} returned HTTP {exc.code}') from None
            except (urllib.error.URLError, TimeoutError):
                if attempt + 1 == attempts:
                    raise RuntimeError(f'{method} {path} failed; uncertain POST must reuse its original request ID') from None
            time.sleep(1)


def inventory(client):
    result = client.call('GET', '/api/tags', attempts=2)
    return [{'name': item['name'], 'size_bytes': item['size']} for item in result.get('models', [])]


def model_snapshot(client, model):
    tags = client.call('GET', '/api/tags')
    item = next((item for item in tags.get('models', []) if item.get('name') == model), None)
    require(item is not None, 'Exact selected model alias must already be installed; no pull attempted')
    show = client.call('POST', '/api/show', {'model': model})
    require(not show.get('remote_host') and not show.get('remote_model') and not model.endswith(':cloud'),
            'Worker benchmark requires a local model')
    weight = None
    for line in show.get('modelfile', '').splitlines():
        match = re.fullmatch(r'FROM\s+.*[/\\]sha256-([a-f0-9]{64})\s*', line)
        if match:
            weight = match.group(1)
    return {'name': model, 'digest': item.get('digest'), 'size': item.get('size'), 'details': item.get('details'),
            'weight_blob_sha256': weight, 'parameters': show.get('parameters'),
            'template_sha256': digest(show.get('template')), 'system_sha256': digest(show.get('system'))}


def signed_proof(task, worker, company, key):
    expected_session = f'paperclip:company:{company}:agent:{worker}:issue:{task["id"]}'
    candidates = []
    for comment in sorted(task.get('comments', []), key=lambda item: item.get('createdAt') or ''):
        if comment.get('authorAgentId') != worker:
            continue
        for line in comment.get('body', '').splitlines():
            if not line.startswith('JARVIS_EXECUTION_EVIDENCE='):
                continue
            try:
                proof = json.loads(line.split('=', 1)[1])
            except ValueError:
                continue
            if not isinstance(proof, dict):
                continue
            unsigned = {name: value for name, value in proof.items() if name != 'signature'}
            signature = hmac.new(key.encode(), json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
            if (proof.get('version') == 2 and hmac.compare_digest(str(proof.get('signature', '')), signature)
                    and proof.get('agent_id') == worker and proof.get('session_id') == expected_session
                    and proof.get('tool') == 'local_ollama_models' and isinstance(proof.get('models'), list)
                    and ('issue_id' not in proof or proof['issue_id'] == task['id'])):
                candidates.append((proof, comment))
    require(candidates, 'No authentic worker-authored evidence bound to this exact company/agent/issue session')
    return candidates[-1]


def runtime_metrics(root, session, run, model):
    start, finish = date(run['startedAt']), date(run['finishedAt'])
    rows, calls, turns = [], [], []
    for line in (root / '.runtime/hermes/logs/agent.log').read_text().splitlines():
        if session not in line:
            continue
        try:
            stamp = dt.datetime.strptime(line[:23], '%Y-%m-%d %H:%M:%S,%f').replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if not start <= stamp <= finish:
            continue
        if 'conversation turn:' in line or 'tool local_ollama_models completed' in line:
            rows.append(line)
        if 'conversation turn:' in line:
            turns.append(line)
        match = API_CALL.search(line)
        if match:
            cache = re.search(r'\bcache=(\d+)/(\d+)', line)
            calls.append({'timestamp': stamp.isoformat(), 'call_index': int(match[1]), 'model': match[2],
                          'provider': match[3], 'input_tokens': int(match[4]), 'output_tokens': int(match[5]),
                          'total_tokens': int(match[6]), 'provider_call_wall_seconds': float(match[7]),
                          'cache_read_tokens': int(cache[1]) if cache else None,
                          'cache_prompt_tokens': int(cache[2]) if cache else None})
    require(turns and all(f'model={model} provider=custom ' in line for line in turns),
            'Issue-correlated runtime turn did not use the exact expected local model/provider')
    require(calls and all(call['model'] == model and call['provider'] == 'custom' for call in calls),
            'Completed provider call logs do not establish the expected local model')
    return {'runtime_log': rows, 'completed_model_calls': calls, 'model_call_count': len(calls),
            'input_tokens': sum(call['input_tokens'] for call in calls),
            'output_tokens': sum(call['output_tokens'] for call in calls),
            'cache_read_tokens': sum(call['cache_read_tokens'] for call in calls) if all(call['cache_read_tokens'] is not None for call in calls) else None,
            'cache_note': 'Input totals include cached prompt tokens. Missing cache counters mean unknown; canonical cachedInputTokens=0 is not proof of no cache.',
            'provider_call_wall_seconds': round(sum(call['provider_call_wall_seconds'] for call in calls), 4),
            'latency_scope': 'Provider-call wall time includes queue/prefill/decode; not native decode-only throughput',
            'native_prompt_eval_duration': None, 'native_eval_duration': None,
            'native_duration_note': 'Canonical runs and Hermes call logs do not expose reliable native per-call prompt/decode eval durations',
            'auxiliary_call_scope': 'Only this canonical run window and exact issue session; separately attributed post-run title generation is excluded'}


def hermes_snapshot(container, run_id):
    require(re.fullmatch(r'run_[a-f0-9]+', run_id or ''), 'Canonical adapter result has no valid linked Hermes run ID')
    # This code reads an existing run only. The runtime credential stays inside
    # the isolated container and is never returned to the caller or artifact.
    code = '''import json,os,sys,urllib.request
try:
 r=urllib.request.Request('http://127.0.0.1:8642/v1/runs/'+sys.argv[1],headers={'Authorization':'Bearer '+os.environ['API_SERVER_KEY']})
 x=json.load(urllib.request.urlopen(r,timeout=15))
 print(json.dumps({k:x.get(k) for k in ('run_id','status','session_id','usage')}))
except Exception as e:
 print(json.dumps({'read_error':type(e).__name__}));sys.exit(1)
'''
    result = subprocess.run(['docker', 'exec', container, '/opt/hermes/.venv/bin/python', '-c', code, run_id],
                            capture_output=True, text=True, timeout=25, check=False)
    require(result.returncode == 0, 'Cannot read linked existing Hermes run through the isolated runtime')
    return json.loads(result.stdout)


def verify(args, env, board, hud, ollama, task, document):
    worker, company, project = (env[name] for name in ('PAPERCLIP_AGENT_ID', 'PAPERCLIP_COMPANY_ID', 'PAPERCLIP_PROJECT_ID'))
    issue = board.call('GET', '/issues/' + task['id'], attempts=2)
    require(issue.get('companyId') == company and issue.get('projectId') == project and
            issue.get('assigneeAgentId') == worker and issue.get('parentId') is None, 'Canonical issue scope/assignee mismatch')
    require(issue.get('description') == PROMPT and issue.get('status') == task.get('status') == 'done', 'Canonical/HUD task mismatch or no actual completion')
    override = issue.get('assigneeAdapterOverrides') or {}
    require(override.get('adapterConfig', {}).get('payloadTemplate', {}).get('model') == args.model, 'Per-issue selected model override was not persisted')
    require(not task.get('children'), 'Worker benchmark unexpectedly created delegated children')
    proof, comment = signed_proof(task, worker, company, env['JARVIS_EXECUTION_PROOF_KEY'])
    runs = board.call('GET', '/issues/' + task['id'] + '/runs', attempts=2)
    worker_runs = sorted([run for run in runs if run.get('agentId') == worker], key=lambda run: run.get('startedAt') or run.get('createdAt') or '')
    require(worker_runs and worker_runs[-1].get('runId') == proof.get('paperclip_run_id') and
            worker_runs[-1].get('status') == 'succeeded', 'Evidence is not the latest succeeded canonical worker execution')
    run = board.call('GET', '/heartbeat-runs/' + proof['paperclip_run_id'], attempts=2)
    require(run.get('id') == proof['paperclip_run_id'] and run.get('companyId') == company and
            run.get('agentId') == worker and run.get('status') == 'succeeded' and
            run.get('contextSnapshot', {}).get('issueId') == task['id'], 'Canonical execution actor/status/scope mismatch')
    matching_audits = []
    for line in (ROOT / '.runtime/hermes/logs/paperclip-tools.jsonl').read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (row.get('issue_id') == task['id'] and row.get('paperclip_run_id') == proof['paperclip_run_id']
                and row.get('session_id') == proof['session_id'] and row.get('tool') == 'local_ollama_models'
                and row.get('result', {}).get('source') == 'Ollama /api/tags'):
            matching_audits.append(row)
    require(matching_audits, 'No fresh exact issue/run/session local tool audit')
    audit = matching_audits[-1]
    actual = [{'name': model.get('name'), 'size_bytes': model.get('size_bytes')} for model in audit['result']['models']]
    signed = [{'name': model.get('name'), 'size_bytes': model.get('size_bytes')} for model in proof['models']]
    current = inventory(ollama)
    require(actual == signed and current == actual, 'Authenticated execution evidence differs from the real ordered Ollama inventory')
    require(document['inventory_before'] == current, 'Inventory changed during the sample; matched timing is inconclusive')
    prose = comment['body'].split('\n\nVerified local_ollama_models data', 1)[0]
    first = actual[:3]
    prose_names_bytes = all(model['name'] in prose and
        (str(model['size_bytes']) in prose or f"{model['size_bytes']:,}" in prose) for model in first)
    prose_count = re.search(r'\b' + str(len(actual)) + r'\b', prose) is not None
    model_metrics = runtime_metrics(ROOT, proof['session_id'], run, args.model)
    usage = run.get('usageJson') or {}
    for local_key, canonical_key in (('input_tokens', 'inputTokens'), ('output_tokens', 'outputTokens')):
        require(usage.get(canonical_key) == model_metrics[local_key], 'Runtime call-token sum differs from canonical usage')
    linked = (run.get('resultJson') or {}).get('run_id')
    hermes = hermes_snapshot(args.hermes_container, linked)
    require(hermes.get('run_id') == linked and hermes.get('status') == 'completed' and
            hermes.get('session_id') == proof['session_id'], 'Linked Hermes run did not complete this exact issue session')
    for key in ('input_tokens', 'output_tokens'):
        require((hermes.get('usage') or {}).get(key) == model_metrics[key], 'Hermes usage differs from canonical/runtime usage')
    finished_model = model_snapshot(ollama, args.model)
    require(finished_model['digest'] == document['model_before']['digest'], 'Selected model digest changed during sample')
    span = (date(run['finishedAt']) - date(run['startedAt'])).total_seconds()
    return {'execution_verified': True, 'canonical_hud_id_status_match': True,
        'canonical_issue': {key: issue.get(key) for key in ('id', 'identifier', 'companyId', 'projectId', 'assigneeAgentId', 'status', 'createdAt', 'completedAt')},
        'canonical_run': {key: run.get(key) for key in ('id', 'companyId', 'agentId', 'status', 'startedAt', 'finishedAt')},
        'canonical_usage': {key: usage.get(key) for key in ('inputTokens', 'outputTokens', 'rawInputTokens', 'rawOutputTokens', 'cachedInputTokens', 'usageSource', 'model')},
        'canonical_run_wall_seconds': round(span, 6), 'hermes_run': hermes,
        'model_metrics': model_metrics, 'signed_worker_evidence': proof, 'actual_tool_audit': audit,
        'inventory_after': current, 'inventory_sha256': digest(current), 'model_after': finished_model,
        'result_prose': prose, 'result_prose_words': len(prose.split()),
        'output_contract': {'first_three_exact_names_and_bytes': prose_names_bytes, 'numeric_total_count_present': prose_count,
                            'under_60_words': len(prose.split()) < 60},
        'canonical_result_author_worker': comment['authorAgentId'] == worker,
        'next_sample_note': 'Wait for unrelated/auxiliary inference to become idle before another sample; post-run title calls can occur after this canonical task window.'}


def comparison(document, path):
    control = json.loads(path.read_text())
    require(control.get('verification', {}).get('execution_verified'), 'Comparison control lacks real verified execution')
    require(control.get('prompt') == document['prompt'] and control['verification']['inventory_sha256'] == document['verification']['inventory_sha256'],
            'Matched samples require the same prompt and ordered model inventory')
    left, right = control['model_before'], document['model_before']
    require(left.get('weight_blob_sha256') and left['weight_blob_sha256'] == right.get('weight_blob_sha256'), 'Cannot establish the same model weights between aliases')
    require(left['template_sha256'] == right['template_sha256'] and left['system_sha256'] == right['system_sha256'], 'Model template/system differ; not a matched thread-profile comparison')
    base, candidate = control['verification'], document['verification']
    return {'control_profile': control['profile'], 'candidate_profile': document['profile'], 'same_weights_prompt_inventory_template_system': True,
            'control_run_seconds': base['canonical_run_wall_seconds'], 'candidate_run_seconds': candidate['canonical_run_wall_seconds'],
            'run_wall_speedup': round(base['canonical_run_wall_seconds'] / candidate['canonical_run_wall_seconds'], 4),
            'control_model_calls': base['model_metrics']['model_call_count'], 'candidate_model_calls': candidate['model_metrics']['model_call_count'],
            'control_output_tokens': base['model_metrics']['output_tokens'], 'candidate_output_tokens': candidate['model_metrics']['output_tokens'],
            'interpretation': 'Real task latency includes model calls, tools and orchestration. Different output lengths/call counts must be considered; no automatic profile promotion.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--model', required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--create', action='store_true')
    action.add_argument('--resume', type=UUID)
    parser.add_argument('--request-id', type=UUID)
    parser.add_argument('--env-file', type=Path, default=ROOT / 'deploy/.env')
    parser.add_argument('--jarvis-url', default='http://127.0.0.1:8765')
    parser.add_argument('--paperclip-url', default='http://127.0.0.1:3100')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    parser.add_argument('--hermes-container', default='jarvis-hermes')
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.profile), 'Profile must be a simple filename label')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.hermes_container), 'Invalid runtime container name')
    require(0 < args.timeout <= 3600, 'Task timeout must be in (0,3600]')
    plan = {'profile': args.profile, 'model': args.model, 'prompt': PROMPT,
            'submission_provenance': 'Operator-created Paperclip API issue; authenticated JARVIS result reads, not a HUD-submission test',
            'assigneeAdapterOverrides': {'adapterConfig': {'payloadTemplate': {'model': args.model}}}}
    if not args.create and not args.resume:
        print(json.dumps({'status': 'not_executed', **plan}, indent=2))
        return 0
    env = settings(args.env_file)
    for name in (*SECRET_NAMES, 'PAPERCLIP_COMPANY_ID', 'PAPERCLIP_PROJECT_ID', 'PAPERCLIP_AGENT_ID'):
        require(env.get(name), 'Missing server-side test configuration: ' + name)
    board = Client(args.paperclip_url + '/api', {'Authorization': 'Bearer ' + env['PAPERCLIP_API_KEY']})
    hud = Client(args.jarvis_url + '/api', {'X-Jarvis-Token': env['JARVIS_HUD_TOKEN']})
    ollama = Client(args.ollama_url)
    output = ROOT / 'docs/evidence' / ('agent-speed-' + args.profile + '.json')
    stage = ROOT / '.runtime' / ('agent-speed-' + args.profile + '.json')
    lock_path = ROOT / '.runtime/agent-speed.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    native_lock_path = ROOT / '.runtime/ollama-benchmark.lock'
    with lock_path.open('a+') as lock, native_lock_path.open('a+') as native_lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(native_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another agent/native speed test holds the lock; no task submitted') from None
        document = {'started_at': now(), 'status': 'running', **plan}
        if args.resume and stage.exists():
            previous = json.loads(stage.read_text())
            if previous.get('issue_id') == str(args.resume):
                require(previous.get('model') == args.model and previous.get('prompt') == PROMPT, 'Resume profile contract differs from original submission')
                document = previous
                document.update({'status': 'resuming', 'resumed_at': now()})
        if args.create and stage.exists():
            previous = json.loads(stage.read_text())
            require(not previous.get('issue_id') and args.request_id and previous.get('request_id') == str(args.request_id),
                    'Profile has a prior submission: resume its issue UUID, or recover an uncertain POST with its SAME --request-id')
            require(previous.get('model') == args.model and previous.get('prompt') == PROMPT,
                    'Uncertain submission recovery must preserve model and prompt')
            document = previous
            document.update({'status': 'recovering_same_submission', 'resumed_at': now()})
        def save():
            for path in (output, stage):
                path.parent.mkdir(parents=True, exist_ok=True)
                text = json.dumps(document, indent=2)
                for name in SECRET_NAMES:
                    require(env[name] not in text, 'A server secret appeared in proposed evidence; artifact not saved')
                path.with_suffix(path.suffix + '.tmp').write_text(text + '\n')
                path.with_suffix(path.suffix + '.tmp').replace(path)
        try:
            if 'inventory_before' not in document:
                document['inventory_before'] = inventory(ollama)
                document['model_before'] = model_snapshot(ollama, args.model)
            if args.create:
                agent = board.call('GET', '/agents/' + env['PAPERCLIP_AGENT_ID'])
                require(agent.get('companyId') == env['PAPERCLIP_COMPANY_ID'] and agent.get('adapterType') == 'hermes_gateway', 'Worker actor/configuration mismatch')
                template = (agent.get('adapterConfig') or {}).get('payloadTemplate') or {}
                require(isinstance(template, dict) and not set(template) - {'model'}, 'Worker payloadTemplate has extra fields; review override merge before benchmarking')
                nonce = document.get('request_id') or str(args.request_id or uuid4())
                document.update({'request_id': nonce, 'submission_started_at': now()})
                save()  # Recover the SAME native nonce after an uncertain POST.
                body = {'title': 'Benchmark ' + args.profile + ': local Ollama inventory', 'description': PROMPT,
                    'status': 'todo', 'priority': 'medium', 'projectId': env['PAPERCLIP_PROJECT_ID'],
                    'assigneeAgentId': env['PAPERCLIP_AGENT_ID'], 'assigneeAdapterOverrides': plan['assigneeAdapterOverrides'],
                    'idempotencyKey': 'jarvis-agent-speed:' + nonce, 'allowDuplicate': True}
                issue = board.call('POST', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/issues', body, attempts=2)
                document['issue_id'], document['identifier'] = issue['id'], issue['identifier']
                save()
                replay = board.call('POST', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/issues', body, attempts=2)
                require(replay.get('id') == issue['id'], 'Native idempotency replay created a different issue')
                document['idempotency_replay_same_id'] = True
            else:
                document['issue_id'] = str(args.resume)
            save()
            print('Monitoring actual operator-created issue:', document.get('identifier', document['issue_id']), document['issue_id'], flush=True)
            deadline, last = time.monotonic() + args.timeout, None
            while time.monotonic() < deadline:
                task = hud.call('GET', '/tasks/' + document['issue_id'], attempts=2)
                if task.get('status') != last:
                    print('Actual Paperclip/HUD status:', task.get('status'), flush=True)
                    last = task.get('status')
                document['last_observed_at'], document['last_observed_status'] = now(), task.get('status')
                save()
                require(task.get('status') not in ('blocked', 'cancelled'), 'Real task failed/blocked; no false completion or automatic retry')
                if task.get('status') == 'done' and not any(run.get('status') in ('running', 'queued') for run in task.get('runs', [])):
                    document['verification'] = verify(args, env, board, hud, ollama, task, document)
                    document['finished_at'] = now()
                    document['submission_to_observation_seconds'] = round((date(document['finished_at']) - date(document.get('submission_started_at', document['started_at']))).total_seconds(), 6)
                    contract = document['verification']['output_contract']
                    document['status'] = 'verified' if all(contract.values()) else 'verified_execution_with_output_limitations'
                    if args.compare:
                        document['comparison'] = comparison(document, args.compare)
                    save()
                    print('Verified real worker execution:', document['status'], 'run seconds=', document['verification']['canonical_run_wall_seconds'], flush=True)
                    return 0
                time.sleep(3)
            raise TimeoutError('Task observation deadline exceeded; canonical job was left untouched and may still be running')
        except Exception as exc:
            document.update({'status': 'failed', 'finished_at': now(), 'error': str(exc)})
            for name in SECRET_NAMES:
                document['error'] = document['error'].replace(env[name], '[REDACTED]')
            save()
            print(document['error'], file=sys.stderr)
            return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
