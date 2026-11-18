"""Supported Hermes lifecycle hooks report ONLY the current assigned Paperclip issue.

No task scheduling or task store. Paperclip remains authoritative. Credentials and
destinations are fixed server-side; ordinary Hermes chat never enters this path.
"""
import threading
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.request

_turns = {}
_lock = threading.Lock()
_request_budget = threading.local()
_logger = logging.getLogger(__name__)
_scope = re.compile(r'^paperclip:company:([0-9a-f-]{36}):agent:([0-9a-f-]{36}):issue:([0-9a-f-]{36})$')


def current_turn():
    """Tools are bound to one admitted runtime turn, never a model-supplied ID."""
    with _lock:
        turns = list(_turns.values())
    if len(turns) != 1:
        raise ValueError('Exactly one authenticated Paperclip turn is required')
    return turns[0]


def sign_evidence(proof):
    key = os.environ.get('JARVIS_EXECUTION_PROOF_KEY', '')
    if proof.get('version') == 3:
        agent = str(proof.get('agent_id', ''))
        if not re.fullmatch(r'[0-9a-f-]{36}', agent):
            raise ValueError('A native employee ID is required for version 3 evidence')
        if key:
            key = hmac.new(key.encode(), ('jarvis-employee-proof-v3:' + agent).encode(), hashlib.sha256).hexdigest()
        else:
            if agent != os.environ.get('JARVIS_PAPERCLIP_AGENT_ID'):
                raise PermissionError('This runtime cannot sign another employee identity')
            key = os.environ.get('JARVIS_AGENT_PROOF_KEY', '')
    if not key:
        raise ValueError('Execution proof signing is not configured')
    encoded = json.dumps(proof, sort_keys=True, separators=(',', ':')).encode()
    return {**proof, 'signature': hmac.new(key.encode(), encoded, hashlib.sha256).hexdigest()}


def authentic_evidence(proof):
    if not isinstance(proof, dict) or proof.get('version') not in (2, 3):
        return False
    unsigned = {k: v for k, v in proof.items() if k != 'signature'}
    try:
        expected = sign_evidence(unsigned)['signature']
    except (ValueError, PermissionError):
        return False
    return hmac.compare_digest(str(proof.get('signature', '')), expected)


def check_budget(deadline=None):
    deadline = deadline if deadline is not None else getattr(_request_budget, 'deadline', None)
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Authenticated CEO preflight exceeded its time budget')
    return remaining


def api(method, path, body=None, run_id=None):
    headers = {'Authorization': 'Bearer ' + os.environ['HERMES_PAPERCLIP_AGENT_KEY'],
               'Content-Type': 'application/json'}
    if run_id:
        headers['X-Paperclip-Run-Id'] = run_id
    request = urllib.request.Request('http://paperclip:3100/api' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method=method)
    remaining = check_budget()
    with urllib.request.urlopen(request, timeout=min(8, remaining) if remaining is not None else 8) as response:
        data = json.load(response)
    check_budget()
    return data


def begin(session_id='', turn_id='', **kwargs):
    key = (session_id, turn_id)
    with _lock:
        _turns.pop(key, None)
    match = _scope.fullmatch(session_id)
    if not match:
        return
    company, agent, issue_id = match.groups()
    ceo = os.environ.get('JARVIS_AGENT_ROLE') == 'ceo'
    previous_deadline = getattr(_request_budget, 'deadline', None)
    deadline = time.monotonic() + 20 if ceo else None
    if ceo:
        _request_budget.deadline = deadline
    turn = None
    try:
        me = api('GET', '/agents/me')
        check_budget(deadline)
        if me['id'] != agent or me['companyId'] != company:
            raise ValueError('Session does not belong to this agent')
        if ceo and (me.get('role') != 'ceo' or agent != os.environ.get('JARVIS_PAPERCLIP_AGENT_ID')):
            raise ValueError('CEO runtime identity mismatch')
        issue = api('GET', '/issues/' + issue_id)
        check_budget(deadline)
        if issue['assigneeAgentId'] != agent or issue['companyId'] != company:
            raise ValueError('Issue is not assigned to this agent')
        run_id = issue.get('executionRunId')
        if not run_id:
            raise ValueError('No active Paperclip execution owns this issue')
        checked_out = api('POST', '/issues/' + issue_id + '/checkout',
            {'agentId': agent, 'expectedStatuses': ['todo', 'backlog', 'blocked', 'in_progress', 'in_review']}, run_id)
        check_budget(deadline)
        if isinstance(checked_out, dict) and checked_out.get('id') == issue_id:
            issue = {**issue, **checked_out}
        decision, comments = None, None
        if ceo:
            comments = sorted(api('GET', '/issues/' + issue_id + '/comments'), key=lambda c: c.get('createdAt') or '')
            check_budget(deadline)
            for comment in comments:
                marker = re.match(r'^\[JARVIS CEO PLAN decision=(self|delegate|hire)\]', comment.get('body', ''))
                if marker and comment.get('authorAgentId') == agent:
                    decision = marker.group(1)
        description = (issue.get('description') or '').lower()
        turn = {'session': session_id, 'issue': issue_id, 'run': run_id, 'response': '',
            'agent': agent, 'company': company, 'project': issue.get('projectId'),
            'ceo': ceo, 'reports_to': me.get('reportsTo'), 'plan_decision': decision, 'reviewed_children': [],
            'needs_inventory': ('ollama' in description and 'model' in description) or 'installed models' in description,
            'inventory_verified': False, 'started_at': time.time()}
        if ceo:
            turn['needs_report'] = bool(re.search(r'\breport\b', description))
        if ceo or os.environ.get('JARVIS_PROFILE'):
            from . import inference_policy, profile_registry
            base_model = profile_registry.profile(os.environ['JARVIS_PROFILE'])['model'] if os.environ.get('JARVIS_PROFILE') else profile_registry.catalog()['model']
            turn['runtime_model'], turn['inference_configuration'] = inference_policy.runtime_selection(me, base_model)
            if ceo and (turn.get('inference_configuration') or {}).get('version') == 3:
                human = [c for c in comments or [] if c.get('authorUserId') and
                    re.match(r'^\[JARVIS USER MESSAGE request_id=[a-f0-9-]{36}\]\n', c.get('body', ''))]
                from . import blocker_review
                records = api('GET', '/companies/' + company + '/issues')
                latest = blocker_review.wake_request(api, turn, comments or [], human, records)
                turn['conversation_request_id'] = latest['id'] if latest else 'initial'
                turn['latest_user_request'] = latest['body'].split('\n', 1)[1] if latest else issue.get('description', '')
                effective = turn['latest_user_request'].lower()
                turn['needs_inventory'] = ('ollama' in effective and 'model' in effective) or 'installed models' in effective
                turn['needs_report'] = bool(re.search(r'\breport\b', effective))
                turn['needs_research'] = bool((re.search(r'\bresearch\b', effective) and re.search(r'\bframeworks?\b', effective)) or
                    ('osint' in effective and re.search(r'research|catalog|knowledge',effective)))
                turn['needs_test_execution'] = bool(re.search(r'\b(?:execute|run)\s+(?:\w+\s+){0,3}tests?\b', effective))
                if latest and not any(c.get('authorAgentId') == agent and
                        c.get('createdAt', '') > latest.get('createdAt', '') and
                        c.get('body', '').startswith('[JARVIS CEO PLAN') for c in comments):
                    turn['plan_decision'] = None
        if os.environ.get('JARVIS_PROFILE'):
            turn['needs_tests'] = bool(re.search(r'\btests?\b|unittest|pytest', description))
        with _lock:
            _turns[key] = turn
        if ceo:
            from . import ceo_tools
            context = ceo_tools.prepare_turn_context(turn, issue=issue, comments=comments, deadline=deadline)
            check_budget(deadline)
            return {'context': context}
        if os.environ.get('JARVIS_PROFILE'):
            from . import employee_tools
            updates = api('GET', '/issues/' + issue_id + '/comments')
            turn['operator_updates'] = [{k: comment.get(k) for k in ('createdAt', 'body')} for comment in
                sorted(updates, key=lambda c: c.get('createdAt') or '') if comment.get('authorUserId')][-3:]
            for update in turn['operator_updates']:
                update['body'] = str(update.get('body') or '')[:1200]
            return {'context': employee_tools.prepare_turn_context(turn, issue)}
    except Exception as exc:
        if turn is not None:
            for name in ('delivered_children', 'delivery_run_id', 'delivery_context_sha256', 'child_evidence'):
                turn.pop(name, None)
        with _lock:
            _turns.pop(key, None)
        return {'action': 'block', 'message': 'Paperclip authenticated turn preflight failed: ' + type(exc).__name__}
    finally:
        if ceo:
            if previous_deadline is None:
                try:
                    del _request_budget.deadline
                except AttributeError:
                    pass
            else:
                _request_budget.deadline = previous_deadline


def response(session_id='', turn_id='', assistant_response='', **kwargs):
    with _lock:
        turn = _turns.get((session_id, turn_id))
    if turn and turn['session'] == session_id:
        turn['response'] = assistant_response


def tool_result(tool_name='', result='', task_id='', turn_id='', **kwargs):
    if tool_name != 'local_ollama_models':
        return
    try:
        data = json.loads(result) if isinstance(result, str) else result
        if (not isinstance(data, dict) or data.get('source') != 'Ollama /api/tags' or
                data.get('error') or data.get('isError') or not isinstance(data.get('models'), list) or
                any(not isinstance(m, dict) or not isinstance(m.get('name'), str) or not m['name'].strip() or
                    type(m.get('size_bytes')) is not int or m['size_bytes'] < 0 for m in data['models'])):
            return
        with _lock:
            turn = _turns.get((task_id, turn_id))
            match = _scope.fullmatch(task_id)
            if (not turn or turn.get('session') != task_id or not match or
                    match.groups() != (turn.get('company'), turn.get('agent'), turn.get('issue'))):
                return
            turn['inventory_verified'] = True
            turn['inventory'] = data['models']
        from hermes_constants import get_hermes_home
        record = {'timestamp': time.time(), 'issue_id': turn['issue'], 'paperclip_run_id': turn['run'],
                  'session_id': task_id, 'tool': tool_name, 'result': data}
        log = get_hermes_home() / 'logs' / 'paperclip-tools.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        if turn.get('ceo') and os.environ.get('JARVIS_AGENT_ROLE') == 'ceo':
            journal_ceo_inventory(turn, data['models'])
    except (ValueError, AttributeError):
        return


def journal_ceo_inventory(turn, models):
    """Publish observed progress; never schedule work or alter task status."""
    fingerprint = hashlib.sha256(json.dumps(models, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with _lock:
        attempted = turn.setdefault('inventory_journal_attempted', set())
        if fingerprint in attempted:
            return
        # A timed-out PATCH may already have committed. Do not retry this
        # same-turn observation automatically and risk duplicate comments.
        attempted.add(fingerprint)
    try:
        if turn.get('agent') != os.environ.get('JARVIS_PAPERCLIP_AGENT_ID'):
            raise PermissionError('CEO runtime identity changed')
        issue = api('GET', '/issues/' + turn['issue'])
        if (issue.get('id') != turn['issue'] or issue.get('companyId') != turn['company'] or
                issue.get('projectId') != turn['project'] or issue.get('assigneeAgentId') != turn['agent'] or
                issue.get('executionRunId') != turn['run'] or issue.get('status') in ('done', 'cancelled')):
            raise PermissionError('Current native execution no longer owns this objective')
        proof = sign_evidence({'version': 2, 'kind': 'tool_event', 'company_id': turn['company'],
            'issue_id': turn['issue'], 'agent_id': turn['agent'], 'paperclip_run_id': turn['run'],
            'session_id': turn['session'], 'tool': 'local_ollama_models', 'success': True,
            'models': models, 'model': turn.get('runtime_model'),
            'inference_configuration': turn.get('inference_configuration')})
        api('PATCH', '/issues/' + turn['issue'], {'comment': '[JARVIS TOOL EVENT]\nJARVIS_TOOL_EVENT=' +
            json.dumps(proof, sort_keys=True, separators=(',', ':'))}, turn['run'])
        turn['inventory_journaled'] = fingerprint
        turn.pop('inventory_journal_error', None)
    except Exception as error:
        message = ('Native inventory progress journal failed (' + type(error).__name__ +
            '); the actual tool result remains valid. Inspect the native execution before retrying.')
        turn['inventory_journal_error'] = message
        _logger.error(message)


def finish(session_id='', turn_id='', completed=False, failed=False, interrupted=False, turn_exit_reason='', **kwargs):
    with _lock:
        turn = _turns.pop((session_id, turn_id), None)
    if not turn or turn['session'] != session_id:
        return
    if turn.get('ceo') or os.environ.get('JARVIS_PROFILE'):
        current = api('GET', '/issues/' + turn['issue'])
        if isinstance(current, dict) and current.get('status') == 'cancelled':
            # A human cancellation remains authoritative after remote stop.
            return
    if turn.get('ceo'):
        from . import ceo_tools
        ceo_tools.finalize(turn, completed=completed, failed=failed, interrupted=interrupted,
                           turn_exit_reason=turn_exit_reason)
        return
    success = completed and not failed and not interrupted and bool(turn['response'].strip())
    missing_tool = turn['needs_inventory'] and not turn['inventory_verified']
    missing_execution = None
    worker_blocker = None
    if os.environ.get('JARVIS_PROFILE'):
        from . import employee_tools
        if success:
            response = turn['response'].lstrip(' \t\n\r#>*_`-')
            label = re.match(r'(?:task )?(?:blocked|incomplete)[*_`]*(?:\s*[:—–-]|[.!]?(?:\r?\n|$))', response, re.I)
            if label:
                reason = response[label.end():].lstrip(' \t\n\r#>*_`-')
                worker_blocker = reason.splitlines()[0] if reason else 'The worker reported incomplete work.'
                success = False
        if success and not employee_tools.missing_execution(turn, require_deliverables=False):
            from . import employee_work
            try:
                selected = employee_tools.profile_registry.profile(os.environ['JARVIS_PROFILE'])
                if selected['sandbox'] and turn.get('needs_artifact'):
                    employee_work.deliver_workspace(turn)
                if turn.get('needs_report') and not any(a['originalFilename'].endswith('.md') for a in turn.get('artifacts', {}).values()):
                    employee_work.deliver_report(turn)
            except Exception as error:
                turn['delivery_error'] = str(error) if isinstance(error, (ValueError, PermissionError)) else 'Native deliverable storage failed; inspect the runtime log'
        missing_execution = employee_tools.missing_execution(turn)
        if turn.get('delivery_error'):
            missing_execution = 'Deliverable verification failed: ' + turn['delivery_error']
        success = success and not missing_execution
    success = success and not missing_tool
    comment = turn['response'] if success else 'Hermes execution failed or was interrupted. ' + str(turn_exit_reason)
    if success and turn.get('report_kind') == 'source_module_inventory' and turn.get('source_inventory_report'):
        comment = (turn['source_inventory_report'] + '\nThe task result is the observed tool inventory above. '
            'The model narrative is retained in the native run log and is not used as inventory evidence.')
    if missing_tool:
        comment = 'Verification failed: no successful local_ollama_models call was recorded. Task is blocked; the response is not accepted as a retrieved inventory.\n\nRuntime response:\n' + turn['response']
    if missing_execution:
        comment = 'Execution verification failed: ' + missing_execution + '\nTask is blocked; the model response is not accepted as completed work.\n\nRuntime response:\n' + turn['response']
    if worker_blocker:
        comment = turn['response'].strip()
    if success and turn.get('inventory') is not None:
        verified = [{k: model.get(k) for k in ('name', 'size_bytes', 'size_gib')} for model in turn['inventory']]
        comment += '\n\nVerified local_ollama_models data (exact tool output; recommendations above are model-generated):\n```json\n' + json.dumps(verified, indent=2) + '\n```'
        if os.environ.get('JARVIS_EXECUTION_PROOF_KEY'):
            comment += '\n\nJARVIS_EXECUTION_EVIDENCE=' + json.dumps(sign_evidence({
                'version': 2, 'agent_id': turn['agent'], 'paperclip_run_id': turn['run'],
                'session_id': turn['session'], 'tool': 'local_ollama_models', 'models': verified}))
    status = 'done' if success else 'blocked'
    if os.environ.get('JARVIS_PROFILE'):
        if turn.get('action_approval'):
            approval = turn['action_approval']
            status = 'in_review' if approval['status'] in ('pending', 'revision_requested') else 'blocked'
            comment = ('Sensitive-action approval ' + approval['id'] + ' is ' + approval['status'] +
                '. No sensitive action was executed and runtime permissions remain unchanged.\n\n' + turn['response'])
        comment += ('\n\nVerified runtime identity: employee ' + turn['agent'] + '; issue ' + turn['issue'] +
            '; execution ' + turn['run'] + '. Generated narrative above is not an execution receipt.')
        if turn.get('runtime_deliveries'):
            comment += '\n\nRuntime output delivery stored actual final text or existing workspace files in Paperclip. This storage does not imply a model publishing tool call.'
        comment += '\n\nJARVIS_EXECUTION_EVIDENCE=' + json.dumps(employee_tools.signed_execution(turn, status), separators=(',', ':'))
    # One atomic Paperclip update records final disposition and the real runtime reply.
    payload = {'status': status, 'comment': comment}
    if status == 'blocked':
        action = 'Review the Hermes execution error, fix its cause, then explicitly retry this task.'
        if missing_execution:
            action = str(missing_execution)[:1500]
        if turn.get('action_approval'):
            action = 'Respect the recorded approval decision: ' + approval['status']
        if worker_blocker and not turn.get('action_approval'):
            action = ('Resolve the reported blocker before retrying: ' + worker_blocker)[:2000]
        report_to_manager = os.environ.get('JARVIS_PROFILE') and current and current.get('parentId') and turn.get('reports_to')
        if report_to_manager:
            from . import blocker_review
        payload['unblockDescriptor'] = {'owner': {'agentId': turn['agent']},
            'action': (blocker_review.REPORT if report_to_manager else '') + action[:1900]}
    api('PATCH', '/issues/' + turn['issue'], payload, turn['run'])
    if status == 'blocked' and report_to_manager:
        blocker_review.report(api, turn, current, action)


def observe_model_context(session_id='', request_messages=None, model='', api_request_id='', **kwargs):
    """Observe the real provider payload without modifying it or logging secrets.

    A preflight log means context was prepared. This separate record confirms
    whether its complete bytes survived Hermes' user-context injection/spill.
    """
    try:
        turn = current_turn()
        context = turn.get('preflight_context_text')
        if session_id != turn['session'] or not context:
            return
        parts = []
        for message in request_messages or []:
            if not isinstance(message, dict):
                continue
            content = message.get('content', '')
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.extend(p['text'] for p in content if isinstance(p, dict) and isinstance(p.get('text'), str))
        present = any(context in part for part in parts)
        record = {'timestamp': time.time(), 'source': 'hermes_pre_api_request',
            'issue_id': turn['issue'], 'paperclip_run_id': turn['run'], 'session_id': session_id,
            'api_request_id': api_request_id, 'model': model,
            'context_sha256': turn['preflight_context_sha256'], 'context_chars': len(context),
            'complete_context_present': present,
            'approx_input_tokens': kwargs.get('approx_input_tokens'),
            'request_char_count': kwargs.get('request_char_count'),
            'tool_count': kwargs.get('tool_count'), 'max_tokens': kwargs.get('max_tokens')}
        from urllib.parse import urlsplit
        record['provider'] = kwargs.get('provider')
        record['endpoint_host'] = urlsplit(str(kwargs.get('base_url') or '')).hostname
        request = kwargs.get('request')
        if isinstance(request, dict):
            # Installed Hermes supplies {method, body}, not bare api_kwargs.
            if isinstance(request.get('body'), dict):
                request = request['body']
            extra = request.get('extra_body')
            extra = extra if isinstance(extra, dict) else {}
            record['request_max_tokens'] = request.get('max_tokens') or extra.get('max_tokens')
            record['available_function_names'] = []
            for tool in request.get('tools', []):
                if not isinstance(tool, dict):
                    continue
                function = tool.get('function') if isinstance(tool.get('function'), dict) else tool
                if isinstance(function.get('name'), str):
                    record['available_function_names'].append(function['name'])
            choice = request.get('tool_choice')
            record['tool_choice'] = choice if isinstance(choice, str) else None
        from hermes_constants import get_hermes_home
        log = get_hermes_home() / 'logs/model-context.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        if present:
            turn['observed_context_sha256'] = turn['preflight_context_sha256']
    except Exception:
        return  # This supported observer never changes inference or task state.


def guard_codex_demo(tool_name='', args=None, **kwargs):
    if os.environ.get('JARVIS_AGENT_ROLE') != 'ceo':
        return None
    try:
        turn = current_turn()
        from . import inference_policy
        if inference_policy.demo_tool_allowed(turn.get('inference_configuration'), tool_name, args or {}):
            return None
        return {'action': 'block', 'message':
            'This operator-authorized Codex demo permits scoped Paperclip reads, self planning and internal report artifacts. '
            'Hiring, delegation, approvals and host/external actions remain unavailable. Report the scope limit honestly.'}
    except Exception:
        return {'action': 'block', 'message': 'An authenticated Paperclip turn is required before using CEO tools.'}


def register(ctx):
    ctx.register_hook('pre_llm_call', begin)
    ctx.register_hook('pre_tool_call', guard_codex_demo)
    ctx.register_hook('pre_api_request', observe_model_context)
    ctx.register_hook('post_llm_call', response)
    ctx.register_hook('post_tool_call', tool_result)
    ctx.register_hook('on_session_end', finish)
