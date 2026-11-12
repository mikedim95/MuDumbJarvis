"""Supported Hermes lifecycle hooks report ONLY the current assigned Paperclip issue.

No task scheduling or task store. Paperclip remains authoritative. Credentials and
destinations are fixed server-side; ordinary Hermes chat never enters this path.
"""
import threading
import json
import os
import re
import time
import urllib.request

_turns = {}
_lock = threading.Lock()
_scope = re.compile(r'^paperclip:company:([0-9a-f-]{36}):agent:([0-9a-f-]{36}):issue:([0-9a-f-]{36})$')


def api(method, path, body=None, run_id=None):
    headers = {'Authorization': 'Bearer ' + os.environ['HERMES_PAPERCLIP_AGENT_KEY'],
               'Content-Type': 'application/json'}
    if run_id:
        headers['X-Paperclip-Run-Id'] = run_id
    request = urllib.request.Request('http://paperclip:3100/api' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)


def begin(session_id='', turn_id='', **kwargs):
    key = (session_id, turn_id)
    with _lock:
        _turns.pop(key, None)
    match = _scope.fullmatch(session_id)
    if not match:
        return
    company, agent, issue_id = match.groups()
    try:
        me = api('GET', '/agents/me')
        if me['id'] != agent or me['companyId'] != company:
            raise ValueError('Session does not belong to this agent')
        issue = api('GET', '/issues/' + issue_id)
        if issue['assigneeAgentId'] != agent or issue['companyId'] != company:
            raise ValueError('Issue is not assigned to this agent')
        run_id = issue.get('executionRunId')
        if not run_id:
            raise ValueError('No active Paperclip execution owns this issue')
        api('POST', '/issues/' + issue_id + '/checkout',
            {'agentId': agent, 'expectedStatuses': ['todo', 'backlog', 'blocked', 'in_progress']}, run_id)
        with _lock:
            description = (issue.get('description') or '').lower()
            _turns[key] = {'session': session_id, 'issue': issue_id, 'run': run_id, 'response': '',
                'needs_inventory': ('ollama' in description and 'model' in description) or 'installed models' in description,
                'inventory_verified': False}
    except Exception as exc:
        return {'action': 'block', 'message': 'Paperclip task checkout failed: ' + type(exc).__name__}


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
    success = completed and not failed and not interrupted and bool(turn['response'].strip())
    missing_tool = turn['needs_inventory'] and not turn['inventory_verified']
    success = success and not missing_tool
    comment = turn['response'] if success else 'Hermes execution failed or was interrupted. ' + str(turn_exit_reason)
    if missing_tool:
        comment = 'Verification failed: no successful local_ollama_models call was recorded. Task is blocked; the response is not accepted as a retrieved inventory.\n\nRuntime response:\n' + turn['response']
    if success and turn.get('inventory') is not None:
        verified = [{k: model.get(k) for k in ('name', 'size_bytes', 'size_gib')} for model in turn['inventory']]
        comment += '\n\nVerified local_ollama_models data (exact tool output; recommendations above are model-generated):\n```json\n' + json.dumps(verified, indent=2) + '\n```'
    # One atomic Paperclip update records final disposition and the real runtime reply.
    payload = {'status': 'done' if success else 'blocked', 'comment': comment}
    if not success:
        payload['unblockDescriptor'] = {'owner': 'board',
            'action': 'Review the Hermes execution error, fix its cause, then explicitly retry this task.'}
    api('PATCH', '/issues/' + turn['issue'], payload, turn['run'])


def register(ctx):
    ctx.register_hook('pre_llm_call', begin)
    ctx.register_hook('post_llm_call', response)
    ctx.register_hook('post_tool_call', tool_result)
    ctx.register_hook('on_session_end', finish)
