import hashlib
import io
import hmac
import importlib
import json
import os
import socketserver
import threading
import sys
import subprocess
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deploy import project_cli_service as service, project_containers as boxes
from test_employee_guard import employee


@pytest.fixture
def assignment(monkeypatch, tmp_path):
    monkeypatch.setattr(boxes, 'LABS', tmp_path / 'labs')
    ids = {k:str(uuid4()) for k in ('company','project','agent','issue','mission','run','ceo')}
    env = {'PAPERCLIP_COMPANY_ID':ids['company'], 'PAPERCLIP_CEO_AGENT_ID':ids['ceo'],
           'JARVIS_EXECUTION_PROOF_KEY':'synthetic-proof'}
    root = {'id':ids['mission'],'companyId':ids['company'],'projectId':ids['project'],
            'assigneeAgentId':ids['ceo'],'status':'blocked'}
    issue = {**root, 'id':ids['issue'], 'parentId':ids['mission'], 'assigneeAgentId':ids['agent'],
             'executionRunId':ids['run'], 'status':'in_progress'}
    records = {root['id']:root, issue['id']:issue}
    worker = {'reportsTo':ids['ceo']}
    jobs = []
    def api(method, path):
        assert method == 'GET'
        if path.startswith('/issues/'):
            return records[path.rsplit('/', 1)[1]]
        if path.startswith('/agents/'):
            return worker
        if path.endswith('/approvals'):
            return []
        if path.endswith('/routines'):
            return jobs
        if '/issues?' in path:
            return list(records.values())
        pytest.fail(path)
    monkeypatch.setattr(service.staffing, 'validate_agent', lambda *args:{'sandbox':True,'tools':['terminal','publish_artifact']})
    turn = {**ids, 'session':'task-session','work_scope':{'kind':'project','mission_id':ids['mission']},
            'workspace':'/workspace/issues/' + ids['issue']}
    return SimpleNamespace(**ids, env=env, root=root, child=issue, records=records, jobs=jobs,
                           worker=worker, board=SimpleNamespace(env=env, api=api), turn=turn)


def test_project_lifecycle_discovers_new_work_and_excludes_general_and_archived(assignment):
    f = assignment
    assert boxes.projects(f.board) == {f.mission}
    second = {**f.root, 'id':str(uuid4())}
    f.records[second['id']] = second
    assert boxes.projects(f.board) == {f.mission, second['id']}
    assert boxes.names(f.mission)[1] == boxes.names(second['id'])[1] == 'jarvis-projects-local'
    assert boxes.names(f.mission)[2] != boxes.names(second['id'])[2]
    second['description'] = '[JARVIS GENERAL WORK]\nObserve agent procedures'
    assert boxes.projects(f.board) == {f.mission}
    f.root['hiddenAt'] = '2026-11-20'
    assert boxes.projects(f.board) == set()


def test_only_provisioned_running_projects_are_kept_after_completion(assignment):
    f = assignment
    f.root['status'] = 'done'
    running = {boxes.names(f.mission)[0]}
    assert boxes.projects(f.board, running) == {f.mission}
    assert not boxes.projects(f.board)
    f.root['status'] = 'cancelled'
    assert not boxes.projects(f.board, running)
    f.root.update(status='done', hiddenAt='archived')
    assert not boxes.projects(f.board, running)


@pytest.mark.parametrize('condition',['active','foreign_run','foreign_mission','completed','hidden','private','general_cron',
                                      'project_cron','reassigned','no_terminal'])
def test_broker_checks_live_native_ancestry_and_actor(assignment, monkeypatch, condition):
    f = assignment
    req = service.wire.message(f.turn, {'workdir':'/project','command':'pwd'})
    if condition == 'foreign_run': req['run'] = str(uuid4())
    if condition == 'foreign_mission': req['mission'] = str(uuid4())
    if condition == 'completed': f.root['status'] = 'done'
    if condition == 'hidden': f.root['hiddenAt'] = 'today'
    if condition == 'private': f.child['privacyRootIssueId'] = f.issue
    if condition == 'reassigned': f.child['assigneeAgentId'] = f.ceo
    if condition == 'no_terminal': monkeypatch.setattr(service.staffing,'validate_agent',lambda *_:None)
    if condition.endswith('_cron'):
        job = {'id':str(uuid4()), 'companyId':f.company, 'projectId':f.project}
        if condition == 'project_cron':
            job['variables'] = boxes.packages.work_scope.variables([], 'project', f.mission)
        f.jobs.append(job)
        f.child.update(parentId=None, originId=job['id'], originKind='routine_execution')
    if condition in ('active','project_cron'):
        service.authorize(f.board, req)
    else:
        with pytest.raises(PermissionError):
            service.authorize(f.board, req)


def test_request_signature_binds_command_project_directory_and_expiry(assignment):
    f = assignment
    req = service.wire.message(f.turn, {'workdir':'/project','command':'pwd'})
    key = hmac.new(f.env['JARVIS_EXECUTION_PROOF_KEY'].encode(),
                   ('jarvis-employee-proof-v3:' + f.agent).encode(), hashlib.sha256).hexdigest()
    proof = service.wire.signature(key, req)
    assert service.verify(f.env, {'proof':proof, 'request':req}) == req
    with pytest.raises(PermissionError):
        service.verify(f.env, {'proof':proof, 'request':{**req,'command':'env'}})
    for bad in ({'time':int(time.time())-80}, {'cwd':'/project/../etc'}, {'timeout':180}):
        altered = {**req, **bad}
        with pytest.raises(ValueError):
            service.verify(f.env, {'proof':service.wire.signature(key, altered),'request':altered})


@pytest.mark.parametrize(('tool', 'args', 'path'), [
    ('terminal', {'command':'pwd'}, '/project'), ('terminal', {'command':'pwd','workdir':'/project/sub'}, '/project/sub'),
    ('write_file', {'path':'hello.py','content':'ok'}, '/project/hello.py'),
    ('read_file', {'path':'/project/shared.txt'}, '/project/shared.txt')])
def test_native_project_guard_defaults_and_fails_closed(employee, assignment, monkeypatch, tool, args, path):
    f = assignment
    monkeypatch.setenv('JARVIS_PAPERCLIP_AGENT_ID', f.agent)
    monkeypatch.setattr(employee.reporting,'current_turn',lambda:f.turn)
    wire = importlib.import_module(employee.__package__ + '.project_cli')
    def guard(params):
        return employee.guard(tool, params, session_id=f.turn['session'], tool_call_id='one')
    assert guard(args)['action'] == 'block'
    token = wire.active_call.set((f.turn, 'one', tool))
    try:
        routed = guard(args)
        assert routed['args']['workdir' if tool == 'terminal' else 'path'] == path
        if tool == 'terminal':
            limited = guard({**args,'timeout':180})
            assert limited['args']['timeout'] == f.turn['scoped_calls']['one']['args']['timeout'] == 120
            for invalid in (False, 0, -1, '120'):
                assert 'positive whole number' in guard({**args,'timeout':invalid})['message']
            assert guard({**args,'workdir':f.turn['workspace']})['action'] == 'block'
    finally:
        wire.active_call.reset(token)
    f.turn['work_scope'] = {'kind':'general','mission_id':None}
    assert employee.guard('terminal',{'command':'pwd'},session_id=f.turn['session'])['args'] == {'workdir':f.turn['workspace']}
    assert employee.guard('terminal',{'command':'pwd','workdir':'/project'},session_id=f.turn['session'])['action'] == 'block'



def test_ready_receipt_remains_visible_after_reworded_blocker():
    from deploy import approved_packages as apt
    import base64
    company, project, parent, child, agent, review = [str(uuid4()) for _ in range(6)]
    scope = apt.receipts.binding(company,project,parent,child,agent,'nmap',review)
    question = {'id':review,'child_id':child,'agent_id':agent,'package':'nmap','answer':'accepted'}
    raw = b'Nmap version fixture\n'
    record = {'scope':scope,'status':'ready','version':'7.95','image':'sha256:'+'a'*64,
              'command':'./.jarvis-bin/nmap','usage':apt.receipts.usage('nmap'),
              'verified_at':'2026-11-20T10:00:00Z','output_sha256':hashlib.sha256(raw).hexdigest(),
              'stdout_base64':base64.b64encode(raw).decode()}
    doc = {'key':apt.receipts.key(review),'companyId':company,'issueId':child,'updatedByUserId':'operator',
           'body':json.dumps(record)}
    def commands(decision):
        return apt.receipts.ready_commands([doc],[decision],company,project,parent,child,agent)
    assert commands(question)['nmap']['probe_command'] == './.jarvis-bin/nmap --version'
    assert not commands({**question,'answer':'rejected'})
    assert not commands({**question,'child_id':str(uuid4())})
    assert apt.reviews.blocker_packages(apt.reviews.REPORT + 'Worker reports incomplete work: blocked. '
        'Operator must complete the already-approved provisioning and expose Nmap in the sandbox before verification can succeed.') == ['nmap']


@pytest.mark.skipif(os.environ.get('JARVIS_TEST_PROJECT_CLI') != '1', reason='opt-in disposable Docker fixtures')
def test_migrate_verify_and_rollback_preserve_project(assignment, monkeypatch, tmp_path):
    from deploy import project_maintenance as maintenance
    f = assignment
    monkeypatch.setattr(boxes, 'NETWORK', 'jarvis-test-' + uuid4().hex[:12])
    monkeypatch.setattr(boxes, 'LEGACY_IMAGE', boxes.IMAGE)
    monkeypatch.setattr(boxes, 'STATUS', tmp_path / 'status')
    base, network, volume = boxes.names(f.mission)
    image = boxes.staffing.inspect('image', boxes.IMAGE)['Id']
    target = {'name':base, 'image':image, 'readonly':True}
    alternate = base + '-lab-' + image.split(':')[1][:12]
    runs = []
    api = f.board.api
    f.board.api = lambda method,path: runs if path.endswith('/runs') else [] if '/tree-holds?' in path else api(method,path)
    docker = boxes.packages.docker
    try:
        old = boxes.provision(f.company, f.mission, target)
        docker('exec', old, 'sh', '-ec', 'echo original > /project/sentinel')
        runs.append({'status':'running'})
        with pytest.raises(ValueError, match='active work'):
            maintenance.switch(f.board, f.mission, old)
        runs.clear()
        with monkeypatch.context() as m:
            def fail(_):
                raise ValueError('Failed package inventory check')
            m.setattr(maintenance, 'verify_release', fail)
            with pytest.raises(ValueError, match='inventory'):
                maintenance.switch(f.board, f.mission, old)
        assert boxes.container(f.company, f.mission) == old
        changed = maintenance.switch(f.board, f.mission, old)
        new = changed['container']
        assert changed['previous_container'] == old and boxes.container(f.company, f.mission) == new
        assert not boxes.staffing.inspect('container', old)['State']['Running']
        assert docker('exec', new, 'cat', '/project/sentinel') == 'original'
        assert not boxes.staffing.inspect('container', new)['HostConfig']['ReadonlyRootfs']
        assert not maintenance.switch(f.board, f.mission, new)['changed']
        boxes.reconcile(f.board)
        assert json.loads(boxes.STATUS.read_text())['bridge_ipv4'][f.mission]
        restore = maintenance.switch(f.board, f.mission, new, rollback=True)
        assert restore['container'] == old and boxes.container(f.company, f.mission) == old
        assert docker('exec', old, 'cat', '/project/sentinel') == 'original'
        docker('stop','--time','1',old)
        # Simulate a dormant, pre-migration project reopening with only its original Docker records.
        (boxes.lab_directory(f.company, f.mission) / 'current.json').unlink()
        assert boxes.container(f.company, f.mission) == new
        assert not boxes.staffing.inspect('container',old)['State']['Running']
        assert docker('exec', new, 'cat', '/project/sentinel') == 'original'
    finally:
        for name in (alternate, base):
            obj = boxes.staffing.inspect('container',name)
            if obj and obj['Config']['Labels'].get(boxes.COMPANY) == f.company:
                docker('rm','-f',obj['Id'])
        if boxes.staffing.inspect('volume',volume):
            docker('volume','rm',volume)
        if boxes.staffing.inspect('network',network):
            docker('network','rm',network)


def test_general_keeps_verified_project_findings_across_archive(assignment, monkeypatch, tmp_path):
    import administration
    import general_knowledge
    f = assignment
    f.root['identifier'] = 'JAR-EXAMPLE'
    f.env['PAPERCLIP_API_KEY'] = 'synthetic-board'
    db = tmp_path / 'general_conversations.sqlite3'
    monkeypatch.setattr(boxes,'STATUS',tmp_path / 'status')
    monkeypatch.setattr(service,'SOCKET',tmp_path / 'project-cli.sock')
    monkeypatch.setattr(administration,'THREAD_INDEX',db)
    data = b'Formatter tests require a trailing newline.'
    req = {**service.wire.message(f.turn,{'command':'pwd','workdir':'/project'}),
           'action':'publish_finding','artifact':str(uuid4())}
    receipt = {'id':req['artifact'],'issueId':f.issue,'companyId':f.company,'createdByAgentId':f.agent,
               'originatingRunId':f.run,'originalFilename':'project-findings.md','byteSize':len(data),
               'sha256':hashlib.sha256(data).hexdigest()}
    original = f.board.api
    f.board.api = lambda method,path: [receipt] if path.endswith('/attachments') else original(method,path)
    monkeypatch.setattr(service.urllib.request,'build_opener',lambda *args:SimpleNamespace(open=lambda *a,**k:io.BytesIO(data)))
    for _ in range(2):
        scope = service.authorize(f.board,req)
        assert service.reference(f.board,req,*scope)['sha256'] == receipt['sha256']
    f.root['hiddenAt'] = 'today'
    notes = general_knowledge.project_findings(f.company, 'formatter')
    assert len(notes)==1 and notes[0]['artifact_id']==receipt['id'] and notes[0]['text']==data.decode()
    assert not general_knowledge.project_findings(str(uuid4()),'formatter')
    assert not general_knowledge.project_findings(f.company,'formatter',str(uuid4()))
    with pytest.raises(PermissionError):
        service.authorize(f.board,req)
    f.root.pop('hiddenAt')
    receipt['sha256'] = '0'*64
    with pytest.raises(ValueError,match='digest mismatch'):
        service.reference(f.board,req,f.child,f.root)


@pytest.mark.skipif(os.environ.get('JARVIS_TEST_PROJECT_CLI') != '1', reason='opt-in disposable Docker fixtures')
def test_live_shared_bridge_separate_disks_and_authenticated_project_terminal(assignment, employee, monkeypatch, tmp_path):
    f = assignment
    network = 'jarvis-test-' + uuid4().hex[:12]
    monkeypatch.setattr(boxes, 'NETWORK', network)
    monkeypatch.setattr(boxes, 'STATUS', tmp_path / 'status.json')
    monkeypatch.setattr(service.staffing, 'Board', lambda env:f.board)
    monkeypatch.setenv('JARVIS_PAPERCLIP_AGENT_ID', f.agent)
    monkeypatch.setenv('JARVIS_AGENT_PROOF_KEY', hmac.new(f.env['JARVIS_EXECUTION_PROOF_KEY'].encode(),
        ('jarvis-employee-proof-v3:' + f.agent).encode(), hashlib.sha256).hexdigest())
    monkeypatch.setattr(employee.reporting, 'current_turn', lambda:f.turn)
    wire = importlib.import_module(employee.__package__ + '.project_cli')
    # Keep the Unix listener name short on machines with long pytest temp paths.
    endpoint = '/tmp/' + network + '.sock'
    monkeypatch.setattr(wire, 'SOCKET', endpoint)
    second = {**f.root,'id':str(uuid4())}
    docker = boxes.packages.docker
    try:
        boxes.reconcile(f.board)
        first_id = boxes.staffing.inspect('container', boxes.names(f.mission)[0])['Id']
        f.records[second['id']] = second
        boxes.reconcile(f.board)
        net = boxes.ensure_network(f.company)
        assert len(net['Containers']) == 2 and net['Internal'] and net['Options'][boxes.ICC] == 'false'
        assert boxes.container(f.company,f.mission) == first_id
        with socketserver.ThreadingUnixStreamServer(endpoint, service.Handler) as srv:
            srv.env, srv.lock, srv.nonces = f.env, threading.Lock(), {}
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            try:
                args = {'workdir':'/project','command':'project-install make pytest && printf "def test_total(): assert 2 + 2 == 4\\n" > test_example.py && pytest -q'}
                got = wire.call(f.turn, args)
                assert got['exit_code'] == 0 and '1 passed' in got['output'], got
                assert b'assert 2 + 2 == 4' in wire.read_file(f.turn, '/project/test_example.py')
                # Real Hermes worker loop and built-in tools, with only a disposable signed assignment.
                runner = Path(__file__).with_name('project_container_dispatch.py').resolve()
                key = os.environ['JARVIS_AGENT_PROOF_KEY']
                native = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--read-only',
                    '--tmpfs','/tmp:rw,nosuid,nodev','-e','HOME=/tmp','-e','HERMES_HOME=/tmp/hermes',
                    '-e','JARVIS_PROFILE=software_development','-e','TERMINAL_ENV=ssh',
                    '-e','TERMINAL_SSH_HOST=jarvis-sandbox-' + '0'*24,
                    '-v', endpoint + ':/fixture.sock:ro',
                    '-v', str(runner.parents[1] / 'hermes-plugin') + ':/plugins:ro',
                    '-v', str(runner) + ':/fixture.py:ro',
                    '--entrypoint','/opt/hermes/.venv/bin/python','nousresearch/hermes-agent:v0.23.1',
                    '/fixture.py'], input=json.dumps({'turn':f.turn, 'key':key, 'hostname':first_id[:12]}),
                    text=True, capture_output=True, timeout=90)
                assert native.returncode == 0, (native.stderr + native.stdout)[-3500:]
                denied = wire.call({**f.turn, 'run':str(uuid4())}, {'workdir':'/project','command':'pwd'})
                assert denied['exit_code'] == 125
            finally:
                srv.shutdown()
                thread.join()
        other = boxes.container(f.company,second['id'])
        assert service.run_command(other,{'mission':second['id'],'cwd':'/project','command':'test ! -e test_example.py','timeout':3})['exit_code'] == 0
        started = boxes.staffing.inspect('container', first_id)['State']['StartedAt']
        f.root['status'] = 'done'
        historical = {**f.root, 'id':str(uuid4())}
        f.records[historical['id']] = historical
        for _ in range(2):
            boxes.reconcile(f.board)
        kept = boxes.staffing.inspect('container', first_id)
        assert kept['State']['Running'] and kept['State']['StartedAt'] == started
        saved = json.loads(boxes.STATUS.read_text())
        assert saved['projects'][f.mission] == 'running'
        assert saved['bridge_ipv4'][f.mission] == kept['NetworkSettings']['Networks'][network]['IPAddress']
        assert not boxes.staffing.inspect('container', boxes.names(historical['id'])[0])
        f.root['hiddenAt'] = 'archived'
        boxes.reconcile(f.board)
        assert not boxes.staffing.inspect('container',first_id)['State']['Running']
        assert f.mission not in json.loads(boxes.STATUS.read_text())['bridge_ipv4']
        del f.root['hiddenAt']
        f.root['status'] = 'todo'
        boxes.reconcile(f.board)
        assert service.run_command(first_id,{'mission':f.mission,'cwd':'/project','command':'test -f test_example.py','timeout':3})['exit_code'] == 0
    finally:
        Path(endpoint).unlink(missing_ok=True)
        for mission in (f.mission, second['id']):
            name, _, volume = boxes.names(mission)
            obj = boxes.staffing.inspect('container', name)
            if obj and obj['Config']['Labels'].get(boxes.COMPANY) == f.company:
                docker('rm','-f',obj['Id'])
            obj = boxes.staffing.inspect('volume', volume)
            if obj and obj['Labels'].get(boxes.COMPANY) == f.company:
                docker('volume','rm',volume)
        obj = boxes.staffing.inspect('network', network)
        if obj and obj['Labels'].get(boxes.COMPANY) == f.company:
            docker('network','rm',obj['Id'])
