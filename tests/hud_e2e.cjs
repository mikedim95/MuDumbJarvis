/* Opt-in real Chromium HUD verification. Requires local Docker host networking.
   Secrets remain in Node's environment; only the HUD token enters its login UI. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const root = '/workspace';
const out = root + '/docs/evidence';
const url = 'http://localhost:8765';
const prompt = 'Use the available local tools to list my installed Ollama models, identify their names and sizes, and recommend which are suitable for research and coding.';
const observe = process.argv.includes('--observe');
const stage = root + '/.runtime/browser-stage.json';
const restarted = root + '/.runtime/browser-restart-done';
const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function writeStage(value) { fs.writeFileSync(stage, JSON.stringify(value, null, 2)); }
async function selectTask(page, identifier) {
  await page.locator('#taskHistory button').filter({hasText: new RegExp('^' + identifier + ' ·')}).click();
  await page.waitForFunction(id => document.getElementById('taskDetail').textContent.startsWith(id + ' ·'), identifier);
}
async function result(page, task) {
  await selectTask(page, task.identifier);
  await page.waitForFunction(identifier => {
    const text = document.getElementById('taskDetail').textContent;
    return ['done', 'blocked', 'cancelled'].some(status => text.startsWith(identifier + ' · ' + status));
  }, task.identifier, {timeout: 1000000, polling: 3000});
  const text = await page.locator('#taskDetail').innerText();
  assert(text.startsWith(task.identifier + ' · done'), text);
  assert(text.includes(task.id), 'HUD and task response must identify the same issue');
  const response = await page.request.get(url + '/api/tasks/' + task.id);
  assert.equal(response.status(), 200);
  const data = await response.json();
  assert.equal(data.status, 'done');
  assert(data.comments.length && data.runs.some(run => run.status === 'succeeded'));
  const rows = fs.readFileSync(root + '/.runtime/hermes/logs/paperclip-tools.jsonl', 'utf8').trim().split('\n').map(JSON.parse);
  const audit = rows.find(row => row.issue_id === task.id);
  assert(audit && audit.tool === 'local_ollama_models' && audit.result.models.length);
  for (const model of audit.result.models) assert(text.includes(model.name), 'HUD missing exact retrieved model: ' + model.name);
  assert(text.includes('Verified local_ollama_models data'));
  const canonical = await fetch('http://localhost:3100/api/issues/' + task.id, {
    headers: {Authorization: 'Bearer ' + process.env.PAPERCLIP_API_KEY}, signal: AbortSignal.timeout(20000)});
  assert.equal(canonical.status, 200);
  const issue = await canonical.json();
  assert.equal(issue.id, data.id);
  assert.equal(issue.status, data.status);
  const runtime = fs.readFileSync(root + '/.runtime/hermes/logs/agent.log', 'utf8').split('\n')
    .filter(line => line.includes('issue:' + task.id) && (line.includes('conversation turn:') || line.includes('tool local_ollama_models completed')));
  assert(runtime.some(line => line.includes('model=jarvis-hermes:3b provider=custom')));
  await page.screenshot({path: out + '/hud-' + task.identifier.toLowerCase() + '.png', fullPage: true});
  return {task: data, tool_audit: audit, runtime_log: runtime, comments_hash: hash(data.comments), visible_result_verified: true};
}

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1600, height: 1050}});
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(url + '/hud/', {waitUntil: 'domcontentloaded'});
    await page.locator('#pinGate').waitFor({state: 'visible'});
    await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
    await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.locator('#pinBtn').click()]);
    await page.locator('#pinGate').waitFor({state: 'hidden'});
    await page.locator('#commandMode').selectOption('task');
    await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    const option = page.locator('#taskAgent option').filter({hasText: 'JARVIS-01'});
    await page.locator('#taskAgent').selectOption(await option.getAttribute('value'));
    if (observe) {
      const task = {id: 'b5c84f82-095c-4235-ac40-0b963b301c7f', identifier: 'JAR-7'};
      const proof = await result(page, task);
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
      await selectTask(page, task.identifier);
      await page.waitForFunction(id => document.getElementById('taskDetail').textContent.startsWith(id + ' · done'), task.identifier);
      fs.writeFileSync(out + '/phase4-hud.json', JSON.stringify({...proof, history_after_refresh: true, browser_errors: errors}, null, 2));
      console.log('PASS: user-submitted JAR-7 is rendered with real tool data and survives browser refresh.');
    } else {
      fs.rmSync(restarted, {force: true});
      const tasks = [];
      for (let index = 0; index < 2; index++) {
        await page.locator('#chatInput').fill(prompt);
        const [response] = await Promise.all([
          page.waitForResponse(response => response.url() === url + '/api/tasks' && response.request().method() === 'POST'),
          page.locator('#sendBtn').click()]);
        assert.equal(response.status(), 201, await response.text());
        const task = await response.json();
        tasks.push(task);
        console.log('Submitted through actual HUD:', task.identifier, task.id);
        await page.waitForFunction(() => !document.getElementById('sendBtn').disabled);
        await page.reload({waitUntil: 'domcontentloaded'});
        await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
        await selectTask(page, task.identifier);
      }
      assert.notEqual(tasks[0].id, tasks[1].id);
      const proofs = [];
      for (const task of tasks) {
        proofs.push(await result(page, task));
        console.log('PASS: HUD displays verified completed execution:', task.identifier);
      }
      fs.writeFileSync(out + '/phase5-browser.json', JSON.stringify({tasks: proofs, history_after_submission_refresh: true, browser_errors: errors}, null, 2));
      writeStage({status: 'ready_for_restart', task_ids: tasks.map(task => task.id)});
      console.log('Ready for service restart verification.');
      const deadline = Date.now() + 600000;
      while (!fs.existsSync(restarted)) {
        if (Date.now() > deadline) throw Error('Service restart verification was not performed within ten minutes');
        await pause(1000);
      }
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
      const after = [];
      for (const task of tasks) after.push(await result(page, task));
      for (let index = 0; index < proofs.length; index++) assert.equal(proofs[index].comments_hash, after[index].comments_hash);
      fs.writeFileSync(out + '/phase5-browser.json', JSON.stringify({tasks: proofs, after_restart: after,
        history_after_submission_refresh: true, history_after_service_restart: true, browser_errors: errors}, null, 2));
      writeStage({status: 'passed', task_ids: tasks.map(task => task.id)});
      console.log('PASS: actual HUD task history and results survive service restart.');
    }
  } catch (error) {
    await page.screenshot({path: out + '/hud-test-failure.png', fullPage: true}).catch(() => {});
    writeStage({status: 'failed', error: error.message});
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
