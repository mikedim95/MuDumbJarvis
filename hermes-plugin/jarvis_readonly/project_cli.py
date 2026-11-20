"""Send an admitted project terminal call from the trusted Hermes runtime."""
from contextvars import ContextVar
import hashlib
import hmac
import json
import os
from pathlib import PurePosixPath
import secrets
import shlex
import socket
import time
from uuid import UUID

SOCKET = '/opt/jarvis-codex/project-cli.sock'
MAX_WIRE = 512 * 1024
BACKEND = 'jarvis_project'
TOOLS = frozenset(('terminal', 'read_file', 'write_file', 'patch'))
active_call = ContextVar('jarvis_project_call', default=None)
MAX_TIMEOUT = 120


class ProjectArgumentError(ValueError):
    """A correctable caller error whose message may be returned to the worker."""


def assigned(turn):
    return ((turn.get('work_scope') or {}).get('kind') == 'project' and not turn.get('private_assignment')
            and turn.get('task_kind') != 'acknowledgement')


def private_input(turn, tool, args):
    # Native artifact reads may explicitly name a verified input in the current issue's private directory.
    path = (args or {}).get('path')
    return (tool == 'read_file' and isinstance(path, str) and turn.get('workspace')
            and path.startswith(turn['workspace'] + '/inputs/') and '..' not in PurePosixPath(path).parts)



def project_path(value):
    return (isinstance(value, str) and (value == '/project' or value.startswith('/project/'))
            and '..' not in PurePosixPath(value).parts and '\0' not in value)


def signature(key, request):
    message = json.dumps(request, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(key.encode(), b'jarvis-project-cli-v1\0' + message, hashlib.sha256).hexdigest()


def message(turn, args):
    scope = turn.get('work_scope') or {}
    if scope.get('kind') != 'project' or not scope.get('mission_id') or turn.get('task_kind') == 'acknowledgement':
        raise PermissionError('The shared CLI requires an active project assignment.')
    request = {k: str(UUID(turn[k])) for k in ('company', 'project', 'issue', 'agent', 'run')}
    command = args.get('command')
    timeout = args.get('timeout', 60)
    if type(timeout) is not int or timeout < 1:
        raise ProjectArgumentError('Use a positive whole number of seconds for the timeout.')
    if not project_path(args.get('workdir')):
        raise ProjectArgumentError('Use /project or a directory under /project.')
    if not isinstance(command, str) or not 0 < len(command) <= 32768 or '\0' in command:
        raise ProjectArgumentError('Supply a project command of 1–32768 characters without null bytes.')
    if args.get('background'):
        raise ProjectArgumentError('Run the project command in the foreground.')
    stdin = args.get('stdin')
    if stdin is not None and (not isinstance(stdin, str) or len(stdin.encode()) > 65536):
        raise ProjectArgumentError('Supply project file input as text of at most 64 KiB.')
    return {**request, **({'stdin': stdin} if stdin is not None else {}), 'mission':str(UUID(scope['mission_id'])), 'command':command, 'cwd':args['workdir'],
            'timeout':min(timeout, MAX_TIMEOUT), 'nonce':secrets.token_hex(16), 'time':int(time.time())}


def call(turn, args):
    request = message(turn, args)
    return exchange(request, os.environ['JARVIS_AGENT_PROOF_KEY'], request['timeout'] + 35)


def reference(turn, artifact=None):
    request = {k:str(UUID(turn[k])) for k in ('company','project','issue','agent','run')}
    mission = (turn.get('work_scope') or {}).get('mission_id')
    request.update(action='publish_finding' if artifact else 'read_findings', mission=str(UUID(mission)) if mission else None,
                   nonce=secrets.token_hex(16), time=int(time.time()))
    if artifact:
        request['artifact'] = str(UUID(artifact))
    key = (hmac.new(os.environ['JARVIS_EXECUTION_PROOF_KEY'].encode(),
                    ('jarvis-employee-proof-v3:' + turn['agent']).encode(), hashlib.sha256).hexdigest()
           if turn.get('ceo') else os.environ['JARVIS_AGENT_PROOF_KEY'])
    response = exchange(request, key, 12)
    if response.get('error'):
        raise ValueError(response['error'])
    return response


def exchange(request, key, timeout):
    packet = json.dumps({'request':request, 'proof':signature(key, request)})
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(timeout)
        conn.connect(SOCKET)
        conn.sendall(packet.encode() + b'\n')
        with conn.makefile('rb') as reader:
            raw = reader.readline(MAX_WIRE + 1)
    if len(raw) > MAX_WIRE or not raw.endswith(b'\n'):
        raise ValueError('Invalid project terminal response.')
    return json.loads(raw)


READ_FILE = """import base64, json, os, stat, sys
parts = sys.argv[1].split('/')
fd = os.open('/project', os.O_RDONLY | os.O_DIRECTORY)
for part in parts[:-1]:
    new = os.open(part, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    os.close(fd)
    fd = new
with os.fdopen(os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd), 'rb') as f:
    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): sys.exit(1)
    data = f.read(32769)
    if not 0 < len(data) <= 32768: sys.exit(1)
    print(json.dumps([os.fstat(f.fileno()).st_mtime, base64.b64encode(data).decode()]))
"""


def read_file(turn, path, include_stat=False):
    import base64
    if not project_path(path) or path == '/project':
        raise PermissionError('Use a file under /project.')
    relative = PurePosixPath(path).relative_to('/project').as_posix()
    if relative == '.':
        raise ValueError('Use a regular project file.')
    result = call(turn, {'workdir':'/project', 'timeout':10, 'command':shlex.join(
        ['/usr/local/bin/python3','-IS','-c',READ_FILE,relative])})
    if result.get('exit_code') != 0 or result.get('truncated'):
        raise ValueError('Could not read a regular project file of up to 32 KiB.')
    modified, encoded = json.loads(result['output'])
    data = base64.b64decode(encoded, validate=True)
    return (data, modified) if include_stat else data


def execute(next_call, tool_name='', args=None, tool_call_id='', session_id='', task_id='', **kwargs):
    """Select the backend around the native dispatch. Hermes still runs its own guardrails."""
    if tool_name not in TOOLS:
        return next_call()
    from . import paperclip_reporting as reporting
    from tools.terminal_scope import enforce_no_refusal, get_terminal_scope, reset_terminal_scope, set_terminal_scope
    try:
        turn = reporting.current_turn()
    except ValueError:
        return json.dumps({'exit_code':125, 'error':'No authenticated assignment.'})
    if not assigned(turn) or private_input(turn, tool_name, args):
        return next_call()
    try:
        if not tool_call_id or turn['session'] != (session_id or task_id):
            raise PermissionError('No matching project assignment.')
        enforce_no_refusal()
        policy = dict(get_terminal_scope() or {})
        policy.update(TERMINAL_ENV=BACKEND, TERMINAL_CWD='/project', TERMINAL_TIMEOUT='60',
                      TERMINAL_CONTAINER_PERSISTENT='false')
    except Exception as exc:
        return json.dumps({'exit_code':125, 'error':'Project workspace unavailable: ' + str(exc)[:180]})
    scope = set_terminal_scope(policy)
    caller = kwargs.get('original_args')
    caller = caller if isinstance(caller, dict) else args or {}
    active = active_call.set((turn, tool_call_id, tool_name, 'workdir' in caller))
    try:
        return next_call()
    finally:
        active_call.reset(active)
        reset_terminal_scope(scope)


class ProjectEnvironment:
    cwd = '/project'

    def execute(self, command, *, cwd=None, timeout=None, stdin_data=None, **kwargs):
        active = active_call.get()
        if active is None:
            raise PermissionError('Project command outside an authorized tool call.')
        turn, call_id, tool, caller_workdir = active
        if turn.get('scoped_calls', {}).get(call_id, {}).get('tool') != tool:
            raise PermissionError('Missing project tool admission.')
        args = {'workdir':cwd or '/project', 'command':command, 'timeout':timeout or 60}
        if stdin_data is not None:
            args['stdin'] = stdin_data
        try:
            result = call(turn, args)
            if result.get('error'):
                return {'returncode':125, 'output':result['error']}
            if result.get('mission_id') != turn['work_scope']['mission_id'] or result.get('workdir') != args['workdir']:
                raise ValueError('Mismatched project execution receipt')
            turn['scoped_calls'][call_id]['project_receipt'] = {
                'mission_id':result['mission_id'], 'workdir':result['workdir']}
            if tool == 'terminal':
                turn['scoped_calls'][call_id]['project_receipt']['workdir_source'] = (
                    'caller' if caller_workdir else 'project_default')
            return {'returncode':result['exit_code'], 'output':result['output']}
        except (OSError, ValueError, KeyError) as exc:
            return {'returncode':125, 'output':'Project workspace unavailable: ' + str(exc)[:180]}

    def cleanup(self):
        # The project lifecycle service owns the container and persistent volume.
        pass


def provider():
    from agent.terminal_env_provider import TerminalEnvironmentProvider

    class ProjectProvider(TerminalEnvironmentProvider):
        name = BACKEND
        display_name = 'JARVIS project workspace'
        default_cwd = '/project'
        skip_container_guards = False
        session_isolated_when_nonpersistent = True

        def is_available(self):
            return os.path.exists(SOCKET)

        def create_environment(self, **kwargs):
            return ProjectEnvironment()

    return ProjectProvider()
