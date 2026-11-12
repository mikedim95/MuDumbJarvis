"""Opt-in actual JARVIS→Paperclip→Hermes→Ollama API smoke test (not browser proof)."""
import json
import os
from pathlib import Path
import time
from uuid import NAMESPACE_URL, uuid5

import requests

base = os.environ.get('JARVIS_TEST_URL', 'http://jarvis:8765')
headers = {'X-Jarvis-Token': os.environ['JARVIS_HUD_TOKEN']}
prompt = 'Use the available local tools to list my installed Ollama models, identify their names and sizes, and recommend which are suitable for research and coding.'
trial = os.environ.get('JARVIS_TRIAL', 'v2')
body = {'input': prompt, 'request_id': str(uuid5(NAMESPACE_URL, 'jarvis-phase4-api-acceptance-' + trial))}


def call(method, path, data=None):
    r = requests.request(method, base + '/api/' + path, json=data, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


task = call('POST', 'tasks', body)
replay = call('POST', 'tasks', body)
assert task['id'] == replay['id'], 'Retry created a duplicate task'
print('JARVIS accepted:', task['identifier'], task['id'], 'retry returned same ID', flush=True)
last = None
for attempt in range(330):
    task = call('GET', 'tasks/' + task['id'])
    if task['status'] != last:
        print('Actual Paperclip status:', task['status'], flush=True)
        last = task['status']
    if task['status'] in ('done', 'blocked', 'cancelled'):
        break
    time.sleep(3)
out = Path(__file__).resolve().parents[1] / ('docs/evidence/phase4-api-' + trial + '.json')
out.write_text(json.dumps(task, indent=2))
assert task['status'] == 'done', task
assert task['comments'] and 'GiB' in task['comments'][-1]['body']
history = call('GET', 'tasks')['tasks']
assert any(t['id'] == task['id'] for t in history)
print('Actual execution finished and history/result persisted.', flush=True)
