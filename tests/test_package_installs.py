import importlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from deploy import provision_packages as host
from test_employee_work import work, AGENT, COMPANY, ISSUE, PROJECT


@pytest.fixture
def native(work, monkeypatch):
    packages = importlib.import_module(work.module.__package__ + '.package_installs')
    rows, docs, installs = [], {}, []
    agent = {'id': AGENT, 'companyId': COMPANY, 'metadata': {'jarvis': {'runtime_id': 'f' * 24}}}
    task = {**work.issue, 'status': 'in_progress'}
    def api(method, path, body=None, run=None):
        if path == '/issues/' + ISSUE:
            return task
        if path.endswith('/approvals') and method == 'POST':
            a = {'id': str(uuid4()), 'companyId': COMPANY, 'status': 'pending', **body}
            rows.append(a)
            return a
        if path.endswith('/approvals'):
            return rows
        if path.startswith('/approvals/') and path.endswith('/issues'):
            return [task]
        if path.endswith('/documents'):
            return list(docs.values())
        if '/documents/' in path and method == 'PUT':
            key = path.rsplit('/', 1)[1]
            assert body['baseRevisionId'] == docs.get(key, {}).get('latestRevisionId')
            docs[key] = {**body, 'issueId': ISSUE, 'companyId': COMPANY, 'updatedByUserId': 'board',
                         'key': key, 'latestRevisionId': str(uuid4())}
            return docs[key]
        raise AssertionError((method, path))
    monkeypatch.setattr(work.module.reporting, 'api', api)
    monkeypatch.setattr(host, 'install', lambda state, issue, name: installs.append((issue,name)))
    container = {'Id': 'abc', 'State': {'Running': True}, 'Config': {'User': '1000:1000',
                 'Labels': {'io.jarvis.employee': 'f' * 24}}, 'HostConfig': {'ReadonlyRootfs': True}}
    def reconcile():
        host.reconcile(SimpleNamespace(api=api), agent, {'sandbox': True, 'tools': ['terminal']}, rows,
                       lambda *args: container)
    def request():
        return json.loads(work.module.request_action_approval({'proposal': 'install package tree'}))
    return SimpleNamespace(rows=rows, docs=docs, installs=installs, container=container, task=task,
                           request=request, reconcile=reconcile, packages=packages, work=work)


def test_owner_decision_triggers_install_and_verified_receipt(native):
    n = native
    pending = n.request()
    assert pending['status'] == 'pending' and n.request() == pending and len(n.rows) == 1
    n.reconcile()
    assert not n.installs and not n.docs
    n.rows[0]['status'] = 'approved'
    n.reconcile()
    assert not n.installs
    n.rows[0]['decidedByUserId'] = 'owner'
    assert n.request()['status'] == 'awaiting_install'
    n.reconcile()
    n.reconcile()
    assert n.installs == [(ISSUE, 'tree')]
    assert n.request()['command'] == './.jarvis-bin/tree' and n.request()['sha256'] == host.packages.CATALOG['tree'][3]
    assert 'action_approval' not in n.work.turn
    next(iter(n.docs.values()))['updatedByAgentId'] = AGENT
    assert n.request()['status'] == 'awaiting_install'


@pytest.mark.parametrize('change', ['reject','reassign','different_project','closed','changed_version','other_agent','wrong_label'])
def test_approval_cannot_authorize_another_scope(native,change):
    n = native
    n.request()
    ticket = n.rows[0]
    ticket.update(status='approved', decidedByUserId='owner')
    if change=='reject': ticket['status']='rejected'
    if change=='reassign': n.task['assigneeAgentId']=str(uuid4())
    if change=='different_project': n.task['projectId']=str(uuid4())
    if change=='closed': n.task['status']='done'
    if change=='changed_version': ticket['payload']['version']='latest'
    if change=='other_agent': ticket['requestedByAgentId']=str(uuid4())
    if change=='wrong_label': n.container['Config']['Labels']={}
    n.reconcile()
    assert not n.installs
    if change == 'reject': assert n.request()['status']=='rejected' and len(n.rows)==1


def test_manifest_and_existing_approval_tool_share_one_native_request(native,monkeypatch):
    n=native
    monkeypatch.setattr(n.work.module, 'upload', lambda turn,name,data:{'originalFilename':name})
    manifest={'name':n.packages.MANIFEST,'content':'{"package":"tree"}'}
    reply=json.loads(n.work.module.publish_artifact(manifest))
    assert n.request()['approval_id']==reply['package_install']['approval_id'] and len(n.rows)==1
    with pytest.raises(ValueError):
        n.work.module.publish_artifact({**manifest,'content':'{"package":"../tree"}'})
    with pytest.raises(ValueError):
        n.work.module.request_action_approval({'proposal':'install package arbitrary.deb'})
    assert len(n.rows)==1


def test_failed_install_can_recover_without_another_decision(native,monkeypatch):
    n=native
    n.request()
    n.rows[0].update(status='approved',decidedByUserId='owner')
    with monkeypatch.context() as patch:
        def fail(*args): raise OSError('sandbox offline')
        patch.setattr(host,'install',fail)
        n.reconcile()
        assert n.request()['status']=='retrying'
    n.reconcile()
    assert n.request()['status']=='installed'


def test_unlisted_package_uses_scoped_ceo_handoff_from_both_worker_tools(work, monkeypatch):
    manager, parent = str(uuid4()), str(uuid4())
    work.turn['reports_to'] = manager
    work.issue['parentId'] = parent
    root = {'id': parent, 'assigneeAgentId': manager, 'companyId': COMPANY, 'projectId': PROJECT, 'status':'blocked'}
    rows = []
    def api(method, path, body=None, run=None):
        if path == '/issues/' + ISSUE: return work.issue
        if path == '/issues/' + parent: return root
        if path == '/issues/' + ISSUE + '/documents': return []
        assert path == '/issues/' + ISSUE + '/comments'
        if method == 'GET': return rows
        assert method == 'POST' and run == work.turn['run']
        row = {**body, 'id':str(uuid4()), 'authorAgentId':AGENT, 'createdByRunId':run}
        rows.append(row)
        return row
    monkeypatch.setattr(work.module.reporting, 'api', api)
    monkeypatch.setattr(work.module, 'upload', lambda *a: {'id':'artifact'})
    requested = json.loads(work.module.request_action_approval({'proposal':'install package jq'}))
    assert requested['status'] == 'requested_ceo_review' and requested['ceo_issue_id'] == parent
    manifest = {'name':'package-request.json', 'content':'{"package":"jq"}'}
    assert json.loads(work.module.publish_artifact(manifest))['package_install'] == requested
    review = importlib.import_module(work.module.__package__ + '.blocker_review')
    assert len(rows) == 1 and review.worker_package_requests(work.issue, rows) == ['jq']
    assert not review.worker_package_requests(work.issue, [dict(rows[0], authorAgentId=manager)])
    root['projectId'] = str(uuid4())
    with pytest.raises(PermissionError): work.module.request_action_approval({'proposal':'install package jq'})


def test_employee_reads_verified_package_receipt_without_reopening_review(work, monkeypatch):
    from deploy import approved_packages as apt
    import hashlib
    parent, manager, review = [str(uuid4()) for _ in range(3)]
    work.turn['reports_to'] = manager
    work.issue['parentId'] = parent
    scope = apt.receipts.binding(COMPANY, PROJECT, parent, ISSUE, AGENT, 'nmap', review)
    doc = {'key':apt.receipts.key(review), 'companyId':COMPANY, 'issueId':ISSUE, 'updatedByUserId':'operator',
        'body':json.dumps({'scope':scope, 'status':'ready', 'version':'7.95', 'command':'./.jarvis-bin/nmap',
            'usage':apt.receipts.usage('nmap'), 'verified_at':'2026-11-20T07:30:00Z', 'image':'sha256:' + 'a'*64,
            'output':'Nmap version 7.95', 'output_sha256':hashlib.sha256(b'Nmap version 7.95\n').hexdigest()})}
    def api(method,path,*args):
        assert method == 'GET'
        return {'/issues/' + ISSUE: work.issue, '/issues/' + parent: {'id':parent, 'assigneeAgentId':manager,
                'companyId':COMPANY, 'projectId':PROJECT, 'status':'blocked'}, '/issues/' + ISSUE + '/documents':[doc]}[path]
    monkeypatch.setattr(work.module.reporting, 'api', api)
    result = json.loads(work.module.request_action_approval({'proposal':'install package nmap'}))
    assert result['status'] == 'ready' and result['command'] == './.jarvis-bin/nmap'
    assert 'version check only' in result['usage'] and not work.turn.get('package_reviews')


def test_hud_approval_binds_catalog_and_employee_before_recording_decision(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from test_tasks import task_api, headers
    from test_phase1 import server
    ceo, approval_id = str(uuid4()), str(uuid4())
    task = {'id': ISSUE, 'companyId': COMPANY, 'projectId': PROJECT, 'assigneeAgentId': AGENT, 'status':'in_review'}
    person = {'id': AGENT, 'companyId': COMPANY, 'reportsTo': ceo, 'metadata': {'jarvis': {'profile':'system_administration'}}}
    data = host.packages.payload('tree', COMPANY, PROJECT, ISSUE, AGENT)
    approval = {'id': approval_id, 'companyId': COMPANY, 'status':'pending', 'type':'request_board_approval',
                'requestedByAgentId': AGENT, 'payload': data}
    posted=[]
    def handler(req):
        path=req.url.path
        if path.endswith('/approve'):
            posted.append(path)
            return httpx.Response(200,json={**approval,'status':'approved','decidedByUserId':'fixture-owner'})
        if path.endswith('/issues'): value=[task]
        elif path.endswith('/agents'): value=[person]
        elif path.endswith(ISSUE): value=task
        else: value=approval
        return httpx.Response(200,json=value)
    def setup(self):
        self.company,self.project,self.agent,self.ceo,self.workforce=COMPANY,PROJECT,AGENT,ceo,True
        self.http=httpx.AsyncClient(base_url='http://paperclip/api/',transport=httpx.MockTransport(handler))
    monkeypatch.setattr(task_api.Paperclip,'__init__',setup)
    path=f'/api/approvals/{approval_id}/decision'
    with TestClient(server.app) as client:
        data['proposal']='Install different software'
        assert client.post(path,headers=headers,json={'decision':'approve','note':'Approve'}).status_code==409
        assert not posted
        data.update(host.packages.payload('tree', COMPANY, PROJECT, ISSUE, AGENT))
        response=client.post(path,headers=headers,json={'decision':'approve','note':'One installation'})
        assert response.status_code==200 and response.json()['status']=='approved' and len(posted)==1
