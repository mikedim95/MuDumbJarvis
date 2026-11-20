"""Live counters plus simulated chart samples verify scrolling and unobstructed navigation."""
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from deploy.staffing import settings
opts=webdriver.ChromeOptions();opts.page_load_strategy='eager'
for flag in ('--headless','--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'):opts.add_argument(flag)
opts.set_capability('goog:loggingPrefs',{'browser':'ALL'})
with webdriver.Chrome(service=Service('/usr/bin/chromedriver'),options=opts) as b:
    wait=WebDriverWait(b,35);el=lambda key:b.find_element(By.ID,key)
    Path('/tmp/jarvis-token-header').mkdir(exist_ok=True)
    for width in (1440,410,320):
        b.set_window_size(width,950);b.get('http://127.0.0.1:8765/hud/')
        b.add_cookie({'name':'jarvis_token','value':settings()['JARVIS_HUD_TOKEN'],'path':'/'})
        b.get('http://127.0.0.1:8765/hud/');wait.until(lambda d:d.execute_script('return !!window.JarvisModes'))
        el('directModeBtn').click()
        wait.until(lambda d:el('tokenUsageTotal').text!='— total')
        assert not b.find_elements(By.ID,'aiProvider')
        assert 'Codex' not in b.find_element(By.CSS_SELECTOR,'#grid > header').text
        assert 'gpt-6.1-sol' not in b.find_element(By.CSS_SELECTOR,'#grid > header').text
        assert b.execute_script("const h=document.querySelector('#grid > header').getBoundingClientRect(),g=document.getElementById('tokenUsageGraph').getBoundingClientRect();return Math.abs(h.width-g.width)<2")
        assert not el('projectContext').is_displayed() and not el('administratorHeading').is_displayed()
        assert b.execute_script("const a=document.getElementById('workspaceScopeTitle').getBoundingClientRect(),c=document.getElementById('generalSidebarToggle').getBoundingClientRect();return Math.abs(a.top+a.height/2-c.top-c.height/2)<2")
        b.execute_script('''
          const original=fetch;
          window.fetch=async function(url,options){
            if(String(url)==='/api/usage/live'){
              const now=Date.now()/1000;
              return new Response(JSON.stringify({at:now,status:'ok',total_tokens:2500000,input_tokens:2400000,output_tokens:100000,
                tokens_per_second:1234.5,window_seconds:60,interval_seconds:5,
                points:[[now-60,0],[now-50,150],[now-40,450],[now-30,75],[now-20,600],[now-10,100],[now,1234.5]]}),{headers:{'Content-Type':'application/json'}});
            }
            return original.call(this,url,options);
          };document.dispatchEvent(new Event('visibilitychange'));
        ''')
        wait.until(lambda d:'1,234.5' in el('tokenUsageReadout').get_attribute('title'))
        path=el('tokenUsageLine').get_attribute('d')
        try:wait.until(lambda d:el('tokenUsageLine').get_attribute('d')!=path)
        except Exception:
            print(b.execute_script("const s=document.getElementById('tokenUsageGraph');return {hidden:document.hidden,width:s.clientWidth,height:s.clientHeight,path:document.getElementById('tokenUsageLine').getAttribute('d')}"),flush=True)
            print(b.get_log('browser'),flush=True);raise
        for key in ('directModeBtn','projectsModeBtn'):
            assert b.execute_script("const r=arguments[0].getBoundingClientRect();return document.elementFromPoint(r.left+r.width/2,r.top+r.height/2)===arguments[0]",el(key))
        assert b.execute_script('return document.body.scrollWidth<=innerWidth')
        el('projectsModeBtn').click();wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.project-list-item'))
        b.find_element(By.CSS_SELECTOR,'.project-list-item').click()
        wait.until(lambda d:el('workspaceScopeTitle').is_displayed() and el('workspaceScopeTitle').text!='General')
        assert not el('projectContext').is_displayed() and not el('administratorHeading').is_displayed()
        assert b.execute_script("const a=document.getElementById('workspaceScopeTitle').getBoundingClientRect(),c=document.getElementById('agentsSidebarToggle').getBoundingClientRect();return Math.abs(a.top+a.height/2-c.top-c.height/2)<2")
        b.save_screenshot('/tmp/jarvis-token-header/'+str(width)+'.png')
        errors=[row['message'] for row in b.get_log('browser') if 'Uncaught' in row['message']]
        assert not errors,errors
        print(width,'px: live counter, sliding chart, clear buttons and compact scoped title passed',flush=True)
