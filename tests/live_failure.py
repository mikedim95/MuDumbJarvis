"""Opt-in negative test: one issue-scoped timeout; agent defaults remain intact."""
import json
import os
from pathlib import Path
import time
import requests

p = os.environ.get('PAPERCLIP_URL', 'http://paperclip:3100') + '/api'
j = os.environ.get('JARVIS_TEST_URL', 'http://jarvis:8765') + '/api'
board = {'Authorization': 'Bearer ' + os.environ['PAPERCLIP_API_KEY']}
hud = {'X-Jarvis-Token': os.environ['JARVIS_HUD_TOKEN']}
response = requests.post(p + '/companies/' + os.environ['PAPERCLIP_COMPANY_ID'] + '/issues',
    headers=board, json={'title': 'Verification: expected one-second execution timeout',
        'description': 'Use local_ollama_models to list actual installed Ollama models.',
        'status': 'todo', 'priority': 'low', 'projectId': os.environ['PAPERCLIP_PROJECT_ID'],
        'assigneeAgentId': os.environ['PAPERCLIP_AGENT_ID'],
        'assigneeAdapterOverrides': {'adapterConfig': {'timeoutSec': 1}},
        'idempotencyKey': 'jarvis-expected-timeout-v1', 'allowDuplicate': True}, timeout=30)
response.raise_for_status()
task = response.json()
print('Expected-failure task:', task['identifier'], task['id'], flush=True)
for attempt in range(360):
    response = requests.get(j + '/tasks/' + task['id'], headers=hud, timeout=30)
    response.raise_for_status()
    task = response.json()
    failures = [r for r in task['runs'] if r['status'] in ('failed', 'timed_out', 'cancelled')]
    if failures and task['status'] == 'blocked':
        break
    time.sleep(3)
out = Path(__file__).resolve().parents[1] / 'docs/evidence/phase4-failure.json'
out.write_text(json.dumps(task, indent=2))
print('Failure state:', task['status'], [(r['status'], r['errorCode']) for r in task['runs']], flush=True)
assert failures and task['status'] == 'blocked'
assert any(r.get('error') or r.get('errorCode') for r in failures)
# A timeout may happen before Hermes creates a turn, so the authoritative run
# error is sufficient even when no runtime comment could be written.
agent_url = p + '/agents/' + os.environ['PAPERCLIP_AGENT_ID']
agent_response = requests.get(agent_url, headers=board, timeout=20)
agent_response.raise_for_status()
if agent_response.json()['status'] == 'error':
    restored = requests.post(agent_url + '/clear-error', headers=board, json={}, timeout=20)
    restored.raise_for_status()
    print('Cleared the intentional agent error; failed issue/run history is retained.', flush=True)
