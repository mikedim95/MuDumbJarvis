"""Board controls for additional, assignment-specific reads of native text attachments."""
import asyncio
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Depends
from pydantic import BaseModel

from agent_config_lock import async_lock
from agent_work import issue_index, document_reader

spec = spec_from_file_location('jarvis_document_access',Path(__file__).resolve().parents[1]/'hermes-plugin/jarvis_readonly/document_access.py')
access = module_from_spec(spec)
spec.loader.exec_module(access)


class PermissionDecision(BaseModel):
    agent_id: UUID
    source_id: UUID
    artifact_id: UUID
    sha256: str
    state: Literal['allowed','denied','revoked']
    request_id: UUID
    expected_revision: UUID | None = None


async def assignment(p,task_id):
    task=await p.issue(task_id)
    person=next((a for a in await p.agents() if a.get('id')==task.get('assigneeAgentId')
                 and a.get('companyId')==p.company and a.get('reportsTo')==p.ceo),None)
    reader=document_reader(person) if person else None
    if not reader or task.get('hiddenAt') or not task.get('parentId') or not task.get('projectId'):
        raise HTTPException(404,'Select an employee assignment')
    return {**task,'document_reader':reader}


async def candidates(p,task):
    rows=await issue_index(p,task['projectId'])
    return {i:r for i,r in rows.items() if not r.get('hiddenAt') and i!=task['id']
            and (task.get('document_reader')!='siblings' or
                 (r.get('parentId')==task['parentId'] and r.get('status')!='cancelled'))}


async def attachments(p,task,source_id):
    if source_id not in await candidates(p,task):
        raise HTTPException(404,'Source is outside this assignment’s project')
    return [a for a in await p.request('GET',f'issues/{source_id}/attachments')
            if access.eligible(a,p.company,source_id)]


async def permission_document(p,task):
    try:
        return await p.request('GET','issues/'+task['id']+'/documents/'+access.KEY)
    except HTTPException as exc:
        if exc.status_code!=404:raise
        return None


def routes(router,client):
    @router.get('/tasks/{task_id}/document-permissions')
    async def get(task_id:UUID,source_id:UUID|None=None,p=Depends(client)):
        task=await assignment(p,str(task_id))
        if source_id:
            return {'documents':[{k:a[k] for k in ('id','originalFilename','sha256')} for a in
                await attachments(p,task,str(source_id))]}
        doc,approvals,sources=await asyncio.gather(permission_document(p,task),
            p.request('GET',f'issues/{task_id}/approvals'),candidates(p,task))
        ids=(p.company,task['id'],task['assigneeAgentId'])
        overrides=access.owner_decisions(access.owner_rows(doc,*ids[:2]),ids[2])
        requests=access.requests(approvals,*ids)
        rows=[]
        for key in sorted(overrides.keys()|requests.keys()):
            source,artifact=key
            if source not in sources:continue
            a=requests.get(key) or {}; override=overrides.get(key);data=override or a['payload']
            rows.append({'source_id':source,'source':sources[source]['identifier'],'artifact_id':artifact,
                'name':data['name'],'sha256':data['sha256'],'state':override['state'] if override else a['status'],
                'approval_id':a.get('id') if a.get('status')=='pending' else None})
        return {'permissions':rows,'revision':(doc or {}).get('latestRevisionId'),'agent_id':task['assigneeAgentId'],
            'private_sibling_inputs':task['document_reader']=='siblings',
            'sources':[{'id':r['id'],'label':r['identifier']+' · '+r['title']} for r in sources.values()]}

    @router.post('/tasks/{task_id}/document-permissions')
    async def decide(task_id:UUID,body:PermissionDecision,p=Depends(client)):
        async with async_lock(task_id):
            task=await assignment(p,str(task_id))
            if task['assigneeAgentId']!=str(body.agent_id):
                raise HTTPException(409,'The assignment changed; reopen permissions')
            a=next((a for a in await attachments(p,task,str(body.source_id)) if a['id']==str(body.artifact_id)
                    and a['sha256']==body.sha256),None)
            if not a:raise HTTPException(409,'The selected document changed')
            row={'agent':str(body.agent_id),'source':str(body.source_id),'artifact':a['id'],'sha256':a['sha256'],
                 'state':body.state,'name':a['originalFilename']}
            if task['document_reader']=='siblings':
                row['delivery']='private_input'
            current=await permission_document(p,task)
            rows=access.owner_rows(current,p.company,task['id'])
            revision=(current or {}).get('latestRevisionId')
            prior=access.owner_decisions(rows,row['agent']).get((row['source'],row['artifact']))
            if (prior and prior['state']==row['state'] and prior['sha256']==row['sha256']
                    and prior.get('delivery')==row.get('delivery')):
                return {'state':body.state,'artifact_id':row['artifact'],'revision':revision}
            if revision != (str(body.expected_revision) if body.expected_revision else None):
                raise HTTPException(409,'Document permissions changed. Reopen them before saving.')
            if prior:rows.remove(prior)
            if len(rows)>=500:raise HTTPException(422,'This assignment’s permission list is full')
            content=json.dumps(rows+[{**row,'request_id':str(body.request_id)}],sort_keys=True)
            saved=await p.request('PUT',f'issues/{task_id}/documents/'+access.KEY,{'body':content,'title':'Owner document permissions',
                'format':'markdown','baseRevisionId':revision,'changeSummary':'Owner set document access to '+body.state})
            verified=access.owner_decisions(access.owner_rows(saved,p.company,task['id']),row['agent'])
            if verified.get((row['source'],row['artifact']),{}).get('request_id')!=str(body.request_id):
                raise HTTPException(502,'Paperclip did not confirm the permission decision')
            return {'state':body.state,'artifact_id':row['artifact'],'revision':saved['latestRevisionId']}
