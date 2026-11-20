"""Real prompt resolution and conflict-checked migration; no production writes."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_codex_workforce_runtime import staffing, COMPANY, CEO

import migrate_prompt_policies as migration

policy=staffing.prompt_policies


@pytest.fixture
def native(tmp_path,monkeypatch):
    monkeypatch.setenv('JARVIS_AGENT_CONFIG_LOCK_DIR',str(tmp_path/'locks'))
    people=[]
    for role in policy.ROLES:
        identifier=CEO if role=='ceo' else str(uuid4())
        item=staffing.registry.profile(role) if role!='ceo' else None
        name='JARVIS '+role
        old=(policy.ROOT/'deploy/JARVIS_CEO_POLICY.md').read_text() if role=='ceo' else policy.legacy_employee(name,item)
        agent={'id':identifier,'companyId':COMPANY,'name':name,'role':'ceo' if role=='ceo' else item['role'],
            'status':'idle','reportsTo':None if role=='ceo' else CEO,
            'adapterConfig':{'instructions':old,'apiKey':{'type':'secret_ref','secretId':'keep'},'timeoutSec':1800},
            'metadata':{'other':'keep','jarvis':{'profile':None if role=='ceo' else role,
                'general_context':{'text':'Owner directions for '+role,'revision':4},
                'inference_configuration':{'provider':'openai-codex','model':'chosen-model','inference_slots':1}}},
            'runtimeConfig':{'heartbeat':{'enabled':False,'maxConcurrentRuns':1}},
            'permissions':{'canCreateAgents':False,'canCreateSkills':False}}
        people.append(agent)
        home=migration.home_for(tmp_path,agent,CEO)
        policy.seed_file(home/'SOUL.md',old)
        if item:
            for skill in item['skills']:policy.seed_file(home/'skills'/skill/'SKILL.md',policy.legacy_skill(item,skill))
    calls=[];runs=[]
    def api(method,path,body=None):
        calls.append((method,path,copy.deepcopy(body)))
        if path=='/companies/'+COMPANY+'/agents':return copy.deepcopy(people)
        if path=='/companies/'+COMPANY+'/live-runs':return copy.deepcopy(runs)
        assert path.startswith('/agents/') and method in ('GET','PATCH')
        a=next(a for a in people if a['id']==path.split('/')[-1])
        if method=='PATCH':a.update(copy.deepcopy(body))
        return copy.deepcopy(a)
    board=SimpleNamespace(api=api,env={'PAPERCLIP_COMPANY_ID':COMPANY,'PAPERCLIP_CEO_AGENT_ID':CEO})
    return SimpleNamespace(board=board,people=people,calls=calls,runs=runs,root=tmp_path)


def test_plan_is_read_only_and_real_defaults_assemble_all_five_roles(native):
    before=copy.deepcopy(native.people)
    plan=migration.make_plan(native.board,native.root)
    assert native.people==before
    assert len(plan['agents'])==5
    assert all(c[0]=='GET' for c in native.calls)
    for e in plan['agents']:
        assert e['native']['after']==policy.assemble(e['role'],e['name'],
            staffing.registry.profile(e['role'])['authority'] if e['role']!='ceo' else '')
        assert len(e['native']['after'])<20000
        assert e['native']['before']!=e['native']['after']
        assert e['files'][0]['after']==policy.identity_soul(e['name'])


def test_apply_and_rollback_touch_only_prompt_fields_and_never_create_work(native):
    before=copy.deepcopy(native.people)
    plan=migration.make_plan(native.board,native.root)
    backup=migration.apply_plan(native.board,plan,native.root)
    assert json.loads(backup.read_text())==plan and backup.stat().st_mode & 0o777==0o600
    for old,a,e in zip(before,native.people,plan['agents']):
        assert {k:v for k,v in a.items() if k not in ('metadata','adapterConfig')}=={
            k:v for k,v in old.items() if k not in ('metadata','adapterConfig')}
        assert a['adapterConfig']=={**old['adapterConfig'],'instructions':e['native']['after']}
        assert a['metadata']['jarvis']['general_context']==old['metadata']['jarvis']['general_context']
        assert a['metadata']['jarvis']['inference_configuration']==old['metadata']['jarvis']['inference_configuration']
        assert staffing.configured_agent_prompt(a,'changed generated default')==e['native']['after']
        home=migration.home_for(native.root,a,CEO)
        for f in e['files']:assert (home/f['path']).read_text()==f['after']
    assert all(method=='GET' or method=='PATCH' and path.startswith('/agents/') for method,path,_ in native.calls)
    migration.rollback(native.board,plan,native.root)
    assert native.people==before
    for a,e in zip(native.people,plan['agents']):
        home=migration.home_for(native.root,a,CEO)
        for f in e['files']:assert ((home/f['path']).read_text() if (home/f['path']).exists() else None)==f['before']


def test_saved_and_unmarked_native_and_local_customizations_are_never_overwritten(native):
    a=native.people[1];custom='Owner-saved specialist prompt, keep every byte.\n'
    a['adapterConfig']['instructions']=custom
    a['metadata']['jarvis']['system_prompts']={'agent':{'text':custom,'sha256':policy.digest(custom)},
        'direct':{'text':'Custom chat prompt','sha256':'retain'}}
    b=native.people[2];b['adapterConfig']['instructions']='Unmarked native UI edit.'
    home=migration.home_for(native.root,b,CEO)
    (home/'SOUL.md').write_text('Manually customized local identity.')
    skill=home/'skills'/policy.ROLES['software_development'][1]/'SKILL.md'
    skill.parent.mkdir(parents=True,exist_ok=True);skill.write_text('Owner procedure.')
    plan=migration.make_plan(native.board,native.root)
    assert plan['agents'][1]['native']['disposition']=='preserved_custom'
    assert plan['agents'][2]['native']['disposition']=='preserved_custom'
    assert plan['agents'][2]['files'][0]['disposition']=='preserved_custom'
    migration.apply_plan(native.board,plan,native.root)
    assert a['adapterConfig']['instructions']==custom
    assert b['adapterConfig']['instructions']=='Unmarked native UI edit.'
    assert (home/'SOUL.md').read_text()=='Manually customized local identity.'
    assert skill.read_text()=='Owner procedure.'
    assert a['metadata']['jarvis']['system_prompts']['agent']['text']==custom


@pytest.mark.parametrize('change',['native','saved','directions','soul','skill','plan'])
def test_conflicting_plan_refuses_all_mutations(native,change):
    plan=migration.make_plan(native.board,native.root)
    a=native.people[-1];home=migration.home_for(native.root,a,CEO)
    if change=='native':a['adapterConfig']['instructions']='Fresh native owner edit'
    elif change=='saved':a['metadata']['jarvis']['system_prompts']={'direct':{'text':'New owner chat prompt'}}
    elif change=='directions':a['metadata']['jarvis']['general_context']['text']='New directions'
    elif change=='soul':(home/'SOUL.md').write_text('New identity')
    elif change=='skill':(home/'skills'/policy.ROLES['security_analysis'][1]/'SKILL.md').write_text('New workflow')
    else:plan['agents'][0]['native']['after']='Tampered plan'
    before=copy.deepcopy(native.people)
    with pytest.raises(ValueError,match='conflict|changed policy'):
        migration.apply_plan(native.board,plan,native.root)
    assert native.people==before and not any(m=='PATCH' for m,*_ in native.calls)


@pytest.mark.parametrize('status',['queued','running'])
def test_busy_agent_defers_without_restarts_or_task_mutations(native,status):
    plan=migration.make_plan(native.board,native.root)
    native.runs.append({'agentId':CEO,'status':status})
    with pytest.raises(ValueError,match='active/queued'):
        migration.apply_plan(native.board,plan,native.root)
    assert all(m=='GET' for m,*_ in native.calls)
    assert not (native.root/'.runtime/backups').exists()


def test_invalid_saved_override_fails_closed_and_local_seeding_preserves_edits(native):
    a=native.people[1]
    a['metadata']['jarvis']['system_prompts']={'agent':{'text':'Owner prompt','sha256':'wrong'}}
    with pytest.raises(ValueError,match='Saved owner'):
        migration.make_plan(native.board,native.root)
    path=native.root/'custom/SOUL.md';policy.seed_file(path,'Owner prompt')
    policy.seed_file(path,'New generated default')
    assert path.read_text()=='Owner prompt'


def test_unmarked_native_edit_wins_over_a_stale_saved_override(native):
    a=native.people[1]
    a['metadata']['jarvis']['system_prompts']={'agent':{'text':'Former saved prompt','sha256':policy.digest('Former saved prompt')}}
    a['adapterConfig']['instructions']='Latest direct native edit'
    assert staffing.configured_agent_prompt(a,'Default')=='Latest direct native edit'


def test_symlinked_files_are_rejected_before_migration(native):
    home=migration.home_for(native.root,native.people[1],CEO)
    (home/'SOUL.md').unlink();(home/'SOUL.md').symlink_to(native.root/'private.txt')
    with pytest.raises(ValueError,match='symlink'):
        migration.make_plan(native.board,native.root)
    assert all(m=='GET' for m,*_ in native.calls)


def test_rollback_preserves_later_owner_edit_instead_of_forcing_old_prompt(native):
    plan=migration.make_plan(native.board,native.root,CEO)
    migration.apply_plan(native.board,plan,native.root)
    native.people[0]['adapterConfig']['instructions']='Owner edit after migration'
    with pytest.raises(ValueError,match='Owner changed'):
        migration.rollback(native.board,plan,native.root)
    assert native.people[0]['adapterConfig']['instructions']=='Owner edit after migration'


def test_reapplying_fresh_plan_is_idempotent_and_does_not_replace_custom_prompt(native):
    plan=migration.make_plan(native.board,native.root)
    migration.apply_plan(native.board,plan,native.root)
    fresh=migration.make_plan(native.board,native.root)
    assert all(e['native']['before']==e['native']['after'] and all(f['before']==f['after'] for f in e['files'])
        for e in fresh['agents'])
    before=copy.deepcopy(native.people)
    migration.apply_plan(native.board,fresh,native.root)
    assert native.people==before and len(native.people)==5


def test_workforce_configurator_rereads_owner_prompt_and_context_under_shared_lock(native,monkeypatch):
    from test_codex_workforce_runtime import workforce
    old=copy.deepcopy(native.people[0])
    current=native.people[0]
    current['adapterConfig']['instructions']='Owner edited this after staging started.'
    current['metadata']['jarvis']['general_context']['text']='Fresh owner preferences.'
    record=current['metadata']['jarvis']['inference_configuration']
    monkeypatch.setattr(staffing,'workforce_record',lambda *a:record)
    workforce.stage_record(native.board,old)
    assert current['adapterConfig']['instructions']=='Owner edited this after staging started.'
    assert current['metadata']['jarvis']['general_context']['text']=='Fresh owner preferences.'
    assert current['metadata']['jarvis']['inference_configuration']==record


def test_shadowed_native_prompt_requires_operator_review_instead_of_false_migration(native):
    native.people[0]['adapterConfig']['payloadTemplate']={'system_message':'Alternate owner system instruction'}
    with pytest.raises(ValueError,match='shadowed'):
        migration.make_plan(native.board,native.root)
    assert all(m=='GET' for m,*_ in native.calls)


def test_initial_skill_seeding_rejects_a_symlinked_parent(native):
    outside=native.root/'outside';outside.mkdir()
    link=native.root/'skills';link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):
        policy.seed_file(link/'new/SKILL.md','Generated procedure')
    assert not (outside/'new').exists()
