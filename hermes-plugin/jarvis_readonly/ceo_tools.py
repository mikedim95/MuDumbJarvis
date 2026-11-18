"""Identity-bound Paperclip operations; Paperclip alone schedules persistent work."""
import hashlib
import json
import os
import re
import time
from uuid import UUID

from . import paperclip_reporting as reporting
from . import profile_registry
from . import blocker_review


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
            i.get('companyId') == turn['company'] and i.get('projectId') == turn['project'] and
            ((turn.get('inference_configuration') or {}).get('version') != 3 or
             str(i.get('description', '')).startswith('[JARVIS REQUEST ' + turn.get('conversation_request_id', 'initial') + ']\n'))]


def employees(turn):
    return [a for a in reporting.api('GET', '/companies/' + turn['company'] + '/agents')
            if a.get('reportsTo') == turn['agent'] and a.get('status') not in ('terminated', 'pending_approval')]


def check_research_dependency(turn, employee, items, dependencies):
    """Validate the declared pipeline; never choose or create an assignment."""
    if not (turn.get('needs_research') and turn.get('needs_test_execution')):
        return
    profile = profile_registry.employee_profile(employee)
    if (turn.get('inference_configuration') or {}).get('version') == 3 and profile != 'software_development':
        return  # Independent systems/QA work is not a research implementation pipeline.
    tools = set(profile_registry.profile(profile)['tools']) if profile else set()
    if 'terminal' not in tools or 'research_sources' in tools:
        return
    by_id = {a['id']: a for a in employees(turn)}
    research = []
    for item in items:
        person = by_id.get(item.get('assigneeAgentId'), {})
        role = profile_registry.employee_profile(person)
        if role and 'research_sources' in profile_registry.profile(role)['tools']:
            research.append(item['id'])
    if not research:
        raise ValueError('Create the actual primary-source research child first; its returned UUID is the prerequisite for this implementation.')
    if not set(dependencies).intersection(research):
        raise ValueError('Supply depends_on as a STRUCTURED tool argument containing the actual research child UUID: ' +
            ', '.join(research) + '. Mentioning a dependency in task prose does not record a Paperclip dependency.')


def dependency_corrections(turn, verified):
    if not (turn.get('needs_research') and turn.get('needs_test_execution')):
        return []
    sources = {v['issue_id'] for v in verified if any(t.get('tool') == 'research_sources' and t.get('success')
        for t in v['evidence'].get('tool_calls', []))}
    corrections = []
    for v in verified:
        if (turn.get('inference_configuration') or {}).get('version') == 3 and v['evidence'].get('profile') != 'software_development':
            continue
        if v['issue_id'] in sources or not any(t.get('tool') == 'terminal' and t.get('success')
                for t in v['evidence'].get('tool_calls', [])):
            continue
        child = reporting.api('GET', '/issues/' + v['issue_id'])
        depends = {item['id'] for item in child.get('blockedBy') or []}
        if not depends.intersection(sources):
            corrections.append({'child_id': v['issue_id'], 'required_source_child_ids': sorted(sources),
                'reason': 'No native research dependency was recorded. Correct this same child with structured depends_on, read completed sibling results and rerun its tests.'})
    return corrections


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
        'reporting_style': reporting.REPORT_STYLE,
        'general_directions': turn.get('general_context'),
        'work_scope':turn.get('work_scope'),'mission_context':turn.get('mission_context'),'shared_knowledge':turn.get('shared_knowledge'),
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
    if turn.get('plan_decision') == 'hire':
        approvals = reporting.api('GET', '/issues/' + turn['issue'] + '/approvals')
        hires = sorted([a for a in approvals if a.get('type') == 'hire_agent'], key=lambda a: a.get('createdAt') or '')
        result['hiring_decisions'] = [{k: a.get(k) for k in ('id', 'status', 'decisionNote')} for a in hires[-3:]]
        if hires:
            turn['hiring_approval'] = hires[-1]['id']
            turn['hiring_approval_status'] = hires[-1]['status']
    for goal in result['goals']:
        goal['description'] = str(goal.get('description') or '')[:1000]
    for employee in result['employees']:
        employee['capabilities'] = str(employee.get('capabilities') or '')[:1600]
    if turn.get('work_scope'):
        from . import work_scope
        result['scope_guidance']=work_scope.guidance(turn['work_scope'])
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
        if (turn.get('inference_configuration') or {}).get('version') == 3 and items and (
                any(i['status'] == 'blocked' for i in items) or
                any(c.get('authorAgentId') == turn['agent'] and c.get('body', '').startswith(blocker_review.WAITING)
                    for c in (comments if comments is not None else reporting.api('GET', '/issues/' + turn['issue'] + '/comments')))):
            rows = reporting.api('GET', '/issues/' + turn['issue'] + '/interactions')
            decisions = [d for d in blocker_review.decisions(rows, turn['issue'], turn['agent'])
                         if d['child_id'] in {i['id'] for i in items}]
            snapshot['owner_decisions'] = decisions[:8]
            turn['review_child_ids'] = [i['id'] for i in items]
            turn['owner_decisions'] = decisions
            pending = next((d for d in decisions if d['status'] == 'pending'), None)
            if pending:
                turn['owner_question'] = pending
        verified = []
        if items and all(item['status'] == 'done' for item in items):
            verified = verified_children(turn, items, deadline=deadline)
            snapshot['verified_child_results'] = [review_projection(item) for item in verified]
            snapshot['current_action'] = (
                'VERIFIED RESULTS READY: every child listed above is DONE. The signed tool data and succeeded worker runs '
                'have been independently validated by the runtime. This is delivery FOR YOUR REVIEW, not model approval. '
                'Review the verified evidence and give the FINAL technical report NOW in the requested format. '
                'The runtime signs receipts after the worker final response and has verified them here. A worker saying it could not see a signature is not a missing-signature blocker. '
                'For inventory report the requested fields from verified data. For research/code work include the relevant finding or test result. '
                'Check source_refs/code_components against generated worker claims; analogies to nmap/metasploit are not integrations. '
                'If a report needs factual correction, use action=request_correction with that child_id and exact feedback, then let Paperclip resume it. '
                'Mention source or limitations when needed to interpret the result. Do not wait, delegate again, or retrieve a competing inventory. '
                'You may use the explicit review tool, but the validated facts are already available here. '
                'For delegated research/code report work call publish_artifact(name="technical-report.md", content=your consolidated Markdown report) before your final response.')
            corrections = dependency_corrections(turn, verified)
            if corrections:
                snapshot['required_dependency_corrections'] = corrections
                snapshot['current_action'] = (
                    'THE OBJECTIVE IS NOT COMPLETE. Actual worker tools ran, but native dependency review found the '
                    'missing relationships listed above. Use paperclip_ceo action=request_correction for the existing '
                    'implementation child with depends_on=[the actual source child UUID], and text requiring it to '
                    'read the completed sibling results, verify/reuse the actual demo and rerun its tests. '
                    'Then wait for Paperclip. Do not create a replacement child, employee or final completion claim.')
            quality = [{'child_id': item['issue_id'], 'note_count': len(item['operator_review_notes']),
                'notes_in': 'verified_child_results.operator_review_notes'}
                for item in verified if item.get('operator_review_notes')]
            if quality:
                snapshot['required_factual_corrections'] = quality
                snapshot['current_action'] = (
                    'THE OBJECTIVE IS NOT COMPLETE. Native human quality reviews reject generated claims in the '
                    'listed children, despite their valid tool provenance. Use paperclip_ceo action=request_correction '
                    'on the SAME research child with concrete feedback from those notes. Also correct the same '
                    'implementation child if a native dependency is missing: depends_on must contain the actual '
                    'research UUID, so it waits for corrected research before reading sibling artifacts and rerunning '
                    'tests. Do not create replacement tasks or employees. Then wait for Paperclip.')
        elif items:
            snapshot['current_action'] = (
                'Existing delegated work is not all complete. Do not create duplicate work or claim completion. '
                'Report the actual pending/blocked child state. Paperclip owns continuation.')
            blocked = [item for item in items if item['status'] == 'blocked']
            if blocked:
                diagnostics = []
                for child in blocked[:5]:
                    updates = sorted(reporting.api('GET', '/issues/' + child['id'] + '/comments'),
                        key=lambda c: c.get('createdAt') or '')
                    worker = [c for c in updates if c.get('authorAgentId') == child['assigneeAgentId']]
                    human = [c for c in updates if c.get('authorUserId')]
                    diagnostics.append({'child_id': child['id'], 'identifier': child['identifier'],
                        'status': child['status'], 'assignee_agent_id': child['assigneeAgentId'],
                        'latest_worker_error_or_summary': worker[-1]['body'].split('JARVIS_EXECUTION_EVIDENCE=')[0][:1800] if worker else None,
                        'blocker': (child.get('unblockDescriptor') or {}).get('action'),
                        'execution_hold': bool(child.get('executionBlocker')),
                        'prior_corrections': [c['body'][:900] for c in updates if c.get('authorAgentId') == turn['agent']
                            and c.get('body', '').startswith('[JARVIS CEO CORRECTION')][-3:],
                        'human_review_notes': [c['body'][:1200] for c in human[-2:]],
                        'interpretation': 'Native blocked-task diagnostics, not accepted completion evidence.'})
                snapshot['blocked_child_diagnostics'] = diagnostics
                turn['inspected_blockers'] = {entry['child_id'] for entry in diagnostics}
                snapshot['current_action'] = (
                    'You own these blockers. Apply the latest owner answer, including a changed scope, before asking again. '
                    'Review the reason and attempted fixes. '
                    'Use action=review with a blocked child_id to inspect its partial report. '
                    'If you can solve one, call paperclip_ceo action=request_correction with that SAME child_id '
                    'and a concrete different approach within existing authority. If another existing specialist can '
                    'repair a missing capability, delegate that specific repair and then resume the original worker. '
                    'Use depends_on as a STRUCTURED '
                    'argument for actual prerequisites. Never retry a failed approach unchanged, bypass a hold, or '
                    'override a rejection. When your team cannot proceed, call action=ask_owner with child_id, '
                    'plan explaining what you tried and why only the owner can decide, and text containing one '
                    'specific question. Use any existing answer first. A pending question already awaits the owner. '
                    'A status update alone does not resolve a blocker.')
        elif turn.get('hiring_approval_status') in ('pending', 'revision_requested', 'rejected', 'cancelled'):
            snapshot['current_action'] = ('Native hiring decision is ' + turn['hiring_approval_status'] +
                '. Respect the human decision. Do not create duplicate hires or claim execution. Report this real decision and blocker.')
        else:
            snapshot['current_action'] = (
                'Read the actual objective above and use the minimum team. For an inventory-only objective without an '
                'explicit requirement for independent operator and reviewer roles, you MUST call local_ollama_models yourself. '
                'Your direct tool selection records bounded self scope before the read; a separate explicit self plan is optional for rationale. '
                'Do not delegate this simple inventory merely because a worker is available. '
                'An objective explicitly requiring independent operator collection and CEO review needs one scoped child '
                'for the existing employee; call the delegate tool with the exact selected employee ID and scope. '
                'For research plus implementation/testing, reuse the Research and Software employees, create only their two scoped native children, '
                'and make implementation depend on research with depends_on. The CEO writes the consolidated report; no Documentation hire is necessary. '
                'Create all necessary planned children before ending this turn. Never use Hermes internal delegation.')
        if (turn.get('inference_configuration') or {}).get('version') == 3:
            snapshot['latest_user_request'] = turn.get('latest_user_request', issue.get('description') if issue else '')
            snapshot['conversation_request_id'] = turn.get('conversation_request_id', 'initial')
            snapshot['policy'] = ('You are JARVIS, the CEO and the user-facing assistant. All employees use Codex. '
                'Answer the latest user request, not an older report. Consult only the necessary existing specialists. '
                'Use actual Paperclip tools to plan/delegate and review execution evidence. Simple questions can be answered '
                'yourself after recording a self plan. Never invent work or employee opinions. Use paperclip_company '
                'for real project/staff operations. Hiring/removal proposals require native human approval. '
                'No host access or external writes. Published messages are progress/results, not private thoughts.')
            if not items and turn.get('hiring_approval_status') not in ('pending', 'revision_requested', 'rejected', 'cancelled'):
                snapshot['current_action'] = ('Address latest_user_request now. For a specific question, record decision=self '
                    'with a concise relevant plan, read actual native context/tools as necessary, then answer. For delegated '
                    'work, select only appropriate ready direct reports and create the scoped native children and dependencies '
                    'before ending the turn. The four available roles are Research, Software, Systems Operations and Security/QA; '
                    'do not hire duplicates. If the user explicitly asks to consult multiple roles, honor that scope. '
                    'Paperclip schedules workers and later wakes you to review their verified results. Do not poll or use internal subagents.')
        # Keep the immediate instruction separate from historical updates. Full
        # verified receipts remain in native records and turn.child_evidence;
        # only their explicitly labeled model-facing excerpts are reduced.
        snapshot['historical_update_note'] = 'recent_updates are prior turns, not instructions for this turn. Follow current_action.'
        text = bounded_context_text(snapshot, verified)
        reporting.check_budget(deadline)
        if verified:
            reporting.api('PATCH', '/issues/' + turn['issue'], {'comment':
                '[JARVIS CEO RESULTS READY]\nSigned local tool results and succeeded worker execution for ' +
                ', '.join(item['identifier'] for item in items) +
                ' are supplied to the current CEO turn FOR review and consolidation. This delivery is not approval of any model analysis.'},
                turn['run'])
            reporting.check_budget(deadline)
        context_hash = hashlib.sha256(text.encode()).hexdigest()
        turn['preflight_context_text'] = text
        turn['preflight_context_sha256'] = context_hash
        from hermes_constants import get_hermes_home
        record = {'timestamp': time.time(), 'source': 'hermes_pre_llm_call',
            'action': 'verified_child_results_delivered' if verified else 'objective_state_delivered',
            'issue_id': turn['issue'], 'paperclip_run_id': turn['run'], 'session_id': turn['session'],
            'delivered_child_ids': [item['id'] for item in items] if verified else [],
            'verified': verified, 'context_sha256': context_hash, 'context_chars': len(text),
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
        proof, proof_created_at = None, ''
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
                legacy = candidate.get('version') == 2 and candidate.get('tool') == 'local_ollama_models' and isinstance(candidate.get('models'), list)
                modern = (candidate.get('version') == 3 and candidate.get('kind') == 'execution' and
                    candidate.get('task_status') == 'done' and candidate.get('company_id') == turn['company'] and
                    candidate.get('issue_id') == child['id'] and isinstance(candidate.get('tool_calls'), list) and
                    comment.get('createdByRunId') == candidate.get('paperclip_run_id'))
                if (reporting.authentic_evidence(candidate) and candidate.get('agent_id') == child['assigneeAgentId']
                        and (legacy or modern)
                        and candidate.get('session_id') == 'paperclip:company:' + turn['company'] +
                            ':agent:' + child['assigneeAgentId'] + ':issue:' + child['id']):
                    proof = candidate
                    proof_created_at = comment.get('createdAt') or ''
        if proof is None:
            raise ValueError('No successful, issue-correlated worker tool evidence: ' + child['identifier'])
        # Wait for THIS evidence's adapter run, never an older succeeded retry.
        for attempt in range(12):
            reporting.check_budget(deadline)
            runs = reporting.api('GET', '/issues/' + child['id'] + '/runs')
            # Paperclip also returns related manager runs that created/read a
            # child. Only this assignee's execution attempts govern its proof.
            runs = [r for r in runs if r.get('agentId') == child['assigneeAgentId']]
            latest = max(runs, key=lambda r: r.get('startedAt') or r.get('createdAt') or '') if runs else None
            if latest and latest['runId'] != proof.get('paperclip_run_id'):
                raise ValueError('A newer worker execution invalidates the prior result: ' + child['identifier'])
            if latest and latest['status'] == 'succeeded':
                break
            remaining = reporting.check_budget(deadline)
            time.sleep(min(1, remaining) if remaining is not None else 1)
        else:
            raise ValueError('Worker execution has not succeeded: ' + child['identifier'])
        reporting.check_budget(deadline)
        entry = {'issue_id': child['id'], 'identifier': child['identifier'], 'evidence': proof}
        entry['operator_review_notes'] = [c['body'][:1500] for c in comments if c.get('authorUserId') and
            (c.get('createdAt') or '') > proof_created_at and
            c.get('body', '').startswith('[JARVIS OPERATOR QUALITY REVIEW]')][:3]
        if proof['version'] == 3:
            validate_execution_receipt(turn, child, proof)
            reports = [c for c in comments if c.get('authorAgentId') == child['assigneeAgentId']
                and c.get('createdByRunId') == proof['paperclip_run_id'] and 'JARVIS_EXECUTION_EVIDENCE=' in c.get('body', '')]
            entry['worker_summary'] = re.split(r'^(?:JARVIS_EXECUTION_EVIDENCE=|Verified runtime identity:|Verified local_ollama_models data)',
                reports[-1]['body'], maxsplit=1, flags=re.M)[0].strip()[:4000]
            entry['deliverables'] = []
            from . import employee_work
            reports=[a for a in proof.get('artifacts',[]) if a['originalFilename'].endswith(('.md','.txt')) or
                re.fullmatch(r'osint-catalog-v\d+\.json',a['originalFilename'])]
            for artifact in reports[:8]:
                raw = employee_work.attachment_bytes(artifact['id'])
                if hashlib.sha256(raw).hexdigest() != artifact['sha256'] or len(raw) != artifact['byteSize']:
                    raise ValueError('Native deliverable bytes do not match the signed receipt')
                if artifact['originalFilename'].endswith(('.md', '.txt')):
                    entry['deliverables'].append({'id': artifact['id'], 'name': artifact['originalFilename'],
                        'sha256': artifact['sha256'], 'excerpt': raw.decode('utf-8')[:4000]})
        verified.append(entry)
    return verified


def validate_execution_receipt(turn, child, proof):
    employee = reporting.api('GET', '/agents/' + child['assigneeAgentId'])
    meta = (employee.get('metadata') or {}).get('jarvis') or {}
    profile = profile_registry.profile(meta.get('profile'))
    from . import inference_policy
    actual_model = inference_policy.proof_model(proof, employee, profile['model'], os.environ.get('JARVIS_EXECUTION_PROOF_KEY', ''))
    if (proof.get('profile') != profile['id'] or proof.get('profile_sha256') != profile['sha256'] or
            meta.get('profile_sha256') != profile['sha256'] or proof.get('model') != actual_model):
        raise ValueError('Worker proof differs from its registered capability/model')
    successful = [c for c in proof['tool_calls'] if c.get('success') is True and c.get('tool') in profile['tools']]
    acknowledgement = proof.get('task_kind') == 'acknowledgement'
    if acknowledgement:
        from . import acknowledgements
        parent = reporting.api('GET', '/issues/' + turn['issue'])
        if not acknowledgements.assignment(child, parent):
            raise ValueError('A communication acknowledgment cannot complete a substantive work assignment')
        calls = [c for c in proof['tool_calls'] if c.get('success') is True]
        if any(c.get('tool') not in ('agent_identity', 'publish_artifact') for c in calls):
            raise ValueError('Communication proof contains unrelated capability execution')
        ack = proof.get('acknowledgement') or {}
        identity = acknowledgements.observed_identity(calls)
        if identity != ack.get('identity'):
            raise ValueError('Acknowledgment lacks the actual identity tool receipt')
        # A signed historical contact remains valid after an owner renames the same agent.
        registered_names = {employee['name'], *(entry.get('name') for entry in
            ((employee.get('metadata') or {}).get('jarvis') or {}).get('name_history', []) if isinstance(entry, dict))}
        receipt_name = identity.get('name') if isinstance(identity, dict) else None
        error = acknowledgements.identity_error(identity, {'agent': child['assigneeAgentId'],
            'company': turn['company'], 'issue': child['id'], 'run': proof['paperclip_run_id'],
            'profile': profile['id'], 'name': receipt_name if receipt_name in registered_names else employee['name'],
            'role': employee['role']}, ack.get('reply'))
        if error:
            raise ValueError(error)
    if not acknowledgement and not any(c['tool'] not in ('publish_artifact', 'request_action_approval') for c in successful):
        raise ValueError('Worker has no successful capability work tool')
    if profile['id'] == 'software_development' and not acknowledgement:
        terminal = [c for c in successful if c['tool'] == 'terminal' and c.get('result', {}).get('exit_code') == 0]
        if not terminal:
            raise ValueError('Software deliverable lacks real successful terminal execution')
        if re.search(r'\btests?\b|unittest|pytest', child.get('description', ''), re.I) and not any(
            re.search(r'(?:Ran [1-9][0-9]* tests?.*?\bOK\b|[1-9][0-9]* passed)', str(c['result'].get('output', '')), re.S)
            for c in terminal):
            raise ValueError('Software deliverable lacks passing actual test output')
        if 'promptfoo' in child.get('description', '').lower():
            evaluations = proof.get('framework_evaluations', [])
            if not any(e.get('framework') == 'promptfoo' and e.get('successes', 0) > 0 and
                    e.get('failures') == 0 and e.get('errors') == 0 and
                    any(a.get('sha256') == e.get('sha256') and a['originalFilename'].endswith('.json')
                        for a in proof.get('artifacts', [])) for e in evaluations):
                raise ValueError('Software deliverable lacks verified actual Promptfoo result bytes')
    persisted = {a['id']: a for a in reporting.api('GET', '/issues/' + child['id'] + '/attachments')}
    if not proof.get('artifacts') and not acknowledgement:
        raise ValueError('Delegated work lacks native persisted deliverables')
    for artifact in proof['artifacts']:
        native = persisted.get(artifact.get('id'))
        if not native or any(native.get(k) != artifact.get(k) for k in ('sha256', 'byteSize', 'originalFilename')):
            raise ValueError('Worker deliverable differs from the native attachment receipt')
        from . import employee_work
        if (native.get('issueId') != child['id'] or native.get('createdByAgentId') != child['assigneeAgentId'] or
                employee_work.artifact_run_id(native) != proof['paperclip_run_id'] or
                employee_work.artifact_run_id(artifact) != proof['paperclip_run_id']):
            raise ValueError('Worker deliverable authorship/run mismatch')


def _text_excerpt(value, limit):
    """Keep both ends of observed text; never summarize or invent its contents."""
    text = value if isinstance(value, str) else str(value or '')
    if len(text) <= limit:
        return text
    if not limit:
        return ''
    head = limit // 2
    return text[:head] + '\n[... excerpt omitted ...]\n' + text[-(limit - head):]


def review_projection(item, excerpt_chars=1000, output_chars=1600, compact_indexes=False):
    """Compact delivery for model review, after full server-side verification.

    Identity, inventory values and human quality decisions are retained. Large
    OSINT source indexes are summarized after full verification; the original
    signed receipts remain in native records and the in-memory review evidence.
    """
    proof = item['evidence']
    if proof['version'] == 2:
        return item
    tools = []
    for call in proof['tool_calls']:
        observed = call.get('result') or {}
        result = {key: observed[key] for key in ('source', 'exit_code', 'error', 'verified', 'result_truncated')
                  if key in observed}
        if call['tool'] == 'agent_identity':
            result.update({key: observed.get(key) for key in ('agent_id', 'company_id', 'issue_id',
                'paperclip_run_id', 'profile', 'name', 'role')})
        if call['tool'] == 'terminal':
            output = observed.get('output', '')
            result.update(output=_text_excerpt(output, output_chars),
                output_excerpt_truncated=len(output) > output_chars,
                output_chars=len(output))
        tools.append({'tool': call['tool'], 'tool_call_id': call.get('tool_call_id'),
            'success': call['success'], 'result_sha256': call.get('result_sha256'),
            'command_excerpt': _text_excerpt((call.get('args') or {}).get('command'), min(excerpt_chars, 500))
                if call['tool'] == 'terminal' else None,
            'result': result})
    artifacts = [{key: artifact.get(key) for key in ('id', 'issueId', 'originalFilename', 'byteSize',
        'sha256', 'createdByAgentId', 'originatingRunId')} for artifact in proof.get('artifacts', [])]
    source_refs=proof.get('source_refs',[])
    index={}
    if proof.get('osint_catalog') or compact_indexes:
        index={'artifact_count':len(artifacts),'source_reference_count':len(source_refs),
            'tool_call_count':len(tools),
            'full_artifact_index_sha256':hashlib.sha256(json.dumps(artifacts,sort_keys=True).encode()).hexdigest(),
            'full_source_index_sha256':hashlib.sha256(json.dumps(source_refs,sort_keys=True).encode()).hexdigest(),
            'full_tool_index_sha256':hashlib.sha256(json.dumps(proof['tool_calls'],sort_keys=True).encode()).hexdigest(),
            'source_indexes_compacted':True}
        artifacts=[a for a in artifacts if not a['originalFilename'].startswith(('osint-source-','osint-discovery-','research-sources-'))]
        source_refs=[{k:s.get(k) for k in ('framework','source_url','sha256','snapshot_artifact_id',
            'blob_sha','code_components')} for s in source_refs[:8]]
        if compact_indexes:
            index['structured_indexes_compacted']=True
            artifacts=[{k:a.get(k) for k in ('id','originalFilename','byteSize','sha256')} for a in artifacts]
            for source in source_refs:
                components=source.get('code_components') or []
                if len(components)>8:
                    source['code_component_count']=len(components)
                    source['code_components']=components[:8]
                    source['code_components_truncated']=True
            outcomes={}
            for tool in tools:
                counts=outcomes.setdefault(tool['tool'],{'successful':0,'failed':0})
                counts['successful' if tool['success'] else 'failed']+=1
            index['tool_outcomes']=outcomes
        if compact_indexes or len(tools)>12:
            identity=next((t for t in tools if t['tool']=='agent_identity'),None)
            if compact_indexes:
                # Retain every tool kind and failure, plus the latest test/fixture
                # executions, instead of a long series of repeated file writes.
                latest={t['tool']:t for t in tools if t['success']}
                retained={id(t) for t in tools if not t['success'] or t is identity}
                retained.update(id(t) for t in latest.values())
                retained.update(id(t) for t in [t for t in tools if t['success'] and t['tool']=='terminal'][-2:])
                tools=[t for t in tools if id(t) in retained]
                index['tool_calls_sampled']=len(tools)<index['tool_call_count']
            else:tools=([identity] if identity else [])+[t for t in tools if t['tool']!='agent_identity'][-10:]
    return {'issue_id': item['issue_id'], 'identifier': item['identifier'],
        'worker_summary': _text_excerpt(item.get('worker_summary'), excerpt_chars),
        'worker_summary_excerpt_truncated': len(item.get('worker_summary') or '') > excerpt_chars,
        'operator_review_notes': item.get('operator_review_notes', []),
        'deliverables': [{key: value for key, value in artifact.items() if key != 'excerpt'} |
            {'excerpt': _text_excerpt(artifact.get('excerpt'), excerpt_chars),
             'excerpt_truncated': len(artifact.get('excerpt') or '') > excerpt_chars}
            for artifact in item.get('deliverables', [])],
        'verified_receipt_projection': {'note': 'Full signed receipt was verified server-side; this projection is not a signed proof. '
                'Text excerpts may omit facts. Use paperclip_ceo action=review for original verified receipts and report excerpts; '
                'full report/source bytes remain in the referenced native artifacts.',
            'receipt_sha256': hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            **{k: proof.get(k) for k in ('version', 'kind', 'task_status', 'company_id', 'issue_id', 'agent_id',
                'paperclip_run_id', 'session_id', 'model', 'profile', 'profile_sha256', 'signature', 'source_refs', 'framework_evaluations', 'task_kind','osint_catalog')},
            **index,'source_refs':source_refs,
            'inventory': [{k: model.get(k) for k in ('name', 'size_bytes', 'size_gib')} for model in proof.get('inventory', [])],
            'artifacts': artifacts, 'tools': tools}}


def bounded_context_text(snapshot, verified):
    """Fit text excerpts to the preflight budget without weakening verification.

    Retain irreducible structured evidence and quality notes or fail closed.
    Compact JSON also avoids spending the bound on repeated indentation.
    """
    prefix = 'Authenticated current Paperclip state (runtime preflight, not a model tool call):\n'
    for excerpt_chars, output_chars, compact_indexes in (
            (1000,1600,False),(600,900,False),(300,450,False),(0,0,False),
            (600,900,True),(300,450,True),(200,300,True),(100,180,True),(0,0,True)):
        if verified:
            snapshot['verified_child_results'] = [review_projection(item, excerpt_chars, output_chars, compact_indexes) for item in verified]
        candidate=snapshot
        if compact_indexes and snapshot.get('latest_user_request') and (snapshot.get('objective') or {}).get('description')==snapshot['latest_user_request']:
            # Initial objectives repeat the same human text in two fields.
            # Reference its complete copy rather than spending the budget twice.
            candidate={**snapshot,'objective':{**snapshot['objective'],
                'description':'Identical to latest_user_request below.',
                'description_same_as_latest_user_request':True}}
        if compact_indexes and verified:
            # Completed-work review needs role identity and authority. Repeated
            # role descriptions and earlier CEO planning prose add no new facts.
            updates=snapshot.get('recent_updates',[])
            candidate={**candidate,
                'employees':[{k:v for k,v in employee.items() if k!='capabilities'} for employee in snapshot.get('employees',[])],
                'capability_profiles':[{k:v for k,v in profile.items() if k!='capabilities'} for profile in snapshot.get('capability_profiles',[])],
                'recent_updates':[update for update in updates if not update.get('authorAgentId')],
                'historical_agent_updates_omitted':sum(bool(update.get('authorAgentId')) for update in updates)}
        text = prefix + json.dumps(candidate, separators=(',', ':'))
        if len(text) <= 32000:
            return text
    knowledge=snapshot.get('shared_knowledge') or {}
    if knowledge.get('entries'):
        reduced={**snapshot,'shared_knowledge':{**knowledge,'entries':[],'entries_omitted_for_context_budget':True}}
        return bounded_context_text(reduced,verified)
    raise ValueError('Verified CEO context exceeds its bounded payload limit')


def manage(args, **kwargs):
    turn, me, issue = scope()
    action = args.get('action')
    if action == 'ask_owner':
        child = next((i for i in children(turn) if i['id'] == args.get('child_id') and i['status'] in ('blocked', 'done')), None)
        if not child or child.get('assigneeAgentId') not in {a['id'] for a in employees(turn)}:
            raise PermissionError('Owner decisions must concern an existing report on this objective.')
        decision = blocker_review.ask(reporting.api, turn, issue, child, str(args.get('text') or '').strip(),
                                     str(args.get('plan') or '').strip())
        return audit(turn, action, {'interaction_id': decision['id'], 'question': decision['question']})
    if action == 'request_correction':
        child_id = str(UUID(str(args.get('child_id', ''))))
        known = next((child for child in children(turn) if child['id'] == child_id), None)
        if not known:
            raise PermissionError('Correction must belong to this current objective/project')
        child = reporting.api('GET', '/issues/' + child_id)
        if (child.get('companyId') != turn['company'] or child.get('projectId') != turn['project'] or child.get('parentId') != turn['issue']):
            raise PermissionError('Correction target changed scope')
        if child.get('executionRunId') or child.get('executionBlocker') or child['status'] not in ('done', 'blocked'):
            raise ValueError('Do not interrupt active work or bypass a native execution reconciliation hold')
        text = str(args.get('text', '')).strip()
        if not 30 <= len(text) <= 1500:
            raise ValueError('Supply concrete factual/test correction feedback (30–1500 characters)')
        review_marker = ''
        if child['status'] == 'blocked' and (turn.get('inference_configuration') or {}).get('version') == 3:
            if (turn.get('owner_question') or {}).get('child_id') == child_id:
                raise ValueError('The project owner has a pending question for this child.')
            # Paperclip enforces stop holds and resume authority on this mutation.
            # Inspecting tree-holds requires board credentials.
            cause = (child.get('unblockDescriptor') or {}).get('action') or ''
            answer = next((d['id'] for d in turn.get('owner_decisions', []) if d['child_id'] == child_id and d['answer']), '')
            revision = hashlib.sha256((cause.strip().casefold() + answer).encode()).hexdigest()[:20]
            review_marker = '[JARVIS BLOCKER REVIEW ' + revision + ']'
            history = reporting.api('GET', '/issues/' + child_id + '/comments')
            if any(c.get('authorAgentId') == turn['agent'] and review_marker in (c.get('body') or '') for c in history):
                raise ValueError('The same correction cycle returned this blocker. Review the result and ask the owner for the missing input.')

        marker = '[JARVIS CEO CORRECTION ' + hashlib.sha256(text.encode()).hexdigest()[:16] + ']'
        if marker in (child.get('description') or ''):
            raise ValueError('This correction was already requested; review the new evidence before repeating it')
        dependencies = [str(UUID(value)) for value in args.get('depends_on', [])]
        related = children(turn)
        if len(dependencies) > 5 or len(set(dependencies)) != len(dependencies) or any(
                value == child_id or value not in {c['id'] for c in related} for value in dependencies):
            raise PermissionError('Correction dependencies must be distinct other children of this objective')
        employee = next((a for a in employees(turn) if a['id'] == child['assigneeAgentId']), None)
        if not employee:
            raise PermissionError('Correction employee is no longer an existing direct report')
        if not dependencies:
            dependencies = [item['id'] for item in child.get('blockedBy') or []]
        check_research_dependency(turn, employee, related, dependencies)
        revised = reporting.api('PATCH', '/issues/' + child_id,
            {'description': (child.get('description') or '')[:6000] + '\n\n' + marker + '\n' + text,
             'status': 'todo', 'unblockDescriptor': None, 'comment': marker + '\nCEO review feedback: ' + text + ('\n' + review_marker if review_marker else ''),
             **({'blockedByIssueIds': dependencies} if dependencies else {})}, turn['run'])
        return audit(turn, action, {'child_id': child_id, 'identifier': revised['identifier'], 'status': revised['status'],
            'next': 'End with the actual waiting state. Paperclip owns the correction assignment and continuation; do not poll or create duplicate work.'})
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
        dependencies = [str(UUID(value)) for value in args.get('depends_on', [])]
        related = {child['id']: child for child in children(turn)}
        if len(dependencies) > 5 or len(set(dependencies)) != len(dependencies) or any(value not in related for value in dependencies):
            raise PermissionError('Dependencies must be distinct existing children of this same objective/project')
        if any(related[value].get('assigneeAgentId') == agent_id for value in dependencies):
            raise ValueError('Do not create a same-employee dependency cycle')
        check_research_dependency(turn, employee, list(related.values()), dependencies)
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
        if (turn.get('inference_configuration') or {}).get('version') == 3:
            cycle = turn.get('conversation_request_id', 'initial')
            key += ':' + cycle
            text = '[JARVIS REQUEST ' + cycle + ']\n' + text
        child = reporting.api('POST', '/companies/' + turn['company'] + '/issues',
                    {'title': title[:120], 'description': text, 'parentId': turn['issue'],
                     'projectId': turn['project'], 'goalId': issue.get('goalId'), 'status': 'todo',
                     'assigneeAgentId': agent_id, 'priority': 'medium', 'idempotencyKey': key,
                     'workspaceSelection': {'kind': 'task_directory'},
                     'allowDuplicate': True, **({'blockedByIssueIds': dependencies} if dependencies else {})}, turn['run'])
        if (child.get('parentId') != turn['issue'] or child.get('projectId') != turn['project']
                or child.get('assigneeAgentId') != agent_id or child.get('description') != text):
            raise ValueError('This employee already has a differently scoped child; review it before requesting more work')
        reporting.api('PATCH', '/issues/' + turn['issue'],
                      {'comment': 'CEO delegated ' + child['identifier'] + ' to ' + employee['name'] +
                       '. Scoped responsibility: ' + text}, turn['run'])
        return audit(turn, action, {'child_id': child['id'], 'identifier': child['identifier'],
                    'assigned_to': employee['name'], 'status': child['status'],
                    'depends_on': dependencies,
                    'next': 'Create any remaining minimum-team child from your plan now, using depends_on for prerequisites. '
                            'Then end with a short waiting update. Paperclip owns execution, dependency release and the CEO completion wake. Do not poll or hire redundantly.'})
    if action == 'review':
        items = children(turn)
        if not items:
            raise ValueError('There are no delegated results to review')
        blocked = [c for c in items if c['status'] == 'blocked' and (not args.get('child_id') or c['id'] == args['child_id'])]
        if blocked:
            return audit(turn, action, {'diagnostics': [{'child_id': c['id'], 'identifier': c['identifier'],
                'blocker': (c.get('unblockDescriptor') or {}).get('action'),
                'partial_reports': blocker_review.partial_reports(reporting, turn, c)} for c in blocked[:5]],
                'next': 'These are partial results. Send an executable correction or ask the owner for the missing decision.'})
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
        portrait = profile_registry.hire_portrait(turn['issue'] + ':' + name, args.get('portrait'), employees(turn))
        # A candidate is inert until a human approves AND provisions its isolated runtime.
        hired = reporting.api('POST', '/companies/' + turn['company'] + '/agent-hires',
                    {'name': name[:80], 'role': 'general', 'title': name[:80], 'reportsTo': me['id'],
                     'capabilities': reason[:2000], 'metadata': {'jarvis': {'portrait_id': portrait}}, 'adapterType': 'hermes_gateway',
                     'adapterConfig': {}, 'runtimeConfig': {'heartbeat': {'enabled': False}},
                     'sourceIssueId': turn['issue']}, turn['run'])
        approval = hired.get('approval') or {}
        turn['hiring_approval'] = approval.get('id')
        turn['hiring_approval_status'] = approval.get('status', 'pending')
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
    # Native roster/approvals remain the only durable source. Check across runs,
    # complementing Paperclip's own per-run hire fingerprint idempotency.
    all_agents = reporting.api('GET', '/companies/' + turn['company'] + '/agents')
    body = profile_registry.hire_body(turn, me, selected['id'], name, reason, args.get('portrait'), all_agents)
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
        turn['hiring_approval_status'] = approval.get('status', 'pending')
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
    turn['hiring_approval_status'] = approval['status']
    return emit({'hire_created': True, 'profile': selected['id'],
        'agent_id': (hired.get('agent') or {}).get('id'), 'approval_id': approval['id'],
        'approval_status': approval['status'], 'authority': selected['authority'],
        'next': 'End this turn and report the pending human approval. No tools or runtime are granted before approval. Paperclip will deliver the decision.'})


def required_work_tools(turn):
    return ({'research_sources'} if turn.get('needs_research') else set()) | (
        {'terminal'} if turn.get('needs_test_execution') else set())


def finalize(turn, completed=False, failed=False, interrupted=False, turn_exit_reason=''):
    items = children(turn)
    success = completed and not failed and not interrupted and bool(turn['response'].strip())
    models = turn.get('inventory', [])
    if turn.get('child_evidence'):
        models = [m for child in turn['child_evidence'] for m in child['evidence'].get('models', child['evidence'].get('inventory', []))]
    names = {m['name'] for m in models if isinstance(m, dict) and isinstance(m.get('name'), str)}
    missing_report = turn.get('needs_inventory') and bool(names) and (
        sum(name in turn['response'] for name in names) < min(2, len(names)))
    governed_decision = turn.get('action_approval') or (turn.get('plan_decision') == 'hire' and turn.get('hiring_approval'))
    turn['completion_blocker'] = blocker_review.objective_blocker(turn['response']) if success and not governed_decision else None
    if success and not turn.get('owner_question') and (turn.get('inference_configuration') or {}).get('version') == 3:
        unresolved = next((c for c in items if c['status'] == 'blocked' and c['id'] in turn.get('inspected_blockers', ())), None)
        if unresolved is None and turn['completion_blocker']:
            unresolved = next((c for c in items if c['status'] == 'done'), None)
        if unresolved and not turn.get('action_approval') and unresolved.get('assigneeAgentId') in {a['id'] for a in employees(turn)}:
            issue = reporting.api('GET', '/issues/' + turn['issue'])
            if issue.get('executionRunId') == turn['run'] and issue.get('assigneeAgentId') == turn['agent']:
                question, reason = blocker_review.disposition(turn['response'], unresolved, turn['completion_blocker'])
                blocker_review.ask(reporting.api, turn, issue, unresolved, question, reason)
    status, comment = 'blocked', turn['response']
    if not success:
        comment = 'CEO runtime failed or was interrupted. ' + str(turn_exit_reason)
    elif turn.get('action_approval'):
        approval = turn['action_approval']
        status = 'in_review' if approval['status'] in ('pending', 'revision_requested') else 'blocked'
        comment = ('Sensitive-action approval ' + approval['id'] + ' is ' + approval['status'] +
            '. No sensitive action was executed; runtime authority remains unchanged.\n\n' + comment)
    elif turn.get('owner_question') and (turn['completion_blocker'] or any(i['id'] == turn['owner_question']['child_id'] and i['status'] == 'blocked' for i in items)):
        comment = blocker_review.WAITING + turn['owner_question']['question']
    elif turn['completion_blocker']:
        comment = turn['completion_blocker']
    elif not turn.get('plan_decision'):
        comment = 'CEO verification blocked: no plan/assignment decision was recorded in Paperclip.\n\n' + comment
    elif any(i['status'] in ('blocked', 'cancelled') for i in items):
        comment = 'CEO has unresolved or cancelled worker tasks; objective is not complete.\n\n' + comment
    elif items and any(i['status'] != 'done' for i in items):
        status = 'blocked'
        comment = '[JARVIS CEO WAITING]\nDelegated work remains active. Paperclip will wake the CEO when all children complete.\n\n' + comment
    elif turn.get('plan_decision') == 'hire' and turn.get('hiring_approval'):
        decision = turn.get('hiring_approval_status', 'pending')
        status = 'in_review' if decision in ('pending', 'revision_requested') else 'blocked'
        comment = 'Human hiring approval ' + turn['hiring_approval'] + ' is ' + decision + '. '
        comment += ('Await a real human decision; no employee execution is authorized.\n\n' if status == 'in_review' else
                    'Respect this decision; do not create a replacement hire automatically.\n\n') + turn['response']
    elif re.match(r"^(?:wait(?:ing)?\b|awaiting\b|pending\b|please\s+wait\b|i(?:'m| am)\s+waiting\b)",
                  re.sub(r'^[\s#>*_`-]+', '', turn['response']).lower()):
        comment = 'CEO report incomplete: the response says it is waiting despite having no pending worker execution.\n\n' + comment
    elif missing_report:
        comment = 'CEO report incomplete: the final prose does not identify the retrieved models.\n\n' + comment
    elif not items and turn.get('company_operation_verified'):
        status = 'done'
    elif not items and turn.get('needs_research') and not turn.get('source_refs'):
        comment = 'CEO verification blocked: the assigned research has no retrieved primary sources or executed worker task.\n\n' + comment
    elif not items and turn.get('needs_test_execution'):
        comment = 'CEO verification blocked: no actual isolated test execution was recorded for the assigned objective.\n\n' + comment
    elif items:
        if (set(turn.get('reviewed_children', [])) == {i['id'] for i in items} or
                (set(turn.get('delivered_children', [])) == {i['id'] for i in items} and
                 turn.get('delivery_run_id') == turn['run'] and turn.get('delivery_context_sha256'))):
            # Re-read canonical evidence before accepting final CEO completion.
            verified = verified_children(turn, items)
            incomplete=[v['identifier'] for v in verified if v['evidence'].get('osint_catalog') and not v['evidence']['osint_catalog'].get('coverage_met')]
            if incomplete:
                reporting.api('PATCH','/issues/'+turn['issue'],{'status':'blocked',
                    'comment':'OSINT coverage remains incomplete in '+', '.join(incomplete)+'.\n\n'+comment,
                    'unblockDescriptor':{'owner':{'agentId':turn['agent']},'action':'Complete the documented source and catalog coverage gaps.'}},turn['run'])
                return
            rejected = [item['identifier'] for item in verified if item.get('operator_review_notes')]
            if rejected:
                reporting.api('PATCH', '/issues/' + turn['issue'], {'status': 'blocked',
                    'comment': 'CEO verification blocked: unresolved native human quality review for ' + ', '.join(rejected) + '.\n\n' + comment,
                    'unblockDescriptor': {'owner': {'agentId': turn['agent']},
                        'action': 'Review the native quality notes and request a correction on each existing child.'}}, turn['run'])
                return
            observed = {tool.get('tool') for child in verified for tool in child['evidence'].get('tool_calls', [])
                if tool.get('success')}
            missing_work = required_work_tools(turn) - observed
            if missing_work:
                # Failed capability coverage remains a native blocker. No new
                # assignment, retry or execution is created by this validator.
                payload = {'status': 'blocked', 'comment': 'CEO verification blocked: required actual work is missing: ' +
                    ', '.join(sorted(missing_work)) + '.\n\n' + comment,
                    'unblockDescriptor': {'owner': {'agentId': turn['agent']},
                        'action': 'Review the missing work and complete the necessary scoped Paperclip assignments.'}}
                reporting.api('PATCH', '/issues/' + turn['issue'], payload, turn['run'])
                return
            corrections = dependency_corrections(turn, verified)
            if corrections:
                reporting.api('PATCH', '/issues/' + turn['issue'], {'status': 'blocked',
                    'comment': 'CEO verification blocked: native dependency corrections are required.\n' + json.dumps(corrections) + '\n\n' + comment,
                    'unblockDescriptor': {'owner': {'agentId': turn['agent']},
                        'action': 'Correct the existing implementation child with its actual research dependency and verify its rerun.'}}, turn['run'])
                return
            if turn.get('needs_report') and any(child['evidence']['version'] == 3 for child in verified) and not any(
                    artifact['originalFilename'].endswith('.md') for artifact in turn.get('artifacts', {}).values()):
                from . import employee_work
                sources = {source['framework']: source for child in verified for source in child['evidence'].get('source_refs', [])}
                try:
                    employee_work.deliver_report(turn, list(sources.values()))
                except (ValueError, PermissionError):
                    pass  # Missing/invalid deliverables below keep the objective blocked.
            if turn.get('needs_report') and any(child['evidence']['version'] == 3 for child in verified) and not any(
                    artifact['originalFilename'].endswith('.md') for artifact in turn.get('artifacts', {}).values()):
                comment = 'CEO report is not persisted: call publish_artifact with the consolidated Markdown report before completion.\n\n' + comment
            else:
                # The signed records and attachments are available on each native child.
                status = 'done'
        else:
            comment = 'CEO review or authenticated result delivery is required before objective completion.\n\n' + comment
    elif turn.get('plan_decision') == 'self' and (not turn['needs_inventory'] or turn['inventory_verified']):
        status = 'done'
        if turn.get('inventory') is not None and turn.get('inventory_journaled') != reporting.inventory_fingerprint(turn['inventory']):
            comment += '\n\nVerified local_ollama_models data:\n```json\n' + json.dumps(turn['inventory'], indent=2) + '\n```'
    else:
        comment = 'CEO has not completed the planned execution or is awaiting human approval.\n\n' + comment
    payload = {'status': status, 'comment': comment}
    if status=='done':payload['unblockDescriptor']=None
    if status == 'blocked':
        action = 'Review the CEO/worker execution, request any required operator decision, then explicitly retry this task.'
        if comment.startswith(blocker_review.WAITING):
            action = comment
        elif comment.startswith('[JARVIS CEO WAITING]'):
            action = 'Await completion of ' + ', '.join(i['identifier'] for i in items) + '; Paperclip will wake this CEO to review their execution evidence and consolidate the result.'
        payload['unblockDescriptor'] = {'owner': {'agentId': turn['agent']}, 'action': action}
    reporting.api('PATCH', '/issues/' + turn['issue'], payload, turn['run'])
    context=turn.get('work_scope') or {}
    if status=='done' and context.get('kind')=='project' and context.get('mission_id')==turn['issue']:
        from . import work_scope
        for routine in reporting.api('GET','/companies/'+turn['company']+'/routines'):
            scoped=work_scope.routine_scope(routine)
            if routine.get('companyId')==turn['company'] and routine.get('assigneeAgentId')==turn['agent'] and routine.get('status')=='active' and scoped['kind']=='project' and scoped['mission_id']==turn['issue']:
                reporting.api('PATCH','/routines/'+routine['id'],{'status':'paused'})


def register(ctx):
    # Hermes pre_verify only runs after code edits; the CEO has no code-edit
    # tools. Finalization below remains the fail-closed completion validator.
    from . import employee_work
    employee_work.register(ctx, ceo=True)
    def request_employee(args, **kwargs):
        turn, me, _ = scope()
        return request_profile_hire(turn, me, {'profile': args['profile'], 'title': args['name'],
            'text': args['reason'], 'portrait': args.get('portrait')}, tool_name='request_employee')

    portrait_field = {'type': 'string', 'enum': list(profile_registry.HIRE_PORTRAITS),
                      'description': 'Optional helmet portrait for this employee. Omit to assign from the least-used designs.'}

    ctx.register_tool(name='request_employee', toolset='jarvis_ceo', schema={
        'name': 'request_employee',
        'description': 'Create a REAL native Paperclip employee-hire approval for an essential missing capability. Use this tool, not a textual request, when no existing employee covers the required capability. The employee remains inert until a human approves. Do not use for capabilities already present.',
        'parameters': {'type': 'object', 'properties': {
            'profile': {'type': 'string', 'enum': list(profile_registry.catalog()['profiles'])},
            'name': {'type': 'string'},
            'portrait': portrait_field,
            'reason': {'type': 'string', 'description': 'Why existing employees cannot provide this essential capability; at least 40 characters.'}},
            'required': ['profile', 'name', 'reason'], 'additionalProperties': False}}, handler=request_employee)
    ctx.register_tool(name='paperclip_context', toolset='jarvis_ceo',
        schema={'name': 'paperclip_context', 'description': 'Read your actual assigned Paperclip objective, company goals, existing employees and child task states. Authenticated current context is automatically supplied; call for additional reads.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, handler=context)
    ctx.register_tool(name='paperclip_ceo', toolset='jarvis_ceo',
        schema={'name': 'paperclip_ceo', 'description': 'Persistent Paperclip CEO operations. A blocked direct report needs request_correction(child_id, text) for an executable fix or ask_owner(child_id, plan=reason, text=question) for a human decision. Simple work uses your own local_ollama_models call, which records self scope before reading. Delegation: action=delegate, exact employee agent_id, title, text=scoped work and acceptance criteria; records a plan before the child. Optional plan adds rationale. Create ALL necessary minimum-team children before ending the turn; depends_on binds prerequisite child UUIDs. Review verified completed-child results and consolidate. Essential missing capability: action=request_hire, profile=one registered capability profile ID, title=employee name, text=concrete unmet capability justification (at least 40 characters). That call records your hiring rationale and requests HUMAN approval. It never provisions before approval and refuses a duplicate suitable employee. A separate plan is optional for profile-based hiring.',
                'parameters': {'type': 'object', 'properties': {
                    'action': {'type': 'string', 'enum': ['plan', 'delegate', 'review', 'request_hire', 'request_correction', 'ask_owner']},
                    'decision': {'type': 'string', 'enum': ['self', 'delegate', 'hire']},
                    'text': {'type': 'string'}, 'plan': {'type': 'string'}, 'agent_id': {'type': 'string'}, 'title': {'type': 'string'},
                    'child_id': {'type': 'string', 'format': 'uuid'},
                    'profile': {'type': 'string', 'enum': list(profile_registry.catalog()['profiles'])}, 'portrait': portrait_field,
                    'depends_on': {'type': 'array', 'items': {'type': 'string', 'format': 'uuid'}, 'maxItems': 5,
                        'description': 'Actual prerequisite child UUIDs as a structured argument. Never put depends_on placeholders in the task description. Also supported when correcting an existing child.'}},
                    'required': ['action'], 'additionalProperties': False}}, handler=manage)
