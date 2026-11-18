/* Operator negative acceptance fixture. No hire/agent/runtime is created. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const root='/workspace',url='http://localhost:8765';
const file=root+'/.runtime/phase14-hire-rejection.json';
const state=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{nonce:crypto.randomUUID()};
const save=()=>{fs.writeFileSync(file,JSON.stringify(state,null,2),{mode:0o600});fs.chmodSync(file,0o600);};
function safeError(e) {
  let value=String(e.message||e).split('Call log:')[0].trim();
  for(const [k,v] of Object.entries(process.env)) if(/KEY|TOKEN|PASSWORD|SECRET/.test(k)&&v.length>=12) value=value.replaceAll(v,'[REDACTED]');
  return value;
}
async function board(method,path,data) {
  const r=await fetch('http://127.0.0.1:3100/api/'+path,{method,
    headers:{Authorization:'Bearer '+process.env.PAPERCLIP_API_KEY,'Content-Type':'application/json'},
    body:data?JSON.stringify(data):undefined,signal:AbortSignal.timeout(25000)});
  assert(r.ok,`Native ${method} ${path}: ${r.status}`);return r.json();
}
(async()=>{
  const company=process.env.PAPERCLIP_COMPANY_ID;
  const roster=await board('GET','companies/'+company+'/agents');
  const before=roster.map(a=>a.id).sort();
  state.roster_before ||= before;assert.deepEqual(before,state.roster_before);save();
  if(!state.task_id) {
    const t=await board('POST','companies/'+company+'/issues',{
      title:'Phase 14: reject an unnecessary employee proposal',
      description:'Operator negative test: native hire proposal only, unassigned backlog. Reject it through the authenticated HUD. Do not create an employee, invoke a runtime or execute tools.',
      projectId:process.env.PAPERCLIP_PROJECT_ID,status:'backlog',workspaceSelection:{kind:'task_directory'},
      idempotencyKey:'jarvis:phase14:hire-rejection:'+state.nonce,allowDuplicate:true});
    state.task_id=t.id;state.identifier=t.identifier;save();
  }
  if(!state.approval_id) {
    const a=await board('POST','companies/'+company+'/approvals',{
      type:'hire_agent',issueIds:[state.task_id],payload:{
        name:'REJECT ONLY: unnecessary Documentation specialist',role:'general',
        title:'Operator negative hire fixture',reportsTo:process.env.PAPERCLIP_CEO_AGENT_ID,
        adapterType:'hermes_gateway',adapterConfig:{},
        runtimeConfig:{heartbeat:{enabled:false,wakeOnAssignment:false,wakeOnDemand:false,maxConcurrentRuns:1}},
        summary:'Operator-authored negative fixture, not a CEO request. Research, Software and CEO already cover the objective. Reject this unnecessary hire. No employee record or runtime exists.',
        metadata:{jarvis:{test_fixture:true,provisioned:false,source_issue_id:state.task_id}}}});
    state.approval_id=a.id;save();
  }
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();await page.goto(url+'/hud/',{waitUntil:'domcontentloaded'});
    await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
    await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
    await page.waitForFunction(()=>document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    const approval=await board('GET','approvals/'+state.approval_id);
    if(approval.status==='pending') {
      await page.locator('#approvalMonitor').evaluate(el=>{el.open=true;});
      await page.locator('#approvalList .monitor-card').filter({hasText:state.approval_id}).getByRole('button',{name:'Review request'}).click();
      await page.getByRole('textbox',{name:'Approval decision note'}).fill('Operator negative acceptance test: reject the unnecessary hire. Existing employees cover this objective. No new employee or runtime is authorized.');
      const responsePromise=page.waitForResponse(r=>r.url()===url+'/api/approvals/'+state.approval_id+'/decision'&&r.request().method()==='POST');
      await page.getByRole('button',{name:'Reject request',exact:true}).click();
      const r=await responsePromise;assert.equal(r.status(),200);
    }
    const after=await board('GET','approvals/'+state.approval_id);assert.equal(after.status,'rejected');
    assert(!after.payload.agentId,'The negative fixture must not create even an inert employee');
    assert.deepEqual((await board('GET','companies/'+company+'/agents')).map(a=>a.id).sort(),before);
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(id=>document.getElementById('approvalList').textContent.includes(id)&&document.getElementById('approvalList').textContent.includes('rejected'),state.approval_id);
    const t=await board('GET','issues/'+state.task_id);assert.equal(t.assigneeAgentId,null);assert.equal(t.executionRunId,null);
    const positive=await board('GET','approvals/80bebd62-f765-421e-bab7-9ebbf313e9df');
    assert.equal(positive.status,'approved');assert(positive.decidedByUserId,'Existing positive hire must have actual human attribution');
    const result={status:'passed',checked_at:new Date().toISOString(),
      negative_fixture:{task_id:state.task_id,identifier:state.identifier,approval_id:after.id,type:after.type,status:after.status,decisionNote:after.decisionNote,decidedAt:after.decidedAt},
      negative_source:'Automated operator-authored hire proposal and HUD rejection; not a claim of autonomous CEO hiring or a new human decision.',
      positive_human_approved_hire:{id:positive.id,status:positive.status,decidedAt:positive.decidedAt,human_attribution_present:!!positive.decidedByUserId},
      roster_unchanged:before,no_employee_created:true,no_runtime_provisioned:true,no_inference_requested:true,browser_refresh_preserved_rejection:true};
    fs.writeFileSync(root+'/docs/evidence/phase14-hire-rejection.json',JSON.stringify(result,null,2));
    state.status='passed';save();console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(e=>{console.error(safeError(e));process.exitCode=1;});
