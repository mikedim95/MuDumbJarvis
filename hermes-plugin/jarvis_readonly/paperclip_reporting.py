"""Supported Hermes lifecycle hooks report ONLY the current assigned Paperclip issue.

No task scheduling or task store. Paperclip remains authoritative. Credentials and
destinations are fixed server-side; ordinary Hermes chat never enters this path.
"""
import threading
import hashlib
import hmac
import json
import os
import re
import time
import urllib.request

_turns = {}
_lock = threading.Lock()
_request_budget = threading.local()
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
    if not key:
        raise ValueError('Execution proof signing is not configured')
    encoded = json.dumps(proof, sort_keys=True, separators=(',', ':')).encode()
    return {**proof, 'signature': hmac.new(key.encode(), encoded, hashlib.sha256).hexdigest()}


def authentic_evidence(proof):
    if not isinstance(proof, dict) or proof.get('version') != 2:
        return False
    unsigned = {k: v for k, v in proof.items() if k != 'signature'}
    expected = sign_evidence(unsigned)['signature']
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
            'ceo': ceo, 'plan_decision': decision, 'reviewed_children': [],
            'needs_inventory': ('ollama' in description and 'model' in description) or 'installed models' in description,
            'inventory_verified': False}
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
        if data.get('source') != 'Ollama /api/tags' or not isinstance(data.get('models'), list):
            return
        with _lock:
            turn = _turns.get((task_id, turn_id))
            if not turn:
                return
            turn['inventory_verified'] = True
            turn['inventory'] = data['models']
        from hermes_constants import get_hermes_home
        record = {'timestamp': time.time(), 'issue_id': turn['issue'], 'paperclip_run_id': turn['run'],
                  'session_id': task_id, 'tool': tool_name, 'result': data}
        with (get_hermes_home() / 'logs' / 'paperclip-tools.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
    except (ValueError, AttributeError):
        return


def finish(session_id='', turn_id='', completed=False, failed=False, interrupted=False, turn_exit_reason='', **kwargs):
    with _lock:
        turn = _turns.pop((session_id, turn_id), None)
    if not turn or turn['session'] != session_id:
        return
    if turn.get('ceo'):
        from . import ceo_tools
        ceo_tools.finalize(turn, completed=completed, failed=failed, interrupted=interrupted,
                           turn_exit_reason=turn_exit_reason)
        return
    success = completed and not failed and not interrupted and bool(turn['response'].strip())
    missing_tool = turn['needs_inventory'] and not turn['inventory_verified']
    missing_execution = None
    if os.environ.get('JARVIS_PROFILE'):
        from . import employee_tools
        missing_execution = employee_tools.missing_execution(turn)
        success = success and not missing_execution
    success = success and not missing_tool
    comment = turn['response'] if success else 'Hermes execution failed or was interrupted. ' + str(turn_exit_reason)
    if missing_tool:
        comment = 'Verification failed: no successful local_ollama_models call was recorded. Task is blocked; the response is not accepted as a retrieved inventory.\n\nRuntime response:\n' + turn['response']
    if missing_execution:
        comment = 'Execution verification failed: ' + missing_execution + '\nTask is blocked; the model response is not accepted as completed work.\n\nRuntime response:\n' + turn['response']
    if success and turn.get('inventory') is not None:
        verified = [{k: model.get(k) for k in ('name', 'size_bytes', 'size_gib')} for model in turn['inventory']]
        comment += '\n\nVerified local_ollama_models data (exact tool output; recommendations above are model-generated):\n```json\n' + json.dumps(verified, indent=2) + '\n```'
        if os.environ.get('JARVIS_EXECUTION_PROOF_KEY'):
            comment += '\n\nJARVIS_EXECUTION_EVIDENCE=' + json.dumps(sign_evidence({
                'version': 2, 'agent_id': turn['agent'], 'paperclip_run_id': turn['run'],
                'session_id': turn['session'], 'tool': 'local_ollama_models', 'models': verified}))
    # One atomic Paperclip update records final disposition and the real runtime reply.
    payload = {'status': 'done' if success else 'blocked', 'comment': comment}
    if not success:
        payload['unblockDescriptor'] = {'owner': {'agentId': turn['agent']},
            'action': 'Review the Hermes execution error, fix its cause, then explicitly retry this task.'}
    api('PATCH', '/issues/' + turn['issue'], payload, turn['run'])


def register(ctx):
    ctx.register_hook('pre_llm_call', begin)
    ctx.register_hook('post_llm_call', response)
    ctx.register_hook('post_tool_call', tool_result)
    ctx.register_hook('on_session_end', finish)
