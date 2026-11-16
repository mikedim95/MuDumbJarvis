"""Real lifecycle inventory observations become signed native progress only."""
import json
from pathlib import Path
import sys

import pytest

from test_ceo_tools import plugin, COMPANY, CEO, ROOT, SESSION


MODELS = [{'name': 'actual-model:7b', 'size_bytes': 4505856194, 'size_gib': 4.2}]
RESULT = {'source': 'Ollama /api/tags', 'models': MODELS}


def observe(plugin, data=RESULT, session=SESSION, turn_id='turn'):
    plugin.reporting.tool_result(tool_name='local_ollama_models', result=json.dumps(data),
        task_id=session, turn_id=turn_id)


def native_comments(plugin):
    return [call for call in plugin.calls if call[0] == 'PATCH']


def test_actual_ceo_inventory_publishes_signed_current_execution_progress_without_status_change(plugin):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
    import task_monitor
    plugin.turn.update(runtime_model='gpt-6.1-sol', inference_configuration={'provider': 'openai-codex'})
    plugin.issue['status'] = 'in_progress'
    observe(plugin)
    assert plugin.turn['inventory_verified'] and plugin.turn['inventory'] == MODELS
    writes = native_comments(plugin)
    assert len(writes) == 1
    method, path, body, run_id = writes[0]
    assert path == '/issues/' + ROOT and run_id == 'ceo-run'
    assert set(body) == {'comment'}, 'Progress storage must not alter status, assignment or schedule'
    assert body['comment'].startswith('[JARVIS TOOL EVENT]\nJARVIS_TOOL_EVENT=')
    proof = json.loads(body['comment'].split('JARVIS_TOOL_EVENT=', 1)[1])
    assert proof['models'] == MODELS and proof['model'] == 'gpt-6.1-sol'
    assert proof['inference_configuration'] == {'provider': 'openai-codex'}
    assert proof['kind'] == 'tool_event' and proof['company_id'] == COMPANY and proof['issue_id'] == ROOT
    assert proof['agent_id'] == CEO and proof['session_id'] == SESSION and proof['paperclip_run_id'] == run_id
    comment = {'authorAgentId': CEO, 'id': 'native-comment', 'body': body['comment']}
    verified = task_monitor.evidence(comment, plugin.issue,
        [{'runId': 'ceo-run', 'agentId': CEO, 'status': 'running'}], COMPANY)
    assert len(verified) == 1 and verified[0]['verified']
    assert not verified[0]['completion_verified'], 'Progress must never be labelled completion'
    assert verified[0]['tools'] == [{'tool': 'local_ollama_models', 'success': True, 'result': MODELS}]


@pytest.mark.parametrize('bad', [None, [], {}, {'source': 'model guess', 'models': MODELS},
    {'source': 'Ollama /api/tags', 'models': 'invented'},
    {'source': 'Ollama /api/tags', 'models': [{'name': 'bad', 'size_bytes': -1}]},
    {'source': 'Ollama /api/tags', 'models': [{'name': 'bad', 'size_bytes': True}]},
    {'source': 'Ollama /api/tags', 'models': [{}]},
    {**RESULT, 'error': 'HTTP failed'}, {**RESULT, 'isError': True}])
def test_invalid_or_failed_results_do_not_publish_or_unlock_inventory(plugin, bad):
    observe(plugin, bad)
    assert not plugin.turn['inventory_verified']
    assert not native_comments(plugin)


@pytest.mark.parametrize('session,turn_id', [('api_direct_chat', 'turn'), (SESSION, 'wrong-turn')])
def test_wrong_or_direct_chat_session_cannot_create_native_receipt(plugin, session, turn_id):
    observe(plugin, session=session, turn_id=turn_id)
    assert not plugin.turn['inventory_verified'] and not plugin.calls


def test_turn_scope_must_match_authenticated_session_components(plugin):
    plugin.turn['agent'] = 'another-agent'
    observe(plugin)
    assert not plugin.turn['inventory_verified'] and not plugin.calls


@pytest.mark.parametrize('ceo_flag,role', [(False, 'ceo'), (True, 'worker'), (False, 'worker')])
def test_non_ceo_callbacks_keep_existing_tool_audit_but_cannot_publish_ceo_progress(plugin, monkeypatch, ceo_flag, role):
    plugin.turn['ceo'] = ceo_flag
    monkeypatch.setenv('JARVIS_AGENT_ROLE', role)
    observe(plugin)
    assert plugin.turn['inventory_verified']
    assert not plugin.calls


@pytest.mark.parametrize('changed', ['id', 'companyId', 'projectId', 'assigneeAgentId', 'executionRunId', 'cancelled'])
def test_lost_native_execution_ownership_prevents_journal_but_preserves_real_result(plugin, changed, caplog):
    if changed == 'cancelled':
        plugin.issue['status'] = 'cancelled'
    else:
        plugin.issue[changed] = 'other'
    observe(plugin)
    assert not native_comments(plugin)
    assert plugin.turn['inventory_verified'] and plugin.turn['inventory'] == MODELS
    assert 'PermissionError' in plugin.turn['inventory_journal_error']
    assert 'actual tool result remains valid' in caplog.text


def test_repeated_same_turn_inventory_is_deduplicated(plugin):
    observe(plugin); observe(plugin)
    assert len(native_comments(plugin)) == 1
    assert len([c for c in plugin.calls if c[0] == 'GET']) == 1
    assert plugin.turn['inventory_journaled']


def test_uncertain_native_write_failure_is_visible_and_never_retried_implicitly(plugin, monkeypatch, caplog):
    original = plugin.reporting.api
    attempts = []

    def failing(method, path, body=None, run_id=None):
        if method == 'PATCH':
            attempts.append((method, path, body, run_id))
            raise TimeoutError('sensitive internal message that must not be logged')
        return original(method, path, body, run_id)

    monkeypatch.setattr(plugin.reporting, 'api', failing)
    observe(plugin); observe(plugin)
    assert len(attempts) == 1 and not native_comments(plugin)
    assert plugin.turn['inventory_verified'] and plugin.turn['inventory'] == MODELS
    assert 'TimeoutError' in plugin.turn['inventory_journal_error'] and 'failed' in caplog.text
    assert 'sensitive internal message' not in caplog.text
    assert 'inventory_journaled' not in plugin.turn


def test_receipt_only_marker_is_not_rendered_as_an_agent_reply():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
    from csi_events import public_body
    assert public_body('[JARVIS TOOL EVENT]\nJARVIS_TOOL_EVENT={"actual":"signed receipt"}') == ''
    assert public_body('[JARVIS TOOL EVENT]\nJARVIS_TOOL_EVENT={"actual":"signed"}\nPublic update') == 'Public update'
