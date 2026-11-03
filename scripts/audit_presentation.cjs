// Read-only presentation inventory. Never launch a mission or trigger a scenario.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.PUBLIC_BASE_URL || 'http://127.0.0.1:19300';
const out = path.resolve('docs/validation/2026-11-03-presentation-audit');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' });
  const errors = [], posts = [], pages = [];
  page.on('pageerror', e => errors.push({ url: page.url(), message: e.message }));
  page.on('request', r => { if (r.method() !== 'GET') posts.push({ method: r.method(), url: r.url().replace(base, '') }); });
  try {
    const runs = await (await page.request.get(base + '/api/runs')).json();
    const routes = ['/', '/how-it-works', '/mission-control', '/missions', '/runs', '/authority', '/policies', '/evidence', '/audit', '/compliance'];
    if (runs[0]) routes.push('/runs/' + runs[0].id);
    for (const route of routes) {
      await page.goto(base + route, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(route === '/mission-control' || route.startsWith('/runs/') ? 2300 : 900);
      const floor = page.getByRole('button', { name: 'Floor plan', exact: true });
      if (await floor.count()) await floor.first().click();
      const inventory = await page.evaluate(() => {
        const clean = text => (text || '').replace(/\s+/g, ' ').trim();
        const root = document.querySelector('main') || document.body;
        const visible = el => !!(el.getBoundingClientRect().width && el.getBoundingClientRect().height);
        return {
          title: document.title,
          headings: [...root.querySelectorAll('h1,h2,h3')].filter(visible).map(el => ({ level: el.tagName, text: clean(el.textContent) })),
          visible_text: root.innerText,
          all_text: clean(root.textContent),
          links: [...document.querySelectorAll('a[href]')].filter(visible).map(el => ({ label: clean(el.textContent), href: el.getAttribute('href') })),
          controls: [...root.querySelectorAll('button,input,textarea,select,summary')].filter(visible).map(el => ({
            tag: el.tagName, role: el.getAttribute('role'), label: el.getAttribute('aria-label') || clean(el.textContent) || el.getAttribute('placeholder') || el.getAttribute('name'), disabled: !!el.disabled,
          })),
          details: [...root.querySelectorAll('details')].map(el => ({ open: el.open, label: clean(el.querySelector('summary')?.textContent) })),
          sections: [...root.querySelectorAll('section[id],article[id]')].map(el => ({ id: el.id, heading: clean(el.querySelector('h2,h3')?.textContent) })),
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
        };
      });
      pages.push({ route, final_url: page.url().replace(base, ''), ...inventory });
      if (['/', '/mission-control', '/authority', '/how-it-works'].includes(route)) {
        await page.screenshot({ path: path.join(out, (route === '/' ? 'landing' : route.slice(1)) + '-desktop.png'), fullPage: true });
      }
      console.log(route, inventory.headings.map(h => h.text).join(' | ').slice(0, 450));
    }
    const mobile = [];
    await page.setViewportSize({ width: 390, height: 1000 });
    for (const route of ['/', '/mission-control', '/authority']) {
      await page.goto(base + route, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1600);
      const floor = page.getByRole('button', { name: 'Floor plan', exact: true });
      if (await floor.count()) await floor.first().click();
      const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
      mobile.push({ route, width: dimensions.viewport, document_width: dimensions.document, overflow: dimensions.document > dimensions.viewport + 1 });
      await page.screenshot({ path: path.join(out, (route === '/' ? 'landing' : route.slice(1)) + '-mobile.png'), fullPage: true });
    }
    fs.writeFileSync(path.join(out, 'mobile.json'), JSON.stringify(mobile, null, 2));
    fs.writeFileSync(path.join(out, 'inventory.json'), JSON.stringify({ captured_at: new Date().toISOString(), scope: 'Read-only UI navigation; no missions or scenarios executed', pages, errors, non_get_requests: posts }, null, 2));
    console.log('Pages:', pages.length, 'errors:', errors.length, 'non-GET requests:', posts.length);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
