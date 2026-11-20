import asyncio
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from test_phase1 import server
import token_usage


def test_rates_use_real_deltas_not_historical_totals_and_cache_native_reads():
    async def scenario():
        meter=token_usage.Meter();clock=[1000.0];tick=[0.0]
        local={'total':{'llm_in':100,'llm_out':20}}
        native=AsyncMock(return_value={'input':500,'output':80})
        sample=lambda:meter.sample(lambda:local,native_reader=native,clock=lambda:clock[0],monotonic=lambda:tick[0])
        first=await sample();assert first['total_tokens']==700 and first['tokens_per_second'] is None
        clock[0]+=2;tick[0]+=2;assert await sample()==first and native.await_count==1
        clock[0]+=3;tick[0]+=3;local['total']['llm_out']+=10;native.return_value={'input':550,'output':90}
        second=await sample();assert second['total_tokens']==770 and second['tokens_per_second']==14
        assert second['input_tokens']==650 and second['output_tokens']==120
        assert len(second['points'])==2
    asyncio.run(scenario())


def test_failures_resets_and_long_gaps_never_invent_usage_spikes():
    async def scenario():
        meter=token_usage.Meter();clock=[1000.0]
        native=AsyncMock(return_value={'input':100,'output':10})
        sample=lambda:meter.sample(lambda:{'total':{}},native_reader=native,clock=lambda:clock[0],monotonic=lambda:clock[0])
        await sample();clock[0]+=5;native.side_effect=RuntimeError('unavailable')
        partial=await sample();assert partial['status']=='partial' and partial['total_tokens']==110 and partial['tokens_per_second'] is None
        clock[0]+=5;native.side_effect=None;native.return_value={'input':200,'output':20}
        assert (await sample())['tokens_per_second'] is None
        clock[0]+=5;native.return_value={'input':210,'output':20};assert (await sample())['tokens_per_second']==2
        clock[0]+=5;native.return_value={'input':1,'output':0};assert (await sample())['tokens_per_second'] is None
        clock[0]+=100;native.return_value={'input':999999,'output':900};data=await sample()
        assert data['tokens_per_second'] is None and len(data['points'])==1
    asyncio.run(scenario())


def test_live_endpoint_requires_auth_and_returns_no_runtime_credentials(monkeypatch):
    monkeypatch.setattr(token_usage,'meter',token_usage.Meter())
    # Override the default reader explicitly through the sample wrapper.
    original=token_usage.meter.sample
    async def sample(read):return await original(read,native_reader=AsyncMock(return_value={'input':7,'output':3}))
    monkeypatch.setattr(token_usage.meter,'sample',sample)
    monkeypatch.setattr(server,'read_usage',lambda:{'total':{'llm_in':10,'llm_out':2},'today':{}})
    with TestClient(server.app) as client:
        assert client.get('/api/usage/live').status_code==401
        result=client.get('/api/usage/live',headers={'X-Jarvis-Token':server.hud_token()})
        assert result.status_code==200 and result.json()['total_tokens']==22
        assert result.headers['cache-control']=='no-store'
        assert not any(word in result.text for word in ('api_key','Authorization','Codex','model'))
