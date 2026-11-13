"""Native deliverable and capability boundaries; no live services are mutated."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

COMPANY = '11111111-1111-4111-8111-111111111111'
AGENT = '22222222-2222-4222-8222-222222222222'
ISSUE = '33333333-3333-4333-8333-333333333333'
PROJECT = '44444444-4444-4444-8444-444444444444'
ARTIFACT = '55555555-5555-4555-8555-555555555555'
SESSION = f'paperclip:company:{COMPANY}:agent:{AGENT}:issue:{ISSUE}'


@pytest.fixture
def work(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1] / 'hermes-plugin/jarvis_readonly'
    package = ModuleType('employee_work_under_test')
    package.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    spec = importlib.util.spec_from_file_location(package.__name__ + '.employee_work', root / 'employee_work.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: tmp_path))
    monkeypatch.setenv('JARVIS_PROFILE', 'software_development')
    monkeypatch.setenv('JARVIS_PAPERCLIP_AGENT_ID', AGENT)
    monkeypatch.setenv('HERMES_PAPERCLIP_AGENT_KEY', 'synthetic-callback-key')
    turn = {'company': COMPANY, 'project': PROJECT, 'issue': ISSUE, 'agent': AGENT, 'run': 'native-run', 'session': SESSION}
    issue = {'id': ISSUE, 'companyId': COMPANY, 'projectId': PROJECT, 'assigneeAgentId': AGENT,
        'executionRunId': 'native-run', 'parentId': '66666666-6666-4666-8666-666666666666'}
    calls = []
    def api(method, path, body=None, run_id=None):
        calls.append((method, path, body, run_id))
        if path == '/issues/' + ISSUE and method == 'GET':
            return issue
        if path.endswith('/attachments') and method == 'GET':
            return []
        raise AssertionError((method, path))
    monkeypatch.setattr(module.reporting, 'current_turn', lambda: turn)
    monkeypatch.setattr(module.reporting, 'api', api)
    return SimpleNamespace(module=module, turn=turn, issue=issue, calls=calls, home=tmp_path, monkeypatch=monkeypatch)


def test_stale_or_reassigned_execution_cannot_publish(work):
    work.issue['executionRunId'] = 'another-run'
    with pytest.raises(PermissionError):
        work.module.publish_artifact({'name': 'report.md', 'content': 'data'})
    assert len(work.calls) == 1


@pytest.mark.parametrize('path', ['/opt/data/config.yaml', '/workspace/issues/other/report.md',
    f'/workspace/issues/{ISSUE}/../config.yaml'])
def test_artifact_path_must_be_inside_current_issue(work, path):
    with pytest.raises((PermissionError, FileNotFoundError)):
        work.module.read_workspace(work.turn, path)


def test_workspace_rejects_symlink_escape_and_preserves_independent_issue_directories(work):
    directory = work.module.workspace_directory(work.turn)
    local = work.home / 'workspace/issues' / ISSUE
    (local / 'report.md').write_text('actual source')
    assert work.module.read_workspace(work.turn, directory + '/report.md') == b'actual source'
    secret = work.home / 'credential.env'
    secret.write_text('must stay private')
    (local / 'escape.md').symlink_to(secret)
    with pytest.raises(OSError):
        work.module.read_workspace(work.turn, directory + '/escape.md')
    second = {**work.turn, 'issue': '77777777-7777-4777-8777-777777777777'}
    assert work.module.workspace_directory(second) != directory
    assert not (work.home / 'workspace/issues' / second['issue'] / 'report.md').exists()


def test_workspace_creation_rejects_symlinked_parent(work):
    elsewhere = work.home / 'elsewhere'
    elsewhere.mkdir()
    (work.home / 'workspace').symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(OSError):
        work.module.workspace_directory(work.turn)


def test_duplicate_artifact_retry_reuses_only_matching_native_run_receipt(work):
    data = b'real report'
    receipt = {'id': ARTIFACT, 'issueId': ISSUE, 'originalFilename': 'report.md', 'byteSize': len(data),
        'sha256': hashlib.sha256(data).hexdigest(), 'createdByAgentId': AGENT, 'originatingRunId': 'native-run'}
    work.monkeypatch.setattr(work.module.reporting, 'api', lambda *args: [receipt])
    work.monkeypatch.setattr(work.module.urllib.request, 'urlopen', lambda *args, **kwargs: pytest.fail('Duplicate upload'))
    result = work.module.upload(work.turn, 'report.md', data)
    assert result['id'] == ARTIFACT
    assert work.turn['artifacts'][ARTIFACT]['sha256'] == receipt['sha256']


def test_upload_binds_native_company_issue_and_run_and_checks_server_hash(work):
    data = b'tested deliverable'
    receipt = {'id': ARTIFACT, 'issueId': ISSUE, 'originalFilename': 'source.py', 'byteSize': len(data),
        'sha256': hashlib.sha256(data).hexdigest(), 'createdByAgentId': AGENT, 'originatingRunId': 'native-run'}
    observed = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, *args): return json.dumps(receipt).encode()
    def send(request, **kwargs):
        observed.append(request)
        return Response()
    work.monkeypatch.setattr(work.module.urllib.request, 'urlopen', send)
    result = work.module.upload(work.turn, 'source.py', data)
    assert result['id'] == ARTIFACT
    assert observed[0].full_url == f'http://paperclip:3100/api/companies/{COMPANY}/issues/{ISSUE}/attachments'
    assert observed[0].get_header('X-paperclip-run-id') == 'native-run'
    assert data in observed[0].data
    receipt['sha256'] = 'tampered'
    with pytest.raises(ValueError, match='differs'):
        work.module.upload(work.turn, 'different.py', data)


@pytest.mark.parametrize('name', ['../report.md', 'report.exe', 'bad\r\nheader.md'])
def test_upload_cannot_inject_paths_headers_or_binary_extensions(work, name):
    with pytest.raises(ValueError):
        work.module.upload(work.turn, name, b'data')


def test_current_native_artifact_projection_is_supported_and_conflicts_fail_closed(work):
    assert work.module.artifact_run_id({'originatingRunId': 'native-run'}) == 'native-run'
    assert work.module.artifact_run_id({'createdByRunId': 'legacy-run'}) == 'legacy-run'
    with pytest.raises(ValueError, match='conflicting'):
        work.module.artifact_run_id({'originatingRunId': 'native-run', 'createdByRunId': 'other-run'})


def test_research_cannot_fetch_a_model_supplied_url(work):
    work.monkeypatch.setattr(work.module, 'github_readme', lambda *args: pytest.fail('External fetch'))
    with pytest.raises(ValueError):
        work.module.research_sources({'frameworks': ['http://127.0.0.1:3100/api/secrets']})
    with pytest.raises(ValueError):
        work.module.research_sources({'frameworks': ['garak', 'garak']})


def test_public_source_redirects_are_denied(work):
    with pytest.raises(PermissionError):
        work.module.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1')


def test_sensitive_action_is_only_a_native_approval_request(work):
    proposal = 'Request an operator to inspect the specific named service configuration without making external changes.'
    def api(method, path, body=None, run_id=None):
        if method == 'GET' and path == '/issues/' + ISSUE: return work.issue
        if method == 'GET' and path.endswith('/approvals'): return []
        assert method == 'POST' and path == '/companies/' + COMPANY + '/approvals'
        assert body['type'] == 'request_board_approval' and body['issueIds'] == [ISSUE]
        assert run_id == 'native-run'
        assert 'never enables host' in body['payload']['execution']
        return {'id': 'approval', 'status': 'pending'}
    work.monkeypatch.setattr(work.module.reporting, 'api', api)
    result = json.loads(work.module.request_action_approval({'proposal': proposal}))
    assert result['executed'] is False and result['status'] == 'pending'
    assert work.turn['action_approval']['id'] == 'approval'


def test_role_registration_never_grants_a_shell_to_research(work):
    work.monkeypatch.setenv('JARVIS_PROFILE', 'research')
    names = []
    work.module.register(SimpleNamespace(register_tool=lambda **tool: names.append(tool['name'])))
    assert set(names) == {'research_sources', 'publish_artifact'}
    assert 'terminal' not in names and 'request_action_approval' not in names


def test_foreign_sibling_artifacts_are_never_read(work):
    def api(method, path, *args):
        if path == '/issues/' + ISSUE: return work.issue
        if path == '/companies/' + COMPANY + '/issues':
            return [{'id': ARTIFACT, 'parentId': work.issue['parentId'], 'companyId': 'foreign',
                     'projectId': PROJECT, 'status': 'done'}]
        pytest.fail('Foreign artifact access')
    work.monkeypatch.setattr(work.module.reporting, 'api', api)
    with pytest.raises(PermissionError):
        work.module.read_worker_artifacts({'issue_id': ARTIFACT})


def test_derived_worker_key_cannot_sign_another_employee(work):
    import hmac
    master = 'synthetic-master-signing-key'
    module = work.module.reporting
    proof = {'version': 3, 'agent_id': AGENT, 'issue_id': ISSUE, 'value': 'observed'}
    work.monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', master)
    signed = module.sign_evidence(proof)
    derived = hmac.new(master.encode(), ('jarvis-employee-proof-v3:' + AGENT).encode(), hashlib.sha256).hexdigest()
    work.monkeypatch.delenv('JARVIS_EXECUTION_PROOF_KEY')
    work.monkeypatch.setenv('JARVIS_AGENT_PROOF_KEY', derived)
    assert module.sign_evidence(proof) == signed
    with pytest.raises(PermissionError):
        module.sign_evidence({**proof, 'agent_id': ARTIFACT})
    work.monkeypatch.setenv('JARVIS_EXECUTION_PROOF_KEY', master)
    assert module.authentic_evidence(signed)
    assert not module.authentic_evidence({**signed, 'issue_id': ARTIFACT})


def test_runtime_report_delivery_preserves_generated_prose_and_exact_source_provenance(work):
    source = {'framework': 'garak', 'repository': 'NVIDIA/garak', 'source_url': 'https://github.com/NVIDIA/garak',
        'blob_sha': 'a' * 40, 'sha256': 'b' * 64}
    work.turn.update({'source_refs': {'garak': source}, 'response': 'garak capabilities and architecture are discussed using retrieved primary-source data. ' * 4})
    writes = []
    work.monkeypatch.setattr(work.module, 'upload', lambda turn, name, data: writes.append((name, data)) or {'id': ARTIFACT})
    work.module.deliver_report(work.turn)
    assert work.turn['response'].strip() in writes[0][1].decode()
    assert 'Git blob SHA-1: ' + 'a' * 40 in writes[0][1].decode()
    assert work.turn['runtime_deliveries'][0]['type'] == 'final_model_report'
    assert 'no model publishing tool call' in work.turn['runtime_deliveries'][0]['source']
    work.turn['response'] += ' Fabricated SHA256: ' + 'c' * 24
    with pytest.raises(ValueError, match='unverified or truncated hash'):
        work.module.deliver_report(work.turn)


def test_runtime_workspace_delivery_collects_only_real_current_issue_files(work):
    root = work.module.workspace_directory(work.turn)
    current = work.home / 'workspace/issues' / ISSUE
    (current / 'test_demo.py').write_text('actual generated code')
    (current / 'private.env').write_text('excluded extension')
    (current / 'escape.txt').symlink_to(work.home / 'elsewhere.txt')
    other = work.home / 'workspace/issues/other'
    other.mkdir(); (other / 'foreign.py').write_text('another task')
    uploads = []
    work.monkeypatch.setattr(work.module, 'upload', lambda turn, name, data: uploads.append((name, data)) or {'id': ARTIFACT})
    work.module.deliver_workspace(work.turn)
    assert uploads == [('test_demo.py', b'actual generated code')]
    assert work.turn['runtime_deliveries'][0]['type'] == 'existing_workspace_file'


def test_primary_source_excerpt_is_bounded_without_inventing_content(work):
    original = '# Project\n![badge](https://badges.example/a)\n## Architecture\nA modular generator/probe/detector pipeline.\n' + 'More feature details.\n' * 200
    excerpt = work.module.source_excerpt(original)
    assert len(excerpt) <= 2200
    assert 'modular generator/probe/detector' in excerpt and 'badges.example' not in excerpt


def test_source_inventory_is_actual_api_data_and_does_not_accept_model_spellings(work):
    work.turn['report_kind'] = 'source_module_inventory'
    work.monkeypatch.setattr(work.module, 'scope', lambda: (work.turn, work.issue))
    work.monkeypatch.setattr(work.module, 'github_readme', lambda repo: {
        'repository': repo, 'source_url': 'https://github.com/' + repo, 'immutable_blob_url': 'https://api.github.com/blob',
        'blob_sha': 'a' * 40, 'sha256': 'b' * 64, 'readme': 'Actual source.',
        'components': [{'name': name} for name in ('analyze', 'probes', 'cli.py', '_config.py', 'generators')]})
    writes = []
    def upload(turn, name, data):
        writes.append((name, data)); return {'id': ARTIFACT, 'originalFilename': name}
    work.monkeypatch.setattr(work.module, 'upload', upload)
    work.module.research_sources({'frameworks': ['garak']})
    assert writes[1][0] == 'source-module-inventory.md'
    assert '"analyze"' in writes[1][1].decode() and '"analyse"' not in writes[1][1].decode()
    assert 'no model-authored analysis' in writes[1][1].decode()
    assert work.turn['runtime_deliveries'][0]['type'] == 'observed_source_inventory'
    work.turn['report_kind'] = 'model_analysis'; writes.clear()
    work.module.research_sources({'frameworks': ['garak']})
    assert len(writes) == 1  # A data inventory never substitutes for a requested comparison.


def test_framework_completion_needs_actual_current_workspace_result_bytes(work):
    directory = work.module.workspace_directory(work.turn)
    current = work.home / 'workspace/issues' / ISSUE
    result = {'results': {'stats': {'successes': 3, 'failures': 0, 'errors': 0}}}
    (current / 'results.json').write_text(json.dumps(result))
    event = {'args': {'command': 'promptfoo eval -c config.json --output results.json'}, 'tool_call_id': 'actual-call'}
    verified = work.module.verify_promptfoo_output(work.turn, [event])
    assert verified['successes'] == 3 and verified['tool_call_id'] == 'actual-call'
    assert verified['sha256'] == hashlib.sha256((current / 'results.json').read_bytes()).hexdigest()
    result['results']['stats']['failures'] = 1
    (current / 'results.json').write_text(json.dumps(result))
    with pytest.raises(ValueError): work.module.verify_promptfoo_output(work.turn, [event])


@pytest.mark.parametrize('command', ['echo promptfoo eval --output results.json',
    'promptfoo eval --help --output results.json', 'promptfoo eval -c config.json',
    'promptfoo eval --output /opt/data/config.yaml'])
def test_help_or_prose_or_foreign_path_cannot_be_framework_execution(work, command):
    with pytest.raises(ValueError):
        work.module.verify_promptfoo_output(work.turn, [{'args': {'command': command}, 'tool_call_id': 'call'}])


def test_real_current_workspace_cd_prefix_is_not_a_missing_execution(work):
    cwd = '/workspace/issues/' + ISSUE
    event = {'args': {'command': 'cd ' + cwd + ' && python3 /usr/local/share/jarvis/isolation_checks.py'},
        'result': {'output': 'Ran 8 tests in 0.001s\nOK', 'exit_code': 0}}
    assert work.module.isolation_fixture_ran(work.turn, event)
    assert work.module.scoped_command_argv(work.turn, 'cd ' + cwd + ' && promptfoo eval -c config.json') == ['promptfoo', 'eval', '-c', 'config.json']
    assert work.module.scoped_command_argv(work.turn, 'cd /opt/data && promptfoo eval') == []
    assert work.module.scoped_command_argv(work.turn, 'echo promptfoo eval') == ['echo', 'promptfoo', 'eval']
    assert work.module.scoped_command_argv(work.turn, 'cd ' + cwd + ' && echo fake && promptfoo eval') == ['echo', 'fake']
    assert work.module.scoped_command_argv(work.turn, 'cd ' + cwd + ' && promptfoo eval --output results.json; cat results.json; echo done') == ['promptfoo', 'eval', '--output', 'results.json']


def test_old_result_file_cannot_mask_failed_evaluation_followed_by_display_command(work):
    import os
    work.module.workspace_directory(work.turn)
    p = work.home / 'workspace/issues' / ISSUE / 'results.json'
    p.write_text(json.dumps({'results': {'stats': {'successes': 3, 'failures': 0, 'errors': 0}}}))
    work.turn['started_at'] = 200
    os.utime(p, (100, 100))
    event = {'args': {'command': 'promptfoo eval --output results.json; cat results.json; echo done'}, 'tool_call_id': 'actual'}
    with pytest.raises(ValueError): work.module.verify_promptfoo_output(work.turn, [event])
    os.utime(p, (300, 300))
    assert work.module.verify_promptfoo_output(work.turn, [event])['successes'] == 3
