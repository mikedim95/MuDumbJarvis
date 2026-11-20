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


def test_verified_success_records_actual_reply_and_clears_prior_blocker(monkeypatch):
    api, result = start(monkeypatch)
    assert result is None
    api.side_effect = None
    reporting.response(session_id=session, assistant_response='Actual runtime result')
    reporting.finish(session_id=session, completed=True)
    assert api.call_args.args == ('PATCH', '/issues/' + issue,
        {'status': 'done', 'comment': 'Actual runtime result', 'unblockDescriptor': None}, 'real-run')


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
    assert api.call_args.args[2] == {'status': 'done', 'comment': 'Retrieved result', 'unblockDescriptor': None}


def test_inventory_reply_without_actual_tool_is_blocked(monkeypatch):
    api, _ = start(monkeypatch, description='List installed Ollama models')
    api.side_effect = None
    reporting.response(session_id=session, assistant_response='An invented inventory')
    reporting.finish(session_id=session, completed=True)
    payload = api.call_args.args[2]
    assert payload['status'] == 'blocked'
    assert 'no successful local_ollama_models call' in payload['comment']
    assert payload['unblockDescriptor']['owner'] == {'agentId': agent}


def test_research_handoff_does_not_require_every_available_tool(monkeypatch):
    description=('OBJECTIVE:\nExpand reconnaissance knowledge to ten tools.\n\n'
        'EXPECTED OUTCOME:\nA source-backed ten-tool catalog.\n\n'
        'AVAILABLE TOOLS:\nlocal_ollama_models, research_sources, publish_artifact\n\n'
        'ACCEPTANCE CRITERIA:\nVerify the original research artifacts.\n\n'
        '[JARVIS CEO CORRECTION abc]\nDo not call local_ollama_models; this is not an inventory task.')
    api,_=start(monkeypatch,description=description)
    api.side_effect=None
    assert not reporting.current_turn()['needs_inventory']
    reporting.response(session_id=session,assistant_response='The research evidence is verified.')
    reporting.finish(session_id=session,completed=True)
    assert api.call_args.args[2]['status']=='done'


def test_structured_inventory_still_requires_the_actual_inventory_call(monkeypatch):
    api,_=start(monkeypatch,description='OBJECTIVE:\nList installed Ollama models.\n\nAVAILABLE TOOLS:\nlocal_ollama_models')
    api.side_effect=None
    reporting.response(session_id=session,assistant_response='An invented inventory')
    reporting.finish(session_id=session,completed=True)
    assert api.call_args.args[2]['status']=='blocked'


def test_negated_inventory_mentions_are_not_an_inventory_request():
    for description in ('Do not call local_ollama_models.',
        'This is public-source research, not an Ollama model inventory.',
        'No inventory of installed models is needed.'):
        assert not reporting.inventory_required(description)


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


def test_failed_worker_callback_uses_its_own_agent_as_blocker_owner(monkeypatch):
    api, _ = start(monkeypatch)
    api.side_effect = None
    reporting.response(session_id=session, assistant_response='Partial runtime output')
    reporting.finish(session_id=session, completed=True, failed=True, turn_exit_reason='tool failure')
    payload = api.call_args.args[2]
    assert payload['status'] == 'blocked'
    assert payload['unblockDescriptor']['owner'] == {'agentId': agent}
    assert payload['unblockDescriptor']['action'].strip()


def test_interrupted_worker_callback_never_assigns_blocker_to_board(monkeypatch):
    api, _ = start(monkeypatch)
    api.side_effect = None
    reporting.finish(session_id=session, completed=False, interrupted=True, turn_exit_reason='operator cancellation')
    payload = api.call_args.args[2]
    assert payload['status'] == 'blocked'
    assert payload['unblockDescriptor']['owner'] == {'agentId': agent}
