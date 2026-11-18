/* Live, once-only workforce acceptance through the ordinary minimal AI input.
 * Private intent/nonce receipts survive browser/process failure. --verify-only
 * never submits work or a follow-up, including an uncertain previous request.
 */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root='/workspace',base='http://localhost:8765';
const receiptPath=root+'/.runtime/codex-workforce-task.json';
const output=root+'/docs/evidence/codex-workforce-hud.json';
const followupText='Give a concise executive summary of this completed readiness report, without delegating again.';
const objective=[
 'Produce one evidence-backed JARVIS workforce readiness report. Use only the four existing relevant specialists; do not hire, fire, change host configuration, resume old objectives or use internal subagents. Record a real Paperclip plan and four persistent child assignments with native dependencies.',
 'Research: retrieve the garak primary source with research_sources and publish workforce-research.md summarizing verified capabilities, source URLs and limits. This is source research, not a framework execution or efficacy claim.',
 'Software: depend on the completed Research child, read its actual published artifacts, and create a tiny offline Python module validator.py with validate_identifier(value): accept only strings of 1–32 ASCII letters/digits/underscores beginning with a letter. Create test_validator.py with two unittest tests covering valid and invalid inputs. Execute the actual tests in your isolated workspace; publish both source files and workforce-software.md with the real command, exit code and output. No package install or network access is needed.',
 'Systems: use local_ollama_models to retrieve the actual installed names and sizes. In your own isolated sandbox execute a real Python diagnostic printing JSON keys uid, platform and python_version from os.getuid(), platform.platform() and platform.python_version(). Publish workforce-systems.md with the real inventory, diagnostic output, execution evidence and limits; distinguish sandbox identity from Kali host identity.',
 'Security/QA: depend on the completed Software child, read its real published source and tests with read_worker_artifacts, and independently execute at least one unit test or Python AST/static check against those exact published bytes in your separate isolated workspace. Prefer executing the published unit tests. If using static checking, execute ast.parse on the published source, print AST_PARSE_OK only after success, and publish your check script. Publish workforce-security.md with your actual command, result, code/artifact references, sandbox scope and limitations. No external scanning or host access.',
 'JARVIS: monitor native work and dependencies, review each employee result and tool evidence, and publish workforce-readiness.md consolidating all four roles, exact installed model inventory, test outcomes and unresolved limits. Mark the objective done only after all four real child executions and artifact deliveries succeed.'
].join(' ');
const roles={researcher:{report:'workforce-research.md',tools:['research_sources']},
 engineer:{report:'workforce-software.md',tools:['read_worker_artifacts','terminal']},
 devops:{report:'workforce-systems.md',tools:['local_ollama_models','terminal']},
 security:{report:'workforce-security.md',tools:['read_worker_artifacts','terminal']}};
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function save(file,data,privateFile=false){
 fs.mkdirSync(path.dirname(file),{recursive:true});
 const temporary=file+'.tmp';fs.writeFileSync(temporary,JSON.stringify(data,null,2)+'\n',{mode:privateFile?0o600:0o644});
 fs.renameSync(temporary,file);if(privateFile)fs.chmodSync(file,0o600);
}
function publicText(value){return String(value||'').replace(/<(?:think|analysis)>[\s\S]*?(?:<\/(?:think|analysis)>|$)/gi,'')
 .split('\n').filter(line=>line.trim()!=='[JARVIS TOOL EVENT]'&&!/^\s*JARVIS_(?:EXECUTION_EVIDENCE|TOOL_EVENT|DISCOVERY_EVENT)=/.test(line)).join('\n').trim();}
function replies(detail,ceo){return (detail.comments||[]).filter(c=>c.authorAgentId===ceo&&publicText(c.body)&&
 !/^\[JARVIS CEO (?:PLAN|REVIEW|WAITING|RESULTS READY|CORRECTION)\b/.test(publicText(c.body)))
 .sort((a,b)=>(a.createdAt||'').localeCompare(b.createdAt||''));}
async function main(){
 assert(process.env.JARVIS_HUD_TOKEN,'JARVIS_HUD_TOKEN is required');
 assert(!/[\r\n]/.test(objective),'The acceptance objective must fit the single-line HUD input without normalization');
 const verifyOnly=process.argv.includes('--verify-only'),exists=fs.existsSync(receiptPath);
 if(verifyOnly&&!exists)throw new Error('No workforce intent/receipt exists. Verification cannot submit work.');
 let receipt=exists?JSON.parse(fs.readFileSync(receiptPath)):null;
 if(receipt)assert.equal(receipt.objective_sha256,sha(objective),'Receipt belongs to a different acceptance objective; inspect it, do not replace or resubmit automatically.');
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[],posts=[],eventReads=[];
 let routeFailure=null;
 const patch=value=>{receipt={...receipt,...value};save(receiptPath,receipt,true);};
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{const pathname=new URL(request.url()).pathname;
  if(request.method()==='POST'&&pathname.startsWith('/api/'))posts.push(pathname);
  if(request.method()==='GET'&&/\/api\/tasks\/[^/]+\/events$/.test(pathname))eventReads.push(pathname);
 });
 async function api(endpoint){
  let response;for(let attempt=0;attempt<3;attempt++){
   try{response=await page.request.get(base+'/api/'+endpoint,{timeout:30000});break;}
   catch(error){if(attempt===2)throw error;await page.waitForTimeout(500);}
  }
  assert.equal(response.status(),200,endpoint);return response.json();
 }
 async function minimal(){
  assert(await page.locator('body').evaluate(element=>element.classList.contains('ai-minimal')));
  assert.equal(await page.locator('#commandMode').inputValue(),'chat');
  assert.equal((await page.locator('#sendBtn').innerText()).trim(),'SEND');
  for(const selector of ['#commandModes','#taskPanel','#clearBtn','#csiLaunch'])assert(!await page.locator(selector).isVisible(),selector+' must remain hidden');
  assert.equal(await page.locator('#csiWorkspace').count(),0);
  const buttons=await page.locator('#grid button').evaluateAll(nodes=>nodes.filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden').map(e=>e.id));
  assert.deepEqual(buttons,['sendBtn'],'The main AI screen has one Send control');
 }
 async function popupHas(values){await page.waitForFunction(needles=>{
  const layer=document.querySelector('[data-csi-auto]');return layer&&layer.getClientRects().length&&needles.every(text=>layer.innerText.includes(text));
 },values,{timeout:45000});}
 async function restore(task){
  await page.evaluate(id=>{
   localStorage.setItem('jarvis-ceo-objective',id);localStorage.setItem('jarvis-task-selected',id);
   localStorage.setItem('jarvis-agent-popups-v1',JSON.stringify({version:1,rects:{},closed:[],seen:[],objective:id,open:[{taskId:id,panel:'agent'}]}));
  },task.id);
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.JarvisTasks&&window.JarvisCEOInput);await minimal();
 }
 async function waitDone(id,label,timeout=900000){
  const deadline=Date.now()+timeout,statuses=new Set();let detail,snapshot,nativeWaitingObserved=false;
  while(Date.now()<deadline){
   [detail,snapshot]=await Promise.all([api('tasks/'+id),api('tasks/'+id+'/events')]);statuses.add(detail.status);
   assert.equal(snapshot.task_id,id);assert.equal(detail.assigneeAgentId,ceo.id);assert(!detail.parentId);
   const children=detail.children||[],running=[...(detail.runs||[]),...children.flatMap(c=>c.runs||[])].filter(r=>['running','queued'].includes(r.status));
   console.log(JSON.stringify({event:label,id,identifier:detail.identifier,status:detail.status,
    children:children.map(c=>({id:c.id,identifier:c.identifier,assignee:c.assigneeAgentId,status:c.status})),native_events:snapshot.events.length,live_runs:running.length}));
   const latestUpdate=(detail.comments||[]).filter(c=>c.authorAgentId===ceo.id&&publicText(c.body))
    .sort((a,b)=>(a.createdAt||'').localeCompare(b.createdAt||'')).at(-1);
   const waiting=detail.status==='blocked'&&publicText(latestUpdate?.body).startsWith('[JARVIS CEO WAITING]')&&
    children.some(c=>['backlog','todo','in_progress','in_review'].includes(c.status));
   if(waiting){nativeWaitingObserved=true;console.log(JSON.stringify({event:'workforce_native_waiting',id,reason:'CEO yielded to persistent child work; not completion'}));}
   if(detail.status==='cancelled'||(detail.status==='blocked'&&!waiting))throw new Error(detail.identifier+' is '+detail.status+'; this is not successful completion. Inspect native errors and retry only the existing objective.');
   if(detail.status==='done'&&children.every(c=>c.status==='done')&&!running.length&&detail.runs.some(r=>r.status==='succeeded'))return {detail,snapshot,statuses:[...statuses],nativeWaitingObserved};
   await page.waitForTimeout(6000);
  }
  throw new Error(label+' exceeded its deadline; retain the native receipt and observe the same objective on rerun.');
 }
 let ceo,rosterBefore,before;
 try{
  assert.equal((await page.request.get(base+'/api/tasks')).status(),401,'Task history requires authentication');
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
  await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisTasks&&window.JarvisCEOInput);await minimal();
  const roster=await api('agents');ceo=roster.agents.find(a=>a.id===roster.ceo_id);
  assert(ceo&&ceo.name==='JARVIS'&&ceo.role==='ceo','The native JARVIS employee is the CEO');
  for(const role of Object.keys(roles))assert.equal(roster.agents.filter(a=>a.role===role&&a.lifecycleState==='ready').length,1,'One existing ready specialist for '+role);
  rosterBefore=roster.agents.map(a=>a.id).sort();before=(await api('tasks')).tasks.map(t=>t.id).sort();
  let task;
  if(receipt){
   if(!receipt.id){
    const matches=(await api('tasks')).tasks.filter(t=>t.description===objective);
    assert.equal(matches.length,1,'Uncertain root intent requires exactly one native match. Never create a replacement automatically.');
    patch({...matches[0],state:'recovered-native-root'});
   }
   task=receipt;await restore(task);
  }else{
   patch({version:1,state:'intent',objective,objective_sha256:sha(objective),created_at:new Date().toISOString(),baseline_task_ids:before});
   await page.route('**/api/tasks',async route=>{
    try{
     if(route.request().method()==='POST'){
      const body=route.request().postDataJSON();
      if(body.objective!==true||body.input!==objective)throw new Error('Root request differs from its saved single-line acceptance objective.');
      patch({request_id:body.request_id,state:'root-post-observed'});
     }
    }catch(error){
     routeFailure='Root request interception failed. The request was blocked before native submission.';
     patch({state:'root-intercept-rejected',last_error:routeFailure});await route.abort('failed').catch(()=>{});return;
    }
    await route.continue().catch(()=>{routeFailure='Root forwarding was not confirmed. Retain the saved intent and inspect the native task before retrying.';patch({last_error:routeFailure});});
   });
   await page.locator('#chatInput').fill(objective);
   const responsePromise=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/tasks',{timeout:35000});
   await page.locator('#sendBtn').click();const response=await responsePromise;
   assert(response.ok(),'Ordinary input must create the CEO objective, without @ceo');task=await response.json();patch({...task,state:'root-submitted'});
   await page.unroute('**/api/tasks');
   assert.equal(task.assigneeAgentId,ceo.id);assert(!task.parentId);
   console.log(JSON.stringify({event:'workforce_submitted',id:task.id,identifier:task.identifier}));
  }
  await popupHas([task.identifier,ceo.name]);
  const first=await waitDone(task.id,'workforce_progress');let detail=first.detail,snapshot=first.snapshot;
  assert.equal(detail.children.length,4,'Exactly four specialist assignments are required');
  const people=new Map(snapshot.agents.map(a=>[a.id,a])),childrenByRole={};
  for(const child of detail.children){
   const employee=people.get(child.assigneeAgentId);assert(employee&&roles[employee.role],'Child must use one of the four existing specialist roles');
   assert(!childrenByRole[employee.role],'A role must not receive duplicate children');childrenByRole[employee.role]=child;
  }
  assert.deepEqual(Object.keys(childrenByRole).sort(),Object.keys(roles).sort());
  for(const employee of [people.get(ceo.id),...Object.values(childrenByRole).map(c=>people.get(c.assigneeAgentId))]){
   assert.equal(employee.provider,'openai-codex');assert.equal(employee.model,'gpt-6.1-sol');
  }
  const edges=snapshot.graph.edges;
  for(const [dependent,prerequisite] of [['engineer','researcher'],['security','engineer']]){
   assert(edges.some(e=>e.source==='task:'+childrenByRole[dependent].id&&e.target==='task:'+childrenByRole[prerequisite].id&&e.label==='depends on'),dependent+' requires a real native dependency on '+prerequisite);
  }
  const artifacts=[],proofs={},workerRuns=new Set();
  async function download(artifact){
   const response=await page.request.get(base+'/api/tasks/'+artifact.issueId+'/artifacts/'+artifact.id);assert.equal(response.status(),200);
   const bytes=await response.body();assert.equal(bytes.length,artifact.byteSize);assert.equal(sha(bytes),artifact.sha256);
   artifacts.push({id:artifact.id,task_id:artifact.issueId,name:artifact.originalFilename,sha256:artifact.sha256,bytes:bytes.length,agent_id:artifact.createdByAgentId,run_id:artifact.originatingRunId});
   return bytes.toString();
  }
  for(const [role,spec] of Object.entries(roles)){
   const child=childrenByRole[role],succeeded=new Set(child.runs.filter(r=>r.status==='succeeded').map(r=>r.runId));
   assert(succeeded.size>0,role+' needs a genuinely succeeded native execution');
   const tools=snapshot.events.filter(e=>e.task_id===child.id&&e.provenance==='verified_tool_output'&&e.source_ref?.agent_id===child.assigneeAgentId&&e.data?.success===true&&succeeded.has(e.source_ref.run_id));
   for(const tool of spec.tools)assert(tools.some(e=>e.data.tool===tool),role+' lacks authenticated successful '+tool+' evidence');
   tools.forEach(e=>workerRuns.add(e.source_ref.run_id));
   proofs[role]={task_id:child.id,identifier:child.identifier,agent_id:child.assigneeAgentId,succeeded_run_ids:[...succeeded],verified_tool_events:tools.map(e=>({id:e.id,tool:e.data.tool,run_id:e.source_ref.run_id}))};
   const report=snapshot.artifacts.find(a=>a.issueId===child.id&&a.originalFilename===spec.report&&a.createdByAgentId===child.assigneeAgentId&&succeeded.has(a.originatingRunId));
   assert(report,role+' must persist its actual requested report');const text=await download(report);assert(text.trim().length>150,role+' report must be substantive');
   if(role==='researcher')assert(tools.some(e=>e.data.tool==='research_sources'&&JSON.stringify(e.data.result).toLowerCase().includes('garak')),'Research must retrieve the requested primary source');
   if(role==='engineer'){
    const testExecution=tools.find(e=>e.data.tool==='terminal'&&/Ran\s+2\s+tests?[\s\S]*\bOK\b/.test(String(e.data.result?.output||'')));
    assert(testExecution,'Software must actually execute two passing tests');
    for(const filename of ['validator.py','test_validator.py']){
     const source=snapshot.artifacts.find(a=>a.issueId===child.id&&a.originalFilename===filename&&a.createdByAgentId===child.assigneeAgentId&&succeeded.has(a.originatingRunId));
     assert(source,'Software source/test bytes must be native artifacts: '+filename);await download(source);
    }
   }
   if(role==='devops'){
    const inventory=tools.find(e=>e.data.tool==='local_ollama_models');assert(Array.isArray(inventory.data.result)&&inventory.data.result.length>0);
    assert(inventory.data.result.every(m=>text.includes(m.name)&&text.includes(String(m.size_bytes))),'Systems report must contain actual model names and byte sizes');
    assert(tools.some(e=>e.data.tool==='terminal'&&/uid/i.test(String(e.data.result?.output||''))&&/platform/i.test(String(e.data.result?.output||''))),'Systems must execute real sandbox identity diagnostics');
    proofs[role].models=inventory.data.result.map(m=>({name:m.name,size_bytes:m.size_bytes}));
   }
   if(role==='security')assert(tools.some(e=>e.data.tool==='terminal'&&
    /(?:Ran\s+[1-9][0-9]*\s+tests?[\s\S]*\bOK\b|[1-9][0-9]* passed|AST_PARSE_OK)/.test(String(e.data.result?.output||''))),
    'Security must execute an actual independent passing test or AST check, not just inspect a directory');
  }
  const workerExecutionRunIds=[...new Set(snapshot.events.filter(e=>e.provenance==='verified_tool_output'&&
   detail.children.some(child=>child.id===e.task_id)).map(e=>e.source_ref?.run_id).filter(Boolean))].sort();
  const finalReport=snapshot.artifacts.find(a=>a.issueId===task.id&&a.originalFilename==='workforce-readiness.md'&&a.createdByAgentId===ceo.id);
  assert(finalReport,'CEO must publish its consolidated report');const consolidated=await download(finalReport);
  assert(proofs.devops.models.every(m=>consolidated.includes(m.name)),'CEO report must include retrieved inventory, not a generic success statement');
  const firstReplies=replies(detail,ceo.id);assert(firstReplies.length>0,'CEO must publish a result comment');
  const taskSetBeforeFollowup=(await api('tasks')).tasks.map(t=>t.id).sort(),childIds=detail.children.map(c=>c.id).sort();
  patch({state:'workforce-completed',children:proofs,initial_ceo_comment_ids:firstReplies.map(c=>c.id),worker_run_ids:workerExecutionRunIds,task_ids_before_followup:taskSetBeforeFollowup});
  if(!receipt.followup){
   assert(!verifyOnly,'No follow-up receipt exists; --verify-only cannot send one');
   patch({followup:{state:'intent',input:followupText,created_at:new Date().toISOString(),before_ceo_comment_ids:firstReplies.map(c=>c.id)}});
   await page.route('**/api/tasks/*/messages',async route=>{
    try{
     const request=route.request();if(request.method()==='POST'){
      const body=request.postDataJSON();
      if(new URL(request.url()).pathname!=='/api/tasks/'+task.id+'/messages'||body.input!==followupText)throw new Error('Follow-up request differs from its saved native objective or text.');
      patch({followup:{...receipt.followup,state:'post-observed',request_id:body.request_id}});
     }
    }catch(error){
     routeFailure='Follow-up request interception failed. The request was blocked before native submission.';
     patch({followup:{...receipt.followup,state:'intercept-rejected'},last_error:routeFailure});await route.abort('failed').catch(()=>{});return;
    }
    await route.continue().catch(()=>{routeFailure='Follow-up forwarding was not confirmed. Retain its saved nonce and inspect the native comment before retrying.';patch({last_error:routeFailure});});
   });
   await page.locator('#chatInput').fill(followupText);
   const responsePromise=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/tasks/'+task.id+'/messages',{timeout:35000});
   await page.locator('#sendBtn').click();const response=await responsePromise;assert(response.ok(),'Ordinary follow-up must address the same native objective');
   const ack=await response.json();assert.equal(ack.task.id,task.id);assert(ack.comment_id);
   patch({followup:{...receipt.followup,state:'submitted',comment_id:ack.comment_id}});await page.unroute('**/api/tasks/*/messages');
  }else if(!receipt.followup.comment_id){
   assert(receipt.followup.request_id,'An unobserved follow-up intent cannot be resubmitted automatically; inspect the retained browser state.');
   const observed=await api('tasks/'+task.id),marker='[JARVIS USER MESSAGE request_id='+receipt.followup.request_id+']\n';
   const matches=observed.comments.filter(c=>c.body===marker+followupText&&!c.authorAgentId);
   assert.equal(matches.length,1,'Uncertain follow-up must resolve to one native comment. Never submit it again automatically.');
   patch({followup:{...receipt.followup,state:'recovered-native-comment',comment_id:matches[0].id}});
  }
  const deadline=Date.now()+180000;let newReply,followSnapshot,followDetail;
  while(Date.now()<deadline){
   [followDetail,followSnapshot]=await Promise.all([api('tasks/'+task.id),api('tasks/'+task.id+'/events')]);
   const human=followDetail.comments.find(c=>c.id===receipt.followup.comment_id);assert(human,'The acknowledged native human message must persist');
   newReply=replies(followDetail,ceo.id).filter(c=>!receipt.followup.before_ceo_comment_ids.includes(c.id)&&Date.parse(c.createdAt)>=Date.parse(human.createdAt)).at(-1);
   console.log(JSON.stringify({event:'workforce_followup_progress',id:task.id,status:followDetail.status,human_comment_id:human.id,new_ceo_comment_id:newReply?.id||null}));
   if(['blocked','cancelled'].includes(followDetail.status))throw new Error('Follow-up is '+followDetail.status+'; old completion must not be accepted as its result');
   if(newReply&&followDetail.status==='done'&&!followDetail.runs.some(r=>['running','queued'].includes(r.status)))break;
   await page.waitForTimeout(3000);
  }
  assert(newReply&&followDetail.status==='done','Follow-up requires a genuinely new published CEO reply and native completion');
  const published=followSnapshot.events.find(e=>e.provenance==='agent_summary'&&e.source_ref?.comment_id===newReply.id&&e.source_ref?.agent_id===ceo.id&&e.task_id===task.id);
  assert(published,'The new CEO reply must be available in the authenticated event projection');
  assert.deepEqual(followDetail.children.map(c=>c.id).sort(),childIds,'Summary follow-up must not delegate again');
  const afterWorkerRuns=[...new Set(followSnapshot.events.filter(e=>e.provenance==='verified_tool_output'&&childIds.includes(e.task_id)).map(e=>e.source_ref?.run_id).filter(Boolean))].sort();
  assert.deepEqual(afterWorkerRuns,workerExecutionRunIds,'Summary follow-up must not execute staff again');
  assert.deepEqual((await api('tasks')).tasks.map(t=>t.id).sort(),taskSetBeforeFollowup,'Follow-up cannot create another root or child task');
  await popupHas([task.identifier,ceo.name,published.data.text.slice(0,100)]);
  await page.waitForFunction(text=>document.getElementById('feed').innerText.includes(text),published.data.text.slice(0,100),{timeout:30000});
  assert.equal(await page.evaluate(()=>window.JarvisTasks.snapshot().objectiveId),task.id);await minimal();
  patch({state:'completed',followup:{...receipt.followup,state:'completed',ceo_comment_id:newReply.id,completed_at:new Date().toISOString()}});
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.JarvisTasks&&window.JarvisCEOInput);
  await popupHas([task.identifier,ceo.name,published.data.text.slice(0,100)]);await minimal();
  assert.equal(await page.evaluate(()=>window.JarvisTasks.snapshot().objectiveId),task.id);
  assert.deepEqual((await api('agents')).agents.map(a=>a.id).sort(),rosterBefore,'The workflow reuses four existing staff; no employee is hired');
  const added=(await api('tasks')).tasks.map(t=>t.id).filter(id=>!before.includes(id));
  assert.deepEqual(added.sort(),exists?[]:[task.id,...childIds].sort(),'Only one requested root and its four children may be created');
  assert.equal(posts.filter(p=>p==='/api/tasks').length,exists?0:1);assert.equal(posts.filter(p=>p==='/api/chat').length,0,'Ordinary CEO conversation never uses direct chat');
  if(verifyOnly)assert.equal(posts.length,0,'--verify-only must issue no mutation requests');
  assert.deepEqual(errors,[]);await page.screenshot({path:root+'/docs/evidence/codex-workforce-hud.png',fullPage:true});
  const previous=fs.existsSync(output)?JSON.parse(fs.readFileSync(output)):{};
  const result={status:'passed',checked_at:new Date().toISOString(),verification_only:verifyOnly,root_created_this_check:!exists,
   task_id:task.id,identifier:task.identifier,ceo_agent_id:ceo.id,ceo_name:ceo.name,objective_request_id:receipt.request_id,
   submitted_via:'Ordinary minimal AI input, no @ceo prefix',native_status:followDetail.status,
   statuses_observed:[...new Set([...(previous.statuses_observed||[]),...first.statuses])],native_waiting_observed:first.nativeWaitingObserved||!!previous.native_waiting_observed,children:proofs,
   native_dependencies:[{task_id:childrenByRole.engineer.id,depends_on:childrenByRole.researcher.id},{task_id:childrenByRole.security.id,depends_on:childrenByRole.engineer.id}],
   artifacts,followup:{request_id:receipt.followup.request_id,human_comment_id:receipt.followup.comment_id,new_ceo_comment_id:newReply.id,
    same_root:true,no_new_tasks:true,no_worker_reexecution:true},
   restored_after_refresh:true,minimal_single_send:true,authenticated_history:true,new_employees:0,direct_chat_posts:0,
   task_posts_this_check:posts.filter(p=>p==='/api/tasks').length,message_posts_this_check:posts.filter(p=>p.endsWith('/messages')).length,
   event_poll_requests:eventReads.length,browser_errors:errors,
   inference:'Every native employee projection declares openai-codex/gpt-6.1-sol. Independent Hermes request-log verification is required for actual provider execution and shared-slot enforcement.'};
  save(output,result);console.log(JSON.stringify(result));
 }catch(error){
  if(routeFailure)error=new Error(routeFailure);
  if(receipt)patch({last_error:String(error.message).split('Call log:')[0],last_checked_at:new Date().toISOString()});
  await page.screenshot({path:root+'/.runtime/codex-workforce-failure.png',fullPage:true}).catch(()=>{});throw error;
 }finally{await browser.close();}
}
main().catch(error=>{console.error(String(error.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
