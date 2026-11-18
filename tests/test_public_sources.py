"""Public HTTPS boundaries, cumulative catalog provenance and coverage."""
import copy
import importlib
import json
import socket
from hashlib import sha256

import pytest
from test_employee_work import work, ISSUE, AGENT, PROJECT, COMPANY, ARTIFACT


@pytest.fixture
def sources(work):
    module=importlib.import_module(work.module.__package__+'.public_sources')
    work.sources=module;return work


@pytest.mark.parametrize('url',['http://example.com','https://user:password@example.com','https://example.com:8443','file:///etc/passwd','https://example.com/\nsecret'])
def test_only_plain_https_document_urls_are_accepted(sources,url):
    with pytest.raises(ValueError):sources.sources.destination(url)


@pytest.mark.parametrize('address',['127.0.0.1','192.168.1.1','169.254.169.254','100.101.41.44','::1','224.0.0.1'])
def test_private_reserved_and_multicast_destinations_are_rejected(sources,monkeypatch,address):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))])
    with pytest.raises(ValueError):sources.sources.destination('https://docs.example.com/')


def test_github_repository_resolves_real_readme_path_and_hash(sources,monkeypatch):
    import base64
    content=b'# Official tool documentation\nCapabilities and limits.'
    monkeypatch.setattr(sources.sources,'fetch',lambda url:(json.dumps({'content':base64.b64encode(content).decode(),
        'sha':'a'*40,'path':'docs/README.md'}).encode(),'application/json',url))
    result=sources.sources.document('https://github.com/owner/tool')
    assert result['source_url']=='https://github.com/owner/tool/blob/HEAD/docs/README.md'
    assert result['sha256']==sha256(content).hexdigest() and result['blob_sha']=='a'*40


def test_github_blob_urls_use_document_bytes_instead_of_navigation_html(sources,monkeypatch):
    import base64
    fetched=[]
    def fetch(url):
        fetched.append(url);return json.dumps({'content':base64.b64encode(b'Actual README text').decode(),
            'path':'docs/README.md','sha':'a'*40}).encode(),'application/json',url
    monkeypatch.setattr(sources.sources,'fetch',fetch)
    data=sources.sources.document('https://github.com/owner/tool/blob/main/docs/README.md')
    assert fetched==['https://api.github.com/repos/owner/tool/contents/docs/README.md?ref=main']
    assert data['text']=='Actual README text'


def test_live_url_sources_are_persisted_and_failures_are_reported_without_fabricating_sources(sources,monkeypatch):
    def document(url):
        if url.endswith('/missing'):raise ValueError('Public source returned HTTP 404')
        return {'requested_url':url,'source_url':url,'sha256':'a'*64,'blob_sha':'','immutable_blob_url':'',
            'repository':'','source_kind':'public_document','retrieved_at':'2026-11-17','text':'Actual docs.'}
    uploads=[]
    monkeypatch.setattr(sources.sources,'document',document)
    monkeypatch.setattr(sources.module,'upload',lambda turn,name,data:uploads.append(json.loads(data)) or {'id':ARTIFACT})
    data=json.loads(sources.module.research_sources({'action':'fetch','urls':['https://docs.example.com/tool','https://docs.example.com/missing']}))
    assert len(data['sources'])==1 and data['retrieval_errors'][0]['error'].endswith('404')
    assert uploads[0]['text']=='Actual docs.'
    assert sources.turn['known_source_urls']=={'https://docs.example.com/tool'}


def catalog(count=15,categories=6):
    return {'catalog_version':'v002','entries':[{'key':'tool:'+str(i),'name':'Tool '+str(i),'category':'Category '+str(i%categories),
        'purpose':'Documentation research','documented_capabilities':['Documented function'],
        'safe_usage_guidance':['Read the docs'],'documented_access_and_cost_prerequisites':{'cost':'unknown'},
        'limitations':['Not tested'],'sources':[{'url':'https://docs.example.com/tool'}],
        'source_retrieval_date_utc':'2026-11-17','validation_status':'documented_only','actually_tested':False} for i in range(count)]}


def test_catalog_coverage_is_based_on_validated_distinct_entries_not_model_claimed_counts(sources):
    sources.turn['known_source_urls']={'https://docs.example.com/tool'}
    result=sources.sources.validate_catalog(sources.turn,json.dumps(catalog()))
    assert result['tools']==15 and result['categories']==6 and result['coverage_met']
    assert not sources.sources.validate_catalog(sources.turn,json.dumps(catalog(3,1)))['coverage_met']
    sources.turn['osint_knowledge']=True
    assert not sources.sources.validate_catalog(sources.turn,json.dumps(catalog()))['coverage_met']
    sources.turn['source_refs']={str(i):{'source_url':'https://docs.example.com/tool'} for i in range(3)}
    assert sources.sources.validate_catalog(sources.turn,json.dumps(catalog()))['coverage_met']


@pytest.mark.parametrize('change',['duplicate','missing-source','untested-claim','missing-fields'])
def test_catalog_deduplication_and_provenance_fail_closed(sources,change):
    sources.turn['known_source_urls']={'https://docs.example.com/tool'};data=catalog()
    if change=='duplicate':data['entries'].append(copy.deepcopy(data['entries'][0]))
    elif change=='missing-source':data['entries'][0]['sources']=[{'url':'https://unretrieved.example/docs'}]
    elif change=='untested-claim':data['entries'][0]['actually_tested']=True
    else:data['entries'][0].pop('limitations')
    with pytest.raises(ValueError):sources.sources.validate_catalog(sources.turn,json.dumps(data))


def test_prior_catalog_is_read_only_company_project_and_agent_scoped(sources,monkeypatch):
    sources.turn['work_scope']={'kind':'general','mission_id':None}
    prior=catalog(3,1);raw=json.dumps(prior).encode();prior_id='66666666-6666-4666-8666-666666666666'
    issues=[{'id':prior_id,'companyId':COMPANY,'projectId':PROJECT,'assigneeAgentId':AGENT,'updatedAt':'2026-11-17','description':'[JARVIS GENERAL WORK]\nShared research'},
        {'id':'foreign','companyId':'other','projectId':PROJECT,'assigneeAgentId':AGENT,'updatedAt':'2026-11-18'}]
    def api(method,path,*args):
        assert method=='GET'
        if path.endswith('/issues'):return issues
        assert path=='/issues/'+prior_id+'/attachments'
        return [{'id':ARTIFACT,'originalFilename':'osint-catalog-v001.json','createdByAgentId':AGENT,'sha256':sha256(raw).hexdigest()}]
    monkeypatch.setattr(sources.module.reporting,'api',api);monkeypatch.setattr(sources.module,'attachment_bytes',lambda identifier:raw)
    result=json.loads(sources.sources.knowledge(sources.turn))
    assert len(result['catalogs'])==1 and sources.turn['prior_osint_catalog']==prior
    assert 'https://docs.example.com/tool' in sources.turn['known_source_urls']


def test_cumulative_publish_merges_prior_entries_without_requiring_model_to_recopy_them(sources,monkeypatch):
    previous=catalog(15,6);sources.turn['prior_osint_catalog']=previous
    sources.turn['known_source_urls']={'https://docs.example.com/tool'}
    fresh=catalog(1,1)['entries'][0];fresh.update(key='new-tool',name='New tool')
    uploads=[]
    monkeypatch.setattr(sources.module,'upload',lambda turn,name,raw:uploads.append(json.loads(raw)) or {'id':ARTIFACT})
    result=json.loads(sources.module.publish_artifact({'name':'osint-catalog-v002.json',
        'content':json.dumps({'preserve_previous':True,'entries':[fresh]})}))
    assert len(uploads[0]['entries'])==16 and result['catalog_validation']['tools']==16


def test_named_record_lookup_reads_native_metadata_and_verified_artifact_bytes(sources,monkeypatch):
    target='77777777-7777-4777-8777-777777777777';raw=b'An existing documentation-only report.'
    sources.issue['description']='Inspect existing JAR-64 evidence; do not duplicate it.'
    def api(method,path,*args):
        assert method=='GET'
        if path.endswith('/issues'):return [{'id':target,'identifier':'JAR-64','companyId':COMPANY,'status':'done','title':'Existing initiative'}]
        assert path=='/issues/'+target+'/attachments'
        return [{'id':ARTIFACT,'originalFilename':'report.md','sha256':sha256(raw).hexdigest(),'byteSize':len(raw)}]
    monkeypatch.setattr(sources.module.reporting,'api',api);monkeypatch.setattr(sources.module,'attachment_bytes',lambda _:raw)
    data=json.loads(sources.sources.records({'issue_ids':['JAR-64']},sources.turn,sources.issue))
    assert data['issues'][0]['status']=='done' and data['issues'][0]['artifacts'][0]['excerpt']==raw.decode()


def test_record_lookup_cannot_expand_to_unmentioned_or_foreign_issues(sources,monkeypatch):
    sources.issue['description']='Inspect only JAR-64.'
    with pytest.raises(PermissionError):sources.sources.records({'issue_ids':['JAR-65']},sources.turn,sources.issue)
    monkeypatch.setattr(sources.module.reporting,'api',lambda *args:[{'id':'foreign','identifier':'JAR-64','companyId':'other'}])
    with pytest.raises(ValueError):sources.sources.records({'issue_ids':['JAR-64']},sources.turn,sources.issue)
