"""Capability-scoped employee tools. All state and results belong to Paperclip."""
import json
import os
import re

from . import paperclip_reporting as reporting
from . import profile_registry


def guard(tool_name='', args=None, task_id='', session_id='', tool_call_id='', **kwargs):
    """Fail closed before builtin tools; model arguments cannot select the host."""
    try:
        selected = profile_registry.profile(os.environ['JARVIS_PROFILE'])
        turn = reporting.current_turn()
        if turn['agent'] != os.environ.get('JARVIS_PAPERCLIP_AGENT_ID'):
            raise PermissionError('Employee identity mismatch')
        requested_session = session_id or task_id
        if requested_session and requested_session != turn['session']:
            raise PermissionError('Tool session is outside the assigned issue')
        if tool_name not in set(selected['tools']) | {'agent_identity'}:
            raise PermissionError('Tool is outside the approved capability profile')
        if not isinstance(args, dict):
            raise PermissionError('Tool arguments must be structured')
        forbidden = {'force', 'backend', 'env_type', 'host', 'ssh_host', 'ssh_key', 'image', 'env'}
        if any(key.startswith('_') or key in forbidden for key in args):
            raise PermissionError('Host, environment and approval overrides are unavailable')
        if tool_name in ('terminal', 'read_file', 'write_file', 'patch'):
            import re
            if (os.environ.get('TERMINAL_ENV') != 'ssh' or
                    not re.fullmatch(r'jarvis-sandbox-[a-f0-9]{24}', os.environ.get('TERMINAL_SSH_HOST', ''))):
                raise PermissionError('The approved private execution backend is unavailable')
            from pathlib import PurePosixPath
            workdir = args.get('workdir', '/workspace')
            if (not isinstance(workdir, str) or '..' in PurePosixPath(workdir).parts or
                    (workdir != '/workspace' and not workdir.startswith('/workspace/'))):
                raise PermissionError('The working directory must stay within the private workspace')
        if tool_name in ('read_file', 'write_file', 'patch'):
            from pathlib import PurePosixPath
            path = args.get('path', '')
            if not isinstance(path, str) or '..' in PurePosixPath(path).parts or (path.startswith('/') and not path.startswith('/workspace/')):
                raise PermissionError('Files must stay within the private workspace')
        if tool_name in ('terminal', 'read_file', 'write_file', 'patch'):
            # Gateway workspace tracking can otherwise seed /root from the
            # parent process. Bind the existing SSH backend before it is used.
            from tools.terminal_tool import register_task_env_overrides
            register_task_env_overrides(task_id or session_id, {'cwd': '/workspace'})
        turn.setdefault('scoped_calls', {})[tool_call_id] = {'tool': tool_name, 'args': dict(args)}
    except Exception as error:
        return {'action': 'block', 'message': 'JARVIS capability guard denied this tool: ' +
            (str(error) if isinstance(error, PermissionError) else 'Authenticated runtime scope is unavailable')}
    return None


def capture(tool_name='', result='', task_id='', session_id='', tool_call_id='', **kwargs):
    """Accept results only for calls admitted to this authenticated issue."""
    try:
        turn = reporting.current_turn()
        if (session_id or task_id) != turn['session']:
            return
        call = turn.get('scoped_calls', {}).pop(tool_call_id, None)
        if not call or call['tool'] != tool_name:
            return
        data = json.loads(result) if isinstance(result, str) else result
        if not isinstance(data, dict):
            return
        ok = not data.get('error') and not data.get('isError')
        if tool_name == 'terminal':
            ok = ok and data.get('exit_code') == 0
        turn.setdefault('employee_execution', []).append({
            'tool': tool_name, 'tool_call_id': tool_call_id,
            'args': call['args'], 'result': data, 'success': bool(ok)})
    except Exception:
        # A missing receipt can never satisfy the fail-closed final check.
        return


def missing_execution(turn):
    selected = profile_registry.profile(os.environ['JARVIS_PROFILE'])
    events = [event for event in turn.get('employee_execution', []) if event['success']]
    if selected['id'] == 'software_development':
        terminal = [event for event in events if event['tool'] == 'terminal']
        if not terminal:
            return 'No successful terminal execution was recorded. Use the actual write_file and terminal tools; describing future execution is insufficient.'
        if turn.get('needs_tests') and not any(
                re.search(r'\b(?:python[0-9.]*|pytest|unittest)\b', str(event['args'].get('command', ''))) and
                re.search(r'(?:Ran [1-9][0-9]* tests?.*?\bOK\b|[1-9][0-9]* passed)',
                          str(event['result'].get('output', '')), re.S)
                for event in terminal):
            return 'No passing test execution was recorded. Execute the requested Python unittest or pytest tests with terminal and inspect the real output and exit code.'
    elif not any(event['tool'] in set(selected['tools']) - {'agent_identity', 'publish_artifact', 'request_action_approval'}
                 for event in events):
        return 'No successful work tool was recorded for the assigned capability. Identity and model-generated prose do not prove execution.'
    return None


def verify(session_id='', attempt=0, **kwargs):
    try:
        turn = reporting.current_turn()
        if session_id != turn['session']:
            return None
        missing = missing_execution(turn)
        if missing and attempt < 2:
            return {'action': 'continue', 'message': missing + ' Complete the scoped task now; do not claim success without the tools.'}
    except Exception:
        return None
    return None


def prepare_turn_context(turn, issue):
    selected = profile_registry.profile(os.environ['JARVIS_PROFILE'])
    context = {'source': 'Authenticated Paperclip assignment',
        'issue_id': turn['issue'], 'paperclip_run_id': turn['run'],
        'title': issue.get('title'), 'objective': str(issue.get('description') or '')[:8000],
        'profile': selected['id'], 'allowed_tools': selected['tools'],
        'authority': selected['authority'],
        'workspace': '/workspace' if selected['sandbox'] else None,
        'completion_requires': 'Actual work tool execution. Identity or a plan describing future actions is insufficient.',
        'instruction': 'Execute this assigned objective NOW using real permitted tool calls. Do not stop with a promise to create files or run tests. Read actual output, then report completed work or the real blocker.'}
    if selected['id'] == 'software_development':
        context['instruction'] += (' Use write_file to create the requested source/tests under /workspace, '
            'then call terminal to execute them. The SSH workspace exists. ' +
            ('Passing unittest or pytest output with exit code zero is required.' if turn.get('needs_tests') else ''))
    return 'Current authenticated employee work (runtime context, not an execution receipt):\n' + json.dumps(context)


def identity(args, **kwargs):
    turn = reporting.current_turn()
    selected = profile_registry.profile(os.environ['JARVIS_PROFILE'])
    me = reporting.api('GET', '/agents/me')
    if me['id'] != turn['agent'] or me['id'] != os.environ.get('JARVIS_PAPERCLIP_AGENT_ID'):
        raise PermissionError('Employee runtime identity mismatch')
    return json.dumps({'source': 'Authenticated Paperclip employee and local capability policy',
        'agent_id': me['id'], 'company_id': turn['company'], 'issue_id': turn['issue'],
        'paperclip_run_id': turn['run'], 'profile': selected['id'], 'model': selected['model'],
        'allowed_tools': selected['tools'], 'authority': selected['authority'], 'inference_slots': 1,
        'next': 'Identity retrieval is complete; assigned work is still unperformed. Call the actual work tools now. '
                'For coding, call write_file and then terminal; report the real execution output. '
                'A sentence saying you are creating or executing is not a tool call and will be blocked.'})


def register(ctx):
    if not os.environ.get('JARVIS_PROFILE'):
        return
    if profile_registry.profile(os.environ['JARVIS_PROFILE'])['sandbox']:
        # Builtin file safety checks the remote path before SSH dispatch.
        # This is the approved container workspace, never the runtime home.
        os.environ['HERMES_WRITE_SAFE_ROOT'] = '/workspace'
    ctx.register_hook('pre_tool_call', guard)
    ctx.register_hook('post_tool_call', capture)
    ctx.register_hook('pre_verify', verify)
    ctx.register_tool(name='agent_identity', toolset='jarvis_employee',
        schema={'name': 'agent_identity', 'description': 'Read your authenticated Paperclip identity, assigned issue, capability profile and approved authority.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, handler=identity)
