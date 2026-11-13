#!/usr/bin/env python3
"""Opt-in role acceptance through JARVIS. This is a test driver, not a scheduler."""
import argparse
import datetime
import hashlib
import hmac
import json
from pathlib import Path
import shlex
import sys
import time
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy'))
import staffing

PROMPTS = {
    'research': 'Phase 12 Research runtime acceptance. Use research_sources to retrieve real current primary-source README data for garak, pyrit and promptfoo. Compare their capabilities and architectures in a concise technical Markdown report with actual source URLs, immutable blob hashes and clear limits. Persist your report using publish_artifact(name="phase12-framework-report.md", content=your report). Report the actual native artifact IDs. Do not claim any framework was executed. No shell, host changes, hiring or cloud LLM.',
    'software_development': (
        'Phase 12 isolated runtime acceptance. Use actual tools, in this order. '
        '1. Call agent_identity. 2. Call read_file with path=/opt/data/config.yaml. The expected denial is a successful boundary check, not a reason to stop. '
        '3. In a foreground terminal call, execute exactly "python3 /usr/local/share/jarvis/isolation_checks.py". '
        'This is an OPERATOR-AUTHORED fixture with eight isolation/resource checks; do not claim you wrote it. '
        '4. Use write_file to create CURRENT_WORKSPACE/test_demo.py: define add(a,b), and a unittest.TestCase with two test_* methods for add(2,3)==5 and add(-2,2)==0; finish with unittest.main(). '
        '5. Run python3 test_demo.py in a separate terminal call and require real passing output. Python unittest is installed; pytest is not. '
        '6. Use write_file to create promptfoo.json from the documented echo example in your context, with three different fixed text cases and matching equals assertions. '
        '7. Run a separate terminal call: promptfoo eval -c promptfoo.json --no-cache --no-write --max-concurrency 1 --output results.json. '
        'Use background=false. No python -c, shell wrappers, cloud providers or model-graded assertions. '
        'The runtime stores actual source/config/results files after all checks pass. Return only a concise factual result and limits; this is a toy evaluation harness, not proof of security efficacy.')
}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--role', choices=list(PROMPTS), required=True)
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({'status': 'not_executed'}))
        return
    board = staffing.Board(staffing.settings())
    roster = board.api('GET', '/companies/' + board.env['PAPERCLIP_COMPANY_ID'] + '/agents')
    agent = next(a for a in roster if ((a.get('metadata') or {}).get('jarvis') or {}).get('profile') == args.role)
    stage_file = ROOT / '.runtime' / ('phase12-' + args.role + '-stage.json')
    stage = json.loads(stage_file.read_text()) if stage_file.exists() else {
        'request_id': str(uuid4()), 'started_at': now(), 'agent_id': agent['id'], 'input': PROMPTS[args.role]}
    stage_file.write_text(json.dumps(stage, indent=2))

    def hud(method, path, body=None):
        request = urllib.request.Request('http://127.0.0.1:8765/api/' + path, method=method,
            headers={'X-Jarvis-Token': board.env['JARVIS_HUD_TOKEN'], 'Content-Type': 'application/json'},
            data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)

    if not stage.get('task_id'):
        task = hud('POST', 'tasks', {'input': stage['input'], 'request_id': stage['request_id'], 'agent_id': agent['id']})
        stage.update({'task_id': task['id'], 'identifier': task['identifier']})
        stage_file.write_text(json.dumps(stage, indent=2))
    print(json.dumps({'role': args.role, 'task_id': stage['task_id'], 'identifier': stage['identifier']}), flush=True)
    last = None
    for _ in range(600):
        task = hud('GET', 'tasks/' + stage['task_id'])
        progress = (task['status'], len(task['comments']), tuple((r['runId'], r['status']) for r in task['runs']))
        if progress != last:
            print(json.dumps({'at': now(), 'status': task['status'], 'comments': len(task['comments']),
                'runs': [{'id': r['runId'], 'status': r['status']} for r in task['runs']]}), flush=True)
            last = progress
        if task['status'] in ('done', 'blocked', 'cancelled', 'in_review') and not task.get('executionRunId'):
            break
        time.sleep(3)
    assert task['status'] == 'done', 'Real role task is not complete; inspect native evidence: ' + task['id']
    canonical = board.api('GET', '/issues/' + task['id'])
    assert canonical['id'] == task['id'] and canonical['status'] == task['status']
    proofs = []
    for comment in sorted(task['comments'], key=lambda value: value.get('createdAt') or ''):
        if comment.get('authorAgentId') != agent['id']:
            continue
        for line in comment['body'].splitlines():
            if line.startswith('JARVIS_EXECUTION_EVIDENCE='):
                proofs.append(json.loads(line.split('=', 1)[1]))
    proof = proofs[-1]
    assert proof['version'] == 3 and proof['kind'] == 'execution' and proof['task_status'] == 'done'
    unsigned = {k: v for k, v in proof.items() if k != 'signature'}
    derived = hmac.new(board.env['JARVIS_EXECUTION_PROOF_KEY'].encode(),
        ('jarvis-employee-proof-v3:' + agent['id']).encode(), hashlib.sha256).hexdigest()
    signature = hmac.new(derived.encode(), json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(signature, proof['signature'])
    assert proof['agent_id'] == agent['id'] and proof['issue_id'] == task['id']
    assert proof['session_id'] == 'paperclip:company:' + board.env['PAPERCLIP_COMPANY_ID'] + ':agent:' + agent['id'] + ':issue:' + task['id']
    for _ in range(12):
        run = board.api('GET', '/heartbeat-runs/' + proof['paperclip_run_id'])
        if run['status'] not in ('running', 'queued'):
            break
        time.sleep(1)
    assert run['status'] == 'succeeded' and run['agentId'] == agent['id'] and run['contextSnapshot']['issueId'] == task['id']
    native_artifacts = board.api('GET', '/issues/' + task['id'] + '/attachments')
    by_id = {a['id']: a for a in native_artifacts}
    verified_files = []
    contents = {}
    for receipt in proof['artifacts']:
        native = by_id[receipt['id']]
        assert native['createdByAgentId'] == agent['id'] and native['originatingRunId'] == run['id']
        request = urllib.request.Request('http://127.0.0.1:3100/api/attachments/' + native['id'] + '/content',
            headers={'Authorization': 'Bearer ' + board.env['PAPERCLIP_API_KEY']})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
        assert len(raw) == native['byteSize'] == receipt['byteSize']
        assert hashlib.sha256(raw).hexdigest() == native['sha256'] == receipt['sha256']
        contents[native['sha256']] = raw
        verified_files.append({'id': native['id'], 'name': native['originalFilename'], 'sha256': native['sha256'], 'bytes': len(raw)})
    assert verified_files
    home = ROOT / '.runtime/employees' / agent['id']
    cutoff = run['startedAt'].replace('T', ' ')[:19]
    trace = [line for line in (home / 'logs/agent.log').read_text().splitlines() if line[:19] >= cutoff and 'issue:' + task['id'] in line and
        any(value in line for value in ('conversation turn:', 'API call #', ' completed ('))]
    assert any('model=jarvis-hermes-aigoat24:3b provider=custom' in line for line in trace)
    names = {event['tool'] for event in proof['tool_calls'] if event['success']}
    assert 'publish_artifact' in names or proof.get('runtime_deliveries')
    policy_probes = []
    source_writes = []
    for candidate in proofs:
        if (candidate.get('version') != 3 or candidate.get('agent_id') != agent['id'] or
                candidate.get('issue_id') != task['id'] or candidate.get('company_id') != proof['company_id'] or
                candidate.get('profile_sha256') != proof['profile_sha256']):
            continue
        payload = {k: v for k, v in candidate.items() if k != 'signature'}
        expected = hmac.new(derived.encode(), json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, candidate.get('signature', '')):
            continue
        for event in candidate.get('tool_calls', []):
            if event['tool'] == 'write_file' and event['success'] and event.get('content_sha256'):
                source_writes.append({'native_run_id': candidate['paperclip_run_id'],
                    'tool_call_id': event['tool_call_id'], 'sha256': event['content_sha256'],
                    'path': event['args'].get('path'),
                    'current_run': candidate['paperclip_run_id'] == run['id']})
            if event['tool'] == 'read_file' and event['result'].get('policy_denied') and event['result'].get('executed') is False:
                policy_probes.append({'native_run_id': candidate['paperclip_run_id'], 'tool_call_id': event['tool_call_id'],
                    'current_run': candidate['paperclip_run_id'] == run['id'],
                    'scope': 'Verified same-issue history; never represented as a new tool call'})
    if args.role == 'research':
        assert 'research_sources' in names and any(file['name'].endswith('.md') for file in verified_files)
    else:
        assert 'terminal' in names and policy_probes
        assert any('Ran ' in event['result'].get('output', '') and 'OK' in event['result'].get('output', '') for event in proof['tool_calls'])
        assert any('promptfoo' in str(event['args'].get('command', '')) and event['success'] for event in proof['tool_calls'])
        assert any(file['name'].endswith('.py') for file in verified_files)
        evaluation = next(e for e in proof['framework_evaluations'] if e['framework'] == 'promptfoo')
        actual = json.loads(contents[evaluation['sha256']])['results']['stats']
        assert actual['successes'] >= 3 and actual['failures'] == 0 and actual['errors'] == 0
        source = next(file for file in verified_files if file['name'] == 'test_demo.py')
        assert any(write['sha256'] == source['sha256'] and Path(write['path']).name == 'test_demo.py' for write in source_writes)
        def command_argv(command):
            argv = shlex.split(command)
            if argv[:3] == ['cd', '/workspace/issues/' + task['id'], '&&']:
                argv = argv[3:]
            return argv
        commands = [command_argv(event['args'].get('command', '')) for event in proof['tool_calls']
            if event['tool'] == 'terminal' and event['success'] and 'Ran 2 tests' in event['result'].get('output', '')]
        assert any(len(argv) == 2 and Path(argv[0]).name in ('python', 'python3') and
            Path(argv[1]).name == 'test_demo.py' for argv in commands)
        assert any(event['tool'] == 'terminal' and event['success'] and
            command_argv(event['args'].get('command', '')) == ['python3', '/usr/local/share/jarvis/isolation_checks.py'] and
            'Ran 8 tests' in event['result'].get('output', '') for event in proof['tool_calls'])
        config_file = next(file for file in verified_files if file['name'] == 'promptfoo.json')
        config = json.loads(contents[config_file['sha256']])
        assert isinstance(config, dict) and config['providers'] == ['echo'] and config['prompts']
        assert len(config['tests']) >= 3
        assert all(test.get('assert') and all(a['type'] in ('equals', 'contains') for a in test['assert']) for test in config['tests'])
    evidence = {'status': 'passed', 'checked_at': now(), 'role': args.role, 'task_id': task['id'],
        'identifier': task['identifier'], 'agent_id': agent['id'], 'paperclip_run_id': run['id'],
        'hermes_run_id': run['resultJson']['run_id'], 'proof': proof, 'verified_native_artifacts': verified_files,
        'runtime_trace': trace, 'hud_and_paperclip_same_task': True}
    evidence['verified_policy_probes'] = policy_probes
    evidence['verified_same_issue_source_writes'] = source_writes
    (ROOT / 'docs/evidence' / ('phase12-' + args.role + '-runtime.json')).write_text(json.dumps(evidence, indent=2))
    print(json.dumps({k: v for k, v in evidence.items() if k not in ('proof', 'runtime_trace')}), flush=True)


if __name__ == '__main__':
    main()
