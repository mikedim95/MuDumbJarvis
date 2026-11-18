/* Real objective submission/observation. Not an application service or scheduler. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const root = '/workspace', url = 'http://localhost:8765';
const trial = Number((process.argv.find(v => v.startsWith('--trial=')) || '--trial=1').split('=')[1]);
assert([1,2,3].includes(trial));
const stageFile = root + '/.runtime/phase14-trial-' + trial + '.json';
const evidenceFile = root + '/docs/evidence/phase14-trial-' + trial + '.json';
const prompt = 'Research three open-source AI security frameworks, compare their capabilities and architectures, produce a technical report, create a minimal isolated demonstration, and execute tests.';
const state = fs.existsSync(stageFile) ? JSON.parse(fs.readFileSync(stageFile, 'utf8')) :
  {trial, objective: prompt, started_at: new Date().toISOString(), request_id: crypto.randomUUID(), progress: []};
const save = () => { fs.writeFileSync(stageFile, JSON.stringify(state, null, 2), {mode: 0o600}); fs.chmodSync(stageFile, 0o600); };
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function safeError(error) {
  let message = String(error.message || error).split('Call log:')[0].trim();
  for (const [key,value] of Object.entries(process.env)) {
    if (/KEY|TOKEN|PASSWORD|SECRET/.test(key) && value.length >= 12) message = message.replaceAll(value,'[REDACTED]');
  }
  return message;
}
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1600, height: 1100}});
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  async function api(path) {
    for(let attempt=0;attempt<4;attempt++) {
      try {
        const r = await page.request.get(url + '/api/' + path, {timeout: 30000});
        if(r.status()>=500 && attempt<3) {await pause(3000);continue;}
        assert(r.ok(), 'HUD GET ' + path + ': ' + r.status()); return r.json();
      } catch(error) {
        if(attempt===3) throw new Error(safeError(error));
        await pause(3000);
      }
    }
  }
  const now = () => new Date().toISOString();
  try {
    await page.goto(url + '/hud/', {waitUntil: 'domcontentloaded'});
    await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
    await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.locator('#pinBtn').click()]);
    await page.locator('#commandMode').selectOption('objective');
    await page.waitForFunction(() => document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    if (!state.task_id) {
      state.roster_before = (await api('agents')).agents.map(a => ({id: a.id, role: a.role})); save();
      await page.locator('#chatInput').fill(state.objective);
      const [response] = await Promise.all([
        page.waitForResponse(r => r.url() === url + '/api/tasks' && r.request().method() === 'POST'),
        page.locator('#sendBtn').click()]);
      assert.equal(response.status(), 201, await response.text());
      assert.equal(response.request().postDataJSON().objective, true);
      const task = await response.json();
      assert.equal(task.assigneeAgentId, process.env.PAPERCLIP_CEO_AGENT_ID);
      state.task_id = task.id; state.identifier = task.identifier; state.native_submission_id = response.request().postDataJSON().request_id; save();
      console.log(JSON.stringify({event: 'objective_submitted_through_HUD', trial, task_id: task.id, identifier: task.identifier, at: now()}));
    } else {
      await page.locator('#taskHistory button').filter({hasText: new RegExp('^' + state.identifier + ' ·')}).click();
      console.log(JSON.stringify({event: 'observing_same_objective', trial, task_id: state.task_id, identifier: state.identifier, at: now()}));
    }
    if (process.argv.includes('--retry')) {
      delete state.error; // Discard old pre-redaction Playwright diagnostics.
      await page.waitForFunction(id => document.getElementById('taskActions').dataset.taskId === id, state.task_id);
      const responsePromise = page.waitForResponse(r => r.url() === url + '/api/tasks/' + state.task_id + '/retry' && r.request().method() === 'POST');
      await page.locator('#taskActions').getByRole('button', {name:'Retry same task',exact:true}).click();
      const response = await responsePromise;
      assert(response.ok(),await response.text());
      state.retries ||= [];state.retries.push({at:now(),response:await response.json()});save();
      console.log(JSON.stringify({event:'same_task_retry_through_HUD',trial,task_id:state.task_id,...state.retries.at(-1)}));
      await pause(9000); // Native retry admission is asynchronous; old blocked state is not a new outcome.
    }
    if (process.argv.includes('--submit-only')) return;
    let previous = null, task;
    for (let n = 0; n < 600; n++) {
      task = await api('tasks/' + state.task_id);
      const snapshot = {status: task.status, execution: task.executionRunId,
        runs: task.runs.map(r => ({id:r.runId,status:r.status,error:r.errorCode})),
        children: task.children.map(c => ({id:c.id,identifier:c.identifier,agent:c.assigneeAgentId,status:c.status,execution:c.executionRunId,
          runs:c.runs.map(r=>({id:r.runId,status:r.status,error:r.errorCode}))}))};
      const serialized = JSON.stringify(snapshot);
      if (serialized !== previous) {
        previous = serialized; state.progress.push({at:now(),...snapshot}); save();
        console.log(JSON.stringify({event:'native_progress',trial,task_id:task.id,at:now(),...snapshot}));
      }
      const retry = state.retries?.at(-1)?.response;
      if (retry?.accepted && !task.runs.some(r=>r.runId!==retry.observedRunId &&
          (!r.startedAt || r.startedAt >= state.retries.at(-1).at))) {
        await pause(3000); continue; // Acknowledged native retry has not been admitted yet.
      }
      if (!task.executionRunId && task.status === 'done' && task.children.length === 2 && task.children.every(c=>c.status==='done' && !c.executionRunId)) break;
      const live = item => item.executionRunId || item.runs.some(r=>['running','queued'].includes(r.status));
      if (!live(task) && task.children.some(c=>['blocked','cancelled','in_review'].includes(c.status) && !live(c))) {
        state.status='requires_review';save();
        console.log(JSON.stringify({event:'requires_review',trial,task_id:task.id,children:snapshot.children}));
        return;
      }
      if (!live(task) && !task.children.length && ['blocked','cancelled'].includes(task.status)) {
        state.status='requires_review';save();
        console.log(JSON.stringify({event:'requires_review',trial,task_id:task.id,status:task.status}));return;
      }
      await pause(3000);
    }
    assert.equal(task.status,'done','Objective did not complete'); assert.equal(task.children.length,2,'Minimum two existing capabilities must suffice');
    const agents = (await api('agents')).agents;
    assert.deepEqual(agents.map(a=>a.id).sort(),state.roster_before.map(a=>a.id).sort(),'Unnecessary employee created');
    const children=[];
    for (const child of task.children) {
      const m=await api('tasks/'+child.id+'/monitor');
      const proof=m.evidence.findLast(e=>e.verified && e.completion_verified && e.kind==='execution');
      assert(proof,'No authenticated actual completed worker execution');
      assert(child.runs.some(r=>r.runId===proof.run_id && r.status==='succeeded'));
      assert(m.artifacts.length,'No native persisted deliverables');
      const downloads=[];
      for(const artifact of proof.artifacts) {
        const r=await page.request.get(url+'/api/tasks/'+child.id+'/artifacts/'+artifact.id);
        assert.equal(r.status(),200);
        const raw=await r.body(); assert.equal(crypto.createHash('sha256').update(raw).digest('hex'),artifact.sha256);
        downloads.push({id:artifact.id,name:artifact.originalFilename,sha256:artifact.sha256,bytes:raw.length,
          text:raw.length<16000?raw.toString('utf8'):undefined});
      }
      children.push({task:child,monitor:m,proof,downloaded_artifacts:downloads});
    }
    assert(children.some(c=>c.proof.tools.some(t=>t.tool==='research_sources' && t.success)));
    const dev=children.find(c=>c.proof.tools.some(t=>t.tool==='terminal' && t.success)); assert(dev);
    assert(dev.monitor.blockedBy.some(i=>i.id===children.find(c=>c!==dev).task.id),'Native dependency missing');
    const topMonitor=await api('tasks/'+task.id+'/monitor');
    assert(topMonitor.plans.length,'No native CEO plan'); assert(topMonitor.artifacts.some(a=>a.originalFilename.endsWith('.md')),'No consolidated report artifact');
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(id=>document.getElementById('taskDetail').textContent.startsWith(id+' · done'),state.identifier);
    assert.deepEqual(errors,[]);
    const result={status:'execution_verified_pending_factual_review',trial,checked_at:now(),task,monitor:topMonitor,children,
      unchanged_roster:true,history_after_browser_refresh:true,browser_errors:errors,progress:state.progress,
      limitation:'Execution provenance does not approve comparative report accuracy; independent factual review is required.'};
    fs.writeFileSync(evidenceFile,JSON.stringify(result,null,2));state.status=result.status;save();
    await page.screenshot({path:root+'/docs/evidence/phase14-trial-'+trial+'.png',fullPage:true});
    console.log(JSON.stringify({event:result.status,trial,task_id:task.id,identifier:task.identifier,children:task.children.map(c=>({id:c.id,identifier:c.identifier}))}));
  } catch(error) {
    state.status='test_failed';state.error=safeError(error);save();
    await page.screenshot({path:root+'/.runtime/phase14-trial-'+trial+'-failure.png',fullPage:true}).catch(()=>{});
    throw error;
  } finally {await browser.close();}
})().catch(error=>{console.error(safeError(error));process.exitCode=1;});
