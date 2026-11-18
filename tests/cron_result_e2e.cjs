/* Read real cron results and native artifact bytes; never submit or retry work. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8765',root='/workspace';
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
 const result={checked_at:new Date().toISOString()};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method())&&new URL(r.url()).pathname.startsWith('/api/'))writes.push(new URL(r.url()).pathname);});
 const api=async path=>{const response=await page.request.get(base+'/api/'+path);assert.equal(response.status(),200);return response.json();};
 try{
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisModes&&window.JarvisTasks);
  await page.locator('#generalModeBtn').click();await page.locator('#generalCronBtn').click();
  const job=(await api('cron-jobs')).jobs.find(j=>j.title==='Daily OSINT tools and techniques research');assert(job);
  const taskId=job.active_issue?.id||job.last_run?.linkedIssueId;assert(taskId);
  const task=await api('tasks/'+taskId),snapshot=await api('tasks/'+taskId+'/events');assert.equal(task.status,'done');
  const reply=[...task.comments].filter(c=>c.authorAgentId===task.assigneeAgentId&&!c.body.startsWith('[JARVIS ')).sort((a,b)=>a.createdAt.localeCompare(b.createdAt)).at(-1);assert(reply);
  const report=snapshot.artifacts.find(a=>a.issueId===taskId&&a.originalFilename==='technical-report.md');assert(report);
  const catalog=snapshot.artifacts.find(a=>a.issueId!==taskId&&/^osint-catalog-v\d+\.json$/.test(a.originalFilename));assert(catalog);
  async function openLatest(){
   await page.locator('#generalModeBtn').click();await page.locator('#generalCronBtn').click();
   const button=page.locator('.cron-card[data-job-id="'+job.id+'"]').getByRole('button',{name:'Open latest run',exact:true});
   await button.click();await page.waitForFunction(id=>window.JarvisModes?.snapshot().isWorkView&&window.JarvisTasks?.snapshot().objectiveId===id,taskId);
  }
  await openLatest();
  const replyNode=page.locator('#feed .msg.jarvis[data-ceo-comment-id="'+reply.id+'"]');
  await replyNode.waitFor({state:'visible'});assert((await replyNode.innerText()).includes(reply.body.slice(0,100)));
  const panel=page.locator('#feed .project-results[data-project-id="'+taskId+'"]');await panel.waitFor({state:'visible'});
  const file=panel.locator('[data-artifact-id="'+report.id+'"]');
  await file.locator('summary').waitFor({state:'visible'});
  assert.equal(await file.evaluate(node=>node.open),false);
  await file.locator('summary').click();
  const nativeReport=await page.request.get(base+'/api/tasks/'+taskId+'/artifacts/'+report.id);assert.equal(nativeReport.status(),200);
  const reportText=await nativeReport.text();
  await page.waitForFunction(({id,text})=>document.querySelector('[data-artifact-id="'+id+'"] .project-file-preview')?.textContent===text,{id:report.id,text:reportText});
  assert.equal(await file.getByRole('link',{name:'Download',exact:true}).getAttribute('href'),'/api/tasks/'+taskId+'/artifacts/'+report.id);
  const workerFile=panel.locator('[data-artifact-id="'+catalog.id+'"]');await workerFile.locator('summary').click();
  const nativeCatalog=await page.request.get(base+'/api/tasks/'+catalog.issueId+'/artifacts/'+catalog.id);assert.equal(nativeCatalog.status(),200);
  const catalogText=await nativeCatalog.text();
  await page.waitForFunction(({id,text})=>document.querySelector('[data-artifact-id="'+id+'"] .project-file-preview')?.textContent===text,{id:catalog.id,text:catalogText});
  await workerFile.locator('summary').click();
  assert.equal(await page.locator('[data-csi-auto]').count(),0);
  await file.scrollIntoViewIfNeeded();await page.screenshot({path:root+'/docs/evidence/cron-result-desktop.png',fullPage:true});
  await page.locator('#directModeBtn').click();assert(!await panel.isVisible());assert(!await replyNode.isVisible());
  await openLatest();await page.waitForTimeout(3500);assert.equal(await replyNode.count(),1);
  // Emulate an older result being evicted from the bounded visible feed.
  await replyNode.evaluate(node=>node.remove());await page.locator('#directModeBtn').click();await openLatest();
  await replyNode.waitFor({state:'visible'});assert.equal(await replyNode.count(),1);
  await page.setViewportSize({width:393,height:852});await file.scrollIntoViewIfNeeded();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:root+'/docs/evidence/cron-result-mobile.png',fullPage:true});
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(id=>window.JarvisTasks?.snapshot().objectiveId===id&&window.JarvisModes?.snapshot().isWorkView,taskId);
  await replyNode.waitFor({state:'visible'});
  await file.locator('summary').waitFor({state:'visible'});
  assert.equal(await file.evaluate(node=>node.open),false);
  await file.locator('summary').click();
  await page.waitForFunction(({id,text})=>document.querySelector('[data-artifact-id="'+id+'"] .project-file-preview')?.textContent===text,{id:report.id,text:reportText});
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  Object.assign(result,{status:'passed',job_id:job.id,task_id:taskId,task_identifier:task.identifier,
   actual_open_latest_run_button:true,published_reply_restored:true,report_matches_native_bytes:true,report_characters:reportText.length,
   worker_catalog_matches_native_bytes:true,files:snapshot.artifacts.length,no_result_popups:true,
   repeated_navigation_without_duplicate_reply:true,evicted_reply_restored:true,reload_restores_result:true,mobile_checks:true,
   native_mutations:0,browser_errors:errors});
 }catch(error){result.status='failed';result.error=error.message;throw error;}
 finally{fs.writeFileSync(root+'/docs/evidence/cron-result-ui.json',JSON.stringify(result,null,2)+'\n');await browser.close();}
 console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(String(error.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
