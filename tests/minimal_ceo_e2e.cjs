/* One genuine Paperclip objective through the default minimal @ceo input.
 * A durable intent/receipt prevents duplicate creation on later invocations.
 * This test is live when no receipt exists; --verify-only never submits.
 */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root='/workspace',base='http://localhost:8765';
const receiptPath=root+'/.runtime/minimal-ceo-task.json';
const output=root+'/docs/evidence/minimal-ceo-hud.json';
const objective='Minimal AI CEO demo: use paperclip_context and local_ollama_models to retrieve the actual installed model names and sizes. Work yourself without hiring or delegation. Publish minimal-ceo-inventory.md using publish_artifact, with exact name, size_bytes and size_gib for every returned model, data sources and limits. Finish with the real inventory result. Do not benchmark, change configuration, perform host commands, external actions or resume paused workers.';
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function save(path,data,privateFile=false){fs.writeFileSync(path,JSON.stringify(data,null,2)+'\n',privateFile?{mode:0o600}:undefined);}
async function main(){
 const explicitVerify=process.argv.includes('--verify-only'),exists=fs.existsSync(receiptPath);
 if(explicitVerify&&!exists)throw new Error('No minimal CEO receipt exists; verification cannot create an objective.');
 const verify=explicitVerify||exists;
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[],posts=[],eventReads=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{
  const path=new URL(r.url()).pathname;
  if(r.method()==='POST'&&path.startsWith('/api/'))posts.push(path);
  if(r.method()==='GET'&&/\/api\/tasks\/[^/]+\/events$/.test(path))eventReads.push(path);
 });
 await page.addInitScript(()=>{localStorage.setItem('jarvis-command-mode','objective');localStorage.setItem('jarvis-csi-open','true');});
 async function api(path){
  let r;
  for(let attempt=0;attempt<3;attempt++){
   try{r=await page.request.get(base+'/api/'+path,{timeout:30000});break;}
   catch(error){if(attempt===2)throw error;await page.waitForTimeout(500);}
  }
  assert.equal(r.status(),200,path);return r.json();
 }
 async function minimal(){
  assert(await page.locator('body').evaluate(el=>el.classList.contains('ai-minimal')));
  assert.equal(await page.locator('#commandMode').inputValue(),'chat');
  assert.equal((await page.locator('#sendBtn').innerText()).trim(),'SEND');
  for(const selector of ['#commandModes','#taskPanel','#clearBtn','#csiLaunch'])assert(!await page.locator(selector).isVisible(),selector+' must stay out of the default AI screen');
  assert.equal(await page.locator('#csiWorkspace').count(),0);
  const buttons=await page.locator('#grid button').evaluateAll(nodes=>nodes.filter(el=>el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden').map(el=>el.id));
  assert.deepEqual(buttons,['sendBtn'],'No operator-panel launch controls belong on the default AI screen');
 }
 async function popupHas(values,timeout=30000){
  await page.waitForFunction(needles=>{
   const root=document.querySelector('[data-csi-auto]');
   if(!root||!root.getClientRects().length)return false;
   const text=root.innerText;return needles.every(v=>text.includes(v));
  },values,{timeout});
 }
 try{
  assert.equal((await page.request.get(base+'/api/tasks')).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
  await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisTasks&&document.getElementById('aiProvider')?.textContent.includes('gpt-6.1-sol'));
  await minimal();
  const agents=await api('agents'),ceo=agents.agents.find(a=>a.id===agents.ceo_id);assert(ceo&&ceo.role==='ceo');
  const rosterBefore=agents.agents.map(a=>({id:a.id,status:a.status}));
  const before=(await api('tasks')).tasks.map(t=>t.id).sort();
  let task;
  if(verify){
   task=JSON.parse(fs.readFileSync(receiptPath));
   if(!task.id){
    const matches=(await api('tasks')).tasks.filter(t=>t.description===task.objective);
    assert.equal(matches.length,1,'Uncertain submission requires one native match. Never submit replacement work automatically.');
    task={...task,...matches[0],state:'recovered-native-receipt'};save(receiptPath,task,true);
   }
   // A fresh browser has no prior view preferences. Restore only the native
   // task reference; the panel must retrieve all identity/results from APIs.
   await page.evaluate(taskId=>{
    const key='jarvis-agent-popups-v1';let previous={};
    try{previous=JSON.parse(localStorage.getItem(key)||'{}')||{};}catch{}
    localStorage.setItem(key,JSON.stringify({version:1,rects:previous.rects||{},closed:[],seen:[],
     objective:taskId,open:[{taskId,panel:'agent'}]}));
   },task.id);
   await page.reload({waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>window.JarvisTasks&&document.getElementById('aiProvider')?.textContent.includes('gpt-6.1-sol'));
   await minimal();
  }else{
   save(receiptPath,{state:'intent',objective,created_at:new Date().toISOString()},true);
   await page.route('**/api/tasks',async route=>{
    if(route.request().method()==='POST'){
     const body=route.request().postDataJSON();assert.equal(body.objective,true);assert.equal(body.input,objective);
     const intent=JSON.parse(fs.readFileSync(receiptPath));save(receiptPath,{...intent,request_id:body.request_id},true);
    }
    await route.continue();
   });
   await page.locator('#chatInput').fill('@ceo '+objective);
   const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/tasks',{timeout:30000});
   await page.locator('#sendBtn').click();const response=await pending;
   assert(response.ok(),'The minimal CEO input must create a real Paperclip objective');
   const created=await response.json(),intent=JSON.parse(fs.readFileSync(receiptPath));
   task={...intent,...created,state:'submitted'};save(receiptPath,task,true);
   await page.unroute('**/api/tasks');
   assert.equal(task.assigneeAgentId,ceo.id);assert(!task.parentId,'Exactly one top-level objective is required');
   console.log(JSON.stringify({event:'minimal_ceo_submitted',id:task.id,identifier:task.identifier}));
   await popupHas([task.identifier,ceo.name]);
   await minimal();
  }
  const seenStatuses=new Set(),seenEvents=new Set();let snapshot,detail,observedPartialTool=false;
  const deadline=Date.now()+240000;
  while(Date.now()<deadline){
   snapshot=await api('tasks/'+task.id+'/events');detail=await api('tasks/'+task.id);
   assert.equal(snapshot.task_id,task.id);assert.equal(detail.assigneeAgentId,ceo.id);assert(!detail.parentId);
   seenStatuses.add(detail.status);snapshot.events.forEach(e=>seenEvents.add(e.id));
   if(detail.status!=='done'&&snapshot.events.some(e=>e.provenance==='verified_tool_output'&&e.data?.tool==='local_ollama_models'))observedPartialTool=true;
   if(['done','blocked','cancelled'].includes(detail.status))break;
   console.log(JSON.stringify({event:'minimal_ceo_progress',id:task.id,status:detail.status,native_events:snapshot.events.length}));
   await page.waitForTimeout(3000);
  }
  assert.equal(detail.status,'done','A blocked/failed objective is not completed work');
  assert.equal((detail.children||[]).length,0,'This inventory objective needs no employees or delegation');
  const runIds=(detail.runs||[]).map(r=>r.runId);assert(runIds.length>=1,'A real native execution is required');
  for(let i=0;i<10&&!detail.runs.some(r=>r.status==='succeeded');i++){await page.waitForTimeout(3000);detail=await api('tasks/'+task.id);}
  assert(detail.runs.some(r=>r.status==='succeeded'),'Native execution must actually succeed');
  const observed=snapshot.events.find(e=>e.provenance==='verified_tool_output'&&e.data?.tool==='local_ollama_models'&&e.source_ref?.agent_id===ceo.id);
  assert(observed,'A signed real inventory tool event must be visible through JARVIS');
  assert(runIds.includes(observed.source_ref.run_id),'Tool evidence must belong to the same native task execution');
  const models=observed.data.result;assert(Array.isArray(models)&&models.length>0);
  const artifact=snapshot.artifacts.find(a=>a.originalFilename==='minimal-ceo-inventory.md');assert(artifact,'Native report artifact is required');
  const downloaded=await page.request.get(base+'/api/tasks/'+task.id+'/artifacts/'+artifact.id);assert.equal(downloaded.status(),200);
  const bytes=await downloaded.body();assert.equal(sha(bytes),artifact.sha256);
  assert(models.every(m=>bytes.toString().includes(m.name)&&bytes.toString().includes(String(m.size_bytes))),'Report must contain the actual retrieved inventory');
  if(verify){
   // Restored view preferences contain references only, never task findings.
   // Never emit a fake submission event or create a second objective.
   await page.waitForTimeout(3500);
  }
  await popupHas([task.identifier,ceo.name,...models.map(m=>m.name)],30000);
  await page.waitForFunction(id=>window.JarvisTaskVisualState?.identifier===id&&
   window.JarvisTaskVisualState?.status==='done'&&!window.JarvisTaskVisualState?.active,task.identifier);
  await minimal();
  const after=(await api('tasks')).tasks.map(t=>t.id).sort();
  const added=after.filter(id=>!before.includes(id));
  assert.deepEqual(added,verify?[]:[task.id],'Only the requested top-level task may be created');
  assert.equal(posts.filter(p=>p==='/api/tasks').length,verify?0:1);
  assert.equal(posts.filter(p=>p==='/api/chat').length,0,'@ceo must not invoke the direct chat runtime');
  const rosterAfter=(await api('agents')).agents;
  assert.deepEqual(rosterAfter.map(a=>a.id).sort(),rosterBefore.map(a=>a.id).sort());
  assert(rosterAfter.filter(a=>rosterBefore.find(b=>a.id===b.id)?.status==='paused').every(a=>a.status==='paused'));
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.JarvisTasks&&document.body.classList.contains('ai-minimal'));
  await popupHas([task.identifier,ceo.name,...models.map(m=>m.name)],30000);
  assert.equal((await api('tasks/'+task.id)).status,'done');await minimal();assert.deepEqual(errors,[]);
  await page.screenshot({path:root+'/docs/evidence/minimal-ceo-hud.png',fullPage:true});
  const previous=verify&&fs.existsSync(output)?JSON.parse(fs.readFileSync(output)):{};
  const result={status:'passed',checked_at:new Date().toISOString(),verification_only:verify,
   task_id:task.id,identifier:task.identifier,assignee_agent_id:ceo.id,assignee_name:ceo.name,top_level_objective:true,
   request_id:task.request_id,submitted_via:'Default minimal chat input with @ceo prefix',
   task_statuses_observed:[...new Set([...(previous.task_statuses_observed||[]),...seenStatuses])],
   native_run_ids:runIds,verified_tool_event_id:observed.id,verified_tool_run_id:observed.source_ref.run_id,
   models_retrieved:models.map(m=>({name:m.name,size_bytes:m.size_bytes,size_gib:m.size_gib})),
   artifact:{id:artifact.id,sha256:artifact.sha256,bytes:bytes.length},
   genuine_partial_tool_observed_before_completion:observedPartialTool||!!previous.genuine_partial_tool_observed_before_completion,
   automatic_agent_identity_visible:true,actual_result_visible:true,popup_and_task_restored_after_refresh:true,
   default_mode_remained_chat:true,send_label_remained_send:true,operator_controls_visible:false,
   created_once:!verify||!!previous.created_once,task_posts_this_check:posts.filter(p=>p==='/api/tasks').length,
   direct_chat_posts:0,new_employees:0,paused_workers_unchanged:true,events_observed:Math.max(seenEvents.size,previous.events_observed||0),
   event_poll_requests:eventReads.length,browser_errors:errors,
   execution_verification:'Native task, succeeded run, signed tool event and artifact correlated. Actual Codex provider trace must be independently checked in the Hermes runtime log.'};
  save(output,result);console.log(JSON.stringify(result));
 }catch(error){await page.screenshot({path:root+'/.runtime/minimal-ceo-failure.png',fullPage:true}).catch(()=>{});throw error;}
 finally{await browser.close();}
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
