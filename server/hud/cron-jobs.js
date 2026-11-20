/* Native Paperclip schedules. This page owns no timer or work queue. */
(() => {
  if(!document.body.classList.contains('ai-minimal'))return;
  const el=id=>document.getElementById(id);
  const context=()=>{const view=window.JarvisModes?.snapshot();return view?.mode==='general'&&view.generalView==='cron'?{kind:'general',missionId:null,agentId:view.cronAgentId,agentName:view.cronAgentName}:
    view?.mode==='projects'&&view.projectView==='cron'?{kind:'project',missionId:view.missionId,agentId:view.cronAgentId,agentName:view.cronAgentName}:null;};
  const active=()=>!!context(),key=()=>JSON.stringify(context());
  let jobs=[],editing=null,busy=false,loading=null,projects=[],missions=[],runIds={},loadedKey='',editingProject=null;
  let selectedJob=null,focusRequested=false,editingAgent=null;
  try{runIds=JSON.parse(localStorage.getItem('jarvis-cron-pending-runs')||'{}');}catch{}
  const date=(value,zone)=>value?new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short',...(zone?{timeZone:zone}:{})}).format(new Date(value)):'—';
  async function api(path='',options={}){
    const response=await fetch('/api/cron-jobs'+path,{cache:'no-store',...options,signal:AbortSignal.timeout(30000)});
    const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'The schedule could not be updated.');return data;
  }
  function button(text,action){const node=document.createElement('button');node.type='button';node.textContent=text;node.disabled=busy;node.onclick=action;return node;}
  function line(text,cls=''){const node=document.createElement('p');node.textContent=text;if(cls)node.className=cls;return node;}
  async function change(action){
    if(busy)return;busy=true;render();el('cronStatus').textContent='Saving…';
    try{await action();el('cronStatus').textContent='';await load();}
    catch(error){el('cronStatus').textContent=error.message;}
    finally{busy=false;render();}
  }
  function render(){
    const scope=context();if(!scope)return;
    const mission=missions.find(m=>m.id===scope.missionId);
    const focusedCard=el('cronList').querySelector('[data-selected="true"]')===document.activeElement;
    el('cronHeading').textContent=scope.agentName?scope.agentName+' · Cron jobs':scope.kind==='general'?'General cron jobs':'Mission cron jobs';
    el('cronDescription').textContent=scope.kind==='general'?'Recurring work that builds knowledge across missions.':
      mission?.closed?'This mission has ended. Its schedules remain paused.':'Recurring work and knowledge for this mission only.';
    el('cronBackBtn').hidden=false;el('cronBackBtn').textContent=scope.agentId?'← Agent':scope.kind==='project'?'← Overview':'← Agents';
    el('cronList').replaceChildren(...jobs.map(job=>{
      const card=document.createElement('article');card.className='cron-card';card.dataset.jobId=job.id;
      if(job.id===selectedJob){
        card.tabIndex=-1;card.dataset.selected='true';card.setAttribute('aria-label',job.title);
      }
      const heading=document.createElement('div');heading.className='cron-card-heading';
      const title=document.createElement('h3');title.textContent=job.title;
      const status=document.createElement('span');status.className='cron-state';status.dataset.status=job.status;status.textContent=job.status;
      heading.append(title,status);card.append(heading);
      const schedule=job.triggers.find(t=>t.enabled)||job.triggers[0];
      card.append(line(schedule?schedule.cronExpression+' · '+schedule.timezone:'No schedule configured','cron-schedule'));
      card.append(line(job.status==='active'&&schedule?'Next run: '+date(schedule.nextRunAt,schedule.timezone):'Schedule paused.','cron-meta'));
      card.append(line(job.work_scope==='project'?'Scope: this mission':'Scope: General · all missions','cron-meta'));
      card.append(line(job.agent_id?'Agent schedule · orchestrated by Jarvis':'Team schedule · orchestrated by Jarvis','cron-meta'));
      const run=job.last_run;
      const phase=job.execution?.display_status,working=['todo','in_progress','waiting_for_workers'].includes(phase);
      if(working)card.append(line('Current run: '+job.execution.identifier+' · '+phase.replace(/_/g,' '),'cron-meta'));
      if(run){card.append(line((working?'Started: ':'Last run: '+String(run.status||'recorded').replace(/_/g,' ')+' · ')+date(run.triggeredAt,schedule?.timezone),'cron-meta'));
        if(run.failureReason&&!working)card.append(line(run.failureReason,'cron-error'));}
      const goal=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Goal';goal.append(summary,line(job.description));card.append(goal);
      const actions=document.createElement('div');actions.className='cron-actions';
      const runButton=button('Run now',()=>change(async()=>{
        runIds[job.id] ||= crypto.randomUUID();localStorage.setItem('jarvis-cron-pending-runs',JSON.stringify(runIds));
        const result=await api('/'+job.id+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:runIds[job.id]})});
        if(result.failureReason)throw new Error(result.failureReason);
        delete runIds[job.id];localStorage.setItem('jarvis-cron-pending-runs',JSON.stringify(runIds));
      }));runButton.disabled=busy||job.status!=='active'||Boolean(job.active_issue);actions.append(runButton);
      actions.append(button(job.status==='active'?'Pause':'Resume',()=>change(()=>api('/'+job.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:job.status==='active'?'paused':'active'})}))));
      actions.append(button('Edit',()=>edit(job)));
      actions.append(button('Archive',()=>change(()=>api('/'+job.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'archived'})}))));
      const issueId=job.active_issue?.id||run?.linkedIssueId;
      if(issueId)actions.append(button('Open latest run',async()=>{await window.JarvisTasks.refresh();await window.JarvisModes.openProject(issueId);}));
      card.append(actions);return card;
    }));
    if(focusedCard)el('cronList').querySelector('[data-selected="true"]')?.focus({preventScroll:true});
    el('newCronBtn').disabled=el('saveCronBtn').disabled=busy||scope.kind==='project'&&(!mission||mission.closed);
    el('newCronBtn').textContent=scope.kind==='general'?'＋ New general job':'＋ New mission job';
    if(!jobs.length&&!loading&&!busy&&el('cronStatus').textContent==='')el('cronList').append(line('No cron jobs yet. Create a schedule to let Jarvis run work automatically.','cron-meta'));
  }
  async function load(){
    const scope=context(),targetKey=key();if(!scope||loading===targetKey)return;loading=targetKey;
    try{const data=await api('?scope='+scope.kind+(scope.missionId?'&mission_id='+encodeURIComponent(scope.missionId):'')+(scope.agentId?'&agent_id='+encodeURIComponent(scope.agentId):''));
      if(targetKey!==key())return;
      if(loadedKey!==targetKey){editing=null;el('cronForm').hidden=true;}loadedKey=targetKey;
      jobs=data.jobs;projects=data.projects;missions=data.missions||[];
      el('cronStatus').textContent='';
      const selection=el('cronProject').value;el('cronProject').replaceChildren(...projects.map(project=>{const option=document.createElement('option');option.value=project.id;option.textContent=project.name;return option;}));
      if(projects.some(p=>p.id===selection))el('cronProject').value=selection;
      render();
      if(focusRequested){
        focusRequested=false;
        const selected=el('cronList').querySelector('[data-selected="true"]');
        if(selected){selected.focus({preventScroll:true});selected.scrollIntoView({block:'nearest'});}
        else el('cronStatus').textContent='This schedule is no longer listed here.';
      }
    }catch(error){el('cronStatus').textContent=error.message;}
    finally{if(loading===targetKey)loading=null;if(active()&&key()!==targetKey)load();}
  }
  function edit(job=null){
    const scope=context();if(!scope)return;
    editing=job?.id||null;const schedule=job?.triggers[0];
    editingProject=job?.projectId||null;editingAgent=job?job.agent_id||null:scope.agentId||null;
    el('cronTitle').value=job?.title||'';el('cronGoal').value=job?.description||'';
    el('cronExpression').value=schedule?.cronExpression||'0 9 * * *';el('cronTimezone').value=schedule?.timezone||'Europe/Athens';
    if(job)el('cronProject').value=job.projectId;
    el('cronScopeLabel').textContent=scope.kind==='general'?'General: this work builds team knowledge across all missions.':'Mission: this work and its findings stay in the selected mission.';
    el('cronForm').hidden=false;el('cronStatus').textContent='';el('cronTitle').focus();
  }
  el('cronForm').onsubmit=event=>{event.preventDefault();if(!el('cronForm').reportValidity())return;
    const scope=context();if(!scope)return;
    change(async()=>{const body={title:el('cronTitle').value,description:el('cronGoal').value,cron_expression:el('cronExpression').value,timezone:el('cronTimezone').value,
      work_scope:scope.kind,mission_id:scope.missionId,project_id:editingProject||undefined,agent_id:editingAgent};
      await api(editing?'/'+editing:'',{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});el('cronForm').hidden=true;editing=null;});};
  el('newCronBtn').onclick=()=>edit();el('cancelCronBtn').onclick=()=>{el('cronForm').hidden=true;editing=null;};
  function activate(){
    if(!active()){selectedJob=null;focusRequested=false;return;}
    if(loadedKey!==key()){jobs=[];el('cronForm').hidden=true;el('cronStatus').textContent='Loading schedules…';render();}
    load();
  }
  async function openJob(id,missionId=null){
    if(!id)return;
    const modes=window.JarvisModes;
    if(missionId&&!(modes.snapshot().mode==='projects'&&modes.snapshot().missionId===missionId)){
      await modes.openProject(missionId);
      if(modes.snapshot().mode!=='projects'||modes.snapshot().missionId!==missionId)return;
    }
    selectedJob=id;focusRequested=true;
    if(missionId)modes.openProjectCron();else modes.setGeneralView('cron');
    if(!active()){selectedJob=null;focusRequested=false;}
  }
  window.JarvisCron={openJob};
  window.addEventListener('jarvis-mode-changed',activate);
  setInterval(()=>{if(active()&&!document.hidden&&!busy)load();},15000);
  if(active())activate();
})();
