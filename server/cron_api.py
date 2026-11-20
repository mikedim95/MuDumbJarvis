"""Owner-facing scheduled work, backed entirely by native Paperclip routines."""
import asyncio
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from task_api import Paperclip
import work_scope

_locks={}


class Job(BaseModel):
    title:str=Field(min_length=2,max_length=200)
    description:str=Field(min_length=10,max_length=8000)
    cron_expression:str=Field(default='0 9 * * *',min_length=9,max_length=100)
    timezone:str=Field(default='Europe/Athens',max_length=100)
    project_id:UUID|None=None
    work_scope:Literal['general','project']='general'
    mission_id:UUID|None=None
    agent_id:UUID|None=None


class JobStatus(BaseModel):
    status:Literal['active','paused','archived']


class JobRun(BaseModel):
    request_id:UUID


def agent_focus(row):
    value = next((v.get('defaultValue') for v in row.get('variables') or [] if v.get('name')=='jarvis_agent_id'), None)
    try:return str(UUID(str(value)))
    except ValueError:return None


def projection(row):
    result={k:row.get(k) for k in ('id','title','description','status','projectId','assigneeAgentId','concurrencyPolicy','createdAt','updatedAt')}
    result['triggers']=[{k:t.get(k) for k in ('id','enabled','cronExpression','timezone','nextRunAt','lastFiredAt','lastResult')}
        for t in row.get('triggers',[]) if t.get('kind')=='schedule']
    run=row.get('lastRun') or next(iter(row.get('recentRuns',[])),None)
    result['last_run']={k:run.get(k) for k in ('id','status','triggeredAt','completedAt','linkedIssueId','failureReason')} if run else None
    result['active_issue']={k:row['activeIssue'].get(k) for k in ('id','identifier','title','status')} if row.get('activeIssue') else None
    scope=work_scope.routine_scope(row)
    result.update(work_scope=scope['kind'],mission_id=scope['mission_id'])
    result['description']=work_scope.clean_description(result['description'])
    if agent_focus(row):result['agent_id']=agent_focus(row)
    return result


async def mission(client,identifier,active=False):
    row=await client.issue(identifier)
    if row.get('parentId') or row.get('assigneeAgentId')!=client.ceo or str(row.get('description') or '').startswith(work_scope.GENERAL_PREFIX) or row.get('originKind')=='routine_execution':
        raise HTTPException(404,'Select a mission owned by Jarvis')
    if active and (work_scope.closed(row) or row.get('executionBlocker')):
        raise HTTPException(409,'Reopen this mission before scheduling work')
    if active:
        holds=await client.request('GET','issues/'+str(identifier)+'/tree-holds?status=active')
        if (holds.get('holds',[]) if isinstance(holds,dict) else holds):raise HTTPException(409,'This mission has a stop hold')
    return row


async def pause_mission(client,identifier):
    rows=await client.request('GET','companies/'+client.company+'/routines')
    for row in rows:
        scope=work_scope.routine_scope(row)
        if row.get('companyId')==client.company and row.get('assigneeAgentId')==client.ceo and scope['kind']=='project' and scope['mission_id']==identifier and row.get('status')=='active':
            await client.request('PATCH','routines/'+row['id'],{'status':'paused'})


async def scoped(client,identifier):
    row=await client.request('GET','routines/'+str(identifier))
    if row.get('companyId')!=client.company or row.get('assigneeAgentId')!=client.ceo:
        raise HTTPException(404,'Cron job is outside the Jarvis CEO scope')
    return row


async def save(client,body,identifier=None):
    if body.agent_id:
        from general_context import team
        if str(body.agent_id) not in {a['id'] for a in await team(client)}:
            raise HTTPException(404,'Agent unavailable')
    if len(body.cron_expression.split())!=5 or any(c not in '0123456789*,-/ ' for c in body.cron_expression):
        raise HTTPException(422,'Use a five-field numeric cron expression, for example 0 9 * * *')
    try:ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:raise HTTPException(422,'Use a valid time zone such as Europe/Athens')
    target=await mission(client,body.mission_id,active=True) if body.work_scope=='project' and body.mission_id else None
    if body.work_scope=='project' and target is None:raise HTTPException(422,'Select the mission for this schedule')
    if body.work_scope=='general' and body.mission_id:raise HTTPException(422,'General jobs do not belong to a mission')
    project=str(target['projectId'] if target else body.project_id or client.project)
    projects=await client.request('GET','companies/'+client.company+'/projects')
    if not any(p['id']==project and p.get('companyId')==client.company for p in projects):
        raise HTTPException(404,'Project is outside this company')
    async with _locks.setdefault(client.company,asyncio.Lock()):
        row=await scoped(client,identifier) if identifier else None
        if row is None:
            existing=await client.request('GET','companies/'+client.company+'/routines')
            row=next((r for r in existing if r.get('assigneeAgentId')==client.ceo and r.get('projectId')==project
                and agent_focus(r)==(str(body.agent_id) if body.agent_id else None)
                and r.get('title','').casefold()==body.title.strip().casefold() and r.get('status')!='archived'
                and work_scope.routine_scope(r)['kind']==body.work_scope
                and (work_scope.routine_scope(r)['mission_id'] or None)==(str(body.mission_id) if body.mission_id else None)),None)
        desired_status=row.get('status','active') if row and identifier else 'active'
        if row:
            original=work_scope.routine_scope(row)
            if original['kind']!=body.work_scope or (original['mission_id'] or None)!=(str(body.mission_id) if body.mission_id else None):
                raise HTTPException(409,'Create a separate job to change its General or mission scope')
        fields={'title':body.title.strip(),'description':work_scope.description(body.description.strip(),body.work_scope,body.mission_id),'projectId':project,
            'assigneeAgentId':client.ceo,'concurrencyPolicy':'skip_if_active','catchUpPolicy':'skip_missed','activityGatePolicy':'always'}
        fields['variables']=work_scope.variables((row or {}).get('variables'),body.work_scope,body.mission_id)
        fields['variables']=[v for v in fields['variables'] if v.get('name')!='jarvis_agent_id']
        if body.agent_id:fields['variables'].append({'name':'jarvis_agent_id','type':'text','required':False,'defaultValue':str(body.agent_id)})
        if row:
            await scoped(client,row['id'])
            await client.request('PATCH','routines/'+row['id'],{'status':'paused'})
            await client.request('PATCH','routines/'+row['id'],fields)
        else:row=await client.request('POST','companies/'+client.company+'/routines',{**fields,'status':'paused'})
        detail=await scoped(client,row['id'])
        schedules=[t for t in detail.get('triggers',[]) if t.get('kind')=='schedule' and not t.get('archived')]
        schedule={'cronExpression':body.cron_expression,'timezone':body.timezone,'enabled':True,'label':'Jarvis cron schedule'}
        if schedules:
            await client.request('PATCH','routine-triggers/'+schedules[0]['id'],schedule)
            for extra in schedules[1:]:await client.request('PATCH','routine-triggers/'+extra['id'],{'enabled':False})
        else:await client.request('POST','routines/'+row['id']+'/triggers',{'kind':'schedule',**schedule})
        await client.request('PATCH','routines/'+row['id'],{'status':desired_status})
        return projection(await scoped(client,row['id']))


def build_router(require_auth):
    router=APIRouter(prefix='/api/cron-jobs',dependencies=[Depends(require_auth)])
    async def client():
        native=Paperclip()
        try:yield native
        finally:await native.http.aclose()
    @router.get('')
    async def listing(scope:Literal['general','project']|None=None,mission_id:UUID|None=None,agent_id:UUID|None=None,native:Paperclip=Depends(client)):
        rows=await native.request('GET','companies/'+native.company+'/routines')
        projects=await native.request('GET','companies/'+native.company+'/projects')
        issues=await native.request('GET','companies/'+native.company+'/issues')
        selected_agent=None;related=set()
        if agent_id:
            from general_context import team
            import agent_work
            selected_agent=next((a for a in await team(native) if a['id']==str(agent_id)),None)
            if not selected_agent:raise HTTPException(404,'Agent unavailable')
            index=await agent_work.issue_index(native)
            links=agent_work.WorkLinks(native.company,native.ceo,index,rows)
            for issue in index.values():
                if str(agent_id) in (issue.get('assigneeAgentId'),(issue.get('activeRun') or {}).get('agentId')):
                    job=links.for_issue(issue).get('cron_job')
                    if job:related.add(job['id'])
        jobs=[]
        for row in rows:
            if row.get('companyId')!=native.company or row.get('assigneeAgentId')!=native.ceo or row.get('status')=='archived':continue
            if agent_id and str(agent_id) not in (row.get('assigneeAgentId'),agent_focus(row)) and row['id'] not in related:continue
            view=projection(row);identifier=(view.get('active_issue') or {}).get('id') or (view.get('last_run') or {}).get('linkedIssueId')
            if scope and view['work_scope']!=scope:continue
            if mission_id and view['mission_id']!=str(mission_id):continue
            task=next((i for i in issues if i['id']==identifier and i.get('companyId')==native.company and i.get('assigneeAgentId')==native.ceo),None)
            if task:
                phase=task['status']
                if phase=='blocked' and str((task.get('unblockDescriptor') or {}).get('action','')).startswith('Await completion of ') and any(
                    c.get('parentId')==task['id'] and (c.get('executionRunId') or c.get('status') in ('todo','in_progress')) for c in issues):phase='waiting_for_workers'
                view['execution']={**{k:task.get(k) for k in ('id','identifier','status')},'display_status':phase}
            jobs.append(view)
        return {'jobs':jobs,**({'agent':{k:selected_agent.get(k) for k in ('id','name')}} if selected_agent else {}),
            'projects':[{k:p.get(k) for k in ('id','name')} for p in projects if p.get('companyId')==native.company],
            'missions':[{**{k:i.get(k) for k in ('id','identifier','title','status','projectId')},'closed':work_scope.closed(i)} for i in issues
                if i.get('companyId')==native.company and i.get('assigneeAgentId')==native.ceo and not i.get('parentId') and work_scope.classify(i,issues,rows)['kind']=='project' and work_scope.classify(i,issues,rows)['mission_id']==i['id']],
            'ceo_id':native.ceo,'source':'Paperclip native routines'}
    @router.post('')
    async def create(body:Job,native:Paperclip=Depends(client)):return await save(native,body)
    @router.put('/{identifier}')
    async def edit(identifier:UUID,body:Job,native:Paperclip=Depends(client)):return await save(native,body,identifier)
    @router.patch('/{identifier}')
    async def status(identifier:UUID,body:JobStatus,native:Paperclip=Depends(client)):
        row=await scoped(native,identifier)
        context=work_scope.routine_scope(row)
        if body.status=='active' and context['kind']=='project':await mission(native,context['mission_id'],active=True)
        await native.request('PATCH','routines/'+str(identifier),{'status':body.status})
        return projection(await scoped(native,identifier))
    @router.post('/{identifier}/run')
    async def run(identifier:UUID,body:JobRun,native:Paperclip=Depends(client)):
        job=await scoped(native,identifier)
        context=work_scope.routine_scope(job)
        if context['kind']=='project':await mission(native,context['mission_id'],active=True)
        if job.get('status')!='active':raise HTTPException(409,'Resume this job before running it')
        result=await native.request('POST','routines/'+str(identifier)+'/run',{'source':'manual','idempotencyKey':'jarvis-cron:'+str(body.request_id)})
        return {k:result.get(k) for k in ('id','status','linkedIssueId','failureReason','triggeredAt')}
    return router
