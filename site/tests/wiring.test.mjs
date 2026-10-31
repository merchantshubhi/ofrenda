// Static checks that need no browser and no Three.js: do the modules agree with each other,
// and does the page keep the project's rules (no CDN, no innerHTML, no inline handlers)?
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = (name) => readFileSync(resolve(SITE, name), 'utf8');
const OWN = ['app.js', 'altar.js', 'model.js', 'models3d.js', 'viewer.js'];

function exportsOf(source) {
  const names = new Set();
  for (const m of source.matchAll(/export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z0-9_$]+)/g)) names.add(m[1]);
  for (const m of source.matchAll(/export\s*\{([^}]+)\}/g)) m[1].split(',').forEach((n) => names.add(n.split(' as ').pop().trim()));
  return names;
}

test('every named import from a local module is really exported by it', () => {
  for (const file of OWN) {
    const source = read(file);
    for (const m of source.matchAll(/import\s*\{([^}]+)\}\s*from\s*'(\.[^']+)'/gs)) {
      const target = resolve(SITE, m[2]);
      assert.ok(existsSync(target) || m[2].includes('three'), `${file} imports ${m[2]}, which does not exist`);
      if (m[2].includes('three.module')) continue; // third party, checked in vendor.test.mjs
      const have = exportsOf(readFileSync(target, 'utf8'));
      for (const name of m[1].split(',').map((n) => n.trim().split(' as ')[0]).filter(Boolean)) {
        assert.ok(have.has(name), `${file} imports { ${name} } from ${m[2]}, but it is not exported`);
      }
    }
  }
});

test('the page loads app.js, which loads the altar; the altar is a lazy import', () => {
  assert.match(read('index.html'), /<script type="module" src="app\.js">/);
  assert.match(read('app.js'), /import\('\.\/altar\.js'\)/);
  assert.match(read('app.js'), /createAltar\(/);
});

test('one machine-config path: site/machine-config.json, read by app.js', () => {
  assert.ok(existsSync(resolve(SITE, 'machine-config.json')));
  assert.ok(!existsSync(resolve(SITE, 'generated/machine-config.json')), 'no second copy to drift apart');
  assert.match(read('app.js'), /loadJson\('machine-config\.json'\)/);
});

test('no CDN, no remote URL and no network call other than the two local JSON files', () => {
  for (const file of [...OWN, 'index.html', 'style.css']) {
    const source = read(file).replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/, '');
    assert.doesNotMatch(source, /https?:\/\/[^\s'"`)]*\.(com|net|org|io|dev)/i, `${file} mentions a remote host`);
    assert.doesNotMatch(source, /\bXMLHttpRequest\b|\bWebSocket\b|\bsendBeacon\b|@import/, file);
  }
  assert.deepEqual([...read('app.js').matchAll(/loadJson\('([^']+)'\)/g)].map((m) => m[1]), ['generated/machines.json', 'machine-config.json']);
});

test('project rules: textContent only, no eval, no inline handlers or styles', () => {
  for (const file of [...OWN, 'index.html']) {
    const source = read(file);
    assert.doesNotMatch(source, /innerHTML|outerHTML|insertAdjacentHTML|document\.write/, file);
    assert.doesNotMatch(source, /\beval\(|new Function\(/, file);
    assert.doesNotMatch(source, /\son[a-z]+\s*=\s*["']/, `${file} has an inline handler`);
    assert.doesNotMatch(source, /\sstyle\s*=\s*["']/, `${file} has an inline style (blocked by the CSP)`);
  }
});

test('the page keeps its strict Content-Security-Policy and the footer line', () => {
  const html = read('index.html');
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /script-src 'self'/);
  assert.match(html, /<p>Not affiliated with NASA\.<\/p>/);
});

test('light theme: no leftover dark-theme colours', () => {
  const css = read('style.css');
  assert.doesNotMatch(css, /#140d1f|#21153a|--night/);
  assert.match(css, /linear-gradient\(/);
});

test('every id the browser check clicks or reads exists in index.html', () => {
  const html = read('index.html');
  const check = read('tests/e2e/browser-check.mjs');
  const dynamic = new Set(['card-sources a']); // elements the app creates
  const wanted = new Set([...check.matchAll(/'#([a-z0-9-]+)(?:[ :\[][^']*)?'/g)].map((m) => m[1]));
  for (const id of wanted) {
    if (dynamic.has(id)) continue;
    assert.match(html, new RegExp(`id="${id}"`), `index.html is missing #${id}, which browser-check.mjs uses`);
  }
  assert.match(html, /class="foot"/);
});
