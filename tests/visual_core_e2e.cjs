/* Read-only HUD acceptance; controlled browser fixtures never wake agents. */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const root='/workspace',base='http://localhost:8765';
const preview=process.argv.includes('--preview'),baseline=process.argv.includes('--baseline');
const fallback=process.argv.includes('--fallback');
const variant=baseline?'before':fallback?'fallback':preview?'preview':'live';
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
async function main() {
  const browser=await chromium.launch({headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required',
    ...(fallback?['--disable-webgl']:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])]});
  const context=await browser.newContext({viewport:{width:1600,height:1100}});
  const page=await context.newPage(),errors=[],shaderErrors=[],mutations=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error'&&/Shader Error|VALIDATE_STATUS|WebGLProgram/.test(m.text()))shaderErrors.push(m.text());});
  page.on('request',r=>{if(r.method()!=='GET'&&/\/api\/(tasks|agents|approvals|chat)/.test(r.url()))mutations.push(r.method()+' '+new URL(r.url()).pathname);});
  async function api(endpoint) {const r=await page.request.get(base+'/api/'+endpoint);assert.equal(r.status(),200);return r.json();}
  async function settle() {
    await page.evaluate(()=>{document.getElementById('boot')?.classList.add('done');document.body.classList.remove('booting');document.body.classList.add('booted');});
    await page.waitForTimeout(700);
  }
  try {
    assert.equal((await page.request.get(base+'/api/tasks')).status(),401);
    await page.goto(base+'/hud/',{waitUntil:'domcontentloaded'});
    await page.locator('#pinInput').fill(process.env.JARVIS_HUD_TOKEN);
    await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.locator('#pinBtn').click()]);
    if(preview) {
      await page.route('**/hud/**',async route=>{
        const name=decodeURIComponent(new URL(route.request().url()).pathname.slice('/hud/'.length))||'index.html';
        if(!['index.html','tasks.js','core/visual-core.js','core/LICENSE.txt'].includes(name))return route.continue();
        return route.fulfill({status:200,body:fs.readFileSync(path.join(root,'server/hud',name)),
          contentType:name.endsWith('.html')?'text/html':name.endsWith('.js')?'application/javascript':'text/plain'});
      });
      await page.reload({waitUntil:'domcontentloaded'});
    }
    await page.waitForFunction(()=>document.getElementById('taskConnection').textContent.includes('Paperclip connected'));
    await settle();
    if(baseline) {
      await page.screenshot({path:root+'/docs/evidence/visual-core-before.png',fullPage:true});
      console.log(JSON.stringify({status:'baseline_captured',backend_mutations:mutations}));return;
    }
    await page.waitForFunction(()=>window.JarvisVisualCore?.snapshot().frame>3);
    const snapshot=()=>page.evaluate(()=>window.JarvisVisualCore.snapshot());
    const initial=await snapshot();assert.equal(initial.arrangement,'ring');
    assert.equal(initial.renderer,fallback?'canvas2d':'webgl2');assert(initial.particles>500);
    const first=await page.locator('#reactor').screenshot();await page.waitForTimeout(900);
    const next=await page.locator('#reactor').screenshot();assert.notEqual(sha(first),sha(next),'The particle circle must move');
    assert((await snapshot()).frame>initial.frame+3);
    // Real persisted result remains usable, independently of visual fixtures.
    await page.locator('#taskHistory button').filter({hasText:/^JAR-42 ·/}).click();
    await page.waitForFunction(()=>document.getElementById('taskDetail').textContent.startsWith('JAR-42 · done'));
    await page.waitForFunction(()=>document.getElementById('stateLabel').textContent==='COMPLETE');
    const task=await api('tasks/27b20fae-a51b-43ab-9f36-514199fab977');assert.equal(task.status,'done');
    const mon=await api('tasks/'+task.id+'/monitor');assert(mon.evidence.some(e=>e.verified&&e.completion_verified));
    const artifact=mon.artifacts.find(a=>a.originalFilename==='test_demo.py');assert(artifact);
    const bytes=await page.request.get(base+'/api/tasks/'+task.id+'/artifacts/'+artifact.id);assert.equal(bytes.status(),200);
    assert.equal(sha(await bytes.body()),artifact.sha256);
    const savedCore=await snapshot();
    await settle();await page.screenshot({path:root+'/docs/evidence/visual-core-'+variant+'-desktop.png',fullPage:true});
    // Exercise the real public audio tap with a silent, browser-local oscillator.
    // It is a test signal, not an agent run, microphone recording or audible demo.
    await page.locator('#commandMode').selectOption('chat');
    await page.evaluate(async()=>{
      const context=new AudioContext();const oscillator=context.createOscillator();oscillator.frequency.value=220;
      const detach=window.JarvisVisualCore.attachAudio('output',context,oscillator);
      const read=window.JarvisCoreSignals.read;
      window.JarvisCoreSignals.read=()=>({state:'speaking',playing:true,level:0,label:'SPEAKING',hint:'BROWSER TEST SIGNAL'});
      window.coreAudioTest={context,oscillator,detach,read};await context.resume();oscillator.start();
      window.dispatchEvent(new Event('jarvis-core-state'));
    });
    await page.waitForFunction(()=>window.JarvisVisualCore.snapshot().audioEnergy.average>0.1);
    const audio=await snapshot();assert.equal(audio.state,'speaking');
    await page.evaluate(async()=>{const f=window.coreAudioTest;f.detach();f.oscillator.stop();await f.context.close();window.JarvisCoreSignals.read=f.read;delete window.coreAudioTest;window.dispatchEvent(new Event('jarvis-core-state'));});
    // A direct-chat state transition must reach the same visual without tasks.
    await page.evaluate(()=>{window.savedVisualRead=window.JarvisCoreSignals.read;window.JarvisCoreSignals.read=()=>({state:'thinking',label:'PROCESSING',hint:'CONTROLLED VISUAL FIXTURE'});window.dispatchEvent(new Event('jarvis-core-state'));});
    await page.waitForFunction(()=>window.JarvisVisualCore.snapshot().state==='thinking');
    await page.evaluate(()=>{window.JarvisCoreSignals.read=window.savedVisualRead;delete window.savedVisualRead;window.dispatchEvent(new Event('jarvis-core-state'));});
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>window.JarvisVisualCore.snapshot().reducedMotion);
    const still=await snapshot();await page.waitForTimeout(600);
    assert.equal((await snapshot()).motionTime,0);assert((await snapshot()).frame<=still.frame+2,'Reduced motion must stop continuous animation');
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.waitForFunction(()=>window.JarvisVisualCore.snapshot().reducedMotion===false);
    const resumed=await snapshot();
    await page.waitForFunction(frame=>window.JarvisVisualCore.snapshot().frame>frame,resumed.frame,{timeout:10000});
    await page.locator('#commandMode').selectOption('objective');
    await page.setViewportSize({width:393,height:852});await settle();
    await page.waitForTimeout(500);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile layout overflows');
    const rect=await page.locator('#reactor').boundingBox();assert(rect.width>150&&rect.width<=393);
    for(const selector of ['#commandMode','#taskRefresh','#chatInput','#sendBtn']) {
      const box=await page.locator(selector).boundingBox();
      assert(box&&box.x>=0&&box.x+box.width<=393,selector+' is clipped on mobile');
    }
    await page.screenshot({path:root+'/docs/evidence/visual-core-'+variant+'-mobile.png',fullPage:true});
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.JarvisVisualCore?.snapshot().frame>0);
    await page.waitForFunction(()=>document.getElementById('taskDetail').textContent.startsWith('JAR-42 · done'));
    assert.deepEqual(errors,[]);assert.deepEqual(shaderErrors,[]);assert.deepEqual(mutations,[]);
    const result={status:'passed',checked_at:new Date().toISOString(),variant,
      source:preview?'Authenticated HUD with source frontend preview; real read-only FastAPI/Paperclip APIs':'Deployed authenticated HUD; real read-only FastAPI/Paperclip APIs',
      core:savedCore,animation_changes_verified:true,real_audio_analysis_verified:audio.audioEnergy,
      direct_state_reactivity:true,reduced_motion_verified:true,mobile_layout_verified:true,
      persisted_result_and_artifact_verified:{issue:task.id,artifact:artifact.id,sha256:artifact.sha256},
      history_after_reload:true,unauthenticated_api_denied:true,backend_mutations:mutations,
      no_agent_inference_requested:true,page_errors:errors,shader_errors:shaderErrors,
      controlled_fixtures:'Browser-only speaking/thinking signals and a silent oscillator; not represented as agent execution.'};
    fs.writeFileSync(root+'/docs/evidence/visual-core-'+variant+'.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  } finally {await browser.close();}
}
main().catch(error=>{
  let s=String(error.message||error).split('Call log:')[0].trim();
  const token=process.env.JARVIS_HUD_TOKEN;if(token)s=s.replaceAll(token,'[REDACTED]');
  console.error(s);process.exitCode=1;
});
