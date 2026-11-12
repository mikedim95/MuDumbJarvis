"""Snapshot completed tasks, then verify after an externally performed restart.

Run with --save before restart; rerun without it afterward. Test artifacts only,
not product storage. No task creation, agent execution, or scheduling.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import requests

root = Path(__file__).resolve().parents[1]
snapshot = root / 'docs/evidence/restart-history.json'
ids = ['886fde66-3bb3-4f9e-8ec8-cd65cd757d58', '8ea14a70-8f37-4c8b-81f4-7636aecd9706',
       'ccd51df4-2119-45cf-a889-41e6ff2f9db2']
base = os.environ.get('JARVIS_TEST_URL', 'http://jarvis:8765') + '/api'
headers = {'X-Jarvis-Token': os.environ['JARVIS_HUD_TOKEN']}
for attempt in range(60):
    try:
        response = requests.get(base + '/tasks', headers=headers, timeout=5)
        if response.ok:
            break
    except requests.RequestException:
        pass
    time.sleep(1)
else:
    raise RuntimeError('Task history was unavailable after restart')
history = response.json()['tasks']
observed = {}
for task_id in ids:
    assert any(t['id'] == task_id for t in history)
    response = requests.get(base + '/tasks/' + task_id, headers=headers, timeout=20)
    response.raise_for_status()
    task = response.json()
    assert task['status'] == 'done' and task['comments']
    observed[task_id] = {'identifier': task['identifier'], 'status': task['status'],
        'comments_sha256': hashlib.sha256(json.dumps(task['comments'], sort_keys=True).encode()).hexdigest(),
        'runs': [(run['runId'], run['status']) for run in task['runs']]}
if '--save' in sys.argv:
    snapshot.write_text(json.dumps({'before': observed}, indent=2))
    print('Saved completed-task history and result hashes before restart.')
else:
    evidence = json.loads(snapshot.read_text())
    # JSON serializes tuples as arrays.
    normalized = json.loads(json.dumps(observed))
    assert evidence['before'] == normalized, 'History/result changed across restart'
    evidence.update(after=observed, verified=True)
    snapshot.write_text(json.dumps(evidence, indent=2))
    print('PASS: identical task IDs, statuses, result comments and runs survived restart.')
