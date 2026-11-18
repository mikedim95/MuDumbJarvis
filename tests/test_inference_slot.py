import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

path = Path(__file__).resolve().parents[1] / 'hermes-plugin/jarvis_readonly/inference_slot.py'
spec = importlib.util.spec_from_file_location('inference_slot_under_test', path)
slot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slot)


@pytest.fixture
def configured(tmp_path, monkeypatch):
    lock = tmp_path / 'inference.lock'
    lock.touch(mode=0o600)
    monkeypatch.setenv('JARVIS_INFERENCE_LOCK', str(lock))
    monkeypatch.setenv('JARVIS_INFERENCE_WAIT_SECONDS', '3')
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'profile'))
    return lock


def test_registers_supported_execution_middleware_without_a_waiting_observer(configured):
    class Context:
        def __init__(self): self.hooks = []; self.middleware = []
        def register_hook(self, name, callback): self.hooks.append((name, callback))
        def register_middleware(self, name, callback): self.middleware.append((name, callback))
    context = Context(); slot.register(context)
    assert context.hooks == [('pre_llm_call', slot.preflight)]
    assert context.middleware == [('llm_execution', slot.execute)]
    assert slot.preflight() is None


@pytest.mark.parametrize('exception', [RuntimeError('provider failed'), InterruptedError('cancelled'), SystemExit('worker exit')])
def test_downstream_error_and_cancellation_release_slot(configured, exception):
    def failing(request): raise exception
    with pytest.raises(type(exception), match=str(exception)):
        slot.execute({}, failing, session_id='session', turn_id='turn', api_request_id='failed-call')
    assert slot.execute({'ok': True}, lambda request: request) == {'ok': True}


@pytest.mark.parametrize('invalid', ['absent', 'directory', 'symlink', 'relative'])
def test_missing_or_invalid_operator_mount_fails_closed_without_provider_call(configured, monkeypatch, invalid):
    if invalid == 'absent': configured.unlink()
    elif invalid == 'directory': configured.unlink(); configured.mkdir()
    elif invalid == 'symlink':
        target = configured.with_suffix('.target'); target.touch(); configured.unlink(); configured.symlink_to(target)
    else: monkeypatch.setenv('JARVIS_INFERENCE_LOCK', 'relative.lock')
    called = []
    assert slot.preflight()['action'] == 'block'
    response = slot.execute({}, lambda request: called.append(request))
    assert called == [] and response.status == 'failed'
    assert response.output == [] and response.choices == [] and response.output_text == ''
    assert 'No model request was sent' in response.error['message']


def test_busy_slot_timeout_does_not_call_provider(configured, monkeypatch):
    import fcntl
    fd = os.open(configured, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        monkeypatch.setenv('JARVIS_INFERENCE_WAIT_SECONDS', '0.05')
        called = []
        response = slot.execute({}, lambda request: called.append(request))
        assert called == [] and response.status == 'failed'
        assert 'wait_timeout' in response.error['message']
    finally: os.close(fd)
    assert slot.execute({}, lambda request: 'real-result') == 'real-result'


def test_unexpected_acquisition_failure_cannot_trigger_middlewares_fail_open_path(configured, monkeypatch):
    def broken_lock(): raise RuntimeError('unexpected acquisition error')
    monkeypatch.setattr(slot, '_open_lock', broken_lock)
    called = []
    assert slot.preflight()['action'] == 'block'
    assert slot.execute({}, lambda request: called.append(request)).status == 'failed'
    assert called == []


def test_log_serialization_failure_never_bypasses_resource_limit(configured):
    # Additive hook fields must not make a logger exception escape before next_call.
    assert slot.execute({}, lambda request: 'actual', session_id=object()) == 'actual'


@pytest.mark.parametrize('seconds', ['-1', '901', 'nan', 'inf', 'invalid'])
def test_invalid_wait_config_cannot_bypass_slot(configured, monkeypatch, seconds):
    monkeypatch.setenv('JARVIS_INFERENCE_WAIT_SECONDS', seconds)
    assert slot.preflight()['action'] == 'block'
    called = []
    assert slot.execute({}, lambda request: called.append(request)).status == 'failed'
    assert called == []


def _contender(lock, home, index, events):
    os.environ['JARVIS_INFERENCE_LOCK'] = lock
    os.environ['JARVIS_INFERENCE_WAIT_SECONDS'] = '5'
    os.environ['HERMES_HOME'] = home
    def provider(request):
        events.put(('start', index, time.monotonic()))
        time.sleep(0.06)
        events.put(('end', index, time.monotonic()))
        return request
    assert slot.execute({'index': index}, provider, session_id='session-' + str(index),
        task_id='paperclip-issue-' + str(index), turn_id='turn-' + str(index),
        api_request_id='call-' + str(index), provider='openai-codex', model='gpt-6.1-sol') == {'index': index}


def test_four_process_profiles_share_exactly_one_physical_inference_slot(configured, tmp_path):
    context = multiprocessing.get_context('fork'); events = context.Queue()
    workers = [context.Process(target=_contender, args=(str(configured), str(tmp_path / ('profile-' + str(i))), i, events)) for i in range(4)]
    for worker in workers: worker.start()
    observed = [events.get(timeout=8) for _ in range(8)]
    for worker in workers: worker.join(timeout=8); assert worker.exitcode == 0
    active = 0; peak = 0
    for event, _, _ in sorted(observed, key=lambda value: value[2]):
        active += 1 if event == 'start' else -1
        assert active in (0, 1)
        peak = max(peak, active)
    assert active == 0 and peak == 1
    for i in range(4):
        journal = [json.loads(line) for line in (tmp_path / ('profile-' + str(i)) / 'logs/inference-slot.jsonl').read_text().splitlines()]
        assert [entry['event'] for entry in journal] == ['inference_slot.queued', 'inference_slot.acquired', 'inference_slot.released']
        assert all(entry['task_id'] == 'paperclip-issue-' + str(i) for entry in journal)
        assert all(entry['api_request_id'] == 'call-' + str(i) for entry in journal)
        assert not any('request' in entry or 'response' in entry or 'token' in entry for entry in journal)


def _hold_until_killed(lock, ready):
    import fcntl
    fd = os.open(lock, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    ready.set()
    time.sleep(10)


def test_process_death_releases_kernel_slot_without_manual_state(configured):
    context = multiprocessing.get_context('fork'); ready = context.Event()
    worker = context.Process(target=_hold_until_killed, args=(str(configured), ready))
    worker.start()
    try:
        assert ready.wait(3)
        worker.kill(); worker.join(3)
        assert worker.exitcode != 0
        assert slot.execute({}, lambda request: 'after-crash') == 'after-crash'
    finally:
        if worker.is_alive(): worker.kill(); worker.join(3)


def test_historical_runtime_without_slot_config_is_unchanged(monkeypatch):
    monkeypatch.delenv('JARVIS_INFERENCE_LOCK', raising=False)
    assert slot.preflight() is None
    assert slot.execute({'request': 1}, lambda request: request) == {'request': 1}


def test_installed_hermes_middleware_failure_contract_without_any_inference(configured, monkeypatch):
    # Run this additionally in the pinned Hermes environment. The portable
    # project test environment need not install the execution runtime itself.
    middleware = pytest.importorskip('hermes_cli.middleware')
    import hermes_cli.plugins as plugins
    def unexpected_skip(*args, **kwargs): pytest.fail('The middleware must return a denial, never fail open')
    manager = SimpleNamespace(_middleware={'llm_execution': [slot.execute]}, _report_hook_failure=unexpected_skip)
    monkeypatch.setattr(plugins, '_delivery_manager', lambda: manager)
    configured.unlink()
    called = []
    response = middleware.run_llm_execution_middleware({}, lambda request: called.append(request))
    assert called == [] and response.status == 'failed' and response.output == []
    assert response.error['code'] == 'jarvis_inference_slot_unavailable'
