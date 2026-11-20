"""Disposable Hermes image fixture. No model, native task, or live worker credentials required."""
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.path[:0] = ['/opt/hermes', '/plugins']
from agent import tool_executor
from hermes_cli import plugins
from hermes_cli.plugins import PluginContext, PluginManifest
import model_tools
from jarvis_readonly import employee_tools, paperclip_reporting, project_cli

data = json.load(sys.stdin)
turn = data['turn']
turn['scoped_calls'] = {}
os.environ.update(JARVIS_AGENT_PROOF_KEY=data['key'], JARVIS_PAPERCLIP_AGENT_ID=turn['agent'])
project_cli.SOCKET = '/fixture.sock'
paperclip_reporting._turns['fixture'] = turn
manager = plugins._delivery_manager()
employee_tools.register(PluginContext(PluginManifest(name='jarvis_readonly'), manager))
agent = Mock()
agent.session_id = turn['session']
agent._current_turn_id = 'fixture'
agent._current_api_request_id = 'fixture'
agent.conversation_id = 'fixture'
agent._conversation_id = 'fixture'
agent.tool_progress_callback = None
agent._tool_guardrails.before_call.return_value = SimpleNamespace(allows_execution=True)
agent.log_prefix_chars = 20
agent.log_prefix = ''
agent._vprint = lambda *a: None


def dispatch(tool, arguments, ident):
    def run(args):
        return model_tools.handle_function_call(tool, args, task_id='fixture-worker',
            tool_call_id=ident, session_id=agent.session_id, skip_pre_tool_call_hook=True,
            skip_tool_request_middleware=True, skip_tool_execution_middleware=True)
    state = tool_executor._run_agent_tool_execution_middleware(agent, function_name=tool,
        function_args=arguments, effective_task_id='fixture-worker', tool_call_id=ident, execute=run)
    response = json.loads(state.result)
    assert not response.get('error'), response
    return response


where = dispatch('terminal', {'command':'pwd && hostname','timeout':180}, 'placement')
assert where['exit_code'] == 0 and where['output'].split() == ['/project', data['hostname']], where
event = next(e for e in turn['employee_execution'] if e['tool_call_id'] == 'placement')
assert 'workdir' not in event['args'] and event['result']['workdir_source'] == 'project_default'
assert event['args']['timeout'] == 120
lab = dispatch('terminal', {'command':'''set -eu
scratch=$(mktemp /var/tmp/project-write.XXXXXXXX)
trap 'rm -f "$scratch"' EXIT
printf editable > "$scratch"
test "$(cat "$scratch")" = editable
test "$(readlink -f /opt/lab)" = /project
python3 -m venv .demo-env
.demo-env/bin/python -c 'print("environment ready")'
'''}, 'writable-lab')
assert lab['exit_code'] == 0 and 'environment ready' in lab['output'], lab
explicit = dispatch('terminal', {'command':'pwd','workdir':'/project'}, 'explicit')
assert explicit['exit_code'] == 0, explicit
event = next(e for e in turn['employee_execution'] if e['tool_call_id'] == 'explicit')
assert event['args']['workdir'] == '/project' and event['result']['workdir_source'] == 'caller'
written = dispatch('write_file', {'path':'example.txt','content':'fixture bytes\n'}, 'write')
read = dispatch('read_file', {'path':'example.txt'}, 'read')
assert 'fixture bytes' in read['content'], read
result = dispatch('terminal', {'command':'cat example.txt'}, 'shared')
assert result['exit_code'] == 0 and result['output'].strip() == 'fixture bytes', result
offline = dispatch('terminal', {'command':"""python3 -c "import socket; socket.socket()" """}, 'offline')
assert offline['exit_code'] != 0 and 'Operation not permitted' in offline['output'], offline
