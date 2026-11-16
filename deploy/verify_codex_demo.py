#!/usr/bin/env python3
"""Read-only cross-check of the already completed, explicitly authorized demo."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

import staffing


def main():
    root = staffing.ROOT; env = staffing.settings(); board = staffing.Board(env)
    demo = json.loads((root / '.runtime/codex-demo-task.json').read_text())
    issue = board.api('GET', '/issues/' + demo['id'])
    runs = board.api('GET', '/issues/' + issue['id'] + '/runs')
    matches = [r for r in runs if r.get('status') == 'succeeded']
    assert len(matches) == 1, 'One successful native execution is required'
    run_id = matches[0]['runId']
    run = board.api('GET', '/heartbeat-runs/' + run_id)
    assert issue['status'] == 'done' and run['status'] == 'succeeded'
    assert run['agentId'] == env['PAPERCLIP_CEO_AGENT_ID'] and run['issueId'] == issue['id']
    hermes_id = run['resultJson']['run_id']
    command = ('import json,os,urllib.request; '
        'r=urllib.request.Request("http://127.0.0.1:8642/v1/runs/' + hermes_id + '",'
        'headers={"Authorization":"Bearer "+os.environ["API_SERVER_KEY"]}); '
        'd=json.load(urllib.request.urlopen(r,timeout=5)); '
        'print(json.dumps({k:d.get(k) for k in ("run_id","status","usage")}))')
    observed = json.loads(subprocess.check_output(['docker', 'exec', 'jarvis-hermes-ceo',
        '/opt/hermes/.venv/bin/python', '-c', command], text=True))
    assert observed['status'] == 'completed' and observed['run_id'] == hermes_id
    assert observed['usage']['input_tokens'] > 0 and observed['usage']['output_tokens'] > 0
    logs = root / '.runtime/hermes-ceo/logs'

    def rows(name):
        return [r for line in (logs / name).read_text().splitlines() if line.strip()
                and (r := json.loads(line)).get('issue_id') == issue['id'] and r.get('paperclip_run_id') == run_id]

    requests = rows('model-context.jsonl')
    assert requests and all(r['model'] == 'gpt-6.1-sol' and r['provider'] == 'openai-codex'
        and r['endpoint_host'] == 'chatgpt.com' and r['complete_context_present'] for r in requests)
    tools = rows('ceo-tools.jsonl'); inventory = rows('paperclip-tools.jsonl')
    assert any(r['action'] == 'context' for r in tools)
    assert any(r['action'] == 'plan' and r['result'].get('decision') == 'self' for r in tools)
    assert len(inventory) == 1 and inventory[0]['result']['source'] == 'Ollama /api/tags'
    models = inventory[0]['result']['models']
    current = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5))['models']
    assert {m['name']: m['size_bytes'] for m in models} == {m['name']: m['size'] for m in current}
    attachments = board.api('GET', '/issues/' + issue['id'] + '/attachments')
    artifact = next(a for a in attachments if a.get('originalFilename') == 'codex-demo-report.md')
    request = urllib.request.Request('http://127.0.0.1:8765/api/tasks/' + issue['id'] + '/artifacts/' + artifact['id'],
        headers={'X-Jarvis-Token': env['JARVIS_HUD_TOKEN']})
    report = urllib.request.urlopen(request, timeout=10).read()
    assert hashlib.sha256(report).hexdigest() == artifact['sha256']
    assert artifact['createdByAgentId'] == run['agentId']
    text = report.decode()
    assert all(m['name'] in text and str(m['size_bytes']) in text and str(m['size_gib']) in text for m in models)
    company = env['PAPERCLIP_COMPANY_ID']
    roster = board.api('GET', '/companies/' + company + '/agents')
    assert len(roster) == 3 and all(a['status'] == 'paused' for a in roster if a['id'] != run['agentId'])
    issues = board.api('GET', '/companies/' + company + '/issues')
    assert not [i for i in issues if i.get('parentId') == issue['id']]
    held = []
    for iid in ('f79972eb-c989-4845-bafa-7bd4e11a0eef', '48560754-910f-4521-b5c9-ad4078efef24',
                'eeb52003-acef-4a34-98cf-45ffe585919e'):
        assert board.api('GET', '/issues/' + iid + '/tree-holds?status=active&mode=pause')
        held.append(iid)
    timer = subprocess.run(['systemctl', '--user', 'is-active', 'jarvis-employee-runtimes.timer'],
        text=True, capture_output=True)
    assert timer.stdout.strip() == 'inactive'
    before = dict(line.split() for line in (root / '.runtime/codex-demo-before-containers.txt').read_text().splitlines())
    after = dict(line.split() for line in subprocess.check_output(
        ['docker', 'ps', '--format', '{{.Names}} {{.ID}}'], text=True).splitlines())
    changes = [name for name, ident in before.items() if after.get(name) != ident]
    assert set(changes) == {'jarvis-hud', 'jarvis-hermes-ceo'}
    hud = json.loads(subprocess.check_output(['docker', 'inspect', 'jarvis-hud'], text=True))[0]
    # Docker emits nanoseconds; fromisoformat safely accepts them on this host.
    restart = datetime.datetime.fromisoformat(hud['State']['StartedAt'].replace('Z', '+00:00'))
    restarted_after_completion = restart > datetime.datetime.fromisoformat(run['finishedAt'].replace('Z', '+00:00'))
    elapsed = (datetime.datetime.fromisoformat(run['finishedAt'].replace('Z', '+00:00')) -
               datetime.datetime.fromisoformat(run['startedAt'].replace('Z', '+00:00'))).total_seconds()
    result = {'status': 'passed', 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'issue_id': issue['id'], 'identifier': issue['identifier'], 'paperclip_run_id': run_id,
        'hermes_run_id': hermes_id, 'native_status': run['status'], 'hermes_status': observed['status'],
        'elapsed_seconds': elapsed, 'provider': 'openai-codex', 'model': 'gpt-6.1-sol',
        'actual_provider_endpoint_host': 'chatgpt.com', 'provider_requests_observed': len(requests),
        'full_authenticated_context_in_provider_requests': True, 'usage': observed['usage'],
        'actual_tools_verified': ['paperclip_context', 'paperclip_ceo:plan:self', 'local_ollama_models', 'publish_artifact'],
        'models': [{k: m[k] for k in ('name', 'size_bytes', 'size_gib')} for m in models],
        'inventory_matches_live_ollama_api': True, 'report_contains_all_exact_inventory_values': True,
        'artifact': {k: artifact[k] for k in ('id', 'originalFilename', 'sha256', 'createdByAgentId')},
        'new_employees': 0, 'child_tasks': 0, 'workers_paused': True, 'staffing_timer': 'inactive',
        'old_objectives_held': held, 'changed_containers': changes,
        'unrelated_containers_unchanged': len(before) - len(changes),
        'hud_restart_after_completion': restarted_after_completion,
        'report_read_after_restart': restarted_after_completion,
        'cloud_cost': 'Unpriced: Paperclip gateway accounting reports an unknown model; actual provider/model verified from Hermes request observer.',
        'scope': 'Separate authorized Codex demo; not Phase 14 acceptance or a local model performance benchmark'}
    (root / 'docs/evidence/codex-demo-execution.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
