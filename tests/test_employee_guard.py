import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


@pytest.fixture
def employee(monkeypatch):
    root = Path(__file__).resolve().parents[1] / 'hermes-plugin/jarvis_readonly'
    package = ModuleType('employee_guard_under_test')
    package.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    spec = importlib.util.spec_from_file_location(package.__name__ + '.employee_tools', root / 'employee_tools.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv('JARVIS_PROFILE', 'software_development')
    monkeypatch.setenv('JARVIS_PAPERCLIP_AGENT_ID', 'employee')
    monkeypatch.setenv('TERMINAL_ENV', 'ssh')
    monkeypatch.setenv('TERMINAL_SSH_HOST', 'jarvis-sandbox-' + 'a' * 24)
    monkeypatch.setattr(module.reporting, 'current_turn', lambda: {'agent': 'employee', 'session': 'issue-session'})
    terminal = ModuleType('tools.terminal_tool')
    module.workspace_bindings = []
    terminal.register_task_env_overrides = lambda *args: module.workspace_bindings.append(args)
    monkeypatch.setitem(sys.modules, 'tools.terminal_tool', terminal)
    return module


@pytest.mark.parametrize('args', [{'_host_local': True, 'command': 'id'}, {'force': True, 'command': 'id'},
    {'backend': 'local', 'command': 'id'}, {'env': {'API_SERVER_KEY': 'x'}, 'command': 'id'}])
def test_model_cannot_override_private_execution_backend(employee, args):
    assert employee.guard(tool_name='terminal', args=args, session_id='issue-session')['action'] == 'block'


def test_private_terminal_call_is_allowed_in_its_assigned_issue(employee):
    assert employee.guard(tool_name='terminal', args={'command': 'python3 -V'}, session_id='issue-session') is None
    assert employee.workspace_bindings == [('issue-session', {'cwd': '/workspace'})]


@pytest.mark.parametrize('workdir', ['/root', '/home/kali', '/workspace/../opt/data', 'relative'])
def test_terminal_cwd_cannot_select_a_parent_runtime_or_host_path(employee, workdir):
    assert employee.guard(tool_name='terminal', args={'command': 'id', 'workdir': workdir}, session_id='issue-session')['action'] == 'block'
    assert employee.workspace_bindings == []


def test_foreign_issue_and_nonapproved_tools_are_denied(employee):
    assert employee.guard(tool_name='terminal', args={'command': 'id'}, session_id='foreign')['action'] == 'block'
    assert employee.guard(tool_name='delegate_task', args={}, session_id='issue-session')['action'] == 'block'


def test_research_profile_has_no_shell(employee, monkeypatch):
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    assert employee.guard(tool_name='terminal', args={'command': 'id'}, session_id='issue-session')['action'] == 'block'


@pytest.mark.parametrize('path', ['/opt/data/config.yaml', '/home/kali/.ssh/id_ed25519', '../../config.yaml'])
def test_file_tools_cannot_read_profile_credentials_or_host_paths(employee, path):
    assert employee.guard(tool_name='read_file', args={'path': path}, session_id='issue-session')['action'] == 'block'


def test_unavailable_scope_fails_closed(employee, monkeypatch):
    monkeypatch.setattr(employee.reporting, 'current_turn', lambda: (_ for _ in ()).throw(ValueError('no turn')))
    assert employee.guard(tool_name='agent_identity', args={})['action'] == 'block'


def test_sandbox_file_safety_uses_remote_workspace(employee, monkeypatch):
    from types import SimpleNamespace
    import os
    monkeypatch.setenv('HERMES_WRITE_SAFE_ROOT', '/opt/data')
    hooks = []
    employee.register(SimpleNamespace(register_hook=lambda *args: hooks.append(args), register_tool=lambda **kwargs: None))
    assert os.environ['HERMES_WRITE_SAFE_ROOT'] == '/workspace'
    assert hooks[0] == ('pre_tool_call', employee.guard)


def test_original_chat_runtime_does_not_change_its_file_policy(employee, monkeypatch):
    from types import SimpleNamespace
    import os
    monkeypatch.delenv('JARVIS_PROFILE')
    monkeypatch.setenv('HERMES_WRITE_SAFE_ROOT', '/opt/data')
    employee.register(SimpleNamespace())
    assert os.environ['HERMES_WRITE_SAFE_ROOT'] == '/opt/data'


def test_identity_and_prose_cannot_complete_software_work(employee):
    turn = {'employee_execution': [{'tool': 'agent_identity', 'success': True}], 'needs_tests': True}
    assert 'No successful terminal' in employee.missing_execution(turn)


def test_failed_terminal_and_successful_non_test_command_do_not_prove_tests(employee):
    turn = {'needs_tests': True, 'employee_execution': [
        {'tool': 'terminal', 'success': False, 'args': {'command': 'python3 test.py'},
         'result': {'output': 'FAILED', 'exit_code': 1}}]}
    assert 'No successful terminal' in employee.missing_execution(turn)
    turn['employee_execution'].append({'tool': 'terminal', 'success': True,
        'args': {'command': 'pwd'}, 'result': {'output': '/workspace', 'exit_code': 0}})
    assert 'No passing test' in employee.missing_execution(turn)


def test_actual_admitted_test_result_is_required_for_completion(employee, monkeypatch):
    turn = {'agent': 'employee', 'session': 'issue-session', 'needs_tests': True}
    monkeypatch.setattr(employee.reporting, 'current_turn', lambda: turn)
    employee.capture(tool_name='terminal', tool_call_id='forged', session_id='issue-session',
        result={'output': 'Ran 2 tests in 0.001s\n\nOK', 'exit_code': 0})
    assert 'No successful terminal' in employee.missing_execution(turn)
    assert employee.guard(tool_name='terminal', tool_call_id='real', session_id='issue-session',
        args={'command': 'python3 /workspace/test.py'}) is None
    employee.capture(tool_name='terminal', tool_call_id='real', session_id='foreign',
        result={'output': 'Ran 2 tests in 0.001s\n\nOK', 'exit_code': 0})
    assert 'No successful terminal' in employee.missing_execution(turn)
    employee.capture(tool_name='terminal', tool_call_id='real', session_id='issue-session',
        result={'output': 'Ran 2 tests in 0.001s\n\nOK', 'exit_code': 0})
    assert employee.missing_execution(turn) is None


def test_verify_reprompts_then_stops_instead_of_accepting_prose(employee, monkeypatch):
    turn = {'session': 'issue-session', 'needs_tests': True}
    monkeypatch.setattr(employee.reporting, 'current_turn', lambda: turn)
    assert employee.verify(session_id='issue-session', attempt=0)['action'] == 'continue'
    assert employee.verify(session_id='issue-session', attempt=2) is None
    assert employee.missing_execution(turn)


def test_employee_receives_actual_bounded_assignment_separately_from_wake_metadata(employee):
    context = employee.prepare_turn_context({'issue': 'real-issue', 'run': 'real-run', 'needs_tests': True},
        {'title': 'Real task', 'description': 'Create and execute the assigned tests.'})
    assert 'real-issue' in context and 'real-run' in context
    assert 'Create and execute the assigned tests.' in context
    assert 'exit code zero' in context and 'not an execution receipt' in context


def test_managed_completion_callback_blocks_the_observed_text_only_failure(employee, monkeypatch):
    turn = {'session': 'issue-session', 'issue': 'issue', 'run': 'run', 'agent': 'employee',
        'needs_inventory': False, 'inventory_verified': False, 'needs_tests': True,
        'response': 'Creating the source, executing tests, and confirming success.',
        'employee_execution': [{'tool': 'agent_identity', 'success': True}]}
    monkeypatch.setitem(employee.reporting._turns, ('issue-session', 'turn'), turn)
    updates = []
    monkeypatch.setattr(employee.reporting, 'api', lambda *args: updates.append(args))
    employee.reporting.finish(session_id='issue-session', turn_id='turn', completed=True)
    payload = updates[-1][2]
    assert payload['status'] == 'blocked'
    assert 'not accepted as completed work' in payload['comment']
    assert 'No successful terminal execution' in payload['comment']
