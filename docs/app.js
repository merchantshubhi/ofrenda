// Builds the page from site/generated/machines.json. All text from data goes in through
// textContent, links are https-only with rel="noopener noreferrer", and nothing leaves this
// origin: the only requests are for local files next to this page.
//
// Two ways to look at the same machines: the floating 3D altar (altar.js, loaded lazily so that a
// device without WebGL never breaks the page) and a plain keyboard-friendly list.
import {
  TIER_INFO, groupByTier, normalizeData, normalizeConfig, kindFor, getStory, dateRows, TIERS,
  safeHttpsUrl,
} from './model.js';

const $ = (id) => document.getElementById(id);
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

const state = { level: 'young', view: '3d', machine: null, opener: null, byId: new Map(), config: {}, altar: null };

async function loadJson(path) {
  try {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null; // missing file, bad JSON, or opened from file://
  }
}

function el(tag, { cls, text, attrs } = {}) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  for (const [k, v] of Object.entries(attrs ?? {})) node.setAttribute(k, v);
  return node;
}

// ---- list view ----

function renderTile(machine) {
  const tile = el('li', { cls: 'tile', attrs: { 'data-tier': machine.tier } });
  tile.append(el('p', { cls: 'chip', text: TIER_INFO[machine.tier].label, attrs: { 'data-tier': machine.tier } }));
  tile.append(el('h2', { text: machine.name }));
  if (machine.verified) {
    const mark = el('p', { cls: 'verified' });
    mark.append(el('span', { text: '✓', attrs: { 'aria-hidden': 'true' } }), document.createTextNode(' Facts checked'));
    tile.append(mark);
  }
  if (machine.status) tile.append(el('p', { text: machine.status }));
  const button = el('button', { cls: 'btn', attrs: { type: 'button' } });
  button.append(document.createTextNode('Hear its story'), el('span', { cls: 'sr', text: ` of ${machine.name}` }));
  button.addEventListener('click', () => openMachine(machine, button));
  tile.append(button);
  return tile;
}

function renderList(machines) {
  const list = $('list');
  if (machines.length === 0) {
    list.replaceChildren(el('li', { cls: 'empty', text: 'There are no machines on the altar yet.' }));
    return;
  }
  const grouped = groupByTier(machines);
  list.replaceChildren(...TIERS.flatMap((tier) => grouped[tier].map(renderTile)));
}

// ---- machine panel ----

function fillList(listId, blockId, items) {
  $(listId).replaceChildren(...items.map((item) => el('li', { text: item })));
  $(blockId).hidden = items.length === 0;
}

function renderStory() {
  const story = state.machine ? getStory(state.machine, state.level) : null;
  for (const level of ['young', 'older']) {
    $(`lvl-${level}`).setAttribute('aria-pressed', String(level === state.level));
  }
  if (!story) {
    $('card-voice').textContent = 'This ghost has no story yet. The facts below are all we have.';
    $('card-origin').textContent = '';
    return;
  }
  $('card-voice').textContent = story.text;
  const how = story.origin === 'model'
    ? 'Voice written by a local open-weight AI model, then checked against the facts.'
    : 'Told in a simple template, built straight from the facts.';
  const fallback = story.fallback ? ' (No story for this reading level yet, so this is the other one.)' : '';
  $('card-origin').textContent = how + fallback;
}

function renderSources(sources) {
  const list = $('card-sources');
  list.replaceChildren();
  if (sources.length === 0) {
    list.append(el('li', { text: 'No sources listed.' }));
    return;
  }
  for (const source of sources) {
    const item = el('li');
    const url = safeHttpsUrl(source.url);
    if (url) {
      item.append(el('a', { text: source.title, attrs: { href: url, target: '_blank', rel: 'noopener noreferrer' } }));
    } else {
      item.append(el('span', { text: `${source.title} (no safe link available)` }));
    }
    if (source.accessed) item.append(el('span', { cls: 'small', text: ` Read ${source.accessed}.` }));
    list.append(item);
  }
}

function openMachine(machine, opener) {
  state.machine = machine;
  state.opener = opener ?? null;
  $('card-title').textContent = machine.name;
  $('card-tier').textContent = TIER_INFO[machine.tier].label;
  $('card-tier').dataset.tier = machine.tier;
  $('card-agency').textContent = machine.agency ?? '';
  $('card-verified').hidden = machine.verified !== true; // only a literal true shows the badge
  $('card-purpose').textContent = machine.purpose ?? '';
  $('card-status').textContent = machine.status ?? '';
  const dates = $('card-dates');
  dates.replaceChildren();
  for (const row of dateRows(machine)) dates.append(el('dt', { text: row.label }), el('dd', { text: row.value }));
  fillList('card-found', 'card-found-block', machine.discoveries);
  fillList('card-how', 'card-how-block', machine.howItWorked);
  $('card-fun').textContent = machine.funFact ?? '';
  $('card-fun-block').hidden = machine.funFact === null;
  renderSources(machine.sources);
  renderStory();

  const card = $('card');
  card.hidden = false;
  card.scrollTop = 0;
  $('card-close').focus({ preventScroll: true });
  if (state.view === '3d') {
    state.altar?.setSelected(machine.id);
    state.altar?.focus(machine.id);
  }
}

function closeCard() {
  const card = $('card');
  if (card.hidden) return;
  card.hidden = true;
  state.altar?.setSelected(null);
  if (state.view === '3d') state.altar?.home();
  const opener = state.opener;
  state.opener = null;
  if (opener?.isConnected) opener.focus({ preventScroll: true });
}

// ---- views ----

function setView(view) {
  state.view = view;
  const is3d = view === '3d';
  $('stage').hidden = !is3d;
  $('hint').hidden = !is3d;
  $('list').hidden = is3d;
  $('view-3d').setAttribute('aria-pressed', String(is3d));
  $('view-list').setAttribute('aria-pressed', String(!is3d));
  if (is3d) state.altar?.start();
  else state.altar?.stop();
}

async function startAltar(machines) {
  try {
    const { createAltar } = await import('./altar.js');
    state.altar = createAltar({
      canvas: $('scene'),
      stage: $('stage'),
      labels: $('labels'),
      machines,
      kindOf: (id) => kindFor(state.config, id),
      reducedMotion,
      onSelect: (id, label) => {
        const machine = state.byId.get(id);
        if (machine) openMachine(machine, label);
      },
    });
    return true;
  } catch {
    $('labels').replaceChildren(); // no WebGL, or the module could not load: the list takes over
    return false;
  }
}

function wire() {
  $('card-close').addEventListener('click', closeCard);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeCard();
  });
  for (const level of ['young', 'older']) {
    $(`lvl-${level}`).addEventListener('click', () => {
      state.level = level;
      renderStory();
    });
  }
  $('view-3d').addEventListener('click', () => setView('3d'));
  $('view-list').addEventListener('click', () => setView('list'));
}

function describeLoad(rawData, data) {
  if (rawData === null) {
    return 'The stories could not be loaded. If you are the builder, run "python -m ghosts.build --no-llm", then serve the site folder with "python -m http.server --directory site 8000" (opening the file directly will not work).';
  }
  if (data.skipped > 0) {
    return `${data.skipped} entr${data.skipped === 1 ? 'y was' : 'ies were'} skipped because the data was incomplete.`;
  }
  return '';
}

async function init() {
  wire();
  const [rawData, rawConfig] = await Promise.all([
    loadJson('generated/machines.json'),
    loadJson('machine-config.json'), // hand-written next to index.html; the build never touches it
  ]);
  state.config = normalizeConfig(rawConfig);
  const data = normalizeData(rawData);
  state.byId = new Map(data.machines.map((machine) => [machine.id, machine]));
  $('banner').hidden = data.preview !== true;
  renderList(data.machines);

  const notices = [describeLoad(rawData, data)];
  const has3d = data.machines.length > 0 && (await startAltar(data.machines));
  if (data.machines.length > 0 && !has3d) {
    notices.push('3D is not available on this device, so the altar is shown as a list instead.');
  }
  $('view-3d').disabled = !has3d;
  $('notice').textContent = notices.filter(Boolean).join(' ');
  setView(has3d ? '3d' : 'list');
}

init();
