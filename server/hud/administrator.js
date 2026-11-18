/* Paperclip holds General configuration; Hermes owns each conversation's messages. */
(() => {
  if (!document.body.classList.contains('ai-minimal')) return;
  const el = id => document.getElementById(id);
  const input = el('administratorInput'), feed = el('administratorFeed');
  const selectionKey = 'jarvis-general-conversation', creationKey = 'jarvis-general-new-conversation';
  const defaultId = 'default';
  const draftKey = id => id === defaultId ? 'jarvis-administrator-draft' : 'jarvis-general-draft:' + id;
  const state = new Map();
  let current = localStorage.getItem(selectionKey) || defaultId, threads = [];
  let listVersion = 0, creating = false, inGeneral = false, followEnd = true;

  async function api(path, options = {}) {
    const response = await fetch('/api/admin/' + path, {cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || data.detail || 'General chat is unavailable.');
      error.data = data;
      throw error;
    }
    return data;
  }
  const post = body => ({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  function threadState(id) {
    if (!state.has(id)) {
      let draft = {};
      try { draft = JSON.parse(localStorage.getItem(draftKey(id)) || '{}') || {}; } catch {}
      const pending = draft.pending || (draft.request_id ? [draft] : []);
      state.set(id, {draft: draft.text || '', pending, messages: [], loaded: false, loading: null, sending: false, status: ''});
    }
    return state.get(id);
  }
  function saveDraft(id) {
    const {draft, pending} = threadState(id);
    if (draft || pending.length) localStorage.setItem(draftKey(id), JSON.stringify({text: draft, pending}));
    else localStorage.removeItem(draftKey(id));
  }
  function scrollToEnd() { followEnd = true; feed.scrollTop = feed.scrollHeight; }
  feed.addEventListener('scroll', () => { followEnd = feed.scrollHeight - feed.clientHeight - feed.scrollTop < 50; });
  new ResizeObserver(() => { if (followEnd) scrollToEnd(); }).observe(feed);

  function messageElement(message) {
    const row = document.createElement('div');
    row.className = 'msg ' + (message.role === 'user' ? 'you' : message.role === 'assistant' ? 'jarvis' : 'sys');
    row.textContent = message.text;
    if (message.open) {
      const link = document.createElement('button');
      link.type = 'button';
      link.textContent = message.label;
      link.onclick = message.open;
      row.append(' ', link);
    }
    return row;
  }
  function append(id, message) {
    threadState(id).messages.push(message);
    if (id === current) { feed.append(messageElement(message)); scrollToEnd(); }
  }
  function renderComposer() {
    const s = threadState(current);
    el('administratorSend').disabled = s.sending;
    const status = el('administratorStatus');
    status.textContent = s.status || (s.pending.length ? 'Delivery unconfirmed.' : '');
    if (!s.sending) for (const request of s.pending) {
      if (s.draft.trim() === request.text.trim()) continue; // Send retries the restored draft.
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.textContent = s.pending.length === 1 ? 'Retry' : 'Retry “' + request.text.slice(0, 40) + '”';
      retry.title = request.text;
      retry.onclick = () => send(null, request);
      status.append(' ', retry);
    }
  }
  function renderThread() {
    const s = threadState(current);
    el('administratorHeading').textContent = threads.find(t => t.id === current)?.title || 'General chat';
    feed.replaceChildren(...s.messages.map(messageElement));
    input.value = s.draft;
    renderComposer();
    scrollToEnd();
  }
  function renderList() {
    const list = el('generalThreads'), focused = document.activeElement?.dataset.threadId;
    list.replaceChildren(...threads.map(thread => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.threadId = thread.id;
      button.textContent = thread.title;
      button.onclick = () => selectThread(thread.id);
      return button;
    }));
    markCurrent();
    if (focused) [...list.children].find(button => button.dataset.threadId === focused)?.focus({preventScroll: true});
  }
  function markCurrent() {
    const view = window.JarvisModes.snapshot();
    for (const button of el('generalThreads').children) {
      button.setAttribute('aria-current', String(view.mode === 'general' && view.generalView === 'chat' && button.dataset.threadId === current));
    }
  }
  async function history(id) {
    const s = threadState(id);
    if (s.loaded) return;
    if (!s.loading) {
      s.loading = api('history?conversation_id=' + encodeURIComponent(id), {signal: AbortSignal.timeout(20000)})
        .then(data => {
          s.messages = data.messages;
          s.loaded = true;
          if (id === current) renderThread();
        }).finally(() => { s.loading = null; });
    }
    await s.loading;
  }
  function readHistory(id) {
    history(id).catch(error => {
      const s = threadState(id);
      s.status = error.message;
      if (id === current) renderComposer();
    });
  }
  function selectThread(id) {
    current = id;
    localStorage.setItem(selectionKey, id);
    renderList(); renderThread();
    window.JarvisModes.setGeneralView('chat');
    readHistory(id);
  }
  async function loadList() {
    const version = ++listVersion;
    try {
      const data = await api('conversations', {signal: AbortSignal.timeout(20000)});
      if (version !== listVersion) return;
      threads = data.conversations;
      if (!threads.some(t => t.id === current)) {
        current = data.default_id;
        localStorage.setItem(selectionKey, current);
        renderThread();
      }
      el('generalThreadsStatus').textContent = '';
      renderList();
      el('administratorHeading').textContent = threads.find(t => t.id === current)?.title || 'General chat';
      if (window.JarvisModes.snapshot().generalView === 'chat') readHistory(current);
    } catch (error) {
      if (version === listVersion) el('generalThreadsStatus').textContent = error.message;
    }
  }
  async function newThread() {
    if (creating) return;
    creating = true;
    el('newGeneralChat').disabled = true;
    try {
      const id = localStorage.getItem(creationKey) || crypto.randomUUID();
      localStorage.setItem(creationKey, id);
      const thread = await api('conversations', {...post({id}), signal: AbortSignal.timeout(20000)});
      ++listVersion;
      threads = [thread, ...threads.filter(t => t.id !== thread.id)];
      localStorage.removeItem(creationKey);
      el('generalThreadsStatus').textContent = '';
      selectThread(thread.id);
      await loadList();
    } catch (error) {
      el('generalThreadsStatus').textContent = error.message;
    } finally {
      creating = false;
      el('newGeneralChat').disabled = false;
    }
  }
  function showReceipts(id, data) {
    const receipts = [...(data.administration_updates || []), ...(data.general_context_updates || [])];
    for (const r of receipts) {
      const row = {role: 'system'};
      if (['start_project', 'start_general_work'].includes(r.action)) {
        row.text = r.task.identifier + ' · ' + r.task.title;
        row.label = r.action === 'start_project' ? 'Open project' : 'Open general work';
        row.open = () => window.JarvisModes.openProject(r.task.id);
        window.JarvisTasks.refresh();
      } else if (r.job) {
        row.text = 'Saved cron job: ' + r.job.title + ' · ' + r.job.status;
        row.label = 'Cron jobs';
        row.open = async () => {
          if (r.job.work_scope === 'project') {
            await window.JarvisModes.openProject(r.job.mission_id); window.JarvisModes.openProjectCron();
          } else window.JarvisModes.setGeneralView('cron');
        };
      } else if (r.action === 'rename_agent') row.text = 'Saved agent name: ' + r.name;
      else if (r.action === 'set_system_prompt') row.text = 'Saved system prompt for ' + r.name + '. Applies next turn.';
      else row.text = 'Saved standing directions for ' + r.name + '.';
      append(id, row);
    }
    if (receipts.some(r => !r.job && !r.task)) window.dispatchEvent(new Event('jarvis-general-context-updated'));
  }
  async function send(event, previous) {
    event?.preventDefault();
    const id = current, s = threadState(id), text = previous?.text || input.value.trim();
    if (!text || s.sending) return;
    let request = previous || s.pending.find(item => item.text.trim() === text);
    if (!request) {
      request = {text, request_id: crypto.randomUUID()};
      s.pending.push(request);
    }
    if (!previous || input.value.trim() === text) {
      input.value = '';
      s.draft = '';
    }
    saveDraft(id);
    s.sending = true; s.status = 'Jarvis is working…';
    let originRevision, project;
    renderComposer();
    try {
      // Capture the Context target before navigating or waiting for history/configuration.
      const selected = request.scope ? null : window.JarvisGeneralContext.selectedTarget();
      window.JarvisModes.setGeneralView('chat');
      originRevision = window.JarvisModes.snapshot().navigationRevision;
      if (selected) {
        const target = await selected;
        request.agent_id = target.agent_id;
        request.scope = target.scope;
        saveDraft(id);
      }
      await history(id);
      if (!s.messages.some(m => m.requestId === request.request_id)) append(id, {role: 'user', text, requestId: request.request_id});
      const data = await api('chat', post({conversation_id: id, input: text, request_id: request.request_id,
        general_context_agent_id: request.agent_id, prompt_scope: request.scope}));
      project = window.JarvisModes.createdProject(data);
      append(id, {role: 'assistant', text: data.text});
      showReceipts(id, data);
      s.pending = s.pending.filter(item => item !== request);
      s.status = ''; saveDraft(id);
      await loadList();
    } catch (error) {
      project ||= window.JarvisModes.createdProject(error.data);
      if (error.data) showReceipts(id, error.data);
      s.status = error.message;
      if (project) {
        s.pending = s.pending.filter(item => item !== request);
        saveDraft(id);
      } else if (!s.draft) {
        s.draft = text;
        if (id === current) input.value = text;
        saveDraft(id);
      }
    } finally {
      s.sending = false;
      if (id === current) {
        renderComposer();
        const view = window.JarvisModes.snapshot();
        if (view.mode === 'general' && view.generalView === 'chat') {
          if (project && view.navigationRevision === originRevision) await window.JarvisModes.openProject(project.id);
          else input.focus();
        }
      }
    }
  }
  function activate() {
    const view = window.JarvisModes.snapshot(), general = view.mode === 'general';
    markCurrent();
    if (general && !inGeneral) loadList();
    if (general && view.generalView === 'chat' && threads.some(t => t.id === current)) readHistory(current);
    inGeneral = general;
  }
  input.addEventListener('input', () => {
    const s = threadState(current);
    s.draft = input.value;
    saveDraft(current);
    if (s.pending.length && !s.sending) renderComposer();
  });
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  el('administratorForm').addEventListener('submit', send);
  el('newGeneralChat').onclick = newThread;
  window.addEventListener('jarvis-mode-changed', activate);
  renderThread(); activate();
})();
