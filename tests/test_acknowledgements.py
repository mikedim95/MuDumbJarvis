"""Contact proofs must not masquerade as research, tests or other work."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from test_employee_guard import employee
from test_ceo_tools import plugin, modern_child, COMPANY, ROOT, CHILD, WORKER

spec = importlib.util.spec_from_file_location('acknowledgements_test', Path(__file__).resolve().parents[1] /
    'hermes-plugin/jarvis_readonly/acknowledgements.py')
ack = importlib.util.module_from_spec(spec); spec.loader.exec_module(ack)

GOAL = 'this is your first manual goal. speak with every agent of yours like a ping. report ping from all of them'
PING = ('[JARVIS REQUEST initial]\nCEO ping for JAR-59. Reply with PONG, your registered name and role, '
    'and a brief acknowledgment that you received this task. Acceptance: actual worker response recorded '
    'in the completed child. This is a communication check only; no code or tests needed.')


@pytest.mark.parametrize('negative', ['no code or tests needed', 'no research or inventory needed',
    'no analysis or tests needed', 'no diagnostics, inventory, or other actions needed'])
def test_ping_only_scope_is_distinct_from_unneeded_capability_work(negative):
    assert ack.communication_only(GOAL)
    assert ack.communication_only(PING.replace('no code or tests needed',negative),explicit=True)


@pytest.mark.parametrize('extra', ['Also execute tests.', 'Also build a demo.', 'And research garak.',
    'Run a terminal command.', 'Ping 8.8.8.8.', 'Fetch https://example.com.', 'Write a report with scan results.',
    'No tests needed but execute the code.', 'Use `python3 script.py`.'])
def test_mixed_or_network_ping_tasks_are_never_communication_exempt(extra):
    assert not ack.communication_only(PING+' '+extra,explicit=True)


def test_child_cannot_select_acknowledgment_under_a_substantive_parent_goal():
    parent={'id':ROOT,'companyId':COMPANY,'projectId':'project','description':GOAL}
    child={'parentId':ROOT,'companyId':COMPANY,'projectId':'project','description':PING}
    assert ack.assignment(child,parent)
    assert not ack.assignment(child,{**parent,'description':'Build code, execute tests, then ping every worker.'})
    assert not ack.assignment({**child,'projectId':'other'},parent)
    assert not ack.assignment(child,{**parent,'companyId':'other'})
    assert not ack.assignment({**child,'parentId':None},parent)


def identity_turn(profile):
    turn={'task_kind':'acknowledgement','agent':WORKER,'company':COMPANY,'issue':CHILD,'run':'worker-run',
        'session':'worker-session','response':'PONG — JARVIS Worker received the ping.'}
    identity={'agent_id':WORKER,'company_id':COMPANY,'issue_id':CHILD,'paperclip_run_id':'worker-run',
        'name':'JARVIS Worker','role':'general','profile':profile}
    turn['employee_execution']=[{'tool':'agent_identity','success':True,'args':{},'result':identity}]
    return turn


@pytest.mark.parametrize('profile',['research','software_development','system_administration','security_analysis'])
def test_acknowledgment_requires_real_issue_and_run_bound_identity_for_every_role(employee,monkeypatch,profile):
    monkeypatch.setenv('JARVIS_PROFILE',profile);turn=identity_turn(profile)
    assert employee.missing_execution(turn) is None
    for field in ['agent_id','company_id','issue_id','paperclip_run_id','profile']:
        forged=copy.deepcopy(turn);forged['employee_execution'][0]['result'][field]='foreign'
        assert employee.missing_execution(forged)
    forged=copy.deepcopy(turn);forged['employee_execution']=[]
    assert employee.missing_execution(forged)
    forged=copy.deepcopy(turn);forged['response']='I plan to reply later.'
    assert employee.missing_execution(forged)
    turn['task_kind']='work'
    assert employee.missing_execution(turn)  # Identity still cannot complete work.


def test_acknowledgment_tool_guard_cannot_run_shell_or_capability_work(employee,monkeypatch):
    turn=identity_turn('software_development');turn['agent']='employee';turn['session']='issue-session'
    monkeypatch.setattr(employee.reporting,'current_turn',lambda:turn)
    monkeypatch.setattr(employee,'journal',lambda *args:None)
    assert employee.guard(tool_name='agent_identity',args={},session_id='issue-session') is None
    assert employee.guard(tool_name='terminal',args={'command':'python3 -V'},session_id='issue-session')['action']=='block'
    assert employee.workspace_bindings==[]


def test_worker_preflight_requires_both_native_scopes_before_using_communication_semantics(employee,monkeypatch):
    turn=identity_turn('software_development');issue={'id':CHILD,'companyId':COMPANY,'projectId':'project',
        'parentId':ROOT,'description':PING}
    parent={'id':ROOT,'companyId':COMPANY,'projectId':'project','description':GOAL}
    monkeypatch.setattr(employee.reporting,'api',lambda method,path:parent)
    context=employee.prepare_turn_context(turn,issue)
    assert turn['task_kind']=='acknowledgement' and turn['needs_artifact'] is False
    assert 'Call agent_identity' in context and 'No artifact is required' in context


@pytest.mark.parametrize('profile',['research','software_development','system_administration','security_analysis'])
def test_ceo_verifies_actual_contact_receipt_without_demanding_unrelated_artifacts(plugin,monkeypatch,profile):
    child,proof=modern_child(plugin,monkeypatch)
    item=plugin.tools.profile_registry.profile(profile)
    plugin.issue['description']=GOAL;child['description']=PING
    plugin.employees[0].update(name='JARVIS Worker',role='general',metadata={'jarvis':{
        'profile':profile,'profile_sha256':item['sha256']}})
    identity=identity_turn(profile)['employee_execution'][0]['result']
    proof.update(task_kind='acknowledgement',profile=profile,profile_sha256=item['sha256'],model=item['model'],
        artifacts=[],tool_calls=[{'tool':'agent_identity','success':True,'result':identity}],
        acknowledgement={'reply':'PONG — JARVIS Worker received the ping.','identity':identity})
    proof.pop('signature',None);proof=plugin.reporting.sign_evidence(proof)
    plugin.child_comments[CHILD][0]['body']='PONG — JARVIS Worker received the ping.\nJARVIS_EXECUTION_EVIDENCE='+json.dumps(proof)
    verified=plugin.tools.verified_children(plugin.turn,[child]);assert len(verified)==1
    plugin.issue['description']='Build and test a program, and also ping every worker.'
    with pytest.raises(ValueError,match='substantive work'):
        plugin.tools.verified_children(plugin.turn,[child])
    plugin.issue['description']=GOAL
    plugin.employees[0]['metadata']['jarvis']['name_history']=[{'name':'JARVIS Worker'}]
    plugin.employees[0]['name']='JARVIS OSINT'
    assert len(plugin.tools.verified_children(plugin.turn,[child]))==1
    plugin.employees[0]['metadata']['jarvis']['name_history']=[]
    plugin.employees[0]['name']='A different employee'
    with pytest.raises(ValueError,match='registered employee'):
        plugin.tools.verified_children(plugin.turn,[child])
