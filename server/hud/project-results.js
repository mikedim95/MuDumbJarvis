/* Selected projects show their delegation. General runs retain their published reports. */
(() => {
  if(!document.body.classList.contains('ai-minimal'))return;
  const feed=document.getElementById('feed'),contents=new Map();
  const selected=()=>window.JarvisTasks?.snapshot().objectiveId;
  let target=null,version='',signature='',controller=null,card=null,hasPublishedResult=false;
  const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;return node;};
  const treePanel=document.createElement('section');
  treePanel.id='projectDelegation';
  treePanel.className='msg';
  treePanel.dataset.uiMode='projects';
  treePanel.setAttribute('aria-labelledby','delegationHeading');
  let treeSignature='';
  const statusNames={backlog:'Backlog',todo:'To do',in_progress:'In progress',in_review:'In review',
    blocked:'Blocked',done:'Done',cancelled:'Cancelled'};

  function renderDelegation(task){
    const {agents,ceoId}=window.JarvisTasks.snapshot();
    const roster=new Map(agents.map(agent=>[agent.id,agent.name]));
    const shape=['id','identifier','title','status','assigneeAgentId','originKind','brief','progress','result','children',
      'scheduled_runs','state','active_agent_id','cron_job','run_issue','schedules','enabled','mission_id'];
    const signature=JSON.stringify(task,shape)+JSON.stringify([ceoId,...roster]);
    if(signature===treeSignature&&treePanel.isConnected)return;
    treeSignature=signature;
    const runningTimers=new Set();
    const schedulesById=new Map((task.schedules||[]).map(schedule=>[schedule.id,schedule]));

    function cronName(routine){
      const schedule=schedulesById.get(routine.id);
      if(!schedule||!ceoId||schedule.assigneeAgentId!==ceoId||schedule.status==='archived'||
        schedule.mission_id!==task.id||!window.JarvisCron?.openJob)return text('span',routine.title);
      const link=text('button',routine.title,'job-cron-link');
      link.type='button';link.setAttribute('aria-label','Open cron job '+routine.title);
      link.onclick=()=>window.JarvisCron.openJob(routine.id,task.id);
      return link;
    }

    function ownerLink(agentId){
      const name=roster.get(agentId);
      if(!name)return text('span',agentId?'Assigned agent':'Unassigned','job-owner');
      const link=text('button',name,'job-owner');
      link.type='button';link.dataset.agentId=agentId;
      link.setAttribute('aria-label','View '+name+' in Agents');
      link.onclick=()=>window.JarvisAgents.open(agentId);
      return link;
    }

    function branch(job,root=false,scheduled=false){
      const item=document.createElement('li');
      item.dataset.taskId=job.id;
      const card=text('article','','job-node'),meta=text('div','','job-meta');
      if(job.identifier)meta.append(text('span',job.identifier,'job-id'));
      if(scheduled||job.originKind==='routine_execution')meta.append(text('span','Scheduled run','job-kind'));
      if(root&&ceoId&&job.assigneeAgentId===ceoId)meta.append(text('span','CEO','job-kind'));
      const owner=ownerLink(job.assigneeAgentId);
      if(!root)meta.append(owner);
      const status=text('span','','job-state');
      const stateLabel=statusNames[job.status]||String(job.status||'Unknown').replaceAll('_',' ');
      let activity=stateLabel;
      if(job.state==='active')activity+=' · Working now';
      else if(job.status==='in_progress'&&job.state==='waiting')activity+=' · Waiting';
      else if(job.status==='in_progress'&&job.state==='queued')activity+=' · Queued';
      const engagement=text('span',activity,'job-engagement');
      if(job.state)engagement.dataset.state=job.state;
      status.append(engagement);
      status.dataset.status=job.status||'unknown';meta.append(status);
      const title=text('h4',root?'':(job.title||job.identifier||'Untitled job'),'job-title');
      if(root)title.append(owner);
      card.append(meta,title);
      if(job.state==='active'&&job.active_agent_id&&job.active_agent_id!==job.assigneeAgentId){
        const executor=text('p','','job-executor');
        executor.append(text('span','Executing agent','job-routine-label'),ownerLink(job.active_agent_id));
        card.append(executor);
      }
      if(job.cron_job){
        const routine=text('p','','job-routine');
        routine.dataset.routineId=job.cron_job.id;
        routine.append(text('span','Cron job','job-routine-label'),cronName(job.cron_job));
        if(job.run_issue?.identifier)routine.title='Scheduled run '+job.run_issue.identifier;
        if(job.state==='active')runningTimers.add(job.cron_job.id);
        card.append(routine);
      }
      if(job.brief?.progress)card.append(text('p',job.brief.progress,'job-progress'));
      if(job.brief?.result){
        const result=text('p','','job-result');
        result.append(text('strong','Result '),document.createTextNode(job.brief.result));
        card.append(result);
      }
      item.append(card);
      if(job.children?.length){
        const children=text('ul','','delegation-children');
        children.setAttribute('aria-label','Delegated jobs');
        for(const child of job.children)children.append(branch(child));
        item.append(children);
      }
      if(job.scheduled_runs?.length){
        const runs=text('ul','','delegation-scheduled');
        runs.setAttribute('aria-label','Scheduled runs');
        for(const run of job.scheduled_runs)runs.append(branch(run,false,true));
        item.append(runs);
      }
      return item;
    }

    const heading=text('h3','Delegation');heading.id='delegationHeading';
    const list=text('ul','','delegation-tree');
    list.setAttribute('aria-label','Delegation tree');
    list.append(branch(task,true));
    treePanel.dataset.projectId=task.id;
    treePanel.replaceChildren(heading,list);
    if(task.schedules?.length){
      const section=text('section','','project-schedules'),schedules=text('ul','');
      section.append(text('h4','Project schedules'),schedules);
      for(const schedule of task.schedules){
        const item=text('li','');
        item.dataset.routineId=schedule.id;
        const timerState=schedule.status==='active'?(schedule.enabled?'Timer on':'Timer off'):(schedule.status||'Unknown');
        const running=runningTimers.has(schedule.id);
        const details=text('span',(running?'Working now · ':'')+timerState,'schedule-state');
        if(running)details.dataset.running='true';
        const identity=text('span','','schedule-identity');
        identity.append(cronName(schedule));
        if(schedule.assigneeAgentId){
          const owner=text('span','','schedule-owner');
          owner.append(document.createTextNode('Owner '),ownerLink(schedule.assigneeAgentId));
          identity.append(owner);
        }
        item.append(identity,details);schedules.append(item);
      }
      treePanel.append(section);
    }
    if(!treePanel.isConnected)feed.prepend(treePanel);
    window.JarvisModes.filterMessages();
  }

  function publishProjectReply(task){
    const ownerMessage=[...(task.comments||[])].filter(c=>c.body?.startsWith('[JARVIS USER MESSAGE request_id='))
      .sort((a,b)=>String(b.createdAt).localeCompare(String(a.createdAt)))[0];
    if(!ownerMessage)return;
    const replies=(task.comments||[]).filter(c=>c.createdAt>=ownerMessage.createdAt&&
      !/^(?:\[JARVIS |CEO delegated |Paperclip authenticated turn preflight failed)/.test(c.body||''));
    const reply=window.JarvisCEOInput.latestReply({...task,comments:replies});
    if(reply)window.dispatchEvent(new CustomEvent('jarvis-ceo-reply',{detail:{task_id:task.id,
      comment_id:reply.id,text:reply.body,projectConversation:true}}));
  }
  function mount(id){
    card=[...feed.children].find(node=>node.classList.contains('project-results')&&node.dataset.projectId===id);
    if(!card){card=text('section','','msg project-results');card.dataset.uiMode='projects';card.dataset.projectId=id;feed.append(card);}
    window.JarvisModes?.filterMessages();return card;
  }
  function publish(task){
    const reply=window.JarvisCEOInput.latestReply(task);
    if(reply)window.dispatchEvent(new CustomEvent('jarvis-ceo-reply',{detail:{task_id:task.id,
      identifier:task.identifier,comment_id:reply.id,text:reply.body,provenance:'agent_summary'}}));
    return !!reply && !reply.body.startsWith('[JARVIS ') && !!window.JarvisCEOInput.publishedText(reply.body);
  }
  function file(artifact,open=false){
    const details=text('details','','project-file');details.dataset.artifactId=artifact.id;
    const summary=text('summary',artifact.originalFilename);details.append(summary);
    const url='/api/tasks/'+encodeURIComponent(artifact.issueId)+'/artifacts/'+encodeURIComponent(artifact.id);
    const download=text('a','Download');download.href=url;download.download=artifact.originalFilename;
    const meta=text('div','','project-file-actions');meta.append(download,text('small',Math.ceil(artifact.byteSize/1024)+' KB'));
    const preview=text('pre','Open to read this file.','project-file-preview');details.append(meta,preview);
    let loaded=false;
    const load=async()=>{
      if(!details.open||loaded)return;loaded=true;preview.textContent='Loading file…';
      const key=artifact.id+':'+artifact.sha256;
      try{
        if(!contents.has(key)){
          const request=fetch(url,{cache:'no-store',signal:AbortSignal.timeout(25000)}).then(async response=>{
            if(!response.ok)throw new Error('Could not load this file ('+response.status+').');return response.text();
          });contents.set(key,request);
          if(contents.size>24)contents.delete(contents.keys().next().value);
        }
        const value=await contents.get(key);if(preview.isConnected)preview.textContent=value;
      }catch(error){contents.delete(key);loaded=false;preview.textContent=error.message+' Close and reopen to retry.';}
    };
    details.addEventListener('toggle',load);details.open=open;return details;
  }
  function render(data){
    if(data?.task_id!==target||target!==selected()||data.task?.id!==target)return;
    const files=data.artifacts||[],next=JSON.stringify([data.task_id,data.task.status,hasPublishedResult,files.map(a=>[a.id,a.issueId,a.sha256])]);
    if(next===signature&&card?.isConnected)return;
    signature=next;const panel=mount(data.task_id);panel.replaceChildren(text('h3','Reports and research files'));
    if(!files.length){panel.append(text('p',data.task.status==='done'?'No files were published for this run.':'Files will appear here as they are published.'));return;}
    const supporting=artifact=>/^(?:osint-source-|osint-discovery-|research-sources-)/.test(artifact.originalFilename);
    const primary=files.filter(a=>!supporting(a)),sources=files.filter(supporting);
    const report=primary.find(a=>a.issueId===data.task_id&&a.originalFilename==='technical-report.md')||
      primary.find(a=>a.issueId===data.task_id&&/\.(?:md|txt)$/.test(a.originalFilename));
    const scope=new Map((data.graph?.nodes||[]).filter(n=>n.kind==='task').map(n=>[n.native_id,n.label]));
    const groups=new Map();for(const artifact of primary){if(!groups.has(artifact.issueId))groups.set(artifact.issueId,[]);groups.get(artifact.issueId).push(artifact);}
    const ordered=[...groups].sort(([a],[b])=>a===data.task_id?-1:b===data.task_id?1:0);
    for(const [issueId,artifacts] of ordered){
      const group=text('div','','project-file-group');group.append(text('h4',issueId===data.task_id?'Jarvis report':scope.get(issueId)||'Worker files'));
      artifacts.sort((a,b)=>(a.id===report?.id?-1:b.id===report?.id?1:a.originalFilename.localeCompare(b.originalFilename)));
      for(const artifact of artifacts)group.append(file(artifact,!hasPublishedResult && artifact.id===report?.id));panel.append(group);
    }
    if(sources.length){const extra=text('details','','project-source-files');extra.append(text('summary','Source snapshots and supporting files ('+sources.length+')'));
      for(const artifact of sources)extra.append(file(artifact));panel.append(extra);}
  }
  async function load(id){
    controller?.abort();const request=new AbortController();controller=request;
    try{
      const response=await fetch('/api/tasks/'+encodeURIComponent(id)+'/events',{cache:'no-store',signal:AbortSignal.any([request.signal,AbortSignal.timeout(25000)])});
      if(!response.ok)throw new Error('Could not load the published files ('+response.status+').');
      const data=await response.json();if(!request.signal.aborted&&selected()===id)render(data);
    }catch(error){
      if(request.signal.aborted||selected()!==id)return;
      version='';signature='';const panel=mount(id);panel.replaceChildren(text('h3','Reports and research files'),text('p',error.message));
      const retry=text('button','Retry');retry.type='button';retry.onclick=()=>load(id);panel.append(retry);
    }
  }
  window.addEventListener('jarvis-task-detail',event=>{
    const task=event.detail?.task;if(!task||task.id!==selected())return;
    if(task.work_scope!=='general'){
      if(target){controller?.abort();target=null;}
      renderDelegation(task);
      publishProjectReply(task);
      return;
    }
    hasPublishedResult=publish(task);
    if(target!==task.id){target=task.id;version='';signature='';mount(task.id).replaceChildren(text('p','Loading published files…'));}
    const next=JSON.stringify([task.id,task.updatedAt,task.status,(task.children||[]).map(c=>[c.id,c.updatedAt,c.status])]);
    if(next!==version){version=next;load(task.id);}
  });
  window.addEventListener('jarvis-project-snapshot',event=>render(event.detail));
})();
