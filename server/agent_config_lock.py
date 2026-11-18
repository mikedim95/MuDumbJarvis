"""Serialize native configuration writes from the HUD and host reconciler."""
import asyncio
from contextlib import contextmanager, asynccontextmanager
import fcntl
import os
from pathlib import Path
from uuid import UUID


def _open(agent_id):
    identifier=str(UUID(str(agent_id)))
    directory=Path(os.environ.get('JARVIS_AGENT_CONFIG_LOCK_DIR',str(Path(__file__).parent/'logs'/'agent-config-locks')))
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    return os.open(directory/(identifier+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)


@contextmanager
def lock(agent_id):
    descriptor=_open(agent_id)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


@asynccontextmanager
async def async_lock(agent_id):
    descriptor=_open(agent_id)
    try:
        while True:
            try:
                fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(.05)
        yield
    finally:
        os.close(descriptor)
