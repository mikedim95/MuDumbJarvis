// Only HUD static assets use the live server. All API traffic stays in browser fixtures.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

const origin = process.env.JARVIS_HUD_ORIGIN || 'http://127.0.0.1:8765';
const ceoId = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
const projectId = 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb';
const approvalId = 'cccccccc-cccc-4ccc-cccc-cccccccccccc';

async function main() {
  const browser = await chromium.launch({args: ['--no-sandbox']});
  try {
    const context = await browser.newContext({serviceWorkers: 'block'});
    await context.routeWebSocket('**/*', socket => socket.close());
    const page = await context.newPage();
    page.setDefaultTimeout(7000);
    const agent = {id: ceoId, name: 'Jarvis', scope: 'agent', lifecycleState: 'ready'};
    const project = {id: projectId, identifier: 'TEST-1', status: 'todo', title: 'Test mission',
      assigneeAgentId: ceoId, work_scope: 'project', mission_id: projectId, comments: [], children: []};
    let projects = [], expectedPost = null;
    const errors = [], unexpected = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const req = route.request(), path = new URL(req.url()).pathname.slice(4);
      if (req.method() === 'POST' && expectedPost && path === expectedPost.path) {
        const arrived = expectedPost.arrived;
        expectedPost = null;
        arrived(route);
        return;
      }
      if (req.method() !== 'GET') {
        unexpected.push(req.method() + ' ' + path);
        return route.fulfill({status: 405, json: {}});
      }
      const reads = {
        '/agents': {ceo_id: ceoId, agents: [agent]},
        '/tasks': {tasks: projects},
        '/monitor': {task_counts: {}, agents: [], live_runs: [], approvals: [], inference: {}, resources: {}},
        ['/tasks/' + projectId]: project,
        ['/tasks/' + projectId + '/monitor']: {plans: [], blockedBy: [], blocks: [], evidence: [], artifacts: []},
        ['/tasks/' + projectId + '/events']: {task_id: projectId, task: project, artifacts: [], events: []},
        '/admin/config': {ceo_id: ceoId, agents: [agent], chat_prompts: [{name: 'General', scope: 'administrator'}]},
        '/admin/history': {messages: []},
        '/admin/conversations': {default_id: 'default', conversations: [
          {id: 'default', title: 'General chat'}, {id: 'other', title: 'Another conversation'}]},
      };
      return route.fulfill({json: reads[path] || {}});
    });
    await page.goto(origin + '/hud/', {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => window.JarvisModes && window.JarvisTasks);

    const chat = page.locator('#chatInput'), send = page.locator('#sendBtn');
    const general = page.locator('#administratorInput'), generalSend = page.locator('#administratorSend');
    function intercept(path) {
      assert.equal(expectedPost, null);
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Timed out waiting for fixture POST ' + path)), 7000);
        expectedPost = {path, arrived: route => { clearTimeout(timer); resolve(route); }};
      });
    }
    async function submit({input, button, path, message, enter = false}) {
      await input.fill(message);
      const [request] = await Promise.all([intercept(path), enter ? input.press('Enter') : button.click()]);
      assert.equal(await input.inputValue(), '', 'Composer must clear on submission to ' + path);
      return request;
    }
    async function finish(route, button, json, status = 200) {
      await route.fulfill({status, json});
      await page.waitForFunction(id => !document.getElementById(id).disabled, await button.getAttribute('id'));
    }

    const direct = {input: chat, button: send, path: '/chat', message: 'Direct message'};
    let request = await submit(direct);
    assert.equal(request.request().postDataJSON().input, direct.message);
    await chat.fill(direct.message); // A new draft can be identical to the previous message.
    await finish(request, send, {text: 'Direct reply'});
    assert.equal(await chat.inputValue(), direct.message);

    await page.locator('#projectsModeBtn').click();
    await page.locator('#newProjectBtn').click();
    const goal = {input: chat, button: send, path: '/tasks', message: '/new Create a timetable', enter: true};
    request = await submit(goal);
    assert.equal(request.request().postDataJSON().input, 'Create a timetable');
    await chat.fill('Next instruction');
    projects = [project];
    await finish(request, send, project);
    assert.equal(await chat.inputValue(), 'Next instruction');

    const update = {input: chat, button: send, path: '/tasks/' + projectId + '/messages', message: 'Change the date'};
    request = await submit(update);
    const nonce = request.request().postDataJSON().request_id;
    assert(nonce);
    await finish(request, send, {detail: 'Fixture offline'}, 503);
    assert.equal(await chat.inputValue(), update.message);
    request = await submit({...update, enter: true});
    assert.equal(request.request().postDataJSON().request_id, nonce);
    await chat.fill(update.message);
    await finish(request, send, {task: project, comment_id: 'fixture-comment'});
    assert.equal(await chat.inputValue(), update.message);

    const decision = {input: chat, button: send, path: '/approvals/' + approvalId + '/decision',
      message: '/approve ' + approvalId + ' proceed'};
    request = await submit(decision);
    await finish(request, send, {detail: 'Fixture offline'}, 503);
    assert.equal(await chat.inputValue(), decision.message);

    await page.locator('#generalModeBtn').click();
    const note = {input: general, button: generalSend, path: '/admin/chat', message: 'General instruction', enter: true};
    request = await submit(note);
    const original = request.request().postDataJSON();
    assert.equal(original.input, note.message);
    assert(original.request_id);
    await general.fill('A later draft');
    await finish(request, generalSend, {error: 'Fixture offline'}, 503);
    assert.equal(await general.inputValue(), 'A later draft');
    const retryArrived = intercept(note.path);
    await page.locator('#administratorStatus').getByRole('button', {name: 'Retry', exact: true}).click();
    request = await retryArrived;
    assert.equal(request.request().postDataJSON().request_id, original.request_id);
    assert.equal(request.request().postDataJSON().input, note.message);
    assert.equal(await general.inputValue(), 'A later draft');
    await finish(request, generalSend, {text: 'General reply'});
    assert.equal(await general.inputValue(), 'A later draft');

    request = await submit({...note, enter: false});
    await general.fill(note.message);
    await finish(request, generalSend, {text: 'Another reply'});
    assert.equal(await general.inputValue(), note.message);

    const receipt = {action: 'start_project', status: 'created', task: project};
    const assigned = {text: 'I opened the project.', administration_updates: [receipt]};
    async function projectOpened() {
      await page.waitForFunction(id => {
        const view = window.JarvisModes.snapshot();
        return view.mode === 'projects' && view.projectView === 'context' && window.JarvisTasks.snapshot().objectiveId === id;
      }, projectId);
    }
    // Switching threads during an assignment retains the original thread's link.
    request = await submit({...note, message: 'Plan a team meeting'});
    await page.locator('[data-thread-id="other"]').click();
    await finish(request, generalSend, assigned);
    await page.locator('[data-thread-id="default"]').click();
    await page.locator('#administratorFeed').getByRole('button', {name: 'Open project'}).click();
    await projectOpened();

    await page.locator('#generalModeBtn').click();
    request = await submit({...note, message: 'Prepare a meeting agenda'});
    await general.fill('Unsent chat note');
    await finish(request, generalSend, assigned);
    await projectOpened();
    await page.locator('#generalModeBtn').click();
    assert.equal(await general.inputValue(), 'Unsent chat note');
    request = await submit({...note, message: 'Write the meeting notes'});
    await finish(request, generalSend, {error: 'Reply interrupted', administration_updates: [receipt]}, 502);
    await projectOpened();
    await page.locator('#generalModeBtn').click();
    assert.equal(await general.inputValue(), '');

    await page.locator('#directModeBtn').click();
    request = await submit({...direct, message: 'Organize the next team meeting'});
    const directNonce = request.request().postDataJSON().request_id;
    assert(directNonce);
    await finish(request, send, {error: 'Fixture offline'}, 503);
    request = await submit({...direct, message: 'Organize the next team meeting'});
    assert.equal(request.request().postDataJSON().request_id, directNonce);
    await chat.fill('My next question');
    await finish(request, send, assigned);
    await projectOpened();
    await page.locator('#directModeBtn').click();
    assert.equal(await chat.inputValue(), 'My next question');

    request = await submit({...direct, message: 'Prepare a timeline'});
    await page.locator('#generalModeBtn').click();
    await finish(request, send, {error: 'Reply interrupted', administration_updates: [receipt]}, 502);
    assert.equal(await page.evaluate(() => window.JarvisModes.snapshot().mode), 'general');
    await page.locator('#directModeBtn').click();
    await page.locator('#feed').getByRole('button', {name: 'Open project'}).last().click();
    await projectOpened();
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    console.log('Composers clear on send and preserve drafts. Confirmed project assignments open from the originating chat, with retry IDs and manual links preserved.');
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
