"""Unfinished native evidence can be read without bypassing completed-work gates."""
import json
from hashlib import sha256
from uuid import uuid4

import pytest

from test_public_sources import sources
from test_employee_work import work, COMPANY, AGENT, ARTIFACT


@pytest.fixture
def native(sources, monkeypatch):
    source=str(uuid4())
    raw=json.dumps({'entries':['original bytes: '+('é\\\"' * 2000)]},ensure_ascii=False).encode()
    row={'id':source,'identifier':'JAR-87','companyId':COMPANY,'status':'blocked','title':'Existing research'}
    artifact={'id':ARTIFACT,'issueId':source,'companyId':COMPANY,'originalFilename':'original.json',
        'sha256':sha256(raw).hexdigest(),'byteSize':len(raw),'createdByAgentId':AGENT,'originatingRunId':'source-run'}
    state={'row':row,'artifacts':[artifact],'raw':raw,
           'runs':[{'runId':'source-run','agentId':AGENT,'status':'succeeded'}],'calls':[]}
    sources.issue['description']='Repair JAR-87 using its existing original artifacts.'
    def api(method,path,*args):
        state['calls'].append((method,path))
        assert method=='GET', 'Input retrieval cannot create work or publish knowledge'
        if path.endswith('/issues'):return [state['row']]
        if path=='/issues/'+source+'/attachments':return state['artifacts']
        if path=='/issues/'+source+'/runs':return state['runs']
        pytest.fail('Unexpected native read: '+path)
    monkeypatch.setattr(sources.module.reporting,'api',api)
    monkeypatch.setattr(sources.module,'attachment_bytes',lambda _:state['raw'])
    state['sources']=sources
    return state


def read(native,**args):
    source=native['sources']
    return source.sources.records({'issue_ids':['JAR-87'],**args},source.turn,source.issue)


def test_original_unfinished_artifact_pages_are_bounded_and_materialized_without_completion(native):
    original=dict(native['row'])
    offset=0;chunks=[];path=None
    while offset is not None:
        encoded=read(native,artifact_id=ARTIFACT,offset=offset,limit=2400)
        assert len(encoded)<=5400
        view=json.loads(encoded)['artifact']
        assert view['source_task_status']=='blocked' and view['source_run_status']=='succeeded'
        assert view['originating_run_id']=='source-run' and view['created_by_agent_id']==AGENT
        assert view['sha256']==sha256(native['raw']).hexdigest()
        if offset==0:path=view['workspace_path']
        chunks.append(view['excerpt']);offset=view['next_offset']
    assert ''.join(chunks).encode()==native['raw']
    assert native['sources'].module.read_workspace(native['sources'].turn,path)==native['raw']
    assert native['row']==original


def test_exact_selector_reaches_artifacts_beyond_old_eight_record_limit(native):
    native['artifacts']=[{**native['artifacts'][0],'id':str(uuid4())} for _ in range(12)]+native['artifacts']
    result=json.loads(read(native,artifact_id=ARTIFACT,materialize=False))
    assert result['artifact']['artifact_id']==ARTIFACT
    assert 'workspace_path' not in result['artifact']


def test_research_profile_can_read_original_pages_without_receiving_a_filesystem(native,monkeypatch):
    monkeypatch.setenv('JARVIS_PROFILE','research')
    result=json.loads(read(native,artifact_id=ARTIFACT))
    assert result['artifact']['excerpt'] and 'workspace_path' not in result['artifact']


@pytest.mark.parametrize('change', ['wrong_company','wrong_issue','wrong_run','wrong_author','bad_hash'])
def test_exact_reader_rejects_cross_scope_or_unverifiable_provenance_before_copying(native,change):
    artifact=native['artifacts'][0]
    if change=='wrong_company':artifact['companyId']='other'
    if change=='wrong_issue':artifact['issueId']=str(uuid4())
    if change=='wrong_run':artifact['originatingRunId']='different'
    if change=='wrong_author':artifact['createdByAgentId']=str(uuid4())
    if change=='bad_hash':native['raw']=b'changed bytes'
    with pytest.raises((PermissionError,ValueError)):
        read(native,artifact_id=ARTIFACT)
    assert not (native['sources'].home/'workspace').exists()


@pytest.mark.parametrize('args', [{'offset':-1},{'limit':2401},{'offset':True},{'artifact_offset':True}])
def test_invalid_pagination_is_rejected(native,args):
    with pytest.raises(ValueError):read(native,artifact_id=ARTIFACT,**args)


def test_default_record_discovery_is_bounded_and_has_working_receipt_pagination(native):
    native['artifacts']=[{**native['artifacts'][0],'id':str(uuid4())} for _ in range(11)]
    offset=0;ids=[]
    while offset is not None:
        encoded=read(native,artifact_offset=offset)
        assert len(encoded)<=5400
        response=json.loads(encoded)
        ids.extend(a['id'] for row in response['issues'] for a in row['artifacts'])
        offset=response['next_artifact_offset']
    assert ids==[a['id'] for a in native['artifacts']]


def test_exact_artifact_never_authorizes_an_unnamed_issue(native):
    source=native['sources']
    with pytest.raises(PermissionError):
        source.sources.records({'issue_ids':['JAR-99'],'artifact_id':ARTIFACT},source.turn,source.issue)
    assert not native['calls']


def test_publisher_can_reopen_own_exact_receipt_from_an_unfinished_assignment(native,monkeypatch):
    src = native['sources']
    issue = {**src.issue, 'identifier':'JAR-94', 'status':'blocked', 'description':'Verify your publication.'}
    artifact = {**native['artifacts'][0], 'issueId':issue['id']}
    run = {'agentId':AGENT,'runId':artifact['originatingRunId'],'status':'succeeded'}
    def api(method,path,*args):
        assert method=='GET'
        if path.endswith('/issues'):return [issue]
        if path.endswith('/attachments'):return [artifact]
        if path.endswith('/runs'):return [run]
        pytest.fail(path)
    monkeypatch.setattr(src.module.reporting,'api',api)
    monkeypatch.setenv('JARVIS_PROFILE','research')
    def view():
        return json.loads(src.sources.records({'issue_ids':['JAR-94'],'artifact_id':ARTIFACT},src.turn,issue))['artifact']
    assert view()['sha256']==artifact['sha256'] and 'workspace_path' not in view()
    run['status']='failed'
    with pytest.raises(PermissionError):view()
    run['runId']=artifact['originatingRunId']=src.turn['run']
    run['status']='running'
    assert view()['source_run_status']=='running'
    issue['assigneeAgentId']='other'
    with pytest.raises(PermissionError):view()
