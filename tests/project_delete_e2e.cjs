/* Temporarily remove the saved acceptance project, verify persistence, then Undo. */
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8765',root='/workspace';
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const errors=[],result={checked_at:new Date().toISOString()};let removed=false,target;
 page.on('pageerror',e=>errors.push(e.message));
 async function api(path,options){const r=await page.request.fetch(base+'/api/'+path,options);assert(r.ok(),path+' '+r.status());return r.json();}
 async function projects(p){await p.locator('#projectsModeBtn').click();await p.locator('.project-list-item').first().waitFor();}
 try{
  await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
  await page.waitForFunction(()=>window.JarvisModes&&window.JarvisTasks);
  const before=(await api('tasks')).tasks;
  target=before.find(t=>t.identifier==='JAR-57'&&!t.hiddenAt);assert(target,'Retained test project must exist');
  const baseline=await api('tasks/'+target.id),eventsBefore=await api('tasks/'+target.id+'/events');
  await projects(page);
  assert.equal(await page.locator('.project-item-arrow').count(),0);
  assert.equal(await page.locator('.project-delete-btn').count(),await page.locator('.project-list-item').count());
  const row=page.locator('.project-list-item[data-project-id="'+target.id+'"]');
  await row.click({position:{x:12,y:12}});
  await page.waitForFunction(id=>window.JarvisTasks.snapshot().objectiveId===id&&window.JarvisModes.snapshot().projectView==='context',target.id);
  await page.locator('#projectBackBtn').click();
  const pending=page.waitForResponse(r=>r.request().method()==='DELETE'&&new URL(r.url()).pathname==='/api/projects/'+target.id);
  await page.locator('.project-delete-btn[data-delete-project-id="'+target.id+'"]').click();
  const deleted=await pending;assert(deleted.ok(),'Native list removal must be confirmed');removed=true;
  await page.waitForFunction(id=>!document.querySelector('.project-list-item[data-project-id="'+id+'"]'),target.id);
  assert.equal(await page.evaluate(()=>window.JarvisModes.snapshot().projectView),'list','Delete must not open a project');
  assert.equal(await page.evaluate(()=>window.JarvisTasks.snapshot().objectiveId),null,'Removing the selected project clears its active scope');
  assert(await page.locator('#undoProjectRemoval').isVisible());
  await page.screenshot({path:root+'/docs/evidence/project-delete-removed.png',fullPage:true});
  const fresh=await context.newPage();fresh.on('pageerror',e=>errors.push(e.message));
  await fresh.goto(base+'/hud/',{waitUntil:'domcontentloaded'});await fresh.waitForFunction(()=>window.JarvisModes&&window.JarvisTasks);
  await projects(fresh);assert.equal(await fresh.locator('.project-list-item[data-project-id="'+target.id+'"]').count(),0);
  const retained=await api('tasks/'+target.id);assert(retained.hiddenAt);assert.equal(retained.status,baseline.status);
  assert.equal(retained.description,baseline.description);assert.deepEqual(retained.comments.map(c=>c.id).sort(),baseline.comments.map(c=>c.id).sort());
  assert.deepEqual(retained.children.map(c=>c.id).sort(),baseline.children.map(c=>c.id).sort());
  const afterEvents=await api('tasks/'+target.id+'/events');assert.deepEqual(afterEvents.artifacts.map(a=>a.id).sort(),eventsBefore.artifacts.map(a=>a.id).sort());
  await page.locator('#undoProjectRemoval').click();
  await page.locator('.project-list-item[data-project-id="'+target.id+'"]').waitFor();removed=false;
  assert.equal((await api('tasks/'+target.id)).hiddenAt,null);await fresh.close();
  await page.screenshot({path:root+'/docs/evidence/project-delete-desktop.png',fullPage:true});
  await page.setViewportSize({width:393,height:852});
  const button=page.locator('.project-delete-btn[data-delete-project-id="'+target.id+'"]');await button.scrollIntoViewIfNeeded();
  const b=await button.boundingBox();assert(b&&b.height>=44&&b.x>=0&&b.x+b.width<=394);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:root+'/docs/evidence/project-delete-mobile.png',fullPage:true});
  assert.deepEqual((await api('tasks')).tasks.map(t=>t.id).sort(),before.map(t=>t.id).sort());
  assert.deepEqual(errors,[]);
  Object.assign(result,{status:'passed',project:target.identifier,whole_row_opens:true,no_right_arrows:true,
   delete_does_not_open_context:true,removal_persists_across_browser_views:true,history_and_artifacts_preserved:true,
   undo_restored_original_project:true,mobile_delete_target_visible:true,browser_errors:errors});
 }catch(error){result.status='failed';result.error=error.message;throw error;}
 finally{
  if(removed&&target){await api('projects/'+target.id+'/restore',{method:'POST'});result.test_cleanup_restored_project=true;}
  fs.writeFileSync(root+'/docs/evidence/project-delete.json',JSON.stringify(result,null,2)+'\n');await browser.close();
 }
 console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(String(e.message).split('Call log:')[0].replaceAll(process.env.JARVIS_HUD_TOKEN||'UNCONFIGURED','[REDACTED]'));process.exitCode=1;});
