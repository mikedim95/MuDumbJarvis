#!/usr/bin/env python3
"""Read-only cross-check of the @ceo HUD receipt, native execution and tools."""
import datetime
import hashlib
import json
import re
import subprocess
import urllib.request

import staffing


def utc(value):
    return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))


def main():
    root = staffing.ROOT; env = staffing.settings(); board = staffing.Board(env)
    receipt = json.loads((root / '.runtime/minimal-ceo-task.json').read_text())
    task = board.api('GET', '/issues/' + receipt['id'])
    runs = board.api('GET', '/issues/' + task['id'] + '/runs')
    assert task['status'] == 'done' and task['parentId'] is None
    assert len(runs) == 1 and runs[0]['status'] == 'succeeded'
    run = board.api('GET', '/heartbeat-runs/' + runs[0]['runId'])
    assert run['issueId'] == task['id'] and run['agentId'] == env['PAPERCLIP_CEO_AGENT_ID']
    hermes_id = run['resultJson']['run_id']; assert re.fullmatch(r'run_[a-f0-9]+', hermes_id)
    code = ('import json,os,urllib.request; '
        'r=urllib.request.Request("http://127.0.0.1:8642/v1/runs/' + hermes_id + '",'
        'headers={"Authorization":"Bearer "+os.environ["API_SERVER_KEY"]}); '
        'd=json.load(urllib.request.urlopen(r,timeout=5)); '
        'print(json.dumps({k:d.get(k) for k in ("run_id","status","usage")}))')
    observed = json.loads(subprocess.check_output(['docker', 'exec', 'jarvis-hermes-ceo',
        '/opt/hermes/.venv/bin/python', '-c', code], text=True))
    assert observed['status'] == 'completed' and observed['usage']['output_tokens'] > 0

    def hud(path):
        request = urllib.request.Request('http://127.0.0.1:8765/api/' + path,
            headers={'X-Jarvis-Token': env['JARVIS_HUD_TOKEN']})
        return urllib.request.urlopen(request, timeout=25).read()

    detail = json.loads(hud('tasks/' + task['id']))
    assert not detail['children']
    snapshot = json.loads(hud('tasks/' + task['id'] + '/events'))
    tool = next(e for e in snapshot['events'] if e['provenance'] == 'verified_tool_output'
        and e['data'].get('tool') == 'local_ollama_models'
        and e['source_ref'].get('run_id') == run['id']
        and e['source_ref'].get('agent_id') == run['agentId'])
    assert tool['data']['success'] is True and utc(tool['occurred_at']) < utc(run['finishedAt'])
    models = tool['data']['result']
    current = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5))['models']
    assert {m['name']: m['size_bytes'] for m in models} == {m['name']: m['size'] for m in current}
    old_models = json.loads((root / '.runtime/csi-before-models.json').read_text())['models']
    assert {m['name']: m['digest'] for m in old_models} == {m['name']: m['digest'] for m in current}
    artifact = next(a for a in snapshot['artifacts'] if a['originalFilename'] == 'minimal-ceo-inventory.md')
    data = hud('tasks/' + task['id'] + '/artifacts/' + artifact['id'])
    assert hashlib.sha256(data).hexdigest() == artifact['sha256']
    assert all(m['name'] in data.decode() and str(m['size_bytes']) in data.decode() for m in models)
    requests = [r for line in (root / '.runtime/hermes-ceo/logs/model-context.jsonl').read_text().splitlines()
        if line.strip() and (r := json.loads(line)).get('issue_id') == task['id']
        and r.get('paperclip_run_id') == run['id']]
    assert requests and all(r['provider'] == 'openai-codex' and r['model'] == 'gpt-6.1-sol'
        and r['endpoint_host'] == 'chatgpt.com' and r['complete_context_present'] for r in requests)
    roster = board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/agents')
    assert len(roster) == 3 and all(a['status'] == 'paused' for a in roster if a['id'] != run['agentId'])
    assert not board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/live-runs')
    assert subprocess.run(['systemctl', '--user', 'is-active', 'jarvis-employee-runtimes.timer'],
        text=True, capture_output=True).stdout.strip() == 'inactive'
    for iid in ('f79972eb-c989-4845-bafa-7bd4e11a0eef', '48560754-910f-4521-b5c9-ad4078efef24',
                'eeb52003-acef-4a34-98cf-45ffe585919e'):
        assert board.api('GET', '/issues/' + iid + '/tree-holds?status=active&mode=pause')
    hud_state = json.loads(subprocess.check_output(['docker', 'inspect', 'jarvis-hud'], text=True))[0]['State']
    result = {'status': 'passed', 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'identifier': task['identifier'], 'task_id': task['id'], 'paperclip_run_id': run['id'],
        'hermes_run_id': hermes_id, 'native_status': run['status'], 'hermes_status': observed['status'],
        'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'provider_requests': len(requests),
        'elapsed_seconds': (utc(run['finishedAt']) - utc(run['startedAt'])).total_seconds(),
        'verified_tool_event_id': tool['id'], 'inventory_published_before_completion': True,
        'models_match_live_api': True, 'model_count': len(models), 'artifact_sha256': artifact['sha256'],
        'new_employees': 0, 'child_tasks': 0, 'paused_workers_preserved': True,
        'old_objectives_held': True, 'staffing_timer': 'inactive', 'original_model_digests_preserved': True,
        'read_after_hud_restart': utc(hud_state['StartedAt']) > utc(run['finishedAt']),
        'scope': 'Real minimal-UI CEO interaction; read-only demo, not resumed Phase 14 delegation.'}
    (root / 'docs/evidence/minimal-ceo-execution.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
