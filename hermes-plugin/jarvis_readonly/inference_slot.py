"""One cross-process inference slot using Hermes' supported LLM middleware.

The pinned Hermes execution middleware brackets the physical main-model call,
including streaming. Its observer hooks cannot enforce this resource limit.
No tasks or queue database live here: Paperclip retains all orchestration.

Automatic auxiliary LLM features must be disabled in these runtime profiles;
the pinned auxiliary client does not pass through ``llm_execution`` middleware.
"""
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import time
from types import SimpleNamespace


class SlotUnavailable(RuntimeError):
    """The operator-provisioned shared resource could not be acquired."""


def _open_lock():
    path = os.environ.get('JARVIS_INFERENCE_LOCK')
    if not path or not os.path.isabs(path):
        raise SlotUnavailable('An absolute shared inference lock path is required')
    # The operator creates and mounts the existing file. Never create another
    # lock silently when a bind mount or shared-volume configuration is absent.
    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SlotUnavailable('The shared inference lock must be a regular file')
    except BaseException:
        os.close(fd)
        raise
    return fd


def _wait_seconds():
    seconds = float(os.environ.get('JARVIS_INFERENCE_WAIT_SECONDS', '900'))
    if not math.isfinite(seconds) or not 0 <= seconds <= 900:
        raise SlotUnavailable('The shared inference wait limit must be between 0 and 900 seconds')
    return seconds


def _journal(event, context, **details):
    """Inspectible correlation metadata only; no prompts, tokens or credentials."""
    home = os.environ.get('HERMES_HOME')
    if not home:
        return
    record = {'event': event, 'timestamp': time.time(), 'pid': os.getpid(),
        **{key: context.get(key) for key in
           ('session_id', 'task_id', 'turn_id', 'api_request_id', 'provider', 'model')}, **details}
    try:
        directory = Path(home) / 'logs'
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory / 'inference-slot.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC, 0o600)
        try:
            os.write(fd, (json.dumps(record, separators=(',', ':')) + '\n').encode())
        finally:
            os.close(fd)
    except Exception:
        pass  # A log failure never releases the slot early or permits inference.


def preflight(**context):
    """Fail before the model turn when the configured shared file is absent."""
    if not os.environ.get('JARVIS_INFERENCE_LOCK'):
        return None  # Historical local runtime configurations remain unchanged.
    try:
        fd = _open_lock()
        os.close(fd)
        _wait_seconds()
    except Exception:
        _journal('inference_slot.denied', context, reason='configuration_unavailable')
        return {'action': 'block', 'message':
            'JARVIS shared inference slot configuration is unavailable. No model request was sent. '
            'The operator must restore the common lock mount before retrying.'}
    return None


def _failure(reason):
    # Hermes skips middleware callback Exceptions raised before next_call. A
    # failed response instead returns through the supported execution contract
    # without invoking the provider. Pinned Codex response validation rejects
    # status=failed/empty output and surfaces this error through its failure
    # pipeline. This contains no assistant message or simulated model output.
    return SimpleNamespace(status='failed', output=[], output_text='', choices=[], usage=None,
        error={'code': 'jarvis_inference_slot_unavailable', 'message':
            'JARVIS shared inference slot unavailable (' + reason + '). No model request was sent.'})


def execute(request, next_call, **context):
    """Serialize a physical provider request; release on every downstream exit."""
    if not os.environ.get('JARVIS_INFERENCE_LOCK'):
        return next_call(request)
    fd = None
    acquired = False
    started = time.monotonic()
    try:
        try:
            seconds = _wait_seconds()
            fd = _open_lock()
            _journal('inference_slot.queued', context)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as error:
                    if error.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                    remaining = seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        raise SlotUnavailable('wait_timeout') from None
                    time.sleep(min(0.1, remaining))
        except Exception as error:
            reason = 'wait_timeout' if isinstance(error, SlotUnavailable) and str(error) == 'wait_timeout' else 'configuration_unavailable'
            _journal('inference_slot.denied', context, reason=reason,
                waited_seconds=round(time.monotonic() - started, 6))
            return _failure(reason)
        _journal('inference_slot.acquired', context, waited_seconds=round(time.monotonic() - started, 6))
        # Exceptions below next_call are propagated by Hermes as downstream
        # failures, unlike middleware callback exceptions before next_call.
        return next_call(request)
    finally:
        if fd is not None:
            if acquired:
                _journal('inference_slot.released', context)
                # Close releases the kernel flock even after provider errors,
                # interrupts or unexpected exceptions. Process death does too.
            try:
                os.close(fd)
            except OSError:
                pass


def register(ctx):
    if os.environ.get('JARVIS_INFERENCE_LOCK'):
        ctx.register_hook('pre_llm_call', preflight)
        ctx.register_middleware('llm_execution', execute)
