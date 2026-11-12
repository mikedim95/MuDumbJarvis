"""Narrow read-only tool; no model-controlled URL, path, command or credentials."""
import json
import os
import time
import urllib.request

from hermes_constants import get_hermes_home


def local_ollama_models(args: dict, **kwargs) -> str:
    if os.environ.get('JARVIS_AGENT_ROLE') == 'ceo':
        from . import paperclip_reporting
        if paperclip_reporting.current_turn().get('plan_decision') != 'self':
            return json.dumps({'status': 'not_executed',
                'reason': 'Direct CEO inventory requires a recorded self decision. Delegated objectives use the existing worker.',
                'next': 'Use paperclip_ceo to assign the scoped child, then end with a short waiting update. When the child is done, review its signed evidence. Do not produce an inventory report before that review.'})
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
    from . import paperclip_reporting
    paperclip_reporting.register(ctx)
    if os.environ.get('JARVIS_AGENT_ROLE') == 'ceo':
        from . import ceo_tools
        ceo_tools.register(ctx)
    ctx.register_tool(name='local_ollama_models', toolset='jarvis_readonly',
        schema={'name': 'local_ollama_models',
                'description': 'Retrieve the ACTUAL installed local Ollama models, their exact names, sizes in bytes and GiB, and architecture details. Always call this tool before answering questions about installed models. Never guess the inventory.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        handler=local_ollama_models)
