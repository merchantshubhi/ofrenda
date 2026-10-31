// Pure data logic for the altar: no DOM, no network, no Three.js. Everything here is unit tested.
// It reads the document written by `python -m ghosts.build` (site/generated/machines.json) and
// never trusts it: every field is checked, and anything missing degrades to "not shown".

export const TIERS = ['resting', 'restless', 'lost'];
export const LEVELS = ['young', 'older'];
export const KNOWN_KINDS = ['rover', 'probe', 'lander'];
export const GENERIC_KIND = 'generic';

export const TIER_INFO = {
  resting: { label: 'The Resting', note: 'They finished their mission and went quiet.' },
  restless: { label: 'The Restless', note: 'Still travelling, still talking.' },
  lost: { label: 'The Lost', note: 'They went quiet before their story was finished.' },
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const text = (v) => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null);
const textList = (v) => (Array.isArray(v) ? v.map(text).filter((s) => s !== null) : []);

/** Return a normalised https URL string, or null. Only https is ever allowed as a link. */
export function safeHttpsUrl(value) {
  if (typeof value !== 'string') return null;
  let url;
  try {
    url = new URL(value.trim());
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) return null;
  return url.href;
}

/** Sources become {title, url|null, accessed|null}; an unsafe URL keeps its title but no link. */
export function normalizeSources(list) {
  if (!Array.isArray(list)) return [];
  const out = [];
  for (const item of list) {
    if (!isObject(item)) continue;
    const url = safeHttpsUrl(item.url);
    const title = text(item.title) ?? (url ? new URL(url).hostname : null);
    if (title === null) continue;
    out.push({ title, url, accessed: text(item.accessed) });
  }
  return out;
}

function normalizeStories(raw) {
  const stories = {};
  for (const level of LEVELS) {
    const entry = isObject(raw) && isObject(raw[level]) ? raw[level] : null;
    stories[level] = entry ? { text: text(entry.text), origin: text(entry.origin) } : { text: null, origin: null };
  }
  return stories;
}

/** One machine, or null if it lacks an id, a name, or a known tier. */
export function normalizeMachine(raw) {
  if (!isObject(raw)) return null;
  const id = text(raw.id);
  const name = text(raw.name);
  const tier = text(raw.tier);
  if (id === null || name === null || !TIERS.includes(tier)) return null;
  return {
    id,
    name,
    tier,
    agency: text(raw.agency),
    body: text(raw.body),
    launched: text(raw.launched),
    arrived: text(raw.arrived),
    ended: text(raw.ended),
    lastContact: text(raw.last_contact),
    status: text(raw.status),
    purpose: text(raw.purpose),
    discoveries: textList(raw.discoveries),
    howItWorked: textList(raw.how_it_worked),
    funFact: text(raw.fun_fact),
    sources: normalizeSources(raw.sources),
    verified: raw.verified === true, // strictly true: "true" or 1 do not count
    stories: normalizeStories(raw.stories),
  };
}

/** Accepts the build document, a bare array, or junk. Never throws. */
export function normalizeData(raw) {
  const list = Array.isArray(raw) ? raw : isObject(raw) && Array.isArray(raw.machines) ? raw.machines : [];
  const machines = [];
  const seen = new Set();
  let skipped = 0;
  for (const item of list) {
    const machine = normalizeMachine(item);
    if (machine === null || seen.has(machine.id)) {
      skipped += 1;
      continue;
    }
    seen.add(machine.id);
    machines.push(machine);
  }
  return {
    preview: isObject(raw) && raw.preview === true, // the banner shows only for a literal true
    model: isObject(raw) && isObject(raw.generator) ? text(raw.generator.model) : null,
    machines,
    skipped,
  };
}

export function groupByTier(machines) {
  const groups = { resting: [], restless: [], lost: [] };
  for (const machine of machines) groups[machine.tier].push(machine);
  return groups;
}

/** The story for a level; if that level is empty, the other one, flagged as a fallback. */
export function getStory(machine, level) {
  const order = level === 'older' ? ['older', 'young'] : ['young', 'older'];
  for (const [i, key] of order.entries()) {
    const story = machine?.stories?.[key];
    if (story && story.text) return { text: story.text, origin: story.origin, level: key, fallback: i > 0 };
  }
  return null;
}

export function normalizeConfig(raw) {
  return isObject(raw) ? raw : {};
}

/** The 3D kind for a machine id; unknown ids or kinds give 'generic'. */
export function kindFor(config, id) {
  if (!isObject(config) || !Object.hasOwn(config, id) || !isObject(config[id])) return GENERIC_KIND;
  const kind = text(config[id].kind)?.toLowerCase();
  return KNOWN_KINDS.includes(kind) ? kind : GENERIC_KIND;
}

/** 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD' to words; anything else is returned as written. */
export function formatDate(value) {
  const s = text(value);
  if (s === null) return null;
  const m = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(s);
  if (!m) return s;
  const [, year, month, day] = m;
  if (month === undefined) return year;
  const name = MONTHS[Number(month) - 1];
  if (!name) return s;
  return day === undefined ? `${name} ${year}` : `${Number(day)} ${name} ${year}`;
}

/** Date rows worth showing, skipping missing ones. */
export function dateRows(machine) {
  const rows = [
    ['Launched', machine.launched],
    ['Arrived', machine.arrived],
    ['Mission ended', machine.ended],
    ['Last contact', machine.lastContact],
  ];
  return rows.filter(([, v]) => v !== null).map(([label, v]) => ({ label, value: formatDate(v) }));
}

/** Percent positions along an upward arch, left to right, for `count` candles. */
export function arcPositions(count) {
  if (!Number.isInteger(count) || count < 1) return [];
  const round = (n) => Math.round(n * 100) / 100;
  const from = 160;
  const to = 20;
  return Array.from({ length: count }, (_, i) => {
    const deg = count === 1 ? 90 : from + ((to - from) * i) / (count - 1);
    const rad = (deg * Math.PI) / 180;
    return { x: round(50 + 40 * Math.cos(rad)), y: round(88 - 66 * Math.sin(rad)) };
  });
}

// ---- altar layout and camera framing (pure maths, shared with altar.js and unit tested) ----

/** Distance from the camera to its target that the default framing is designed around. */
export const BASE_DISTANCE = 14;
const FOV_DEG = 42; // must match the camera in altar.js
const ISLAND_GAP = 1.2;
const MIN_RADIUS = 2.9;
const MACHINE_REACH = 2.2; // how far a machine model reaches sideways from its centre, at scale 1
// Islands float at slightly different heights and depths so the altar feels alive, not ruled.
const TIER_OFFSET = { resting: { y: 0, z: 0 }, restless: { y: 0.8, z: -1.5 }, lost: { y: 0.2, z: 0 } };

/** Machines shrink a little when many share one island. */
export function machineScale(count) {
  return Math.max(0.6, 1 - 0.1 * Math.max(0, count - 2));
}

function planIsland(machines) {
  const count = machines.length;
  const scale = machineScale(count);
  const spacing = 4.4 * scale;
  const span = Math.max(0, count - 1) * spacing;
  const radius = Math.max(MIN_RADIUS, span / 2 + MACHINE_REACH * scale + 0.9);
  const spots = machines.map((machine, i) => ({ id: machine.id, x: -span / 2 + i * spacing, z: 0 }));
  return { radius, scale, machines: spots };
}

/**
 * Where each tier's island floats and where its machines stand on it. Islands run left to right
 * (resting, restless, lost). Machine x/z are relative to their island. Always returns all
 * three tiers, even empty ones, plus `halfWidth`, the half extent of the whole altar.
 */
export function layoutAltar(groups) {
  const plans = TIERS.map((tier) => planIsland(groups?.[tier] ?? []));
  const total = plans.reduce((sum, plan) => sum + 2 * plan.radius, 0) + ISLAND_GAP * (TIERS.length - 1);
  let cursor = -total / 2;
  const tiers = {};
  TIERS.forEach((tier, i) => {
    const plan = plans[i];
    tiers[tier] = { x: cursor + plan.radius, ...TIER_OFFSET[tier], ...plan };
    cursor += 2 * plan.radius + ISLAND_GAP;
  });
  return { tiers, halfWidth: total / 2 };
}

/**
 * How far to pull the camera back (a multiplier of at least 1) so the whole altar fits across a
 * screen of this aspect ratio. A phone held upright needs a lot more distance than a laptop.
 */
export function framing(aspect, halfWidth) {
  const safeAspect = Number.isFinite(aspect) && aspect > 0.2 ? aspect : 0.2;
  const halfFov = (FOV_DEG / 2) * (Math.PI / 180);
  const needed = (halfWidth + 1.5) / (Math.tan(halfFov) * safeAspect);
  return Math.max(1, needed / BASE_DISTANCE);
}
