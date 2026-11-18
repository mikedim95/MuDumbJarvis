import importlib.util
import json
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
    {'backend': 'local', 'command': 'id'}, {'env': {'API_SERVER_KEY': 'x'}, 'command': 'id'},
    {'cross_profile': True, 'command': 'id'}])
def test_model_cannot_override_private_execution_backend(employee, args):
    assert employee.guard(tool_name='terminal', args=args, session_id='issue-session')['action'] == 'block'


def test_private_terminal_call_is_allowed_in_its_assigned_issue(employee):
    assert employee.guard(tool_name='terminal', args={'command': 'python3 -V'}, session_id='issue-session') == {
        'action': 'modify', 'args': {'workdir': '/workspace'}}
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


def test_brief_report_instruction_preserves_worker_directions_and_assignment(employee, monkeypatch):
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    directions = {'text': 'Cite the official manual.'}
    objective = 'Report the documented file formats.'
    turn = {'issue': 'native-issue', 'run': 'native-run', 'general_context': directions}
    context = json.loads(employee.prepare_turn_context(turn, {'description': objective}).split('\n', 1)[1])
    assert context['reporting_style'] == employee.reporting.REPORT_STYLE
    assert context['general_directions'] == directions and context['objective'] == objective


def test_existing_record_handoff_does_not_require_new_sources_from_a_historical_limitation(employee, monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: tmp_path))
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    turn = {'issue': 'native-issue', 'run': 'native-run'}
    employee.prepare_turn_context(turn, {'description':
        'Inspect existing JAR-64 and JAR-65 records and published artifacts. Do not restart research. '
        'Call research_sources with action=records. The older assistant statements about a '
        'three-framework-only schema are stale. Publish the requested handoff.'})
    turn['employee_execution'] = [{'tool': 'research_sources', 'success': True,
        'args': {'action': 'records', 'issue_ids': ['JAR-64', 'JAR-65']}, 'result': {'issues': []}}]
    turn['artifacts'] = {'report': {'originalFilename': 'handoff.txt'}}
    assert turn['required_framework_count'] == 0
    assert employee.missing_execution(turn) is None


@pytest.mark.parametrize('objective', ['Research three open-source AI security frameworks.',
    'Retrieve 3 frameworks and compare their capabilities.'])
def test_explicit_three_framework_research_still_requires_actual_source_retrieval(employee, monkeypatch, tmp_path, objective):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: tmp_path))
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    turn = {'issue': 'native-issue', 'run': 'native-run'}
    employee.prepare_turn_context(turn, {'description': objective})
    turn['employee_execution'] = [{'tool': 'research_sources', 'success': True, 'result': {}}]
    assert turn['required_framework_count'] == 3
    assert 'Not all requested frameworks' in employee.missing_execution(turn)


@pytest.mark.parametrize('path', ['/opt/data/config.yaml', '/home/kali/.ssh/id_ed25519', '../../config.yaml', '/workspace/', '.', ''])
def test_file_tools_cannot_read_profile_credentials_or_host_paths(employee, path):
    assert employee.guard(tool_name='read_file', args={'path': path}, session_id='issue-session')['action'] == 'block'


def test_patch_cannot_hide_foreign_paths_inside_multifile_patch_text(employee):
    assert employee.guard(tool_name='patch', args={'mode': 'patch',
        'patch': '*** Begin Patch\n*** Add File: /opt/data/config.yaml\n+secret\n*** End Patch'},
        session_id='issue-session')['action'] == 'block'
    assert employee.guard(tool_name='patch', args={'path': '/workspace/test.py',
        'old_string': 'old', 'new_string': 'new'}, session_id='issue-session') is None


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


def test_passing_unit_tests_do_not_hide_a_failed_required_framework_job(employee):
    turn = {'needs_tests': True, 'needs_promptfoo': True, 'employee_execution': [
        {'tool': 'terminal', 'success': True, 'args': {'command': 'python3 test.py'},
         'result': {'output': 'Ran 2 tests in 0.001s\nOK', 'exit_code': 0}},
        {'tool': 'terminal', 'success': False, 'args': {'command': 'promptfoo eval -c broken.json'},
         'result': {'output': 'Invalid configuration', 'exit_code': 1}}]}
    assert 'latest work tool failed' in employee.missing_execution(turn)
    turn['employee_execution'].pop()
    assert 'No successful Promptfoo result JSON' in employee.missing_execution(turn)


def test_failed_terminal_and_successful_non_test_command_do_not_prove_tests(employee):
    turn = {'needs_tests': True, 'employee_execution': [
        {'tool': 'terminal', 'success': False, 'args': {'command': 'python3 test.py'},
         'result': {'output': 'FAILED', 'exit_code': 1}}]}
    assert 'latest work tool failed' in employee.missing_execution(turn)
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
        args={'command': 'python3 /workspace/test.py'})['action'] == 'modify'
    employee.capture(tool_name='terminal', tool_call_id='real', session_id='foreign',
        result={'output': 'Ran 2 tests in 0.001s\n\nOK', 'exit_code': 0})
    assert 'No successful terminal' in employee.missing_execution(turn)
    employee.capture(tool_name='terminal', tool_call_id='real', session_id='issue-session',
        result={'output': 'Ran 2 tests in 0.001s\n\nOK', 'exit_code': 0})
    assert employee.missing_execution(turn) is None


def test_operator_isolation_checks_do_not_replace_generated_program_tests(employee):
    turn = {'needs_tests': True, 'needs_runtime_fixture': True, 'employee_execution': [
        {'tool': 'terminal', 'success': True, 'args': {'command': 'python3 /usr/local/share/jarvis/isolation_checks.py'},
         'result': {'output': 'Ran 8 tests in 0.001s\nOK', 'exit_code': 0}}]}
    assert 'No passing test' in employee.missing_execution(turn)
    turn['employee_execution'].append({'tool': 'terminal', 'success': True,
        'args': {'command': 'python3 test_demo.py'}, 'result': {'output': 'Ran 2 tests in 0.001s\nOK', 'exit_code': 0}})
    assert employee.missing_execution(turn) is None


def test_verify_reprompts_then_stops_instead_of_accepting_prose(employee, monkeypatch):
    turn = {'session': 'issue-session', 'needs_tests': True}
    monkeypatch.setattr(employee.reporting, 'current_turn', lambda: turn)
    assert employee.verify(session_id='issue-session', attempt=0)['action'] == 'continue'
    assert employee.verify(session_id='issue-session', attempt=2) is None
    assert employee.missing_execution(turn)


def test_employee_receives_actual_bounded_assignment_separately_from_wake_metadata(employee, monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: tmp_path))
    context = employee.prepare_turn_context({'issue': '11111111-1111-4111-8111-111111111111', 'run': 'real-run', 'needs_tests': True},
        {'title': 'Real task', 'description': 'Create and execute the assigned tests.'})
    assert '11111111-1111-4111-8111-111111111111' in context and 'real-run' in context
    assert 'Create and execute the assigned tests.' in context
    assert 'exit code zero' in context and 'not an execution receipt' in context
    assert 'no parent or sibling deliverables' in context and 'foreground terminal' in context


def test_retry_can_reuse_verified_files_without_instructions_to_regenerate_them(employee, monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: tmp_path))
    context = employee.prepare_turn_context({'issue': '11111111-1111-4111-8111-111111111111', 'run': 'real-run', 'needs_tests': True},
        {'description': 'Reuse existing files; do not rewrite them. Execute unittest and promptfoo, then report.'})
    payload = json.loads(context.split('\n', 1)[1])
    assert 'Reuse existing' in payload['instruction']
    assert 'Use write_file to create' not in payload['instruction']
    assert 'offline_framework_reference' not in payload


@pytest.mark.parametrize(('filename', 'reply', 'status'), [
    ('research.txt', 'Blocked: primary evidence is unavailable.\n\nSee the limitations report.', 'blocked'),
    ('research.md', '**Incomplete:** primary evidence is unavailable.', 'blocked'),
    ('research.txt', 'Two matching records were verified.', 'done'),
])
def test_published_worker_report_remains_evidence_of_its_actual_outcome(employee, monkeypatch, filename, reply, status):
    artifact = {'id': 'receipt', 'originalFilename': filename}
    turn = {'session': 'issue-session', 'issue': 'issue', 'run': 'run', 'company': 'company',
        'agent': '22222222-2222-4222-8222-222222222222', 'needs_inventory': False, 'inventory_verified': False,
        'needs_artifact': True, 'needs_report': True, 'response': reply, 'artifacts': {'receipt': artifact},
        'employee_execution': [{'tool': 'research_sources', 'tool_call_id': 'read', 'success': True,
                                'args': {}, 'result': {'source': 'primary'}}]}
    monkeypatch.setenv('JARVIS_PROFILE', 'research')
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', 'test-signing-key')
    monkeypatch.setitem(employee.reporting._turns, ('issue-session', 'turn'), turn)
    calls = []
    monkeypatch.setattr(employee.reporting, 'api', lambda *args: calls.append(args))
    employee.reporting.finish(session_id='issue-session', turn_id='turn', completed=True)
    payload = calls[-1][2]
    assert [call[0] for call in calls] == ['GET', 'PATCH']
    assert payload['status'] == status
    narrative, signed = payload['comment'].split('\n\nJARVIS_EXECUTION_EVIDENCE=')
    assert narrative == reply
    proof = json.loads(signed)
    assert employee.reporting.authentic_evidence(proof)
    assert proof['artifacts'] == [artifact] and proof['task_status'] == status
    if status == 'blocked':
        assert 'primary evidence is unavailable.' in payload['unblockDescriptor']['action']
    else:
        assert payload['unblockDescriptor'] is None


def test_managed_completion_callback_blocks_the_observed_text_only_failure(employee, monkeypatch):
    turn = {'session': 'issue-session', 'issue': 'issue', 'run': 'run', 'agent': 'employee',
        'needs_inventory': False, 'inventory_verified': False, 'needs_tests': True,
        'response': 'Creating the source, executing tests, and confirming success.',
        'employee_execution': [{'tool': 'agent_identity', 'success': True}]}
    monkeypatch.setitem(employee.reporting._turns, ('issue-session', 'turn'), turn)
    updates = []
    monkeypatch.setattr(employee.reporting, 'api', lambda *args: updates.append(args))
    monkeypatch.setattr(employee, 'signed_execution', lambda *args: {'test_receipt': True})
    employee.reporting.finish(session_id='issue-session', turn_id='turn', completed=True)
    payload = updates[-1][2]
    assert payload['status'] == 'blocked'
    assert 'not accepted as completed work' in payload['comment']
    assert 'No successful terminal execution' in payload['comment']


def test_native_multiline_comment_contract_preserves_json_escapes(employee, monkeypatch):
    import json
    turn = {'company': '11111111-1111-4111-8111-111111111111', 'issue': '33333333-3333-4333-8333-333333333333',
        'agent': '22222222-2222-4222-8222-222222222222', 'run': 'native-run', 'session': 'issue-session'}
    monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', 'synthetic-master-signing-key')
    writes = []
    monkeypatch.setattr(employee.reporting, 'api', lambda *args: writes.append(args))
    employee.journal(turn, {'tool': 'terminal', 'tool_call_id': 'real-call', 'success': True,
        'args': {'command': 'printf "line\\n"'}, 'result': {'output': 'line\nnext', 'exit_code': 0}})
    body = writes[0][2]['body']
    # Paperclip normalizes escaped newlines only in single-line input.
    normalized = body if '\n' in body else body.replace('\\n', '\n')
    line = next(line for line in normalized.splitlines() if line.startswith('JARVIS_TOOL_EVENT='))
    receipt = json.loads(line.split('=', 1)[1])
    assert receipt['result']['output'] == 'line\nnext'
    assert receipt['args']['command'] == 'printf "line\\n"'
    assert employee.reporting.authentic_evidence(receipt)


@pytest.mark.parametrize('command', ['cd /workspace/issues/truncated-uuid && pwd',
    'cat /workspace/issues/current/../foreign/result.json'])
def test_terminal_rejects_mistyped_or_foreign_issue_paths(employee, monkeypatch, command):
    turn = {'agent': 'employee', 'session': 'issue-session', 'workspace': '/workspace/issues/current'}
    monkeypatch.setattr(employee.reporting, 'current_turn', lambda: turn)
    result = employee.guard(tool_name='terminal', args={'command': command}, session_id='issue-session')
    assert result['action'] == 'block' and employee.workspace_bindings == []


def test_terminal_cwd_is_enforced_every_call_and_effective_args_are_recorded(employee, monkeypatch):
    turn = {'agent': 'employee', 'session': 'issue-session', 'workspace': '/workspace/issues/current'}
    monkeypatch.setattr(employee.reporting, 'current_turn', lambda: turn)
    for n in range(2):
        result = employee.guard(tool_name='terminal', args={'command': 'python3 test_demo.py'},
            session_id='issue-session', tool_call_id=str(n))
        assert result == {'action': 'modify', 'args': {'workdir': turn['workspace']}}
        assert turn['scoped_calls'][str(n)]['args']['workdir'] == turn['workspace']
