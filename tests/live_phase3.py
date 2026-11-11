"""Opt-in live acceptance test; creates one idempotent, read-only Paperclip issue."""
import json
import os
from pathlib import Path
import time
import requests

base = os.environ.get('PAPERCLIP_URL', 'http://paperclip:3100') + '/api'
s = requests.Session()
s.headers['Authorization'] = 'Bearer ' + os.environ['PAPERCLIP_API_KEY']
for attempt in range(60):
    try:
        if s.get(base + '/health', timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(1)
else:
    raise RuntimeError('Paperclip was not ready within 60 seconds')


def call(method, path, body=None):
    r = s.request(method, base + path, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


agent = call('GET', '/agents/' + os.environ['PAPERCLIP_AGENT_ID'])
print('Agent lifecycle:', agent['lifecycleState'], flush=True)
assert agent['lifecycleState'] == 'ready', agent.get('lifecycleError')
task = call('POST', '/companies/' + os.environ['PAPERCLIP_COMPANY_ID'] + '/issues', {
    'title': 'Phase 3: inspect actual local Ollama inventory',
    'description': 'Use local_ollama_models to retrieve the installed Ollama models. Report the first two model names and their sizes in GiB. Do not guess.',
    'status': 'todo', 'priority': 'medium',
    'assigneeAgentId': agent['id'], 'projectId': os.environ['PAPERCLIP_PROJECT_ID'],
    'idempotencyKey': 'jarvis-phase3-local-inventory-v1'})
print('Created persistent task:', task['id'], task['identifier'], flush=True)
last = None
for attempt in range(300):
    task = call('GET', '/issues/' + task['id'])
    if task['status'] != last:
        print('Task state:', task['status'], 'execution:', task.get('executionRunId'), flush=True)
        last = task['status']
    if task['status'] in ('done', 'blocked', 'cancelled'):
        break
    time.sleep(3)
comments = call('GET', '/issues/' + task['id'] + '/comments')
evidence = {'task': task, 'comments': comments, 'runs': call('GET', '/issues/' + task['id'] + '/runs')}
out = Path(__file__).resolve().parents[1] / 'docs/evidence/phase3-task.json'
out.write_text(json.dumps(evidence, indent=2))
print('Final status:', task['status'], 'comments:', len(comments), flush=True)
assert task['status'] == 'done', task['status']
assert comments and any('GiB' in c.get('body', '') for c in comments)
