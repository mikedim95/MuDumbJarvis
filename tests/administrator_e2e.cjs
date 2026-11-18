/* --apply-setup performs the owner's requested rename and cooperative chat prompt save. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8765',root='/workspace',apply=process.argv.includes('--apply-setup');
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],mutations=[];
 const result={checked_at:new Date().toISOString(),apply_setup:apply};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(['POST','DELETE','PATCH'].includes(r.method())&&new URL(r.url()).pathname.startsWith('/api/'))mutations.push(new URL(r.url()).pathname);});
 const api=async path=>{const r=await page.request.get(base+'/api/'+path);assert.equal(r.status(),200);return r.json();};
 async function send(text){
  await page.locator('#administratorInput').fill(text);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/admin/chat')&&r.request().method()==='POST',{timeout:300000});
  await page.locator('#administratorSend').click();const r=await response,data=await r.json();
  assert.equal(r.status(),200,data.error);assert.equal(data.surface,'administrator');
  assert.equal(data.runtime.provider,'openai-codex');assert.equal(data.runtime.model,'gpt-6.1-sol');
  await page.locator('#administratorSend').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.getElementById('administratorSend').disabled,{timeout:30000});
  return data;
 }
 try{
  assert.equal((await page.request.get(base+'/api/admin/config')).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisModes&&window.JarvisTasks);
  const before=await api('tasks'),config=await api('admin/config');
  const retainedHistory=await api('admin/history');
  assert.equal(config.agents.length,5);assert.equal(config.chat_prompts.length,2);
  await page.locator('#projectsModeBtn').click();await page.locator('#administratorBtn').click();
  await page.locator('#administratorPanel').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelectorAll('#administratorTargets button').length===7);
  assert(!await page.locator('#projectBrowser').isVisible());assert(!await page.locator('#projectContext').isVisible());
  assert(!await page.locator('#feed').isVisible());assert(!await page.locator('#chatRow').isVisible());
  assert.equal(await page.locator('[data-csi-auto]:visible').count(),0);
  await page.locator('#administratorInspector summary').click();
  for(const prompt of [...config.chat_prompts,...config.agents.map(a=>({...a,scope:'agent'}))]){
   const key=prompt.scope==='agent'?prompt.id:prompt.scope;
   await page.locator('#administratorTargets button[data-target="'+key+'"]').click();
   assert.equal(await page.locator('#administratorPrompt').innerText(),prompt.system_prompt);
  }
  if(apply){
   const rename=await send('Rename JARVIS Research to JARVIS OSINT.');
   assert(rename.administration_updates.some(r=>r.action==='rename_agent'&&r.status==='saved'&&r.name==='JARVIS OSINT'));
   const direct=config.chat_prompts.find(t=>t.scope==='direct');
   const extra='Act constructively on clear, feasible requests. Ask for clarification only when a missing detail materially affects the result.';
   const newPrompt=direct.system_prompt.includes(extra)?direct.system_prompt:direct.system_prompt+' '+extra;
   await page.locator('#administratorTargets button[data-target="direct"]').click();
   const changed=await send('Set the Direct Chat system prompt to this exact text:\n'+newPrompt);
   assert(changed.administration_updates.some(r=>r.action==='set_system_prompt'&&r.scope==='direct'&&r.status==='saved'));
   const observed=await api('admin/config');assert.equal(observed.chat_prompts.find(t=>t.scope==='direct').system_prompt,newPrompt);
   const renamed=observed.agents.find(a=>a.id===config.agents.find(a=>a.name==='JARVIS Research'||a.name==='JARVIS OSINT').id);
   assert.equal(renamed.name,'JARVIS OSINT');
   result.native_changes={renamed_agent:{id:renamed.id,name:renamed.name},saved_direct_prompt:true,
    rename_tools:rename.tools.map(t=>t.name),prompt_tools:changed.tools.map(t=>t.name),provider:changed.runtime.provider,model:changed.runtime.model};
   const history=await api('admin/history');assert(history.messages.some(m=>m.role==='user'&&m.text==='Rename JARVIS Research to JARVIS OSINT.'));
   assert(history.messages.some(m=>m.role==='assistant'&&m.text===changed.text));
  }
  await page.locator('#administratorInput').fill('UNSENT_ADMINISTRATOR_DRAFT');
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.JarvisModes?.snapshot().projectView==='admin');
  await page.waitForFunction(()=>document.querySelectorAll('#administratorTargets button').length===7);
  assert.equal(await page.locator('#administratorInput').inputValue(),'UNSENT_ADMINISTRATOR_DRAFT');
  assert(await page.locator('#administratorPanel').isVisible());
  if(retainedHistory.messages.some(m=>m.role==='assistant')||apply)await page.locator('#administratorFeed .jarvis').first().waitFor({state:'visible'});
  await page.locator('#administratorInput').fill('');
  await page.locator('#administratorInspector summary').click();
  await page.locator('#administratorTargets button[data-target="direct"]').click();
  await page.screenshot({path:root+'/docs/evidence/administrator-desktop.png',fullPage:true});
  await page.setViewportSize({width:393,height:852});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const input=await page.locator('#administratorInput').boundingBox();assert(input.y+input.height<=852&&input.width>250);
  await page.waitForFunction(()=>{const feed=document.getElementById('administratorFeed');return feed.scrollHeight-feed.clientHeight-feed.scrollTop<3;});
  assert.equal(await page.locator('[data-csi-auto]:visible').count(),0);
  await page.screenshot({path:root+'/docs/evidence/administrator-mobile.png',fullPage:true});
  await page.locator('#administratorBackBtn').click();assert(await page.locator('#projectBrowser').isVisible());
  await page.locator('#directModeBtn').click();assert(await page.locator('#chatInput').isVisible());assert(!await page.locator('#administratorPanel').isVisible());
  assert.equal(await page.locator('#feed .you:visible,#feed .jarvis:visible').count(),0);
  assert.deepEqual((await api('tasks')).tasks.map(t=>t.id).sort(),before.tasks.map(t=>t.id).sort());
  assert.deepEqual(errors,[]);
  assert(mutations.every(path=>path==='/api/admin/chat'));
  Object.assign(result,{status:'passed',separate_chat:true,seven_actual_prompt_targets:true,prompt_and_history_reload:true,
   drafts_isolated:true,project_list_preserved:true,mobile_checks:true,browser_errors:errors,mutations,
   retained_administrator_messages:retainedHistory.messages.length,
   retained_owner_configuration:{osint_agent:config.agents.find(a=>a.name==='JARVIS OSINT')?.id||null,
    saved_directions:config.agents.map(a=>({name:a.name,revision:a.general_context.revision})),
    direct_prompt_sha256:config.chat_prompts.find(t=>t.scope==='direct').prompt_sha256}});
 }catch(error){result.status='failed';result.error=error.message;throw error;}
 finally{fs.writeFileSync(root+'/docs/evidence/administrator'+(apply?'-live':'')+'.json',JSON.stringify(result,null,2)+'\n');await browser.close();}
 console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(String(error.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
