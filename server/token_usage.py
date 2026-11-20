"""Read-only, shared sampling of reported chat and workforce token counters."""
import asyncio
from collections import deque
import math
import time

from task_api import Paperclip

INTERVAL = 5
WINDOW = 60


def count(value):
    return int(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else 0


async def workforce_counts():
    p=Paperclip()
    try:
        rows=await asyncio.wait_for(p.request('GET',f'companies/{p.company}/costs/by-agent?period=all'),timeout=3)
        return {'input':sum(count(row.get('inputTokens')) for row in rows),
                'output':sum(count(row.get('outputTokens')) for row in rows)}
    finally:
        await p.http.aclose()


class Meter:
    def __init__(self):
        self.lock=asyncio.Lock();self.last=None;self.baseline=None;self.native=None
        self.points=deque(maxlen=120);self.cached=None

    async def sample(self, local_usage, *, native_reader=workforce_counts, clock=time.time, monotonic=time.monotonic):
        async with self.lock:
            now=clock();tick=monotonic()
            if self.cached is not None and self.last is not None and tick-self.last<INTERVAL:
                return self.cached
            local=local_usage().get('total') or {}
            chat={'input':count(local.get('llm_in')),'output':count(local.get('llm_out'))}
            complete=True
            try:self.native=await native_reader()
            except Exception:complete=False
            native=self.native or {'input':0,'output':0}
            totals={name:chat[name]+count(native.get(name)) for name in ('input','output')}
            total=sum(totals.values());rate=None
            if complete and self.baseline is not None and self.last is not None:
                elapsed=tick-self.last
                deltas=[totals[name]-self.baseline[name] for name in ('input','output')]
                if 0<elapsed<=INTERVAL*3 and all(delta>=0 for delta in deltas):rate=round(sum(deltas)/elapsed,2)
            # Missing data and reset counters create gaps, never invented activity.
            self.baseline=totals if complete else None;self.last=tick
            self.points.append([now,rate])
            while self.points and self.points[0][0]<now-WINDOW-INTERVAL:self.points.popleft()
            self.cached={'at':now,'status':'ok' if complete else 'partial',
                'total_tokens':total,'input_tokens':totals['input'],'output_tokens':totals['output'],
                'tokens_per_second':rate,'window_seconds':WINDOW,'interval_seconds':INTERVAL,
                'points':list(self.points),'source':'Reported chat usage and native Paperclip agent costs'}
            return self.cached


meter=Meter()
