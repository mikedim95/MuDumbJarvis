/* The selected configuration is the default target of a General chat message. */
(() => {
  if (!document.body.classList.contains('ai-minimal')) return;
  const el = id => document.getElementById(id);
  const selector = el('generalAgentList');
  let targets = [], selected = null, loading = null, ceoId = null;
  const active = () => {
    const view = window.JarvisModes.snapshot();
    return view.mode === 'general' && view.generalView === 'context';
  };
  const target = () => targets.find(item => item.key === selected);
  function showTarget() {
    const item = target();
    if (!item) return;
    selector.value = selected;
    const notes = item.general_context;
    el('generalContextText').hidden = !notes;
    el('generalContextText').textContent = notes ? notes.text || 'No general directions saved for this agent.' : '';
    el('generalContextStatus').textContent = notes ?
      (notes.revision ? 'Saved revision ' + notes.revision : 'No saved directions yet.') : '';
    el('administratorPromptLabel').textContent = item.name + ' · ' + (notes ? 'Agent system prompt' : 'Chat system prompt');
    el('administratorPrompt').textContent = item.system_prompt || 'No additional system prompt saved.';
  }
  function group(label, items) {
    const group = document.createElement('optgroup');
    group.label = label;
    group.append(...items.map(item => new Option(item.name, item.key)));
    return group;
  }
  async function readConfiguration() {
    const preferAgent = active();
    const response = await fetch('/api/admin/config', {cache: 'no-store', signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error('Agent configuration is unavailable. Try again.');
    const data = await response.json();
    const agents = data.agents.map(a => ({...a, key: a.id, agent_id: a.id}));
    const prompts = data.chat_prompts.map(p => ({...p, key: p.scope}));
    targets = [...agents, ...prompts];
    ceoId = data.ceo_id;
    if (!target()) selected = preferAgent ? data.ceo_id : 'administrator';
    selector.replaceChildren(group('Agents', agents), group('Chat prompts', prompts));
    showTarget();
  }
  function refresh() {
    if (!loading) loading = readConfiguration().finally(() => { loading = null; });
    return loading;
  }
  function reload() {
    refresh().catch(error => { el('generalContextStatus').textContent = error.message; });
  }
  function renderWork() {
    const work = window.JarvisTasks.snapshot().tasks.filter(t => !t.parentId && t.work_scope === 'general').slice(0, 16);
    const items = work.map(task => {
      const item = document.createElement('li'), button = document.createElement('button');
      button.type = 'button';
      button.textContent = [task.identifier, task.title, task.status].filter(Boolean).join(' · ');
      button.dataset.generalWorkId = task.id;
      button.onclick = () => window.JarvisModes.openProject(task.id);
      item.append(button);
      return item;
    });
    el('generalKnowledgeList').replaceChildren(...items);
    if (!items.length) el('generalKnowledgeList').textContent = 'No general work yet.';
  }
  function activate() {
    document.body.dataset.generalContext = active() ? 'open' : 'closed';
    if (active()) { renderWork(); reload(); }
  }
  selector.onchange = () => { selected = selector.value; showTarget(); };
  el('generalContextBtn').onclick = () => window.JarvisModes.setGeneralView('context');
  window.addEventListener('jarvis-mode-changed', activate);
  window.addEventListener('jarvis-tasks-updated', () => { if (active()) renderWork(); });
  window.addEventListener('jarvis-general-context-updated', reload);
  window.JarvisGeneralContext = {
    selectedAgentId: () => active() && target()?.scope === 'agent' ? selected : null,
    selectedTarget: async () => {
      const requested = active() ? selected : 'administrator';
      if (!targets.length) await refresh();
      const item = targets.find(t => t.key === (requested || ceoId));
      if (!item) throw new Error('Choose a configuration target in Context.');
      return item;
    },
  };
  activate();
})();
