/* Select a portrait for brief status and questions needing an owner reply. */
(() => {
  if (!document.body.classList.contains('ai-minimal')) return;
  const el = id => document.getElementById(id);
  const map = el('agentsMap'), details = el('agentDetails');
  const stateNames = {
    active:'Running', waiting:'Waiting', blocked:'Blocked', idle:'Idle', queued:'Queued',
    paused:'Paused', unavailable:'Unavailable', closed:'Closed', unknown:'Unknown',
  };
  let request = null, snapshot = null, signature = '', selectedId = null, focusAgent = null;
  const replyForms = new Map();
  let loadedScope = null;
  const missionId = () => {const v=window.JarvisModes.snapshot();return v.mode==='projects'&&v.projectView!=='list'?v.missionId:null;};
  const visible = () => !el('agentsRail').hidden && document.body.dataset.rightPanel==='open';
  function activityLabel(agent) {
    if (agent.activity === 'blocked' && !agent.questions?.length &&
        agent.current_work?.next_actor === 'package_service' && agent.current_work.reason === agent.status_reason) {
      return 'Package setup';
    }
    return stateNames[agent.activity] || agent.activity || 'Unknown';
  }
  const entry = (tag, value = '', className = '') => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  function action(label, accessibleName, handle) {
    const button = entry('button',label,'relation-link');
    button.type = 'button';
    button.setAttribute('aria-label',accessibleName);
    button.onclick = handle;
    return button;
  }
  function missionLink(mission, label) {
    if (!mission?.id || mission.hiddenAt) return entry('span',label);
    const link = action(label,'Open project ' + label,() => window.JarvisModes.openProject(mission.id));
    link.dataset.projectId = mission.id;
    return link;
  }
  function replyForm(question) {
    const packageReview = question.kind === 'package_review' || Boolean(question.package);
    const cached = replyForms.get(question.id);
    if (cached && cached.dataset.kind === (packageReview?'package_review':'text')) return cached;
    const form = entry(packageReview?'section':'form','','agent-question');
    form.dataset.kind = packageReview?'package_review':'text';
    form.dataset.questionId = question.id;
    const meta = question.mission?.id === question.task.id
      ? missionLink(question.mission,question.task.identifier)
      : entry('span',question.task.identifier || question.task.title);
    meta.classList.add('agent-question-task');
    const prompt = entry(packageReview?'p':'label',question.question,'agent-question-prompt');
    form.append(meta,prompt);
    if(packageReview){
      const controls=document.createElement('jarvis-package-response');
      controls.setAttribute('task-id',question.task.id);
      controls.setAttribute('question-id',question.id);
      form.append(controls);
      replyForms.set(question.id,form);
      return form;
    }
    const input = entry('textarea');
    input.id = 'agent-reply-' + question.id;
    input.rows = 2;
    input.required = true;
    input.maxLength = 8000;
    input.placeholder = 'Write your reply…';
    prompt.htmlFor = input.id;
    const send = entry('button','Reply');
    send.type = 'submit';
    const error = entry('p','','agent-question-error');
    error.setAttribute('role','status');
    form.append(input,send,error);
    form.onsubmit = async event => {
      event.preventDefault();
      if (send.disabled) return;
      const text = input.value.trim();
      if (!text) {
        error.textContent = 'Write a reply before sending.';
        input.focus();
        return;
      }
      error.textContent = '';
      input.readOnly = send.disabled = true;
      send.textContent = 'Sending…';
      try {
        await window.JarvisTasks.replyToQuestion(question.task.id,question.id,text);
        const hadFocus = form.contains(document.activeElement);
        request?.abort();
        request = null;
        render({...snapshot, agents:snapshot.agents.map(agent => ({...agent,
          questions:(agent.questions || []).filter(item => item.id !== question.id)}))});
        if (hadFocus) (details.querySelector('.agent-question textarea') || el('agentDetailsHeading'))?.focus();
      } catch (err) {
        error.textContent = err.message;
      } finally {
        input.readOnly = send.disabled = false;
        send.textContent = 'Reply';
        load();
      }
    };
    replyForms.set(question.id,form);
    return form;
  }
  function renderDetails(agent) {
    details.hidden = !agent;
    details.replaceChildren();
    if (!agent) { delete details.dataset.agentId; return; }
    details.dataset.agentId = agent.id;
    const activity = agent.activity || 'unknown';
    details.dataset.activity = activity;
    const heading = entry('h3',agent.name);
    heading.id = 'agentDetailsHeading';
    heading.tabIndex = -1;
    const questions = agent.questions || [];
    const recoveries = (agent.work || []).filter(job=>job.recovery);
    const waitingForReply = reason => questions.length && reason?.startsWith('Waiting for your decision.');
    const activeJob = (agent.work || []).find(job => job.state === activity);
    const reason = activity === 'idle' ? '' : activity === 'active' && activeJob
      ? [activeJob.identifier,activeJob.title].filter(Boolean).join(' · ') : agent.status_reason || '';
    const first = reason.split(/(?<=[.!?])\s|\n/)[0];
    const primary = entry('p',first.length > 160 ? first.slice(0,157).trimEnd() + '…' : first,'agent-reason');
    primary.id = 'agentStatusReason';
    const top = entry('div','','agent-detail-heading');
    top.append(heading,entry('span',activityLabel(agent),'agent-activity'));
    details.append(top);
    if (questions.length) {
      const section = entry('section','','agent-questions');
      const title = entry('h4',questions.length === 1 ? 'Question for you' : 'Questions for you');
      title.id = 'agentQuestionsHeading';
      section.setAttribute('aria-labelledby',title.id);
      section.append(title,...questions.map(replyForm));
      details.append(section);
    }
    for(const item of agent.package_decisions || []){
      const current = agent.current_work;
      if (current && item.task?.id !== current.id &&
          (!current.mission?.id || item.mission?.id !== current.mission.id)) continue;
      const result=item.installation?.status==='ready'?(item.package==='nmap'?'Installed (version checks only)':'Installed'):item.decision==='accepted'?'Approved':'Declined';
      details.append(entry('p',item.child+' · '+item.package+' · '+result,'agent-question-task'));
    }
    if(recoveries.length){
      const section=entry('section','','agent-recoveries');section.append(entry('h4','Action needed'));
      for(const job of recoveries){
        const recovery=window.JarvisRecovery?.control(job,'agent');
        if(recovery){if(!recovery.querySelector('.agent-question-task'))recovery.prepend(entry('span',job.identifier||job.title,'agent-question-task'));section.append(recovery);}
      }
      details.append(section);
    }
    const current = entry('section','','agent-work-summary');current.id='agentCurrent';
    current.append(entry('h4','Current work'));
    const job=agent.current_work || activeJob;
    if(job){
      current.append(entry('p',[job.identifier,job.title].filter(Boolean).join(' · '),'agent-current-task'));
      const scope=entry('div','','agent-work-meta');
      if(job.mission)scope.append(missionLink(job.mission,job.mission.title));
      if(job.cron_job)scope.append(entry('span','Cron: '+job.cron_job.title));
      if(scope.childNodes.length)current.append(scope);
    }else current.append(entry('p',activity==='active'?'Running; no linked assignment supplied.':'No current assignment.'));
    if(primary.textContent && activity!=='active' && !recoveries.length && !waitingForReply(primary.textContent))current.append(primary);
    details.append(current);
    const published=entry('section','','agent-work-summary');published.id='agentPublished';
    published.append(entry('h4','Last activity'));
    const recent=agent.recent_activity, latest=recent?.latest;
    const summary=latest?.summary || agent.published_update || (recent
      ? recent.available?'No recorded activity yet.':'Activity could not be loaded. Retrying…'
      : 'Loading latest activity…');
    published.append(entry('p',summary));
    if(latest){
      const meta=entry('div','','agent-work-meta');
      const kind = {tool_result:'Recorded action', owner_decision:'Your decision', package_verification:'Package verification'}[latest.kind] || 'Published update';
      meta.append(entry('span',[latest.task?.identifier,kind].filter(Boolean).join(' · ')));
      const date=new Date(latest.at);
      if(latest.at&&!Number.isNaN(date.valueOf())){
        const time=entry('time',date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}));
        time.dateTime=latest.at;meta.append(time);
      }
      published.append(meta);
    }
    details.append(published);
    const context = action('Context','Open context for '+agent.name,()=>window.JarvisGeneralContext.open(agent.id));
    context.id='agentContextBtn';
    const cron=action('Cron jobs','Open cron jobs for '+agent.name,()=>window.JarvisModes.openAgentCron(agent.id,agent.name));cron.id='agentCronBtn';
    const controls=entry('div','','agent-controls');controls.append(context,cron);details.append(controls);
    const assignments=[...(agent.work||[]),...(agent.past_work||[])].filter(j=>j.parentId&&j.assigneeAgentId===agent.id);
    if(agent.document_permissions&&assignments.length&&window.JarvisDocumentPermissions)details.append(window.JarvisDocumentPermissions.panel(agent,assignments));
    const jobs=(agent.work||[]).slice(0,3), schedules=(agent.schedules||[]).slice(0,3);
    if (jobs.length || schedules.length) {
      const group=entry('details','','agent-group');group.append(entry('summary','Assignments'));

      for (const job of jobs) {
        const label = job.next_actor === 'package_service' && job.state === 'blocked' ? 'Package setup' : stateNames[job.state] || job.state;
        const row=entry('p','','agent-relation');row.append(entry('span',job.identifier+' · '+label));
        if (job.mission) row.append(missionLink(job.mission,job.mission.title));
        if (job.cron_job) row.append(entry('span','Cron: '+job.cron_job.title));
        group.append(row);
      }
      for (const job of schedules) group.append(entry('p','Cron: '+job.title,'agent-relation'));
      details.append(group);
    }
  }
  function focusKey(node) {
    if (node?.classList.contains('agent-station')) return JSON.stringify(['portrait',node.dataset.agentId]);
    if (!details.contains(node)) return null;
    const question = node.closest('[data-question-id]');
    if (question) return JSON.stringify([question.dataset.questionId,node.tagName,node.type,node.dataset.answer,node.hasAttribute('data-other')]);
    const recovery=node.closest('[data-recovery-task-id]');
    if(recovery)return JSON.stringify(['recovery',recovery.dataset.recoveryTaskId,node.tagName,node.type||'']);
    return node.matches('button') ? JSON.stringify([details.dataset.agentId,node.dataset.retryTaskId||node.id||node.dataset.projectId]) : null;
  }

  function select(id,{focus = false,reveal = false,refresh = false} = {}) {
    if (!snapshot) return;
    const agent = snapshot.agents.find(a => a.id === id);
    selectedId = agent?.id || null;
    const cards = [...map.querySelectorAll('.agent-station')];
    for (const card of cards) card.setAttribute('aria-expanded',String(card.dataset.agentId === selectedId));
    renderDetails(agent);
    if(refresh){request?.abort();request=null;load();}
    if (!agent) return;
    if (focus) {
      const tile = cards.find(card => card.dataset.agentId === id);
      tile?.focus({preventScroll:true});
      tile?.scrollIntoView({block:'nearest',inline:'nearest'});
    }
    if (reveal) {
      const panel = el('agentsPanel'), heading = el('agentDetailsHeading');
      // Reveal the reply action as well as the input. Long questions otherwise
      // leave Reply below the bottom edge of the scrollable agent column.
      const firstItem = details.querySelector('.agent-question,.job-retry,#agentPublished') || heading;
      const bottom = firstItem.getBoundingClientRect().bottom;
      panel.scrollTop += Math.max(0,bottom - panel.getBoundingClientRect().bottom + 12);
    }
  }
  function portrait(agent) {
    const state = agent.activity || 'unknown', label = activityLabel(agent);
    const specialization = agent.specialization || agent.title || agent.role || '';
    const card = entry('button','','agent-station');
    card.type = 'button';
    card.dataset.agentId = agent.id;
    card.dataset.activity = state;
    card.setAttribute('aria-controls','agentDetails');
    card.setAttribute('aria-expanded',String(agent.id === selectedId));
    const count = agent.questions?.length || 0;
    const recoveryCount = (agent.work||[]).filter(job=>job.recovery).length;
    const questionLabel = count === 1 ? '1 question for you' : count ? count + ' questions for you' : '';
    card.setAttribute('aria-label',[agent.name,specialization,label,questionLabel,recoveryCount?'Action needed':''].filter(Boolean).join(', '));
    card.onclick = () => select(selectedId === agent.id ? null : agent.id,{reveal:true,refresh:true});
    const frame = entry('span','','agent-likeness');
    const initials = entry('span',agent.name.split(/\s+/).slice(0,2).map(s => s[0]).join(''),'agent-initials');
    initials.setAttribute('aria-hidden','true');
    frame.append(initials);
    if (agent.portrait_url) {
      const image = entry('img','','agent-portrait');
      image.alt = '';
      image.width = 240; image.height = 240;
      image.onerror = () => { image.hidden = true; };
      image.src = agent.portrait_url;
      frame.append(image);
    }
    frame.append(entry('span',label,'agent-activity'));
    if (count || recoveryCount) {
      const badge = entry('span','!','agent-question-badge');
      badge.setAttribute('aria-hidden','true');
      frame.append(badge);
    }
    const name = entry('span',agent.name,'agent-name');
    const role = entry('span',specialization,'agent-specialization');
    card.append(frame,name,role);
    return card;
  }
  function render(data) {
    const next = JSON.stringify(data);
    loadedScope = missionId();
    if (signature !== next) {
      snapshot = data;
      const previousFocus = focusKey(document.activeElement);
      const previousScroll = el('agentTeam')?.scrollLeft || 0;
      const openQuestions = new Set(data.agents.flatMap(agent => (agent.questions || []).map(question => question.id)));
      for (const id of replyForms.keys()) if (!openQuestions.has(id)) replyForms.delete(id);
      const leader = data.agents.find(a => a.id === data.ceo_id);
      const workers = data.agents.filter(a => a !== leader);
      const roster = document.createDocumentFragment();
      if (leader) {
        const top = entry('div'); top.id = 'agentLeader'; top.append(portrait(leader)); roster.append(top);
      }
      if (workers.length) {
        const row = entry('ul'); row.id = 'agentTeam';
        row.setAttribute('aria-label','Team members');
        for (const worker of workers) {
          const item = entry('li'); item.append(portrait(worker)); row.append(item);
        }
        roster.append(row);
      }
      map.replaceChildren(roster);
      if (workers.length) el('agentTeam').scrollLeft = previousScroll;
      select(selectedId);
      if (previousFocus)
        [...map.querySelectorAll('button'),...details.querySelectorAll('button,textarea,select,input')]
          .find(n => focusKey(n) === previousFocus)?.focus({preventScroll:true});
      const running = data.agents.filter(agent => agent.activity === 'active').length;
      el('agentsActivitySummary').textContent = data.agents.length + (data.agents.length === 1 ? ' agent' : ' agents') + ' · ' + running + ' running now';
      signature = next;
    }
    if (focusAgent) {
      const id = focusAgent;
      focusAgent = null;
      select(id,{focus:true,reveal:true,refresh:true});
    }
  }
  async function load() {
    if (!visible() || document.hidden || request) return;
    const originScope=missionId(), originAgent=selectedId;
    const controller = new AbortController();
    request = controller;
    if (!signature) el('agentsNotice').textContent = 'Loading agents…';
    try {
      const query=new URLSearchParams();
      if(originScope)query.set('mission_id',originScope);
      if(originAgent)query.set('agent_id',originAgent);
      const response = await fetch('/api/agents/work'+(query.size?'?'+query:''),{cache:'no-store',
        signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
      if(response.status===404&&originAgent&&!controller.signal.aborted&&originScope===missionId()){
        selectedId=null;renderDetails(null);request=null;load();return;
      }
      if (!response.ok) throw new Error('Could not load agent activity.');
      const data = await response.json();
      if (controller.signal.aborted || !visible() || originScope!==missionId() || originAgent!==selectedId) return;
      el('agentsNotice').textContent = data.agents?.length ? '' : 'No agents are registered.';
      render(data);
    } catch {
      if (!controller.signal.aborted && visible())
        el('agentsNotice').textContent = signature ? 'Connection interrupted. Showing the last update.' : 'Could not load agent activity. Retrying…';
    } finally {
      if (request === controller) request = null;
    }
  }
  function renderWork() {
    const work=window.JarvisTasks.snapshot().tasks.filter(t=>!t.parentId&&!t.hiddenAt&&t.work_scope==='general').slice(0,16);
    el('generalKnowledgeList').replaceChildren(...work.map(task=>{
      const item=entry('li'),button=action([task.identifier,task.title,task.status].filter(Boolean).join(' · '),'Open general work '+task.identifier,()=>window.JarvisModes.openProject(task.id));item.append(button);return item;
    }));
    if(!work.length)el('generalKnowledgeList').textContent='No general work yet.';
  }
  function activate() {
    renderWork();
    if (loadedScope!==missionId()) { request?.abort();request=null;signature='';snapshot=null;selectedId=null;map.replaceChildren();details.hidden=true; }
    loadedScope=missionId();
    if (visible()) { load(); return; }
    request?.abort(); request = null; focusAgent = null;
  }
  window.JarvisAgents = {open(id) {
    const view=window.JarvisModes.snapshot();
    if(view.mode==='projects'&&['agent-context','cron','agents'].includes(view.projectView))window.JarvisModes.setProjectView('chat');
    else if(view.mode==='general'&&['context','cron','agents'].includes(view.generalView))window.JarvisModes.setMode('direct');
    window.JarvisPanels.open('right');
    if (visible()) {
      if (snapshot?.agents.some(a => a.id === id)) select(id,{focus:true,reveal:true,refresh:true});
      else focusAgent = id;
    }
  }};
  window.addEventListener('jarvis-mode-changed',activate);
  window.addEventListener('jarvis-panels-changed',activate);
  window.addEventListener('jarvis-tasks-updated',()=>{renderWork();if(loadedScope!==missionId())activate();});
  window.addEventListener('jarvis-recovery-changed',()=>{request?.abort();request=null;load();});
  document.addEventListener('visibilitychange',() => { if (!document.hidden) load(); });
  setInterval(load,8000);
  activate();
})();
