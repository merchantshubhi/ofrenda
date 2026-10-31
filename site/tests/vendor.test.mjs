// Three.js must be stored inside site/vendor (never fetched from a CDN). If this fails, the 3D
// altar cannot load and the page falls back to the list. See vendor/README.md for how to add it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const VENDOR = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'vendor');

test('vendor/three.module.js exists and is a real build', () => {
  const file = resolve(VENDOR, 'three.module.js');
  assert.ok(existsSync(file), 'missing site/vendor/three.module.js - see site/vendor/README.md');
  assert.ok(readFileSync(file, 'utf8').length > 100000, 'three.module.js looks truncated');
});

test('three.module.js has the sibling files it imports', () => {
  const file = resolve(VENDOR, 'three.module.js');
  if (!existsSync(file)) return assert.fail('three.module.js is missing');
  for (const m of readFileSync(file, 'utf8').matchAll(/from\s*'(\.\/[^']+)'/g)) {
    assert.ok(existsSync(resolve(VENDOR, m[1])), `three.module.js imports ${m[1]}, which is not in vendor/`);
  }
});

test('OrbitControls.js is present and imports the local Three.js', () => {
  const source = readFileSync(resolve(VENDOR, 'OrbitControls.js'), 'utf8');
  assert.match(source, /from '\.\/three\.module\.js'/);
});
