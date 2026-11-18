/* Real schedule UI; approval lifecycle is a browser-only fixture, never a native approval. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8765',root='/workspace',fixture='aaaaaaaa-1111-4111-8111-111111111111';
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],nativeWrites=[];
 let fixturePending=false,fixtureDecision=null;
 const result={checked_at:new Date().toISOString(),approval_lifecycle_uses_browser_fixture:true};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method())&&new URL(r.url()).pathname.startsWith('/api/')&&!r.url().includes(fixture))nativeWrites.push(new URL(r.url()).pathname);});
 const api=async path=>{const r=await page.request.get(base+'/api/'+path);assert.equal(r.status(),200);return r.json();};
 try{
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisModes&&window.JarvisTasks);
  await page.locator('#cronModeBtn').click();await page.locator('#cronPanel').waitFor({state:'visible'});
  const data=await api('cron-jobs'),job=data.jobs.find(j=>j.title==='Daily OSINT tools and techniques research');assert(job);
  await page.locator('.cron-card[data-job-id="'+job.id+'"]').waitFor();
  const card=page.locator('.cron-card[data-job-id="'+job.id+'"]');
  assert((await card.innerText()).includes('0 9 * * * · Europe/Athens'));
  assert((await card.innerText()).includes('Next run:'));assert(!await page.locator('#chatRow').isVisible());
  assert(!await page.locator('#feed').isVisible());assert.equal(await page.locator('[data-csi-auto]').count(),0);
  await card.getByRole('button',{name:'Edit',exact:true}).click();assert.equal(await page.locator('#cronTitle').inputValue(),job.title);
  assert.equal(await page.locator('#cronExpression').inputValue(),'0 9 * * *');await page.locator('#cancelCronBtn').click();
  await page.screenshot({path:root+'/docs/evidence/cron-jobs-desktop.png',fullPage:true});
  await page.setViewportSize({width:393,height:852});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:root+'/docs/evidence/cron-jobs-mobile.png',fullPage:true});
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.JarvisModes?.snapshot().mode==='cron');
  await page.locator('.cron-card[data-job-id="'+job.id+'"]').waitFor();
  const run=JSON.parse(fs.readFileSync(root+'/docs/evidence/osint-first-run.json','utf8'));assert(run.linkedIssueId);
  await page.setViewportSize({width:1440,height:1000});await page.locator('#projectsModeBtn').click();
  await page.locator('.project-list-item[data-project-id="'+run.linkedIssueId+'"]').click();
  await page.waitForTimeout(4500);
  assert.equal(await page.locator('[data-csi-auto]').count(),0,'Routine project progress opened a popup');
  await page.evaluate(()=>{
   window.dispatchEvent(new CustomEvent('jarvis-ai-activity',{detail:{kind:'tool',request_id:'browser-fixture-tool',tool:{name:'research_sources'}}}));
   window.dispatchEvent(new CustomEvent('jarvis-ai-activity',{detail:{kind:'error',request_id:'browser-fixture-error',message:'Fixture error; must stay inline.'}}));
  });
  await page.waitForTimeout(500);assert.equal(await page.locator('[data-csi-auto]').count(),0);
  await page.route('**/api/monitor',async route=>{
   const response=await route.fetch(),body=await response.json();
   if(fixturePending)body.approvals=[...(body.approvals||[]),{id:fixture,type:'request_board_approval',status:'pending',
    issue_ids:[run.linkedIssueId],proposal:{title:'Browser fixture approval',summary:'UI verification only. No native approval or work is created.'}}];
   await route.fulfill({response,json:body});
  });
  await page.route('**/api/approvals/'+fixture+'/decision',async route=>{
   fixtureDecision=route.request().postDataJSON();assert.equal(fixtureDecision.decision,'approve');fixturePending=false;
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:fixture,status:'approved'})});
  });
  fixturePending=true;
  const approval=page.locator('[data-csi-auto] [data-approval-id="'+fixture+'"]');await approval.waitFor({state:'visible',timeout:25000});
  assert((await page.locator('[data-csi-auto]').innerText()).includes('YOUR APPROVAL IS REQUIRED'));
  assert(!(await page.locator('[data-csi-auto]').innerText()).includes('PUBLISHED JARVIS UPDATE'));
  await page.screenshot({path:root+'/docs/evidence/approval-only-popup.png',fullPage:true});
  await approval.getByRole('button',{name:'Approve',exact:true}).click();
  await page.locator('[data-csi-auto]').waitFor({state:'detached',timeout:25000});assert(fixtureDecision);
  assert.deepEqual(errors,[]);assert.deepEqual(nativeWrites,[]);
  Object.assign(result,{status:'passed',daily_native_job_id:job.id,cron_navigation_and_reload:true,
   existing_goal_form:true,mobile_checks:true,progress_and_chat_events_do_not_popup:true,
   only_pending_approval_opens:true,decision_closes_popup:true,native_mutations:0,browser_errors:errors});
 }catch(error){result.status='failed';result.error=error.message;throw error;}
 finally{fs.writeFileSync(root+'/docs/evidence/cron-jobs-ui.json',JSON.stringify(result,null,2)+'\n');await browser.close();}
 console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
