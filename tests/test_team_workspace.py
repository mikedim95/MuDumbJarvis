import hashlib
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from test_project_workspace import board, CEO, CHILD, FIRST, SECOND, WORKER, HEADERS, server, workspace
from test_employee_work import work

team = workspace.team


def test_owner_controls_are_revisioned_and_project_local(board, monkeypatch):
    native = board.client.request

    async def request(self, method, path, body=None):
        if method == 'PUT' and path.endswith('/' + team.KEY):
            body = {**body, 'key': team.KEY, 'companyId': 'company', 'updatedByUserId': 'board-owner',
                    'issueId': path.split('/')[1]}
        if path.endswith('/attachments'):
            return []
        return await native(self, method, path, body)
    monkeypatch.setattr(board.client, 'request', request)
    url = '/api/projects/' + FIRST + '/shared-workspace'
    data = {'notes': 'Reviewed 4 items', 'enabled': True}
    with TestClient(server.app) as client:
        assert client.get(url).status_code == 401
        assert client.get(url, headers=HEADERS).json()['enabled'] is False
        assert client.get(url.replace(FIRST, CHILD), headers=HEADERS).status_code == 404
        saved = client.put(url, json=data, headers=HEADERS).json()
        assert saved['enabled'] and saved['revision']
        assert client.put(url, json=data, headers=HEADERS).json() == saved
        assert client.get(url, headers=HEADERS).json()['notes'] == data['notes']
        assert client.get(url.replace(FIRST, SECOND), headers=HEADERS).json()['notes'] == ''
        assert client.put(url, json={**data, 'enabled': False}, headers=HEADERS).status_code == 409
        off = client.put(url, json={**data, 'enabled': False, 'expected_revision': saved['revision']}, headers=HEADERS)
        assert off.status_code == 200 and not off.json()['enabled'] and len(board.writes) == 2
        board.issues[SECOND]['description'] = '[JARVIS GENERAL WORK]\nNew work'
        assert client.put(url.replace(FIRST, SECOND), json=data, headers=HEADERS).status_code == 404


def test_shared_notes_and_verified_outcomes_reach_assigned_roles_only(board):
    raw = b'{"outcome":"partial","items_reviewed":4}'
    digest = hashlib.sha256(raw).hexdigest()
    report = {'companyId': 'company', 'issueId': CHILD, 'createdByAgentId': WORKER, 'id': str(uuid4()),
              'originalFilename': team.RESULT, 'sha256': digest, 'byteSize': len(raw)}
    doc = {'companyId': 'company', 'issueId': FIRST, 'key': team.KEY, 'latestRevisionId': str(uuid4()),
           'updatedByUserId': 'owner', 'body': json.dumps({'enabled': True, 'notes': 'Internal project note'})}
    board.issues[CHILD]['privacyParentIssueId'] = FIRST  # Native open children inherit their parent's visibility.
    inputs = {report['id']: raw}
    calls = []
    def api(method, path):
        calls.append(path)
        if path.endswith('/documents/' + team.KEY):
            assert path.startswith('/issues/' + FIRST + '/')
            return doc
        if path == '/issues/' + CHILD + '/attachments':
            return [report, {**report, 'originalFilename': 'private.txt', 'id': str(uuid4())}]
        assert path == '/issues/' + FIRST + '/attachments'
        return []
    def read(task, agent, root=FIRST):
        turn = {'agent': agent, 'ceo': agent == CEO, 'reports_to': CEO, 'issue': task['id'],
                'work_scope': {'mission_id': root}, 'company': 'company', 'project': 'native'}
        return team.read_for_turn(turn, task, list(board.issues.values()), [], api, inputs.__getitem__)
    for task, agent in ((board.issues[CHILD], WORKER), (board.issues[FIRST], CEO)):
        view = read(task, agent)
        assert view['notes'] == 'Internal project note'
        assert view['recent_results'] == [{'task': 'JAR-3', 'agent_id': WORKER, 'artifact_id': report['id'],
                                          'sha256': digest, 'outcome': 'partial', 'items_reviewed': 4}]
    count = len(calls)
    for issue in (board.issues[SECOND], {**board.issues[CHILD], 'parentId': SECOND},
                  {**board.issues[CHILD], 'parentId': CHILD}, {**board.issues[CHILD], 'hiddenAt': 'yesterday'},
                  {**board.issues[CHILD], 'privacyRootIssueId': FIRST},
                  {**board.issues[CHILD], 'privacyParentIssueId': SECOND},
                  {**board.issues[CHILD], 'assigneeAgentId': 'another'}, {**board.issues[CHILD], 'projectId': 'elsewhere'}):
        assert read(issue, WORKER) is None
    assert len(calls) == count
    inputs[report['id']] = b'x' * len(raw)
    incomplete = read(board.issues[CHILD], WORKER)
    assert not incomplete['recent_results'] and incomplete['results_incomplete']
    doc['body'] = json.dumps({'enabled': False, 'notes': 'retained in owner view'})
    assert read(board.issues[CHILD], WORKER) is None
    doc['updatedByAgentId'] = WORKER
    with pytest.raises(ValueError, match='owner revision'):
        read(board.issues[CHILD], WORKER)


def test_routine_requires_native_mission_binding(board):
    job = {'id': 'cron', 'companyId': 'company', 'projectId': 'native', 'variables': [
        {'name': 'jarvis_work_scope', 'defaultValue': 'project'},
        {'name': 'jarvis_mission_id', 'defaultValue': FIRST}]}
    run = {**board.issues[SECOND], 'originKind': 'routine_execution', 'originId': job['id'],
           'description': '[JARVIS MISSION ' + SECOND + ']\nOther'}
    assert team.membership(run, board.issues, {}, 'company', 'native', CEO) is None
    assert team.membership(run, board.issues, {'cron': job}, 'company', 'native', CEO) == FIRST


@pytest.mark.parametrize('data', [{'outcome': 'completed', 'items_reviewed': True}, {'url': 'unshared'},
                                  {'outcome': 'completed', 'notes': 'private'}, {'outcome': 'unknown'}])
def test_invalid_project_report_rejected_before_upload(work, data):
    with pytest.raises(ValueError, match='outcome'):
        work.module.publish_artifact({'name': team.RESULT, 'content': json.dumps(data)})
    assert all(not path.endswith('/attachments') for _, path, _, _ in work.calls)
