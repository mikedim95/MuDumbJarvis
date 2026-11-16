/* Real direct-chat regression: no Paperclip objective and no secret env bundle. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const root='/workspace',base='http://localhost:8765';
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[],mutations=[],replies=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{const p=new URL(r.url()).pathname;if(r.method()==='POST'&&p.startsWith('/api/'))mutations.push(p);});
 try{
  assert.equal((await page.request.post(base+'/api/chat',{data:{input:'unauthorized'}})).status(),401);
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
  await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisTasks&&document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
  await page.evaluate(()=>{document.getElementById('boot')?.classList.add('done');document.body.classList.remove('booting');document.body.classList.add('booted');});
  await page.locator('#commandMode').selectOption('chat');
  const before=(await (await page.request.get(base+'/api/tasks')).json()).tasks.map(t=>t.id).sort();
  async function ask(input,again=false){
   await page.locator('#chatInput').fill(input);
   const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/chat',{timeout:900000});
   const start=Date.now();await page.locator('#sendBtn').click();
   assert(await page.locator('#sendBtn').isDisabled(),'Chat must prevent overlapping submissions');
   if(again){await page.locator('#chatInput').fill('This queued draft must not submit while a reply is pending.');await page.locator('#chatInput').press('Enter');}
   const response=await pending,body=await response.json();
   assert.equal(response.status(),200,body.error||'Direct chat request failed');
   assert.equal(typeof body.text,'string');assert(body.text.trim());
   assert(!/Hermes stream error|session_model_lock|"runtime"\s*:/.test(body.text));
   assert.match(body.text.replace(/[*_`]/g,'').trim(),/^(?:4|four)[.!]?$/i,'Model must answer the actual question');
   await page.waitForFunction(value=>document.getElementById('feed').textContent.includes(value),body.text);
   await page.waitForFunction(()=>!document.getElementById('sendBtn').disabled);
   const result={input,reply:body.text,elapsed_seconds:(Date.now()-start)/1000,run_id:body.run_id||null};replies.push(result);
   console.log(JSON.stringify({event:'real_direct_reply',...result}));
  }
  await ask('What is two plus two? Reply with the number only.',true);
  await ask('Repeat your previous answer only.');
  const after=(await (await page.request.get(base+'/api/tasks')).json()).tasks.map(t=>t.id).sort();
  assert.deepEqual(after,before);assert.equal(mutations.filter(p=>p==='/api/tasks').length,0);
  assert.equal(mutations.filter(p=>p==='/api/chat').length,2,'Repeated Enter must not create an overlapping turn');
  assert.equal((await page.locator('#feed .jarvis').count()),2);
  await page.screenshot({path:root+'/docs/evidence/direct-chat-fixed.png',fullPage:true});
  assert.deepEqual(errors,[]);
  const result={status:'passed',checked_at:new Date().toISOString(),source:'Actual authenticated HUD direct-chat requests',
   real_replies:replies,contextual_followup_verified:true,no_overlapping_chat:true,task_history_unchanged:true,
   paperclip_task_submissions:0,chat_submissions:2,browser_errors:errors};
  fs.writeFileSync(root+'/docs/evidence/direct-chat-fixed.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
 }catch(error){
  await page.screenshot({path:root+'/.runtime/direct-chat-fix/20261116T103124Z/browser-failure.png',fullPage:true}).catch(()=>{});
  throw error;
 }finally{await browser.close();}
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
