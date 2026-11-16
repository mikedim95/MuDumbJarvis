#!/usr/bin/env python3
"""Read-only correlation of CSI demo UI, native execution and real tool data."""
import datetime
import hashlib
import itertools
import json
import re
import subprocess
import urllib.request

import staffing


def utc(value):
    return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))


def main():
    root = staffing.ROOT; env = staffing.settings(); board = staffing.Board(env)
    receipt = json.loads((root / '.runtime/csi-demo-task.json').read_text())
    task = board.api('GET', '/issues/' + receipt['id'])
    runs = board.api('GET', '/issues/' + task['id'] + '/runs')
    assert task['status'] == 'done' and len(runs) == 1 and runs[0]['status'] == 'succeeded'
    run = board.api('GET', '/heartbeat-runs/' + runs[0]['runId'])
    assert run['issueId'] == task['id'] and run['agentId'] == env['PAPERCLIP_CEO_AGENT_ID']
    hermes_id = run['resultJson']['run_id']; assert re.fullmatch(r'run_[a-f0-9]+', hermes_id)
    command = ('import json,os,urllib.request; '
        'r=urllib.request.Request("http://127.0.0.1:8642/v1/runs/' + hermes_id + '",'
        'headers={"Authorization":"Bearer "+os.environ["API_SERVER_KEY"]}); '
        'd=json.load(urllib.request.urlopen(r,timeout=5)); '
        'print(json.dumps({k:d.get(k) for k in ("run_id","status","usage")}))')
    observed = json.loads(subprocess.check_output(['docker', 'exec', 'jarvis-hermes-ceo',
        '/opt/hermes/.venv/bin/python', '-c', command], text=True))
    assert observed['status'] == 'completed' and observed['usage']['output_tokens'] > 0

    def hud(path):
        request = urllib.request.Request('http://127.0.0.1:8765/api/' + path,
            headers={'X-Jarvis-Token': env['JARVIS_HUD_TOKEN']})
        return urllib.request.urlopen(request, timeout=25).read()

    snapshot = json.loads(hud('tasks/' + task['id'] + '/events'))
    tool_events = [e for e in snapshot['events'] if e['provenance'] == 'verified_tool_output' and
        e['data'].get('tool') == 'local_ollama_models' and e['source_ref'].get('run_id') == run['id']]
    assert len(tool_events) == 1 and tool_events[0]['data']['success'] is True
    tool_event = tool_events[0]; models = tool_event['data']['result']
    assert utc(tool_event['occurred_at']) < utc(run['finishedAt']), 'Observed tool result must precede completion'
    actual = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5))['models']
    assert {m['name']: m['size_bytes'] for m in models} == {m['name']: m['size'] for m in actual}
    artifact = next(a for a in snapshot['artifacts'] if a['originalFilename'] == 'csi-demo-inventory.md')
    data = hud('tasks/' + task['id'] + '/artifacts/' + artifact['id'])
    assert hashlib.sha256(data).hexdigest() == artifact['sha256']
    assert all(m['name'] in data.decode() and str(m['size_bytes']) in data.decode() for m in models)
    assert any(e['type'] == 'evidence.file_recovered' and e['source_ref'].get('artifact_id') == artifact['id'] for e in snapshot['events'])
    assert any(n['id'] == 'artifact:' + artifact['id'] for n in snapshot['graph']['nodes'])
    rows = [json.loads(line) for line in (root / '.runtime/hermes-ceo/logs/model-context.jsonl').read_text().splitlines() if line.strip()]
    requests = [r for r in rows if r.get('issue_id') == task['id'] and r.get('paperclip_run_id') == run['id']]
    assert requests and all(r['provider'] == 'openai-codex' and r['model'] == 'gpt-6.1-sol' and
        r['endpoint_host'] == 'chatgpt.com' and r['complete_context_present'] for r in requests)
    before = json.loads((root / '.runtime/csi-before-services.json').read_text())
    changed, restarted, same, reordered_mounts = [], [], [], []
    for name, prior in before.items():
        current = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]
        cfg = {'config': current['Config'], 'mounts': current['Mounts'], 'host': current['HostConfig'],
               'networks': sorted(current['NetworkSettings']['Networks'])}
        digest = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        same_config = digest == prior['configuration_sha256']
        # Docker's Mounts list can arrive in a different map-iteration order.
        # Recover the original order against the recorded SHA; do not waive
        # differences in any config, mount value, host setting or network.
        if not same_config and current['Id'] == prior['id'] and len(current['Mounts']) <= 8:
            for order in itertools.permutations(current['Mounts']):
                if hashlib.sha256(json.dumps({**cfg, 'mounts': order}, sort_keys=True).encode()).hexdigest() == prior['configuration_sha256']:
                    same_config = True; reordered_mounts.append(name); break
        if current['Id'] != prior['id'] or not same_config:
            changed.append(name)
        elif current['State']['StartedAt'] != prior['started_at']:
            restarted.append(name)
        else:
            same.append(name)
    # Other projects can deploy concurrently on this shared host. Enforce the
    # required untouched JARVIS/model/AIGoat/PentAGI boundary and report unrelated
    # observed changes separately instead of attributing them to this feature.
    # This separate project's app was independently recreated during the audit.
    # All other initial services, including PentAGI's database/exporter/scraper,
    # remain inside the strict preservation check.
    protected = set(before) - {'nine-labs-app-1'}
    assert set(changed) & protected == {'jarvis-hud'}
    assert set(restarted) & protected == {'jarvis-hermes-ceo'}
    unrelated_changes = [name for name in changed + restarted if name not in protected]
    old_models = json.loads((root / '.runtime/csi-before-models.json').read_text())['models']
    assert {m['name']: m['digest'] for m in old_models} == {m['name']: m['digest'] for m in actual}
    roster = board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/agents')
    assert len(roster) == 3 and all(a['status'] == 'paused' for a in roster if a['id'] != run['agentId'])
    assert not board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/live-runs')
    timer = subprocess.run(['systemctl', '--user', 'is-active', 'jarvis-employee-runtimes.timer'], text=True, capture_output=True)
    assert timer.stdout.strip() == 'inactive'
    hud_state = json.loads(subprocess.check_output(['docker', 'inspect', 'jarvis-hud'], text=True))[0]['State']
    after_restart = utc(hud_state['StartedAt']) > utc(run['finishedAt'])
    for iid in ('f79972eb-c989-4845-bafa-7bd4e11a0eef','48560754-910f-4521-b5c9-ad4078efef24','eeb52003-acef-4a34-98cf-45ffe585919e'):
        assert board.api('GET', '/issues/' + iid + '/tree-holds?status=active&mode=pause')
    result = {'status': 'passed', 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'identifier': task['identifier'], 'task_id': task['id'], 'paperclip_run_id': run['id'],
        'hermes_run_id': hermes_id, 'native_status': run['status'], 'hermes_status': observed['status'],
        'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'provider_requests': len(requests),
        'elapsed_seconds': (utc(run['finishedAt']) - utc(run['startedAt'])).total_seconds(),
        'usage': observed['usage'], 'verified_tool_event_id': tool_event['id'],
        'native_tool_comment_id': tool_event['source_ref']['comment_id'],
        'verified_inventory_published_before_completion': True, 'models_match_live_api': True,
        'model_count': len(models), 'artifact': artifact,
        'recorded_event_types': sorted({e['type'] for e in snapshot['events']}),
        'new_employees': 0, 'paused_workers_preserved': True, 'old_objectives_held': True,
        'staffing_timer': 'inactive', 'case_and_evidence_available_after_hud_restart': after_restart,
        'changed_services': changed, 'restarted_services': restarted,
        'untouched_services': same, 'original_models_and_digests_preserved': True,
        'unrelated_service_changes_observed': unrelated_changes,
        'docker_mount_order_only': reordered_mounts,
        'limits': 'No synthetic identity match, geographic trace or decryption finding. Separate authorized demo; unfinished Phase 14 remains paused.'}
    (root / 'docs/evidence/csi-execution.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
