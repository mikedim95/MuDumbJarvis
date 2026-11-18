/* Navigation holds view preferences and drafts only. Paperclip owns projects. */
(() => {
  if(!document.body.classList.contains('ai-minimal'))return;
  const el=id=>document.getElementById(id),drafts={direct:''};
  const savedMode=localStorage.getItem('jarvis-app-mode');
  let mode=['projects','general'].includes(savedMode)?savedMode:savedMode==='cron'?'general':'direct';
  let projectView=['context','cron'].includes(localStorage.getItem('jarvis-project-view'))?localStorage.getItem('jarvis-project-view'):'list';
  let generalView=savedMode==='cron'?'cron':localStorage.getItem('jarvis-general-view')||'chat',generalReturn='cron';
  if(!['chat','cron','context','agents','run'].includes(generalView))generalView='chat';
  let projectSignature='',choosingProject=false,removedProject=null,navigationRevision=0;
  const workView=()=>mode==='projects'&&projectView==='context'||mode==='general'&&generalView==='run';
  const missionId=()=>{const data=window.JarvisTasks.snapshot(),task=data.tasks.find(t=>t.id===data.objectiveId);return task?.mission_id||task?.id||null;};
  const snapshot=()=>({mode,projectView,generalView,navigationRevision,isWorkView:workView(),missionId:missionId(),cronScope:mode==='projects'?'project':'general'});
  function createdProject(response){
    return response?.administration_updates?.find(r=>r.action==='start_project'&&r.status==='created'&&
      r.task?.id&&r.task.work_scope==='project'&&r.task.mission_id===r.task.id)?.task;
  }
  const draftKey=(view=mode,id=window.JarvisTasks.snapshot().objectiveId)=>view==='projects'||view==='general'&&generalView==='run'?'project:'+(id||'new'):view==='direct'?'direct':'general';
  const busy=()=>choosingProject||(el('sendBtn').disabled&&!el('sendBtn').hasAttribute('data-direct-pending'));
  function setSidebar(open){
    document.body.dataset.generalSidebar=open?'open':'closed';
    el('generalSidebarToggle').setAttribute('aria-expanded',String(open));
  }
  function displayStatus(task){
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
    const listing=mode==='projects'&&projectView==='list',admin=mode==='general'&&generalView==='chat';
    const cron=mode==='general'&&generalView==='cron'||mode==='projects'&&projectView==='cron';
    document.body.dataset.uiMode=mode;document.body.dataset.projectView=projectView;document.body.dataset.generalView=generalView;
    el('directModeBtn').setAttribute('aria-pressed',String(mode==='direct'));
    el('projectsModeBtn').setAttribute('aria-pressed',String(mode==='projects'));
    el('generalModeBtn').setAttribute('aria-pressed',String(mode==='general'));
    el('generalNav').hidden=mode!=='general';
    el('generalComposer').hidden=mode!=='general'||generalView==='run';
    el('generalCronBtn').setAttribute('aria-pressed',String(generalView==='cron'));
    el('generalContextBtn').setAttribute('aria-pressed',String(generalView==='context'));
    el('generalAgentsBtn').setAttribute('aria-pressed',String(generalView==='agents'));
    el('agentsPanel').hidden=mode!=='general'||generalView!=='agents';
    el('projectBrowser').hidden=!listing;
    el('projectContext').hidden=!workView()&&!(mode==='projects'&&projectView==='cron');
    el('administratorPanel').hidden=!admin;
    el('generalContextPanel').hidden=mode!=='general'||generalView!=='context';
    el('chatRow').hidden=mode!=='direct'&&!workView();
    el('cronPanel').hidden=!cron;
    const data=window.JarvisTasks.snapshot(),projects=data.tasks.filter(t=>!t.parentId&&!t.hiddenAt&&t.assigneeAgentId===data.ceoId&&
      (t.work_scope||'project')==='project'&&(!t.mission_id||t.mission_id===t.id));
    renderList(projects);
    el('projectListStatus').textContent=!data.ceoId?'Loading projects…':projects.length?'':data.error||'No projects yet. Start one below.';
    el('newProjectBtn').disabled=choosingProject;
    el('projectRemovalNotice').hidden=!removedProject;
    el('projectRemovalText').textContent=removedProject?removedProject.identifier+' removed from the list.':'';
    el('undoProjectRemoval').disabled=choosingProject;
    const current=data.tasks.find(t=>t.id===(mode==='projects'&&projectView==='cron'?missionId():data.objectiveId));
    el('projectTitle').textContent=current?.title||(data.objectiveId?'Loading project…':'New project');
    el('projectStatus').textContent=current?current.identifier+' · '+displayStatus(current):'';
    el('projectBackBtn').textContent=mode==='general'?'← General':'← Projects';
    el('projectScheduleBtn').hidden=mode!=='projects'||projectView!=='context'||!current;
    el('modeDescription').textContent=mode==='direct'?'Brief conversations with your Paperclip context.':
      listing?'Missions with their own context, knowledge, and schedules.':mode==='general'&&generalView!=='run'?'Standing directions and knowledge for the whole team.':'';
    el('chatInput').placeholder=mode==='direct'?'Ask Jarvis about your work or anything else…':
      data.objectiveId?'Send Jarvis an update about this project…':'What goal should Jarvis and the workers achieve?';
    el('chatInput').setAttribute('aria-label',mode==='direct'?'Direct chat message':data.objectiveId?'Project update':'New project goal');
    el('sendBtn').textContent=mode==='direct'?'SEND':data.objectiveId?'SEND UPDATE':'SET GOAL';
    filterMessages();
  }
  function notify(){
    navigationRevision++;
    setSidebar(false);
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
    setMode('general');setGeneralView('chat');
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
      projectView='context';el('chatInput').value=drafts[draftKey()]||'';notify();
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
      if(next==='general'&&generalView==='run')generalView='chat';
    }
    mode=next;el('modeError').textContent='';notify();
    if(initial&&workView()&&window.JarvisTasks.snapshot().objectiveId){
      try{await window.JarvisTasks.selectObjective(window.JarvisTasks.snapshot().objectiveId);}
      catch(error){if(mode==='projects')el('modeError').textContent=error.message;}
    }
  }
  function setGeneralView(next){
    if(!['chat','cron','context','agents'].includes(next)||busy())return;
    generalView=next;mode='general';notify();if(next==='chat')el('administratorInput').focus();
    if(next==='agents')el('agentsHeading').focus({preventScroll:true});
  }
  function openProjectCron(){if(busy()||!missionId())return;projectView='cron';mode='projects';notify();}
  window.JarvisModes={snapshot,setMode,setGeneralView,filterMessages,render,showProjectList,openProject,openAdministrator,openProjectCron,createdProject};
  el('directModeBtn').onclick=()=>setMode('direct');
  el('projectsModeBtn').onclick=()=>setMode('projects');
  el('generalModeBtn').onclick=()=>setMode('general');
  el('generalCronBtn').onclick=()=>setGeneralView('cron');
  el('generalAgentsBtn').onclick=()=>setGeneralView('agents');
  el('projectBackBtn').onclick=()=>mode==='general'?setGeneralView(generalReturn):showProjectList();
  el('projectScheduleBtn').onclick=openProjectCron;
  el('cronBackBtn').onclick=()=>openProject(missionId());
  el('generalSidebarToggle').onclick=()=>setSidebar(document.body.dataset.generalSidebar!=='open');
  document.addEventListener('click',event=>{
    if(document.body.dataset.generalSidebar==='open'&&!event.target.closest('#generalNav,#generalSidebarToggle'))setSidebar(false);
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&document.body.dataset.generalSidebar==='open'){
      setSidebar(false);el('generalSidebarToggle').focus();event.preventDefault();
    }
  });
  el('newProjectBtn').onclick=newProject;
  el('undoProjectRemoval').onclick=undoRemoval;
  window.addEventListener('jarvis-tasks-updated',render);
  setMode(mode,true);
})();
