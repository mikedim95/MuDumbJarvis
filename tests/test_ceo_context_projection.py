"""Large multi-specialist results retain provenance inside bounded CEO context."""
import copy
import hashlib
import json

import pytest

from test_ceo_tools import plugin, COMPANY, PROJECT, ROOT, WORKER, decode_preflight


def specialist_results(state, quality=False):
    profiles = ('research', 'software_development', 'system_administration', 'security_analysis')
    entries = []
    for index, profile in enumerate(profiles, 1):
        child_id = f'{index:08d}-1111-4111-8111-111111111111'
        agent = f'{index:08d}-2222-4222-8222-222222222222'
        run = 'native-run-' + str(index)
        artifact = {'id': 'artifact-' + str(index), 'issueId': child_id,
            'originalFilename': profile + '.md', 'byteSize': 4000,
            'sha256': str(index) * 64, 'createdByAgentId': agent, 'originatingRunId': run}
        output = 'Observed actual command output\n' + ('diagnostic body\n' * 400) + '\nRan 2 tests\n\nOK\n'
        tools = [{'tool': 'terminal', 'tool_call_id': 'call-' + str(index), 'success': True,
            'args': {'command': 'python -m unittest test_validator.py'},
            'result': {'exit_code': 0, 'output': output}, 'result_sha256': 'a' * 64}]
        proof = {'version': 3, 'kind': 'execution', 'task_status': 'done', 'company_id': COMPANY,
            'issue_id': child_id, 'agent_id': agent, 'paperclip_run_id': run,
            'session_id': f'paperclip:company:{COMPANY}:agent:{agent}:issue:{child_id}',
            'model': 'gpt-6.1-sol', 'profile': profile, 'profile_sha256': 'b' * 64,
            'signature': 'c' * 64, 'artifacts': [artifact], 'tool_calls': tools,
            'source_refs': [{'framework': 'garak', 'source_url': 'https://github.com/NVIDIA/garak',
                'blob_sha': 'd' * 40, 'sha256': 'e' * 64, 'code_components': ['probes', 'detectors']}],
            'framework_evaluations': [], 'inventory': []}
        if profile == 'system_administration':
            proof['inventory'] = [{'name': f'model-{i}:3b', 'size_bytes': 2000000000 + i,
                'size_gib': 1.86, 'details': {'unneeded_runtime_details': 'x' * 900}} for i in range(10)]
        state.children.append({'id': child_id, 'identifier': 'JAR-' + str(100 + index),
            'status': 'done', 'assigneeAgentId': agent, 'companyId': COMPANY,
            'projectId': PROJECT, 'parentId': ROOT, 'description': '[JARVIS REQUEST initial]\nScoped work'})
        notes = ['[JARVIS OPERATOR QUALITY REVIEW]\nReject the integration claim; the source shows only a standalone probe.'] if quality else []
        entries.append({'issue_id': child_id, 'identifier': 'JAR-' + str(100 + index),
            'worker_summary': ('Model-written report with limitations. ' * 120)[:4000],
            'evidence': proof, 'operator_review_notes': notes,
            'deliverables': [{'id': artifact['id'], 'name': artifact['originalFilename'],
                'sha256': artifact['sha256'], 'excerpt': ('Model-authored report body. ' * 160)[:4000]}]})
    return entries


def test_four_large_specialist_results_fit_without_losing_identity_or_native_proof(plugin, monkeypatch):
    verified = specialist_results(plugin)
    original = copy.deepcopy(verified)
    assert len(json.dumps(verified)) > 42800, 'Regression fixture must exceed the failed live review projection'
    plugin.turn.update(inference_configuration={'version': 3}, plan_decision='delegate',
        latest_user_request='Consolidate the four completed specialist reports.')
    monkeypatch.setattr(plugin.tools, 'verified_children', lambda *args, **kwargs: verified)
    text = plugin.tools.prepare_turn_context(plugin.turn)
    snapshot = decode_preflight(text)
    assert len(text) <= 32000
    assert plugin.turn['child_evidence'] == verified == original
    assert set(plugin.turn['delivered_children']) == {item['issue_id'] for item in verified}
    assert 'FINAL technical report NOW' in snapshot['current_action']
    for projected, item in zip(snapshot['verified_child_results'], verified):
        receipt = projected['verified_receipt_projection']; proof = item['evidence']
        for key in ('version', 'kind', 'task_status', 'company_id', 'issue_id', 'agent_id',
                    'paperclip_run_id', 'session_id', 'profile_sha256', 'signature'):
            assert receipt[key] == proof[key]
        assert receipt['receipt_sha256'] == hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        assert receipt['artifacts'] == proof['artifacts']
        assert receipt['source_refs'] == proof['source_refs']
        call = receipt['tools'][0]
        assert call['tool_call_id'] == proof['tool_calls'][0]['tool_call_id']
        assert call['success'] is True and call['result']['exit_code'] == 0
        assert call['result_sha256'] == proof['tool_calls'][0]['result_sha256']
        assert call['result']['output'].startswith('Observed actual command output')
        assert call['result']['output'].endswith('Ran 2 tests\n\nOK\n')
        assert call['result']['output_excerpt_truncated'] is True
        assert projected['worker_summary_excerpt_truncated'] is True
        assert projected['deliverables'][0]['excerpt_truncated'] is True
    models = snapshot['verified_child_results'][2]['verified_receipt_projection']['inventory']
    assert len(models) == 10
    assert models[0] == {'name': 'model-0:3b', 'size_bytes': 2000000000, 'size_gib': 1.86}


def test_quality_rejections_survive_projection_and_keep_completion_blocked(plugin, monkeypatch):
    verified = specialist_results(plugin, quality=True)
    plugin.turn.update(inference_configuration={'version': 3}, plan_decision='delegate')
    plugin.turn['response'] = ('Verified inventory contains model-0:3b and model-1:3b. '
        'The retrieved reports require factual corrections before this objective can be accepted. '
        'Successful execution provenance does not establish the accuracy of generated prose.')
    monkeypatch.setattr(plugin.tools, 'verified_children', lambda *args, **kwargs: verified)
    snapshot = decode_preflight(plugin.tools.prepare_turn_context(plugin.turn))
    assert 'THE OBJECTIVE IS NOT COMPLETE' in snapshot['current_action']
    assert len(snapshot['required_factual_corrections']) == 4
    for projected, item in zip(snapshot['verified_child_results'], verified):
        assert projected['operator_review_notes'] == item['operator_review_notes']
    plugin.tools.finalize(plugin.turn, completed=True)
    final = next(body for method, path, body, _ in reversed(plugin.calls) if method == 'PATCH' and 'status' in body)
    assert final['status'] == 'blocked' and 'human quality review' in final['comment']


def test_budget_reduces_only_excerpts_while_preserving_human_notes(plugin, monkeypatch):
    verified = specialist_results(plugin, quality=True)
    # A long legitimate objective leaves less room for optional report/output excerpts.
    plugin.issue.update(description='Project requirement. ' * 400)
    plugin.turn.update(inference_configuration={'version': 3}, plan_decision='delegate',
        latest_user_request='Current request. ' * 350)
    monkeypatch.setattr(plugin.tools, 'verified_children', lambda *args, **kwargs: verified)
    text = plugin.tools.prepare_turn_context(plugin.turn)
    assert len(text) <= 32000
    for projected, item in zip(decode_preflight(text)['verified_child_results'], verified):
        assert projected['operator_review_notes'] == item['operator_review_notes']
        assert projected['verified_receipt_projection']['artifacts'] == item['evidence']['artifacts']
    assert any(len(projected['worker_summary']) < 1000 for projected in decode_preflight(text)['verified_child_results'])


def test_irreducible_quality_notes_fail_closed_without_delivery_or_native_writes(plugin, monkeypatch):
    verified = specialist_results(plugin)
    for item in verified:
        item['operator_review_notes'] = ['[JARVIS OPERATOR QUALITY REVIEW]\n' + 'Reject unsupported claim. ' * 600]
    monkeypatch.setattr(plugin.tools, 'verified_children', lambda *args, **kwargs: verified)
    with pytest.raises(ValueError, match='bounded payload limit'):
        plugin.tools.prepare_turn_context(plugin.turn)
    assert not plugin.turn.get('delivered_children') and not plugin.turn.get('child_evidence')
    assert not any(method in ('PATCH', 'POST') for method, *_ in plugin.calls)


def test_large_osint_source_indexes_fit_after_full_verification_without_mutating_receipts(plugin,monkeypatch):
    verified=specialist_results(plugin)[:1];proof=verified[0]['evidence']
    proof['osint_catalog']={'tools':16,'categories':9,'coverage_met':True}
    template=copy.deepcopy(proof['artifacts'][0])
    proof['artifacts'] += [{**template,'id':'source-'+str(i),'originalFilename':'osint-source-'+str(i)+'.json'} for i in range(40)]
    proof['source_refs']=[{'framework':'document:'+str(i),'source_url':'https://github.com/owner/tool-'+str(i),
        'requested_url':'https://github.com/owner/tool-'+str(i),'sha256':'a'*64,'snapshot_artifact_id':'source-'+str(i),
        'immutable_blob_url':'https://api.github.com/repos/owner/tool/git/blobs/'+'b'*40} for i in range(40)]
    original=copy.deepcopy(verified)
    monkeypatch.setattr(plugin.tools,'verified_children',lambda *a,**k:verified)
    plugin.turn.update(inference_configuration={'version':3},plan_decision='delegate')
    text=plugin.tools.prepare_turn_context(plugin.turn);snapshot=decode_preflight(text)
    projected=snapshot['verified_child_results'][0]['verified_receipt_projection']
    assert len(text)<=32000 and verified==original
    assert projected['artifact_count']==41 and projected['source_reference_count']==40
    assert len(projected['source_refs'])==8 and len(projected['artifacts'])==1
    assert projected['source_indexes_compacted'] is True and projected['signature']==proof['signature']


def test_many_specialist_tool_receipts_use_a_counted_hashed_projection_without_losing_failures_or_quality_notes(plugin,monkeypatch):
    verified=specialist_results(plugin,quality=True)
    for item in verified:
        template=item['evidence']['tool_calls'][0]
        item['evidence']['tool_calls']=[{**copy.deepcopy(template),'tool_call_id':'call-'+str(i)} for i in range(30)]
        item['evidence']['tool_calls'][0]['success']=False
        item['evidence']['tool_calls'][0]['result']={'error':'Observed initial fixture failure','exit_code':1}
    original=copy.deepcopy(verified)
    monkeypatch.setattr(plugin.tools,'verified_children',lambda *a,**k:verified)
    plugin.turn.update(inference_configuration={'version':3},plan_decision='delegate')
    text=plugin.tools.prepare_turn_context(plugin.turn)
    assert len(text)<=32000 and verified==original
    for projected,item in zip(decode_preflight(text)['verified_child_results'],verified):
        proof=projected['verified_receipt_projection']
        assert proof['structured_indexes_compacted'] is True and proof['tool_call_count']==30
        assert proof['tool_outcomes']['terminal']=={'successful':29,'failed':1}
        assert proof['full_tool_index_sha256']==hashlib.sha256(json.dumps(item['evidence']['tool_calls'],sort_keys=True).encode()).hexdigest()
        assert any(t['tool_call_id']=='call-0' and not t['success'] for t in proof['tools'])
        assert projected['operator_review_notes']==item['operator_review_notes']
        assert proof['agent_id']==item['evidence']['agent_id'] and proof['signature']==item['evidence']['signature']


def test_compact_review_retains_human_instructions_and_references_a_complete_duplicate_objective(plugin):
    verified=specialist_results(plugin)[:1]
    request='Current human scope and acceptance criteria. '*100
    human={'authorAgentId':None,'body':'Human clarification must remain intact.'}
    snapshot={'objective':{'description':request},'latest_user_request':request,
        'recent_updates':[{'authorAgentId':'ceo','body':'Prior planning prose. '*2000},human]}
    text=plugin.tools.bounded_context_text(snapshot,verified)
    parsed=decode_preflight(text)
    assert len(text)<=32000 and parsed['latest_user_request']==request
    assert parsed['objective']['description_same_as_latest_user_request'] is True
    assert parsed['recent_updates']==[human] and parsed['historical_agent_updates_omitted']==1


def test_incidental_worker_model_inventory_does_not_turn_a_staffing_report_into_an_inventory_request(plugin,monkeypatch):
    verified=specialist_results(plugin)
    monkeypatch.setattr(plugin.tools,'verified_children',lambda *a,**k:verified)
    plugin.turn.update(inference_configuration={'version':3},plan_decision='delegate',needs_inventory=False,
        response='Retain the four employees in their observed roles. The isolated tests and diagnostics succeeded; '
            'the OSINT handoff preserved prior work. This establishes bounded preparation with the documented capability limits.')
    plugin.tools.prepare_turn_context(plugin.turn)
    plugin.tools.finalize(plugin.turn,completed=True)
    final=next(body for method,path,body,_ in reversed(plugin.calls) if method=='PATCH' and 'status' in body)
    assert final['status']=='done' and final['unblockDescriptor'] is None
