/* Opt-in LIVE browser regression. Run only after CEO acceptance is idle.
   Only the HUD token enters the browser; other credentials stay in Node. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const expectedModel = process.env.JARVIS_TEST_MODEL || 'jarvis-hermes:3b';
const assert = require('node:assert/strict');
const root = '/workspace', out = root + '/docs/evidence';
const origin = 'http://localhost:8765';
const secrets = Object.entries(process.env).filter(([name, value]) => value &&
  name !== 'JARVIS_HUD_TOKEN' && /SECRET|_KEY$/i.test(name));
const leaks = new Set(), scanErrors = [], pageErrors = [], scanning = new Set(), scanPaths = new Map();
const activeResponsePages = new WeakSet(), preauthenticationResponsePaths = new Set();
let currentStage = 'starting';
function progress(name, detail = {}) {
  currentStage = name;
  fs.writeFileSync(root + '/.runtime/direct-chat-stage.json', JSON.stringify({checked_at: new Date().toISOString(), stage: name, ...detail}, null, 2));
  console.log('DIRECT CHAT: ' + name + (Object.keys(detail).length ? ' ' + JSON.stringify(detail) : ''));
}
async function responseText(response, path) {
  let timer;
  try {
    return await Promise.race([response.text(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('Text response body exceeded 15 seconds: ' + path)), 15000);
    })]);
  } finally { clearTimeout(timer); }
}
async function drainScans(name) {
  progress(name, {pending_response_paths: [...scanPaths.values()]});
  let timer;
  try {
    await Promise.race([Promise.all([...scanning]), new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('Response scan drain exceeded 20 seconds')), 20000);
    })]);
  } finally { clearTimeout(timer); }
}
let responseCount = 0, scanEnabled = true, taskPosts = 0;
let authenticatedPage, capturedChatResponse, failureScreenshot;
function redact(value) {
  let result = String(value);
  for (const secret of [...secrets.map(([, value]) => value), process.env.JARVIS_HUD_TOKEN].filter(Boolean)) {
    result = result.replaceAll(secret, '[REDACTED]');
  }
  return result;
}
function scan(value, source) {
  for (const [name, secret] of secrets) if (String(value).includes(secret)) leaks.add(name);
}
function attach(page) {
  page.on('pageerror', error => pageErrors.push(redact(error.message)));
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.origin === origin && url.pathname === '/api/tasks' && request.method() === 'POST') {
      taskPosts++;
    }
  });
  page.on('response', response => {
    if (!scanEnabled) return;
    const url = new URL(response.url());
    if (!activeResponsePages.has(page)) {
      if (url.origin === origin) preauthenticationResponsePaths.add(url.pathname);
      return;
    }
    if (url.origin !== origin || !/json|text\/|javascript|html/i.test(response.headers()['content-type'] || '')) return;
    if (/text\/event-stream/i.test(response.headers()['content-type'] || '')) {
      scanErrors.push({path: url.pathname, error: 'Streaming response requires a separate event-frame scan'});
      return;
    }
    const pending = (async () => {
      try {
        const body = await responseText(response, url.pathname);
        responseCount++;
        scan(body, url.pathname);
      } catch (error) {
        if (response.status() < 300 || response.status() >= 400) {
          const failure = {path: url.pathname, error: redact(error.message)};
          scanErrors.push(failure);
          console.log('DIRECT CHAT: response_scan_error ' + JSON.stringify(failure));
        }
      }
    })();
    scanning.add(pending);
    scanPaths.set(pending, url.pathname);
    pending.finally(() => { scanning.delete(pending); scanPaths.delete(pending); });
  });
}
async function browserJSON(page, path) {
  const response = await page.request.get(origin + path, {timeout: 30000});
  assert.equal(response.status(), 200, 'HUD read failed: ' + path);
  const body = await responseText(response, path);
  responseCount++;
  scan(body, path);
  return JSON.parse(body);
}
async function companyIds() {
  const response = await fetch('http://localhost:3100/api/companies/' +
    encodeURIComponent(process.env.PAPERCLIP_COMPANY_ID) + '/issues', {
    headers: {Authorization: 'Bearer ' + process.env.PAPERCLIP_API_KEY}, signal: AbortSignal.timeout(30000)});
  assert.equal(response.status, 200, 'Canonical Paperclip company issue read failed');
  const data = await response.json();
  assert(Array.isArray(data), 'Unexpected canonical issue list');
  return data.map(issue => issue.id).sort();
}
function lines(file) { return fs.readFileSync(file, 'utf8').split('\n'); }
function ceoTurns() {
  return lines(root + '/.runtime/hermes-ceo/logs/agent.log').filter(line => line.includes('conversation turn:')).length;
}
async function socketProbe(page) {
  return page.evaluate(() => new Promise(resolve => {
    const messages = [];
    let opened = false, timedOut = false;
    const socket = new WebSocket(location.origin.replace(/^http/, 'ws') + '/ws');
    const timer = setTimeout(() => {
      timedOut = true; resolve({opened, timed_out: true, code: null, messages}); socket.close();
    }, 7000);
    socket.onopen = () => { opened = true; };
    socket.onmessage = event => { messages.push(String(event.data)); socket.close(1000); };
    socket.onerror = () => {};
    socket.onclose = event => { clearTimeout(timer); resolve({opened, timed_out: timedOut, code: event.code, messages}); };
  }));
}
(async () => {
  for (const name of ['JARVIS_HUD_TOKEN', 'PAPERCLIP_API_KEY', 'PAPERCLIP_COMPANY_ID']) {
    assert(process.env[name], 'Missing server-side test configuration: ' + name);
  }
  fs.mkdirSync(out, {recursive: true});
  progress('starting');
  const ceoBefore = ceoTurns();
  const workerFile = root + '/.runtime/hermes/logs/agent.log';
  const workerLineCount = lines(workerFile).length;
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const anonymous = await browser.newContext();
    const anonymousPage = await anonymous.newPage();
    attach(anonymousPage);
    await anonymousPage.goto(origin + '/hud/', {waitUntil: 'domcontentloaded'});
    progress('anonymous_websocket');
    const rejectedSocket = await socketProbe(anonymousPage);
    rejectedSocket.messages.forEach(message => scan(message, 'unauthenticated websocket'));
    assert(!rejectedSocket.timed_out && [1006, 1008].includes(rejectedSocket.code) &&
      rejectedSocket.messages.length === 0, 'Unauthenticated browser WebSocket was not rejected');
    await drainScans('anonymous_scan_complete');
    await anonymous.close();

    const context = await browser.newContext({viewport: {width: 1600, height: 1050}});
    const page = await context.newPage();
    authenticatedPage = page;
    page.setDefaultTimeout(45000);
    attach(page);
    await page.goto(origin + '/hud/', {waitUntil: 'domcontentloaded'});
    const usage = await page.request.get(origin + '/api/usage', {timeout: 30000});
    scan(await usage.text(), '/api/usage');
    responseCount++;
    if (usage.status() === 401) {
      await page.locator('#pinGate').waitFor({state: 'visible'});
      await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
      await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.locator('#pinBtn').click()]);
    } else assert.equal(usage.status(), 200);
    await page.locator('#pinGate').waitFor({state: 'hidden'});
    activeResponsePages.add(page);
    progress('authenticated_response_scanning_enabled');
    // Navigation can abort pre-login background 401 bodies. The explicit
    // pre-login usage response above and WebSocket frames are scanned; the
    // background response observer starts after authenticated navigation.
    scan(await page.content(), 'authenticated initial DOM HTML');
    for (const path of await page.locator('script[src]').evaluateAll(elements => elements.map(element => element.src))) {
      if (new URL(path).origin !== origin) continue;
      const script = await page.request.get(path, {timeout: 30000});
      assert.equal(script.status(), 200);
      scan(await responseText(script, new URL(path).pathname), 'authenticated script source');
      responseCount++;
    }
    const acceptedSocket = await socketProbe(page);
    acceptedSocket.messages.forEach(message => scan(message, 'authenticated websocket'));
    assert(acceptedSocket.opened && !acceptedSocket.timed_out &&
      acceptedSocket.messages.some(message => { try { return JSON.parse(message).type === 'status'; } catch { return false; } }),
      'Authenticated browser WebSocket did not receive a real status frame');
    await page.locator('#commandMode').selectOption('task');
    await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    progress('checking_existing_timeout');
    const failedId = '2d33efc6-446e-48b7-b4ff-fbb76032833e';
    const failedTask = await browserJSON(page, '/api/tasks/' + failedId);
    assert.equal(failedTask.status, 'blocked');
    const timedOut = failedTask.runs.find(run => run.status === 'timed_out' && run.errorCode === 'timeout');
    assert(timedOut, 'Existing timeout fixture lost its canonical failed execution');
    const canonicalFailureResponse = await fetch('http://localhost:3100/api/issues/' + failedId, {
      headers: {Authorization: 'Bearer ' + process.env.PAPERCLIP_API_KEY}, signal: AbortSignal.timeout(30000)});
    assert.equal(canonicalFailureResponse.status, 200);
    const canonicalFailure = await canonicalFailureResponse.json();
    assert.equal(canonicalFailure.id, failedTask.id);
    assert.equal(canonicalFailure.status, 'blocked');
    const canonicalRunsResponse = await fetch('http://localhost:3100/api/issues/' + failedId + '/runs', {
      headers: {Authorization: 'Bearer ' + process.env.PAPERCLIP_API_KEY}, signal: AbortSignal.timeout(30000)});
    assert.equal(canonicalRunsResponse.status, 200);
    const canonicalFailedRuns = await canonicalRunsResponse.json();
    assert(canonicalFailedRuns.some(run => run.runId === timedOut.runId &&
      run.status === 'timed_out' && run.errorCode === 'timeout'));
    await page.locator('#taskHistory button').filter({hasText: /^JAR-4 ·/}).click();
    await page.waitForFunction(id => {
      const detail = document.getElementById('taskDetail').textContent;
      return detail.startsWith('JAR-4 · blocked') && detail.includes(id) && detail.includes('ERROR: timeout');
    }, failedId);
    const failedJobEvidence = {id: failedId, identifier: 'JAR-4', status: 'blocked',
      canonical_run_id: timedOut.runId, canonical_run_status: 'timed_out',
      canonical_error_code: 'timeout', matching_paperclip_id_status: true, actual_ui_error_visible: true};
    await page.locator('#commandMode').selectOption('chat');
    const hudBefore = (await browserJSON(page, '/api/tasks')).tasks.map(task => task.id).sort();
    const canonicalBefore = await companyIds();
    progress('submitting_one_ready_chat');
    await page.locator('#chatInput').fill('Reply with READY only.');
    const [response] = await Promise.all([
      page.waitForResponse(result => new URL(result.url()).origin === origin &&
        new URL(result.url()).pathname === '/api/chat' && result.request().method() === 'POST', {timeout: 900000}),
      page.locator('#sendBtn').click()]);
    progress('chat_response_received', {http_status: response.status()});
    assert.equal(response.status(), 200, 'Direct Hermes chat failed');
    const chatBody = await responseText(response, '/api/chat');
    scan(chatBody, '/api/chat');
    const chat = JSON.parse(chatBody);
    capturedChatResponse = {received_at: new Date().toISOString(), source: 'Actual authenticated POST /api/chat response',
      http_status: response.status(), text: redact(chat.text), run_id: redact(chat.run_id),
      reply_exactly_ready: chat.text?.trim() === 'READY',
      hud_task_ids_before: hudBefore, company_issue_ids_before: canonicalBefore,
      ceo_conversation_turns_before: ceoBefore};
    fs.writeFileSync(root + '/.runtime/direct-chat-http-response.json', JSON.stringify(capturedChatResponse, null, 2));
    assert(typeof chat.text === 'string' && chat.text.includes('READY') && typeof chat.run_id === 'string' && chat.run_id.startsWith('run_'),
      'Direct chat did not return a READY acknowledgement with a real Hermes run ID');
    await page.waitForFunction(() => document.getElementById('feed').textContent.includes('READY'), null, {timeout: 30000});
    progress('ready_visible_in_hud');
    const hudAfter = (await browserJSON(page, '/api/tasks')).tasks.map(task => task.id).sort();
    const canonicalAfter = await companyIds();
    assert.deepEqual(hudAfter, hudBefore, 'Direct chat changed HUD task IDs');
    assert.deepEqual(canonicalAfter, canonicalBefore, 'Direct chat changed canonical company issue IDs');
    assert.equal(taskPosts, 0, 'Direct chat issued an unintended POST /api/tasks');

    const session = JSON.parse(fs.readFileSync(root + '/server/logs/hermes_sessions.json', 'utf8'))['jarvis-main'];
    assert(typeof session === 'string' && session.startsWith('api_') && !session.includes('paperclip:'),
      'Direct chat reused a Paperclip issue session');
    const freshTurns = lines(workerFile).slice(workerLineCount).filter(line =>
      line.includes('conversation turn:') && line.includes('session=' + session + ' '));
    assert(freshTurns.some(line => line.includes('model=' + expectedModel + ' provider=custom')),
      'No fresh direct-session worker turn using local Ollama was recorded');
    const ceoAfter = ceoTurns();
    assert.equal(ceoAfter, ceoBefore, 'Direct chat started an unintended CEO conversation turn');
    scan(await page.content(), 'HUD DOM HTML');
    scan(await page.locator('body').innerText(), 'HUD DOM text');
    scan(await page.evaluate(() => [...document.querySelectorAll('input,textarea')]
      .map(element => element.value).join('\n')), 'HUD DOM form values');
    scanEnabled = false;
    await drainScans('final_response_scan');
    assert.deepEqual(scanErrors, [], 'Some received same-origin text responses could not be scanned');
    assert.deepEqual([...leaks], [], 'A server secret appeared in browser content; see sanitized field names');
    assert.deepEqual(pageErrors, [], 'Browser page errors were recorded');
    const evidence = {checked_at: new Date().toISOString(), status: 'passed',
      existing_failed_job: failedJobEvidence,
      unauthenticated_websocket: {rejected: true, close_code: rejectedSocket.code, messages_received: 0},
      authenticated_websocket: {connected: true, status_received: true},
      direct_chat: {text: chat.text, run_id: chat.run_id, visible_ready: true, reply_exactly_ready: chat.text.trim() === 'READY', session_id: session,
        fresh_local_runtime_turns: freshTurns},
      hud_task_ids_before: hudBefore, hud_task_ids_after: hudAfter,
      company_issue_ids_before: canonicalBefore, company_issue_ids_after: canonicalAfter,
      unintended_task_posts: taskPosts, ceo_conversation_turns_before: ceoBefore, ceo_conversation_turns_after: ceoAfter,
      secret_scan: {server_secret_fields_checked: secrets.map(([name]) => name),
        responses_scanned: responseCount, dom_scanned: true, authenticated_script_sources_scanned: true,
        response_observer_scope: 'After authenticated navigation; explicit pre-login usage response and WebSocket frames scanned separately',
        preauthentication_background_paths_excluded: [...preauthenticationResponsePaths],
        preauthentication_exclusion_reason: 'Login navigation can abort background 401 response bodies; they do not belong to the authenticated page',
        leaked_fields: []}, browser_errors: pageErrors};
    scan(JSON.stringify(evidence), 'evidence artifact');
    assert.equal(leaks.size, 0, 'Server secret detected in proposed evidence; artifact was not saved');
    progress('saving_verified_evidence');
    await page.screenshot({path: out + '/direct-chat-regression.png', fullPage: true});
    fs.writeFileSync(out + '/direct-chat-regression.json', JSON.stringify(evidence, null, 2));
    progress('passed');
    console.log('PASS: real HUD direct chat used its separate local Hermes session; no tasks/CEO turns or server-secret exposure.');
  } catch (error) {
    if (authenticatedPage && !authenticatedPage.isClosed()) {
      try {
        scan(await authenticatedPage.content(), 'failure DOM HTML');
        scan(await authenticatedPage.locator('body').innerText(), 'failure DOM text');
        scan(await authenticatedPage.evaluate(() => [...document.querySelectorAll('input,textarea')]
          .map(element => element.value).join('\n')), 'failure DOM form values');
        if (!leaks.size) {
          failureScreenshot = 'direct-chat-failure.png';
          await authenticatedPage.screenshot({path: out + '/' + failureScreenshot, fullPage: true});
        }
      } catch { failureScreenshot = undefined; }
    }
    fs.writeFileSync(out + '/direct-chat-regression.json', JSON.stringify({
      checked_at: new Date().toISOString(), status: 'failed', stage: currentStage, error: redact(error.message),
      captured_http_chat: capturedChatResponse, failure_screenshot: failureScreenshot,
      secret_scan: {responses_scanned: responseCount, leaked_fields: [...leaks]},
      browser_errors: pageErrors}, null, 2));
    throw Error(redact(error.message));
  } finally { await browser.close(); }
})().catch(error => { console.error(redact(error.message)); process.exitCode = 1; });
