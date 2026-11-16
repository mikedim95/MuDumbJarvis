/* CSI acceptance against real authenticated Paperclip projections.
 * Default mode performs GETs only. --live submits ONE explicitly authorized
 * CEO demo; a durable intent/receipt prevents accidental duplicate work.
 * --verify-only observes that existing demo without submitting again.
 * Adversarial/network fixtures below exist only in this headless browser and
 * are explicitly distinguished from native task/execution evidence.
 */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');

const root='/workspace',base='http://localhost:8765';
const completed='69c12f12-4670-46de-85a2-695437e80255';
const blocked='f79972eb-c989-4845-bafa-7bd4e11a0eef';
const receipt=root+'/.runtime/csi-demo-task.json';
const output=root+'/docs/evidence';
const panels=['identity','files','warning','log','graph','timeline','network','metadata','decryption','agent'];
const objective='CSI popup demo: use paperclip_context and local_ollama_models to retrieve the actual installed model names and sizes. Work yourself, without hiring or delegation. Produce a concise technical inventory report with exact name, size_bytes and size_gib for every installed model, data sources and limits. Publish csi-demo-inventory.md with publish_artifact and finish with the real results. Do not benchmark, change configuration, perform host commands or external actions.';
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const live=process.argv.includes('--live'),verify=process.argv.includes('--verify-only');
const variant=live||verify?'live':'readonly';
const windowSelector=id=>`[data-csi-window="${id}"]`;

function saveJSON(path,value,privateFile=false){
 fs.writeFileSync(path,JSON.stringify(value,null,2)+'\n',privateFile?{mode:0o600}:undefined);
}
function safeError(error){
 let value=String(error.message||error).split('Call log:')[0].trim();
 if(process.env.JARVIS_HUD_TOKEN)value=value.replaceAll(process.env.JARVIS_HUD_TOKEN,'[REDACTED]');
 return value;
}
async function main(){
 assert(!(live&&verify),'Choose --live or --verify-only, not both');
 if(live&&fs.existsSync(receipt))throw new Error('CSI demo already has a durable intent/receipt; use --verify-only. Never submit a replacement automatically.');
 if(verify&&!fs.existsSync(receipt))throw new Error('No CSI demo receipt exists; nothing to observe.');
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}});
 const errors=[],mutations=[],polls=[];
 page.on('pageerror',error=>errors.push(safeError(error)));
 page.on('request',request=>{
  const url=new URL(request.url());
  if(request.method()!=='GET'&&/^\/api\/(tasks|agents|approvals|chat)(\/|$)/.test(url.pathname))mutations.push({method:request.method(),path:url.pathname});
  if(request.method()==='GET'&&/^\/api\/tasks\/[^/]+\/events$/.test(url.pathname))polls.push({path:url.pathname,at:Date.now()});
 });
 async function api(path){const response=await page.request.get(base+'/api/'+path);assert.equal(response.status(),200,path);return response.json();}
 async function settle(){
  await page.evaluate(()=>{document.getElementById('boot')?.classList.add('done');document.body.classList.remove('booting');document.body.classList.add('booted');});
  await page.waitForTimeout(300);
 }
 async function launch(){
  if(!await page.locator('#csiWorkspace').isVisible())await page.locator('#csiLaunch').click();
  await page.locator('#csiWorkspace').waitFor({state:'visible'});
 }
 async function selectCase(id){
  await launch();
  await page.waitForFunction(value=>Array.from(document.querySelector('#csiCaseSelect')?.options||[]).some(option=>option.value===value),id);
  await page.locator('#csiCaseSelect').selectOption(id);
  await page.waitForFunction(value=>document.querySelector('#csiCaseSelect')?.value===value,id);
  const snapshot=await api('tasks/'+id+'/events');
  assert.equal(snapshot.task_id,id);assert.equal(snapshot.source,'Paperclip');
  await page.waitForTimeout(800);
  return snapshot;
 }
 async function openPanel(id){
  await page.locator(`[data-csi-open="${id}"]`).first().click();
  await page.locator(windowSelector(id)).waitFor({state:'visible'});
  await page.waitForTimeout(220);
  return page.locator(windowSelector(id));
 }
 async function closePanel(id,minimize=false){
  const panel=await openPanel(id);
  const hook=panel.locator(`[data-csi-${minimize?'minimize':'close'}="${id}"]`);
  if(await hook.count())await hook.click();
  else await panel.getByRole('button',{name:new RegExp('^'+(minimize?'Minimize':'Close')+' ')}).click();
  await panel.waitFor({state:'hidden'});
 }
 async function artifactCheck(id,name){
  const mon=await api('tasks/'+id+'/monitor');
  const artifact=mon.artifacts.find(item=>item.originalFilename===name);assert(artifact,'Actual report attachment is required');
  const response=await page.request.get(base+'/api/tasks/'+id+'/artifacts/'+artifact.id);assert.equal(response.status(),200);
  const content=await response.body();assert.equal(sha(content),artifact.sha256);
  return {id:artifact.id,name,sha256:artifact.sha256,bytes:content.length};
 }
 try{
  assert.equal((await page.request.get(base+'/api/tasks/'+completed+'/events')).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
  await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
  await settle();
  const initialRoster=(await api('agents')).agents.map(a=>({id:a.id,status:a.status}));
  const first=await selectCase(completed);
  assert(first.events.length>0&&first.snapshot_id,'Real native events are required');
  assert(first.events.every(event=>event.id&&event.type&&event.source_ref?.issue_id),'Events must be traceable');
  const repeated=await api('tasks/'+completed+'/events');
  assert.deepEqual(repeated.events.map(e=>e.id),first.events.map(e=>e.id),'Unchanged native records need stable event IDs');
  const checks={auth_required:true,real_event_source:true,stable_event_ids:true};
  let taskId=completed,artifact;

  if(live||verify){
   if(live){
    // Record intent before clicking. If the browser loses the create response,
    // --verify-only can find the unique objective in native history; it never
    // creates another task to compensate for an uncertain response.
    saveJSON(receipt,{state:'intent',objective,created_at:new Date().toISOString()},true);
    await page.route('**/api/tasks',async route=>{
     if(route.request().method()==='POST'){
      const body=route.request().postDataJSON();
      assert.equal(body.objective,true,'CSI composer must submit a CEO-managed objective');
      assert.equal(body.input,objective);
      const intent=JSON.parse(fs.readFileSync(receipt));
      saveJSON(receipt,{...intent,request_id:body.request_id},true);
     }
     await route.continue();
    });
    await page.locator('#csiObjectiveInput').fill(objective);
    const created=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/tasks');
    await page.locator('#csiObjectiveSend').click();
    const response=await created;assert(response.ok(),'HUD must accept the actual objective');
    const task=await response.json();taskId=task.id;
    const intent=JSON.parse(fs.readFileSync(receipt));
    saveJSON(receipt,{...intent,...task,state:'submitted'},true);
    await page.unroute('**/api/tasks');
    console.log(JSON.stringify({event:'csi_objective_submitted',id:taskId,identifier:task.identifier}));
   }else{
    const existing=JSON.parse(fs.readFileSync(receipt));taskId=existing.id;
    if(!taskId){
     const matches=(await api('tasks')).tasks.filter(t=>t.description===existing.objective);
     assert.equal(matches.length,1,'Uncertain submission requires exactly one matching native objective; do not retry automatically');
     taskId=matches[0].id;saveJSON(receipt,{...existing,...matches[0],state:'recovered_native_receipt'},true);
    }
   }
   await selectCase(taskId);
   const statuses=new Set(),eventIds=new Set();let current;
   for(let i=0;i<120;i++){
    const snapshot=await api('tasks/'+taskId+'/events');
    current=snapshot.task;statuses.add(current.status);
    snapshot.events.forEach(event=>eventIds.add(event.id));
    if(['done','blocked','cancelled'].includes(current.status))break;
    if(i%10===0)console.log(JSON.stringify({event:'csi_observed',id:taskId,status:current.status,native_events:eventIds.size}));
    await page.waitForTimeout(3000);
   }
   assert.equal(current.status,'done','A real failed/blocked runtime must not count as completed');
   artifact=await artifactCheck(taskId,'csi-demo-inventory.md');
   await openPanel('agent');
   await page.waitForFunction(()=>Boolean(document.getElementById('csiAgentResponse')?.textContent.trim()));
   const final=await api('tasks/'+taskId+'/events');
   assert(final.events.some(e=>e.type==='evidence.file_recovered'),'Real artifact discovery must become a backend event');
   assert(final.events.some(e=>e.type==='task.progress'),'Actual task status must drive progress');
   assert(final.graph.nodes.some(n=>n.id.includes(artifact.id)),'Native artifact must be represented in the relationship graph');
   const published=final.events.filter(e=>e.provenance==='agent_summary'&&e.data?.text).at(-1)?.data.text;
   assert(published&&published.length>30,'The real agent must publish a substantive result');
   await page.waitForFunction(text=>document.querySelector('#csiAgentResponse pre')?.textContent===text,published);
   assert.equal(mutations.filter(m=>m.method==='POST'&&m.path==='/api/tasks').length,live?1:0);
   checks.actual_runtime_completed=true;checks.published_response_visible=true;checks.native_statuses_observed=[...statuses];checks.native_event_count=eventIds.size;
   checks.created_once=live;checks.existing_receipt_only=verify;
  }else{
   for(const id of panels)await openPanel(id);
   const localVoices=await page.evaluate(()=>Array.from(window.speechSynthesis?.getVoices()||[]).filter(v=>v.localService===true).length);
   if(!localVoices){
    const channel=await openPanel('agent');
    assert(await channel.getByRole('button',{name:/READ REPLY/i}).isDisabled());
    assert.match(await channel.innerText(),/No local device voice is available/i);
    checks.missing_local_voice_honest=true;
   }
   await openPanel('identity');
   assert.match(await page.locator(windowSelector('identity')).innerText(),/JARVIS|CEO|employee|agent/i);
   const files=await openPanel('files');
   artifact=await artifactCheck(completed,'codex-demo-report.md');
   assert(await files.locator(`a[href*="${artifact.id}"]`).count(),'Files window must link the real persisted report');
   assert.match(await files.innerText(),/Paperclip|native|artifact|recorded|upload/i);
   await openPanel('graph');await page.locator(windowSelector('graph')+' .react-flow').waitFor({state:'visible'});
   await openPanel('log');await page.locator(windowSelector('log')+' .xterm').waitFor({state:'visible'});
   await openPanel('timeline');await page.locator(windowSelector('timeline')+' .vis-timeline').waitFor({state:'visible'});
   checks.requested_libraries_mounted=true;
   for(const id of ['network','decryption']){
    const pane=await openPanel(id);
    if(!first.events.some(e=>e.type.startsWith(id==='network'?'network.':'decryption.')))
     assert.match(await pane.innerText(),/no verified|no recorded|not reported|awaiting verified|waiting for verified|no .*available/i,'Missing discoveries must not become invented activity');
   }
   const identity=await openPanel('identity');
   const before=await identity.boundingBox(),handle=identity.locator('.csi-window-handle');
   const box=await handle.boundingBox();assert(box);
   await page.mouse.move(box.x+80,box.y+15);await page.mouse.down();
   await page.mouse.move(box.x+190,box.y+65,{steps:12});await page.mouse.up();await page.waitForTimeout(300);
   const dragged=await identity.boundingBox();assert(dragged.x>before.x+40||dragged.y>before.y+20,'Titlebar must actually drag the window');
   const shell=identity.locator('xpath=..');
   const resize=shell.locator(`[data-csi-resize="identity"], [style*="se-resize"], [style*="nwse-resize"]`).last();
   const corner=await resize.boundingBox();assert(corner,'A real resize handle is required');
   await page.mouse.move(corner.x+corner.width/2,corner.y+corner.height/2);await page.mouse.down();
   await page.mouse.move(corner.x+corner.width/2+75,corner.y+corner.height/2+40,{steps:10});await page.mouse.up();await page.waitForTimeout(300);
   const resized=await identity.boundingBox();assert(resized.width>dragged.width+20||resized.height>dragged.height+15,'Resize handle must change panel size');
   assert.equal(await identity.getAttribute('data-focused'),'true');checks.drag_resize_focus=true;
   await closePanel('log',true);await openPanel('log');checks.minimize_restore=true;
   await closePanel('metadata');
   await page.reload({waitUntil:'domcontentloaded'});await settle();await launch();await selectCase(completed);
   await page.locator(windowSelector('identity')).waitFor({state:'visible'});
   const restored=await page.locator(windowSelector('identity')).boundingBox();
   for(const key of ['x','y','width','height'])assert(Math.abs(restored[key]-resized[key])<5,'Saved geometry differs after refresh: '+key);
   assert.equal(await page.locator(windowSelector('metadata')).count(),0,'User-closed panel must stay closed after refresh');
   await openPanel('metadata');checks.geometry_and_close_state_after_refresh=true;
   const warning=await selectCase(blocked);
   assert(warning.events.some(e=>['analysis.warning','task.failed'].includes(e.type)),'Old blocked objective needs an actual native warning');
   await page.locator(windowSelector('warning')).waitFor({state:'visible'});
   assert((await page.locator(windowSelector('warning')).innerText()).length>40);checks.real_failure_visible=true;
   await selectCase(completed);

   // Browser-only hostile label: it is never written to Paperclip or reported
   // as an actual discovered node. React must render its bytes as plain text.
   const probe='<img src=x onerror="window.__csiXss=1">';
   await page.evaluate(()=>{window.__csiXss=0;});
   await page.route('**/api/tasks/'+completed+'/events',async route=>{
    const data=structuredClone(first);
    data.snapshot_id='browser-only-xss-probe';
    data.graph.nodes.push({id:'browser-only-hostile-label',kind:'task',label:probe,status:'test fixture'});
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
   });
   await openPanel('graph');
   await page.waitForFunction(text=>document.querySelector('[data-csi-window="graph"]')?.textContent.includes(text),probe,{timeout:20000});
   assert.equal(await page.evaluate(()=>window.__csiXss),0);
   assert.equal(await page.locator(windowSelector('graph')+' img[onerror]').count(),0);
   await page.unroute('**/api/tasks/'+completed+'/events');checks.browser_only_xss_fixture_safe=true;
   await page.route('**/api/tasks/'+completed+'/events',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Browser-only controlled event-feed outage'})}));
   await page.waitForFunction(()=>/503|unavailable|failed|stale|offline|outage|disconnected/i.test(document.getElementById('csiConnection')?.textContent||''),null,{timeout:20000});
   await page.unroute('**/api/tasks/'+completed+'/events');checks.browser_only_outage_visible=true;
   await page.reload({waitUntil:'domcontentloaded'});await settle();await launch();await selectCase(completed);
   await page.emulateMedia({reducedMotion:'reduce'});await openPanel('identity');
   assert.equal(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches),true);
   checks.reduced_motion=true;
   await page.screenshot({path:output+'/csi-windows-readonly-desktop.png',fullPage:true});
   await page.setViewportSize({width:393,height:852});await page.waitForTimeout(400);
   for(const id of panels){
    const pane=await openPanel(id),bounds=await pane.boundingBox();assert(bounds);
    assert(bounds.x>=-1&&bounds.y>=-1&&bounds.x+bounds.width<=394&&bounds.y+bounds.height<=853,'Panel escapes mobile viewport: '+id);
   }
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile document overflows horizontally');
   await page.screenshot({path:output+'/csi-windows-readonly-mobile.png',fullPage:true});checks.mobile_bounds=true;
   assert.deepEqual(mutations,[],'Read-only acceptance must never mutate native tasks or invoke an agent');
  }

  await page.reload({waitUntil:'domcontentloaded'});await settle();await launch();
  const finalSnapshot=await selectCase(taskId);
  assert.equal(finalSnapshot.task.status,'done');
  assert.equal((await artifactCheck(taskId,artifact.name)).sha256,artifact.sha256);
  const finalRoster=(await api('agents')).agents.map(a=>({id:a.id,status:a.status}));
  assert.deepEqual(finalRoster.map(a=>a.id).sort(),initialRoster.map(a=>a.id).sort(),'UI must not hire employees');
  assert(finalRoster.filter(a=>initialRoster.find(p=>p.id===a.id)?.status==='paused').every(a=>a.status==='paused'),'Paused employees must remain paused');
  assert.deepEqual(errors,[]);
  checks.history_after_refresh=true;checks.artifact_hash_verified=true;checks.workers_remain_paused=true;
  if(live||verify){
   await openPanel('agent');
   await page.reload({waitUntil:'domcontentloaded'});await settle();await launch();await selectCase(taskId);
   await page.locator(windowSelector('agent')).waitFor({state:'visible'});
   const title=await page.locator(windowSelector('agent')+' .csi-window-handle').boundingBox();
   const front=await page.evaluate(point=>document.elementFromPoint(point.x,point.y)?.closest('[data-csi-window]')?.dataset.csiWindow,
    {x:title.x+Math.min(140,title.width/2),y:title.y+20});
   assert.equal(front,'agent','Restored focused agent window must remain in front');
   checks.focus_restored_in_front=true;
   await page.screenshot({path:output+'/csi-windows-live-desktop.png',fullPage:true});
  }
  const previousPath=output+'/csi-windows-'+variant+'.json';
  const previous=verify&&fs.existsSync(previousPath)?JSON.parse(fs.readFileSync(previousPath)):{};
  if(verify){
   checks.created_once=!!previous.checks?.created_once||checks.created_once;
   checks.native_statuses_observed=[...new Set([...(previous.checks?.native_statuses_observed||[]),...(checks.native_statuses_observed||[])])];
   checks.native_event_count=Math.max(previous.checks?.native_event_count||0,checks.native_event_count||0);
  }
  const result={status:'passed',checked_at:new Date().toISOString(),variant,verification_only:verify,
   task_id:taskId,identifier:finalSnapshot.task.identifier,artifact,checks:{...(previous.checks||{}),...checks},
   native_event_count:finalSnapshot.events.length,native_event_types:[...new Set(finalSnapshot.events.map(e=>e.type))],
   event_poll_requests:polls.length,backend_mutations:mutations,page_errors:errors,
   controlled_fixtures:live||verify?[]:['Headless-browser-only hostile graph label; never persisted as a real finding','Headless-browser-only HTTP 503; never a fabricated native task failure'],
   inference_requested:live,execution_verification:live||verify?'Correlate this task with native Paperclip run, Hermes provider trace, signed tool output and persisted artifact; UI rendering alone is not execution proof.':'No inference or new task requested.'};
  if(live)saveJSON(output+'/csi-windows-initial-live.json',result);
  saveJSON(previousPath,result);console.log(JSON.stringify(result));
 }catch(error){
  // Failures stay private: diagnostics may include the user's real case data.
  // Never print the DOM, screenshot, cookies, access code, or full call log.
  const directory=root+'/.runtime/csi-browser-failure-'+variant+'-'+Date.now();
  try{
   fs.mkdirSync(directory,{recursive:true,mode:0o700});fs.chmodSync(directory,0o700);
   const details=await page.evaluate(()=>({
    location:location.pathname,
    connection:document.getElementById('csiConnection')?.textContent,
    case_id:document.getElementById('csiCaseSelect')?.value,
    viewport:{width:innerWidth,height:innerHeight},
    windows:Array.from(document.querySelectorAll('[data-csi-window]')).map(node=>{
     const r=node.getBoundingClientRect(),shell=node.parentElement,style=getComputedStyle(shell);
     return {id:node.dataset.csiWindow,focused:node.dataset.focused,
      bounds:{x:r.x,y:r.y,width:r.width,height:r.height},z_index:style.zIndex,
      visibility:style.visibility,pointer_events:style.pointerEvents};
    })
   })).catch(()=>({page_unavailable:true}));
   saveJSON(directory+'/diagnostic.json',{error:safeError(error),details,page_errors:errors,
    backend_mutations:mutations,event_poll_requests:polls},true);
   const html=await page.content().catch(()=>'Page DOM unavailable');
   fs.writeFileSync(directory+'/page.html',html.replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'),{mode:0o600});
   await page.screenshot({path:directory+'/page.png',fullPage:true,timeout:10000}).then(()=>fs.chmodSync(directory+'/page.png',0o600)).catch(()=>{});
   console.error('Private CSI failure diagnostics: '+directory);
  }catch{}
  throw error;
 }finally{await browser.close();}
}
main().catch(error=>{console.error(safeError(error));process.exitCode=1;});
