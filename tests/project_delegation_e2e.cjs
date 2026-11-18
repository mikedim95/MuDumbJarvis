// Exercise the real HUD with isolated, read-only Paperclip fixtures.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

const origin = process.env.JARVIS_HUD_ORIGIN || 'http://127.0.0.1:8765';
const id = n => '00000000-0000-4000-a000-' + String(n).padStart(12, '0');
const agents = [
  ['Jarvis', 'Mission leadership'], ['Researcher', 'Source discovery'], ['Editor', 'Editorial review'],
  ['Archivist', 'Archive management'], ['Verifier', 'Source verification'],
].map(([name, title], index) => ({
  id: id(index + 1), name, title, lifecycleState: 'ready', role: index === 0 ? 'ceo' : 'worker',
  status: index === 1 ? 'running' : 'idle', reportsTo: index === 0 ? null : id(1),
}));

function job(number, parent, owner, title, status, progress, result = '') {
  return {
    id: id(number), identifier: 'JAR-' + number, parentId: parent?.id || null,
    mission_id: parent?.mission_id || id(number), work_scope: 'project',
    assigneeAgentId: agents[owner].id, title, status, brief: {progress, result},
    updatedAt: '2026-01-01T12:00:00Z', children: [], comments: [], runs: [],
  };
}

async function main() {
  const project = job(501, null, 0, 'Prepare a reading list', 'blocked', 'Waiting for source verification.');
  const research = job(502, project, 1, 'Find primary sources', 'in_progress', 'Checking two references.');
  const review = job(503, project, 2, 'Review the draft', 'done', 'Review complete.', 'Two corrections were accepted.');
  const source = job(504, research, 2, 'Verify the older source', 'blocked',
    'The archive requires a library card.', 'The publication date is still unverified.');
  project.children.push(research, review);
  research.children.push(source);
  const other = job(505, null, 0, 'Organize next month’s meeting', 'todo', 'The CEO has the assignment.');
  const scheduled = job(506, null, 0, 'Weekly reading-list check', 'in_progress', 'Checking the latest additions.');
  scheduled.originKind = 'routine_execution';
  scheduled.mission_id = project.id;
  const update = job(507, scheduled, 1, 'Check the new titles', 'in_progress', 'Looking up last week’s additions.');
  scheduled.children.push(update);
  project.scheduled_runs = [scheduled];
  const reference = ({id, identifier, title}) => ({id, identifier, title});
  const cron = {id: id(700), title: 'Weekly reading audit', status: 'active', enabled: true, work_scope: 'project',
    mission_id: project.id, mission: reference(project), assigneeAgentId: agents[0].id};
  const future = {...cron, id: id(701), title: 'Quarterly archive review', assigneeAgentId: agents[3].id};
  project.schedules = [cron, future];
  const shared = {...cron, id: id(702), title: 'Company calendar review', work_scope: 'general', mission_id: null, mission: null};
  const generalRun = job(508, null, 4, 'Review next week’s calendar', 'blocked', 'Waiting for the calendar owner to confirm the meeting dates.');
  Object.assign(generalRun, {work_scope: 'general', mission_id: null, state: 'waiting',
    cron_job: {id: shared.id, title: shared.title}, run_issue: reference(generalRun)});
  const definitions = [...project.schedules, shared];
  for (const current of [scheduled, update]) {
    current.cron_job = {id: cron.id, title: cron.title};
    current.run_issue = reference(scheduled);
  }
  project.state = scheduled.state = 'waiting';
  source.state = 'blocked';
  research.state = update.state = 'active';
  research.active_agent_id = update.active_agent_id = agents[1].id;
  review.state = 'closed';
  other.state = 'queued';
  const automaticReport = 'Archived CEO report from the initial assignment.';
  project.comments.push({id: id(600), authorAgentId: agents[0].id, body: automaticReport, createdAt: '2026-01-01T12:00:00Z'});
  const tasks = [project, research, review, source, other, scheduled, update, generalRun];
  function roster() {
    const portraits = [
      '/hud/portraits/ceo.webp', '/hud/portraits/osint.webp', '/hud/portraits/security.webp',
      '/api/agents/' + agents[3].id + '/portrait/' + id(910), '/hud/portraits/vector.webp',
    ];
    const activity = ['waiting', 'active', source.state==='closed'?'idle':'blocked', 'idle', 'waiting'];
    const reasons = [project.brief.progress, update.brief.progress, activity[2]==='idle'?'No current assignment.':source.brief.progress,
      'No current assignment.', generalRun.brief.progress];
    return agents.map((agent, index) => {
      const assignments = tasks.filter(task => task.assigneeAgentId === agent.id).map(task => ({
        ...reference(task), status: task.status, state: task.state, reason: task.brief.progress, work_scope: task.work_scope,
        mission: task.work_scope === 'general' ? null : reference(task === other ? other : project),
        assigneeAgentId: task.assigneeAgentId, active_agent_id: task.active_agent_id || null,
        cron_job: task.cron_job || null, run_issue: task.run_issue || null,
      }));
      return {...agent, portrait_url: portraits[index],
        specialization: agent.title, activity: activity[index], status_reason: reasons[index],
        work: assignments.filter(task => task.state !== 'closed'),
        past_work: assignments.filter(task => task.state === 'closed'),
        schedules: definitions.filter(schedule => schedule.assigneeAgentId === agent.id)};
    });
  }
  const fileName = 'reading-list-evidence.txt';
  const unexpected = [], errors = [];

  const browser = await chromium.launch({args: ['--no-sandbox']});
  try {
    const context = await browser.newContext({serviceWorkers: 'block'});
    await context.routeWebSocket('**/*', socket => socket.close());
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(4);
      if (request.method() !== 'GET' || path.includes('/artifacts/')) {
        unexpected.push(request.method() + ' ' + path);
        return route.fulfill({status: 405, json: {}});
      }
      if (path === '/agents/' + agents[3].id + '/portrait/' + id(910)) {
        // A one-pixel PNG supplied as an authenticated native portrait.
        return route.fulfill({contentType:'image/png',body:Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64')});
      }
      const detail = tasks.find(task => '/tasks/' + task.id === path);
      if (detail) return route.fulfill({json: detail});
      if (path.startsWith('/tasks/') && path.endsWith('/events')) {
        const task = tasks.find(task => path === '/tasks/' + task.id + '/events');
        return route.fulfill({json: {task_id: task.id, task, events: [], artifacts: [{
          id: id(900), issueId: task.id, originalFilename: fileName, sha256: 'fixture', byteSize: 20,
        }]}});
      }
      if (path.endsWith('/monitor') && path.startsWith('/tasks/')) {
        return route.fulfill({json: {plans: [], blockedBy: [], blocks: [], evidence: [], artifacts: []}});
      }
      const reads = {
        '/agents': {ceo_id: agents[0].id, agents},
        '/agents/work': {ceo_id: agents[0].id, agents: roster()},
        '/cron-jobs': {jobs: definitions.filter(schedule => schedule.work_scope === url.searchParams.get('scope') &&
          schedule.mission_id === url.searchParams.get('mission_id')).map(schedule => ({...schedule, description: 'Check the reading list.',
          triggers: [{kind: 'schedule', enabled: true, cronExpression: '0 9 * * 1', timezone: 'UTC'}]})),
          projects: [], missions: [{...reference(project), closed: false}]},
        '/tasks': {tasks: tasks.map(({brief, children, comments, runs, scheduled_runs, schedules, ...row}) => row)},
        '/monitor': {task_counts: {}, agents: [], live_runs: [], approvals: [], inference: {}, resources: {}},
        '/admin/conversations': {default_id: 'default', conversations: [{id: 'default', title: 'General chat'}]},
        '/admin/history': {messages: []},
        '/admin/config': {ceo_id: agents[0].id, agents, chat_prompts: [{scope: 'administrator', name: 'General chat'}]},
      };
      return route.fulfill({json: reads[path] || {}});
    });
    await page.goto(origin + '/hud/', {waitUntil: 'domcontentloaded'});
    const tree = page.locator('#projectDelegation');
    const item = task => tree.locator('li[data-task-id="' + task.id + '"]');
    const card = task => item(task).locator(':scope > article');
    async function choose(task) {
      await page.locator('#projectsModeBtn').click();
      const item = page.locator('.project-list-item[data-project-id="' + task.id + '"]');
      if (task === project) assert.equal(await item.locator('.project-item-status').innerText(), 'Waiting');
      await item.click();
      await card(task).waitFor({state: 'visible'});
      if (task === project) assert((await page.locator('#projectStatus').innerText()).endsWith('Waiting'));
    }
    async function checkNoFiles() {
      assert.equal(await page.locator('#feed .project-file:visible, #feed [download]:visible').count(), 0);
      assert.equal(await page.getByText(fileName, {exact: true}).isVisible(), false);
    }

    await choose(project);
    assert.equal(await tree.locator('li[data-task-id]').count(), 6);
    assert.deepEqual(await item(project).locator(':scope > ul:not(.delegation-scheduled) > li').evaluateAll(nodes =>
      nodes.map(node => node.dataset.taskId).sort()), [research.id, review.id].sort());
    assert.equal(await item(research).locator(':scope > ul > li').getAttribute('data-task-id'), source.id);
    assert.equal(await item(project).locator(':scope > ul.delegation-scheduled > li').getAttribute('data-task-id'), scheduled.id);
    assert.equal((await card(scheduled).locator('.job-kind').innerText()).toLowerCase(), 'scheduled run');
    const [rootBox, branchBox, leafBox] = await Promise.all([project, research, source].map(task => card(task).boundingBox()));
    assert(rootBox.x < branchBox.x && branchBox.x < leafBox.x, 'Nested assignments should be visibly indented');
    assert(await item(source).evaluate(node => parseFloat(getComputedStyle(node, '::before').borderBlockEndWidth) > 0),
      'A visible connector should join each job to its parent');
    for (const task of [project, research, review, source, scheduled, update]) {
      const node = card(task), content = await node.innerText();
      const titleText = task === project ? await page.locator('#projectTitle').innerText() : content;
      assert(titleText.includes(task.title));
      assert(content.includes(agents.find(agent => agent.id === task.assigneeAgentId).name));
      assert.equal(await node.locator('.job-state').getAttribute('data-status'), task.status);
      assert((await node.locator('.job-state').innerText()).trim());
      assert((await node.locator('.job-progress').innerText()).includes(task.brief.progress));
      if (task.brief.result) assert((await node.locator('.job-result').innerText()).includes(task.brief.result));
    }
    // Paperclip reports both as blocked. Only the task with an actionable barrier uses the blocked label.
    assert.equal(await card(project).locator('.job-engagement').innerText(), 'Waiting');
    assert.equal(await card(project).locator('.job-engagement').getAttribute('data-state'), 'waiting');
    assert.equal(await card(source).locator('.job-engagement').innerText(), 'Blocked');
    assert.equal(await card(source).locator('.job-engagement').getAttribute('data-state'), 'blocked');
    assert.equal(await card(update).locator('.job-engagement').getAttribute('data-state'), 'active');
    assert((await card(update).locator('.job-routine[data-routine-id="' + cron.id + '"]').innerText()).includes(cron.title));
    const schedules = tree.locator('.project-schedules');
    const upcoming = schedules.locator('[data-routine-id="' + future.id + '"]');
    assert((await upcoming.innerText()).includes(future.title));
    const futureOwner = upcoming.locator('.schedule-owner .job-owner[data-agent-id="' + agents[3].id + '"]');
    assert.equal(await futureOwner.innerText(), agents[3].name);
    assert.equal(await upcoming.locator('[data-running="true"]').count(), 0);
    assert.equal(await schedules.locator('[data-routine-id="' + cron.id + '"] [data-running="true"]').count(), 1);
    await checkNoFiles();
    assert(!(await page.locator('#feed').innerText()).includes(automaticReport));
    const cronCard = page.locator('.cron-card[data-job-id="' + cron.id + '"][data-selected="true"]');
    await card(update).getByRole('button', {name: 'Open cron job ' + cron.title}).click();
    await cronCard.waitFor({state: 'visible'});
    await page.locator('#cronBackBtn').click();
    await card(update).waitFor({state: 'visible'});

    await page.locator('#generalModeBtn').click();
    await page.locator('#administratorInput').fill('Keep this general draft.');
    const agentsButton = page.locator('#generalAgentsBtn');
    const [agentsBox, cronBox] = await Promise.all([agentsButton, page.locator('#generalCronBtn')].map(button => button.boundingBox()));
    assert(agentsBox.y > cronBox.y && Math.abs(agentsBox.x - cronBox.x) < 8);
    await agentsButton.click();
    const map = page.locator('#agentsMap');
    const station = index => map.locator('button.agent-station[data-agent-id="' + agents[index].id + '"]');
    const details = index => page.locator('#agentDetails[data-agent-id="' + agents[index].id + '"]');
    const assignment = (index, task) => details(index).locator('[data-issue-id="' + task.id + '"]');
    async function selectPortrait(index, keyboard = false) {
      const tile = station(index);
      if (await tile.getAttribute('aria-expanded') !== 'true') {
        if (keyboard) { await tile.focus(); await tile.press('Enter'); }
        else await tile.click();
      }
      await details(index).waitFor({state:'visible'});
      assert.equal(await tile.getAttribute('aria-expanded'), 'true');
    }
    await station(3).waitFor({state: 'visible'});
    assert.equal(await map.locator('.agent-station').count(), agents.length);
    assert.equal(await map.locator('#agentLeader .agent-station').count(),1);
    assert.equal(await map.locator('#agentTeam .agent-station').count(),agents.length-1);
    assert.equal(await page.locator('#agentDetails:visible').count(),0);
    for (const [index, agent] of roster().entries()) {
      const tile = station(index);
      assert((await tile.locator('.agent-name').innerText()).includes(agent.name));
      assert.equal(await tile.locator('.agent-specialization').innerText(),agent.specialization);
      assert.equal(await tile.getAttribute('data-activity'), agent.activity);
      const img = tile.locator('img.agent-portrait');
      const portrait = await img.evaluate(async node => {
        await node.decode();
        return {url:new URL(node.currentSrc).pathname,width:node.naturalWidth,height:node.naturalHeight};
      });
      assert.equal(portrait.url,agent.portrait_url);
      const minSize = agent.portrait_url.startsWith('/hud/') ? 128 : 1;
      assert(portrait.width >= minSize && portrait.height >= minSize, 'The assigned portrait must decode');
      const [imageRect, statusRect] = await Promise.all([img,tile.locator('.agent-activity')].map(n => n.boundingBox()));
      assert(statusRect.x < imageRect.x+imageRect.width && statusRect.x+statusRect.width > imageRect.x &&
        statusRect.y < imageRect.y+imageRect.height && statusRect.y+statusRect.height > imageRect.y,'Status should overlay the portrait');
    }
    const coords = await Promise.all(agents.map((_,i) => station(i).boundingBox()));
    const lineup = await map.locator('#agentTeam').boundingBox();
    assert(Math.abs((coords[0].x+coords[0].width/2) - (lineup.x+lineup.width/2)) < 8,
      'The CEO portrait should be centered above the team');
    for (const [i,worker] of coords.slice(1).entries()) {
      assert(worker.y >= coords[0].y+coords[0].height,'The CEO portrait should sit above all workers');
      assert(Math.abs(worker.y-coords[1].y) < 3,'Workers share one row');
      if (i > 0) assert(worker.x > coords[i].x,'Worker portraits should appear side by side');
    }
    assert.match(await station(1).locator('.agent-activity').innerText(), /running|working|active/i);
    assert.match(await station(2).locator('.agent-activity').innerText(), /blocked/i);
    assert.match(await station(4).locator('.agent-activity').innerText(), /waiting/i);
    assert.match(await station(3).locator('.agent-activity').innerText(), /idle/i);
    await selectPortrait(2,true);
    assert((await details(2).innerText()).includes(source.brief.progress));
    assert.match(await assignment(2,source).innerText(), /blocked/i);
    await station(2).press('Space');
    assert.equal(await page.locator('#agentDetails:visible').count(),0);
    await selectPortrait(4);
    assert((await details(4).innerText()).includes(generalRun.brief.progress));
    assert(!(await details(4).innerText()).includes(source.brief.progress));
    await selectPortrait(1);
    assert.match(await assignment(1, update).innerText(), /running|working|active/i);
    await selectPortrait(3);
    const ownerSchedule = details(3).locator('.agent-schedule[data-routine-id="' + future.id + '"]');
    assert((await ownerSchedule.innerText()).includes(future.title));
    await ownerSchedule.locator('button[data-project-id="' + project.id + '"]').click();
    await futureOwner.click();
    await details(3).waitFor({state: 'visible'});
    assert(await station(3).evaluate(el => el.contains(document.activeElement)));
    await selectPortrait(1);
    const routineWork = assignment(1, update);
    const cronLink = routineWork.locator('[data-routine-id="' + cron.id + '"]');
    assert((await cronLink.innerText()).includes(cron.title));
    await cronLink.click();
    await cronCard.waitFor({state: 'visible'});
    assert(await cronCard.evaluate(node => node === document.activeElement));
    assert((await page.locator('#cronHeading').innerText()).includes('Mission'));
    assert.equal(await page.evaluate(() => window.JarvisModes.snapshot().missionId), project.id);
    await page.locator('#generalModeBtn').click();
    await agentsButton.click();
    await selectPortrait(4);
    await assignment(4, generalRun).locator('[data-routine-id="' + shared.id + '"]').click();
    await page.locator('.cron-card[data-job-id="' + shared.id + '"][data-selected="true"]').waitFor({state: 'visible'});
    assert((await page.locator('#cronHeading').innerText()).includes('General'));
    await agentsButton.click();
    await selectPortrait(1);
    await routineWork.locator('button[data-project-id="' + project.id + '"]').click();
    await card(update).waitFor({state: 'visible'});
    const worker = card(update).locator('button[data-agent-id="' + agents[1].id + '"]');
    assert.equal(await worker.innerText(), agents[1].name);
    await worker.click();
    await details(1).waitFor({state: 'visible'});
    assert(await station(1).evaluate(el => el.contains(document.activeElement)));
    assert.equal(await page.locator('#administratorInput').inputValue(), 'Keep this general draft.');
    await choose(project);

    // Root and parent timestamps stay the same while the grandchild and conversation update.
    source.status = 'done';
    source.state = 'closed';
    source.brief = {progress: 'Archive entry checked.', result: 'The publication date is confirmed.'};
    const answer = 'I confirmed the date and will review the reading list.';
    project.comments.push(
      {id: id(601), authorUserId: id(42), body: '[JARVIS USER MESSAGE request_id=' + id(700) + ']\nIs the date confirmed?', createdAt: '2026-01-01T13:00:00Z'},
      {id: id(602), authorAgentId: agents[0].id, body: answer, createdAt: '2026-01-01T13:01:00Z'},
      {id: id(603), authorAgentId: agents[0].id, body: '[JARVIS CEO REVIEW]\nInternal review marker', createdAt: '2026-01-01T13:02:00Z'},
    );
    await card(source).locator('.job-state[data-status="done"]').waitFor();
    assert((await card(source).innerText()).includes(source.brief.result));
    assert(!(await card(source).innerText()).includes('library card'));
    await page.locator('#feed [data-ceo-comment-id="' + id(602) + '"]').waitFor({state: 'visible'});
    const feedText = await page.locator('#feed').innerText();
    assert(feedText.includes(answer));
    assert(!feedText.includes(automaticReport) && !feedText.includes('[JARVIS '));

    await page.setViewportSize({width: 390, height: 844});
    await card(source).scrollIntoViewIfNeeded();
    assert(await tree.evaluate(node => node.scrollWidth <= node.clientWidth + 1));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert(await page.locator('#chatInput').isVisible());
    await choose(other);
    assert.equal(await tree.locator('li[data-task-id]').count(), 1);
    assert.equal(await page.getByText(source.brief.result, {exact: true}).isVisible(), false);
    await checkNoFiles();
    await page.reload({waitUntil: 'domcontentloaded'});
    await card(other).waitFor({state: 'visible'});
    assert.equal(await tree.locator('li[data-task-id]').count(), 1);
    await page.locator('#projectBackBtn').click();
    await page.locator('#newProjectBtn').click();
    assert.equal(await tree.isVisible(), false);
    assert(await page.locator('#chatInput').isVisible());
    await page.locator('#generalModeBtn').click();
    const sidebar = page.locator('#generalSidebarToggle');
    await sidebar.click();
    await agentsButton.click();
    await station(3).waitFor({state: 'visible'});
    const team = map.locator('#agentTeam');
    await station(2).locator('.agent-activity').filter({hasText:/idle/i}).waitFor();
    const mobileWorkers = await Promise.all(agents.slice(1).map((_,i) => station(i+1).boundingBox()));
    assert(mobileWorkers.every(box => Math.abs(box.y-mobileWorkers[0].y) < 3),'Mobile worker portraits must stay on one row');
    await selectPortrait(4,true);
    const [mobileRow, lastPortrait] = await Promise.all([team,station(4)].map(n => n.boundingBox()));
    assert(lastPortrait.x >= mobileRow.x-2 && lastPortrait.x+lastPortrait.width <= mobileRow.x+mobileRow.width+2,
      'The final mobile portrait must be reachable within the horizontal row');
    assert((await details(4).innerText()).includes(generalRun.brief.progress));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert(await page.locator('#administratorInput').isVisible());
    await sidebar.click();
    await page.locator('#generalThreads button[data-thread-id=default]').click();
    assert(await page.locator('#administratorPanel').isVisible());
    assert.equal(await page.locator('#administratorInput').inputValue(), 'Keep this general draft.');
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    console.log('Delegation, decoded agent portraits, waiting and blocked reasons, keyboard and mobile selection, and project/cron links passed.');
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
