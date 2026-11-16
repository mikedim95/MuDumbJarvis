/* Explicitly authorized cloud demo. Creates exactly one native HUD objective.
 * The durable receipt prevents duplicate submissions; --verify-only resumes
 * observation after a browser/test interruption without creating more work.
 */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const root='/workspace',base='http://localhost:8765',receipt=root+'/.runtime/codex-demo-task.json';
const objective='Codex demo: use paperclip_context to read company employees and goals, then local_ollama_models to retrieve actual installed model names and sizes. Work yourself without hiring or delegation. Produce a concise technical inventory report with exact names, size_bytes and size_gib, roster availability, data sources and limits. Publish codex-demo-report.md using publish_artifact; finish with results. Do not benchmark, change configuration or run host commands.';
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
async function main(){
 const verify=process.argv.includes('--verify-only');
 if(fs.existsSync(receipt)&&!verify)throw new Error('Demo already submitted; use --verify-only');
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 async function api(path){const r=await page.request.get(base+'/api/'+path);assert.equal(r.status(),200);return r.json();}
 try{
  assert.equal((await page.request.get(base+'/api/tasks')).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
  await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
  let task;
  if(verify){task=JSON.parse(fs.readFileSync(receipt));await page.evaluate(id=>localStorage.setItem('jarvis-task-selected',id),task.id);await page.reload({waitUntil:'domcontentloaded'});}
  else{
   await page.locator('#commandMode').selectOption('objective');await page.locator('#chatInput').fill(objective);
   const response=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/tasks');
   await page.locator('#sendBtn').click();const r=await response;assert(r.ok());task=await r.json();
   fs.writeFileSync(receipt,JSON.stringify(task,null,2),{mode:0o600});console.log(JSON.stringify({event:'objective_submitted',id:task.id,identifier:task.identifier}));
  }
  await page.waitForFunction(()=>window.JarvisVisualCore?.snapshot().frame>0);
  const seen=new Set();let current;
  for(let count=0;count<120;count++){
   current=await api('tasks/'+task.id);seen.add(current.status);
   if(['done','blocked','cancelled'].includes(current.status))break;
   if(count%10===0)console.log(JSON.stringify({event:'observed',id:task.id,status:current.status}));
   await page.waitForTimeout(3000);
  }
  assert.equal(current.status,'done','Actual task must complete, rather than merely return prose');
  await page.waitForFunction(id=>document.getElementById('taskDetail').textContent.includes('done')&&localStorage.getItem('jarvis-task-selected')===id,task.id);
  const mon=await api('tasks/'+task.id+'/monitor');
  const artifact=mon.artifacts.find(a=>a.originalFilename==='codex-demo-report.md');assert(artifact,'The requested report must be persisted');
  const response=await page.request.get(base+'/api/tasks/'+task.id+'/artifacts/'+artifact.id);assert.equal(response.status(),200);
  const content=await response.body();assert.equal(sha(content),artifact.sha256);
  const dashboard=await api('monitor'),ceo=dashboard.agents.find(a=>a.role==='ceo');
  assert.equal(ceo.capability.provider,'openai-codex');assert.equal(ceo.capability.model,'gpt-6.1-sol');
  assert(dashboard.agents.filter(a=>a.id!==ceo.id).every(a=>a.status==='paused'));
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('taskDetail').textContent.includes('done'));
  assert.equal((await api('tasks/'+task.id)).status,'done');assert.deepEqual(errors,[]);
  await page.evaluate(()=>{document.getElementById('boot')?.classList.add('done');document.body.classList.remove('booting');document.body.classList.add('booted');});
  await page.screenshot({path:root+'/docs/evidence/codex-demo-hud.png',fullPage:true});
  const previous=verify&&fs.existsSync(root+'/docs/evidence/codex-demo-hud.json')?JSON.parse(fs.readFileSync(root+'/docs/evidence/codex-demo-hud.json')):{};
  const result={status:'passed',checked_at:new Date().toISOString(),issue_id:task.id,identifier:task.identifier,
    objective,statuses_observed:[...new Set([...(previous.statuses_observed||[]),...seen])],final_status:current.status,submitted_through:'authenticated JARVIS HUD',
    ceo_id:ceo.id,provider:ceo.capability.provider,model:ceo.capability.model,
    artifact:{id:artifact.id,sha256:artifact.sha256,bytes:content.length},history_after_refresh:true,
    workers_remain_paused:true,page_errors:errors,verification_only:verify,native_execution_verification:'See codex-demo-execution.json for provider, tool, run and data correlation'};
  fs.writeFileSync(root+'/docs/evidence/codex-demo-hud.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
