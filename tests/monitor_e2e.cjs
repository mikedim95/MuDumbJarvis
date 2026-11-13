/* Operator acceptance fixtures only. Uses real HUD/native APIs; no scheduler. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const root = '/workspace', url = 'http://localhost:8765';
const stateFile = root + '/.runtime/phase13-browser-stage.json';
const state = fs.existsSync(stateFile) ? JSON.parse(fs.readFileSync(stateFile, 'utf8')) : {nonce: crypto.randomUUID()};
const save = () => fs.writeFileSync(stateFile, JSON.stringify(state, null, 2));
save();
async function board(method, path, data) {
  const r = await fetch('http://127.0.0.1:3100/api/' + path, {method,
    headers: {Authorization: 'Bearer ' + process.env.PAPERCLIP_API_KEY, 'Content-Type': 'application/json'},
    body: data ? JSON.stringify(data) : undefined, signal: AbortSignal.timeout(25000)});
  assert(r.ok, `Native ${method} ${path}: ${r.status}`); return r.json();
}
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1600, height: 1100}});
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const api = async path => { const r = await page.request.get(url + '/api/' + path); assert(r.ok(), await r.text()); return r.json(); };
  try {
    const unauth = await page.request.get(url + '/api/monitor'); assert.equal(unauth.status(), 401);
    await page.goto(url + '/hud/', {waitUntil: 'domcontentloaded'});
    await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
    await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.locator('#pinBtn').click()]);
    await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    const dashboard = await api('monitor');
    assert.equal(dashboard.inference.inference_slots, 1);
    assert.equal(dashboard.inference.configured_cpu_threads, 24);
    assert(dashboard.inference.available);
    assert(Array.isArray(dashboard.inference.loaded_models)); // An idle model may be unloaded.
    assert(dashboard.agents.some(a => a.capability.profile === 'research'));
    assert(dashboard.agents.some(a => a.capability.profile === 'software_development'));
    for (const id of ['employeeMonitor', 'resourceMonitor']) await page.locator('#' + id).evaluate(el => { el.open = true; });
    assert((await page.locator('#employeeList').innerText()).includes('No shell, host files'));
    assert((await page.locator('#inferenceStatus').innerText()).includes('24 CPU threads · 1 shared inference slot'));
    await page.locator('#taskHistory button').filter({hasText: /^JAR-42 ·/}).click();
    await page.waitForFunction(() => document.getElementById('taskDetail').textContent.startsWith('JAR-42 · done'));
    await page.waitForFunction(() => document.getElementById('toolEvidence').textContent.includes('VERIFIED RUNTIME'));
    const taskId = '27b20fae-a51b-43ab-9f36-514199fab977';
    const mon = await api('tasks/' + taskId + '/monitor');
    assert(mon.evidence.some(e => e.verified && e.completion_verified));
    const a = mon.artifacts.find(a => a.originalFilename === 'test_demo.py'); assert(a);
    const bytes = await page.request.get(url + '/api/tasks/' + taskId + '/artifacts/' + a.id);
    assert.equal(bytes.status(), 200);
    assert.equal(crypto.createHash('sha256').update(await bytes.body()).digest('hex'), a.sha256);
    const current = await api('tasks/' + taskId);
    const run = current.runs.find(r => r.runId === 'f6b5e6f7-8c3d-42a6-a5b5-0cf056d6db57'); assert(run);
    const log = await api('tasks/' + taskId + '/runs/' + run.runId + '/log'); assert(log.content);
    await page.locator('#logMonitor').evaluate(el => { el.open = true; });
    await page.locator('#runList .monitor-card').filter({hasText: run.runId}).getByRole('button', {name: 'Read execution log'}).click();
    await page.waitForFunction(id => document.getElementById('runLog').textContent.includes('Execution ' + id), run.runId);
    const secretValues = Object.entries(process.env).filter(([k,v]) => /KEY|TOKEN|PASSWORD|SECRET/.test(k) && v.length >= 16).map(([,v]) => v);
    const exposed = JSON.stringify({dashboard, mon, log});
    assert(secretValues.every(value => !exposed.includes(value)), 'Private credential entered monitoring');
    if (!state.task_id) {
      const t = await board('POST', 'companies/' + process.env.PAPERCLIP_COMPANY_ID + '/issues', {
        title: 'Phase 13: native monitoring control fixture', description: 'Operator test fixture: unassigned backlog task. No employee inference, hiring or external action is authorized.',
        projectId: process.env.PAPERCLIP_PROJECT_ID, status: 'backlog', workspaceSelection: {kind: 'task_directory'},
        idempotencyKey: 'jarvis:monitor-fixture:' + state.nonce, allowDuplicate: true});
      state.task_id = t.id; state.identifier = t.identifier; save();
    }
    state.approvals ||= {}; save();
    for (const decision of ['approve', 'reject']) {
      if (!state.approvals[decision]) {
        const a = await board('POST', 'companies/' + process.env.PAPERCLIP_COMPANY_ID + '/approvals', {
          type: 'request_board_approval', issueIds: [state.task_id], payload: {
            title: 'Phase 13 UI ' + decision + ' fixture', summary: 'Operator-controlled UI test; audit record only. No spending, host action, external action or employee permission is granted.',
            recommendedAction: decision + ' this test record'}});
        state.approvals[decision] = a.id; save();
      }
      const before = await board('GET', 'approvals/' + state.approvals[decision]);
      if (before.status === 'pending') {
        await page.locator('#taskRefresh').click();
        await page.locator('#approvalMonitor').evaluate(el => { el.open = true; });
        const item = page.locator('#approvalList .monitor-card').filter({hasText: state.approvals[decision]});
        await item.getByRole('button', {name: 'Review request'}).click();
        await page.getByRole('textbox', {name: 'Approval decision note'}).fill('Automated operator acceptance fixture for native ' + decision + '; no sensitive action is executed.');
        await page.getByRole('button', {name: decision === 'approve' ? 'Approve request' : 'Reject request', exact: true}).click();
        await page.waitForFunction(() => document.getElementById('approvalReview').hidden);
      }
      const after = await board('GET', 'approvals/' + state.approvals[decision]);
      assert.equal(after.status, decision === 'approve' ? 'approved' : 'rejected');
    }
    const fixture = await api('tasks/' + state.task_id);
    if (fixture.status !== 'cancelled') {
      await page.locator('#taskRefresh').click();
      await page.locator('#taskHistory button').filter({hasText: new RegExp('^' + state.identifier + ' ·')}).click();
      await page.waitForFunction(id => document.getElementById('taskDetail').textContent.startsWith(id + ' ·'), state.identifier);
      const dialogPromise = page.waitForEvent('dialog');
      await page.getByRole('button', {name: 'Cancel task tree'}).click();
      const dialog = await dialogPromise; assert(dialog.message().includes('Cancel 1 task')); await dialog.accept();
      await page.waitForFunction(id => document.getElementById('taskDetail').textContent.startsWith(id + ' · cancelled'), state.identifier);
    }
    assert.equal((await api('tasks/' + state.task_id)).status, 'cancelled');
    await page.locator('#taskRefresh').click();
    await page.locator('#taskHistory button').filter({hasText: new RegExp('^' + state.identifier + ' ·')}).click();
    await page.waitForFunction(id => document.getElementById('taskDetail').textContent.startsWith(id + ' · cancelled'), state.identifier);
    await page.route('**/api/monitor', route => route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({detail: 'Controlled monitoring outage'})}));
    await page.locator('#taskRefresh').click();
    await page.waitForFunction(() => document.getElementById('taskError').textContent.includes('Controlled monitoring outage'));
    assert((await page.locator('#taskConnection').innerText()).includes('stale'));
    await page.unroute('**/api/monitor'); await page.locator('#taskRefresh').click();
    await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    await page.reload({waitUntil: 'domcontentloaded'});
    await page.waitForFunction(id => document.getElementById('taskDetail').textContent.startsWith(id + ' · cancelled'), state.identifier);
    assert.equal((await api('tasks/' + taskId)).status, 'done');
    assert.deepEqual(errors, []);
    await page.locator('#taskHistory button').filter({hasText: /^JAR-42 ·/}).click();
    await page.waitForFunction(() => document.getElementById('taskDetail').textContent.startsWith('JAR-42 · done'));
    for (const id of ['evidenceMonitor', 'artifactMonitor']) await page.locator('#' + id).evaluate(el => { el.open = true; });
    await page.screenshot({path: root + '/docs/evidence/phase13-hud.png', fullPage: true});
    const evidence = {status: 'passed', checked_at: new Date().toISOString(), source: 'Real Chromium HUD and native Paperclip APIs',
      verified_existing_task: taskId, native_run_id: run.runId, signed_receipts_verified: true,
      artifact_hash_checked: a.sha256, authenticated_native_log_visible: true, secrets_absent: true,
      control_fixture: state, approvals: 'Actual native audit fixtures; automated operator test, not a claim of human hiring approval',
      cancellation: 'Native task-tree cancellation; no inference was started for the unassigned fixture',
      controlled_monitoring_outage_recovered: true, browser_refresh_preserved_history: true,
      inference_status: dashboard.inference, browser_errors: errors};
    fs.writeFileSync(root + '/docs/evidence/phase13-browser.json', JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
