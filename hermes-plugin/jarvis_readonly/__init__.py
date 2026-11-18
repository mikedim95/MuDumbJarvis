"""Narrow read-only tool; no model-controlled URL, path, command or credentials."""
import json
import os
import time
import urllib.request

from hermes_constants import get_hermes_home


def local_ollama_models(args: dict, **kwargs) -> str:
    if os.environ.get('JARVIS_AGENT_ROLE') == 'ceo':
        from . import ceo_tools, paperclip_reporting
        turn, _, issue = ceo_tools.scope()
        if issue.get('projectId') != turn['project']:
            raise PermissionError('Direct inventory objective project mismatch')
        decision = turn.get('plan_decision')
        message = ('Local inventory was NOT executed. No Ollama HTTP request was sent; '
                   'no asynchronous result is pending. ')
        if decision == 'delegate':
            raise ValueError(message + 'Continue the scoped assigned worker task and review verified completed-worker results; do not retrieve a competing CEO inventory.')
        if decision == 'hire':
            raise ValueError(message + 'Follow the human approval process and review only authorized worker results; direct inventory is outside that recorded plan.')
        if decision not in (None, 'self'):
            raise ValueError(message + 'The recorded plan does not authorize direct inventory; read the actual Paperclip state.')
        if ceo_tools.children(turn):
            raise ValueError(message + 'Existing Paperclip child work is the execution path. Use pending worker state or review verified completed-child results instead.')
        if decision is None:
            objective = issue.get('description') or issue.get('title')
            if not isinstance(objective, str) or not objective.strip():
                raise ValueError(message + 'The actual assigned objective is required to record the requested read scope.')
            objective = objective.strip()
            excerpt = objective[:3000]
            if len(objective) > 3000:
                excerpt += '\n[Objective truncated for this record; full text remains on the assigned Paperclip issue.]'
            comment = ("[JARVIS CEO PLAN decision=self]\nRuntime-recorded scope from the model's direct local_ollama_models selection. "
                       'This is not a model-supplied rationale or a separate paperclip_ceo invocation.\nAssigned objective: ' + excerpt +
                       '\nAuthorized requested action: read local Ollama model names and sizes with local_ollama_models, then report verified facts or actual blockers. '
                       'No employee assignment or new permission is created.')
            paperclip_reporting.api('PATCH', '/issues/' + turn['issue'], {'comment': comment}, turn['run'])
            choice = {'timestamp': time.time(), 'source': 'model_direct_tool_choice',
                'tool': 'local_ollama_models', 'action': 'self_execution_selected',
                'issue_id': turn['issue'], 'paperclip_run_id': turn['run'], 'session_id': turn['session'],
                'result': {'recorded': True, 'decision': 'self',
                    'basis': 'The model directly invoked this read-only tool; the runtime recorded its assigned-objective scope before the read.',
                    'separate_paperclip_ceo_invocation': False}}
            choice_log = get_hermes_home() / 'logs' / 'ceo-tools.jsonl'
            choice_log.parent.mkdir(parents=True, exist_ok=True)
            with choice_log.open('a') as stream:
                stream.write(json.dumps(choice) + '\n')
            turn['plan_decision'] = 'self'
    base = os.environ['JARVIS_OLLAMA_URL'].rstrip('/')
    with urllib.request.urlopen(base + '/api/tags', timeout=15) as response:
        data = json.load(response)
    models = [{'name': item['name'], 'size_bytes': item['size'],
               'size_gib': round(item['size'] / 1024 ** 3, 2),
               'details': item.get('details', {})} for item in data.get('models', [])]
    record = {'timestamp': time.time(), 'tool': 'local_ollama_models', 'models': models}
    log = get_hermes_home() / 'logs' / 'jarvis-tools.jsonl'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a') as stream:
        stream.write(json.dumps(record) + '\n')
    result = {'source': 'Ollama /api/tags', 'models': models}
    if os.environ.get('JARVIS_AGENT_ROLE') == 'ceo':
        result['next'] = 'The local tool succeeded. Produce the FINAL technical inventory report NOW: source Ollama /api/tags; a table of each exact model name, provided size_gib and size_bytes; completion and blockers. Copy the provided sizes exactly without recalculation. Do not invent retrieval times, commands or extra capabilities. This is direct CEO execution: do not wait for Paperclip confirmation or nonexistent children.'
    return json.dumps(result)


def register(ctx):
    if os.environ.get('JARVIS_PROFILE'):
        from . import employee_tools
        employee_tools.register(ctx)
    from . import paperclip_reporting
    paperclip_reporting.register(ctx)
    from . import general_context_bridge
    general_context_bridge.register(ctx)
    from . import administration_bridge
    administration_bridge.register(ctx)
    if os.environ.get('JARVIS_AGENT_ROLE') == 'ceo':
        from . import ceo_tools
        ceo_tools.register(ctx)
    description = 'Retrieve the ACTUAL installed local Ollama models, their exact names, sizes in bytes and GiB, and architecture details. Always call this tool before answering questions about installed models. Never guess the inventory.'
    if os.environ.get('JARVIS_AGENT_ROLE') == 'ceo':
        description = ('Retrieve actual local Ollama model names and sizes. For inventory-only work, your direct call is an explicit self-execution choice: '
                       'the runtime records bounded objective/tool scope before the requested read. A separate paperclip_ceo self plan is optional for rationale. '
                       'Do not call this tool for delegated work or to replace verified worker results; review and consolidate those results instead.')
    ctx.register_tool(name='local_ollama_models', toolset='jarvis_readonly',
        schema={'name': 'local_ollama_models',
                'description': description,
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        handler=local_ollama_models)
