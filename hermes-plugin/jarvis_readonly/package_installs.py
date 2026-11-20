"""Exact, human-approved Debian utilities for one native employee assignment."""
import json
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

KIND = 'jarvis_package_install'
MANIFEST = 'package-request.json'
DEVELOPMENT = json.loads(Path(__file__).with_name('development_packages.json').read_text())
# Historical assignment approvals use this three-package contract.
CATALOG = {name: (spec['version'], *spec['archives'][0], spec['sha256'])
           for name, spec in DEVELOPMENT.items() if name in ('tree', 'gojq', 'shfmt')}


def payload(name, company, project, issue, agent):
    if not isinstance(name, str) or name not in CATALOG:
        raise ValueError('Supported sandbox packages: ' + ', '.join(CATALOG))
    version, _, _, digest = CATALOG[name]
    for value in (company, project, issue, agent):
        if str(UUID(value)) != value:
            raise ValueError('A native project, issue and employee are required')
    return {'kind': KIND, 'package': name, 'version': version, 'sha256': digest,
            'company': company, 'project': project, 'issue_id': issue, 'agent': agent,
            'name': f'Install {name} {version}', 'proposal': f'Install {name} {version} into the requesting agent’s workspace for this assignment.',
            'scope': f'One assignment: {issue}. Requesting employee: {agent}.',
            'execution': f'After owner approval the runtime installs and verifies ./.jarvis-bin/{name}.'}


def matches(row, expected):
    return (row.get('companyId') == expected['company'] and row.get('type') == 'request_board_approval'
            and row.get('requestedByAgentId') == expected['agent'] and row.get('payload') == expected)


def receipt_key(approval_id):
    return 'jarvis-install-' + str(UUID(approval_id))


def receipt(doc, approval):
    if not doc:
        return None
    expected = approval['payload']
    if not isinstance(expected.get('package'), str) or expected['package'] not in CATALOG:
        return None
    if (doc.get('key') != receipt_key(approval['id']) or doc.get('companyId') != expected['company']
            or doc.get('issueId') != expected['issue_id'] or not doc.get('updatedByUserId')
            or doc.get('updatedByAgentId')):
        return None
    try:
        body = json.loads(doc['body'])
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(body, dict) or body.get('approval_id') != approval['id'] or body.get('request') != expected:
        return None
    status = body.get('status')
    if status == 'installed':
        return {'status': status, 'command': './.jarvis-bin/' + expected['package'], 'sha256': expected['sha256']}
    if status == 'retrying':
        return {'status': status, 'detail': 'Provisioning failed. The runtime will retry.'}
    return None


def assignment_review(name, turn, issue, api):
    """Preserve a pending decision or a denial for this particular assignment."""
    if name in CATALOG:
        expected = payload(name, turn['company'], turn['project'], issue['id'], turn['agent'])
        rows = api('GET', '/issues/' + issue['id'] + '/approvals')
        for row in rows:
            if matches(row, expected) and row.get('status') in ('pending','revision_requested','rejected'):
                return {'status':row['status'], 'decision':row['status'], 'approval_id':row['id'], 'package':name}
    elif issue.get('parentId'):
        from . import blocker_review
        parent = issue['parentId']
        for row in api('GET', '/issues/' + parent + '/interactions'):
            choice = blocker_review.package_decision(row, parent, turn['reports_to'])
            if (choice and choice['child_id'] == issue['id'] and choice['agent_id'] == turn['agent']
                    and choice['package'] == name and (choice['answer'] == 'rejected' or choice['status'] == 'pending')):
                return {'status':choice['status'], 'decision':choice['answer'], 'request_id':choice['id'], 'package':name}


def request(name, turn, issue, api):
    import os
    from . import profile_registry
    if not os.environ.get('JARVIS_PROFILE'):
        raise PermissionError('A sandbox employee must request installation from its assignment')
    profile = profile_registry.profile(os.environ['JARVIS_PROFILE'])
    if not profile['sandbox'] or 'terminal' not in profile['tools'] or turn.get('task_kind') == 'acknowledgement':
        raise PermissionError('Package requests require a sandbox assignment with terminal access')
    if not isinstance(name, str):
        raise ValueError('Use one package name.')
    name = name.lower()
    if name in DEVELOPMENT and (turn.get('work_scope') or {}).get('mission_id'):
        from . import project_packages
        policy = project_packages.for_assignment(turn, issue, api, refresh=True)
        if policy and name in policy['approved']:
            review = assignment_review(name, turn, issue, api)
            if review:
                return review
            try:
                return project_packages.install(turn, name, policy)
            except FileNotFoundError:
                return {'status':'preparing','package':name,'mission_id':policy['mission_id'],
                        'next':'The project has approved this tool. The package service is preparing its verified payload.'}
    if name not in CATALOG:
        from . import apt_receipts, blocker_review
        blocker_review.package_name(name)
        if not issue.get('parentId') or not turn.get('reports_to'):
            raise ValueError('A package review needs a CEO-owned parent assignment.')
        parent = api('GET', '/issues/' + issue['parentId'])
        if (parent.get('assigneeAgentId') != turn['reports_to'] or parent.get('companyId') != turn['company']
                or parent.get('projectId') != turn['project'] or parent.get('parentId') or parent.get('hiddenAt')
                or parent.get('status') in ('done', 'cancelled')):
            raise PermissionError('The parent assignment does not belong to this employee’s manager.')
        for doc in api('GET', '/issues/' + issue['id'] + '/documents'):
            if not (doc.get('key') or '').startswith('jarvis-apt-'):
                continue
            try:
                rid = str(UUID(doc['key'][len('jarvis-apt-'):]))
            except ValueError:
                continue
            expected_scope = apt_receipts.binding(turn['company'], turn['project'], parent['id'],
                                                 issue['id'], turn['agent'], name, rid)
            saved = apt_receipts.read(doc, expected_scope)
            if saved:
                return {k: saved[k] for k in ('status', 'version', 'command', 'usage', 'detail', 'retry_after') if k in saved}
        # Record the employee's handoff even if its turn stops before finalization.
        path = '/issues/' + issue['id'] + '/comments'
        nonce = str(uuid5(NAMESPACE_URL, f'jarvis-package:{issue["id"]}:{turn["agent"]}:{name}'))
        line = blocker_review.PACKAGE_REQUEST + name
        row = next((r for r in api('GET', path) if r.get('clientRequestId') == nonce), None)
        if row is None:
            row = api('POST', path, {'body': line, 'clientRequestId': nonce}, turn['run'])
        if row.get('body') != line or row.get('authorAgentId') != turn['agent'] or not row.get('id'):
            raise ValueError('Paperclip did not confirm the employee package request.')
        turn.setdefault('package_reviews', {})[name] = row['id']
        return {'status':'requested_ceo_review', 'package':name, 'request_id':row['id'],
                'ceo_issue_id':parent['id'], 'next':'Report this dependency and wait for the owner’s decision.'}
    expected = payload(name, turn['company'], turn['project'], issue['id'], turn['agent'])
    path = '/issues/' + issue['id']
    rows = api('GET', path + '/approvals')
    approval = next((a for a in rows if matches(a, expected)), None)
    if approval is None:
        approval = api('POST', '/companies/' + turn['company'] + '/approvals', {
            'type': 'request_board_approval', 'requestedByAgentId': turn['agent'],
            'issueIds': [issue['id']], 'payload': expected}, turn['run'])
    if not matches(approval, expected):
        raise ValueError('Paperclip did not confirm the scoped package request')
    state = {'approval_id': approval['id'], 'decision': approval['status'], 'package': name}
    if approval['status'] == 'approved' and approval.get('decidedByUserId'):
        docs = api('GET', path + '/documents')
        doc = next((d for d in docs if d.get('key') == receipt_key(approval['id'])), None)
        install = receipt(doc, approval)
        if install and install['status'] == 'installed':
            if (turn.get('action_approval') or {}).get('id') == approval['id']:
                turn.pop('action_approval')
            return {**state, **install}
        state['status'] = (install or {}).get('status', 'awaiting_install')
    else:
        state['status'] = approval['status']
    turn['action_approval'] = {'id': approval['id'], 'status': approval['status'], 'kind': KIND, 'package': name}
    return state
