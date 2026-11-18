/* Workspace reads use live APIs. Thread writes are intercepted in an isolated browser. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8765',root='/workspace';

async function checkComposer(page){
 const input=page.locator('#generalComposer #administratorInput');
 await input.waitFor({state:'visible'});
 assert.equal(await page.locator('textarea:visible').count(),1);
 assert(await input.evaluate(node=>{
  const r=node.getBoundingClientRect();
  return r.width>0&&r.height>0&&r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1;
 }),'The General composer must fit in the viewport');
}

async function checkThreads(browser,cookies){
 const context=await browser.newContext({storageState:{cookies,origins:[]},viewport:{width:1280,height:900}});
 const page=await context.newPage(),threads=new Map([['default',{id:'default',title:'General chat'}]]);
 const histories=new Map([['default',[{role:'assistant',text:'Team baseline.'}]]]),messages=[],errors=[],unexpectedWrites=[];
 page.on('pageerror',err=>errors.push(err.message));
 await page.route('**/api/**',async route=>{
  const request=route.request(),method=request.method(),url=new URL(request.url());
  const respond=json=>route.fulfill({status:200,json});
  if(url.pathname==='/api/admin/conversations'){
   if(method==='GET')return respond({conversations:[...threads.values()],default_id:'default'});
   if(method==='POST'){
    const {id,title}=request.postDataJSON();
    if(!threads.has(id)){threads.set(id,{id,title:title||'New conversation'});histories.set(id,[]);}
    return respond(threads.get(id));
   }
  }
  if(url.pathname==='/api/admin/history'&&method==='GET')return respond({messages:histories.get(url.searchParams.get('conversation_id')||'default')||[]});
  if(url.pathname==='/api/admin/chat'&&method==='POST'){
   const data=request.postDataJSON(),id=data.conversation_id;
   if(!threads.has(id))return route.fulfill({status:404,json:{detail:'Unknown conversation'}});
   histories.get(id).push({role:'user',text:data.input},{role:'assistant',text:'Thread reply.'});
   if(threads.get(id).title==='New conversation')threads.get(id).title=data.input;
   messages.push(data);return respond({text:'Thread reply.',conversation_id:id,administration_updates:[],general_context_updates:[]});
  }
  if(!['GET','HEAD'].includes(method)){
   unexpectedWrites.push(method+' '+url.pathname);return route.fulfill({status:405});
  }
  return route.continue();
 });
 try{
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
  await page.locator('#generalModeBtn').click();
  const input=page.locator('#administratorInput'),feed=page.locator('#administratorFeed');
  const thread=id=>page.locator('#generalThreads button[data-thread-id="'+id+'"]');
  await feed.getByText('Team baseline.',{exact:true}).waitFor();
  await input.fill('Draft for existing thread');
  await page.locator('#newGeneralChat').click();
  await page.waitForFunction(()=>document.getElementById('administratorInput').value==='');
  assert(!(await feed.innerText()).includes('Team baseline.'));
  await input.fill('Check the daily report');await page.locator('#administratorSend').click();
  await feed.getByText('Thread reply.',{exact:true}).waitFor();
  assert.equal(messages.length,1);const id=messages[0].conversation_id;
  assert(id&&id!=='default'&&threads.has(id));
  await input.fill('Draft for report thread');
  await thread('default').click();await feed.getByText('Team baseline.',{exact:true}).waitFor();
  assert.equal(await input.inputValue(),'Draft for existing thread');assert(!(await feed.innerText()).includes('Thread reply.'));
  await thread(id).click();await feed.getByText('Thread reply.',{exact:true}).waitFor();
  assert.equal(await input.inputValue(),'Draft for report thread');assert(!(await feed.innerText()).includes('Team baseline.'));
  await page.reload({waitUntil:'domcontentloaded'});await feed.getByText('Thread reply.',{exact:true}).waitFor();
  assert.equal(await input.inputValue(),'Draft for report thread');
  await page.locator('#generalCronBtn').click();await page.locator('#cronPanel').waitFor();
  assert(await input.isVisible());assert.equal(await input.inputValue(),'Draft for report thread');
  await input.fill('Summarize the schedule');await page.locator('#administratorSend').click();
  await page.waitForFunction(()=>!document.getElementById('administratorSend').disabled&&document.getElementById('administratorInput').value==='');
  assert.deepEqual(messages.map(m=>m.conversation_id),[id,id]);assert.equal(messages[1].input,'Summarize the schedule');
  assert.deepEqual(unexpectedWrites,[]);assert.deepEqual(errors,[]);
 }finally{await context.close();}
}

async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
 const result={checked_at:new Date().toISOString()};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(['POST','PATCH','PUT','DELETE'].includes(r.method())&&new URL(r.url()).pathname.startsWith('/api/'))writes.push(new URL(r.url()).pathname);});
 const api=async path=>{const r=await page.request.get(base+'/api/'+path);assert.equal(r.status(),200);return r.json();};
 try{
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisModes&&window.JarvisTasks);
  assert.deepEqual(await page.locator('#appModes button').allTextContents(),['CHAT','PROJECTS','GENERAL']);
  await page.locator('#generalModeBtn').click();await page.locator('#administratorPanel').waitFor({state:'visible'});
  await checkComposer(page);
  const contextItem=await page.locator('#generalContextBtn').boundingBox(),cronItem=await page.locator('#generalCronBtn').boundingBox();
  assert(contextItem&&cronItem&&Math.abs(contextItem.x-cronItem.x)<8&&Math.abs(contextItem.y-cronItem.y)>20,'Context and Cron jobs should be stacked in the sidebar');
  await page.locator('#administratorInput').fill('GENERAL_DRAFT_STAYS_HERE');
  await page.screenshot({path:root+'/docs/evidence/general-workspace-chat-desktop.png',fullPage:true});
  await page.locator('#projectsModeBtn').click();await page.locator('#projectBrowser').waitFor({state:'visible'});
  const tasks=(await api('tasks')).tasks,ceo=(await api('agents')).ceo_id;
  const missions=tasks.filter(t=>!t.parentId&&!t.hiddenAt&&t.assigneeAgentId===ceo&&t.work_scope==='project'&&t.mission_id===t.id);
  const general=tasks.filter(t=>!t.parentId&&t.assigneeAgentId===ceo&&t.work_scope==='general');assert(missions.length&&general.length);
  await page.waitForFunction(count=>document.querySelectorAll('.project-list-item').length===count,missions.length);
  for(const task of general)assert.equal(await page.locator('.project-list-item[data-project-id="'+task.id+'"]').count(),0);
  await page.locator('#newProjectBtn').click();assert.equal(await page.locator('#chatInput').inputValue(),'');
  await page.locator('#chatInput').fill('MISSION_DRAFT_STAYS_LOCAL');
  await page.locator('#generalModeBtn').click();assert.equal(await page.locator('#administratorInput').inputValue(),'GENERAL_DRAFT_STAYS_HERE');
  await page.locator('#generalContextBtn').click();
  const select=page.locator('select#generalAgentList, #generalAgentList select');
  await select.locator('optgroup[label="Agents"] option').first().waitFor({state:'attached'});
  const contexts=await api('general-context');
  for(const agent of contexts.agents){
   await select.selectOption(agent.id);
   if(agent.general_context.text)assert.equal(await page.locator('#generalContextText').innerText(),agent.general_context.text);
   else assert((await page.locator('#generalContextText').innerText()).trim());
  }
  await checkComposer(page);assert.equal(await page.locator('#administratorInput').inputValue(),'GENERAL_DRAFT_STAYS_HERE');
  assert(await page.locator('#generalContextPanel #administratorInspector').count());
  assert(await page.locator('#generalKnowledgeList button').count()>0);
  await page.screenshot({path:root+'/docs/evidence/general-workspace-knowledge-desktop.png',fullPage:true});
  await page.locator('#generalCronBtn').click();await page.locator('#cronPanel').waitFor({state:'visible'});
  await checkComposer(page);
  const jobs=(await api('cron-jobs?scope=general')).jobs;assert(jobs.length&&jobs.every(j=>j.work_scope==='general'&&!j.mission_id));
  await page.locator('.cron-card[data-job-id="'+jobs[0].id+'"]').waitFor();
  assert((await page.locator('#cronDescription').innerText()).includes('across missions'));
  await page.locator('#newCronBtn').click();assert((await page.locator('#cronScopeLabel').innerText()).startsWith('General:'));await page.locator('#cancelCronBtn').click();
  await page.screenshot({path:root+'/docs/evidence/general-workspace-cron-desktop.png',fullPage:true});
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.JarvisModes?.snapshot().generalView==='cron');
  await page.locator('.cron-card').first().waitFor();
  const mission=missions.find(t=>t.status==='done')||missions[0];
  await page.locator('#projectsModeBtn').click();await page.locator('.project-list-item[data-project-id="'+mission.id+'"]').click();
  await page.locator('#projectScheduleBtn').click();await page.waitForFunction(()=>window.JarvisModes?.snapshot().projectView==='cron');
  assert.equal(await page.locator('#cronHeading').innerText(),'Mission cron jobs');
  for(const job of jobs)assert.equal(await page.locator('.cron-card[data-job-id="'+job.id+'"]').count(),0);
  if(mission.status==='done')assert(await page.locator('#newCronBtn').isDisabled());
  await page.screenshot({path:root+'/docs/evidence/mission-cron-desktop.png',fullPage:true});
  await page.locator('#generalModeBtn').click();await page.locator('#generalThreads button[data-thread-id="default"]').click();
  await page.setViewportSize({width:393,height:852});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await checkComposer(page);
  await page.screenshot({path:root+'/docs/evidence/general-workspace-chat-mobile.png',fullPage:true});
  await page.locator('#generalSidebarToggle').click();await page.locator('#generalCronBtn').click();
  await page.locator('.cron-card').first().waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await checkComposer(page);
  assert.notEqual(await page.locator('body').getAttribute('data-general-sidebar'),'open');
  await page.screenshot({path:root+'/docs/evidence/general-workspace-cron-mobile.png',fullPage:true});
  assert.equal(await page.locator('[data-csi-auto]').count(),0);assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  await checkThreads(browser,await page.context().cookies());
  Object.assign(result,{status:'passed',navigation:['Chat','Projects','General'],general_chat_history_reused:true,general_draft_isolated:true,
   mission_list_excludes_general_work:true,general_agent_contexts:contexts.agents.length,shared_work_visible:true,
   general_jobs:jobs.length,mission_jobs_exclude_general:true,closed_mission_scheduling_disabled:true,reload_restores_scope:true,
   mobile_checks:true,shared_general_composer:true,thread_history_isolated:true,thread_drafts_survive_reload:true,
   simulated_thread_messages:2,native_mutations:0,browser_errors:errors});
 }catch(error){result.status='failed';result.error=error.message;await page.screenshot({path:root+'/docs/evidence/general-workspace-failure.png',fullPage:true}).catch(()=>{});throw error;}
 finally{fs.writeFileSync(root+'/docs/evidence/general-workspace-ui.json',JSON.stringify(result,null,2)+'\n');await browser.close();}
 console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(String(error.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
