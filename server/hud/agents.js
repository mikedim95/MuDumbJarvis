/* Select a portrait to answer questions and inspect the agent's work. */
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
  const visible = () => !el('agentsPanel').hidden;
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
  function stateLabel(job) {
    if (job.state === 'closed') return {done:'Done',cancelled:'Cancelled'}[job.status] || 'Closed';
    if (job.state === 'waiting' && job.status === 'in_review') return 'In review';
    return stateNames[job.state] || 'Unknown';
  }
  function missionLink(mission, label) {
    if (!mission?.id || mission.hiddenAt) return entry('span',label);
    const link = action(label,'Open project ' + label,() => window.JarvisModes.openProject(mission.id));
    link.dataset.projectId = mission.id;
    return link;
  }
  function relation(nodes, label, value) {
    const row = entry('div','','agent-relation');
    row.append(entry('span',label,'relation-type'),value);
    nodes.append(row);
  }
  function replyForm(question) {
    if (replyForms.has(question.id)) return replyForms.get(question.id);
    const form = entry('form','','agent-question');
    form.dataset.questionId = question.id;
    const prompt = entry('label',question.question,'agent-question-prompt');
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
    const meta = question.mission?.id === question.task.id
      ? missionLink(question.mission,question.task.identifier)
      : entry('span',question.task.identifier || question.task.title);
    meta.classList.add('agent-question-task');
    form.append(meta,prompt,input,send,error);
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
    const historyOpen = details.dataset.agentId === agent?.id && details.querySelector('details[open]');
    details.hidden = !agent;
    details.replaceChildren();
    if (!agent) { delete details.dataset.agentId; return; }
    details.dataset.agentId = agent.id;
    const schedules = new Map(snapshot.agents.flatMap(a => (a.schedules || []).map(s => [s.id,s])));
    const activity = agent.activity || 'unknown';
    details.dataset.activity = activity;
    const heading = entry('h3',agent.name);
    heading.id = 'agentDetailsHeading';
    heading.tabIndex = -1;
    const questions = agent.questions || [];
    const waitingForReply = reason => questions.length && reason?.startsWith('Waiting for your decision. ');
    const primary = entry('p',agent.status_reason || '', 'agent-reason');
    primary.id = 'agentStatusReason';
    const top = entry('div','','agent-detail-heading');
    top.append(heading,entry('span',stateNames[activity] || activity,'agent-activity'));
    details.append(top);
    if (questions.length) {
      const section = entry('section','','agent-questions');
      const title = entry('h4',questions.length === 1 ? 'Question for you' : 'Questions for you');
      title.id = 'agentQuestionsHeading';
      section.setAttribute('aria-labelledby',title.id);
      section.append(title,...questions.map(replyForm));
      details.append(section);
    }
    if (primary.textContent && !waitingForReply(primary.textContent)) details.append(primary);

    function cronLink(ref) {
      const schedule = schedules.get(ref.id);
      const canOpen = schedule && schedule.assigneeAgentId === snapshot.ceo_id && schedule.status !== 'archived'
        && (schedule.work_scope === 'general' || schedule.mission?.id && !schedule.mission.hiddenAt);
      const name = canOpen
        ? action(ref.title,'Open cron job ' + ref.title,() => window.JarvisCron.openJob(ref.id,schedule.mission?.id))
        : entry('span',ref.title);
      name.dataset.routineId = ref.id;
      return name;
    }
    function jobRow(job) {
      const row = entry('li','','agent-job');
      row.dataset.issueId = job.id;
      row.dataset.state = job.state;
      const title = job.title || job.identifier || 'Untitled job';
      const headline = entry('div','','agent-job-heading');
      const rootJob = job.mission?.id === job.id;
      const name = rootJob ? missionLink(job.mission,title) : entry('span',title);
      headline.append(entry('span',job.identifier || '', 'agent-job-id'),name,entry('span',stateLabel(job),'relation-status'));
      row.append(headline);
      if (job.state !== 'closed' && job.reason && !(waitingForReply(job.reason) && questions.some(q => q.task.id === job.id))) {
        if (primary.isConnected && primary.textContent === job.reason) row.setAttribute('aria-describedby',primary.id);
        else row.append(entry('p',job.reason,'job-reason'));
      }
      if (job.mission && !rootJob) {
        relation(row,'Project',missionLink(job.mission,[job.mission.identifier,job.mission.title].filter(Boolean).join(' · ')));
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
      head.append(cronLink(job),entry('span',job.enabled ? 'Enabled' : job.status === 'paused' ? 'Paused' : 'Disabled','relation-status'));
      row.append(head);
      if (job.mission)
        relation(row,'Project',missionLink(job.mission,[job.mission.identifier,job.mission.title].filter(Boolean).join(' · ')));
      else if (job.work_scope === 'general') relation(row,'Scope',entry('span','General'));
      return row;
    }
    function group(title,rows,makeRow) {
      if (!rows.length) return;
      const section = entry('section','','agent-group'), list = entry('ul');
      list.append(...rows.map(makeRow));
      section.append(entry('h4',title),list);
      details.append(section);
    }
    const rank = {blocked:0,active:1,waiting:2,queued:3};
    group('Assigned work',[...(agent.work || [])].sort((a,b) => rank[a.state] - rank[b.state]),jobRow);
    group('Owned schedules',agent.schedules || [],scheduleRow);
    const past = agent.past_work || [];
    if (past.length) {
      const history = entry('details','','agent-history'), list = entry('ul');
      history.append(entry('summary','Past work (' + past.length + ')'),list);
      history.open = Boolean(historyOpen);
      const populate = () => {
        if (history.open && !list.childElementCount) list.append(...past.map(jobRow));
      };
      populate();
      history.addEventListener('toggle',populate);
      details.append(history);
    }
  }
  function focusKey(node) {
    if (node?.classList.contains('agent-station')) return JSON.stringify(['portrait',node.dataset.agentId]);
    if (!details.contains(node)) return null;
    const question = node.closest('[data-question-id]');
    if (question) return JSON.stringify([question.dataset.questionId,node.tagName,node.type]);
    if (!node.matches('button,summary')) return null;
    const group = node.closest('[data-issue-id],.agent-schedule');
    return JSON.stringify([details.dataset.agentId,group?.dataset.issueId || group?.dataset.routineId,
      node.dataset.projectId || node.dataset.routineId || 'history']);
  }
  function select(id,{focus = false,reveal = false} = {}) {
    if (!snapshot) return;
    const agent = snapshot.agents.find(a => a.id === id);
    selectedId = agent?.id || null;
    const cards = [...map.querySelectorAll('.agent-station')];
    for (const card of cards) card.setAttribute('aria-expanded',String(card.dataset.agentId === selectedId));
    renderDetails(agent);
    if (!agent) return;
    if (focus) {
      const tile = cards.find(card => card.dataset.agentId === id);
      tile?.focus({preventScroll:true});
      tile?.scrollIntoView({block:'nearest',inline:'nearest'});
    }
    if (reveal) {
      const panel = el('agentsPanel'), heading = el('agentDetailsHeading');
      const firstItem = details.querySelector('.agent-question textarea,.agent-reason') || heading;
      const bottom = firstItem.getBoundingClientRect().bottom;
      panel.scrollTop += Math.max(0,bottom - panel.getBoundingClientRect().bottom + 12);
    }
  }
  function portrait(agent) {
    const state = agent.activity || 'unknown', label = stateNames[state] || state;
    const specialization = agent.specialization || agent.title || agent.role || '';
    const card = entry('button','','agent-station');
    card.type = 'button';
    card.dataset.agentId = agent.id;
    card.dataset.activity = state;
    card.setAttribute('aria-controls','agentDetails');
    card.setAttribute('aria-expanded',String(agent.id === selectedId));
    const count = agent.questions?.length || 0;
    const questionLabel = count === 1 ? '1 question for you' : count ? count + ' questions for you' : '';
    card.setAttribute('aria-label',[agent.name,specialization,label,questionLabel].filter(Boolean).join(', '));
    card.onclick = () => select(selectedId === agent.id ? null : agent.id,{reveal:true});
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
    if (count) {
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
        [...map.querySelectorAll('button'),...details.querySelectorAll('button,summary,textarea')]
          .find(n => focusKey(n) === previousFocus)?.focus({preventScroll:true});
      const running = data.agents.filter(agent => agent.activity === 'active').length;
      el('agentsActivitySummary').textContent = data.agents.length + (data.agents.length === 1 ? ' agent' : ' agents') + ' · ' + running + ' running now';
      signature = next;
    }
    if (focusAgent) {
      const id = focusAgent;
      focusAgent = null;
      select(id,{focus:true,reveal:true});
    }
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
    if (visible()) {
      if (snapshot?.agents.some(a => a.id === id)) select(id,{focus:true,reveal:true});
      else focusAgent = id;
    }
  }};
  window.addEventListener('jarvis-mode-changed',activate);
  document.addEventListener('visibilitychange',() => { if (!document.hidden) load(); });
  setInterval(load,8000);
  activate();
})();
