// Optional real-browser check: serves ../.. on a local port and drives it in headless Chromium
// (with software WebGL). It needs two dev-only packages that are NOT part of the website:
//     cd site && npm install --no-save puppeteer-core @sparticuz/chromium
//     node tests/e2e/browser-check.mjs            (screenshots go to $SHOTS or ./shots)
import http from 'node:http';
import { readFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join, extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';
import chromium from '@sparticuz/chromium';

const SITE = process.env.SITE_DIR ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SHOTS = process.env.SHOTS ?? join(process.cwd(), 'shots');
mkdirSync(SHOTS, { recursive: true });
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
const real = JSON.parse(readFileSync(join(SITE, 'generated', 'machines.json'), 'utf8'));

function serve(overrides = {}) {
  const server = http.createServer((req, res) => {
    const path = new URL(req.url, 'http://x').pathname;
    if (Object.hasOwn(overrides, path)) {
      const body = overrides[path];
      if (body === null) { res.writeHead(404).end('missing'); return; }
      res.writeHead(200, { 'content-type': 'application/json' }).end(typeof body === 'string' ? body : JSON.stringify(body));
      return;
    }
    const file = join(SITE, path === '/' ? 'index.html' : path);
    if (!file.startsWith(SITE) || !existsSync(file)) { res.writeHead(404).end('nope'); return; }
    res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' }).end(readFileSync(file));
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok({ url: `http://127.0.0.1:${server.address().port}/`, close: () => server.close() })));
}

const browser = await puppeteer.launch({
  args: [...chromium.args, '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  executablePath: await chromium.executablePath(), headless: 'shell',
});
let failures = 0;
const check = (name, ok, detail = '') => {
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  -> ${detail}`}`);
};

async function open(overrides, { w = 1280, h = 760, mobile = false, noGL = false, reduce = false } = {}) {
  const server = await serve(overrides);
  const page = await browser.newPage();
  const errors = [];
  const external = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('request', (r) => { if (!/^(http:\/\/127\.0\.0\.1|data:|blob:)/.test(r.url())) external.push(r.url()); });
  await page.setViewport({ width: w, height: h, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile });
  if (reduce) await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  if (noGL) await page.evaluateOnNewDocument(() => {
    const orig = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(t) ? null : orig.call(this, t, ...a); };
  });
  await page.goto(server.url, { waitUntil: 'load' });
  return { page, errors, external, close: async () => { await page.close(); server.close(); } };
}
const ready = (page) => page.waitForSelector('#stage[data-rendered="true"]', { timeout: 20000 });
const text = (page, sel) => page.$eval(sel, (n) => n.textContent.trim());
const visible = (page, sel) => page.$eval(sel, (n) => !n.hidden && n.getClientRects().length > 0);
const labels = (page) => page.$$eval('.label', (ns) => ns.map((n) => { const r = n.getBoundingClientRect(); return { id: n.dataset.id, text: n.textContent, x: r.x, y: r.y, w: r.width, h: r.height, hidden: n.hidden }; }));
const closeCard = async (page) => { await page.keyboard.press('Escape'); };

// ================= 1. desktop, real data =================
{
  const s = await open({});
  const { page } = s;
  await ready(page);
  const ls = await labels(page);
  check('desktop: three machine labels, real names', ls.map((l) => l.id).join() === 'opportunity,voyager-1,mars-polar-lander' && ls[0].text.startsWith('Opportunity'), JSON.stringify(ls.map((l) => l.text)));
  check('desktop: labels fully on screen', ls.every((l) => l.x >= 0 && l.x + l.w <= 1280 && l.y >= 0 && l.y + l.h <= 760), JSON.stringify(ls));
  check('desktop: banner hidden (real data has no preview flag)', !(await visible(page, '#banner')));
  check('desktop: footer text', (await text(page, '.foot')).startsWith('Not affiliated with NASA.'));
  const withScene = await page.screenshot({ clip: { x: 0, y: 130, width: 1280, height: 560 } });
  await page.addStyleTag({ content: '#scene{visibility:hidden}' });
  const without = await page.screenshot({ clip: { x: 0, y: 130, width: 1280, height: 560 } });
  check('desktop: the WebGL canvas actually draws something', withScene.length > without.length * 1.4, `${withScene.length} vs ${without.length}`);
  await page.evaluate(() => { document.getElementById('scene').style.visibility = ''; });
  await page.addStyleTag({ content: '#scene{visibility:visible!important}' });
  await new Promise((r) => setTimeout(r, 400));
  await page.screenshot({ path: join(SHOTS, 'desktop-altar.png') });

  for (const m of real.machines) {
    await page.click(`.label[data-id="${m.id}"]`);
    await page.waitForSelector('#card:not([hidden])');
    check(`${m.id}: panel shows real name, tier and agency`, (await text(page, '#card-title')) === m.name && (await text(page, '#card-tier')).includes('The ') && (await text(page, '#card-agency')) === m.agency);
    check(`${m.id}: younger story is the generated one`, (await text(page, '#card-voice')) === m.stories.young.text);
    await page.click('#lvl-older');
    check(`${m.id}: older story is the generated one`, (await text(page, '#card-voice')) === m.stories.older.text);
    check(`${m.id}: reading-level buttons reflect state`, (await page.$eval('#lvl-older', (n) => n.getAttribute('aria-pressed'))) === 'true');
    check(`${m.id}: verified badge shown (verified === true)`, (await visible(page, '#card-verified')) === (m.verified === true));
    const links = await page.$$eval('#card-sources a', (as) => as.map((a) => ({ href: a.href, rel: a.rel, target: a.target, text: a.textContent })));
    const safe = m.sources.filter((s) => s.url.startsWith('https://'));
    check(`${m.id}: ${safe.length} source links, all https + noopener noreferrer`, links.length === safe.length && links.every((l) => l.href.startsWith('https://') && l.rel === 'noopener noreferrer' && l.target === '_blank'), JSON.stringify(links.slice(0, 2)));
    check(`${m.id}: source titles are the real ones`, links.map((l) => l.text).join('|') === safe.map((s) => s.title).join('|'));
    check(`${m.id}: dates, discoveries and how-it-worked listed`, (await page.$$eval('#card-dates dt', (n) => n.length)) >= 2 && (await page.$$eval('#card-found li', (n) => n.length)) === m.discoveries.length && (await page.$$eval('#card-how li', (n) => n.length)) === m.how_it_worked.length);
    await page.screenshot({ path: join(SHOTS, `desktop-card-${m.id}.png`) });
    await closeCard(page);
    check(`${m.id}: Escape closes the panel and returns focus to the label`, !(await visible(page, '#card')) && (await page.evaluate(() => document.activeElement.dataset.id)) === m.id);
    await page.click('#lvl-young');
  }

  // clicking the 3D machine itself (not the label)
  for (const m of real.machines) {
    await new Promise((r) => setTimeout(r, 700));
    const l = (await labels(page)).find((x) => x.id === m.id);
    let opened = null;
    for (const dy of [50, 80, 110, 140, 170]) {
      await page.mouse.click(l.x + l.w / 2, l.y + l.h + dy);
      await new Promise((r) => setTimeout(r, 150));
      if (await visible(page, '#card')) { opened = await text(page, '#card-title'); break; }
    }
    check(`${m.id}: clicking the 3D model opens the right panel`, opened === m.name, String(opened));
    await closeCard(page);
    await new Promise((r) => setTimeout(r, 900));
  }

  // keyboard
  await page.focus('.label[data-id="voyager-1"]');
  await page.keyboard.press('Enter');
  await page.waitForSelector('#card:not([hidden])');
  check('keyboard: Enter on a label opens the panel and focuses Close', (await text(page, '#card-title')) === 'Voyager 1' && (await page.evaluate(() => document.activeElement.id)) === 'card-close');
  await page.click('#card-close');
  check('close button hides the panel', !(await visible(page, '#card')));

  // list view
  await page.click('#view-list');
  const tiles = await page.$$eval('.tile', (ns) => ns.map((n) => ({ tier: n.dataset.tier, name: n.querySelector('h2').textContent, verified: !!n.querySelector('.verified') })));
  check('list: three real tiles, in tier order, with verified marks', tiles.map((t) => t.name).join() === 'Opportunity,Voyager 1,Mars Polar Lander' && tiles.every((t) => t.verified), JSON.stringify(tiles));
  check('list: 3D stage hidden', !(await visible(page, '#stage')));
  await page.screenshot({ path: join(SHOTS, 'desktop-list.png') });
  await page.click('.tile:nth-child(3) button');
  await page.waitForSelector('#card:not([hidden])');
  check('list: "Hear its story" opens the right machine', (await text(page, '#card-title')) === 'Mars Polar Lander');
  await page.screenshot({ path: join(SHOTS, 'desktop-list-card.png') });
  await page.click('#card-close');
  await page.click('#view-3d');
  await page.waitForSelector('#stage:not([hidden])');
  check('back to 3D works', await visible(page, '#stage'));
  check('desktop: no console or page errors', s.errors.length === 0, s.errors.join(' | '));
  check('desktop: zero external network requests', s.external.length === 0, s.external.join(' '));
  await s.close();
}

// ================= 2. phone =================
{
  const s = await open({}, { w: 390, h: 780, mobile: true });
  const { page } = s;
  await ready(page);
  await new Promise((r) => setTimeout(r, 500));
  const ls = await labels(page);
  check('phone: no sideways scrolling', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), await page.evaluate(() => document.documentElement.scrollWidth));
  check('phone: all three labels inside the screen', ls.length === 3 && ls.every((l) => l.x >= 0 && l.x + l.w <= 390), JSON.stringify(ls));
  check('phone: tap targets are at least 44px', (await page.$$eval('button', (bs) => bs.filter((b) => b.getClientRects().length).every((b) => b.getBoundingClientRect().height >= 43.5))));
  await page.screenshot({ path: join(SHOTS, 'phone-altar.png') });
  await page.touchscreen.tap(ls[1].x + ls[1].w / 2, ls[1].y + ls[1].h / 2);
  await page.waitForSelector('#card:not([hidden])');
  const card = await page.$eval('#card', (n) => { const r = n.getBoundingClientRect(); return { x: r.x, r: r.right, y: r.y, b: r.bottom }; });
  check('phone: tapping a label opens a bottom sheet inside the screen', (await text(page, '#card-title')) === 'Voyager 1' && card.x >= 0 && card.r <= 390 && card.b <= 780, JSON.stringify(card));
  await page.screenshot({ path: join(SHOTS, 'phone-card.png') });
  await page.click('#card-close');
  await page.click('#view-list');
  await page.screenshot({ path: join(SHOTS, 'phone-list.png') });
  check('phone: list shows three tiles without overflow', (await page.$$eval('.tile', (n) => n.length)) === 3 && (await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)));
  check('phone: no console or page errors', s.errors.length === 0, s.errors.join(' | '));
  await s.close();
}

// ================= 3. failure modes =================
{
  const s = await open({}, { noGL: true });
  await page_wait(s.page);
  check('no WebGL: falls back to the list, 3D button disabled, says why', (await visible(s.page, '#list')) && (await s.page.$eval('#view-3d', (b) => b.disabled)) && (await text(s.page, '#notice')).includes('3D is not available') && (await s.page.$$eval('.tile', (n) => n.length)) === 3);
  await s.page.click('.tile button');
  check('no WebGL: stories still work', (await visible(s.page, '#card')) && (await text(s.page, '#card-voice')) === real.machines[0].stories.young.text);
  await s.close();
}
async function page_wait(page) { await page.waitForFunction(() => document.getElementById('notice').textContent.length > 0 || document.getElementById('stage').dataset.rendered, { timeout: 20000 }); }
{
  const s = await open({ '/generated/machines.json': null });
  await new Promise((r) => setTimeout(r, 800));
  check('missing machines.json: friendly message, empty list, no crash', (await text(s.page, '#notice')).includes('could not be loaded') && (await text(s.page, '#list')).includes('no machines') && s.errors.filter((e) => !/404/.test(e)).length === 0, s.errors.join('|'));
  await s.close();
}
{
  const s = await open({ '/generated/machines.json': '{"machines":[{"id":"x"},null,5,{"id":"y","name":"Y","tier":"haunted"}]}' });
  await new Promise((r) => setTimeout(r, 800));
  check('broken entries are skipped and reported', (await text(s.page, '#notice')).includes('4 entries were skipped') && (await text(s.page, '#list')).includes('no machines'));
  await s.close();
}
{
  const s = await open({ '/machine-config.json': null });
  await ready(s.page);
  check('missing machine-config.json: altar still renders all machines (generic models)', (await labels(s.page)).length === 3);
  await s.close();
}
{
  const s = await open({ '/machine-config.json': '{"opportunity":{"kind":"hovercraft"},"voyager-1":5}' });
  await ready(s.page);
  check('unknown kinds fall back to the generic model without errors', (await labels(s.page)).length === 3 && s.errors.length === 0, s.errors.join('|'));
  await s.close();
}
{
  const s = await open({}, { reduce: true });
  await ready(s.page);
  await s.page.click('.label[data-id="opportunity"]');
  await s.page.waitForSelector('#card:not([hidden])');
  check('reduced motion: altar renders and panel opens', (await text(s.page, '#card-title')) === 'Opportunity' && s.errors.length === 0, s.errors.join('|'));
  await s.close();
}
{
  const doc = structuredClone(real);
  doc.preview = true;
  doc.machines[0].verified = false;
  doc.machines[1].sources = [
    { title: 'Good https', url: 'https://example.org/a', accessed: '2026-10-29' },
    { title: 'Plain http', url: 'http://example.org/b' },
    { title: 'Script', url: 'javascript:alert(1)' },
    { title: '<img src=x onerror=alert(1)>', url: 'https://example.org/c' },
  ];
  doc.machines[2].stories = {};
  const s = await open({ '/generated/machines.json': doc });
  await ready(s.page);
  check('preview banner shows only when preview === true', await visible(s.page, '#banner'));
  await s.page.click('.label[data-id="opportunity"]');
  check('unverified machine: no verified badge', !(await visible(s.page, '#card-verified')));
  await s.page.click('#card-close');
  await s.page.click('.label[data-id="voyager-1"]');
  const links = await s.page.$$eval('#card-sources a', (as) => as.map((a) => a.href));
  const items = await s.page.$$eval('#card-sources li', (ls) => ls.map((l) => l.textContent));
  check('unsafe sources become plain text; only https is linked', links.length === 2 && links.every((h) => h.startsWith('https://')) && items.some((t) => t.includes('Plain http (no safe link')) && items.some((t) => t.includes('Script (no safe link')), JSON.stringify({ links, items }));
  check('markup in a title is shown as text, not run', (await s.page.$$eval('#card-sources img', (n) => n.length)) === 0 && items.some((t) => t.includes('<img src=x onerror=alert(1)>')));
  await s.page.click('#card-close');
  await s.page.click('.label[data-id="mars-polar-lander"]');
  check('machine with no stories: calm message, facts remain', (await text(s.page, '#card-voice')).includes('no story yet') && (await text(s.page, '#card-title')) === 'Mars Polar Lander');
  check('no errors with hostile data', s.errors.length === 0, s.errors.join('|'));
  await s.close();
}

// ================= 4. many machines per tier =================
for (const [name, vp] of [['desktop', {}], ['phone', { w: 390, h: 780, mobile: true }]]) {
  const doc = structuredClone(real);
  const base = real.machines[0];
  for (let i = 2; i <= 4; i += 1) doc.machines.push({ ...structuredClone(base), id: `rover-${i}`, name: `Extra Rover ${i}` });
  doc.machines.push({ ...structuredClone(real.machines[1]), id: 'probe-2', name: 'Extra Probe' });
  const s = await open({ '/generated/machines.json': doc }, vp);
  await ready(s.page);
  await new Promise((r) => setTimeout(r, 600));
  const ls = (await labels(s.page)).filter((l) => !l.hidden);
  const W = vp.w ?? 1280;
  const overlaps = [];
  for (let i = 0; i < ls.length; i += 1) for (let j = i + 1; j < ls.length; j += 1) {
    const a = ls[i], b = ls[j];
    const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    if (ox > 4 && oy > 4) overlaps.push(`${a.id}/${b.id}`);
  }
  check(`${name}: 6 machines on the altar, labels on screen`, ls.length === 6 && ls.every((l) => l.x >= 0 && l.x + l.w <= W), JSON.stringify(ls.map((l) => [l.id, Math.round(l.x), Math.round(l.w)])));
  check(`${name}: labels do not cover each other`, overlaps.length === 0, overlaps.join(','));
  await s.page.screenshot({ path: join(SHOTS, `${name}-many.png`) });
  await s.page.click('.label[data-id="rover-3"]');
  await s.page.waitForSelector('#card:not([hidden])');
  check(`${name}: each extra machine opens its own panel`, (await text(s.page, '#card-title')) === 'Extra Rover 3');
  check(`${name}: no errors`, s.errors.length === 0, s.errors.join('|'));
  await s.close();
}

await browser.close();
console.log(failures === 0 ? '\nALL BROWSER CHECKS PASSED' : `\n${failures} BROWSER CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
