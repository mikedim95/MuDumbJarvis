import hashlib
import importlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_employee_work import work, COMPANY, PROJECT, AGENT, ISSUE
from test_project_workspace import board, FIRST, SECOND, CHILD, HEADERS, server, workspace


def test_project_package_owner_controls_and_revision_isolation(board,monkeypatch):
    board.issues[FIRST]['status']='blocked'
    original=board.client.request
    async def request(self,method,path,body=None):
        if method=='PUT' and path.endswith('/'+workspace.development.KEY):
            body={**body,'key':workspace.development.KEY,'issueId':path.split('/')[1],
                  'companyId':self.company,'updatedByUserId':'owner'}
        return await original(self,method,path,body)
    monkeypatch.setattr(board.client,'request',request)
    route='/api/projects/'+FIRST+'/development-packages'
    with TestClient(server.app) as c:
        assert c.get(route).status_code==401
        assert c.put(route,json={'packages':['make']}).status_code==401
        initial=c.get(route,headers=HEADERS).json()
        assert initial['approved']==[] and any(v['command']=='pytest' for v in initial['catalog'])
        put=lambda packages,**extra:c.put(route,json={'packages':packages,**extra},headers=HEADERS)
        assert put(['nmap']).status_code==422 and put(['make','make']).status_code==422
        first=put(['make','python3-pytest']).json()
        assert first['approved']==['make','python3-pytest'] and first==put(['python3-pytest','make']).json()
        assert c.get(route.replace(FIRST,SECOND),headers=HEADERS).json()['approved']==[]
        assert c.get(route.replace(FIRST,CHILD),headers=HEADERS).status_code==404
        assert put([]).status_code==409
        off=put([],expected_revision=first['revision']).json()
        assert off['approved']==[] and off['revision']!=first['revision'] and len(board.writes)==2
        board.issues[FIRST]['description']='[JARVIS GENERAL WORK]\nRecurring general research.'
        assert c.get(route,headers=HEADERS).status_code==404


@pytest.fixture
def tooling(work,monkeypatch):
    pkg=importlib.import_module(work.module.__package__+'.project_packages')
    root=work.issue['parentId'];ceo=str(uuid4())
    project={'id':root,'assigneeAgentId':ceo,'companyId':COMPANY,'projectId':PROJECT,'status':'blocked','description':'Build a demo'}
    work.issue['status']='in_progress'
    work.turn.update(work_scope={'kind':'project','mission_id':root},reports_to=ceo,_scope_issues=[project,work.issue])
    raw=b'#!/bin/sh\nprintf "example test executable\\n"\n'
    digest=hashlib.sha256(raw).hexdigest()
    monkeypatch.setitem(pkg.CATALOG,'python3-pytest',{**pkg.CATALOG['python3-pytest'],'sha256':digest})
    cache=work.home/'cache';cache.mkdir();(cache/digest).write_bytes(raw)
    monkeypatch.setattr(pkg,'CACHE',cache)
    row={'key':pkg.KEY,'issueId':root,'companyId':COMPANY,'updatedByUserId':'owner','latestRevisionId':str(uuid4()),
         'body':json.dumps({'version':1,'packages':{'python3-pytest':digest}})}
    interactions=[]
    def api(method,path,*args):
        assert method=='GET', 'A standing project grant does not create an assignment approval or task'
        if path=='/issues/'+ISSUE:return work.issue
        if path=='/issues/'+root:return project
        if path=='/issues/'+root+'/documents/'+pkg.KEY:return row
        if path=='/issues/'+root+'/interactions':return interactions
        pytest.fail(path)
    monkeypatch.setattr(work.module.reporting,'api',api)
    monkeypatch.setattr(work.module,'upload',lambda *args:{'id':'fixture-native-receipt'})
    def install():
        return json.loads(work.module.publish_artifact({'name':'package-request.json',
            'content':json.dumps({'package':'python3-pytest'})}))['package_install']
    return SimpleNamespace(pkg=pkg,raw=raw,digest=digest,install=install,api=api,project=project,doc=row,
        interactions=interactions,cache=cache,exe=work.home/'workspace/issues'/ISSUE/'.jarvis-bin/pytest')


def test_package_request_installs_approved_binary_on_concurrent_retry(tooling,work):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:tooling.install(),range(2)))
    installed=results[0]
    assert results[1]==installed and installed['command']=='./.jarvis-bin/pytest'
    assert installed['status']=='installed' and installed['sha256']==tooling.digest
    assert installed['policy_revision']==tooling.doc['latestRevisionId'] and installed['mission_id']==work.issue['parentId']
    assert tooling.exe.read_bytes()==tooling.raw and 'action_approval' not in work.turn
    assert list(tooling.exe.parent.iterdir())==[tooling.exe]
    tooling.exe.write_bytes(b'employee-edited file')
    with pytest.raises(ValueError,match='digest'):tooling.install()
    assert tooling.exe.read_bytes()==b'employee-edited file'


@pytest.mark.parametrize('change',['revoked','new_version','another_root','general','hidden','closed','reassigned','foreign'])
def test_assignment_grant_follows_live_mission_and_pinned_version(tooling,work,change):
    if change=='revoked':tooling.doc['body']=json.dumps({'version':1,'packages':{}})
    if change=='new_version':tooling.doc['body']=json.dumps({'version':1,'packages':{'python3-pytest':'0'*64}})
    if change=='another_root':work.turn['work_scope']['mission_id']=str(uuid4())
    if change=='general':tooling.project['description']='[JARVIS GENERAL WORK]\nResearch batch'
    if change=='hidden':tooling.project['hiddenAt']='now'
    if change=='closed':tooling.project['status']='done'
    if change=='reassigned':work.issue['assigneeAgentId']=str(uuid4())
    if change=='foreign':tooling.project['projectId']=str(uuid4())
    policy=tooling.pkg.for_assignment(work.turn,work.issue,tooling.api,refresh=True)
    assert not policy or policy['approved']==[]
    assert not tooling.exe.exists()


def test_grant_must_be_owner_authored_and_job_denial_takes_precedence(tooling,work):
    tooling.doc['updatedByAgentId']=AGENT
    with pytest.raises(ValueError,match='owner'):tooling.install()
    tooling.doc.pop('updatedByAgentId')
    reviews=importlib.import_module(work.module.__package__+'.blocker_review')
    child={**work.issue,'identifier':'JAR-2'}
    decision=reviews.package_confirmation(child,'python3-pytest')
    tooling.interactions.append({**decision,'id':str(uuid4()),'issueId':child['parentId'],'createdByAgentId':work.turn['reports_to'],
                                 'status':'rejected','resolvedByUserId':'owner'})
    assert tooling.install()['status']=='rejected' and not tooling.exe.exists()


def test_install_rejects_modified_payload_or_symlinked_issue_directory(tooling,work):
    (tooling.cache/tooling.digest).write_bytes(b'changed')
    with pytest.raises(ValueError,match='digest'):tooling.install()
    (tooling.cache/tooling.digest).write_bytes(tooling.raw)
    protected=work.home/'private';protected.mkdir()
    (work.home/'workspace').symlink_to(protected,target_is_directory=True)
    with pytest.raises(OSError):tooling.install()
    assert not list(protected.iterdir())


@pytest.mark.skipif(os.environ.get('JARVIS_TEST_OFFLINE_TOOLS')!='1',reason='uses the employee Docker image and operator package cache')
def test_real_approved_tools_execute_in_offline_employee_sandbox(tooling,work,monkeypatch):
    from deploy import provision_packages as provision
    prod=provision.packages.DEVELOPMENT
    pins={name:spec['sha256'] for name,spec in prod.items()}
    tooling.doc['body']=json.dumps({'version':1,'packages':pins})
    base=tooling.api
    def api(method,path,*args):
        if path.endswith('/approvals'):return []
        return base(method,path,*args)
    monkeypatch.setattr(work.module.reporting,'api',api)
    for name,spec in prod.items():
        monkeypatch.setitem(tooling.pkg.CATALOG,name,spec)
        (tooling.cache/spec['sha256']).write_bytes(provision.package_bytes(name))
        result=json.loads(work.module.publish_artifact({'name':'package-request.json',
            'content':json.dumps({'package':name})}))['package_install']
        assert result['status']=='installed' and result['sha256']==pins[name]
    task_dir=work.home/'workspace/issues'/ISSUE
    (task_dir/'addition.py').write_text('def add(a, b): return a + b\n')
    (task_dir/'test_addition.py').write_text('from addition import add\n\ndef test_sum(): assert add(1, 2) == 3\n')
    (task_dir/'Makefile').write_text('check:\n\t./.jarvis-bin/pytest -q test_addition.py\n')
    prefix=['docker','run','--rm','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev','--mount',
            'type=bind,src='+str(task_dir)+',dst=/workspace/task','--workdir','/workspace/task','--entrypoint','/bin/sh',
            'jarvis-command-center:employee-sandbox-v3','-ec']
    cmds='./.jarvis-bin/make check; printf \'{"n":7}\\n\' | ./.jarvis-bin/gojq -e ".n == 7"; printf "echo    ok\\n" | ./.jarvis-bin/shfmt; ./.jarvis-bin/tree -L 1'
    output=subprocess.run([*prefix,cmds],capture_output=True,text=True,timeout=35,check=True).stdout
    assert all(text in output for text in ('1 passed','true','echo ok','test_addition.py'))
    (task_dir/'test_addition.py').write_text('def test_failure(): assert False\n')
    failed=subprocess.run([*prefix,'./.jarvis-bin/pytest -q test_addition.py'],capture_output=True,text=True,timeout=35)
    assert failed.returncode==1 and '1 failed' in failed.stdout
