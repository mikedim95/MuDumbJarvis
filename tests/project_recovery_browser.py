"""Exercise real recovery UI with intercepted mutations; never creates/retries live work."""
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from deploy.staffing import settings

ROOT='3cfa2dd1-4ba0-46cd-ade7-e92ecb82ca33'
RUN='4edc2f0c-b63b-47a7-adeb-64e2456a1638'
ACTION='00f71421-4038-4e9a-91a8-40ea452eae84'
RECOVERY={'run_id':RUN,'action_id':ACTION,'can_retry':True,'needs_reconciliation':True,
    'reason':'The agent connection failed (HTTP 502).','next_action':'Review the stopped execution.'}
script='''
window.__recoveryWrites=[];window.__recoveryTick=0;window.__retryFailOnce=false;
const original=window.fetch;
window.fetch=async function(url,options={}){
 const path=new URL(typeof url==='string'?url:url.url,location.href).pathname;
 if(options.method==='POST'&&/\\/api\\/tasks\\/[^/]+\\/(retry|resolve-execution)$/.test(path)){
  const body=JSON.parse(options.body);window.__recoveryWrites.push({path,body});
  if(path.endsWith('/retry')&&window.__retryFailOnce){window.__retryFailOnce=false;throw new TypeError('Simulated lost response');}
  await new Promise(resolve=>setTimeout(resolve,100));
  return new Response(JSON.stringify(path.endsWith('/retry')?{accepted:true,requestId:'fixture-request'}:
    {resolution_saved:true,task:{id:ROOT,status:'todo'}}),{headers:{'Content-Type':'application/json'}});
 }
 const response=await original.call(this,url,options);
 if(!response.ok)return response;
 if(path==='/api/agents/work'){
  const data=await response.json(),ceo=data.agents.find(a=>a.id===data.ceo_id);
  ceo.activity='blocked';ceo.questions=[];ceo.status_reason=RECOVERY.reason;ceo.published_update='Fixture '+window.__recoveryTick;ceo.recent_activity=null;
  ceo.work=[{id:ROOT,identifier:'JAR-84',title:'Project recovery fixture',state:'blocked',status:'blocked',recovery:RECOVERY,
    mission:{id:ROOT,title:'Existing project'}}];
  return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
 }
 if(path==='/api/tasks/'+ROOT){
  const data=await response.json();data.status='blocked';data.state='blocked';data.recovery=RECOVERY;
  data.brief={progress:RECOVERY.reason,result:''};
  return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
 }
 return response;
};
'''
script='const ROOT='+json.dumps(ROOT)+',RECOVERY='+json.dumps(RECOVERY)+';\n'+script
options=webdriver.ChromeOptions();options.page_load_strategy='eager'
for flag in ('--headless','--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader'):
    options.add_argument(flag)
options.set_capability('goog:loggingPrefs',{'browser':'ALL'})
Path('/tmp/jarvis-recovery').mkdir(exist_ok=True)
with webdriver.Chrome(service=Service('/usr/bin/chromedriver'),options=options) as browser:
    browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':script})
    wait=WebDriverWait(browser,35)
    for width in (1440,410):
        browser.set_window_size(width,1000);browser.get('http://127.0.0.1:8765/hud/')
        browser.add_cookie({'name':'jarvis_token','value':settings()['JARVIS_HUD_TOKEN'],'path':'/'})
        browser.execute_script("localStorage.setItem('jarvis-app-mode','direct');localStorage.setItem('jarvis-right-panel','open')")
        browser.get('http://127.0.0.1:8765/hud/')
        wait.until(lambda b:b.execute_script('return !!window.JarvisRecovery&&!!window.JarvisModes&&!!window.JarvisAgents'))
        browser.execute_script("JarvisPanels.open('right')")
        card=wait.until(lambda b:b.find_element(By.CSS_SELECTOR,'#agentLeader .agent-station'))
        assert card.find_elements(By.CSS_SELECTOR,'.agent-question-badge')
        card.click()
        button=wait.until(lambda b:b.find_element(By.CSS_SELECTOR,'#agentDetails [data-resolve-task-id]'))
        button.click()
        field=browser.find_element(By.CSS_SELECTOR,'#agentDetails .execution-resolution textarea')
        draft='The stopped execution is verified. Preserve existing artifacts and continue only the existing task.'
        field.send_keys(draft)
        browser.execute_script("window.__recoveryTick++;dispatchEvent(new Event('jarvis-recovery-changed'))")
        wait.until(lambda b:'Fixture 1' in b.find_element(By.ID,'agentPublished').text)
        assert browser.find_element(By.CSS_SELECTOR,'#agentDetails .execution-resolution textarea').get_attribute('value')==draft
        checkbox=browser.find_element(By.CSS_SELECTOR,'#agentDetails .execution-resolution input');checkbox.click()
        browser.find_element(By.CSS_SELECTOR,'#agentDetails .execution-resolution button').click()
        wait.until(lambda b:len(b.execute_script('return __recoveryWrites'))==1)
        body=browser.execute_script('return __recoveryWrites[0].body')
        assert body['action_id']==ACTION and body['provider_stopped'] and body['evidence']==draft
        browser.execute_script('JarvisModes.openProject(arguments[0])',ROOT)
        wait.until(lambda b:b.execute_script('return JarvisModes.snapshot().mode==="projects"'))
        browser.execute_script("JarvisModes.setProjectView('context');JarvisPanels.close('right')")
        tree=wait.until(lambda b:b.find_element(By.CSS_SELECTOR,'#projectDelegation [data-resolve-task-id="'+ROOT+'"]'))
        assert tree.is_displayed()
        tree.click()
        browser.save_screenshot('/tmp/jarvis-recovery/'+str(width)+'.png')
        assert browser.execute_script('return document.body.scrollWidth<=innerWidth')
        print(width,'px: visible CEO action badge, inline resolution, preserved draft, scoped project control passed',flush=True)
    # Use the real request client with intercepted responses to verify its durable
    # nonce semantics independently of native task timing.
    browser.execute_script('window.__recoveryWrites=[]')
    browser.execute_async_script('''const done=arguments[arguments.length-1];Promise.all([
      JarvisTasks.retry(arguments[0],arguments[1]),JarvisTasks.retry(arguments[0],arguments[1])
    ]).then(()=>done(true),e=>done(e.message));''',ROOT,RUN)
    writes=browser.execute_script('return __recoveryWrites');assert len(writes)==1
    browser.execute_async_script('const done=arguments[arguments.length-1];JarvisTasks.retry(arguments[0],arguments[1]).then(()=>done(true),e=>done(e.message))',ROOT,RUN)
    writes=browser.execute_script('return __recoveryWrites');assert len(writes)==2 and writes[0]['body']['request_id']!=writes[1]['body']['request_id']
    browser.execute_script('window.__retryFailOnce=true;window.__recoveryWrites=[]')
    for _ in range(2):
        browser.execute_async_script('const done=arguments[arguments.length-1];JarvisTasks.retry(arguments[0],arguments[1]).then(()=>done(true),e=>done(e.message))',ROOT,RUN)
    writes=browser.execute_script('return __recoveryWrites');assert len(writes)==2 and writes[0]['body']['request_id']==writes[1]['body']['request_id']
    errors=[e['message'] for e in browser.get_log('browser') if 'Uncaught' in e['message']]
    assert not errors,errors
    print('Retry requests: concurrent clicks coalesce, acknowledged attempts get fresh IDs, lost responses retain the same ID',flush=True)
