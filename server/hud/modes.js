/* Navigation holds view preferences and drafts only. Paperclip owns projects. */
(() => {
  if(!document.body.classList.contains('ai-minimal'))return;
  const el=id=>document.getElementById(id),drafts={direct:''};
  const savedMode=localStorage.getItem('jarvis-app-mode');
  let mode=['projects','general'].includes(savedMode)?savedMode:savedMode==='cron'?'general':'direct';
  let projectView=['context','chat','agents','agent-context','cron'].includes(localStorage.getItem('jarvis-project-view'))?localStorage.getItem('jarvis-project-view'):'list';
  let generalView=savedMode==='cron'?'cron':localStorage.getItem('jarvis-general-view')||'overview',generalReturn='overview';
  if(!['overview','agents','run'].includes(generalView))generalView='overview';
  if(['agents','agent-context','cron'].includes(projectView))projectView='chat';
  if(mode==='general'&&generalView==='agents')mode='direct';
  let cronAgentId=null,cronAgentName='';
  let projectSignature='',choosingProject=false,removedProject=null,navigationRevision=0;
  const workView=()=>mode==='projects'&&projectView==='context'||mode==='general'&&generalView==='run';
  const missionId=()=>{const data=window.JarvisTasks.snapshot(),task=data.tasks.find(t=>t.id===data.objectiveId);return task?.mission_id||task?.id||null;};
  const snapshot=()=>({mode,projectView,generalView,navigationRevision,isWorkView:workView(),missionId:missionId(),cronScope:mode==='projects'?'project':'general',cronAgentId,cronAgentName});
  function createdProject(response){
    return response?.administration_updates?.find(r=>r.action==='start_project'&&r.status==='created'&&
      r.task?.id&&r.task.work_scope==='project'&&r.task.mission_id===r.task.id)?.task;
  }
  const draftKey=(view=mode,id=window.JarvisTasks.snapshot().objectiveId)=>view==='projects'||view==='general'&&generalView==='run'?'project:'+(id||'new'):view==='direct'?'direct':'general';
  const busy=()=>choosingProject||(el('sendBtn').disabled&&!el('sendBtn').hasAttribute('data-direct-pending'));
  function displayStatus(task){
    if(task.state==='blocked')return 'Blocked';
    if(task.status==='blocked'&&task.state==='waiting')return 'Waiting';
    if(task.status==='blocked'&&String(task.unblockDescriptor?.action||'').startsWith('Await completion of ')&&
      window.JarvisTasks.snapshot().tasks.some(child=>child.parentId===task.id&&
        (child.executionRunId||['todo','in_progress'].includes(child.status))))return 'Waiting for workers';
    return String(task.status||'recorded').replace(/_/g,' ');
  }
  function filterMessages(){
    const id=window.JarvisTasks.snapshot().objectiveId||'';
    for(const message of el('feed').children){
      message.hidden=workView()?message.dataset.uiMode!=='projects'||(message.dataset.projectId||'')!==id:
        mode!=='direct'||message.dataset.uiMode!=='direct';
    }
  }
  function renderList(projects){
    const signature=JSON.stringify(projects.map(t=>[t.id,t.identifier,t.title,t.status,displayStatus(t)]));
    if(signature!==projectSignature){
      projectSignature=signature;
      const deleteFocused=!!document.activeElement?.dataset.deleteProjectId;
      const focused=document.activeElement?.dataset.projectId||document.activeElement?.dataset.deleteProjectId;
      el('projectList').replaceChildren(...projects.map(task=>{
        const item=document.createElement('li'),button=document.createElement('button');
        button.type='button';button.className='project-list-item';button.dataset.projectId=task.id;
        const meta=document.createElement('span');meta.className='project-item-meta';
        const identifier=document.createElement('span');identifier.textContent=task.identifier;
        const status=document.createElement('span');status.className='project-item-status';status.dataset.status=task.status;
        status.textContent=displayStatus(task);meta.append(identifier,status);
        const title=document.createElement('strong');title.textContent=task.title||task.identifier;
        const remove=document.createElement('button');remove.type='button';remove.className='project-delete-btn';
        remove.dataset.deleteProjectId=task.id;remove.textContent='Delete';remove.title='Remove from project list';
        remove.setAttribute('aria-label','Delete project '+task.identifier);
        remove.onclick=event=>{event.stopPropagation();event.preventDefault();deleteProject(task);};
        button.append(meta,title);button.onclick=()=>openProject(task.id);item.append(button,remove);return item;
      }));
      if(focused){const target=[...el('projectList').querySelectorAll('button')].find(b=>(deleteFocused?b.dataset.deleteProjectId:b.dataset.projectId)===focused);target?.focus({preventScroll:true});}
    }
    for(const button of el('projectList').querySelectorAll('button'))button.disabled=choosingProject;
  }
  function render(){
    const listing=mode==='projects'&&projectView==='list';
    const selected=mode==='projects'&&!listing&&!!missionId();
    window.JarvisTeamWorkspace?.select(selected && projectView === 'context' ? missionId() : null);
    window.JarvisProjectPackages?.select(selected && projectView === 'context' ? missionId() : null);
    const admin=mode==='direct'||mode==='projects'&&projectView==='chat'||mode==='general'&&generalView==='chat';
    const cron=mode==='general'&&generalView==='cron'||mode==='projects'&&projectView==='cron';
    const context=mode==='general'&&generalView==='context'||mode==='projects'&&projectView==='agent-context';
    document.body.dataset.uiMode=mode;document.body.dataset.projectView=projectView;document.body.dataset.generalView=generalView;
    document.body.dataset.workspace='true';
    el('directModeBtn').setAttribute('aria-pressed',String(mode!=='projects'));
    el('projectsModeBtn').setAttribute('aria-pressed',String(mode==='projects'));
    el('generalNav').hidden=listing||mode==='projects'&&!selected;
    el('globalTools').hidden=true;el('projectTools').hidden=listing||mode==='projects'&&!selected;
    el('conversationListHeading').hidden=false;
    el('generalThreads').hidden=el('conversationListHeading').hidden;
    el('generalThreadsStatus').hidden=el('conversationListHeading').hidden;
    el('generalComposer').hidden=!admin;
    el('generalCronBtn').setAttribute('aria-pressed',String(mode==='general'&&generalView==='cron'));
    el('generalAgentsBtn').setAttribute('aria-pressed',String(mode==='general'&&generalView==='agents'));
    const section=mode==='projects'?projectView:mode==='direct'?'chat':generalView;
    el('projectOverviewBtn').setAttribute('aria-pressed',String(section==='context'&&mode==='projects'||section==='overview'));
    el('projectChatBtn').setAttribute('aria-pressed',String(section==='chat'));
    el('projectAgentsBtn').setAttribute('aria-pressed',String(['agents','agent-context','cron'].includes(section)||mode==='general'&&section==='context'));
    el('agentsPanel').hidden=false;el('agentsRail').hidden=false;
    el('projectAgentsBtn').hidden=true;el('generalAgentsBtn').hidden=true;
    el('agentsHeading').textContent=selected?'Project agents':'Agents';
    el('generalOverviewPanel').hidden=mode!=='general'||generalView!=='overview';
    el('projectBrowser').hidden=!listing;
    el('projectContext').hidden=listing;
    if(mode==='general'&&generalView==='run')el('projectContext').hidden=false;
    el('administratorPanel').hidden=!admin;
    el('generalContextPanel').hidden=!context;
    el('chatRow').hidden=!workView()||mode==='projects'&&!!missionId();
    el('feed').hidden=!workView();
    el('cronPanel').hidden=!cron;
    const data=window.JarvisTasks.snapshot(),projects=data.tasks.filter(t=>!t.parentId&&!t.hiddenAt&&t.assigneeAgentId===data.ceoId&&
      (t.work_scope||'project')==='project'&&(!t.mission_id||t.mission_id===t.id));
    renderList(projects);
    el('projectListStatus').textContent=!data.ceoId?'Loading projects…':projects.length?'':data.error||'No projects yet. Start one below.';
    el('newProjectBtn').disabled=choosingProject;
    el('projectRemovalNotice').hidden=!removedProject;
    el('projectRemovalText').textContent=removedProject?removedProject.identifier+' removed from the list.':'';
    el('undoProjectRemoval').disabled=choosingProject;
    const generalWorkspace=mode!=='projects'&&!(mode==='general'&&generalView==='run');
    const current=generalWorkspace?null:data.tasks.find(t=>t.id===(mode==='projects'&&projectView==='cron'?missionId():data.objectiveId));
    el('projectContext').setAttribute('aria-label',generalWorkspace?'General workspace':'Selected project');
    el('projectTitle').textContent=generalWorkspace?'General':current?.title||(data.objectiveId?'Loading project…':'New project');
    el('projectStatus').textContent=generalWorkspace?'Shared context · all projects':current?current.identifier+' · '+displayStatus(current):'';
    el('projectGoal').textContent=current?.description||'';el('projectGoal').hidden=!current?.description;
    const compactTitle=admin&&(mode!=='projects'||!!missionId());
    el('workspaceScopeTitle').hidden=!compactTitle;el('workspaceScopeTitle').textContent=el('projectTitle').textContent;
    el('projectContext').hidden=listing||compactTitle;
    document.body.dataset.compactScope=String(compactTitle);
    el('projectBackBtn').hidden=generalWorkspace;
    el('projectBackBtn').textContent=mode==='general'?'← General':'← Projects';
    el('modeDescription').textContent=listing?'Choose a project or start a new mission.':
      mode==='direct'?'Ask Jarvis anything, including replies and results across projects.':
      mode==='general'&&generalView==='agents'?'Your team and its standing directions.':'';
    el('administratorInput').placeholder=mode==='projects'?'Message Jarvis about this project…':'Message Jarvis…';
    el('administratorInput').setAttribute('aria-label',mode==='projects'?'Project message':'General message');
    el('chatInput').placeholder=mode==='direct'?'Ask Jarvis about your work or anything else…':
      data.objectiveId?'Send Jarvis an update about this project…':'What goal should Jarvis and the workers achieve?';
    el('chatInput').setAttribute('aria-label',mode==='direct'?'Direct chat message':data.objectiveId?'Project update':'New project goal');
    el('sendBtn').textContent=mode==='direct'?'SEND':data.objectiveId?'SEND UPDATE':'SET GOAL';
    filterMessages();
  }
  function notify(){
    navigationRevision++;
    localStorage.setItem('jarvis-app-mode',mode);localStorage.setItem('jarvis-project-view',projectView);
    localStorage.setItem('jarvis-general-view',generalView);
    render();window.dispatchEvent(new CustomEvent('jarvis-mode-changed',{detail:snapshot()}));
  }
  function showProjectList(){
    if(busy())return;
    drafts[draftKey()]=el('chatInput').value;projectView='list';el('modeError').textContent='';notify();
    el('projectsHeading').focus();
  }
  function openAdministrator(){
    setMode('direct');
  }
  async function deleteProject(task){
    if(busy())return;
    choosingProject=true;el('modeError').textContent='';render();
    try{await window.JarvisTasks.removeProject(task.id);removedProject={id:task.id,identifier:task.identifier};}
    catch(error){el('modeError').textContent=error.message;}
    finally{choosingProject=false;render();if(removedProject?.id===task.id)el('undoProjectRemoval').focus({preventScroll:true});}
  }
  async function undoRemoval(){
    if(busy()||!removedProject)return;
    choosingProject=true;el('modeError').textContent='';render();
    try{await window.JarvisTasks.restoreProject(removedProject.id);removedProject=null;}
    catch(error){el('modeError').textContent=error.message;}
    finally{choosingProject=false;render();}
  }
  async function openProject(id){
    if(busy())return;
    drafts[draftKey()]=el('chatInput').value;choosingProject=true;render();el('modeError').textContent='';
    try{
      await window.JarvisTasks.selectObjective(id);
      const task=window.JarvisTasks.snapshot().tasks.find(t=>t.id===id);
      if(task?.work_scope==='general'){if(generalView!=='run')generalReturn=generalView;mode='general';generalView='run';}
      else mode='projects';
      projectView=mode==='projects'&&(!task?.mission_id||task.mission_id===task.id)?'chat':'context';el('chatInput').value=drafts[draftKey()]||'';notify();
      if(mode==='projects'){el('feed').scrollTop=0;el('projectTitle').focus({preventScroll:true});}
      else el('chatInput').focus();
    }catch(error){el('modeError').textContent=error.message;}
    finally{choosingProject=false;render();}
  }
  function newProject(){
    if(busy())return;
    try{
      drafts[draftKey()]=el('chatInput').value;window.JarvisTasks.newObjective();
      for(const message of [...el('feed').children]){
        if(message.dataset.uiMode==='projects'&&!message.dataset.projectId)message.remove();
      }
      projectView='context';el('chatInput').value='';drafts[draftKey()]='';el('modeError').textContent='';notify();el('chatInput').focus();
    }catch(error){el('modeError').textContent=error.message;}
  }
  async function setMode(next,initial=false){
    if(next==='cron'){next='general';generalView='cron';}
    if(!['direct','projects','general'].includes(next)||(!initial&&busy()))return;
    if(!initial){
      drafts[draftKey()]=el('chatInput').value;
      el('chatInput').value=drafts[draftKey(next)]||'';
      if(next==='projects')projectView='list';
      if(next==='general')generalView='overview';
    }
    mode=next;el('modeError').textContent='';notify();
    if(initial&&workView()&&window.JarvisTasks.snapshot().objectiveId){
      try{await window.JarvisTasks.selectObjective(window.JarvisTasks.snapshot().objectiveId);}
      catch(error){if(mode==='projects')el('modeError').textContent=error.message;}
    }
  }
  function setGeneralView(next){
    if(!['overview','chat','cron','context','agents'].includes(next)||busy())return;
    if(next==='agents'){window.JarvisPanels?.open('right');next='chat';}
    if(next==='chat'){mode='direct';notify();return;}
    generalView=next;mode='general';notify();if(next==='chat')el('administratorInput').focus();
    if(next==='agents')el('agentsHeading').focus({preventScroll:true});
  }
  function setProjectView(next){
    if(busy()||!missionId()||!['context','chat','agents','agent-context','cron'].includes(next))return;
    if(next==='agents'){window.JarvisPanels?.open('right');next='chat';}
    mode='projects';projectView=next;notify();
  }
  function openProjectCron(){cronAgentId=null;cronAgentName='';setProjectView('cron');}
  function openAgentCron(id,name){cronAgentId=id;cronAgentName=name;const view=snapshot();if(view.mode==='projects'&&view.projectView!=='list'&&view.missionId)setProjectView('cron');else setGeneralView('cron');}
  function openAgentContext(){const view=snapshot();if(view.mode==='projects'&&view.projectView!=='list'&&view.missionId)setProjectView('agent-context');else setGeneralView('context');}
  window.JarvisModes={snapshot,setMode,setGeneralView,filterMessages,render,showProjectList,openProject,openAdministrator,openProjectCron,createdProject,setProjectView,openAgentContext,openAgentCron};
  el('directModeBtn').onclick=()=>setMode('direct');
  el('projectsModeBtn').onclick=()=>setMode('projects');
  el('generalCronBtn').onclick=()=>setGeneralView('cron');
  el('generalAgentsBtn').onclick=()=>setGeneralView('agents');
  el('projectBackBtn').onclick=()=>mode==='general'?setGeneralView(generalReturn):showProjectList();
  el('projectScheduleBtn').onclick=openProjectCron;
  el('projectOverviewBtn').onclick=()=>mode==='projects'?setProjectView('context'):setGeneralView('overview');
  el('projectChatBtn').onclick=()=>mode==='projects'?setProjectView('chat'):setMode('direct');
  el('projectAgentsBtn').onclick=()=>mode==='projects'?setProjectView('agents'):setGeneralView('agents');
  el('cronBackBtn').onclick=()=>cronAgentId?window.JarvisAgents.open(cronAgentId):mode==='projects'?setProjectView('context'):setGeneralView('agents');
  el('newProjectBtn').onclick=newProject;
  el('undoProjectRemoval').onclick=undoRemoval;
  window.addEventListener('jarvis-tasks-updated',render);
  setMode(mode,true);
})();
