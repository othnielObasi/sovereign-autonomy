const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// Read-only checks: never create missions or send robot commands.
const base = process.env.PUBLIC_BASE_URL || 'http://127.0.0.1:19300';
const output = path.resolve('docs/validation/2026-11-03-public-pages');
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], checks = [], externalRequests = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', request => {
    if (new URL(request.url()).origin !== base) externalRequests.push(request.url());
  });
  try {
    assert.equal((await page.goto(base)).status(), 200);
    assert.match(await page.locator('h1').innerText(), /Intelligence that acts/);
    assert.equal(await page.locator('.family-card').count(), 5);
    assert.deepEqual(await page.locator('main > section').evaluateAll(els => els.slice(0, 2).map(el => el.id)), ['top', 'experience']);
    assert.equal(await page.locator('main > section').count(), 7);
    assert.equal(await page.locator('#authority .flow-node').count(), 3);
    await page.locator('#story-interface-details summary').click();
    await page.locator('.facility-preview img').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => { const img = document.querySelector('.facility-preview img'); return img.complete && img.naturalWidth > 0; });
    await page.locator('#story-interface-details summary').click();
    assert.equal(await page.locator('a[href="/mission-control"]').count() >= 2, true);
    checks.push('Landing preserves hero, exposes five groups, authority flow, simulator image and application links');
    const recording = await page.locator('#mission-story-data').evaluate(el => JSON.parse(el.textContent));
    const archiveResponse = await page.request.get(base + '/landing/mission-story/audit.json');
    assert.equal(archiveResponse.status(), 200);
    const archive = await archiveResponse.json();
    assert.equal(archive.event_count, 413);
    assert.equal(archive.events.length, 413);
    assert.equal(archive.individual_hashes_verified, true);
    assert.equal(archive.chronological_chain_valid, false);
    assert.equal(archive.chronological_link_mismatches.length, 37);
    const sourceEvents = new Map(archive.events.map(e => [e.id, e]));
    assert.equal(recording.steps.length, 5);
    for (const [i, step] of recording.steps.entries()) {
      await page.locator('[data-story-step]').nth(i).click();
      assert.equal(await page.locator('#story-title').innerText(), step.title);
      assert.equal(await page.locator('#story-fact').innerText(), step.fact);
      for (const eventId of step.event_ids) assert.ok(sourceEvents.has(eventId));
      const poseEvent = step.event_ids.map(id => sourceEvents.get(id)).find(e => e.payload.context?.telemetry?.x === step.pose.x && e.payload.context.telemetry.y === step.pose.y);
      assert.ok(poseEvent, 'Map position must come from a cited observation');
    }
    assert.equal(recording.steps[2].pose.speed, 0);
    assert.equal(recording.steps[4].pose.speed, 0);
    assert.equal(recording.permit_uses, archive.events.filter(e => e.type === 'AUTHORITY' && e.payload.event === 'permit_used').length);
    assert.match(await page.locator('#story-recording-limits').textContent(), /37 linkage discontinuities/);
    await page.locator('#story-next').click();
    assert.equal(await page.locator('#story-count').innerText(), '01 / 05');
    await page.locator('[data-story-step]').first().focus();
    await page.keyboard.press('End');
    assert.equal(await page.locator('#story-count').innerText(), '05 / 05');
    await page.keyboard.press('Home');
    assert.equal(await page.locator('#story-count').innerText(), '01 / 05');
    checks.push('Five mission moments cite actual archived events and positions; navigation works and audit limitations are disclosed');
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, 'landing-desktop.png'), fullPage: true });

    await page.locator('.family-card[href$="#control"]').click();
    await page.waitForURL('**/how-it-works#control');
    await page.locator('#control').waitFor();
    assert.equal(await page.locator('#cap-results article').count(), 22);
    assert.equal(await page.locator('#cap-results .cap-purpose').count(), 22);
    assert.equal(await page.locator('#cap-results .cap-example').count(), 22);
    assert.equal(await page.locator('#cap-results details:not([open])').count(), 22);
    const firstDetails = page.locator('#cap-results details').first();
    await firstDetails.locator('summary').click();
    assert.equal(await firstDetails.evaluate(el => el.open), true);
    await page.keyboard.press('Enter');
    assert.equal(await firstDetails.evaluate(el => el.open), false);
    checks.push('Capability details start collapsed and expand or collapse with pointer and keyboard');
    checks.push('Landing capability links reach the matching guide section; all 22 cards render');
    await page.locator('#master button').nth(4).click();
    assert.equal(await page.locator('#step-title').innerText(), 'Authorise');
    assert.equal(await page.locator('#master button').nth(4).evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#step-title').innerText(), 'Execute');
    await page.locator('#stage-capabilities').click();
    assert.equal(await page.locator('#cap-results article').count(), 4);
    assert.equal(await page.locator('#cap-count').innerText(), '4 of 22 capability areas');
    await page.locator('#reset-filters').click();
    assert.equal(await page.locator('#cap-results article').count(), 22);
    assert.equal(await page.locator('#reset-filters').isDisabled(), true);
    checks.push('Lifecycle shortcuts filter related capabilities; result counts and reset restore the full list');
    checks.push('Lifecycle stages respond to pointer and keyboard input without losing focus');

    await page.locator('#scene-tabs button').nth(0).click();
    assert.equal(await page.locator('#scene-flow li').count(), 6);
    const normal = await page.locator('.scene-map .scenario-route').getAttribute('d');
    await page.locator('#scene-tabs button').nth(1).click();
    assert.notEqual(await page.locator('.scene-map .scenario-route').getAttribute('d'), normal);
    assert.match(await page.locator('#scene-title').innerText(), /corridor changes/);
    await page.locator('#scene-tabs button').nth(2).click();
    assert.equal(await page.locator('.scene-map .scenario-route').getAttribute('stroke'), '#f2b197');
    checks.push('Scenario selection changes explanation and illustrated route or refusal state');

    await page.locator('#cap-search').fill('Recovery');
    assert.deepEqual(await page.locator('#cap-results h4').allTextContents(), ['Recovery']);
    assert.equal(await page.locator('#cap-results details[open]').count(), 1);
    await page.locator('#cap-search').fill('no-such-capability');
    assert.equal(await page.locator('#cap-results article').count(), 0);
    assert.match(await page.locator('#cap-results').innerText(), /No capabilities match/);
    await page.locator('#cap-search').fill('');
    await page.locator('#family-nav button').nth(3).click();
    assert.equal(await page.locator('#cap-results article').count(), 4);
    await page.locator('#family-nav button').first().click();
    await page.locator('#status-filter button').nth(2).click();
    assert.deepEqual(await page.locator('#cap-results h4').allTextContents(), ['AI planning', 'Agentic planning', 'Perception']);
    await page.locator('#status-filter button').first().click();
    assert.equal(await page.locator('#cap-results .workspace-link').count(), 22);
    checks.push('Search, no-results, family and configuration filters work; every capability links to a workspace');
    const destinations = await page.locator('.workspace-link').evaluateAll(els => [...new Set(els.map(el => el.getAttribute('href')))]);
    for (const destination of [...destinations, '/landing/validation.json', '/landing/fonts/manrope.woff2', '/landing/fonts/dm-sans.woff2']) {
      assert.equal((await page.request.get(base + destination)).status(), 200, destination);
    }
    checks.push('All linked workspace destinations and the recorded validation report return HTTP 200');

    const ids = await page.locator('[id]').evaluateAll(els => els.map(el => el.id));
    assert.equal(new Set(ids).size, ids.length, 'Duplicate element IDs');
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, 'guide-desktop.png'), fullPage: true });
    for (const route of ['/', '/how-it-works']) {
      for (const width of [390, 768, 1024, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(base + route);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${route}: overflow at ${width}`);
        if (route === '/') {
          await page.locator('[data-story-step]').nth(2).click();
          assert.equal(await page.locator('#story-fact').innerText(), '0.378 m');
          assert.equal(await page.locator('#story-people circle').count(), 4);
          assert.equal(await page.evaluate(() => {
            const robot = document.getElementById('story-robot').getBoundingClientRect();
            const box = document.querySelector('.story-map-scroll').getBoundingClientRect();
            const x = (robot.left + robot.right) / 2, y = (robot.top + robot.bottom) / 2;
            return x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;
          }), true, 'Recorded robot stays visible within the scrollable map');
        }
        if (width === 390 || width === 1024) {
          const menu = page.locator('.public-nav-toggle');
          await menu.click();
          assert.equal(await menu.getAttribute('aria-expanded'), 'true');
          await page.keyboard.press('Escape');
          assert.equal(await menu.getAttribute('aria-expanded'), 'false');
        }
        if (width === 390) await page.screenshot({ path: path.join(output, route === '/' ? 'landing-mobile.png' : 'guide-mobile.png'), fullPage: true });
      }
    }
    checks.push('Both pages fit 390, 768, 1024 and 1440px; mobile/tablet navigation opens and closes');
    // Check every public-page local link and its fragment against actual served HTML.
    const links = new Set();
    for (const route of ['/', '/how-it-works']) {
      await page.goto(base + route);
      for (const href of await page.locator('a[href]').evaluateAll(els => els.map(e => e.href))) {
        const url = new URL(href);
        if (url.origin === base && ['/', '/how-it-works'].includes(url.pathname)) links.add(url.href);
      }
    }
    for (const href of links) {
      const response = await page.goto(href);
      if (response) assert.equal(response.status(), 200);
      const hash = new URL(href).hash;
      if (hash) assert.equal(await page.locator(`[id="${hash.slice(1)}"]`).count(), 1, href);
    }
    checks.push('Public navigation and capability deep links resolve to existing sections');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(base + '/how-it-works');
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior), 'auto');
    assert.deepEqual(errors, []);
    assert.deepEqual(externalRequests, []);
    checks.push('Public pages load their fonts and assets locally without third-party requests');
    checks.push('Reduced motion is respected and both pages have no JavaScript errors');
    fs.writeFileSync(path.join(output, 'browser-report.json'), JSON.stringify({ base, checks, errors }, null, 2));
    console.log(JSON.stringify({ passed: checks.length, checks, errors }, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
