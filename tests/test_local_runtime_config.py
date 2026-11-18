"""Model selection must never turn a bounded local route into a remote route."""
import importlib.util
from pathlib import Path

import pytest
import yaml

source = Path(__file__).resolve().parents[1] / 'deploy/select_ollama_profile.py'
spec = importlib.util.spec_from_file_location('local_model_config_under_test', source)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


@pytest.mark.parametrize('change', ['legacy', 'named', 'remote_endpoint', 'expanded_budget', 'other_provider'])
def test_selection_keeps_the_reviewed_local_endpoint_and_output_bound(tmp_path, change):
    config = {'model': {'default': 'jarvis-example:7b', 'provider': 'custom',
        'base_url': selector.LOCAL_BASE_URL, 'context_length': 65536, 'ollama_num_ctx': 65536}}
    if change != 'legacy':
        config['model']['provider'] = 'custom:jarvis-local-ollama'
        config['providers'] = {'jarvis-local-ollama': {'api': selector.LOCAL_BASE_URL,
            'api_key': 'ollama-local-only', 'extra_body': {'max_tokens': 768}}}
    if change == 'remote_endpoint':
        config['providers']['jarvis-local-ollama']['api'] = 'https://remote.example/v1'
    elif change == 'expanded_budget':
        config['providers']['jarvis-local-ollama']['extra_body']['max_tokens'] = 8192
    elif change == 'other_provider':
        config['model']['provider'] = 'custom:other'
    path = tmp_path / 'config.yaml'; path.write_text(yaml.safe_dump(config))
    if change in ('legacy', 'named'):
        observed = selector.snapshot(tmp_path, Path('config.yaml'))
        assert observed['data'] == config
    else:
        with pytest.raises(selector.ProfileError, match='fixed local'):
            selector.snapshot(tmp_path, Path('config.yaml'))
