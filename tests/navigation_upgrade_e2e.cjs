/* Run in the browser-test image with JARVIS_HUD_TOKEN and a read-only mount of
   the preceding release's /app/server/hud at /previous-hud. The proxy switches
   releases on one origin so Chromium retains the actual HTTP cache on upgrade. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');

const fixture = process.env.JARVIS_PREVIOUS_HUD_DIR || '/previous-hud';
const upstream = {hostname: '127.0.0.1', port: 8765};
const assetTypes = {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html'};

async function main() {
  const token = process.env.JARVIS_HUD_TOKEN;
  assert(token, 'Set JARVIS_HUD_TOKEN for the read-only live API checks.');
  const previousModes = await fs.readFile(path.join(fixture, 'modes.js'), 'utf8');
  assert(previousModes.includes("el('cronModeBtn').onclick"), 'Use a release with the previous cron navigation.');
  let upgraded = false;
  const staticRequests = [], refusedWrites = [], browserErrors = [];
  const proxy = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (!['GET', 'HEAD'].includes(req.method)) {
      refusedWrites.push(req.method + ' ' + url.pathname);
      res.writeHead(405).end();
      return;
    }
    if (url.pathname === '/between-releases') {
      res.writeHead(200, {'Content-Type': 'text/html'}).end('<title>Between releases</title>');
      return;
    }
    if (url.pathname.startsWith('/hud/')) {
      staticRequests.push({upgraded, url: req.url});
      if (!upgraded) {
        const filename = path.join(fixture, url.pathname.slice(5) || 'index.html');
        try {
          const data = await fs.readFile(filename);
          const extension = path.extname(filename);
          res.writeHead(200, {
            'Content-Type': assetTypes[extension] || 'application/octet-stream',
            'Cache-Control': extension === '.html' ? 'no-cache' : 'public, max-age=86400',
          }).end(data);
        } catch {
          res.writeHead(404).end();
        }
        return;
      }
    } else if (!url.pathname.startsWith('/api/')) {
      res.writeHead(404).end();
      return;
    }
    const target = http.request({...upstream, path: req.url, method: req.method,
      headers: {...req.headers, host: upstream.hostname + ':' + upstream.port}}, reply => {
      res.writeHead(reply.statusCode, reply.headers);
      reply.pipe(res);
    });
    target.on('error', () => res.destroy());
    target.end();
  });
  proxy.on('upgrade', (_req, socket) => socket.destroy());
  await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + proxy.address().port;
  let browser;
  try {
    browser = await chromium.launch({args: ['--no-sandbox', '--disable-dev-shm-usage']});
    const context = await browser.newContext({viewport: {width: 1360, height: 900}});
    await context.addCookies([{name: 'jarvis_token', value: token, url: origin}]);
    const page = await context.newPage();
    page.on('pageerror', error => { if (upgraded) browserErrors.push(error.message); });
    await page.goto(origin + '/hud/', {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => typeof document.getElementById('cronModeBtn')?.onclick === 'function');
    await page.goto(origin + '/between-releases');
    upgraded = true;
    const cachedModes = await page.evaluate(async () => (await fetch('/hud/modes.js')).text());
    assert.equal(cachedModes, previousModes);
    assert.equal(staticRequests.filter(r => r.url === '/hud/modes.js').length, 1,
      'The second fetch of the old URL must come from the browser cache.');

    const response = await page.goto(origin + '/hud/', {waitUntil: 'domcontentloaded'});
    assert.match(response.headers()['cache-control'] || '', /\bno-cache\b/);
    await page.locator('#generalModeBtn').click();
    await page.locator('#administratorInput').waitFor({state: 'visible'});
    await page.locator('#projectsModeBtn').click();
    const cards = page.locator('#projectList .project-list-item');
    await cards.first().waitFor({state: 'visible'});
    const missions = await page.evaluate(() => {
      const {tasks, ceoId} = window.JarvisTasks.snapshot();
      return tasks.filter(t => !t.hiddenAt && !t.parentId && t.assigneeAgentId === ceoId &&
        t.work_scope === 'project' && t.mission_id === t.id).map(t => t.id);
    });
    assert.deepEqual(await cards.evaluateAll(nodes => nodes.map(node => node.dataset.projectId)), missions);
    await cards.first().click();
    await page.locator('#projectContext').waitFor({state: 'visible'});
    await page.locator('#generalModeBtn').click();
    await page.locator('#administratorInput').waitFor({state: 'visible'});
    assert(staticRequests.some(r => r.upgraded && /^\/hud\/modes\.js\?v=[a-f0-9]+$/.test(r.url)),
      'The upgraded page must request a fresh navigation module.');
    assert.deepEqual(browserErrors, []);
    assert.deepEqual(refusedWrites, []);
    console.log(JSON.stringify({generalOpened: true, projectsListed: missions.length,
      missionOpened: true, previousScriptServedFromCache: true, nativeWrites: 0}));
  } finally {
    if (browser) await browser.close();
    proxy.closeAllConnections();
    await new Promise(resolve => proxy.close(resolve));
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
