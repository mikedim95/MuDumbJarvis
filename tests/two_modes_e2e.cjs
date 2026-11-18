/* Authenticated live mode/context check. A private receipt prevents duplicate goals. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const root='/workspace',base='http://127.0.0.1:8765';
const receiptFile=root+'/.runtime/two-modes-task.json',outFile=root+'/docs/evidence/two-modes.json';
const objective='Create one read-only inventory project. Record a CEO plan and assign exactly one persistent child to the existing JARVIS Systems employee to collect installed model names and exact byte sizes using local_ollama_models and publish modes-systems.md. Jarvis must review that worker execution evidence, publish modes-project.md, and include the actual model names and byte sizes in the final reply. Use the existing staff only. No hiring, host changes or resuming older objectives.';
const observeOnly=process.argv.includes('--observe-only');
const result=observeOnly?JSON.parse(fs.readFileSync(outFile)):{checked_at:new Date().toISOString(),browser_errors:[]};
let receipt=fs.existsSync(receiptFile)?JSON.parse(fs.readFileSync(receiptFile)):null;
const saveReceipt=()=>fs.writeFileSync(receiptFile,JSON.stringify(receipt,null,2)+'\n',{mode:0o600});
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>result.browser_errors.push(e.message));
 const mutations=[];page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname.startsWith('/api/tasks'))mutations.push(new URL(r.url()).pathname);});
 async function api(path){const r=await page.request.get(base+'/api/'+path,{timeout:30000});assert.equal(r.status(),200,path);return r.json();}
 async function mode(value){await page.locator(value==='direct'?'#directModeBtn':'#projectsModeBtn').click();await page.waitForFunction(m=>document.body.dataset.uiMode===m,value);}
 async function selectProject(id){if(!await page.locator('#projectBrowser').isVisible()){if(await page.locator('body').getAttribute('data-ui-mode')!=='projects')await mode('projects');else await page.locator('#projectBackBtn').click();}await page.locator('.project-list-item[data-project-id="'+id+'"]').click();await page.waitForFunction(value=>window.JarvisTasks.snapshot().objectiveId===value&&window.JarvisModes.snapshot().projectView==='context',id);}
 try{
  assert.equal((await page.request.get(base+'/api/tasks')).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisModes&&window.JarvisTasks&&window.JarvisCEOInput);
  assert.equal(await page.locator('body').getAttribute('data-ui-mode'),'direct');
  assert(await page.locator('#directModeBtn').isVisible());assert(await page.locator('#projectsModeBtn').isVisible());
  assert(!await page.locator('#projectContext').isVisible());
  if(!observeOnly){
  const before=(await api('tasks')).tasks.filter(t=>!t.parentId).map(t=>t.id).sort();
  await page.locator('#chatInput').fill('Who are the existing workers in Paperclip? Use their actual names and keep it brief.');
  const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/chat',{timeout:180000});
  await page.locator('#sendBtn').click();const reply=await pending,chat=await reply.json();
  assert.equal(reply.status(),200,chat.error);assert.equal(chat.runtime.model,'gpt-6.1-sol');
  assert.equal(chat.paperclip_context.read_only,true);assert.equal(chat.paperclip_context.status,'available');
  assert.match(chat.text,/Research/i);assert.match(chat.text,/Software/i);assert.match(chat.text,/Systems/i);assert.match(chat.text,/Security/i);
  assert.deepEqual((await api('tasks')).tasks.filter(t=>!t.parentId).map(t=>t.id).sort(),before);assert.equal(mutations.length,0);
  result.direct_chat={...chat,tasks_created:0};
  await page.screenshot({path:root+'/docs/evidence/two-modes-direct.png',fullPage:true});
  }
  await mode('projects');await page.waitForFunction(()=>document.querySelectorAll('.project-list-item').length>1);
  if(!receipt){
   assert(!observeOnly,'Observe mode requires an existing native goal');
   await page.locator('#newProjectBtn').click();assert.equal(await page.locator('#sendBtn').innerText(),'SET GOAL');
   receipt={state:'intent',input:objective,created_at:new Date().toISOString()};saveReceipt();
   await page.route('**/api/tasks',async route=>{if(route.request().method()==='POST'){const d=route.request().postDataJSON();assert.equal(d.input,objective);receipt.request_id=d.request_id;saveReceipt();}await route.continue();});
   await page.locator('#chatInput').fill(objective);
   const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/tasks',{timeout:45000});
   await page.locator('#sendBtn').click();const r=await pending,d=await r.json();assert(r.ok(),JSON.stringify(d));
   receipt={...receipt,...d,state:'submitted'};saveReceipt();await page.unroute('**/api/tasks');
  }
  assert(receipt.id,'Uncertain intent requires native reconciliation; do not create a replacement goal');
  await selectProject(receipt.id);
  const other=(await api('tasks')).tasks.find(t=>!t.parentId&&t.id!==receipt.id&&t.status==='done');assert(other);
  await page.locator('#chatInput').fill('DRAFT_FOR_FIRST_PROJECT');
  await selectProject(other.id);await page.waitForFunction(()=>document.getElementById('chatInput').value==='');
  await page.locator('#chatInput').fill('DRAFT_FOR_OTHER_PROJECT');
  await selectProject(receipt.id);await page.waitForFunction(()=>document.getElementById('chatInput').value==='DRAFT_FOR_FIRST_PROJECT');
  await mode('direct');await page.locator('#chatInput').fill('DIRECT_DRAFT');
  assert.equal(await page.locator('[data-csi-auto] [data-ceo-task-id]').count(),0,'Project panels must stay out of Direct Chat');
  await mode('projects');await selectProject(receipt.id);assert.equal(await page.locator('#chatInput').inputValue(),'DRAFT_FOR_FIRST_PROJECT');
  result.drafts_isolated=true;
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(id=>window.JarvisTasks?.snapshot().objectiveId===id,receipt.id);
  assert.equal(await page.locator('body').getAttribute('data-ui-mode'),'projects');
  await page.waitForFunction(()=>document.getElementById('modeError').textContent==='');
  let detail;const deadline=Date.now()+480000;
  while(Date.now()<deadline){
   detail=await api('tasks/'+receipt.id);console.log(JSON.stringify({identifier:detail.identifier,status:detail.status,children:detail.children.map(c=>({identifier:c.identifier,status:c.status}))}));
   if(detail.status==='done')break;
   assert(!['blocked','cancelled'].includes(detail.status),'Project is '+detail.status+'; inspect the same saved task, not a replacement');
   await page.waitForTimeout(5000);
  }
  assert.equal(detail.status,'done');assert.equal(detail.children.length,1);assert.equal(detail.children[0].status,'done');
  const events=await api('tasks/'+receipt.id+'/events');
  assert(events.events.some(e=>e.task_id===detail.children[0].id&&e.provenance==='verified_tool_output'&&e.data?.tool==='local_ollama_models'&&e.data.success===true));
  assert(events.artifacts.some(a=>a.originalFilename==='modes-project.md'));
  await page.waitForFunction(id=>document.querySelector('[data-ceo-task-id="'+id+'"]')?.innerText.includes('JARVIS CONSOLIDATED RESULT'),receipt.id,{timeout:30000});
  await page.screenshot({path:root+'/docs/evidence/two-modes-projects.png',fullPage:true});
  result.project={id:detail.id,identifier:detail.identifier,status:detail.status,children:detail.children.map(c=>({id:c.id,identifier:c.identifier,status:c.status,assigneeAgentId:c.assigneeAgentId})),runs:detail.runs};
  result.project_snapshot=events;result.selected_project_survives_reload=true;
  assert(!await page.locator('#feed').innerText().then(text=>text.includes('Verified delegated execution data:')));
  await selectProject(other.id);
  await page.waitForFunction(id=>window.JarvisTasks.snapshot().objectiveId===id,other.id);
  await selectProject(receipt.id);
  await page.waitForFunction(id=>window.JarvisTasks.snapshot().objectiveId===id,receipt.id);
  result.independent_project_contexts=[other.id,receipt.id];
  await mode('direct');assert.equal(await page.locator('[data-csi-auto] [data-ceo-task-id]').count(),0);
  await page.setViewportSize({width:393,height:852});
  for(const view of ['direct','projects']){
   await mode(view);if(view==='projects')await selectProject(receipt.id);for(const selector of ['#directModeBtn','#projectsModeBtn','#chatInput','#sendBtn']){const b=await page.locator(selector).boundingBox();assert(b&&b.x>=0&&b.y>=0&&b.x+b.width<=394&&b.y+b.height<=853,selector+' outside mobile viewport');}
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:root+'/docs/evidence/two-modes-'+view+'-mobile.png',fullPage:true});
  }
  await mode('direct'); // Navigation stays usable with a mobile project panel open.
  assert.deepEqual(result.browser_errors,[]);result.status='passed';receipt.state='completed';saveReceipt();
 }catch(error){result.status='failed';result.error=String(error.message);throw error;}
 finally{fs.writeFileSync(outFile,JSON.stringify(result,null,2)+'\n');await browser.close();}
 console.log(JSON.stringify({status:result.status,project:result.project.identifier,direct_chat_creates_no_tasks:true,per_project_context:true}));
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
