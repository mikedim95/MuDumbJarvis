/* Opt-in LIVE CEO acceptance. Real HUD submissions, Paperclip state, Hermes
   audits and local Ollama data are required. No mocks or alternate scheduler. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const root = '/workspace';
const out = root + '/docs/evidence';
const url = 'http://localhost:8765';
const paperclip = 'http://localhost:3100/api';
const stageFile = root + '/.runtime/ceo-browser-stage.json';
const evidenceFile = out + '/ceo-browser.json';
const prompts = [
  'Inspect the local Ollama installation, identify installed models, and produce a technical inventory report.',
  'Use two distinct roles for this objective: delegate read-only local Ollama data collection to the existing JARVIS-01 operator, then act as the CEO to independently review the completed worker execution evidence and consolidate a technical inventory report. Record a clear scoped Paperclip child task with acceptance criteria, reuse the existing employee, and do not request or create any hires. The worker must use local_ollama_models to retrieve actual model names and sizes. Wait for Paperclip to wake you after the child completes, review the succeeded run and signed tool evidence, then report verified findings and unresolved limits.'
];
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const now = () => new Date().toISOString();
const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const canonical = value => Array.isArray(value) ? value.map(canonical) :
  value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const freshDelegation = process.argv.includes('--fresh-delegation');
const resume = process.argv.includes('--resume') || freshDelegation;
const stage = {status: 'starting', started_at: now(), submitted: [], progress: [], browser_errors: []};
function writeStage(update = {}) {
  Object.assign(stage, update, {updated_at: now()});
  fs.writeFileSync(stageFile + '.tmp', JSON.stringify(stage, null, 2));
  fs.renameSync(stageFile + '.tmp', stageFile);
}
function rows(file) {
  if (!fs.existsSync(file)) return [];
  return fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).flatMap(line => {
    try { return [JSON.parse(line)]; } catch { return []; }
  });
}
async function board(path) {
  const response = await fetch(paperclip + path, {headers: {Authorization: 'Bearer ' + process.env.PAPERCLIP_API_KEY},
    signal: AbortSignal.timeout(25000)});
  assert.equal(response.status, 200, 'Canonical Paperclip read failed: ' + path + ' HTTP ' + response.status);
  return response.json();
}
async function hud(page, path) {
  const response = await page.request.get(url + '/api/' + path, {timeout: 30000});
  assert.equal(response.status(), 200, 'Authenticated HUD read failed: ' + path);
  return response.json();
}
async function selectTask(page, task) {
  await page.locator('#taskHistory button').filter({hasText: new RegExp('^' + task.identifier + ' ·')}).click();
  await page.waitForFunction(identifier => document.getElementById('taskDetail').textContent.startsWith(identifier + ' ·'), task.identifier);
}
function runtimeLines(directory, issueId) {
  return fs.readFileSync(directory + '/logs/agent.log', 'utf8').split('\n').filter(line =>
    line.includes('issue:' + issueId) && (line.includes('conversation turn:') || line.includes('tool local_ollama_models completed')));
}
function assertLocalRuntime(lines) {
  assert(lines.some(line => line.includes('model=jarvis-hermes:3b provider=custom')), 'Missing issue-correlated local model execution');
}
function assertVisibleInventory(text, models) {
  assert(models.length > 0, 'No actual model inventory was retrieved');
  for (const model of models) {
    assert(text.includes(model.name), 'HUD missing retrieved model name: ' + model.name);
    assert(text.includes(String(model.size_bytes)), 'HUD missing retrieved exact byte size: ' + model.name);
  }
}
function nativeChildCompletion(run, taskId, childId, ceoId, workerId) {
  const summaries = run.childIssueSummaries;
  return run.status === 'succeeded' && run.agentId === ceoId &&
    run.wakeReason === 'issue_children_completed' && run.contextSource === 'issue.children_completed' &&
    run.issueId === taskId && Array.isArray(run.childIssueIds) && run.childIssueIds.length === 1 &&
    run.childIssueIds[0] === childId && Array.isArray(summaries) && summaries.length === 1 &&
    summaries[0].id === childId && summaries[0].status === 'done' && summaries[0].assigneeAgentId === workerId &&
    (run.completedChildIssueId === undefined || run.completedChildIssueId === childId);
}
function assertTechnicalReport(data, ceoId, models) {
  const reports = data.comments.filter(comment => comment.authorAgentId === ceoId &&
    (comment.body.includes('Verified local_ollama_models data') || comment.body.includes('Verified delegated execution data')))
    .sort((a, b) => (a.createdAt || '').localeCompare(b.createdAt || ''));
  assert(reports.length, 'No CEO final report with verified execution data was recorded');
  const prose = reports.at(-1).body.split(/\n\nVerified (?:local_ollama_models data|delegated execution data)/)[0].trim();
  const normalizedProse = prose.replace(/^[\s#*_>\-]+/, '');
  assert(!/^(?:\[[^\]]+\]\s*)?(?:waiting\b|please wait\b|pending\b|I(?:'m| am) waiting\b)/i.test(normalizedProse),
    'CEO final prose is a waiting update, not the completed technical report');
  assert(prose.length >= 100, 'CEO final technical report is missing substantive prose');
  const namesInReport = models.filter(model => prose.includes(model.name));
  assert(namesInReport.length >= Math.min(2, models.length),
    'CEO report must discuss retrieved model names before the appended raw evidence');
  const sizesInReport = namesInReport.filter(model => prose.includes(String(model.size_bytes)) ||
    (model.size_gib != null && prose.includes(String(model.size_gib))));
  assert(sizesInReport.length >= Math.min(2, models.length),
    'CEO report must present actual retrieved model sizes before the appended raw evidence');
  return prose;
}
function authenticatedProof(proof) {
  assert.equal(proof.version, 2);
  const unsigned = Object.fromEntries(Object.entries(proof).filter(([key]) => key !== 'signature'));
  const expected = crypto.createHmac('sha256', process.env.JARVIS_EXECUTION_PROOF_KEY)
    .update(JSON.stringify(canonical(unsigned))).digest('hex');
  assert.equal(proof.signature, expected, 'Worker evidence signature is invalid');
}
function workerProof(child, workerId) {
  const candidates = child.comments.filter(comment => comment.authorAgentId === workerId)
    .flatMap(comment => comment.body.split('\n')).filter(line => line.startsWith('JARVIS_EXECUTION_EVIDENCE='))
    .flatMap(line => { try { return [JSON.parse(line.split('=').slice(1).join('='))]; } catch { return []; } });
  const proof = candidates.at(-1);
  assert(proof, 'No actual signed worker execution evidence');
  authenticatedProof(proof);
  assert.equal(proof.agent_id, workerId);
  if (proof.issue_id !== undefined) assert.equal(proof.issue_id, child.id);
  assert.equal(proof.tool, 'local_ollama_models');
  assert.equal(proof.session_id, 'paperclip:company:' + process.env.PAPERCLIP_COMPANY_ID +
    ':agent:' + workerId + ':issue:' + child.id);
  assert(child.runs.some(run => run.runId === proof.paperclip_run_id && run.status === 'succeeded'));
  return proof;
}
async function verifyTask(page, task, index, ceoId, workerId) {
  await selectTask(page, task);
  const data = await hud(page, 'tasks/' + task.id);
  assert.equal(data.status, 'done');
  assert.equal(data.assigneeAgentId, ceoId);
  assert(data.runs.some(run => run.status === 'succeeded'));
  const canonicalIssue = await board('/issues/' + task.id);
  assert.equal(canonicalIssue.id, data.id);
  assert.equal(canonicalIssue.status, data.status);
  await page.waitForFunction(({identifier, id}) => {
    const text = document.getElementById('taskDetail').textContent;
    return text.startsWith(identifier + ' · done') && text.includes(id);
  }, task);
  const text = await page.locator('#taskDetail').innerText();
  const plans = data.comments.filter(comment => comment.authorAgentId === ceoId &&
    comment.body.startsWith('[JARVIS CEO PLAN decision='));
  const ceoLog = runtimeLines(root + '/.runtime/hermes-ceo', task.id);
  assertLocalRuntime(ceoLog);
  const actions = rows(root + '/.runtime/hermes-ceo/logs/ceo-tools.jsonl').filter(row => row.issue_id === task.id);
  const succeededContextRunIds = new Set(data.runs.filter(run => run.status === 'succeeded').map(run => run.runId));
  const contextTool = actions.find(row => row.action === 'context' && succeededContextRunIds.has(row.paperclip_run_id));
  let contextDeliveryEvent;
  if (!contextTool) {
    const expectedSession = 'paperclip:company:' + process.env.PAPERCLIP_COMPANY_ID +
      ':agent:' + ceoId + ':issue:' + task.id;
    contextDeliveryEvent = rows(root + '/.runtime/hermes-ceo/logs/ceo-preflight.jsonl').findLast(row =>
      row.source === 'hermes_pre_llm_call' && row.issue_id === task.id && row.session_id === expectedSession &&
      /^[0-9a-f]{64}$/.test(row.context_sha256 || '') && succeededContextRunIds.has(row.paperclip_run_id) &&
      ((row.action === 'objective_state_delivered' && row.context_delivered_for_review === false &&
        Array.isArray(row.verified) && row.verified.length === 0 &&
        Array.isArray(row.delivered_child_ids) && row.delivered_child_ids.length === 0) ||
       (row.action === 'verified_child_results_delivered' && row.context_delivered_for_review === true &&
        Array.isArray(row.verified) && row.verified.length > 0 &&
        Array.isArray(row.delivered_child_ids) && row.delivered_child_ids.length > 0)));
    assert(contextDeliveryEvent,
      'A succeeded CEO run must receive actual objective context through the context tool or supported pre_llm_call delivery');
    const contextRun = await board('/heartbeat-runs/' + contextDeliveryEvent.paperclip_run_id);
    assert(contextRun.status === 'succeeded' && contextRun.agentId === ceoId);
    assert.equal(contextRun.contextSnapshot?.issueId, task.id);
  }
  let toolAudit, proof, delegateRunId, reviewRunId, consolidationRunId, deliveryEvent,
    receptionConsolidationMethod, canonicalWorkerRun, childLog = [], runDetails = [];
  if (index === 0) {
    assert(plans.some(comment => comment.body.startsWith('[JARVIS CEO PLAN decision=self]')));
    assert.equal(data.children.length, 0, 'Simple inventory unnecessarily delegated work');
    toolAudit = rows(root + '/.runtime/hermes-ceo/logs/paperclip-tools.jsonl')
      .findLast(row => row.issue_id === task.id && row.tool === 'local_ollama_models' &&
        data.runs.some(run => run.runId === row.paperclip_run_id && run.status === 'succeeded'));
    assert(toolAudit && toolAudit.result.source === 'Ollama /api/tags');
    assert(data.runs.some(run => run.runId === toolAudit.paperclip_run_id && run.status === 'succeeded'));
    assertVisibleInventory(text, toolAudit.result.models);
  } else {
    assert(plans.some(comment => comment.body.startsWith('[JARVIS CEO PLAN decision=delegate]')));
    assert.equal(data.children.length, 1, 'Delegation must reuse exactly one existing worker');
    const child = data.children[0];
    assert.equal(child.parentId, task.id);
    assert.equal(child.assigneeAgentId, workerId);
    assert.equal(child.status, 'done');
    proof = workerProof(child, workerId);
    // The issue-runs endpoint also returns related manager runs. Only actual
    // assignee executions determine the latest worker evidence accepted here.
    const childRuns = await board('/issues/' + child.id + '/runs');
    const workerRuns = childRuns.filter(run => run.agentId === workerId).sort((a, b) =>
      (b.startedAt || b.createdAt || '').localeCompare(a.startedAt || a.createdAt || ''));
    assert(workerRuns.length, 'Canonical child execution has no worker actor metadata');
    assert.equal(workerRuns[0].runId, proof.paperclip_run_id,
      'Signed evidence must belong to the latest actual worker execution');
    assert.equal(workerRuns[0].status, 'succeeded');
    const rawWorkerRun = await board('/heartbeat-runs/' + proof.paperclip_run_id);
    canonicalWorkerRun = {id: rawWorkerRun.id, companyId: rawWorkerRun.companyId,
      agentId: rawWorkerRun.agentId, status: rawWorkerRun.status,
      issueId: rawWorkerRun.contextSnapshot?.issueId};
    assert.equal(canonicalWorkerRun.id, proof.paperclip_run_id);
    assert.equal(canonicalWorkerRun.companyId, process.env.PAPERCLIP_COMPANY_ID);
    assert.equal(canonicalWorkerRun.agentId, workerId);
    assert.equal(canonicalWorkerRun.issueId, child.id);
    assert.equal(canonicalWorkerRun.status, 'succeeded');
    toolAudit = rows(root + '/.runtime/hermes/logs/paperclip-tools.jsonl')
      .find(row => row.issue_id === child.id && row.paperclip_run_id === proof.paperclip_run_id &&
        row.tool === 'local_ollama_models');
    assert(toolAudit && toolAudit.result.source === 'Ollama /api/tags');
    assert.equal(proof.models.length, toolAudit.result.models.length);
    for (const model of proof.models) {
      assert(toolAudit.result.models.some(actual => actual.name === model.name && actual.size_bytes === model.size_bytes),
        'Signed worker inventory differs from the actual tool audit: ' + model.name);
    }
    const successful = data.runs.filter(run => run.status === 'succeeded');
    const succeededIds = new Set(successful.map(run => run.runId));
    const rawRuns = await Promise.all(successful.map(run => board('/heartbeat-runs/' + run.runId)));
    runDetails = rawRuns.map(run => ({id: run.id, status: run.status, agentId: run.agentId,
      invocationSource: run.invocationSource, triggerDetail: run.triggerDetail,
      wakeReason: run.contextSnapshot?.wakeReason, contextSource: run.contextSnapshot?.source,
      issueId: run.contextSnapshot?.issueId,
      childIssueIds: run.contextSnapshot?.childIssueIds,
      childIssueSummaries: run.contextSnapshot?.paperclipWake?.childIssueSummaries?.map(summary => ({
        id: summary.id, status: summary.status, assigneeAgentId: summary.assigneeAgentId})),
      completedChildIssueId: run.contextSnapshot?.completedChildIssueId}));
    const nativeConsolidationIds = new Set(runDetails.filter(run =>
      nativeChildCompletion(run, task.id, child.id, ceoId, workerId)).map(run => run.id));
    const delegation = actions.find(row => row.action === 'delegate' && row.result.child_id === child.id &&
      succeededIds.has(row.paperclip_run_id));
    assert(delegation, 'The actual delegate action must belong to a succeeded CEO run');
    const review = actions.find(row => row.action === 'review' &&
      nativeConsolidationIds.has(row.paperclip_run_id) && row.paperclip_run_id !== delegation.paperclip_run_id &&
      row.result.reviewed?.some(item => item.issue_id === child.id && item.evidence.signature === proof.signature));
    delegateRunId = delegation.paperclip_run_id;
    if (review) {
      reviewRunId = review.paperclip_run_id;
      consolidationRunId = reviewRunId;
      receptionConsolidationMethod = 'explicit_review_tool';
      assert(data.comments.some(comment => comment.authorAgentId === ceoId && comment.body.startsWith('[JARVIS CEO REVIEW]')));
    } else {
      const expectedSession = 'paperclip:company:' + process.env.PAPERCLIP_COMPANY_ID +
        ':agent:' + ceoId + ':issue:' + task.id;
      deliveryEvent = rows(root + '/.runtime/hermes-ceo/logs/ceo-preflight.jsonl').findLast(row =>
        row.source === 'hermes_pre_llm_call' && row.action === 'verified_child_results_delivered' &&
        row.issue_id === task.id && row.session_id === expectedSession &&
        row.context_delivered_for_review === true && /^[0-9a-f]{64}$/.test(row.context_sha256 || '') &&
        nativeConsolidationIds.has(row.paperclip_run_id) && row.paperclip_run_id !== delegateRunId &&
        Array.isArray(row.delivered_child_ids) && row.delivered_child_ids.length === 1 &&
        row.delivered_child_ids[0] === child.id && Array.isArray(row.verified) && row.verified.length === 1 &&
        row.verified[0].issue_id === child.id && row.verified[0].identifier === child.identifier &&
        row.verified[0].evidence?.signature === proof.signature);
      assert(deliveryEvent,
        'A distinct succeeded CEO run must receive authenticated child results through the actual review tool or supported pre_llm_call context delivery');
      authenticatedProof(deliveryEvent.verified[0].evidence);
      assert.equal(hash(canonical(deliveryEvent.verified[0].evidence)), hash(canonical(proof)),
        'Delivered child evidence must exactly match the authenticated worker proof');
      assert(data.comments.some(comment => comment.authorAgentId === ceoId &&
        comment.body.startsWith('[JARVIS CEO RESULTS READY]')),
        'Verified preflight delivery must be recorded honestly as results supplied for review');
      consolidationRunId = deliveryEvent.paperclip_run_id;
      receptionConsolidationMethod = 'pre_llm_context_delivery';
    }
    assert.notEqual(delegateRunId, consolidationRunId);
    assert(succeededIds.size >= 2, 'Missing separate delegation and consolidation CEO runs');
    const canonicalDelegate = runDetails.find(run => run.id === delegateRunId);
    assert(canonicalDelegate && canonicalDelegate.status === 'succeeded' && canonicalDelegate.agentId === ceoId);
    assert.equal(canonicalDelegate.issueId, task.id);
    const canonicalConsolidation = runDetails.find(run => run.id === consolidationRunId);
    assert(canonicalConsolidation && canonicalConsolidation.status === 'succeeded' && canonicalConsolidation.agentId === ceoId);
    assert.equal(canonicalConsolidation.wakeReason, 'issue_children_completed',
      'The exact succeeded consolidation run must be a native child-completion wake');
    assert.equal(canonicalConsolidation.issueId, task.id);
    assert.equal(canonicalConsolidation.contextSource, 'issue.children_completed');
    assert.deepEqual(canonicalConsolidation.childIssueIds, [child.id]);
    assert.deepEqual(canonicalConsolidation.childIssueSummaries, [
      {id: child.id, status: 'done', assigneeAgentId: workerId}]);
    // Some Paperclip builds include a legacy singular field. The installed
    // release records the authoritative IDs and completed summaries as arrays.
    if (canonicalConsolidation.completedChildIssueId !== undefined) {
      assert.equal(canonicalConsolidation.completedChildIssueId, child.id);
    }
    childLog = runtimeLines(root + '/.runtime/hermes', child.id);
    assertLocalRuntime(childLog);
    assert(text.includes('DELEGATED WORK (1)') && text.includes(child.identifier + ' · done'));
    assert(text.includes('JARVIS-01') && text.includes('succeeded'));
    assertVisibleInventory(text, proof.models);
    const canonicalChild = await board('/issues/' + child.id);
    assert.equal(canonicalChild.parentId, task.id);
    assert.equal(canonicalChild.status, child.status);
  }
  const finalProse = assertTechnicalReport(data, ceoId, proof?.models || toolAudit.result.models);
  assert(!actions.some(row => row.action === 'request_hire'), 'An unnecessary employee was requested');
  const currentModels = await (await fetch('http://localhost:11434/api/tags', {signal: AbortSignal.timeout(20000)})).json();
  for (const model of toolAudit.result.models) {
    const actual = currentModels.models.find(item => item.name === model.name);
    assert(actual && actual.size === model.size_bytes, 'Tool inventory does not match actual local Ollama: ' + model.name);
  }
  await page.screenshot({path: out + '/ceo-' + task.identifier.toLowerCase() + '.png', fullPage: true});
  return {task: data, canonical_id_status_verified: true, visible_result_verified: true,
    tool_audit: toolAudit, signed_worker_evidence: proof, canonical_worker_run: canonicalWorkerRun, ceo_actions: actions,
    objective_context_reception_method: contextTool ? 'explicit_context_tool' : 'pre_llm_context_delivery',
    objective_context_delivery_event: contextDeliveryEvent,
    ceo_runtime_log: ceoLog, worker_runtime_log: childLog, canonical_ceo_runs: runDetails,
    delegate_run_id: delegateRunId, review_run_id: reviewRunId, consolidation_run_id: consolidationRunId,
    reception_consolidation_method: receptionConsolidationMethod, child_results_delivery_event: deliveryEvent,
    comments_hash: hash(data.comments), substantive_ceo_report_verified: true, final_prose: finalProse};
}
function childWaitState(data, ceoId, allChildrenDoneSince, clock = Date.now()) {
  const latestCeoComment = (data.comments || []).filter(comment => comment.authorAgentId === ceoId)
    .sort((a, b) => (a.createdAt || '').localeCompare(b.createdAt || '')).at(-1)?.body || '';
  const children = data.children || [];
  const safeChildren = children.length > 0 && children.every(child => !['blocked', 'cancelled'].includes(child.status));
  const allDone = safeChildren && children.every(child => child.status === 'done');
  const firstAllDone = allDone && allChildrenDoneSince === null ? clock : allChildrenDoneSince;
  const markedWait = data.status === 'blocked' && latestCeoComment.startsWith('[JARVIS CEO WAITING]');
  const graceMs = markedWait && allDone ? clock - firstAllDone : null;
  return {allChildrenDoneSince: firstAllDone, graceMs,
    allowed: markedWait && safeChildren && (!allDone || graceMs < 60000),
    graceExpired: graceMs !== null && graceMs >= 60000};
}
async function waitForTask(page, task, index, ceoId, workerId) {
  await selectTask(page, task);
  const deadline = Date.now() + 3600000;
  let lastState = '', allChildrenDoneSince = null;
  while (Date.now() < deadline) {
    const data = await hud(page, 'tasks/' + task.id);
    const waiting = childWaitState(data, ceoId, allChildrenDoneSince);
    allChildrenDoneSince = waiting.allChildrenDoneSince;
    const observed = {identifier: task.identifier, id: task.id, status: data.status,
      runs: data.runs.map(run => ({id: run.runId, status: run.status})),
      children: (data.children || []).map(child => ({id: child.id, identifier: child.identifier,
        status: child.status, assigneeAgentId: child.assigneeAgentId,
        runs: child.runs.map(run => ({id: run.runId, status: run.status}))}))};
    if (waiting.graceMs !== null) observed.child_completion_grace_ms = waiting.graceMs;
    const key = JSON.stringify(observed);
    if (key !== lastState) {
      stage.progress.push({...observed, observed_at: now()});
      console.log(task.identifier + ': ' + data.status + '; runs=' +
        observed.runs.map(run => run.status).join(',') + '; children=' +
        observed.children.map(child => child.identifier + ':' + child.status).join(','));
      lastState = key;
    }
    writeStage({status: 'monitoring', current_task: task.id, current_progress: observed});
    if (waiting.graceExpired) {
      throw Error(task.identifier + ' remained blocked for 60 seconds after all children completed without native CEO continuation');
    }
    if (data.status === 'cancelled' || (data.status === 'blocked' && !waiting.allowed)) {
      throw Error(task.identifier + ' ended ' + data.status + ': ' +
        ([...(data.comments || [])].sort((a, b) => (a.createdAt || '').localeCompare(b.createdAt || '')).at(-1)?.body ||
          data.unblockDescriptor?.action || 'Review canonical execution errors').slice(0, 900));
    }
    if (data.status === 'done' && data.runs.some(run => run.status === 'succeeded') &&
      !data.runs.some(run => ['running', 'queued'].includes(run.status))) {
      return verifyTask(page, task, index, ceoId, workerId);
    }
    await pause(3000);
  }
  throw Error(task.identifier + ' exceeded its 60-minute acceptance deadline');
}

(async () => {
  for (const name of ['JARVIS_HUD_TOKEN', 'PAPERCLIP_API_KEY', 'PAPERCLIP_COMPANY_ID',
    'PAPERCLIP_CEO_AGENT_ID', 'PAPERCLIP_AGENT_ID', 'JARVIS_EXECUTION_PROOF_KEY']) {
    assert(process.env[name], 'Required server-side test configuration missing: ' + name);
  }
  fs.mkdirSync(out, {recursive: true});
  if (resume) {
    const saved = JSON.parse(fs.readFileSync(stageFile, 'utf8'));
    assert.equal(saved.submitted?.length, 2, 'Resume requires both original HUD submissions');
    Object.assign(stage, saved, {status: 'resuming', error: null});
  }
  writeStage();
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1600, height: 1050}});
  page.setDefaultTimeout(45000);
  page.on('pageerror', error => stage.browser_errors.push(error.message));
  try {
    await page.goto(url + '/hud/', {waitUntil: 'domcontentloaded'});
    const access = await page.request.get(url + '/api/usage', {timeout: 30000});
    if (access.status() === 401) {
      await page.locator('#pinGate').waitFor({state: 'visible'});
      await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
      await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.locator('#pinBtn').click()]);
    }
    await page.locator('#pinGate').waitFor({state: 'hidden'});
    await page.locator('#commandMode').selectOption('objective');
    await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    assert(await page.locator('#taskAgent').isDisabled(), 'The CEO objective assignee must be server-controlled');
    const discovery = await hud(page, 'agents');
    const ceoId = process.env.PAPERCLIP_CEO_AGENT_ID, workerId = process.env.PAPERCLIP_AGENT_ID;
    assert.equal(discovery.ceo_id, ceoId);
    assert.deepEqual(discovery.agents.map(agent => agent.id).sort(), [ceoId, workerId].sort(),
      'Acceptance must start with only the CEO and the existing worker');
    assert.equal(discovery.agents.find(agent => agent.id === ceoId).role, 'ceo');
    assert.equal(discovery.agents.find(agent => agent.id === workerId).reportsTo, ceoId);
    stage.roster_before = discovery.agents.map(agent => ({id: agent.id, name: agent.name, role: agent.role, reportsTo: agent.reportsTo}));
    if (freshDelegation) {
      const previous = await hud(page, 'tasks/' + stage.submitted[1].id);
      assert.equal(previous.status, 'cancelled', 'Cancel the superseded verification attempt through Paperclip before creating a fresh test objective');
      assert(previous.children.every(child => ['done', 'cancelled'].includes(child.status)),
        'A superseded attempt may retain completed/cancelled child history but cannot leave an active or blocked child');
      const previousAttempts = new Map();
      for (const attempt of [...(stage.previous_delegation_attempts || []), stage.previous_delegation,
        {...stage.submitted[1], status: previous.status, superseded_at: now(),
          reason: 'Prior verification attempt cancelled through Paperclip; preserved execution and child history remains inspectable.'}].filter(Boolean)) {
        if (!attempt.id) continue;
        assert.notEqual(attempt.id, stage.submitted[0].id, 'The first accepted objective must remain unchanged');
        previousAttempts.set(attempt.id, {...(previousAttempts.get(attempt.id) || {}), ...attempt});
      }
      const preserved = [];
      for (const attempt of previousAttempts.values()) {
        const historical = attempt.id === previous.id ? previous : await hud(page, 'tasks/' + attempt.id);
        preserved.push({...attempt, status: historical.status,
          child_ids: historical.children.map(child => child.id),
          children: historical.children.map(child => ({id: child.id, identifier: child.identifier,
            status: child.status, assigneeAgentId: child.assigneeAgentId}))});
      }
      stage.previous_delegation_attempts = preserved;
      stage.previous_delegation = preserved.find(attempt => attempt.id === previous.id);
      writeStage({status: 'creating_fresh_delegation'});
    }
    const submissionIndices = freshDelegation ? [1] : (resume ? [] : [0, 1]);
    if (submissionIndices.length) {
      for (const index of submissionIndices) {
        await page.locator('#chatInput').fill(prompts[index]);
        const [response] = await Promise.all([
          page.waitForResponse(response => response.url() === url + '/api/tasks' && response.request().method() === 'POST'),
          page.locator('#sendBtn').click()]);
        assert.equal(response.status(), 201, await response.text());
        const task = await response.json();
        assert.equal(task.assigneeAgentId, ceoId);
        assert.equal(response.request().postDataJSON().objective, true);
        const submitted = {id: task.id, identifier: task.identifier, prompt: prompts[index]};
        if (freshDelegation) stage.submitted[1] = submitted;
        else stage.submitted.push(submitted);
        writeStage({status: 'submitted', error: null, current_task: task.id,
          current_progress: {identifier: task.identifier, id: task.id, status: task.status, runs: [], children: []}});
        console.log('Submitted LIVE CEO objective through HUD: ' + task.identifier + ' ' + task.id);
        await page.waitForFunction(() => !document.getElementById('sendBtn').disabled);
      }
    }
    assert.notEqual(stage.submitted[0].id, stage.submitted[1].id);
    const proofs = [];
    for (let index = 0; index < stage.submitted.length; index++) {
      proofs.push(await waitForTask(page, stage.submitted[index], index, ceoId, workerId));
      fs.writeFileSync(evidenceFile, JSON.stringify({checked_at: now(), tasks: proofs,
        roster_before: stage.roster_before, previous_delegation: stage.previous_delegation,
        previous_delegation_attempts: stage.previous_delegation_attempts || [], progress: stage.progress, browser_errors: stage.browser_errors}, null, 2));
      console.log('PASS: real CEO execution verified for ' + stage.submitted[index].identifier);
    }
    await page.reload({waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    const refreshed = [];
    for (const task of stage.submitted) refreshed.push(await hud(page, 'tasks/' + task.id));
    for (let index = 0; index < proofs.length; index++) {
      assert.equal(refreshed[index].status, 'done');
      assert.equal(hash(refreshed[index].comments), proofs[index].comments_hash);
      await selectTask(page, stage.submitted[index]);
      await page.waitForFunction(identifier => document.getElementById('taskDetail').textContent.startsWith(identifier + ' · done'),
        stage.submitted[index].identifier);
    }
    const after = await hud(page, 'agents');
    assert.deepEqual(after.agents.map(agent => agent.id).sort(), stage.roster_before.map(agent => agent.id).sort(),
      'CEO created an unnecessary employee');
    assert.deepEqual(stage.browser_errors, []);
    fs.writeFileSync(evidenceFile, JSON.stringify({checked_at: now(), tasks: proofs, progress: stage.progress,
      history_after_browser_refresh: true, roster_before: stage.roster_before, previous_delegation: stage.previous_delegation,
      previous_delegation_attempts: stage.previous_delegation_attempts || [],
      roster_after: after.agents.map(agent => ({id: agent.id, name: agent.name, role: agent.role, reportsTo: agent.reportsTo})),
      no_unnecessary_employees: true, browser_errors: stage.browser_errors}, null, 2));
    writeStage({status: 'passed'});
    console.log('PASS: LIVE CEO self-execution and persistent CEO-to-worker delegation, native wake, verified consolidation, refreshed history and unchanged two-agent roster.');
  } catch (error) {
    await page.screenshot({path: out + '/ceo-test-failure.png', fullPage: true}).catch(() => {});
    writeStage({status: 'failed', error: error.message});
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
