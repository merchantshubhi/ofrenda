import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  TIERS, BASE_DISTANCE, normalizeData, normalizeConfig, kindFor, getStory, groupByTier,
  safeHttpsUrl, formatDate, dateRows, layoutAltar, framing, machineScale,
} from '../model.js';

const read = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const real = read('../generated/machines.json');
const config = read('../machine-config.json');
const fake = (id, tier) => ({ id, name: id, tier });

test('real data: three machines, one per tier, nothing skipped', () => {
  const data = normalizeData(real);
  assert.equal(data.machines.length, 3);
  assert.equal(data.skipped, 0);
  assert.deepEqual(data.machines.map((m) => m.tier).sort(), [...TIERS].sort());
});

test('real data: stories, sources and verification status are preserved as written', () => {
  const data = normalizeData(real);
  for (const [i, machine] of data.machines.entries()) {
    const raw = real.machines[i];
    assert.equal(machine.verified, raw.verified === true);
    assert.equal(machine.sources.length, raw.sources.length);
    assert.equal(machine.stories.young.text, raw.stories.young.text);
    assert.equal(machine.stories.older.text, raw.stories.older.text);
    assert.equal(machine.agency, raw.agency);
  }
});

test('machine config gives every real machine a real 3D kind', () => {
  const data = normalizeData(real);
  const kinds = Object.fromEntries(data.machines.map((m) => [m.id, kindFor(normalizeConfig(config), m.id)]));
  assert.deepEqual(kinds, { opportunity: 'rover', 'voyager-1': 'probe', 'mars-polar-lander': 'lander' });
});

test('kindFor falls back to generic for junk', () => {
  assert.equal(kindFor({ a: { kind: 'hovercraft' } }, 'a'), 'generic');
  assert.equal(kindFor({ a: 5 }, 'a'), 'generic');
  assert.equal(kindFor(null, 'a'), 'generic');
  assert.equal(kindFor({}, 'toString'), 'generic');
});

test('only a literal true counts as verified; bad entries are skipped and counted', () => {
  const data = normalizeData({ machines: [{ ...real.machines[0], verified: 'true' }, { id: 'x' }, null, 5] });
  assert.equal(data.machines[0].verified, false);
  assert.equal(data.skipped, 3);
});

test('unsafe links lose the link but keep the title', () => {
  assert.equal(safeHttpsUrl('http://example.org'), null);
  assert.equal(safeHttpsUrl('javascript:alert(1)'), null);
  assert.equal(safeHttpsUrl('https://user:pw@example.org'), null);
  assert.equal(safeHttpsUrl('https://example.org/a'), 'https://example.org/a');
});

test('story falls back to the other reading level and says so', () => {
  const machine = normalizeData(real).machines[0];
  const onlyOlder = { ...machine, stories: { young: { text: null, origin: null }, older: machine.stories.older } };
  assert.equal(getStory(onlyOlder, 'young').fallback, true);
  assert.equal(getStory(machine, 'older').fallback, false);
  assert.equal(getStory({ stories: {} }, 'young'), null);
});

test('dates read as words and skip missing ones', () => {
  assert.equal(formatDate('2003-07-07'), '7 Jul 2003');
  assert.equal(formatDate('1977'), '1977');
  const voyager = normalizeData(real).machines.find((m) => m.id === 'voyager-1');
  assert.deepEqual(dateRows(voyager).map((r) => r.label), ['Launched']);
});

// ---- altar layout ----

test('layout: all three tiers, left to right, islands never overlap', () => {
  const layout = layoutAltar(groupByTier(normalizeData(real).machines));
  const { resting, restless, lost } = layout.tiers;
  assert.ok(resting.x < restless.x && restless.x < lost.x);
  assert.ok(resting.x + resting.radius < restless.x - restless.radius);
  assert.ok(restless.x + restless.radius < lost.x - lost.radius);
  assert.ok(layout.halfWidth >= lost.x + lost.radius - 1e-9);
  assert.ok(Math.abs(layout.halfWidth + resting.x - resting.radius) < 1e-9, 'altar is centred');
});

test('layout: every real machine gets exactly one spot, inside its island', () => {
  const groups = groupByTier(normalizeData(real).machines);
  const layout = layoutAltar(groups);
  for (const tier of TIERS) {
    const info = layout.tiers[tier];
    assert.deepEqual(info.machines.map((s) => s.id), groups[tier].map((m) => m.id));
    for (const spot of info.machines) assert.ok(Math.hypot(spot.x, spot.z) < info.radius - 1);
  }
});

test('layout: empty tiers still exist, and many machines get room and shrink', () => {
  const empty = layoutAltar({ resting: [], restless: [], lost: [] });
  assert.equal(TIERS.every((t) => empty.tiers[t].machines.length === 0), true);
  assert.ok(empty.halfWidth > 0);

  const crowd = layoutAltar({
    resting: ['a', 'b', 'c', 'd'].map((id) => fake(id, 'resting')),
    restless: [fake('p', 'restless'), fake('q', 'restless')],
    lost: [fake('l', 'lost')],
  });
  const xs = crowd.tiers.resting.machines.map((s) => s.x);
  for (let i = 1; i < xs.length; i += 1) assert.ok(xs[i] - xs[i - 1] > 2.5, 'machines do not stand on each other');
  assert.ok(crowd.tiers.resting.scale < 1 && machineScale(1) === 1);
  assert.ok(crowd.tiers.resting.x + crowd.tiers.resting.radius < crowd.tiers.restless.x - crowd.tiers.restless.radius);
});

test('framing: never closer than the default, and pulls back for tall narrow screens', () => {
  const half = layoutAltar(groupByTier(normalizeData(real).machines)).halfWidth;
  assert.ok(framing(16 / 9, half) >= 1);
  assert.ok(framing(0.5, half) > framing(1.78, half));
  assert.ok(framing(0.5, half) > 2, 'a phone held upright needs the altar much further away');
  assert.equal(framing(100, 1), 1);
  assert.ok(Number.isFinite(framing(0, half)) && Number.isFinite(framing(NaN, half)));
  assert.ok(BASE_DISTANCE > 0);
});
