"""Versioned capability templates, never an employee roster or task store."""
import hashlib
import json
from pathlib import Path


HIRE_PORTRAITS = tuple(json.loads(Path(__file__).with_name('portraits.json').read_text())['hires'])


def hire_portrait(seed, choice=None, roster=()):
    if choice is not None:
        if choice not in HIRE_PORTRAITS:
            raise ValueError('Choose a portrait from the hiring catalog')
        return choice
    used = [((a.get('metadata') or {}).get('jarvis') or {}).get('portrait_id')
            for a in roster if a.get('status') != 'terminated']
    offset = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], 'big') % len(HIRE_PORTRAITS)
    order = HIRE_PORTRAITS[offset:] + HIRE_PORTRAITS[:offset]
    return min(order, key=used.count)


def catalog():
    data = json.loads(Path(__file__).with_name('profiles.json').read_text())
    if data['version'] != 1 or data['inference_slots'] != 1:
        raise ValueError('Unsupported capability policy')
    return data


def profile(name):
    data = catalog()
    if name not in data['profiles']:
        raise ValueError('Select a registered capability profile')
    item = {**data['profiles'][name], 'id': name, 'version': data['version'], 'model': data['model']}
    item['sha256'] = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return item


def employee_profile(agent):
    return ((agent.get('metadata') or {}).get('jarvis') or {}).get('profile')


def ready_employee(agent):
    managed = (agent.get('metadata') or {}).get('jarvis') or {}
    return (agent.get('status') not in ('terminated', 'pending_approval', 'paused')
            and agent.get('lifecycleState') == 'ready'
            and (not managed.get('managed') or managed.get('provisioned') is True))


def hire_body(turn, ceo, profile_id, name, reason, portrait=None, roster=()):
    item = profile(profile_id)
    runtime = hashlib.sha256((turn['company'] + ':' + turn['issue'] + ':' + profile_id).encode()).hexdigest()[:24]
    body = {'name': name[:80], 'role': item['role'], 'title': item['name'], 'reportsTo': ceo['id'],
        'capabilities': ', '.join(item['capabilities']) + '. ' + item['authority'],
        'adapterType': 'hermes_gateway', 'adapterConfig': {},
        'permissions': {'canCreateAgents': False, 'canCreateSkills': False},
        'runtimeConfig': {'heartbeat': {'enabled': False, 'wakeOnAssignment': True,
            'wakeOnDemand': True, 'maxConcurrentRuns': 1}},
        'metadata': {'jarvis': {'managed': True, 'provisioned': False, 'profile': profile_id,
            'portrait_id': hire_portrait(runtime, portrait, roster),
            'profile_sha256': item['sha256'], 'runtime_id': runtime, 'source_issue_id': turn['issue'],
            'hiring_reason': reason[:2000], 'limits': item['limits'], 'model': item['model'],
            'workspace': 'private employee container; issue-scoped directories; no host access'}},
        'sourceIssueId': turn['issue']}
    if turn.get('inference_configuration') and turn['inference_configuration'].get('version') != 3:
        body['metadata']['jarvis']['inference_configuration'] = turn['inference_configuration']
    return body
