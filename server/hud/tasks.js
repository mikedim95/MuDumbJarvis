/* Paperclip owns every task. Browser storage holds only view preferences and
   an unacknowledged submission nonce, never task state or API credentials. */
(() => {
  const el = id => document.getElementById(id);
  const mode = el('commandMode');
  let tasks = [], selected = localStorage.getItem('jarvis-task-selected'), fetching = false, submitting = false;
  let refreshQueued = false, reloadAgents = false, ceoId = null, agents = [];
  let pending;
  try { pending = JSON.parse(localStorage.getItem('jarvis-task-pending') || 'null'); } catch {}
  const error = message => { el('taskError').textContent = message; };
  const persistent = () => mode.value === 'task' || mode.value === 'objective';
  function visualState(task) {
    const active = item => Boolean(item.executionRunId) || (item.runs || []).some(r => r.status === 'running') || (item.children || []).some(active);
    // Presentation snapshot only. Paperclip remains the source of every status.
    window.JarvisTaskVisualState = task ? {identifier: task.identifier, status: task.status, active: active(task)} : null;
    window.dispatchEvent(new CustomEvent('jarvis-task-visual-state', {detail: window.JarvisTaskVisualState}));
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
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed (' + response.status + ').');
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
    visualState(task);
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
    try {
      if (loadAgents || persistent() || !el('taskAgent').options.length) {
        const data = await api('agents');
        agents = data.agents; ceoId = data.ceo_id || null;
        populateAgents();
      }
      tasks = (await api('tasks')).tasks;
      if (!tasks.some(task => task.id === selected)) selected = tasks[0]?.id || null;
      if (selected) localStorage.setItem('jarvis-task-selected', selected);
      history();
      window.JarvisMonitor.dashboard(await api('monitor'));
      await detail();
      el('taskConnection').textContent = 'Paperclip connected · ' + tasks.length + ' persistent tasks · updated ' + new Date().toLocaleTimeString();
      if (!pending) error('');
      if (mode.value === 'objective' && !ceoId) error('The Paperclip CEO is not configured. Persistent task and Direct chat remain available.');
    } catch (err) {
      visualState(null);
      el('taskConnection').textContent = 'Paperclip connection failed — displayed data may be stale.';
      error(err.message);
    } finally {
      fetching = false;
      if (refreshQueued) {
        const agentsRequested = reloadAgents;
        refreshQueued = false; reloadAgents = false;
        queueMicrotask(() => refresh(agentsRequested));
      }
    }
  }

  async function submit(text) {
    if (submitting) return;
    const isObjective = mode.value === 'objective';
    if (pending && (pending.input !== text || Boolean(pending.objective) !== isObjective)) {
      error('A previous submission is awaiting confirmation. Retry its original ' +
        (pending.objective ? 'CEO objective' : 'persistent task') + ' first: ' + pending.input);
      return;
    }
    if (!pending) {
      if (isObjective && !ceoId) { error('No CEO is configured. Refresh and retry.'); return; }
      if (!el('taskAgent').value) { error('No ready agent is connected. Refresh and retry.'); return; }
      pending = {input: text, request_id: crypto.randomUUID(), objective: isObjective};
      if (!isObjective) pending.agent_id = el('taskAgent').value;
      localStorage.setItem('jarvis-task-pending', JSON.stringify(pending));
    }
    submitting = true; el('sendBtn').disabled = true; error('');
    try {
      const task = await api('tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pending)});
      pending = null; localStorage.removeItem('jarvis-task-pending');
      selected = task.id; localStorage.setItem('jarvis-task-selected', selected);
      el('chatInput').value = '';
      await refresh();
    } catch (err) {
      error(err.message + ' The submission ID has been saved; retrying this text in the same mode is safe.');
    } finally { submitting = false; el('sendBtn').disabled = false; }
  }

  function changeMode() {
    const isPersistent = persistent();
    visualState(null);
    localStorage.setItem('jarvis-command-mode', mode.value);
    for (const id of ['taskPanel', 'taskAgentLabel', 'taskRefresh']) el(id).hidden = !isPersistent;
    el('feed').hidden = isPersistent; el('clearBtn').hidden = isPersistent;
    el('chatInput').placeholder = mode.value === 'objective' ? 'Give the CEO one objective to plan, execute and review…' :
      (isPersistent ? 'Submit a persistent task to the selected agent…' : 'Type to Hermes… (/new resets your conversation)');
    el('sendBtn').textContent = mode.value === 'objective' ? 'SEND OBJECTIVE' : (isPersistent ? 'SEND TASK' : 'SEND');
    if (isPersistent) refresh(true);
  }
  window.JarvisTasks = {submit};
  mode.value = pending ? (pending.objective ? 'objective' : 'task') : (localStorage.getItem('jarvis-command-mode') || 'objective');
  if (!['chat', 'task', 'objective'].includes(mode.value)) mode.value = 'objective';
  if (pending) el('chatInput').value = pending.input;
  mode.onchange = changeMode;
  el('taskAgent').onchange = () => { if (mode.value === 'task') localStorage.setItem('jarvis-task-agent', el('taskAgent').value); };
  el('taskRefresh').onclick = () => { error(''); refresh(true); };
  window.addEventListener('jarvis-reconnected', () => { if (persistent()) refresh(true); });
  window.addEventListener('online', () => { if (persistent()) refresh(true); });
  window.addEventListener('jarvis-monitor-changed', () => { if (persistent()) refresh(true); });
  setInterval(() => { if (persistent()) refresh(); }, 3000);
  changeMode();
})();
