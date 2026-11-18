"""The runtime reconciler must not overwrite owner edits made while checking containers."""
import asyncio
import copy
from hashlib import sha256
from threading import Thread, Event
from unittest.mock import Mock

import pytest
from test_codex_workforce_runtime import staffing, EMPLOYEE
from test_phase1 import server
import agent_config_lock


def test_runtime_reconciliation_preserves_fresh_notes_custom_prompt_and_name(tmp_path,monkeypatch):
    monkeypatch.setenv('JARVIS_AGENT_CONFIG_LOCK_DIR',str(tmp_path/'locks'))
    text='Use the current owner system prompt.'
    current={'id':EMPLOYEE,'name':'JARVIS OSINT','metadata':{'keep':'yes','jarvis':{
        'profile_sha256':'frozen','general_context':{'text':'Fresh owner directions','revision':4},
        'system_prompts':{'agent':{'text':text,'sha256':sha256(text.encode()).hexdigest()}}}},
        'adapterConfig':{'instructions':text,'apiKey':{'type':'secret_ref','secretId':'keep-reference'},'other':'keep'}}
    before=copy.deepcopy(current);calls=[]
    def api(method,path,body=None):
        calls.append((method,path,copy.deepcopy(body)))
        if method=='PATCH':current.update(copy.deepcopy(body))
        return copy.deepcopy(current)
    board=Mock();board.api.side_effect=api
    staffing.runtime_patch(board,EMPLOYEE,fields={'adapterConfig':{'instructions':'Generated default','timeoutSec':1200}},
        jarvis_updates={'provisioned':True,'runtime_name':'existing-worker'})
    assert current['name']==before['name']
    assert current['metadata']['jarvis']['general_context']==before['metadata']['jarvis']['general_context']
    assert current['metadata']['jarvis']['profile_sha256']=='frozen'
    assert current['adapterConfig']=={**before['adapterConfig'],'timeoutSec':1200}
    assert current['metadata']['jarvis']['provisioned'] is True
    assert calls[0][0]=='GET' and calls[1][0]=='PATCH'


def test_corrupt_saved_prompt_is_reported_instead_of_silently_replaced():
    agent={'metadata':{'jarvis':{'system_prompts':{'agent':{'text':'Owner prompt','sha256':'invalid'}}}}}
    with pytest.raises(ValueError,match='Saved owner system prompt'):
        staffing.configured_agent_prompt(agent,'Generated default')
    assert staffing.configured_agent_prompt({},'Generated default')=='Generated default'


def test_host_and_hud_configuration_writers_share_the_same_lock(tmp_path,monkeypatch):
    monkeypatch.setenv('JARVIS_AGENT_CONFIG_LOCK_DIR',str(tmp_path/'locks'))
    acquired=Event();release=Event();order=[]
    def host_writer():
        with staffing._configuration_lock.lock(EMPLOYEE):
            acquired.set();release.wait(5);order.append('host')
    thread=Thread(target=host_writer);thread.start();assert acquired.wait(5)
    async def scenario():
        async def hud_writer():
            async with agent_config_lock.async_lock(EMPLOYEE):order.append('hud')
        pending=asyncio.create_task(hud_writer())
        await asyncio.sleep(.1);assert order==[]
        release.set();await pending
    try:asyncio.run(scenario())
    finally:release.set();thread.join(5)
    assert order==['host','hud']
