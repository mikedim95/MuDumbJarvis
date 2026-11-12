import importlib.util
from pathlib import Path
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor

path = Path(__file__).resolve().parents[1] / 'hermes-plugin/jarvis_readonly/paperclip_reporting.py'
spec = importlib.util.spec_from_file_location('reporting', path)
reporting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporting)
company = '11111111-1111-4111-8111-111111111111'
agent = '22222222-2222-4222-8222-222222222222'
issue = '33333333-3333-4333-8333-333333333333'
session = f'paperclip:company:{company}:agent:{agent}:issue:{issue}'


def start(monkeypatch, assignee=agent, description=''):
    api = Mock(side_effect=[{'id': agent, 'companyId': company},
        {'companyId': company, 'assigneeAgentId': assignee, 'executionRunId': 'real-run', 'description': description}, {}])
    monkeypatch.setattr(reporting, 'api', api)
    result = reporting.begin(session_id=session)
    return api, result


def test_direct_chat_cannot_change_paperclip(monkeypatch):
    api = Mock()
    monkeypatch.setattr(reporting, 'api', api)
    reporting.begin(session_id='api_direct_chat')
    reporting.response(session_id='api_direct_chat', assistant_response='Hello')
    reporting.finish(session_id='api_direct_chat', completed=True)
    api.assert_not_called()


def test_wrong_assignment_blocks_execution(monkeypatch):
    api, result = start(monkeypatch, assignee='someone-else')
    assert result['action'] == 'block'
    assert api.call_count == 2


def test_verified_success_records_actual_reply(monkeypatch):
    api, result = start(monkeypatch)
    assert result is None
    api.side_effect = None
    reporting.response(session_id=session, assistant_response='Actual runtime result')
    reporting.finish(session_id=session, completed=True)
    assert api.call_args.args == ('PATCH', '/issues/' + issue,
        {'status': 'done', 'comment': 'Actual runtime result'}, 'real-run')


def test_failed_execution_never_marks_done(monkeypatch):
    api, _ = start(monkeypatch)
    api.side_effect = None
    reporting.response(session_id=session, assistant_response='Partial output')
    reporting.finish(session_id=session, completed=True, failed=True, turn_exit_reason='tool failure')
    assert api.call_args.args[2]['status'] == 'blocked'


def test_callbacks_on_separate_workers_keep_turn_identity(monkeypatch):
    with ThreadPoolExecutor(1) as worker:
        api, _ = worker.submit(start, monkeypatch).result()
    api.side_effect = None
    with ThreadPoolExecutor(1) as worker:
        worker.submit(reporting.response, session_id=session, assistant_response='Retrieved result').result()
    with ThreadPoolExecutor(1) as worker:
        worker.submit(reporting.finish, session_id=session, completed=True).result()
    assert api.call_args.args[2] == {'status': 'done', 'comment': 'Retrieved result'}


def test_inventory_reply_without_actual_tool_is_blocked(monkeypatch):
    api, _ = start(monkeypatch, description='List installed Ollama models')
    api.side_effect = None
    reporting.response(session_id=session, assistant_response='An invented inventory')
    reporting.finish(session_id=session, completed=True)
    payload = api.call_args.args[2]
    assert payload['status'] == 'blocked'
    assert 'no successful local_ollama_models call' in payload['comment']
    assert payload['unblockDescriptor']['owner'] == 'board'


def test_actual_inventory_tool_unlocks_completion_and_writes_correlated_audit(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    (tmp_path / 'logs').mkdir()
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: tmp_path))
    api, _ = start(monkeypatch, description='List installed Ollama models')
    api.side_effect = None
    reporting.tool_result(tool_name='local_ollama_models', task_id=session,
        result='{"source":"Ollama /api/tags","models":[{"name":"real-model","size_bytes":100}]}')
    reporting.response(session_id=session, assistant_response='Retrieved inventory')
    reporting.finish(session_id=session, completed=True)
    assert api.call_args.args[2]['status'] == 'done'
    assert issue in (tmp_path / 'logs/paperclip-tools.jsonl').read_text()
