// The 3D altar: one floating island per tier, with each machine's model, a ring of candles,
// and an HTML button label above every machine (so the altar is fully keyboard operable).
// Loaded lazily by app.js; if WebGL is missing this module throws and the List view is used.
import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { buildModel, disposeModel, PALETTE } from './models3d.js';
import { TIERS, TIER_INFO, groupByTier, layoutAltar, framing, BASE_DISTANCE } from './model.js';

const ISLAND_COLOR = { resting: 0xbfe8d4, restless: 0xd3c8f7, lost: 0xfbd0dc };
const HOME_TARGET = new THREE.Vector3(0, 1.2, 0);
const DRAG_PX = 6; // a pointer that moved further than this was a drag, not a click

const flat = (color) =>
  new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0.05, flatShading: true });

export function createAltar({ canvas, stage, labels, machines, kindOf, reducedMotion, onSelect }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); // throws without WebGL
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = !reducedMotion;
  controls.enablePan = false;
  controls.minDistance = 5;
  controls.minPolarAngle = 0.9;
  controls.maxPolarAngle = 1.6;
  controls.minAzimuthAngle = -0.9;
  controls.maxAzimuthAngle = 0.9;

  scene.add(new THREE.HemisphereLight(0xfff3e6, 0xc9b8ff, 1.9));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(4, 8, 6);
  scene.add(sun);

  // A tiny seeded generator keeps petals and stars in the same places on every load.
  let seed = 7;
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;

  const stars = new Float32Array(160 * 3);
  for (let i = 0; i < 160; i += 1) {
    stars[i * 3] = (rand() - 0.5) * 60;
    stars[i * 3 + 1] = rand() * 16 - 2;
    stars[i * 3 + 2] = -6 - rand() * 18;
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute('position', new THREE.BufferAttribute(stars, 3));
  scene.add(new THREE.Points(starGeometry, new THREE.PointsMaterial({ color: 0xffffff, size: 0.18, transparent: true, opacity: 0.9 })));

  const groups = groupByTier(machines);
  const layout = layoutAltar(groups);
  const byId = new Map(machines.map((m) => [m.id, m]));
  const entries = new Map(); // machine id -> { body, root, spot, scale, label }
  const flames = [];
  const pickTargets = [];

  function makeCandle(x, z, machineId) {
    const g = new THREE.Group();
    const wax = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.42, 10), flat(PALETTE.cream));
    wax.position.y = 0.21;
    const flame = new THREE.Mesh(new THREE.SphereGeometry(0.075, 10, 8), new THREE.MeshBasicMaterial({ color: 0xffd36e }));
    flame.scale.set(1, 1.5, 1);
    flame.position.y = 0.52;
    const halo = new THREE.Mesh(
      new THREE.SphereGeometry(0.2, 12, 10),
      new THREE.MeshBasicMaterial({ color: 0xffe9a8, transparent: true, opacity: 0.28, depthWrite: false }),
    );
    halo.position.y = 0.52;
    g.add(wax, flame, halo);
    g.position.set(x, 0.35, z);
    flames.push({ flame, halo, phase: rand() * 6 });
    if (machineId) {
      g.traverse((o) => { o.userData.machineId = machineId; });
      pickTargets.push(g);
    }
    return g;
  }

  for (const tier of TIERS) {
    const info = layout.tiers[tier];
    const root = new THREE.Group();
    root.position.set(info.x, info.y, info.z);
    root.userData.baseY = info.y;
    root.userData.phase = rand() * 6;
    const r = info.radius;
    root.add(new THREE.Mesh(new THREE.CylinderGeometry(r, r * 0.88, 0.6, 28), flat(ISLAND_COLOR[tier])));
    const under = new THREE.Mesh(new THREE.ConeGeometry(r * 0.88, r * 0.68, 7), flat(0xc9bfe8));
    under.rotation.x = Math.PI;
    under.position.y = -(0.3 + 0.34 * r);
    root.add(under);

    const nearest = (x, z) => {
      let best = null;
      let bestD = Infinity;
      for (const spot of info.machines) {
        const d = Math.hypot(spot.x - x, spot.z - z);
        if (d < bestD) { bestD = d; best = spot.id; }
      }
      return best;
    };
    const candleCount = 5 + 2 * Math.max(1, info.machines.length);
    for (let i = 0; i < candleCount; i += 1) {
      const a = (i / candleCount) * Math.PI * 2 + 0.3;
      const x = Math.cos(a) * (r - 0.55);
      const z = Math.sin(a) * (r - 0.55);
      root.add(makeCandle(x, z, nearest(x, z)));
    }
    const petalCount = 8 + 5 * Math.max(1, info.machines.length);
    for (let i = 0; i < petalCount; i += 1) {
      const a = rand() * Math.PI * 2;
      const d = r * (0.45 + rand() * 0.42);
      const petal = new THREE.Mesh(new THREE.IcosahedronGeometry(0.1 + rand() * 0.06, 0), flat(i % 3 ? PALETTE.marigold : 0xffd166));
      petal.position.set(Math.cos(a) * d, 0.34, Math.sin(a) * d);
      root.add(petal);
    }

    for (const spot of info.machines) {
      const body = buildModel(kindOf(spot.id));
      body.scale.setScalar(info.scale);
      body.position.set(spot.x, 0.3, spot.z);
      body.traverse((o) => { o.userData.machineId = spot.id; });
      root.add(body);
      pickTargets.push(body);

      const machine = byId.get(spot.id);
      const label = document.createElement('button');
      label.type = 'button';
      label.className = 'label';
      label.dataset.id = spot.id;
      label.dataset.tier = tier;
      label.append(document.createTextNode(machine.name));
      const small = document.createElement('small');
      small.textContent = TIER_INFO[tier].label;
      label.append(small);
      label.addEventListener('click', () => onSelect(spot.id, label));
      labels.append(label);
      entries.set(spot.id, { body, root, spot, scale: info.scale, label });
    }
    scene.add(root);
  }

  // ---- camera ----
  const home = new THREE.Vector3(0, 4.2, 13.5);
  let goal = null;
  let selected = null;
  let hovered = null;

  function resize() {
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const k = framing(camera.aspect, layout.halfWidth);
    home.set(0, 4.2 * k, 13.5 * k);
    controls.maxDistance = BASE_DISTANCE * k * 1.5;
    camera.updateProjectionMatrix();
    if (!selected && !goal) {
      camera.position.copy(home);
      controls.target.copy(HOME_TARGET);
      controls.update();
    }
  }

  function flyTo(position, target) {
    if (reducedMotion) {
      camera.position.copy(position);
      controls.target.copy(target);
      controls.update();
      goal = null;
    } else {
      goal = { position, target };
    }
  }

  function focus(id) {
    const entry = entries.get(id);
    if (!entry) return;
    const p = new THREE.Vector3(entry.root.position.x + entry.spot.x, entry.root.position.y, entry.root.position.z + entry.spot.z);
    const back = camera.aspect < 1 ? 11 : 6.2;
    flyTo(new THREE.Vector3(p.x * 0.55, p.y + 2.6 + (camera.aspect < 1 ? 2 : 0), p.z + back), new THREE.Vector3(p.x, p.y + 1.1, p.z));
  }

  function goHome() {
    flyTo(home.clone(), HOME_TARGET.clone());
  }

  function setSelected(id) {
    selected = id;
    for (const [key, entry] of entries) entry.label.classList.toggle('selected', key === id);
  }

  // ---- picking ----
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  function pick(event) {
    const rect = canvas.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(pickTargets, true)[0];
    return hit ? hit.object.userData.machineId : null;
  }
  let downAt = null;
  canvas.addEventListener('pointerdown', (e) => { downAt = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener('pointermove', (e) => {
    hovered = e.pointerType === 'mouse' ? pick(e) : null;
    canvas.style.cursor = hovered ? 'pointer' : 'grab';
  });
  canvas.addEventListener('pointerleave', () => { hovered = null; });
  canvas.addEventListener('click', (e) => {
    if (downAt && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > DRAG_PX) return;
    const id = pick(e);
    if (id) onSelect(id, entries.get(id).label);
  });

  // ---- animation ----
  const temp = new THREE.Vector3();
  function placeLabels() {
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    const items = [];
    for (const entry of entries.values()) {
      temp.set(
        entry.root.position.x + entry.spot.x,
        entry.root.position.y + 0.3 + 2.5 * entry.scale + 0.7,
        entry.root.position.z + entry.spot.z,
      ).project(camera);
      entry.label.hidden = temp.z > 1;
      if (entry.label.hidden) continue;
      const half = entry.label.offsetWidth / 2 + 6; // keep labels fully on screen on phones
      items.push({
        label: entry.label,
        half,
        height: entry.label.offsetHeight,
        x: Math.min(Math.max(((temp.x + 1) / 2) * w, half), w - half),
        y: ((1 - temp.y) / 2) * h, // the label's bottom edge
      });
    }
    // Crowded altars: go left to right and lift any label that would sit on top of an earlier one.
    items.sort((a, b) => a.x - b.x);
    const placed = [];
    for (const item of items) {
      for (let moved = true; moved; ) {
        moved = false;
        for (const other of placed) {
          const sideBySide = Math.abs(item.x - other.x) < item.half + other.half;
          const stacked = item.y > other.y - other.height && item.y - item.height < other.y;
          if (sideBySide && stacked) {
            item.y = other.y - other.height - 4;
            moved = true;
          }
        }
      }
      placed.push(item);
    }
    for (const item of items) {
      item.label.style.left = `${item.x}px`;
      item.label.style.top = `${item.y}px`;
    }
  }

  let last = 0;
  let frameId = 0;
  let running = false;
  const unit = new THREE.Vector3();
  function frame(now) {
    if (!running) return;
    frameId = requestAnimationFrame(frame);
    if (document.hidden || !stage.clientWidth || now - last < 33) return; // about 30 fps keeps laptops cool
    last = now;
    const t = now / 1000;
    if (goal) {
      camera.position.lerp(goal.position, 0.1);
      controls.target.lerp(goal.target, 0.1);
      if (camera.position.distanceTo(goal.position) < 0.05) goal = null;
    }
    controls.update();
    if (!reducedMotion) {
      for (const entry of entries.values()) {
        entry.root.position.y = entry.root.userData.baseY + Math.sin(t * 0.8 + entry.root.userData.phase) * 0.12;
        entry.body.rotation.y = Math.sin(t * 0.4 + entry.root.userData.phase) * 0.25;
        const hot = entry.label.dataset.id === hovered || entry.label.dataset.id === selected;
        unit.setScalar(entry.scale * (hot ? 1.08 : 1));
        entry.body.scale.lerp(unit, 0.2);
      }
      for (const f of flames) {
        const s = 1 + Math.sin(t * 9 + f.phase) * 0.12;
        f.flame.scale.set(s, 1.5 * s, s);
        f.halo.material.opacity = 0.24 + Math.sin(t * 6 + f.phase) * 0.06;
      }
    }
    renderer.render(scene, camera);
    placeLabels();
    stage.dataset.rendered = 'true';
  }

  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null;
  observer?.observe(stage);
  resize();

  return {
    focus,
    home: goHome,
    setSelected,
    start() {
      if (running) return;
      running = true;
      resize();
      frameId = requestAnimationFrame(frame);
    },
    stop() {
      running = false;
      cancelAnimationFrame(frameId);
    },
    dispose() {
      running = false;
      cancelAnimationFrame(frameId);
      observer?.disconnect();
      controls.dispose();
      scene.traverse((o) => {
        o.geometry?.dispose();
        o.material?.dispose();
      });
      for (const entry of entries.values()) { disposeModel(entry.body); entry.label.remove(); }
      renderer.dispose();
    },
  };
}
