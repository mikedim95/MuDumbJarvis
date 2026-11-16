/* Real default AI-only screen, Codex inference and agent-triggered tool popup. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const root='/workspace',base='http://localhost:8765';
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[],posts=[],activity=[],replies=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname.startsWith('/api/'))posts.push(new URL(r.url()).pathname);});
 page.on('websocket',socket=>socket.on('framereceived',frame=>{
  try{const event=JSON.parse(frame.payload);if(event.type==='chat_activity')activity.push(event);}catch{}
 }));
 await page.addInitScript(()=>{
  // Existing operator-view preferences must not reopen the old dashboard.
  localStorage.setItem('jarvis-csi-open','true');localStorage.setItem('jarvis-command-mode','objective');
 });
 async function api(path){const r=await page.request.get(base+'/api/'+path);assert.equal(r.status(),200);return r.json();}
 try{
  assert.equal((await page.request.post(base+'/api/chat',{data:{input:'unauthorized'}})).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
  await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisTasks&&document.getElementById('aiProvider')?.textContent.includes('gpt-6.1-sol'));
  assert(await page.locator('body').evaluate(el=>el.classList.contains('ai-minimal')));
  assert.equal(await page.locator('#commandMode').inputValue(),'chat');
  for(const selector of ['#commandModes','#taskPanel','#clearBtn','#csiLaunch'])assert(!await page.locator(selector).isVisible(),selector+' should not be on AI screen');
  assert.equal(await page.locator('#csiWorkspace').count(),0);
  const visible=await page.locator('#grid button').evaluateAll(nodes=>nodes.filter(el=>el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden').map(el=>el.id));
  assert.deepEqual(visible,['sendBtn']);
  await page.waitForTimeout(3500);
  assert.equal(await page.locator('[data-csi-auto] [data-csi-window]').count(),0,'Historical tasks must not cause a popup storm');
  const before=(await api('tasks')).tasks.map(t=>t.id).sort();
  await page.screenshot({path:root+'/docs/evidence/minimal-ai-empty.png',fullPage:true});
  async function ask(input){
   await page.locator('#chatInput').fill(input);const started=Date.now();
   const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/chat',{timeout:180000});
   await page.locator('#sendBtn').click();const r=await pending,body=await r.json();
   assert.equal(r.status(),200,body.error||'Chat failed');
   assert.equal(body.runtime.provider,'openai-codex');assert.equal(body.runtime.model,'gpt-6.1-sol');
   assert.equal(body.runtime.model_lock,'confirmed');
   assert(body.text.trim());await page.waitForFunction(text=>document.getElementById('feed').textContent.includes(text),body.text);
   replies.push({input,reply:body.text,run_id:body.run_id,runtime:body.runtime,seconds:(Date.now()-started)/1000,request_id:body.request_id});
   console.log(JSON.stringify({event:'verified_codex_reply',run_id:body.run_id,provider:body.runtime.provider,model:body.runtime.model,seconds:(Date.now()-started)/1000}));
   return body;
  }
  const first=await ask('Reply exactly CODEX_CHAT_READY.');assert.equal(first.text.trim(),'CODEX_CHAT_READY');
  const follow=await ask('Repeat your previous answer exactly.');assert.equal(follow.text.trim(),'CODEX_CHAT_READY');
  assert.equal(await page.locator('[data-csi-auto] [data-csi-window]').count(),0,'Ordinary replies should not open dashboards');
  const tool=await ask('Use your available local_ollama_models tool to retrieve the installed model names and sizes. List the returned model names. This is only a metadata read; use Codex for inference.');
  assert(tool.tools.some(t=>t.name==='local_ollama_models'),'A real tool execution is required');
  const observed=activity.find(e=>e.kind==='tool'&&e.request_id===tool.request_id&&e.tool?.name==='local_ollama_models');assert(observed,'Tool event must arrive over the authenticated backend socket');
  await page.locator('[data-csi-auto] [data-csi-window]').first().waitFor({state:'visible'});
  assert.match(await page.locator('[data-csi-auto]').innerText(),/local_ollama_models|tool/i);
  assert.equal(posts.filter(p=>p==='/api/tasks').length,0);assert.equal(posts.filter(p=>p==='/api/chat').length,3);
  assert.deepEqual((await api('tasks')).tasks.map(t=>t.id).sort(),before);
  await page.screenshot({path:root+'/docs/evidence/minimal-ai-agent-popup.png',fullPage:true});
  await page.setViewportSize({width:393,height:852});await page.waitForTimeout(500);
  for(const selector of ['#chatInput','#sendBtn']){const b=await page.locator(selector).boundingBox();assert(b&&b.x>=0&&b.y>=0&&b.x+b.width<=394&&b.y+b.height<=853,selector+' outside mobile viewport');}
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:root+'/docs/evidence/minimal-ai-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  const result={status:'passed',checked_at:new Date().toISOString(),provider:'openai-codex',model:'gpt-6.1-sol',
   real_replies:replies,manual_dashboard_controls_visible:false,old_view_preferences_overridden:true,
   ordinary_chat_has_no_popups:true,agent_tool_popup_triggered:true,trigger_request_id:tool.request_id,
   source:'Real authenticated HUD chat and backend WebSocket tool event',paperclip_tasks_created:0,
   history_unchanged:true,mobile_input_visible:true,local_inference_accepted:false,browser_errors:errors};
  fs.writeFileSync(root+'/docs/evidence/minimal-codex-chat.json',JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({status:'passed',provider:result.provider,model:result.model,tool_popup:true,chat_requests:replies.length}));
 }catch(error){await page.screenshot({path:root+'/.runtime/minimal-ai-failure.png',fullPage:true}).catch(()=>{});throw error;}
 finally{await browser.close();}
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
