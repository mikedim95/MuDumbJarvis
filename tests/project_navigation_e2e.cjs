/* Read-only navigation checks. No goals, comments, retries or directions are written. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const root='/workspace',base='http://127.0.0.1:8765';
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
 const result={checked_at:new Date().toISOString()};
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname.startsWith('/api/'))writes.push(new URL(r.url()).pathname);});
 const api=async path=>{const r=await page.request.get(base+'/api/'+path);assert.equal(r.status(),200);return r.json();};
 async function choose(id){await page.locator('.project-list-item[data-project-id="'+id+'"]').click();await page.waitForFunction(value=>window.JarvisTasks?.snapshot().objectiveId===value&&window.JarvisModes?.snapshot().projectView==='context',id);}
 async function back(){await page.locator('#projectBackBtn').click();await page.locator('#projectBrowser').waitFor({state:'visible'});}
 try{
  assert.equal((await page.request.get(base+'/api/general-context')).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisModes&&window.JarvisGeneralContext);
  const before=await api('tasks'),roster=await api('agents');
  const projects=before.tasks.filter(t=>!t.parentId&&t.assigneeAgentId===roster.ceo_id);assert(projects.length>=2);
  const first=projects.find(t=>t.identifier==='JAR-59')||projects[0],second=projects.find(t=>t.id!==first.id&&t.status==='done');assert(second);
  await page.locator('#projectsModeBtn').click();await page.locator('.project-list-item').first().waitFor();
  assert.equal(await page.locator('#projectSelect').count(),0);
  assert.equal(await page.locator('.project-list-item').count(),projects.length);
  assert(!await page.locator('#chatRow').isVisible());assert(!await page.locator('#feed').isVisible());assert(!await page.locator('#reactorWrap').isVisible());
  assert.equal(await page.locator('[data-csi-auto]').count(),0);
  const large=await page.locator('#newProjectBtn').boundingBox();assert(large.height>=60&&large.width>=600&&large.y>800);
  await page.screenshot({path:root+'/docs/evidence/project-list-desktop.png',fullPage:true});
  await choose(first.id);assert(!await page.locator('#projectBrowser').isVisible());assert(await page.locator('#chatInput').isVisible());
  assert.equal(await page.locator('#projectTitle').innerText(),first.title);
  await page.locator('#chatInput').fill('DRAFT_FOR_FIRST_PROJECT');await back();await choose(second.id);
  await page.waitForFunction(()=>document.getElementById('chatInput').value==='');
  await page.locator('#chatInput').fill('DRAFT_FOR_SECOND_PROJECT');await back();await choose(first.id);
  await page.waitForFunction(()=>document.getElementById('chatInput').value==='DRAFT_FOR_FIRST_PROJECT');
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(id=>window.JarvisModes?.snapshot().projectView==='context'&&window.JarvisTasks?.snapshot().objectiveId===id,first.id);
  await page.waitForFunction(()=>document.getElementById('modeError').textContent==='');
  assert(!await page.locator('#projectBrowser').isVisible());assert(await page.locator('#chatInput').isVisible());
  await page.screenshot({path:root+'/docs/evidence/project-selected-desktop.png',fullPage:true});
  await back();await page.locator('#newProjectBtn').click();
  assert.equal(await page.locator('#projectTitle').innerText(),'New project');
  assert.equal(await page.evaluate(()=>window.JarvisTasks.snapshot().objectiveId),null);
  assert(!await page.locator('#projectBrowser').isVisible());assert.equal(await page.locator('#chatInput').inputValue(),'');
  assert.equal(await page.locator('#feed .msg:visible').count(),0);assert.equal(await page.locator('[data-csi-auto] [data-ceo-task-id]').count(),0);
  assert.equal(await page.locator('#sendBtn').innerText(),'SET GOAL');
  assert(await page.locator('#chatInput').evaluate(e=>document.activeElement===e));
  await page.screenshot({path:root+'/docs/evidence/project-new-desktop.png',fullPage:true});
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.JarvisModes?.snapshot().projectView==='context');
  assert.equal(await page.evaluate(()=>window.JarvisTasks.snapshot().objectiveId),null);assert.equal(await page.locator('#feed .msg:visible').count(),0);
  await back();await page.setViewportSize({width:393,height:852});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const mobile=await page.locator('#newProjectBtn').boundingBox();assert(mobile.height>=60&&mobile.width>=330&&mobile.y>700&&mobile.y+mobile.height<=853);
  await page.screenshot({path:root+'/docs/evidence/project-list-mobile.png',fullPage:true});
  await page.locator('#newProjectBtn').click();
  const input=await page.locator('#chatInput').boundingBox();assert(input.y+input.height<=853);
  await page.screenshot({path:root+'/docs/evidence/project-new-mobile.png',fullPage:true});
  await page.locator('#directModeBtn').click();await page.locator('#generalContextBtn').click();
  await page.waitForFunction(()=>document.querySelectorAll('#generalAgentList button').length>=5);
  const contexts=await api('general-context');
  assert.equal(await page.locator('#generalAgentList button').count(),contexts.agents.length);
  for(const agent of contexts.agents){
   await page.locator('#generalAgentList button[data-agent-id="'+agent.id+'"]').click();
   assert.equal(await page.locator('#generalContextText').innerText(),agent.general_context.text||'No general directions saved for this agent.');
  }
  assert(await page.locator('#chatInput').isVisible());
  await page.screenshot({path:root+'/docs/evidence/general-context-mobile.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:root+'/docs/evidence/general-context-desktop.png',fullPage:true});
  assert.deepEqual((await api('tasks')).tasks.map(t=>t.id).sort(),before.tasks.map(t=>t.id).sort());
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  Object.assign(result,{status:'passed',projects:projects.length,project_ids:[first.id,second.id],
   list_replaces_dropdown:true,list_hidden_in_context:true,new_project_empty_until_prompt:true,
   selected_scope_restored_after_reload:true,per_project_drafts_isolated:true,general_context_agents:contexts.agents.length,
   mobile_checks:true,api_mutations:0,browser_errors:errors});
 }catch(error){result.status='failed';result.error=error.message;throw error;}
 finally{fs.writeFileSync(root+'/docs/evidence/project-navigation.json',JSON.stringify(result,null,2)+'\n');await browser.close();}
 console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
