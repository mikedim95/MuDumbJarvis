"""Idempotent operator setup of the initial CEO, not an agent hiring bypass."""
import json
import os
from pathlib import Path
import requests
import time

root = Path(__file__).resolve().parents[1]
path = root / 'deploy/.env'
env = dict(l.split('=', 1) for l in path.read_text().splitlines() if '=' in l and not l.startswith('#'))
base = os.environ.get('PAPERCLIP_BOOTSTRAP_URL', 'http://localhost:3100') + '/api'
session = requests.Session()
session.headers.update({'Authorization': 'Bearer ' + env['PAPERCLIP_API_KEY'],
                        'Origin': 'http://localhost:3100', 'Host': 'localhost:3100'})


def call(method, route, body=None):
    response = session.request(method, base + route, json=body, timeout=30)
    if not response.ok:
        raise RuntimeError(f'CEO setup {method} {route}: HTTP {response.status_code}')
    return response.json()


def save(name, value):
    if env.get(name) and env[name] != value:
        raise RuntimeError('Existing identity/config differs: ' + name)
    if not env.get(name):
        lines = [l for l in path.read_text().splitlines() if not l.startswith(name + '=')]
        path.write_text('\n'.join(lines + [name + '=' + value]) + '\n')
        path.chmod(0o600)
        env[name] = value


for attempt in range(90):
    try:
        if session.get(base + '/health', timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(1)
else:
    raise RuntimeError('Paperclip did not become ready for CEO setup')

company = env['PAPERCLIP_COMPANY_ID']
agents = call('GET', '/companies/' + company + '/agents')
ceos = [a for a in agents if a.get('role') == 'ceo' and a.get('status') != 'terminated']
if len(ceos) > 1:
    raise RuntimeError('Multiple CEOs exist; refusing to create or choose another')
ceo = ceos[0] if ceos else None
stored = call('GET', '/companies/' + company + '/secrets')
secret = next((s for s in stored if s['name'] == 'hermes-ceo-api-key'), None)
secret = secret or call('POST', '/companies/' + company + '/secrets',
                       {'name': 'hermes-ceo-api-key', 'value': env['API_SERVER_CEO_KEY']})
adapter = {'apiBaseUrl': 'https://hermes-tls:8644',
           'apiKey': {'type': 'secret_ref', 'secretId': secret['id'], 'version': 'latest'},
           'paperclipApiUrl': 'http://paperclip:3100', 'sessionKeyStrategy': 'issue',
           'timeoutSec': 1800, 'instructions': (root / 'deploy/CEO_POLICY.md').read_text(),
           'payloadTemplate': {'input': 'Execute the current CEO objective supplied by the authenticated Paperclip preflight. Plan and delegate through native tools, review verified results, and return the consolidated report or real blockers.', 'conversation_history': [
               {'role': 'user', 'content': 'Where is authoritative task context?'},
               {'role': 'assistant', 'content': 'Paperclip. I will use the current authenticated objective and verified results supplied for this turn.'}]}}
if ceo is None:
    # Phase 5's company has no CEO and no hiring gate. Never turn an existing gate off.
    company_state = call('GET', '/companies/' + company)
    if company_state.get('requireBoardApprovalForNewAgents'):
        raise RuntimeError('Initial CEO needs operator creation/approval; existing hiring gate remains enabled')
    ceo = call('POST', '/companies/' + company + '/agents',
               {'name': 'JARVIS-CEO', 'role': 'ceo', 'title': 'Executive planner and evidence reviewer',
                'adapterType': 'hermes_gateway', 'adapterConfig': adapter,
                'runtimeConfig': {'heartbeat': {'enabled': False, 'wakeOnAssignment': True,
                    'wakeOnDemand': True, 'maxConcurrentRuns': 1}},
                'permissions': {'canCreateAgents': True, 'canCreateSkills': False},
                'capabilities': 'Plan objectives, select the minimum team, delegate persistent Paperclip children, '
                                'review verified results. Essential hires require human approval.'})
else:
    ceo = call('PATCH', '/agents/' + ceo['id'], {'adapterConfig': adapter})
if ceo.get('permissions', {}).get('canCreateAgents') is not True or ceo.get('permissions', {}).get('canCreateSkills') is not False:
    ceo = call('PATCH', '/agents/' + ceo['id'] + '/permissions',
               {'canCreateAgents': True, 'canCreateSkills': False})
call('PATCH', '/companies/' + company, {'requireBoardApprovalForNewAgents': True})
worker = call('GET', '/agents/' + env['PAPERCLIP_AGENT_ID'])
worker_patch = {'reportsTo': ceo['id']}
if not ((worker.get('metadata') or {}).get('jarvis') or {}).get('managed'):
    worker_patch['capabilities'] = ('Local technical inventory operator. Retrieve actual installed Ollama models, names, '
        'byte sizes and architecture details using the read-only local_ollama_models tool. '
        'No filesystem changes, external actions or hiring.')
call('PATCH', '/agents/' + env['PAPERCLIP_AGENT_ID'], worker_patch)
save('PAPERCLIP_CEO_AGENT_ID', ceo['id'])
if not env.get('HERMES_PAPERCLIP_CEO_KEY'):
    key = call('POST', '/agents/' + ceo['id'] + '/keys', {'name': 'Isolated Hermes CEO callbacks'})
    save('HERMES_PAPERCLIP_CEO_KEY', key['token'])
print(json.dumps({'ceo_id': ceo['id'], 'worker_id': env['PAPERCLIP_AGENT_ID'],
                  'hiring_requires_human_approval': True, 'credentials': 'server-side only'}))
