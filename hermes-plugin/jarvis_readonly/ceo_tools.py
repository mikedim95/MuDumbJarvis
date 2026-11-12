"""Identity-bound Paperclip operations; Paperclip alone schedules persistent work."""
import hashlib
import json
import os
import re
import time
from uuid import UUID

from . import paperclip_reporting as reporting


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


def audit(turn, action, result):
    from hermes_constants import get_hermes_home
    record = {'timestamp': time.time(), 'issue_id': turn['issue'], 'paperclip_run_id': turn['run'],
              'session_id': turn['session'], 'tool': 'paperclip_ceo', 'action': action, 'result': result}
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
        'employees': [{k: a.get(k) for k in ('id', 'name', 'role', 'title', 'capabilities', 'lifecycleState')}
                      for a in roster],
        'plan_decision': turn.get('plan_decision'),
        'recent_updates': [{'authorAgentId': c.get('authorAgentId'), 'createdAt': c.get('createdAt'),
                            'body': update_body(c)} for c in updates[-3:]],
        'children': [{k: i.get(k) for k in ('id', 'identifier', 'title', 'status', 'assigneeAgentId')}
                     for i in items],
        'policy': 'Use the minimum employees. Simple inventory: plan self, then use local_ollama_models and write the final technical report. '
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
                'Read the actual objective above and select the minimum team. A simple inventory can be done directly '
                'after a self plan. An objective explicitly requiring operator collection and CEO review needs one scoped '
                'child for the existing employee; call the delegate tool with the exact selected employee ID and scope.')
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
        plan = str(args.get('text', '')).strip()
        if decision not in ('self', 'delegate', 'hire') or not 10 <= len(plan) <= 4000:
            raise ValueError('A self/delegate/hire decision and a clear scoped plan are required')
        reporting.api('PATCH', '/issues/' + turn['issue'],
                      {'comment': f'[JARVIS CEO PLAN decision={decision}]\n' + plan}, turn['run'])
        turn['plan_decision'] = decision
        return audit(turn, action, {'recorded': True, 'decision': decision,
                     'next': 'Call local_ollama_models now.' if decision == 'self' else
                             'Delegate a scoped child to one existing employee.' if decision == 'delegate' else
                             'Request a hire for human approval only if existing employees cannot do the work.'})
    if action == 'delegate':
        agent_id = str(UUID(str(args.get('agent_id', ''))))
        employee = next((a for a in employees(turn) if a['id'] == agent_id and a.get('lifecycleState') == 'ready'), None)
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
    ctx.register_tool(name='paperclip_context', toolset='jarvis_ceo',
        schema={'name': 'paperclip_context', 'description': 'Read your actual assigned Paperclip objective, company goals, existing employees and child task states. Authenticated current context is automatically supplied; call for additional reads.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, handler=context)
    ctx.register_tool(name='paperclip_ceo', toolset='jarvis_ceo',
        schema={'name': 'paperclip_ceo', 'description': 'Persistent Paperclip CEO operations. Simple work: plan with decision=self and text, then use local_ollama_models and report. Delegation: action=delegate, exact employee agent_id, title, text=scoped work and acceptance criteria; records this selected scope as the plan BEFORE creating one child. Optional plan adds rationale. End turn after delegation. When verified completed-child results are delivered, write the final consolidated report; review optionally rereads the evidence. request_hire only for essential missing capability with human approval.',
                'parameters': {'type': 'object', 'properties': {
                    'action': {'type': 'string', 'enum': ['plan', 'delegate', 'review', 'request_hire']},
                    'decision': {'type': 'string', 'enum': ['self', 'delegate', 'hire']},
                    'text': {'type': 'string'}, 'plan': {'type': 'string'}, 'agent_id': {'type': 'string'}, 'title': {'type': 'string'}},
                    'required': ['action'], 'additionalProperties': False}}, handler=manage)
