"""Native, owner-controlled supplementary access to one document for one assignment."""
import json
import re
from uuid import UUID

KIND = 'jarvis_document_read'
KEY = 'jarvis-document-permissions'


def owner_rows(doc, company, issue):
    if doc is None:
        return []
    if (doc.get('companyId') != company or doc.get('issueId') != issue or doc.get('key') != KEY
            or not doc.get('updatedByUserId') or doc.get('updatedByAgentId')):
        raise PermissionError('Document permissions require an owner-authored native revision')
    rows = json.loads(doc['body'])
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('Invalid native permission document')
    return rows


def owner_decisions(rows, agent):
    return {(r['source'], r['artifact']):r for r in rows if r['agent']==agent}


def requests(approvals, company, issue, agent):
    result = {}
    for a in sorted(approvals,key=lambda r:(r.get('createdAt') or '', r.get('id') or '')):
        p = a.get('payload') or {}
        if (a.get('companyId') == company and a.get('type') == 'request_board_approval'
                and a.get('requestedByAgentId') == agent and p.get('kind') == KIND
                and p.get('issue_id') == issue and p.get('agent') == agent):
            result[(p.get('source'), p.get('artifact'))] = a
    return result


def eligible(artifact, company, issue):
    return (artifact.get('companyId') == company and artifact.get('issueId') == issue
            and str(artifact.get('originalFilename','')).lower().endswith(('.txt','.json','.md','.csv'))
            and 0 < (artifact.get('byteSize') or 0) <= 131072 and artifact.get('createdByAgentId')
            and bool(re.fullmatch('[a-f0-9]{64}',artifact.get('sha256') or '')))


def assignment_overrides(api, turn):
    try:
        doc = api('GET','/issues/'+turn['issue']+'/documents/'+KEY)
    except Exception as exc:
        if getattr(exc,'code',None)!=404:raise
        doc = None
    return owner_decisions(owner_rows(doc,turn['company'],turn['issue']),turn['agent'])


def granted_sibling_artifacts(api, turn, siblings, artifact_id=None):
    """Resolve individual grants against the producing run across source task transitions."""
    from .employee_work import artifact_run_id
    if not siblings:
        return []
    grants = assignment_overrides(api, turn)
    results = []
    for source in siblings:
        allowed = {aid: grant for (iid, aid), grant in grants.items() if iid == source['id']
                   and grant['state'] == 'allowed' and (not artifact_id or aid == artifact_id)}
        if not allowed:
            continue
        path = '/issues/' + source['id']
        runs = {r['runId'] for r in api('GET', path + '/runs')
                if r.get('agentId') == source.get('assigneeAgentId') and r.get('status') == 'succeeded'}
        for a in api('GET', path + '/attachments'):
            grant = allowed.get(a.get('id'))
            if (grant and eligible(a, turn['company'], source['id']) and a['sha256'] == grant.get('sha256')
                    and a['createdByAgentId'] == source.get('assigneeAgentId') and artifact_run_id(a) in runs):
                results.append({**a, 'issue_id':source['id'], 'identifier':source.get('identifier'),
                    'source_task_status':source['status'], 'access':'granted_input',
                    'private_input':grant.get('delivery') == 'private_input'})
    return results


def record_access(args, turn):
    """Return an exact, checked record selector or a request/decision receipt."""
    from . import employee_work as work
    match = re.fullmatch(r'(request|read) document ([0-9a-fA-F-]{36})', str(args.get('query','')).strip(), re.I)
    if not match:
        return None
    mode, aid = match[1].lower(), str(UUID(match[2]))
    refs = args.get('issue_ids')
    if not isinstance(refs,list) or len(refs)!=1 or not isinstance(refs[0],str):
        raise ValueError('Specify the source issue for the requested document')
    api = work.reporting.api
    company, task, agent = turn['company'],turn['issue'],turn['agent']
    rows = api('GET','/companies/'+company+'/issues')
    source = next((r for r in rows if r.get('companyId')==company and r.get('projectId')==turn['project']
                   and not r.get('hiddenAt') and refs[0].lower() in (r['id'].lower(),str(r.get('identifier')).lower())),None)
    if not source:
        raise PermissionError('Document is unavailable in this assignment’s project')
    key = (source['id'],aid)
    overrides = assignment_overrides(api, turn)
    old = requests(api('GET','/issues/'+task+'/approvals'),company,task,agent).get(key) or {}
    override = overrides.get(key)
    if override and override['state']!='allowed':
        raise PermissionError('The owner '+override['state']+' this additional document permission')
    approved = override or (old.get('payload') if old.get('status')=='approved' and old.get('decidedByUserId') else None)
    if not approved and mode=='read':
        raise PermissionError('Document access requires an owner grant. Use query="request document '+aid+'" to request it.')
    if not approved and old:
        return json.dumps({'approval_id':old['id'],'status':old['status'],'document_read':False})
    artifacts = api('GET','/issues/'+source['id']+'/attachments')
    artifact = next((a for a in artifacts if a.get('id')==aid and eligible(a,company,source['id'])),None)
    if not artifact:
        raise PermissionError('The requested document is unavailable')
    if approved:
        if approved.get('sha256')!=artifact['sha256']:
            raise PermissionError('Document contents changed since the owner grant')
        if mode=='request':
            return json.dumps({'status':'allowed','document_read':False})
        return {**args,'issue_ids':[source['id']],'artifact_id':aid,'materialize':False}
    message='Allow '+source['identifier']+' / '+artifact['originalFilename']+' to be read for this assignment?'
    a = api('POST','/companies/'+company+'/approvals',{'type':'request_board_approval','issueIds':[task],
        'requestedByAgentId':agent,'payload':{'kind':KIND,'proposal':message,'agent':agent,'issue_id':task,
        'source':source['id'],'artifact':aid,'sha256':artifact['sha256'],'name':artifact['originalFilename'],
        'execution':'Read this exact document for this assignment only.'}},turn['run'])
    turn['action_approval']={'id':a['id'],'status':a['status']}
    return json.dumps({'approval_id':a['id'],'status':a['status'],'document_read':False})
