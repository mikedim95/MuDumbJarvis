"""Profile activity and long CEO questions; all replies are intercepted locally."""
import json
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from deploy.staffing import settings


ROOT = '3cfa2dd1-4ba0-46cd-ade7-e92ecb82ca33'
QUESTION = '6b91e86c-24c6-4f90-a660-745e8422860b'
CEO = settings()['PAPERCLIP_CEO_AGENT_ID']
script = '''
window.__activityTick=0;window.__hasQuestion=true;window.__replyWrites=[];window.__failReply=true;
const original=window.fetch;
window.fetch=async function(url,options={}){
 const parsed=new URL(typeof url==='string'?url:url.url,location.href),path=parsed.pathname;
 if(options.method==='POST'&&path==='/api/tasks/'+ROOT+'/messages'){
   window.__replyWrites.push(JSON.parse(options.body));
   if(window.__failReply){window.__failReply=false;return new Response(JSON.stringify({detail:'Fixture connection interrupted.'}),{status:502});}
   window.__hasQuestion=false;
   return new Response(JSON.stringify({task:{id:ROOT,status:'todo'},interaction_id:QUESTION}),{headers:{'Content-Type':'application/json'}});
 }
 const response=await original.call(this,url,options);
 if(!response.ok||path!=='/api/agents/work')return response;
 const data=await response.json(),ceo=data.agents.find(a=>a.id===data.ceo_id),project=parsed.searchParams.has('mission_id');
 ceo.current_work={id:ROOT,identifier:'JAR-84',title:'Review the research handoff',state:'blocked',
   mission:{id:ROOT,title:'Research mission'},reason:'Waiting for your answer.'};
 ceo.package_decisions=[
   {child:'JAR-89',package:'nmap',decision:'accepted',installation:{status:'ready'},task:{id:ROOT},mission:{id:ROOT}},
   {child:'JAR-17',package:'unrelated-package',decision:'accepted',task:{id:'other'},mission:{id:'other'}}
 ];
 ceo.recent_activity={available:true,latest:{summary:(project?'Project':'General')+' activity fixture '+window.__activityTick,
   kind:'published_update',at:'2026-11-19T10:20:24Z',task:{id:ROOT,identifier:'JAR-84'}}};
 ceo.questions=window.__hasQuestion?[{id:QUESTION,question:'Please provide the missing decision. '+
   'This long explanation describes the existing evidence and the specific unresolved operational issue. '.repeat(5),
   task:{id:ROOT,identifier:'JAR-84'},mission:{id:ROOT,title:'Research mission'}}]:[];
 ceo.work=[];
 return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
};
'''
script = 'const ROOT=' + json.dumps(ROOT) + ',QUESTION=' + json.dumps(QUESTION) + ';\n' + script
options = webdriver.ChromeOptions()
options.page_load_strategy = 'eager'
for flag in ('--headless', '--no-sandbox', '--disable-dev-shm-usage', '--use-gl=angle', '--use-angle=swiftshader'):
    options.add_argument(flag)
options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
Path('/tmp/jarvis-agent-activity').mkdir(exist_ok=True)
with webdriver.Chrome(service=Service('/usr/bin/chromedriver'), options=options) as browser:
    browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': script})
    wait = WebDriverWait(browser, 35, ignored_exceptions=(StaleElementReferenceException,))
    for width in (1440, 410):
        browser.set_window_size(width, 1000)
        browser.get('http://127.0.0.1:8765/hud/')
        browser.add_cookie({'name': 'jarvis_token', 'value': settings()['JARVIS_HUD_TOKEN'], 'path': '/'})
        browser.get('http://127.0.0.1:8765/hud/')
        wait.until(lambda b: b.execute_script('return !!window.JarvisAgents&&!!window.JarvisModes'))
        browser.execute_script("JarvisModes.setMode('direct');JarvisPanels.open('right');JarvisAgents.open(arguments[0])", CEO)
        wait.until(lambda b: 'General activity fixture' in b.find_element(By.ID, 'agentPublished').text)
        assert 'Review the research handoff' in browser.find_element(By.ID, 'agentCurrent').text
        details = browser.find_element(By.ID, 'agentDetails').text
        assert 'JAR-89 · nmap · Installed' in details and 'unrelated-package' not in details
        button = wait.until(lambda b: b.find_element(By.CSS_SELECTOR, '.agent-question button[type=submit]'))
        assert browser.execute_script('''const n=arguments[0],r=n.getBoundingClientRect(),p=document.querySelector('#agentsPanel').getBoundingClientRect();
            return r.top>=p.top&&r.bottom<=p.bottom&&document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===n;''', button), 'Reply must be visible after opening a long question'
        field = browser.find_element(By.CSS_SELECTOR, '.agent-question textarea')
        draft = 'Fixture answer, intercepted locally without changing native work.'
        field.send_keys(draft)
        browser.execute_script("__activityTick++;dispatchEvent(new Event('jarvis-recovery-changed'))")
        wait.until(lambda b: 'fixture 1' in b.find_element(By.ID, 'agentPublished').text)
        assert browser.find_element(By.CSS_SELECTOR, '.agent-question textarea').get_attribute('value') == draft
        browser.find_element(By.CSS_SELECTOR, '.agent-question button[type=submit]').click()
        wait.until(lambda b: 'Fixture connection interrupted' in b.find_element(By.CSS_SELECTOR, '.agent-question-error').text)
        assert browser.find_element(By.CSS_SELECTOR, '.agent-question textarea').get_attribute('value') == draft
        browser.find_element(By.CSS_SELECTOR, '.agent-question button[type=submit]').click()
        wait.until(lambda b: len(b.execute_script('return __replyWrites')) == 2 and not b.find_elements(By.CSS_SELECTOR, '.agent-question'))
        writes = browser.execute_script('return __replyWrites')
        assert all(w['interaction_id'] == QUESTION and w['input'] == draft for w in writes)
        browser.execute_script('JarvisModes.openProject(arguments[0])', ROOT)
        wait.until(lambda b: b.execute_script('const v=JarvisModes.snapshot();return v.mode==="projects"&&v.projectView==="chat"&&v.missionId===arguments[0]', ROOT))
        browser.execute_script('JarvisPanels.open("right");JarvisAgents.open(arguments[0])', CEO)
        wait.until(lambda b: 'Project activity fixture' in b.find_element(By.ID, 'agentPublished').text)
        assert 'General activity fixture' not in browser.find_element(By.ID, 'agentDetails').text
        assert browser.execute_script('return document.body.scrollWidth<=innerWidth')
        browser.save_screenshot('/tmp/jarvis-agent-activity/' + str(width) + '.png')
        errors = [r['message'] for r in browser.get_log('browser') if 'Uncaught' in r['message']]
        assert not errors, errors
        print(f'{width}px: current/last activity, project isolation, visible Reply, preserved draft and confirmed submission passed', flush=True)
