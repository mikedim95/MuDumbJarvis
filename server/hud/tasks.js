/* Paperclip owns every task. Browser storage holds only view preferences and
   an unacknowledged submission nonce, never task state or API credentials. */
(() => {
  const el = id => document.getElementById(id);
  const mode = el('commandMode');
  let tasks = [], selected = localStorage.getItem('jarvis-task-selected'), fetching = false, submitting = false;
  let refreshQueued = false, reloadAgents = false, ceoId = null, agents = [];
  let projectVisibilityVersion = 0;
  let objectiveId = localStorage.getItem('jarvis-ceo-objective') || null;
  if (!objectiveId) {
    try { objectiveId = JSON.parse(localStorage.getItem('jarvis-agent-popups-v1') || 'null')?.objective || null; } catch {}
  }
  let pending, lastError = '';
  try { pending = JSON.parse(localStorage.getItem('jarvis-task-pending') || 'null'); } catch {}
  const error = message => { lastError = message; el('taskError').textContent = message; };
  const snapshot = () => ({tasks, selected, agents, ceoId, submitting, objectiveId, error: lastError});
  const announce = () => window.dispatchEvent(new CustomEvent('jarvis-tasks-updated', {detail: snapshot()}));
  const persistent = () => mode.value === 'task' || mode.value === 'objective';
  const projectView = () => document.body.classList.contains('ai-minimal') && !!window.JarvisModes?.snapshot().isWorkView;
  function visualState(task) {
    const active = item => Boolean(item.executionRunId) || (item.runs || []).some(r => r.status === 'running') || (item.children || []).some(active);
    // Presentation snapshot only. Paperclip remains the source of every status.
    window.JarvisTaskVisualState = task ? {identifier: task.identifier, status: task.status, active: active(task)} : null;
    if(!document.body.classList.contains('ai-minimal')||projectView())window.dispatchEvent(new CustomEvent('jarvis-task-visual-state', {detail: window.JarvisTaskVisualState}));
  }
  const agentName = id => {
    const agent = agents.find(item => item.id === id);
    return agent ? agent.name + (agent.role ? ' (' + agent.role + ')' : '') : (id || 'unassigned');
  };

  async function api(path, options = {}) {
    const response = await fetch('/api/' + path, {...options, signal: AbortSignal.timeout(25000)});
    if (response.status === 401) throw new Error('Authentication required. Unlock the HUD and retry.');
    let data;
    try { data = await response.json(); } catch { throw new Error('Invalid response from JARVIS (' + response.status + ').'); }
    if (!response.ok) { const failure = new Error(typeof data.detail === 'string' ? data.detail : 'Request failed (' + response.status + ').'); failure.status = response.status; throw failure; }
    return data;
  }

  function history() {
    el('taskHistory').replaceChildren();
    for (const task of tasks) {
      const button = document.createElement('button');
      const parent = tasks.find(item => item.id === task.parentId);
      button.textContent = task.identifier + ' · ' + task.status + ' · ' +
        (task.parentId ? 'Subtask of ' + (parent?.identifier || task.parentId) + ' · ' : '') + task.title;
      button.setAttribute('aria-current', String(task.id === selected));
      button.onclick = () => { selected = task.id; window.JarvisMonitor.clear(); localStorage.setItem('jarvis-task-selected', selected); history(); detail().catch(e => error(e.message)); };
      el('taskHistory').append(button);
    }
    if (!tasks.length) el('taskHistory').textContent = 'No tasks yet.';
  }

  function updates(task) {
    const lines = [];
    if (task.unblockDescriptor?.action) lines.push('', 'Next action: ' + task.unblockDescriptor.action);
    for (const run of task.runs || []) {
      lines.push('', 'Execution ' + run.runId + ': ' + run.status);
      if (run.error || run.errorCode) lines.push('ERROR: ' + (run.error || run.errorCode));
    }
    for (const comment of [...(task.comments || [])].sort((a, b) => (a.createdAt || '').localeCompare(b.createdAt || ''))) {
      if ((comment.body || '').startsWith('[JARVIS TOOL EVENT]')) continue;
      const body = (comment.body || '').split('\n').filter(line => !line.startsWith('JARVIS_EXECUTION_EVIDENCE=')).join('\n');
      lines.push('', 'Update ' + (comment.createdAt || '') + ' · ' + agentName(comment.authorAgentId || comment.authorUserId), body);
    }
    if (task.status === 'done' && !(task.comments || []).length) lines.push('', 'Task is done in Paperclip, but no result comment was recorded.');
    return lines;
  }

  async function detail() {
    if (!selected) return;
    const target = selected;
    const task = await api('tasks/' + encodeURIComponent(target));
    if (selected !== target) return;
    window.dispatchEvent(new CustomEvent('jarvis-task-detail',{detail:{task}}));
    visualState(task);
    if (document.body.classList.contains('ai-minimal') && task.work_scope !== 'general') return;
    const lines = [task.identifier + ' · ' + task.status, 'Paperclip ID: ' + task.id,
      'Assigned to: ' + agentName(task.assigneeAgentId)];
    if (task.parentId) {
      const parent = tasks.find(item => item.id === task.parentId);
      lines.push('Parent: ' + (parent?.identifier || task.parentId));
    }
    lines.push('', task.description || task.title, ...updates(task));
    if (task.children?.length) {
      lines.push('', 'DELEGATED WORK (' + task.children.length + ')');
      for (const child of task.children) {
        lines.push('', child.identifier + ' · ' + child.status, 'Paperclip ID: ' + child.id,
          'Assigned to: ' + agentName(child.assigneeAgentId), child.description || child.title, ...updates(child));
      }
    }
    el('taskDetail').textContent = lines.join('\n');
    await window.JarvisMonitor.show(task);
  }

  function populateAgents() {
    const isObjective = mode.value === 'objective';
    const previous = localStorage.getItem('jarvis-task-agent') || (!pending?.objective && pending?.agent_id);
    el('taskAgent').replaceChildren();
    for (const agent of agents.filter(item => !isObjective || item.id === ceoId)) {
      const option = document.createElement('option');
      option.value = agent.id;
      option.textContent = agent.name + ' · ' + agent.status + (agent.role ? ' (' + agent.role + ')' : '');
      option.title = agent.lifecycleError || agent.capabilities || agent.lifecycleState;
      option.disabled = agent.lifecycleState !== 'ready';
      if (isObjective || agent.id === previous || (!previous && agent.name === 'JARVIS-01')) option.selected = true;
      el('taskAgent').append(option);
    }
    if (isObjective && !el('taskAgent').options.length) {
      const option = document.createElement('option');
      option.value = ''; option.textContent = 'CEO unavailable'; option.disabled = true;
      el('taskAgent').append(option);
    }
    el('taskAgent').disabled = isObjective;
  }

  async function refresh(loadAgents = false) {
    if (fetching) { refreshQueued = true; reloadAgents ||= loadAgents; return; }
    fetching = true;
    const visibilityVersion = projectVisibilityVersion;
    try {
      if (loadAgents || persistent() || !el('taskAgent').options.length) {
        const data = await api('agents');
        agents = data.agents; ceoId = data.ceo_id || null;
        populateAgents();
      }
      const latestTasks = (await api('tasks')).tasks;
      if(visibilityVersion!==projectVisibilityVersion){refreshQueued=true;return;}
      tasks = latestTasks;
      if (!tasks.some(task => task.id === selected)) selected = tasks[0]?.id || null;
      if (selected) localStorage.setItem('jarvis-task-selected', selected);
      history();
      window.JarvisMonitor.dashboard(await api('monitor'));
      if(!document.body.classList.contains('ai-minimal')||projectView())await detail();
      el('taskConnection').textContent = 'Paperclip connected · ' + tasks.length + ' persistent tasks · updated ' + new Date().toLocaleTimeString();
      if (!pending) error('');
      if (mode.value === 'objective' && !ceoId) error('The Paperclip CEO is not configured. Persistent task and Direct chat remain available.');
    } catch (err) {
      visualState(null);
      el('taskConnection').textContent = 'Paperclip connection failed — displayed data may be stale.';
      error(err.message);
    } finally {
      fetching = false;
      announce();
      if (refreshQueued) {
        const agentsRequested = reloadAgents;
        refreshQueued = false; reloadAgents = false;
        queueMicrotask(() => refresh(agentsRequested));
      }
    }
  }

  async function submit(text, objective = null) {
    if (submitting) return;
    const isObjective = objective === true || (objective === null && mode.value === 'objective');
    if (pending && (pending.task_id || pending.input !== text || Boolean(pending.objective) !== isObjective)) {
      error('A previous submission is awaiting confirmation. Retry its original ' +
        (pending.objective ? 'CEO objective' : 'persistent task') + ' first: ' + pending.input);
      return;
    }
    if (!pending) {
      if (isObjective && !ceoId) { error('No CEO is configured. Refresh and retry.'); return; }
      if (isObjective ? !agents.some(agent => agent.id === ceoId && agent.lifecycleState === 'ready') : !el('taskAgent').value) {
        error('No ready agent is connected. Refresh and retry.'); return;
      }
      pending = {input: text, request_id: crypto.randomUUID(), objective: isObjective};
      if (!isObjective) pending.agent_id = el('taskAgent').value;
      localStorage.setItem('jarvis-task-pending', JSON.stringify(pending));
    }
    submitting = true; el('sendBtn').disabled = true; error('');
    try {
      const task = await api('tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pending)});
      pending = null; localStorage.removeItem('jarvis-task-pending');
      selected = task.id; localStorage.setItem('jarvis-task-selected', selected);
      if (isObjective) { objectiveId = task.id; localStorage.setItem('jarvis-ceo-objective', objectiveId); }
      if (isObjective && document.body.classList.contains('ai-minimal')) {
        window.dispatchEvent(new CustomEvent('jarvis-objective-submitted', {detail: {task}}));
      }
      await refresh();
      return task;
    } catch (err) {
      error(err.message + ' The submission ID has been saved; retrying this text in the same mode is safe.');
    } finally { submitting = false; el('sendBtn').disabled = false; announce(); }
  }

  async function followup(text) {
    if (submitting) return;
    if (pending?.objective && !pending.task_id && pending.input === text) return submitCEO(text);
    if (!objectiveId) return submitCEO(text);
    if (pending && (pending.task_id !== objectiveId || pending.input !== text)) {
      error('A previous submission is awaiting confirmation. Retry its original text before starting another objective or follow-up: ' + pending.input);
      return;
    }
    if (!pending) {
      pending = {input: text, request_id: crypto.randomUUID(), objective: true, task_id: objectiveId};
      localStorage.setItem('jarvis-task-pending', JSON.stringify(pending));
    }
    const target = objectiveId;
    submitting = true; el('sendBtn').disabled = true; error('');
    try {
      const receipt = await api('tasks/' + encodeURIComponent(target) + '/messages', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({input: pending.input, request_id: pending.request_id})});
      if (receipt.task?.id !== target || !receipt.comment_id) throw new Error('The CEO follow-up was not confirmed. Retry the same text.');
      pending = null; localStorage.removeItem('jarvis-task-pending');
      selected = target; localStorage.setItem('jarvis-task-selected', target);
      window.dispatchEvent(new CustomEvent('jarvis-objective-submitted', {detail: {task: receipt.task, followup: true, comment_id: receipt.comment_id}}));
      await refresh(); return receipt.task;
    } catch (err) {
      if (err.status === 404) {
        pending = null; localStorage.removeItem('jarvis-task-pending'); newObjective();
        error('That CEO objective is no longer available. Use /new followed by your objective.');
      } else error(err.message + ' The message ID has been saved; retrying the same text is safe.');
    }
    finally { submitting = false; el('sendBtn').disabled = false; announce(); }
  }

  async function submitCEO(text) {
    try {
      const data = await api('agents'); agents = data.agents; ceoId = data.ceo_id || null;
      return await submit(text, true);
    } catch (err) { error(err.message); announce(); }
  }

  function newObjective() {
    if (pending) throw new Error('A submission is awaiting confirmation. Retry its original text before starting another objective.');
    objectiveId = null; localStorage.removeItem('jarvis-ceo-objective');
    window.dispatchEvent(new CustomEvent('jarvis-ceo-context', {detail: {task_id: null}})); announce();
  }

  async function decide(approvalId, decision, note) {
    if (submitting) return;
    submitting = true; error('');
    try {
      const result = await api('approvals/' + encodeURIComponent(approvalId) + '/decision', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({decision, note})});
      window.dispatchEvent(new Event('jarvis-monitor-changed')); return result;
    } catch (err) { error(err.message); }
    finally { submitting = false; announce(); }
  }

  function changeMode() {
    const isPersistent = persistent();
    visualState(null);
    localStorage.setItem('jarvis-command-mode', mode.value);
    for (const id of ['taskPanel', 'taskAgentLabel', 'taskRefresh']) el(id).hidden = !isPersistent;
    el('feed').hidden = isPersistent; el('clearBtn').hidden = isPersistent;
    el('chatInput').placeholder = document.body.classList.contains('ai-minimal') ? 'Tell JARVIS what you need… · /new starts a new objective' : mode.value === 'objective' ? 'Give the CEO one objective to plan, execute and review…' :
      (isPersistent ? 'Submit a persistent task to the selected agent…' : 'Type to Hermes… (/new resets your conversation)');
    el('sendBtn').textContent = mode.value === 'objective' ? 'SEND OBJECTIVE' : (isPersistent ? 'SEND TASK' : 'SEND');
    if (isPersistent) refresh(true);
  }
  async function projectVisibility(id,removed){
    if(submitting||pending)throw new Error('Finish or retry the pending submission before changing the project list.');
    const task=tasks.find(t=>t.id===id&&!t.parentId&&t.assigneeAgentId===ceoId);
    if(removed&&!task)throw new Error('Project is not in the authenticated CEO history.');
    const receipt=await api('projects/'+encodeURIComponent(id)+(removed?'':'/restore'),{method:removed?'DELETE':'POST'});
    if(receipt.id!==id||receipt.removed!==removed||receipt.task?.id!==id)throw new Error('Project visibility was not confirmed.');
    projectVisibilityVersion++;
    // Hidden projects can disappear from the native collection during the
    // next poll. Undo uses the confirmed native record, not list membership.
    const currentIndex=tasks.findIndex(t=>t.id===id);
    if(currentIndex>=0)tasks=tasks.map(t=>t.id===id?receipt.task:t);
    else tasks=[...tasks,receipt.task].sort((a,b)=>(b.createdAt||'').localeCompare(a.createdAt||''));
    if(removed&&objectiveId===id){objectiveId=null;localStorage.removeItem('jarvis-ceo-objective');window.dispatchEvent(new CustomEvent('jarvis-ceo-context',{detail:{task_id:null}}));}
    if(removed&&selected===id){selected=null;localStorage.removeItem('jarvis-task-selected');window.JarvisMonitor.clear();}
    history();announce();return receipt;
  }
  window.JarvisTasks = {submit, snapshot, followup, newObjective, decide, refresh,
    removeProject:id=>projectVisibility(id,true),restoreProject:id=>projectVisibility(id,false),
    selectObjective: async id => {
      if (pending) throw new Error('A submission is awaiting confirmation. Retry its text before changing projects.');
      if (!tasks.length||!ceoId||!tasks.some(task=>task.id===id)) {
        const [roster,history]=await Promise.all([api('agents'),api('tasks')]);
        agents=roster.agents;ceoId=roster.ceo_id||null;tasks=history.tasks;populateAgents();
      }
      const task=tasks.find(task=>task.id===id&&!task.parentId&&!task.hiddenAt&&task.assigneeAgentId===ceoId);
      if(!task)throw new Error('Project is not in the authenticated CEO history.');
      objectiveId=id;selected=id;localStorage.setItem('jarvis-ceo-objective',id);localStorage.setItem('jarvis-task-selected',id);
      window.dispatchEvent(new CustomEvent('jarvis-objective-submitted',{detail:{task}}));
      history();await detail();announce();return task;
    },
    select: async id => {
      if (!tasks.some(task => task.id === id)) throw new Error('Task is not in the authenticated history.');
      selected = id; localStorage.setItem('jarvis-task-selected', id); history();
      window.JarvisMonitor.clear(); await detail(); announce();
    },
    submitObjective: async text => {
      if (document.body.classList.contains('ai-minimal')) {
        return submitCEO(text);
      }
      mode.value = 'objective'; changeMode();
      return submit(text);
    }
  };
  mode.value = document.body.classList.contains('ai-minimal') ? 'chat' : pending ? (pending.objective ? 'objective' : 'task') : (localStorage.getItem('jarvis-command-mode') || 'objective');
  if (!['chat', 'task', 'objective'].includes(mode.value)) mode.value = 'objective';
  if (pending && persistent()) el('chatInput').value = pending.input;
  mode.onchange = changeMode;
  el('taskAgent').onchange = () => { if (mode.value === 'task') localStorage.setItem('jarvis-task-agent', el('taskAgent').value); };
  el('taskRefresh').onclick = () => { error(''); refresh(true); };
  window.addEventListener('jarvis-reconnected', () => { if (persistent()) refresh(true); });
  window.addEventListener('online', () => { if (persistent()) refresh(true); });
  window.addEventListener('jarvis-monitor-changed', () => { if (persistent()) refresh(true); });
  window.addEventListener('jarvis-mode-changed',event=>{if(['projects','general'].includes(event.detail?.mode))refresh(true);});
  setInterval(() => { if (persistent()||projectView()) refresh(); }, 3000);
  changeMode();
})();
