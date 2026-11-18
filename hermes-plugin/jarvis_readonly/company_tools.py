"""CEO-only, bounded native Paperclip company operations; never host commands."""
import hashlib
import re
from uuid import UUID

from . import ceo_tools
from . import paperclip_reporting as reporting


def manage(args, **kwargs):
    turn, me, issue = ceo_tools.scope()
    if (turn.get('inference_configuration') or {}).get('version') != 3:
        raise PermissionError('Company management requires the approved Codex workforce policy')
    action = args['action']
    company = turn['company']
    projects = reporting.api('GET', '/companies/' + company + '/projects')
    projects = [p for p in projects if p.get('companyId') == company]
    roster = reporting.api('GET', '/companies/' + company + '/agents')
    if action == 'context':
        approvals = reporting.api('GET', '/issues/' + turn['issue'] + '/approvals')
        return ceo_tools.audit(turn, action, {'source': 'Paperclip native company records',
            'projects': [{k: p.get(k) for k in ('id', 'name', 'description', 'status')} for p in projects[:40]],
            'employees': [{**{k: a.get(k) for k in ('id', 'name', 'role', 'status', 'reportsTo')},
                'profile': ((a.get('metadata') or {}).get('jarvis') or {}).get('profile')}
                for a in roster if a.get('reportsTo') == me['id'] and a.get('companyId') == company],
            'approvals': [{k: a.get(k) for k in ('id', 'type', 'status', 'decisionNote')} for a in approvals]},
            tool_name='paperclip_company')
    if not turn.get('plan_decision'):
        ceo_tools.manage({'action': 'plan', 'decision': 'self',
            'plan': 'Perform the requested scoped Paperclip company operation using native records and report its actual result.'})
    if action == 'rename_agent':
        agent_id = str(UUID(args['agent_id']))
        agent = next((a for a in roster if a['id'] == agent_id and a.get('companyId') == company
                      and (a.get('reportsTo') == me['id'] or a['id'] == me['id'])), None)
        if not agent or agent.get('status') in ('terminated', 'pending_approval'):
            raise PermissionError('Rename requires a current agent in your own team')
        name = str(args.get('name', '')).strip()
        if not 2 <= len(name) <= 100 or re.search(r'[\x00-\x1f\x7f]', name):
            raise ValueError('Provide a name between 2 and 100 characters on one line')
        changed = agent['name'] != name
        if changed:
            reporting.api('PATCH', '/agents/' + agent_id, {'name': name}, turn['run'])
        updated = reporting.api('GET', '/agents/' + agent_id)
        if updated.get('companyId') != company or updated.get('name') != name:
            raise ValueError('Paperclip did not confirm the requested agent name')
        turn['company_operation_verified'] = True
        return ceo_tools.audit(turn, action, {'agent_id': agent_id, 'name': name, 'renamed': changed},
                               tool_name='paperclip_company')
    if action == 'create_project':
        name = str(args.get('name', '')).strip()
        if not 2 <= len(name) <= 100:
            raise ValueError('Provide a project name between 2 and 100 characters')
        existing = next((p for p in projects if p['name'].casefold() == name.casefold()), None)
        if existing:
            return ceo_tools.audit(turn, action, {'project_id': existing['id'], 'name': existing['name'],
                'created': False, 'source': 'Existing native project reused'}, tool_name='paperclip_company')
        body = {'name': name, 'description': str(args.get('description', ''))[:4000], 'status': 'planned',
            'idempotencyKey': 'jarvis-project:' + hashlib.sha256((company + ':' + name.casefold()).encode()).hexdigest()}
        repository = args.get('repository_url')
        if repository:
            if not isinstance(repository, str) or not re.fullmatch(
                    r'https://github\.com/[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*/?', repository):
                raise ValueError('Repository must be an HTTPS github.com owner/repository URL without credentials')
            body['repositoryUrls'] = [repository]
        project = reporting.api('POST', '/companies/' + company + '/projects', body, turn['run'])
        return ceo_tools.audit(turn, action, {'created': True, 'project_id': project['id'], 'name': project['name'],
            'status': project['status'], 'host_workspace_mounted': False}, tool_name='paperclip_company')
    if action == 'set_project':
        project_id = str(UUID(args['project_id']))
        project = next((p for p in projects if p['id'] == project_id), None)
        if not project:
            raise PermissionError('Project must belong to the current JARVIS company')
        all_issues = reporting.api('GET', '/companies/' + company + '/issues')
        if any(i.get('parentId') == turn['issue'] for i in all_issues):
            raise ValueError('Choose the project before delegation; an existing task tree cannot be silently moved')
        updated = reporting.api('PATCH', '/issues/' + turn['issue'], {'projectId': project_id}, turn['run'])
        if updated.get('projectId') != project_id:
            raise ValueError('Native project association was not confirmed')
        turn['project'] = project_id
        return ceo_tools.audit(turn, action, {'project_id': project_id, 'name': project['name'],
            'issue_id': turn['issue'], 'associated': True}, tool_name='paperclip_company')
    if action == 'request_termination':
        agent_id = str(UUID(args['agent_id']))
        agent = next((a for a in roster if a['id'] == agent_id and a.get('companyId') == company and
            a.get('reportsTo') == me['id']), None)
        if not agent or agent_id == me['id']:
            raise PermissionError('Only a direct report may be proposed for removal; CEO self-removal is unavailable')
        if agent.get('status') == 'terminated':
            return ceo_tools.audit(turn, action, {'agent_id': agent_id, 'status': 'terminated',
                'history_preserved': True}, tool_name='paperclip_company')
        reason = str(args.get('reason', '')).strip()
        if not 20 <= len(reason) <= 2000:
            raise ValueError('Provide the human-requested reason and scope for removal (20–2000 characters)')
        approvals = reporting.api('GET', '/issues/' + turn['issue'] + '/approvals')
        approval = next((a for a in approvals if (a.get('payload') or {}).get('kind') == 'jarvis_staff_termination'
            and (a.get('payload') or {}).get('agentId') == agent_id), None)
        if not approval:
            approval = reporting.api('POST', '/companies/' + company + '/approvals', {
                'type': 'request_board_approval', 'requestedByAgentId': me['id'], 'issueIds': [turn['issue']],
                'payload': {'kind': 'jarvis_staff_termination', 'agentId': agent_id, 'name': agent['name'],
                    'reason': reason, 'summary': 'Terminate ' + agent['name'] + '; retain employee/task/execution history.',
                    'scope': 'Native direct-report termination only; active runs are cancelled by Paperclip.',
                    'issue_id': turn['issue']}}, turn['run'])
        turn['action_approval'] = {'id': approval['id'], 'status': approval['status']}
        return ceo_tools.audit(turn, action, {'approval_id': approval['id'], 'status': approval['status'],
            'executed': False, 'agent_id': agent_id, 'next': 'Human may type /approve ' + approval['id'] +
            ' or /reject ' + approval['id'] + '. No removal occurs before the native decision.'}, tool_name='paperclip_company')
    raise ValueError('Unsupported bounded company operation')


def register(ctx):
    ctx.register_tool(name='paperclip_company', toolset='jarvis_ceo', handler=manage, schema={
        'name': 'paperclip_company', 'description': 'Native JARVIS CEO project and staff operations. Rename a team member with action=rename_agent, agent_id and name, then report the confirmed name. Read context; create/reuse a project; associate current objective before delegation; request human approval to remove a direct report. No host files, repository writes, self-approval or deletion.',
        'parameters': {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['context', 'create_project', 'set_project', 'rename_agent', 'request_termination']},
            'name': {'type': 'string'}, 'description': {'type': 'string'}, 'repository_url': {'type': 'string'},
            'project_id': {'type': 'string'}, 'agent_id': {'type': 'string'}, 'reason': {'type': 'string'}},
            'required': ['action'], 'additionalProperties': False}})
