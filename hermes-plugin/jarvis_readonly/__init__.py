"""Narrow read-only tool; no model-controlled URL, path, command or credentials."""
import json
import os
import time
import urllib.request

from hermes_constants import get_hermes_home


def local_ollama_models(args: dict, **kwargs) -> str:
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
    return json.dumps({'source': 'Ollama /api/tags', 'models': models})


def register(ctx):
    ctx.register_tool(name='local_ollama_models', toolset='jarvis_readonly',
        schema={'name': 'local_ollama_models',
                'description': 'Retrieve the ACTUAL installed local Ollama models, their exact names, sizes in bytes and GiB, and architecture details. Always call this tool before answering questions about installed models. Never guess the inventory.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        handler=local_ollama_models)
