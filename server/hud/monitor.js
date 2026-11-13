/* Monitoring is a view over authenticated Paperclip records. No local scheduler. */
(() => {
  const el = id => document.getElementById(id);
  let task = null, selected = null, acting = false, reviewing = null;
  let savedRetries = [];
  try { savedRetries = JSON.parse(localStorage.getItem('jarvis-retry-nonces') || '[]'); } catch {}
  const retryIds = new Map(Array.isArray(savedRetries) ? savedRetries : []);
  let rendered = null;
  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    node.textContent = value ?? '';
    if (className) node.className = className;
    return node;
  };
  const button = (label, fn) => {
    const node = text('button', label, 'monitor-button');
    node.type = 'button'; node.onclick = fn; return node;
  };
  const card = (title, body) => {
    const node = text('div', '', 'monitor-card');
    node.append(text('div', title), text('pre', body)); return node;
  };
  const json = value => JSON.stringify(value, null, 2);
  const gb = value => typeof value === 'number' ? (value / 1073741824).toFixed(1) + ' GiB' : 'unavailable';
  async function api(path, options = {}) {
    const response = await fetch('/api/' + path, {...options, signal: AbortSignal.timeout(25000)});
    let data;
    try { data = await response.json(); } catch { throw new Error('Invalid monitoring response (' + response.status + ').'); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Monitoring request failed (' + response.status + ').');
    return data;
  }
  const post = (path, body = {}) => api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: json(body)});
  async function action(fn) {
    if (acting) return;
    acting = true;
    try { await fn(); el('taskError').textContent = ''; window.dispatchEvent(new Event('jarvis-monitor-changed')); }
    catch (error) { el('taskError').textContent = error.message; }
    finally { acting = false; }
  }
  function dashboard(data) {
    const counts = data.task_counts;
    el('taskSummary').textContent = `${counts.in_progress} active · ${counts.todo + counts.backlog} queued · ${counts.blocked} blocked · ${counts.in_review} in review · ${counts.done} done`;
    el('employeeList').replaceChildren();
    for (const agent of data.agents) {
      const c = agent.capability || {};
      const active = data.live_runs.filter(r => r.agentId === agent.id);
      const node = card(agent.name + ' · ' + (agent.title || agent.role), [
        'ID: ' + agent.id, 'Reports to: ' + (agent.reportsTo || 'company board'),
        'Availability: ' + agent.status + ' / ' + agent.lifecycleState + (active.length ? ' · native runs: ' + active.length : ' · no live execution'),
        agent.lifecycleError || '', 'Profile: ' + (c.profile || agent.role), 'Model: ' + (c.model || 'local CEO runtime'),
        'Tools: ' + (c.tools || []).join(', '), 'Limits: ' + json(c.limits), c.authority || '', c.workspace || '',
        c.dormancy || 'No scheduled employee inference while idle'
      ].filter(Boolean).join('\n'));
      el('employeeList').append(node);
    }
    const m = data.inference, host = data.resources;
    el('inferenceStatus').replaceChildren(text('div', `${m.provider} · ${m.available ? 'connected' : m.error} · ${m.configured_cpu_threads} CPU threads · ${m.inference_slots} shared inference slot`),
      text('div', `CPU busy: ${host.cpu_busy_percent ?? 'sampling'}% · load: ${(host.load_average || []).map(v => v.toFixed(2)).join(' / ')} · RAM available: ${gb(host.memory_available_bytes)} / ${gb(host.memory_total_bytes)}`),
      text('div', host.scope, 'monitor-muted'));
    for (const model of m.loaded_models || []) el('inferenceStatus').append(text('div', `${model.name} · ${gb(model.size)} loaded · context ${model.context_length ?? 'unavailable'}`));
    if (m.available && !(m.loaded_models || []).length) el('inferenceStatus').append(text('div', 'No model is currently resident; inference loads on demand.', 'monitor-muted'));
    for (const run of data.live_runs) el('inferenceStatus').append(text('div', `${run.status} · ${run.agentName || run.agentId} · ${run.issueId} · run ${run.id}`, 'monitor-muted'));
    const pending = data.approvals.filter(a => ['pending', 'revision_requested'].includes(a.status));
    el('approvalCount').textContent = '(' + pending.length + ' pending)';
    el('approvalList').replaceChildren();
    if (!data.approvals.length) el('approvalList').append(text('div', 'No approval requests for this project.', 'monitor-muted'));
    for (const a of data.approvals) {
      const node = card((a.proposal.name || a.proposal.title || a.type) + ' · ' + a.status,
        'Approval ID: ' + a.id + '\nTasks: ' + a.issue_ids.join(', ') + '\n' + (a.hiring_reason || a.proposal.summary || a.decisionNote || ''));
      if (['pending', 'revision_requested'].includes(a.status)) node.append(button('Review request', () => review(a)));
      el('approvalList').append(node);
    }
    if (reviewing && !pending.some(a => a.id === reviewing)) { el('approvalReview').hidden = true; reviewing = null; }
  }
  function review(a) {
    const node = el('approvalReview'); node.replaceChildren(); node.hidden = false; reviewing = a.id;
    node.append(text('div', 'HUMAN DECISION · ' + a.type), text('pre', json({approval_id: a.id, employee: a.proposal, capability: a.capability, reason: a.hiring_reason, tasks: a.issue_ids})),
      text('div', a.type === 'hire_agent' ? 'Approval authorizes only this scoped employee profile. Provisioning is performed by the operator runtime service.' :
        'Approval records a decision. Sensitive host or external actions still require operator execution; no host tool access is granted.', 'monitor-muted'));
    const note = document.createElement('textarea'); note.setAttribute('aria-label', 'Approval decision note'); note.placeholder = 'Reason for approval or rejection'; node.append(note);
    const row = text('div', '', 'monitor-row');
    for (const decision of ['approve', 'reject']) row.append(button(decision === 'approve' ? 'Approve request' : 'Reject request', () => action(async () => {
      if (!note.value.trim()) throw new Error('Enter a decision note before approving or rejecting.');
      await post('approvals/' + a.id + '/decision', {decision, note: note.value.trim()}); node.hidden = true; reviewing = null;
    })));
    row.append(button('Close review', () => { node.hidden = true; reviewing = null; })); node.append(row);
  }
  function controls(current, monitor) {
    el('taskActions').replaceChildren();
    if (!['done', 'cancelled'].includes(current.status)) el('taskActions').append(button('Cancel task tree', () => action(async () => {
      const preview = await post('tasks/' + current.id + '/cancel-preview');
      const n = preview.totals.affectedIssues;
      if (!n) throw new Error('No active tasks in this tree can be cancelled.');
      if (!window.confirm(`Cancel ${n} task(s), including their active or queued executions? Completed history remains available.`)) return;
      await post('tasks/' + current.id + '/cancel', {reason: 'Human cancelled this task tree through the authenticated JARVIS HUD.'});
    })));
    if (monitor.interruption?.canRetry || current.status === 'blocked') el('taskActions').append(button('Retry same task', () => action(async () => {
      const observed = monitor.interruption?.observedRunId ?? current.runs?.[0]?.runId ?? null;
      const key = current.id + ':' + observed;
      if (!retryIds.has(key)) {
        retryIds.set(key, crypto.randomUUID());
        localStorage.setItem('jarvis-retry-nonces', json([...retryIds].slice(-20)));
      }
      const result = await post('tasks/' + current.id + '/retry', {request_id: retryIds.get(key), observed_run_id: observed});
      el('runLog').textContent = json(result);
    })));
  }
  async function show(current) {
    task = current; selected = current.id;
    const target = current.id;
    const m = await api('tasks/' + target + '/monitor');
    if (selected !== target) return;
    const key = json({id: target, status: current.status, runs: current.runs, monitor: m});
    if (key === rendered) return;
    rendered = key;
    controls(current, m);
    el('taskPlan').textContent = [m.plans.map(p => p.body).join('\n\n'),
      m.plan_document ? 'Native plan document:\n' + json(m.plan_document) : '',
      'Waiting on: ' + (m.blockedBy.map(i => `${i.identifier || i.id} · ${i.status}`).join(', ') || 'no dependencies'),
      'Unblocks: ' + (m.blocks.map(i => `${i.identifier || i.id} · ${i.status}`).join(', ') || 'none'),
      m.execution_blocker ? 'Execution blocker:\n' + json(m.execution_blocker) : '',
      m.recovery ? 'Recovery action:\n' + json(m.recovery) : ''
    ].filter(Boolean).join('\n\n');
    el('toolEvidence').replaceChildren();
    const seen = new Set();
    for (const proof of [...m.evidence].reverse()) {
      for (const event of proof.tools || []) {
        const key = proof.run_id + ':' + (event.tool_call_id || event.tool);
        if (seen.has(key)) continue;
        seen.add(key);
        const detail = document.createElement('details');
        detail.append(text('summary', `${proof.verified ? 'VERIFIED RUNTIME' : 'UNVERIFIED'} · ${event.tool} · ${event.success ? 'success' : 'failed / denied'}`, proof.verified ? 'evidence-ok' : 'evidence-unverified'),
          text('pre', json({task_id: target, execution_id: proof.run_id, execution_status: proof.run_status, tool_call_id: event.tool_call_id,
            source: proof.verification, arguments: event.args, result: event.result, result_sha256: event.result_sha256})));
        el('toolEvidence').append(detail);
      }
    }
    if (!seen.size) el('toolEvidence').append(text('div', 'No verifiable runtime tool receipts recorded. Model prose alone is not execution evidence.', 'monitor-muted'));
    el('artifactList').replaceChildren();
    for (const a of m.artifacts) {
      const node = card(a.originalFilename + ' · ' + a.byteSize + ' bytes',
        `Artifact: ${a.id}\nExecution: ${a.originatingRunId || 'unrecorded'}\nAuthor: ${a.createdByAgentId || 'human'}\nSHA-256: ${a.sha256}`);
      const link = text('a', 'Download verified bytes', 'monitor-button');
      link.href = '/api/tasks/' + target + '/artifacts/' + a.id; link.setAttribute('download', a.originalFilename);
      node.append(link); el('artifactList').append(node);
    }
    if (!m.artifacts.length) el('artifactList').append(text('div', 'No native artifacts recorded.', 'monitor-muted'));
    el('runList').replaceChildren();
    for (const run of current.runs || []) {
      const node = card(run.status + ' · ' + run.runId, [run.startedAt, run.errorCode, run.error].filter(Boolean).join('\n'));
      node.append(button('Read execution log', () => action(async () => {
        const log = await api('tasks/' + target + '/runs/' + run.runId + '/log');
        el('runLog').textContent = `Execution ${run.runId}\n` + log.content;
        if (log.next_offset) el('runLog').append(text('div', 'First 32 KiB shown. Complete log remains available in Paperclip.'));
      }))); el('runList').append(node);
    }
  }
  window.JarvisMonitor = {dashboard, show, clear: () => { selected = null; rendered = null; }};
})();
