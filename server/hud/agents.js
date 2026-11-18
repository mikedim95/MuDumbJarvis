/* Reporting lines, assignments and schedules from the current Paperclip roster. */
(() => {
  if (!document.body.classList.contains('ai-minimal')) return;
  const el = id => document.getElementById(id);
  const map = el('agentsMap');
  let request = null, signature = '', focusAgent = null;
  const visible = () => !el('agentsPanel').hidden;
  const entry = (tag, value = '', className = '') => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  function action(label, accessibleName, handle) {
    const button = entry('button', label, 'relation-link');
    button.type = 'button';
    button.setAttribute('aria-label', accessibleName);
    button.onclick = handle;
    return button;
  }
  function activity(agent) {
    const work = agent.work || [];
    if (work.some(job => job.state === 'active') || agent.status === 'running') return ['active', 'Running'];
    if (['paused','terminated','error','pending_approval'].includes(agent.status)) {
      const label = agent.status.replaceAll('_',' ');
      return ['unavailable', label[0].toUpperCase() + label.slice(1)];
    }
    if (work.some(job => job.state === 'queued')) return ['queued', 'Queued'];
    if (work.some(job => job.state === 'waiting')) return ['waiting', 'Waiting'];
    return ['idle', 'Idle'];
  }
  function stateLabel(job) {
    if (job.state === 'active') return 'Running';
    if (job.state === 'queued') return 'Queued';
    return {blocked:'Blocked',in_review:'In review',done:'Done',cancelled:'Cancelled',
      backlog:'Backlog'}[job.status] || (job.state === 'closed' ? 'Closed' : 'Waiting');
  }
  function focusStation() {
    if (!focusAgent || !visible()) return;
    const station = [...map.querySelectorAll('.agent-station')].find(card => card.dataset.agentId === focusAgent);
    if (station) {
      station.focus({preventScroll:true});
      station.scrollIntoView({block:'nearest'});
      focusAgent = null;
    }
  }
  function focusKey(node) {
    const station = node?.closest('.agent-station');
    if (!station) return null;
    if (node === station) return station.dataset.agentId;
    const group = node.closest('[data-issue-id],.agent-schedule');
    return [station.dataset.agentId,group?.dataset.issueId || group?.dataset.routineId || '',
      node.dataset.projectId || node.dataset.routineId || 'history'].join('/');
  }
  function render(data) {
    const next = JSON.stringify(data);
    if (signature === next) { focusStation(); return; }
    const agents = data.agents || [];
    const byId = new Map(agents.map(a => [a.id, a]));
    const schedules = new Map(agents.flatMap(a => (a.schedules || []).map(s => [s.id, s])));
    const expanded = new Set([...map.querySelectorAll('details[open]')].map(node => node.dataset.group));
    const previousFocus = focusKey(document.activeElement);
    const seen = new Set();

    function missionLink(mission, label) {
      if (!mission?.id || mission.hiddenAt) return entry('span', label);
      const button = action(label, 'Open project ' + label, () => window.JarvisModes.openProject(mission.id));
      button.dataset.projectId = mission.id;
      return button;
    }
    function cronLink(ref) {
      const schedule = schedules.get(ref.id);
      const canOpen = schedule && schedule.assigneeAgentId === data.ceo_id && schedule.status !== 'archived'
        && (schedule.work_scope === 'general' || schedule.mission?.id && !schedule.mission.hiddenAt);
      const node = canOpen
        ? action(ref.title, 'Open cron job ' + ref.title, () => window.JarvisCron.openJob(ref.id, schedule.mission?.id))
        : entry('span', ref.title);
      node.dataset.routineId = ref.id;
      return node;
    }
    function relation(nodes, label, value) {
      const row = entry('div','','agent-relation');
      row.append(entry('span',label,'relation-type'), value);
      nodes.append(row);
    }
    function jobRow(job) {
      const row = entry('li','','agent-job');
      row.dataset.issueId = job.id;
      row.dataset.state = job.state;
      const title = job.title || job.identifier || 'Untitled job';
      const heading = entry('div','','agent-job-heading');
      const rootJob = job.mission?.id === job.id;
      const name = rootJob ? missionLink(job.mission, title) : entry('span', title);
      heading.append(entry('span',job.identifier || '', 'agent-job-id'), name, entry('span',stateLabel(job),'relation-status'));
      row.append(heading);
      if (job.mission && !rootJob) {
        const label = [job.mission.identifier, job.mission.title].filter(Boolean).join(' · ');
        relation(row,'Project',missionLink(job.mission,label));
      } else if (job.work_scope === 'general') {
        relation(row,'Scope',entry('span','General'));
      }
      if (job.cron_job) relation(row,'Cron job',cronLink(job.cron_job));
      if (job.run_issue?.identifier && job.run_issue.id !== job.id)
        relation(row,'Run',entry('span',job.run_issue.identifier));
      return row;
    }
    function scheduleRow(job) {
      const row = entry('li','','agent-schedule');
      row.dataset.routineId = job.id;
      row.dataset.enabled = String(Boolean(job.enabled));
      const head = entry('div','','agent-job-heading');
      head.append(cronLink(job),entry('span', job.enabled ? 'Enabled' : job.status === 'paused' ? 'Paused' : 'Disabled', 'relation-status'));
      row.append(head);
      if (job.mission) {
        const label = [job.mission.identifier,job.mission.title].filter(Boolean).join(' · ');
        relation(row,'Project',missionLink(job.mission,label));
      } else if (job.work_scope === 'general') {
        relation(row,'Scope',entry('span','General'));
      }
      return row;
    }
    function station(agent) {
      seen.add(agent.id);
      const item = entry('li','','agent-branch');
      const card = entry('article','','agent-station');
      card.tabIndex = -1;
      card.dataset.agentId = agent.id;
      const [state,label] = activity(agent);
      card.dataset.activity = state;
      card.setAttribute('aria-label', agent.name);
      const identity = entry('div','','agent-identity');
      const symbol = entry('span','','agent-symbol');
      symbol.setAttribute('aria-hidden','true');
      const name = entry('div','','agent-name');
      name.append(entry('h3',agent.name));
      const role = agent.title || agent.role;
      if (role) name.append(entry('p',role));
      identity.append(symbol,name,entry('span',label,'agent-activity'));
      card.append(identity);
      const work = [...(agent.work || [])];
      const rank = {active:0,queued:1,waiting:2};
      work.sort((a,b) => rank[a.state] - rank[b.state]);
      const jobs = agent.schedules || [], past = agent.past_work || [];
      const links = entry('div','','agent-links');
      function group(title, rows, makeRow) {
        if (!rows.length) return;
        const section = entry('section','','agent-group');
        const list = entry('ul');
        list.append(...rows.map(makeRow));
        section.append(entry('h4',title),list);
        links.append(section);
      }
      group('Assigned work',work,jobRow);
      group('Owned schedules',jobs,scheduleRow);
      if (past.length) {
        const details = entry('details','','agent-history');
        details.dataset.group = agent.id;
        const summary = entry('summary','Past work (' + past.length + ')');
        const list = entry('ul');
        const populate = () => {
          if (details.open && !list.childElementCount) list.append(...past.map(jobRow));
        };
        details.append(summary,list);
        details.open = expanded.has(agent.id);
        populate();
        details.addEventListener('toggle',populate);
        links.append(details);
      }
      if (links.childElementCount) card.append(links);
      item.append(card);
      const reports = agents.filter(a => a.reportsTo === agent.id && !seen.has(a.id));
      if (reports.length) {
        const children = entry('ul','','agent-reports');
        children.setAttribute('aria-label','Reports to ' + agent.name);
        for (const report of reports) if (!seen.has(report.id)) children.append(station(report));
        item.append(children);
      }
      return item;
    }

    const roots = agents.filter(a => a.id === data.ceo_id || !byId.has(a.reportsTo));
    const tree = document.createDocumentFragment();
    for (const agent of [...roots,...agents]) if (!seen.has(agent.id)) tree.append(station(agent));
    map.replaceChildren(tree);
    // Polling preserves the user's keyboard position even when other work changes.
    if (previousFocus) {
      [...map.querySelectorAll('.agent-station,button,summary')].find(n => focusKey(n) === previousFocus)?.focus({preventScroll:true});
    }
    const running = agents.filter(a => activity(a)[0] === 'active').length;
    el('agentsActivitySummary').textContent = agents.length + (agents.length === 1 ? ' agent' : ' agents') + ' · ' + running + ' running now';
    if (!agents.length) el('agentsNotice').textContent = 'No agents are registered.';
    signature = next;
    focusStation();
  }
  async function load() {
    if (!visible() || document.hidden || request) return;
    const controller = new AbortController();
    request = controller;
    if (!signature) el('agentsNotice').textContent = 'Loading agents…';
    try {
      const response = await fetch('/api/agents/work',{cache:'no-store',
        signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
      if (!response.ok) throw new Error('Could not load agent activity.');
      const data = await response.json();
      if (controller.signal.aborted || !visible()) return;
      el('agentsNotice').textContent = data.agents?.length ? '' : 'No agents are registered.';
      render(data);
    } catch {
      if (!controller.signal.aborted && visible())
        el('agentsNotice').textContent = signature ? 'Connection interrupted. Showing the last update.' : 'Could not load agent activity. Retrying…';
    } finally {
      if (request === controller) request = null;
    }
  }
  function activate() {
    if (visible()) { load(); return; }
    request?.abort(); request = null; focusAgent = null;
  }
  window.JarvisAgents = {open(id) {
    window.JarvisModes.setGeneralView('agents');
    if (visible()) { focusAgent = id; focusStation(); }
  }};
  window.addEventListener('jarvis-mode-changed',activate);
  document.addEventListener('visibilitychange',() => { if (!document.hidden) load(); });
  setInterval(load,8000);
  activate();
})();
