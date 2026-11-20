"""Read-only live check plus simulated asynchronous delivery, draft preservation and deduplication."""
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from deploy.staffing import settings

options=webdriver.ChromeOptions();options.page_load_strategy='eager'
for flag in ('--headless','--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'):options.add_argument(flag)
options.set_capability('goog:loggingPrefs',{'browser':'ALL'})
with webdriver.Chrome(service=Service('/usr/bin/chromedriver'),options=options) as browser:
    wait=WebDriverWait(browser,35);el=lambda key:browser.find_element(By.ID,key)
    mission='2e99466d-59df-41e6-a19e-dad1e4e62119'
    for width in (1440,410):
        browser.set_window_size(width,950);browser.get('http://127.0.0.1:8765/hud/')
        browser.add_cookie({'name':'jarvis_token','value':settings()['JARVIS_HUD_TOKEN'],'path':'/'})
        browser.get('http://127.0.0.1:8765/hud/');wait.until(lambda b:b.execute_script('return !!window.JarvisModes'))
        el('projectsModeBtn').click()
        selector='.project-list-item[data-project-id="'+mission+'"]'
        wait.until(lambda b:b.find_elements(By.CSS_SELECTOR,selector));browser.find_element(By.CSS_SELECTOR,selector).click()
        wait.until(lambda b:b.find_elements(By.CSS_SELECTOR,'[data-work-reply-id]'))
        reply=browser.find_element(By.CSS_SELECTOR,'[data-work-reply-id]')
        assert 'The team found no verified runnable pentest suites' in reply.text
        el('administratorInput').clear();el('administratorInput').send_keys('Unsent delivery-check draft')
        browser.execute_script('''
          window.deliveryPhase='pending';window.deliveryChecks=0;
          const original=window.fetch;
          window.fetch=async function(url,options){
            if(String(url).startsWith('/api/admin/updates?')){
              const query=new URL(String(url),location.href).searchParams;
              if(query.get('mission_id')==='2e99466d-59df-41e6-a19e-dad1e4e62119'){
                window.deliveryChecks++;
                const ready=window.deliveryPhase==='done';
                return new Response(JSON.stringify({work:[{state:ready?'closed':'waiting',has_reply:ready,identifier:'JAR-75'}],
                  messages:ready?[{id:'paperclip:browser-delivery-check',role:'assistant',text:'Asynchronous result delivered.',timestamp:Date.now()/1000,
                    source:{kind:'project_result',task_id:query.get('mission_id'),identifier:'JAR-75'}}]:[]}),{headers:{'Content-Type':'application/json'}});
              }
            }
            return original.call(this,url,options);
          };
          window.dispatchEvent(new CustomEvent('jarvis-mode-changed',{detail:JarvisModes.snapshot()}));
        ''')
        wait.until(lambda b:'working with the team' in el('administratorStatus').text)
        browser.execute_script("deliveryPhase='done';window.dispatchEvent(new CustomEvent('jarvis-mode-changed',{detail:JarvisModes.snapshot()}));")
        wait.until(lambda b:'Asynchronous result delivered.' in el('administratorFeed').text)
        assert el('administratorInput').get_attribute('value')=='Unsent delivery-check draft'
        count=browser.execute_script('return deliveryChecks')
        browser.execute_script("window.dispatchEvent(new CustomEvent('jarvis-mode-changed',{detail:JarvisModes.snapshot()}));")
        wait.until(lambda b:b.execute_script('return deliveryChecks')>count)
        assert len(browser.find_elements(By.CSS_SELECTOR,'[data-work-reply-id="paperclip:browser-delivery-check"]'))==1
        assert not any(n.is_displayed() for n in browser.find_elements(By.CSS_SELECTOR,'.appr,[data-csi-auto]'))
        Path('/tmp/jarvis-work-reply-check').mkdir(exist_ok=True)
        browser.save_screenshot('/tmp/jarvis-work-reply-check/'+str(width)+'.png')
        el('directModeBtn').click();wait.until(lambda b:el('workspaceScopeTitle').text=='General')
        assert 'Asynchronous result delivered.' not in el('administratorFeed').text
        errors=[row['message'] for row in browser.get_log('browser') if 'Uncaught' in row['message']]
        assert not errors,errors
        print(width,'px: recovered report, automatic delivery, no duplicates, draft and scope preserved',flush=True)
