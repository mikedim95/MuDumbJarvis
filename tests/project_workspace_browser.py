"""Live UI acceptance: scoped navigation, drafts and requests; inference replies are stubbed.
Run from repository root with PYTHONPATH=. python3 tests/project_workspace_browser.py.
"""
import json
from pathlib import Path
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from deploy.staffing import settings

BASE='http://127.0.0.1:8765'
options=webdriver.ChromeOptions()
for arg in ('--headless','--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'):
    options.add_argument(arg)
options.set_capability('goog:loggingPrefs',{'browser':'ALL'})
with webdriver.Chrome(service=Service('/usr/bin/chromedriver'),options=options) as browser:
    wait=WebDriverWait(browser,35)
    el=lambda key:browser.find_element(By.ID,key)
    def displayed(key):
        return bool(browser.find_elements(By.ID,key)) and el(key).is_displayed()
    def click(key):
        node=el(key)
        if not node.is_displayed() and node.find_elements(By.XPATH,'ancestor::*[@id="generalNav"]'):
            el('generalSidebarToggle').click()
        node.click()
    def ready_chat():
        wait.until(lambda b:displayed('administratorPanel') and not el('administratorSend').get_attribute('disabled'))
    def choose(project):
        click('projectsModeBtn')
        wait.until(lambda b:b.find_elements(By.CSS_SELECTOR,f'.project-list-item[data-project-id="{project}"]'))
        browser.find_element(By.CSS_SELECTOR,f'.project-list-item[data-project-id="{project}"]').click()
        wait.until(lambda b:b.execute_script('return JarvisModes.snapshot().projectView')=='chat' and displayed('workspaceScopeTitle'))
    def open_agents():
        if el('agentsSidebarToggle').get_attribute('aria-expanded')!='true':click('agentsSidebarToggle')
    def profile():
        wait.until(lambda b:b.find_elements(By.CSS_SELECTOR,'.agent-station'))
        card=browser.find_elements(By.CSS_SELECTOR,'.agent-station')[0]
        if not displayed('agentDetails') or el('agentDetails').get_attribute('data-agent-id')!=card.get_attribute('data-agent-id'):card.click()
        wait.until(lambda b:displayed('agentContextBtn') and displayed('agentCronBtn'))
        return card.get_attribute('data-agent-id')
    def stub():
        browser.execute_script('''
          if(window.workspaceTestFetch)return;
          window.workspaceTestFetch=window.fetch;window.workspaceRequests=[];
          window.fetch=async function(url,options={}){
            if(String(url)==='/api/admin/chat'&&options.method==='POST'){
              const body=JSON.parse(options.body);window.workspaceRequests.push(body);
              await new Promise(resolve=>setTimeout(resolve,1400));
              return new Response(JSON.stringify({text:'Scoped reply for '+(body.mission_id||'general'),conversation_id:body.conversation_id,
                 mission_id:body.mission_id,administration_updates:[],general_context_updates:[]}),{status:200,headers:{'Content-Type':'application/json'}});
            }
            return window.workspaceTestFetch.call(this,url,options);
          };
        ''')
    Path('/tmp/jarvis-workspace-check').mkdir(exist_ok=True)
    for width in (1440,410):
        browser.set_window_size(width,950)
        browser.get(BASE+'/hud/')
        browser.add_cookie({'name':'jarvis_token','value':settings()['JARVIS_HUD_TOKEN'],'path':'/'})
        browser.get(BASE+'/hud/')
        wait.until(lambda b:b.execute_script('return !!window.JarvisModes'))
        browser.execute_script("localStorage.removeItem('jarvis-administrator-draft')")
        click('directModeBtn');ready_chat();stub()
        assert el('directModeBtn').text=='GENERAL'
        assert len(browser.find_elements(By.CSS_SELECTOR,'#appModes button'))==2
        browser.save_screenshot('/tmp/jarvis-workspace-check/general-'+str(width)+'.png')
        global_thread=browser.execute_script("return document.querySelector('#generalThreads [aria-current=\"true\"]').dataset.threadId")
        el('administratorInput').clear();el('administratorInput').send_keys('Global unsent '+str(width))
        click('projectsModeBtn')
        wait.until(lambda b:len(b.find_elements(By.CSS_SELECTOR,'.project-list-item'))>=1)
        ids=[n.get_attribute('data-project-id') for n in browser.find_elements(By.CSS_SELECTOR,'.project-list-item')]
        first=ids[0]
        general_nav=browser.execute_script("return [...document.querySelectorAll('#projectTools button:not([hidden])')].map(n=>n.textContent)")
        choose(first)
        assert browser.execute_script("return [...document.querySelectorAll('#projectTools button:not([hidden])')].map(n=>n.textContent)")==general_nav
        click('projectOverviewBtn')
        wait.until(lambda b:b.find_elements(By.CSS_SELECTOR,'.delegation-tree'))
        assert displayed('feed') and not displayed('generalComposer')
        browser.save_screenshot('/tmp/jarvis-workspace-check/project-'+str(width)+'.png')
        click('projectChatBtn');ready_chat()
        project_thread=browser.execute_script("return document.querySelector('#generalThreads [aria-current=\"true\"]').dataset.threadId")
        assert project_thread!=global_thread
        el('administratorInput').clear();el('administratorInput').send_keys('Project draft '+str(width))
        click('directModeBtn');ready_chat()
        assert el('administratorInput').get_attribute('value')=='Global unsent '+str(width)
        choose(first);click('projectChatBtn');ready_chat()
        assert el('administratorInput').get_attribute('value')=='Project draft '+str(width)
        open_agents();agent=profile();click('agentContextBtn')
        wait.until(lambda b:not el('generalContextText').get_attribute('disabled'))
        assert el('agentProjectScope').get_attribute('aria-pressed')=='true'
        assert browser.execute_script("return document.getElementById('projectContext').getBoundingClientRect().top < document.getElementById('generalContextPanel').getBoundingClientRect().top")
        browser.save_screenshot('/tmp/jarvis-workspace-check/context-'+str(width)+'.png')
        el('generalContextText').send_keys('Temporary local draft')
        click('agentGeneralScope');el('generalContextText').send_keys('Temporary standing draft')
        click('agentProjectScope')
        assert el('generalContextText').get_attribute('value')=='Temporary local draft'
        click('contextBackBtn');wait.until(lambda b:displayed('agentCronBtn'));click('agentCronBtn')
        wait.until(lambda b:displayed('cronPanel') and el('cronStatus').text!='Loading schedules…')
        assert 'Cron jobs' in el('cronHeading').text and 'Loading' not in el('cronStatus').text
        assert browser.execute_script('return JarvisModes.snapshot().cronAgentId')==agent
        assert not displayed('projectScheduleBtn')
        click('cronBackBtn');wait.until(lambda b:displayed('agentsPanel'))
        click('directModeBtn');ready_chat()
        assert el('administratorInput').get_attribute('value')=='Global unsent '+str(width)
        el('administratorSend').click()
        assert el('administratorInput').get_attribute('value')==''
        wait.until(lambda b:len(b.execute_script('return workspaceRequests'))==1)
        assert browser.execute_script('return workspaceRequests[0].mission_id') is None
        choose(first);click('projectChatBtn');ready_chat()
        el('administratorSend').click()
        assert el('administratorInput').get_attribute('value')==''
        wait.until(lambda b:len(b.execute_script('return workspaceRequests'))==2)
        assert browser.execute_script('return workspaceRequests[1].mission_id')==first
        click('directModeBtn');ready_chat();time.sleep(1.6)
        assert 'Scoped reply for '+first not in el('administratorFeed').text
        assert browser.execute_script('return JarvisModes.snapshot().mode')=='direct'
        click('directModeBtn');open_agents();wait.until(lambda b:displayed('agentsPanel'));profile()
        assert not displayed('generalCronBtn')
        click('agentCronBtn');wait.until(lambda b:displayed('cronPanel') and el('cronStatus').text!='Loading schedules…')
        assert browser.execute_script('return JarvisModes.snapshot().cronScope')=='general'
        assert browser.execute_script('return document.body.scrollWidth<=window.innerWidth')
        Path('/tmp/jarvis-workspace-check').mkdir(exist_ok=True)
        browser.save_screenshot('/tmp/jarvis-workspace-check/agent-cron-'+str(width)+'.png')
        errors=[r['message'] for r in browser.get_log('browser') if 'Uncaught' in r['message']]
        assert not errors,errors
        print(json.dumps({'width':width,'project_isolation':True,'agent_context_and_cron':True,'send_scope':True}),flush=True)
