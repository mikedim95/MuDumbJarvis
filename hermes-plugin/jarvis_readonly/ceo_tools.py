"""Identity-bound Paperclip operations; Paperclip alone schedules persistent work."""
import hashlib
import json
import os
import re
import time
from uuid import UUID

from . import paperclip_reporting as reporting
from . import profile_registry


def scope():
    if os.environ.get('JARVIS_AGENT_ROLE') != 'ceo':
        raise PermissionError('CEO tools are unavailable in this runtime')
    turn = reporting.current_turn()
    me = reporting.api('GET', '/agents/me')
    if me['id'] != turn['agent'] or me.get('role') != 'ceo' or me['id'] != os.environ.get('JARVIS_PAPERCLIP_AGENT_ID'):
        raise PermissionError('CEO identity mismatch')
    issue = reporting.api('GET', '/issues/' + turn['issue'])
    if (issue.get('assigneeAgentId') != me['id'] or issue.get('companyId') != turn['company']
            or issue.get('executionRunId') != turn['run']):
        raise PermissionError('No current CEO execution owns this objective')
    return turn, me, issue


def children(turn):
    issues = reporting.api('GET', '/companies/' + turn['company'] + '/issues')
    return [i for i in issues if i.get('parentId') == turn['issue'] and
            i.get('companyId') == turn['company'] and i.get('projectId') == turn['project']]


def employees(turn):
    return [a for a in reporting.api('GET', '/companies/' + turn['company'] + '/agents')
            if a.get('reportsTo') == turn['agent'] and a.get('status') not in ('terminated', 'pending_approval')]


def audit(turn, action, result, tool_name='paperclip_ceo'):
    from hermes_constants import get_hermes_home
    record = {'timestamp': time.time(), 'issue_id': turn['issue'], 'paperclip_run_id': turn['run'],
              'session_id': turn['session'], 'tool': tool_name, 'action': action, 'result': result}
    log = get_hermes_home() / 'logs' / 'ceo-tools.jsonl'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a') as stream:
        stream.write(json.dumps(record) + '\n')
    return json.dumps(result)


def update_body(comment):
    body = comment.get('body', '')
    if body.startswith('[JARVIS CEO WAITING]'):
        body = body.split('\n\n', 1)[0]
    return body.split('Verified local_ollama_models')[0][:1800]


def context_snapshot(turn, issue=None, comments=None):
    """Read bounded authoritative state; this helper never claims a model tool call."""
    issue = issue or reporting.api('GET', '/issues/' + turn['issue'])
    goals = reporting.api('GET', '/companies/' + turn['company'] + '/goals')
    comments = sorted(comments if comments is not None else reporting.api(
        'GET', '/issues/' + turn['issue'] + '/comments'), key=lambda c: c.get('createdAt') or '')
    roster = employees(turn)
    items = children(turn)
    if len(roster) > 20 or len(items) > 12:
        raise ValueError('CEO context exceeds the bounded employee/child limit')
    updates = [c for c in comments if c.get('authorUserId') or
        (c.get('authorAgentId') == turn['agent'] and c.get('body', '').startswith(
        ('[JARVIS CEO PLAN', '[JARVIS CEO REVIEW]', '[JARVIS CEO WAITING]', '[JARVIS CEO RESULTS READY]')))]
    result = {'source': 'Paperclip REST API',
        'objective': {k: issue.get(k) for k in ('id', 'identifier', 'title', 'description', 'status', 'goalId')},
        'goals': [{k: g.get(k) for k in ('id', 'title', 'description', 'status')} for g in goals[:20]],
        'goal_count': len(goals), 'goal_list_truncated': len(goals) > 20,
        'employees': [{**{k: a.get(k) for k in ('id', 'name', 'role', 'title', 'capabilities', 'lifecycleState')},
                       'profile': profile_registry.employee_profile(a),
                       'runtime_ready': profile_registry.ready_employee(a)}
                      for a in roster],
        'capability_profiles': [{k: profile_registry.profile(name)[k] for k in ('id', 'name', 'capabilities', 'authority')}
                               for name in profile_registry.catalog()['profiles']],
        'plan_decision': turn.get('plan_decision'),
        'recent_updates': [{'authorAgentId': c.get('authorAgentId'), 'createdAt': c.get('createdAt'),
                            'body': update_body(c)} for c in updates[-3:]],
        'children': [{k: i.get(k) for k in ('id', 'identifier', 'title', 'status', 'assigneeAgentId')}
                     for i in items],
        'policy': 'Use the minimum employees. Simple inventory must use self execution: call local_ollama_models directly and the runtime records its scope before reading, or optionally record an explicit self plan for rationale. Then write the final technical report. '
                  'With no children, do not wait for child completion. For separate operator and CEO review roles, use paperclip_ceo '
                  'action=delegate with the existing employee ID, title and scoped text; plan rationale is optional. '
                  'A pending child is handled by Paperclip: end with a waiting update. When verified child results are delivered '
                  'below, analyze them and write the FINAL report NOW; there is no worker left to wait for. '
                  'Explicit review tool use is optional after authenticated result delivery. Hiring always needs human approval.'}
    # Bound each free-text field before constructing the hook context.
    result['objective']['description'] = str(result['objective'].get('description') or '')[:8000]
    for goal in result['goals']:
        goal['description'] = str(goal.get('description') or '')[:1000]
    for employee in result['employees']:
        employee['capabilities'] = str(employee.get('capabilities') or '')[:1600]
    return result, items


def context(args, **kwargs):
    turn, me, issue = scope()
    result, _ = context_snapshot(turn, issue)
    return audit(turn, 'context', result)


def prepare_turn_context(turn, issue=None, comments=None, deadline=None):
    """Supply authenticated facts through the supported pre_llm_call context result.

    This reads Paperclip and validates existing results. It does not plan, assign,
    schedule, invent a tool invocation, or approve the model's eventual analysis.
    """
    for key in ('delivered_children', 'delivery_run_id', 'delivery_context_sha256'):
        turn.pop(key, None)
    if not turn.get('reviewed_children'):
        turn.pop('child_evidence', None)
    try:
        reporting.check_budget(deadline)
        snapshot, items = context_snapshot(turn, issue, comments)
        reporting.check_budget(deadline)
        verified = []
        if items and all(item['status'] == 'done' for item in items):
            verified = verified_children(turn, items, deadline=deadline)
            snapshot['verified_child_results'] = verified
            snapshot['current_action'] = (
                'VERIFIED RESULTS READY: every child listed above is DONE. The signed tool data and succeeded worker runs '
                'have been independently validated by the runtime. This is delivery FOR YOUR REVIEW, not model approval. '
                'Analyze and consolidate these exact names, size_bytes and size_gib into the FINAL technical report NOW. '
                'State source, completed work and unresolved limits. Do not wait, delegate again, or retrieve a competing inventory. '
                'You may use the explicit review tool, but the validated facts are already available here.')
        elif items:
            snapshot['current_action'] = (
                'Existing delegated work is not all complete. Do not create duplicate work or claim completion. '
                'Report the actual pending/blocked child state. Paperclip owns continuation.')
        else:
            snapshot['current_action'] = (
                'Read the actual objective above and use the minimum team. For an inventory-only objective without an '
                'explicit requirement for independent operator and reviewer roles, you MUST call local_ollama_models yourself. '
                'Your direct tool selection records bounded self scope before the read; a separate explicit self plan is optional for rationale. '
                'Do not delegate this simple inventory merely because a worker is available. '
                'An objective explicitly requiring independent operator collection and CEO review needs one scoped child '
                'for the existing employee; call the delegate tool with the exact selected employee ID and scope.')
        text = 'Authenticated current Paperclip state (runtime preflight, not a model tool call):\n' + json.dumps(snapshot, indent=2)
        if len(text) > 32000:
            raise ValueError('Verified CEO context exceeds its bounded payload limit')
        reporting.check_budget(deadline)
        if verified:
            reporting.api('PATCH', '/issues/' + turn['issue'], {'comment':
                '[JARVIS CEO RESULTS READY]\nSigned local tool results and succeeded worker execution for ' +
                ', '.join(item['identifier'] for item in items) +
                ' are supplied to the current CEO turn FOR review and consolidation. This delivery is not approval of any model analysis.'},
                turn['run'])
            reporting.check_budget(deadline)
        context_hash = hashlib.sha256(text.encode()).hexdigest()
        from hermes_constants import get_hermes_home
        record = {'timestamp': time.time(), 'source': 'hermes_pre_llm_call',
            'action': 'verified_child_results_delivered' if verified else 'objective_state_delivered',
            'issue_id': turn['issue'], 'paperclip_run_id': turn['run'], 'session_id': turn['session'],
            'delivered_child_ids': [item['id'] for item in items] if verified else [],
            'verified': verified, 'context_sha256': context_hash,
            'context_delivered_for_review': bool(verified)}
        log = get_hermes_home() / 'logs' / 'ceo-preflight.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        reporting.check_budget(deadline)
        if verified:
            turn['delivered_children'] = [item['id'] for item in items]
            turn['delivery_run_id'] = turn['run']
            turn['delivery_context_sha256'] = context_hash
            turn['child_evidence'] = verified
        return text
    except Exception:
        for key in ('delivered_children', 'delivery_run_id', 'delivery_context_sha256'):
            turn.pop(key, None)
        if not turn.get('reviewed_children'):
            turn.pop('child_evidence', None)
        raise


def verified_children(turn, items, deadline=None):
    verified = []
    for child in items:
        reporting.check_budget(deadline)
        if child['status'] != 'done':
            raise ValueError('Worker results are not complete: ' + child['identifier'] + ' ' + child['status'])
        comments = reporting.api('GET', '/issues/' + child['id'] + '/comments')
        reporting.check_budget(deadline)
        proof = None
        for comment in sorted(comments, key=lambda c: c.get('createdAt') or ''):
            if comment.get('authorAgentId') != child.get('assigneeAgentId'):
                continue
            for line in comment.get('body', '').splitlines():
                if not line.startswith('JARVIS_EXECUTION_EVIDENCE='):
                    continue
                try:
                    candidate = json.loads(line.split('=', 1)[1])
                except (ValueError, TypeError):
                    continue
                if not isinstance(candidate, dict):
                    continue
                if (reporting.authentic_evidence(candidate) and candidate.get('agent_id') == child['assigneeAgentId']
                        and candidate.get('tool') == 'local_ollama_models'
                        and isinstance(candidate.get('models'), list)
                        and candidate.get('session_id') == 'paperclip:company:' + turn['company'] +
                            ':agent:' + child['assigneeAgentId'] + ':issue:' + child['id']):
                    proof = candidate
        if proof is None:
            raise ValueError('No successful, issue-correlated worker tool evidence: ' + child['identifier'])
        # Wait for THIS evidence's adapter run, never an older succeeded retry.
        for attempt in range(12):
            reporting.check_budget(deadline)
            runs = reporting.api('GET', '/issues/' + child['id'] + '/runs')
            # Paperclip also returns related manager runs that created/read a
            # child. Only this assignee's execution attempts govern its proof.
            runs = [r for r in runs if r.get('agentId') == child['assigneeAgentId']]
            latest = max(runs, key=lambda r: r.get('startedAt') or '') if runs else None
            if latest and latest['runId'] != proof.get('paperclip_run_id'):
                raise ValueError('A newer worker execution invalidates the prior result: ' + child['identifier'])
            if latest and latest['status'] == 'succeeded':
                break
            remaining = reporting.check_budget(deadline)
            time.sleep(min(1, remaining) if remaining is not None else 1)
        else:
            raise ValueError('Worker execution has not succeeded: ' + child['identifier'])
        reporting.check_budget(deadline)
        verified.append({'issue_id': child['id'], 'identifier': child['identifier'], 'evidence': proof})
    return verified


def manage(args, **kwargs):
    turn, me, issue = scope()
    action = args.get('action')
    if action == 'plan':
        decision = args.get('decision')
        if decision not in ('self', 'delegate', 'hire'):
            raise ValueError('An explicit self/delegate/hire decision is required')
        if 'text' in args or 'plan' in args:
            plan = args['text'] if 'text' in args else args['plan']
            if not isinstance(plan, str) or not 10 <= len(plan.strip()) <= 4000:
                raise ValueError('Plan text or plan rationale must be a string between 10 and 4000 characters')
            plan = plan.strip()
        elif decision == 'self':
            objective = issue.get('description') or issue.get('title')
            if not isinstance(objective, str) or not objective.strip():
                raise ValueError('The actual assigned objective is required for a runtime-generated self scope')
            objective = objective.strip()
            excerpt = objective[:3000]
            if len(objective) > 3000:
                excerpt += '\n[Objective truncated for this plan record; full text remains on the assigned Paperclip issue.]'
            plan = ('Runtime-generated execution scope, not a model-supplied rationale. '
                    'The CEO explicitly selected self.\nAssigned Paperclip objective: ' + excerpt +
                    '\nUse the existing authorized local_ollama_models read-only inventory tool and report verified facts or actual blockers. '
                    'This plan grants no new permissions and assigns no worker.')
        else:
            raise ValueError('A clear scoped plan is required for delegate or hire decisions')
        reporting.api('PATCH', '/issues/' + turn['issue'],
                      {'comment': f'[JARVIS CEO PLAN decision={decision}]\n' + plan}, turn['run'])
        turn['plan_decision'] = decision
        return audit(turn, action, {'recorded': True, 'decision': decision,
                     'next': 'Call local_ollama_models now.' if decision == 'self' else
                             'Delegate a scoped child to one existing employee.' if decision == 'delegate' else
                             'Request a hire for human approval only if existing employees cannot do the work.'})
    if action == 'delegate':
        agent_id = str(UUID(str(args.get('agent_id', ''))))
        employee = next((a for a in employees(turn) if a['id'] == agent_id and profile_registry.ready_employee(a)), None)
        if employee is None:
            raise PermissionError('Only a ready existing direct report may receive delegated work')
        title, text = str(args.get('title', '')).strip(), str(args.get('text', '')).strip()
        if not title or not 20 <= len(text) <= 6000:
            raise ValueError('A clear title, responsibility and acceptance criteria are required')
        if turn.get('plan_decision') != 'delegate':
            plan = str(args.get('plan', '')).strip()
            if plan and not 10 <= len(plan) <= 4000:
                raise ValueError('An optional rationale must be between 10 and 4000 characters')
            if not plan:
                plan = ('Selected existing employee: ' + employee['name'] + ' (' + agent_id + ').\n'
                        'Responsibility: ' + title + '.\nScope and acceptance criteria supplied by the CEO:\n' + text +
                        '\nReview owner: CEO. Reuse one existing employee; no new hire is requested.')
            reporting.api('PATCH', '/issues/' + turn['issue'],
                          {'comment': '[JARVIS CEO PLAN decision=delegate]\n' + plan}, turn['run'])
            turn['plan_decision'] = 'delegate'
        key = 'jarvis-ceo:' + turn['issue'] + ':' + agent_id
        child = reporting.api('POST', '/companies/' + turn['company'] + '/issues',
                    {'title': title[:120], 'description': text, 'parentId': turn['issue'],
                     'projectId': turn['project'], 'goalId': issue.get('goalId'), 'status': 'todo',
                     'assigneeAgentId': agent_id, 'priority': 'medium', 'idempotencyKey': key,
                     'allowDuplicate': True}, turn['run'])
        if (child.get('parentId') != turn['issue'] or child.get('projectId') != turn['project']
                or child.get('assigneeAgentId') != agent_id or child.get('description') != text):
            raise ValueError('This employee already has a differently scoped child; review it before requesting more work')
        reporting.api('PATCH', '/issues/' + turn['issue'],
                      {'comment': 'CEO delegated ' + child['identifier'] + ' to ' + employee['name'] +
                       '. Scoped responsibility: ' + text}, turn['run'])
        return audit(turn, action, {'child_id': child['id'], 'identifier': child['identifier'],
                    'assigned_to': employee['name'], 'status': child['status'],
                    'next': 'End this turn with a short waiting update. Do not poll or hire. '
                            'Paperclip will wake the CEO when the worker finishes.'})
    if action == 'review':
        items = children(turn)
        if not items:
            raise ValueError('There are no delegated results to review')
        verified = verified_children(turn, items)
        turn['reviewed_children'] = [i['id'] for i in items]
        turn['child_evidence'] = verified
        reporting.api('PATCH', '/issues/' + turn['issue'],
                      {'comment': '[JARVIS CEO REVIEW]\nVerified completed child results, succeeded Paperclip runs, '
                       'assigned-worker authorship and exact local tool data: ' +
                       ', '.join(i['identifier'] for i in items)}, turn['run'])
        return audit(turn, action, {'reviewed': verified,
                    'next': 'Consolidate these verified facts into the final technical report. State blockers and limits.'})
    if action == 'request_hire':
        if args.get('profile'):
            return request_profile_hire(turn, me, args)
        if turn.get('plan_decision') != 'hire':
            raise ValueError('Record why existing employees cannot cover the essential capability first')
        reason = str(args.get('text', '')).strip()
        name = str(args.get('title', '')).strip()
        if not name or len(reason) < 40:
            raise ValueError('A name and concrete unmet capability justification are required')
        company = reporting.api('GET', '/companies/' + turn['company'])
        if not company.get('requireBoardApprovalForNewAgents'):
            raise PermissionError('Human hiring approval must be enabled')
        # A candidate is inert until a human approves AND provisions its isolated runtime.
        hired = reporting.api('POST', '/companies/' + turn['company'] + '/agent-hires',
                    {'name': name[:80], 'role': 'general', 'title': name[:80], 'reportsTo': me['id'],
                     'capabilities': reason[:2000], 'adapterType': 'hermes_gateway',
                     'adapterConfig': {}, 'runtimeConfig': {'heartbeat': {'enabled': False}},
                     'sourceIssueId': turn['issue']}, turn['run'])
        approval = hired.get('approval') or {}
        turn['hiring_approval'] = approval.get('id')
        return audit(turn, action, {'approval_id': approval.get('id'), 'approval_status': approval.get('status'),
                     'agent_status': (hired.get('agent') or {}).get('status'),
                     'next': 'Stop and report the pending human hiring approval. The candidate cannot execute before approval and operator provisioning.'})
    raise ValueError('Unknown CEO action')


def request_profile_hire(turn, me, args, tool_name='paperclip_ceo'):
    """Native approval-aware staffing; no runtime or employee bypass is granted."""
    def emit(result):
        return audit(turn, 'request_hire', result, tool_name=tool_name)
    selected = profile_registry.profile(args['profile'])
    reason, name = str(args.get('text', '')).strip(), str(args.get('title', '')).strip()
    if len(reason) < 40 or len(reason) > 4000 or not name:
        raise ValueError('Name and concrete essential capability justification are required')
    roster = employees(turn)
    suitable = [a for a in roster if profile_registry.employee_profile(a) == selected['id']]
    if suitable:
        return emit({'hire_created': False, 'existing_employees': [
            {'id': a['id'], 'name': a['name'], 'runtime_ready': profile_registry.ready_employee(a)} for a in suitable],
            'next': 'Reuse the existing employee. If its runtime is being provisioned, wait for the native readiness notification; do not create a duplicate.'})
    body = profile_registry.hire_body(turn, me, selected['id'], name, reason)
    # Native roster/approvals remain the only durable source. Check across runs,
    # complementing Paperclip's own per-run hire fingerprint idempotency.
    all_agents = reporting.api('GET', '/companies/' + turn['company'] + '/agents')
    pending = [a for a in all_agents if a.get('reportsTo') == me['id'] and a.get('status') == 'pending_approval'
               and profile_registry.employee_profile(a) == selected['id']]
    if pending:
        return emit({'hire_created': False, 'pending_employee_ids': [a['id'] for a in pending],
            'next': 'A matching employee hire is already awaiting a human decision. Do not create another employee for this capability.'})
    prior = next((a for a in all_agents if ((a.get('metadata') or {}).get('jarvis') or {}).get('runtime_id') ==
                  body['metadata']['jarvis']['runtime_id']), None)
    if prior:
        approvals = reporting.api('GET', '/issues/' + turn['issue'] + '/approvals')
        approval = next((a for a in approvals if (a.get('payload') or {}).get('agentId') == prior['id']), {})
        turn['hiring_approval'] = approval.get('id')
        turn['plan_decision'] = 'hire'
        return emit({'hire_created': False, 'agent_id': prior['id'],
            'approval_id': approval.get('id'), 'approval_status': approval.get('status'),
            'next': 'This request already exists. Respect its human decision; a rejection is a blocker, not permission to rehire.'})
    company = reporting.api('GET', '/companies/' + turn['company'])
    if not company.get('requireBoardApprovalForNewAgents'):
        raise PermissionError('Human hiring approval must be enabled')
    reporting.api('PATCH', '/issues/' + turn['issue'], {'comment':
        '[JARVIS CEO PLAN decision=hire]\nEssential missing profile: ' + selected['name'] +
        '\nCEO justification: ' + reason + '\nProposed authority: ' + selected['authority'] +
        '\nNo employee runtime is provisioned until a human approves the native Paperclip hire.'}, turn['run'])
    turn['plan_decision'] = 'hire'
    hired = reporting.api('POST', '/companies/' + turn['company'] + '/agent-hires', body, turn['run'])
    approval = hired.get('approval') or {}
    if not approval.get('id') or approval.get('status') != 'pending':
        raise ValueError('Native human hiring approval was not created')
    turn['hiring_approval'] = approval['id']
    return emit({'hire_created': True, 'profile': selected['id'],
        'agent_id': (hired.get('agent') or {}).get('id'), 'approval_id': approval['id'],
        'approval_status': approval['status'], 'authority': selected['authority'],
        'next': 'End this turn and report the pending human approval. No tools or runtime are granted before approval. Paperclip will deliver the decision.'})


def finalize(turn, completed=False, failed=False, interrupted=False, turn_exit_reason=''):
    items = children(turn)
    success = completed and not failed and not interrupted and bool(turn['response'].strip())
    models = turn.get('inventory', [])
    if turn.get('child_evidence'):
        models = [m for child in turn['child_evidence'] for m in child['evidence']['models']]
    names = {m['name'] for m in models if isinstance(m, dict) and isinstance(m.get('name'), str)}
    missing_report = bool(names) and (len(turn['response'].strip()) < 100 or
        sum(name in turn['response'] for name in names) < min(2, len(names)))
    status, comment = 'blocked', turn['response']
    if not success:
        comment = 'CEO runtime failed or was interrupted. ' + str(turn_exit_reason)
    elif not turn.get('plan_decision'):
        comment = 'CEO verification blocked: no plan/assignment decision was recorded in Paperclip.\n\n' + comment
    elif any(i['status'] in ('blocked', 'cancelled') for i in items):
        comment = 'CEO has unresolved or cancelled worker tasks; objective is not complete.\n\n' + comment
    elif items and any(i['status'] != 'done' for i in items):
        status = 'blocked'
        comment = '[JARVIS CEO WAITING]\nDelegated work remains active. Paperclip will wake the CEO when all children complete.\n\n' + comment
    elif turn.get('plan_decision') == 'hire' and turn.get('hiring_approval'):
        status = 'in_review'
        comment = 'Pending human hiring approval ' + turn['hiring_approval'] + '. No employee is authorized to execute yet.\n\n' + comment
    elif re.match(r"^(?:wait(?:ing)?\b|awaiting\b|pending\b|please\s+wait\b|i(?:'m| am)\s+waiting\b)",
                  re.sub(r'^[\s#>*_`-]+', '', turn['response']).lower()):
        comment = 'CEO report incomplete: the response says it is waiting despite having no pending worker execution.\n\n' + comment
    elif missing_report:
        comment = 'CEO report incomplete: the final prose does not identify the retrieved models.\n\n' + comment
    elif items:
        if (set(turn.get('reviewed_children', [])) == {i['id'] for i in items} or
                (set(turn.get('delivered_children', [])) == {i['id'] for i in items} and
                 turn.get('delivery_run_id') == turn['run'] and turn.get('delivery_context_sha256'))):
            # Re-read canonical evidence before accepting final CEO completion.
            verified = verified_children(turn, items)
            status = 'done'
            comment += '\n\nVerified delegated execution data:\n```json\n' + json.dumps(verified, indent=2) + '\n```'
        else:
            comment = 'CEO review or authenticated result delivery is required before objective completion.\n\n' + comment
    elif turn.get('plan_decision') == 'self' and (not turn['needs_inventory'] or turn['inventory_verified']):
        status = 'done'
        if turn.get('inventory') is not None:
            comment += '\n\nVerified local_ollama_models data:\n```json\n' + json.dumps(turn['inventory'], indent=2) + '\n```'
    else:
        comment = 'CEO has not completed the planned execution or is awaiting human approval.\n\n' + comment
    payload = {'status': status, 'comment': comment}
    if status == 'blocked':
        action = 'Review the CEO/worker execution, request any required operator decision, then explicitly retry this task.'
        if comment.startswith('[JARVIS CEO WAITING]'):
            action = 'Await completion of ' + ', '.join(i['identifier'] for i in items) + '; Paperclip will wake this CEO to review their execution evidence and consolidate the result.'
        payload['unblockDescriptor'] = {'owner': {'agentId': turn['agent']}, 'action': action}
    reporting.api('PATCH', '/issues/' + turn['issue'], payload, turn['run'])


def register(ctx):
    def request_employee(args, **kwargs):
        turn, me, _ = scope()
        return request_profile_hire(turn, me, {'profile': args['profile'], 'title': args['name'], 'text': args['reason']}, tool_name='request_employee')

    ctx.register_tool(name='request_employee', toolset='jarvis_ceo', schema={
        'name': 'request_employee',
        'description': 'Create a REAL native Paperclip employee-hire approval for an essential missing capability. Use this tool, not a textual request, when no existing employee covers the required capability. The employee remains inert until a human approves. Do not use for capabilities already present.',
        'parameters': {'type': 'object', 'properties': {
            'profile': {'type': 'string', 'enum': list(profile_registry.catalog()['profiles'])},
            'name': {'type': 'string'},
            'reason': {'type': 'string', 'description': 'Why existing employees cannot provide this essential capability; at least 40 characters.'}},
            'required': ['profile', 'name', 'reason'], 'additionalProperties': False}}, handler=request_employee)
    ctx.register_tool(name='paperclip_context', toolset='jarvis_ceo',
        schema={'name': 'paperclip_context', 'description': 'Read your actual assigned Paperclip objective, company goals, existing employees and child task states. Authenticated current context is automatically supplied; call for additional reads.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, handler=context)
    ctx.register_tool(name='paperclip_ceo', toolset='jarvis_ceo',
        schema={'name': 'paperclip_ceo', 'description': 'Persistent Paperclip CEO operations. Simple work uses your own local_ollama_models call, which records self scope before reading. Delegation: action=delegate, exact employee agent_id, title, text=scoped work and acceptance criteria; records a plan before the child. Optional plan adds rationale. End turn after delegation. Review verified completed-child results and consolidate. Essential missing capability: action=request_hire, profile=one registered capability profile ID, title=employee name, text=concrete unmet capability justification (at least 40 characters). That call records your hiring rationale and requests HUMAN approval. It never provisions before approval and refuses a duplicate suitable employee. A separate plan is optional for profile-based hiring.',
                'parameters': {'type': 'object', 'properties': {
                    'action': {'type': 'string', 'enum': ['plan', 'delegate', 'review', 'request_hire']},
                    'decision': {'type': 'string', 'enum': ['self', 'delegate', 'hire']},
                    'text': {'type': 'string'}, 'plan': {'type': 'string'}, 'agent_id': {'type': 'string'}, 'title': {'type': 'string'},
                    'profile': {'type': 'string', 'enum': list(profile_registry.catalog()['profiles'])}},
                    'required': ['action'], 'additionalProperties': False}}, handler=manage)
