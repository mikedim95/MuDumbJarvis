"""Shared knowledge and mission knowledge have independent native lifetimes."""
import copy
import importlib
import json
from hashlib import sha256

import pytest
from test_employee_work import work,COMPANY,PROJECT,AGENT,ARTIFACT


@pytest.fixture
def scopes(work):
    work.scope=importlib.import_module(work.module.__package__+'.work_scope')
    return work


def test_native_routine_scope_survives_description_stamping_and_preserves_other_variables(scopes):
    module=scopes.scope
    custom={'name':'Topic','defaultValue':'retained'}
    routine={'id':'routine','variables':module.variables([custom],'project','mission')}
    assert module.routine_scope(routine)['mission_id']=='mission' and custom in routine['variables']
    assert module.clean_description(module.description('Actual owner goal','general'))=='Actual owner goal'
    assert module.routine_scope({'id':'legacy','variables':[]})['kind']=='general'


def test_workers_inherit_general_or_their_exact_mission_without_accepting_a_child_override(scopes):
    module=scopes.scope
    root={'id':'root','companyId':COMPANY,'description':module.description('Learn tools','general')}
    child={'id':'child','companyId':COMPANY,'parentId':'root','description':'Unrelated text'}
    assert module.classify(child,[root,child])['kind']=='general'
    other={'id':'other','companyId':COMPANY,'description':'A local mission'}
    child.update(parentId='other',description=module.description('Fake promotion','general'))
    assert module.classify(child,[root,other,child])=={'kind':'project','mission_id':'other','routine_id':None}
    assert module.classify({**child,'parentId':'foreign'},[{**root,'id':'foreign','companyId':'another'}])['kind']=='project'


def test_an_execution_keeps_its_stamped_scope_if_a_routine_is_archived_or_removed(scopes):
    mission='77777777-7777-4777-8777-777777777777'
    issue={'id':'run','companyId':COMPANY,'originKind':'routine_execution','originId':'routine',
        'description':scopes.scope.description('Collect local facts','project',mission)}
    assert scopes.scope.classify(issue)['mission_id']==mission
    general={**issue,'description':scopes.scope.description('Shared learning','general')}
    assert scopes.scope.classify(general)['kind']=='general'


@pytest.mark.parametrize('kind',['general','project'])
def test_catalog_lookup_reads_general_and_only_the_current_mission(scopes,monkeypatch,kind):
    from test_public_sources import catalog
    sources=importlib.import_module(scopes.module.__package__+'.public_sources')
    rows=[{'id':'general','companyId':COMPANY,'projectId':PROJECT,'assigneeAgentId':AGENT,
        'createdAt':'2026-11-16','description':scopes.scope.description('Shared','general')},
        {'id':'mission-a','companyId':COMPANY,'projectId':PROJECT,'assigneeAgentId':AGENT,'createdAt':'2026-11-17'},
        {'id':'mission-b','companyId':COMPANY,'projectId':PROJECT,'assigneeAgentId':AGENT,'createdAt':'2026-11-18'}]
    data={row['id']:catalog(3,1) for row in rows}
    for key,value in data.items():value['catalog_version']=key
    raw={key:json.dumps(value).encode() for key,value in data.items()};reads=[]
    def api(method,path,*args):
        assert method=='GET'
        if path.endswith('/issues'):return rows
        issue=path.split('/')[2];reads.append(issue)
        return [{'id':issue,'originalFilename':'osint-catalog-v001.json','createdByAgentId':AGENT,'sha256':sha256(raw[issue]).hexdigest()}]
    monkeypatch.setattr(scopes.module.reporting,'api',api);monkeypatch.setattr(scopes.module,'attachment_bytes',lambda identifier:raw[identifier])
    scopes.turn['work_scope']={'kind':kind,'mission_id':'mission-a' if kind=='project' else None}
    result=json.loads(sources.knowledge(scopes.turn))
    assert 'mission-b' not in reads
    assert {c['work_scope'] for c in result['catalogs']}==({'general','project'} if kind=='project' else {'general'})
    assert scopes.turn['prior_osint_catalog']['catalog_version']==('mission-a' if kind=='project' else 'general')


def test_general_brief_is_available_to_a_different_role_and_excludes_mission_findings(scopes,monkeypatch):
    from test_public_sources import catalog
    knowledge=importlib.import_module(scopes.module.__package__+'.general_knowledge')
    root={'id':'general','companyId':COMPANY,'description':scopes.scope.description('Shared learning','general')}
    worker={'id':'shared-worker','parentId':'general','companyId':COMPANY,'status':'done','createdAt':'2026-11-16'}
    local={'id':'local','companyId':COMPANY,'parentId':'mission','status':'done','createdAt':'2026-11-18'}
    raw=json.dumps(catalog()).encode();reads=[]
    def api(method,path,*args):
        assert method=='GET';reads.append(path)
        assert path=='/issues/shared-worker/attachments'
        return [{'id':ARTIFACT,'originalFilename':'osint-catalog-v001.json','sha256':sha256(raw).hexdigest()}]
    monkeypatch.setattr(scopes.module.reporting,'api',api);monkeypatch.setattr(scopes.module,'attachment_bytes',lambda _:raw)
    turn={**scopes.turn,'agent':'a-different-role'}
    result=knowledge.brief(turn,[root,worker,local],[])
    assert result['total_entries']==15 and result['entries'] and len(json.dumps(result))<2400
    assert reads==['/issues/shared-worker/attachments']
