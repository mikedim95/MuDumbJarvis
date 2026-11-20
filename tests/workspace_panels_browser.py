"""Live acceptance for shared, independently collapsible conversation and agent columns."""
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from deploy.staffing import settings

options=webdriver.ChromeOptions();options.page_load_strategy='eager'
for flag in ('--headless','--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'):options.add_argument(flag)
options.set_capability('goog:loggingPrefs',{'browser':'ALL'})
with webdriver.Chrome(service=Service('/usr/bin/chromedriver'),options=options) as b:
    wait=WebDriverWait(b,35);el=lambda key:b.find_element(By.ID,key)
    def click(key):
        node=el(key)
        if not node.is_displayed() and node.find_elements(By.XPATH,'ancestor::*[@id="generalNav"]'):el('generalSidebarToggle').click()
        node.click()
    def open_right():
        if el('agentsSidebarToggle').get_attribute('aria-expanded')!='true':click('agentsSidebarToggle')
        wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.agent-station'))>0)
    def roster():return set(b.execute_script("return [...document.querySelectorAll('.agent-station')].map(n=>n.dataset.agentId)"))
    def ready():wait.until(lambda d:el('administratorPanel').is_displayed() and not el('administratorSend').get_attribute('disabled'))
    def choose_project():
        click('projectsModeBtn');selector='.project-list-item'
        wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,selector));b.find_element(By.CSS_SELECTOR,selector).click();ready()
    def check_columns():
        assert b.execute_script("return document.getElementById('generalNav').getBoundingClientRect().right <= document.getElementById('workspaceMain').getBoundingClientRect().left+1")
        assert b.execute_script("return document.getElementById('workspaceMain').getBoundingClientRect().right <= document.getElementById('agentsRail').getBoundingClientRect().left+1")
        assert b.execute_script("return document.getElementById('agentsRail').contains(document.getElementById('agentsMap')) && !document.getElementById('workspaceMain').contains(document.getElementById('agentsPanel'))")
    def width():return b.execute_script("return document.getElementById('workspaceMain').getBoundingClientRect().width")
    def profile():
        open_right();card=b.find_element(By.CSS_SELECTOR,'.agent-station')
        if not el('agentDetails').is_displayed():card.click()
        wait.until(lambda d:el('agentContextBtn').is_displayed())
    Path('/tmp/jarvis-panels-check').mkdir(exist_ok=True)
    b.set_window_size(1440,1000);b.get('http://127.0.0.1:8765/hud/')
    b.add_cookie({'name':'jarvis_token','value':settings()['JARVIS_HUD_TOKEN'],'path':'/'})
    b.get('http://127.0.0.1:8765/hud/');wait.until(lambda d:d.execute_script('return !!window.JarvisPanels'))
    click('directModeBtn');ready();b.execute_script("JarvisPanels.open('left');JarvisPanels.open('right')")
    open_right();general=roster();assert len(general)>=2;check_columns()
    assert not el('projectAgentsBtn').is_displayed()
    el('administratorInput').send_keys('Preserve general draft');middle=width()
    click('agentsSidebarToggle');assert width()>middle+200 and b.execute_script("return document.getElementById('agentsRail').inert")
    right_closed=width();click('generalSidebarToggle');assert width()>right_closed+150
    assert el('administratorInput').get_attribute('value')=='Preserve general draft'
    b.refresh();wait.until(lambda d:d.execute_script('return !!window.JarvisPanels'));ready()
    assert b.execute_script("return document.body.dataset.leftPanel==='closed' && document.body.dataset.rightPanel==='closed'")
    assert el('administratorInput').get_attribute('value')=='Preserve general draft'
    click('generalSidebarToggle');open_right();check_columns()
    b.save_screenshot('/tmp/jarvis-panels-check/general-wide.png')
    choose_project();b.refresh();wait.until(lambda d:d.execute_script('return !!window.JarvisPanels'));ready();open_right();wait.until(lambda d:roster()!=general);check_columns()
    assert el('agentsHeading').text=='Project agents' and el('administratorPanel').is_displayed()
    el('administratorInput').send_keys('Preserve project draft');profile()
    assert el('administratorPanel').is_displayed()
    b.save_screenshot('/tmp/jarvis-panels-check/project-wide.png')
    click('agentContextBtn');wait.until(lambda d:not el('generalContextText').get_attribute('disabled'))
    assert el('agentProjectScope').get_attribute('aria-pressed')=='true' and el('agentsRail').is_displayed()
    click('contextBackBtn');ready();assert el('administratorInput').get_attribute('value')=='Preserve project draft'
    click('agentCronBtn');wait.until(lambda d:el('cronPanel').is_displayed());click('cronBackBtn');ready()
    click('generalSidebarToggle');click('directModeBtn');ready()
    assert b.execute_script("return document.body.dataset.leftPanel==='closed' && document.body.dataset.rightPanel==='open'")
    wait.until(lambda d:roster()==general)
    print('Desktop: separate columns, independent collapse, persistence, scope, Context/Cron and drafts passed',flush=True)
    b.set_window_size(410,950);wait.until(lambda d:d.execute_script('return JarvisPanels.snapshot().narrow'))
    assert b.execute_script("return document.body.dataset.leftPanel==='closed' && document.body.dataset.rightPanel==='closed'")
    full=width();click('generalSidebarToggle');assert el('generalSidebarToggle').get_attribute('aria-expanded')=='true'
    assert abs(width()-full)<2
    click('agentsSidebarToggle');assert el('generalSidebarToggle').get_attribute('aria-expanded')=='false'
    open_right();assert b.execute_script("const r=document.getElementById('agentsRail').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth+1 && r.top>=document.getElementById('workspaceControls').getBoundingClientRect().bottom-1")
    b.find_element(By.TAG_NAME,'body').send_keys(Keys.ESCAPE)
    assert el('agentsSidebarToggle').get_attribute('aria-expanded')=='false'
    assert b.execute_script("return document.activeElement.id==='agentsSidebarToggle'")
    choose_project();open_right();profile();click('agentContextBtn');wait.until(lambda d:el('generalContextPanel').is_displayed())
    assert el('agentsSidebarToggle').get_attribute('aria-expanded')=='false'
    click('contextBackBtn');ready();open_right()
    assert b.execute_script('return document.body.scrollWidth<=innerWidth')
    b.save_screenshot('/tmp/jarvis-panels-check/project-narrow.png')
    errors=[row['message'] for row in b.get_log('browser') if 'Uncaught' in row['message']]
    assert not errors,errors
    print('Mobile: separate drawers, correct edges, Escape/focus, scope and no overflow passed',flush=True)
