/* Paperclip owns every task. Browser storage holds only view preferences and
   an unacknowledged submission nonce, never task state or API credentials. */
(() => {
  const el = id => document.getElementById(id);
  const mode = el('commandMode');
  let tasks = [], selected = localStorage.getItem('jarvis-task-selected'), fetching = false, submitting = false;
  let refreshQueued = false, reloadAgents = false;
  let pending;
  try { pending = JSON.parse(localStorage.getItem('jarvis-task-pending') || 'null'); } catch {}
  const error = message => { el('taskError').textContent = message; };

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
      button.textContent = `${task.identifier} · ${task.status} · ${task.title}`;
      button.setAttribute('aria-current', String(task.id === selected));
      button.onclick = () => { selected = task.id; localStorage.setItem('jarvis-task-selected', selected); history(); detail().catch(e => error(e.message)); };
      el('taskHistory').append(button);
    }
    if (!tasks.length) el('taskHistory').textContent = 'No tasks yet.';
  }

  async function detail() {
    if (!selected) return;
    const target = selected;
    const task = await api('tasks/' + encodeURIComponent(target));
    if (selected !== target) return;
    const runs = task.runs || [];
    const lines = [`${task.identifier} · ${task.status}`, `Paperclip ID: ${task.id}`, '', task.description || task.title];
    if (task.unblockDescriptor?.action) lines.push('', 'Needs operator: ' + task.unblockDescriptor.action);
    for (const run of runs) {
      lines.push('', `Execution ${run.runId}: ${run.status}`);
      if (run.error || run.errorCode) lines.push('ERROR: ' + (run.error || run.errorCode));
    }
    for (const comment of [...(task.comments || [])].sort((a, b) => (a.createdAt || '').localeCompare(b.createdAt || ''))) {
      lines.push('', `Update ${comment.createdAt || ''}`, comment.body || '');
    }
    if (task.status === 'done' && !(task.comments || []).length) lines.push('', 'Task is done in Paperclip, but no result comment was recorded.');
    el('taskDetail').textContent = lines.join('\n');
  }

  async function refresh(loadAgents = false) {
    if (fetching) { refreshQueued = true; reloadAgents ||= loadAgents; return; }
    fetching = true;
    try {
      if (loadAgents || mode.value === 'task' || !el('taskAgent').options.length) {
        const data = await api('agents');
        const previous = el('taskAgent').value || pending?.agent_id;
        el('taskAgent').replaceChildren();
        for (const agent of data.agents) {
          const option = document.createElement('option');
          option.value = agent.id;
          option.textContent = `${agent.name} · ${agent.status} (${agent.adapterType})`;
          option.title = agent.lifecycleError || agent.capabilities || agent.lifecycleState;
          option.disabled = agent.lifecycleState !== 'ready';
          if (agent.id === previous || (!previous && agent.name === 'JARVIS-01')) option.selected = true;
          el('taskAgent').append(option);
        }
      }
      tasks = (await api('tasks')).tasks;
      if (!tasks.some(task => task.id === selected)) selected = tasks[0]?.id || null;
      if (selected) localStorage.setItem('jarvis-task-selected', selected);
      history();
      await detail();
      el('taskConnection').textContent = `Paperclip connected · ${tasks.length} persistent tasks · updated ${new Date().toLocaleTimeString()}`;
      if (!pending) error('');
    } catch (err) {
      el('taskConnection').textContent = 'Paperclip connection failed — displayed data may be stale.';
      error(err.message);
    } finally {
      fetching = false;
      if (refreshQueued) {
        const agents = reloadAgents;
        refreshQueued = false; reloadAgents = false;
        queueMicrotask(() => refresh(agents));
      }
    }
  }

  async function submit(text) {
    if (submitting) return;
    if (pending && pending.input !== text) {
      error('A previous submission is awaiting confirmation. Retry its original text first: ' + pending.input);
      return;
    }
    if (!pending) {
      if (!el('taskAgent').value) { error('No ready agent is connected. Refresh and retry.'); return; }
      pending = {input: text, request_id: crypto.randomUUID(), agent_id: el('taskAgent').value};
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
      error(err.message + ' The submission ID has been saved; retrying this text is safe.');
    } finally { submitting = false; el('sendBtn').disabled = false; }
  }

  function changeMode() {
    const isTask = mode.value === 'task';
    localStorage.setItem('jarvis-command-mode', mode.value);
    for (const id of ['taskPanel', 'taskAgentLabel', 'taskRefresh']) el(id).hidden = !isTask;
    el('feed').hidden = isTask; el('clearBtn').hidden = isTask;
    el('chatInput').placeholder = isTask ? 'Submit a persistent task to the selected agent…' : 'Type to Hermes… (/new resets your conversation)';
    el('sendBtn').textContent = isTask ? 'SEND TASK' : 'SEND';
    if (isTask) refresh(true);
  }
  window.JarvisTasks = {submit};
  mode.value = pending ? 'task' : (localStorage.getItem('jarvis-command-mode') || 'chat');
  if (pending) el('chatInput').value = pending.input;
  mode.onchange = changeMode;
  el('taskRefresh').onclick = () => { error(''); refresh(true); };
  window.addEventListener('jarvis-reconnected', () => { if (mode.value === 'task') refresh(true); });
  window.addEventListener('online', () => { if (mode.value === 'task') refresh(true); });
  setInterval(() => {
    if (mode.value === 'task') refresh();
  }, 3000);
  changeMode();
})();
