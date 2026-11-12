"""One-time official REST bootstrap; safe to rerun, never prints credentials."""
import json
import os
from pathlib import Path
import secrets
import requests
import time

root = Path(__file__).resolve().parents[1]
env_path = root / 'deploy/.env'
env = dict(line.split('=', 1) for line in env_path.read_text().splitlines() if '=' in line and not line.startswith('#'))
base = os.environ.get('PAPERCLIP_BOOTSTRAP_URL', 'http://localhost:3100')
session = requests.Session()
session.headers['Origin'] = 'http://localhost:3100'
session.headers['Host'] = 'localhost:3100'
for attempt in range(60):
    try:
        if session.get(base + '/api/health', timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(1)
else:
    raise RuntimeError('Paperclip did not become ready within 60 seconds')


def call(method, path, body=None):
    response = session.request(method, base + '/api' + path, json=body, timeout=30)
    if not response.ok:
        raise RuntimeError(f'{method} {path}: {response.status_code} {response.text[:600]}')
    return response.json()


def save_env(name, value):
    if not env.get(name):
        lines = [line for line in env_path.read_text().splitlines() if not line.startswith(name + '=')]
        env_path.write_text('\n'.join(lines + [name + '=' + value]) + '\n')
        env[name] = value


if not env.get('PAPERCLIP_API_KEY'):
    credentials_path = root / '.runtime/operator.json'
    if not credentials_path.exists():
        credentials_path.write_text(json.dumps({'email': 'operator@jarvis.local', 'password': secrets.token_urlsafe(32)}))
        credentials_path.chmod(0o600)
        credentials = json.loads(credentials_path.read_text())
    credentials = json.loads(credentials_path.read_text())
    signed_in = session.post(base + '/api/auth/sign-in/email', json=credentials, timeout=30)
    if not signed_in.ok:
        call('POST', '/auth/sign-up/email', {**credentials, 'name': 'JARVIS Operator'})
    claim = session.post(base + '/api/bootstrap/claim', json={}, timeout=30)
    if claim.status_code not in (200, 409):
        raise RuntimeError('First-admin claim failed: ' + str(claim.status_code))
    key = call('POST', '/board-api-keys', {'name': 'JARVIS backend', 'expiresAt': None})
    save_env('PAPERCLIP_API_KEY', key['token'])

session.headers['Authorization'] = 'Bearer ' + env['PAPERCLIP_API_KEY']
companies = call('GET', '/companies')
company = next((c for c in companies if c['name'] == 'JARVIS'), None)
company = company or call('POST', '/companies', {'name': 'JARVIS', 'description': 'Local JARVIS command center'})
company_id = company['id']
projects = call('GET', f'/companies/{company_id}/projects')
project = next((p for p in projects if p['name'] == 'General Operations'), None)
project = project or call('POST', f'/companies/{company_id}/projects', {'name': 'General Operations', 'status': 'in_progress'})
stored = call('GET', f'/companies/{company_id}/secrets')
secret = next((s for s in stored if s['name'] == 'hermes-api-key'), None)
secret = secret or call('POST', f'/companies/{company_id}/secrets', {'name': 'hermes-api-key', 'value': env['API_SERVER_KEY']})
agents = call('GET', f'/companies/{company_id}/agents')
agent = next((a for a in agents if a['name'] == 'JARVIS-01'), None)
adapter = {'apiBaseUrl': 'https://hermes-tls:8643',
    'apiKey': {'type': 'secret_ref', 'secretId': secret['id'], 'version': 'latest'},
    'paperclipApiUrl': 'http://paperclip:3100', 'sessionKeyStrategy': 'issue',
    'timeoutSec': 900,
    'instructions': 'You are JARVIS-01, a local read-only research and coding assistant. Execute the assigned task using available tools. Always call local_ollama_models for actual installed model information. Give a useful final answer with exact tool-provided names and sizes. Keep the answer concise: one inventory list and two short recommendation paragraphs. Do not invent context windows, benchmarks or capabilities absent from tool data; label recommendations as tentative inferences. No cloud LLMs. Filesystem modifications and external actions require explicit operator permission and are unavailable. Task checkout and final reporting are handled securely by the Hermes lifecycle plugin; do not invent API calls or claim you updated Paperclip yourself.'}
if agent is None:
    agent = call('POST', f'/companies/{company_id}/agents', {'name': 'JARVIS-01', 'role': 'general',
        'title': 'Local read-only assistant', 'adapterType': 'hermes_gateway', 'adapterConfig': adapter,
        'runtimeConfig': {'heartbeat': {'enabled': False, 'wakeOnAssignment': True, 'wakeOnDemand': True, 'maxConcurrentRuns': 1}},
        'permissions': {'canCreateAgents': False, 'canCreateSkills': False}})
else:
    agent = call('PATCH', '/agents/' + agent['id'], {'adapterConfig': adapter})
if agent.get('lifecycleError'):
    call('POST', '/agents/' + agent['id'] + '/lifecycle/retry', {})
if not env.get('HERMES_PAPERCLIP_AGENT_KEY'):
    key = call('POST', '/agents/' + agent['id'] + '/keys', {'name': 'Hermes issue reporting'})
    save_env('HERMES_PAPERCLIP_AGENT_KEY', key['token'])
for name, value in [('PAPERCLIP_URL', 'http://paperclip:3100'), ('PAPERCLIP_COMPANY_ID', company_id),
                    ('PAPERCLIP_PROJECT_ID', project['id']), ('PAPERCLIP_AGENT_ID', agent['id'])]:
    save_env(name, value)
print(json.dumps({'company': company_id, 'project': project['id'], 'agent': agent['id'], 'secrets': 'stored server-side'}))
