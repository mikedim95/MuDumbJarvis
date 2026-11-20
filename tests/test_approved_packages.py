import base64
import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deploy import approved_packages as apt, apt_tool
from test_tasks import AGENT, CEO, CHILD, ISSUE

COMPANY, PROJECT = str(uuid4()), str(uuid4())


@pytest.fixture
def request_data():
    review = str(uuid4())
    parent = {'id': ISSUE, 'status': 'blocked', 'companyId': COMPANY, 'projectId': PROJECT, 'assigneeAgentId': CEO}
    child = {**parent, 'id': CHILD, 'identifier': 'JAR-30', 'parentId': ISSUE, 'assigneeAgentId': AGENT,
             'unblockDescriptor': {'action': apt.reviews.REPORT + apt.reviews.PACKAGE_REQUEST + 'jq'}}
    row = {**apt.reviews.package_confirmation(child, 'jq', 'owner'), 'id': review, 'issueId': ISSUE, 'companyId': COMPANY,
           'status': 'accepted', 'createdByUserId': 'operator', 'resolvedByUserId': 'owner'}
    scope = apt.receipts.binding(COMPANY, PROJECT, ISSUE, CHILD, AGENT, 'jq', review)
    board = SimpleNamespace(env={'PAPERCLIP_COMPANY_ID': COMPANY, 'PAPERCLIP_CEO_AGENT_ID': CEO})
    return SimpleNamespace(parent=parent, child=child, row=row, scope=scope, agent={'id': AGENT}, board=board)


@pytest.mark.parametrize('change', ['none', 'pending', 'rejected', 'different_owner', 'different_project',
                                     'different_employee', 'archived', 'forged_question', 'foreign_company', 'other_author'])
def test_provisioning_requires_actual_scoped_owner_decision(request_data, change):
    f = request_data
    if change in ('pending', 'rejected'):
        f.row['status'] = change
    if change == 'different_owner':
        f.row['resolvedByUserId'] = 'other'
    if change == 'different_project':
        f.child['projectId'] = str(uuid4())
    if change == 'different_employee':
        f.child['assigneeAgentId'] = CEO
    if change == 'archived':
        f.parent['hiddenAt'] = 'today'
    if change == 'forged_question':
        f.row['payload']['prompt'] = 'Change an unrelated setting?'
    if change == 'foreign_company':
        f.row['companyId'] = str(uuid4())
    if change == 'other_author':
        f.row['createdByAgentId'] = AGENT
    assert list(apt.accepted(f.board, f.parent, f.child, f.agent, [f.row])) == ([f.scope] if change == 'none' else [])


def test_offline_commands_never_accept_scanner_targets_or_arbitrary_programs():
    assert apt_tool.command('nmap', ['--version']) == ['/usr/bin/nmap', '--version']
    assert apt_tool.command('zip', ['--package-version'])[0] == '/usr/bin/dpkg-query'
    assert apt_tool.command('jq', ['-r', '.field']) == ['/usr/bin/jq', '-r', '.field']
    for name, args in [('nmap', []), ('nmap', ['127.0.0.1']), ('nmap', ['--version', 'anything']),
                       ('bash', ['-c', 'echo test']), ('jq', ['-f', '/ipc/input'])]:
        with pytest.raises(ValueError):
            apt_tool.command(name, args)
    result = apt_tool.execute('bash', {'args': ['--package-version'], 'input': base64.b64encode(b'').decode()})
    assert result['code'] == 0 and result['stdout'].strip()


def test_native_markdown_stdout_normalization_and_receipt_integrity(request_data):
    scope = request_data.scope
    output = 'version header\nsecond line'
    data = {'scope':scope, 'status':'ready', 'verified_at':'2026-11-20T06:30:00Z',
            'version':'1.7', 'command':'./.jarvis-bin/jq', 'usage':apt.receipts.usage('jq'),
            'image':'sha256:' + 'a'*64, 'output':output,
            'output_sha256':hashlib.sha256((output + '\n').encode()).hexdigest()}
    doc = {'key':apt.receipts.key(scope['review']), 'companyId':scope['company'], 'issueId':scope['issue'],
           'updatedByUserId':'operator', 'body':json.dumps(data).replace('\\n', '\n')}
    assert apt.receipts.read(doc, scope)['status'] == 'ready'
    data['stdout_base64'] = base64.b64encode(b'different bytes').decode()
    assert not apt.receipts.read({**doc, 'body':json.dumps(data)}, scope)


def test_launcher_publication_is_idempotent_and_symlink_safe(tmp_path, request_data):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    scope = request_data.scope
    sock = tmp_path / 's'
    # Linux limits the bind address length. Bind relative to the temporary directory.
    with socket.socket(socket.AF_UNIX) as server:
        previous = os.getcwd()
        try:
            os.chdir(tmp_path)
            server.bind('s')
        finally:
            os.chdir(previous)
        digest = apt.publish_client(scope, workspace, sock)
        assert digest == apt.publish_client(scope, workspace, sock)
        dest = workspace / 'issues' / CHILD / '.jarvis-bin'
        assert (dest / '.apt-jq.sock').samefile(sock)
        assert digest == hashlib.sha256((dest / 'jq').read_bytes()).hexdigest()
        (dest / 'jq').unlink()
        protected = tmp_path / 'original'
        protected.write_text('keep me')
        (dest / 'jq').symlink_to(protected)
        with pytest.raises(OSError):
            apt.publish_client(scope, workspace, sock)
        assert protected.read_text() == 'keep me'
        (workspace / 'issues' / ISSUE).symlink_to(tmp_path)
        with pytest.raises(OSError):
            apt.publish_client({**scope, 'issue': ISSUE}, workspace, sock)
        assert not (tmp_path / '.jarvis-bin').exists()


def test_installs_once_and_rereads_scope_after_the_build(request_data, monkeypatch):
    f = request_data
    docs, writes = {}, []
    def api(method, path, body=None):
        if 'tree-holds?' in path: return []
        if path.endswith('/comments'):
            return [{'authorAgentId': AGENT, 'createdByRunId': 'run',
                     'body': apt.reviews.PACKAGE_REQUEST + 'jq\nJARVIS_EXECUTION_EVIDENCE={}'}]
        if path.endswith('/documents'): return list(docs.values())
        assert method == 'PUT' and '/documents/' in path
        k = path.rsplit('/', 1)[1]
        docs[k] = {**body, 'key': k, 'issueId': CHILD, 'companyId': COMPANY, 'updatedByUserId': 'operator'}
        return docs[k]
    f.board.api = api
    monkeypatch.setattr(apt, 'build', lambda scope: 'sha256:' + 'f' * 64)
    monkeypatch.setattr(apt, 'fetch_scope', lambda *args: False)
    monkeypatch.setattr(apt, 'client_ready', lambda *args: True)
    def deliver(scope, agent, image):
        writes.append(scope)
        return {'status':'ready', 'version':'1.7', 'image':image, 'verified_at':datetime.now(timezone.utc).isoformat(),
                'command':'./.jarvis-bin/jq', 'usage':apt.receipts.usage('jq'),
                'stdout_base64':base64.b64encode(b'jq-1.7\n').decode(), 'output_sha256':hashlib.sha256(b'jq-1.7\n').hexdigest()}
    monkeypatch.setattr(apt, 'deliver', deliver)
    assert not apt.provision(f.board, f.scope, f.child, f.agent, set())
    assert not writes and not docs
    monkeypatch.setattr(apt, 'fetch_scope', lambda *args: True)
    assert apt.provision(f.board, f.scope, f.child, f.agent, set())
    assert apt.provision(f.board, f.scope, f.child, f.agent, {f.row['id']})
    assert writes == [f.scope] and len(docs) == 1
    doc = next(iter(docs.values()))
    assert apt.receipts.read(doc, f.scope)['version'] == '1.7'
    assert apt.receipts.read(dict(doc, updatedByAgentId=AGENT), f.scope) is None
    assert apt.receipts.read(doc, {**f.scope, 'agent': CEO}) is None
    assert json.loads(doc['body'])['scope'] == f.scope
