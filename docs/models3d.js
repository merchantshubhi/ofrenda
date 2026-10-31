// Hand-built 3D stand-ins for each kind of machine, made only from Three.js primitives.
// They are simple, original shapes, not copies of any NASA artwork or CAD model.
import * as THREE from './vendor/three.module.js';

/** Soft colours shared with the altar scene (candles, petals). */
export const PALETTE = { cream: 0xfff3dc, marigold: 0xf5a623, navy: 0x1b2554 };

const MAT = {
  body: new THREE.MeshStandardMaterial({ color: 0xc9b99a, roughness: 0.7, metalness: 0.2 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x3a3347, roughness: 0.8, metalness: 0.1 }),
  gold: new THREE.MeshStandardMaterial({ color: 0xf0b429, roughness: 0.35, metalness: 0.7 }),
  panel: new THREE.MeshStandardMaterial({ color: 0x2b4a8f, roughness: 0.4, metalness: 0.5 }),
  white: new THREE.MeshStandardMaterial({ color: 0xf1ece0, roughness: 0.5, metalness: 0.2 }),
  glow: new THREE.MeshStandardMaterial({ color: 0xffd28a, emissive: 0xff9f43, emissiveIntensity: 0.6 }),
};

function mesh(geometry, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(geometry, material);
  m.position.set(x, y, z);
  return m;
}

/** A cylinder stretched between two points, for legs and struts. */
function strut(a, b, radius, material) {
  const from = new THREE.Vector3(...a);
  const to = new THREE.Vector3(...b);
  const length = from.distanceTo(to);
  const m = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, length, 8), material);
  m.position.copy(from).add(to).multiplyScalar(0.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), to.clone().sub(from).normalize());
  return m;
}

function buildRover() {
  const g = new THREE.Group();
  g.add(mesh(new THREE.BoxGeometry(1.6, 0.35, 1.0), MAT.body, 0, 0.55, 0));
  g.add(mesh(new THREE.BoxGeometry(1.5, 0.05, 0.95), MAT.panel, 0, 0.77, 0));
  g.add(mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.8, 10), MAT.white, 0.55, 1.15, 0.25));
  g.add(mesh(new THREE.BoxGeometry(0.34, 0.16, 0.16), MAT.dark, 0.55, 1.58, 0.25));
  g.add(mesh(new THREE.SphereGeometry(0.05, 12, 8), MAT.glow, 0.7, 1.58, 0.34));
  g.add(mesh(new THREE.SphereGeometry(0.05, 12, 8), MAT.glow, 0.4, 1.58, 0.34));
  g.add(strut([0.8, 0.5, -0.2], [1.25, 0.35, -0.2], 0.04, MAT.dark));
  for (const x of [-0.65, 0, 0.65]) {
    for (const z of [-0.62, 0.62]) {
      const wheel = mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.16, 20), MAT.dark, x, 0.2, z);
      wheel.rotation.x = Math.PI / 2;
      g.add(wheel);
    }
  }
  return g;
}

function buildProbe() {
  const g = new THREE.Group();
  g.add(mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.45, 10), MAT.body));
  const dish = mesh(new THREE.SphereGeometry(1.1, 32, 12, 0, Math.PI * 2, Math.PI - 0.6, 0.6), MAT.white, 0, 0, 0.9);
  dish.material = dish.material.clone();
  dish.material.side = THREE.DoubleSide;
  dish.rotation.x = Math.PI / 2; // opens toward +z
  g.add(dish);
  g.add(strut([0, 0, 0.3], [0, 0, 1.2], 0.025, MAT.dark));
  const boom = strut([-0.4, 0, -0.1], [-2.2, 0, -0.1], 0.04, MAT.dark);
  g.add(boom);
  for (const x of [-1.0, -1.6, -2.1]) {
    const rtg = mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.5, 12), MAT.gold, x, 0, -0.1);
    g.add(rtg);
  }
  g.add(strut([0.4, 0, -0.1], [2.4, 0.2, -0.1], 0.02, MAT.dark));
  g.add(mesh(new THREE.SphereGeometry(0.07, 10, 8), MAT.glow, 2.4, 0.2, -0.1));
  g.add(mesh(new THREE.BoxGeometry(0.5, 0.3, 0.3), MAT.dark, 0.2, -0.38, 0.1));
  return g;
}

function buildLander() {
  const g = new THREE.Group();
  g.add(mesh(new THREE.CylinderGeometry(0.8, 0.9, 0.5, 6), MAT.body, 0, 0.95, 0));
  g.add(mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.06, 6), MAT.gold, 0, 1.22, 0));
  for (let i = 0; i < 3; i += 1) {
    const a = (i * Math.PI * 2) / 3 + Math.PI / 6;
    const cos = Math.cos(a);
    const sin = Math.sin(a);
    g.add(strut([0.55 * cos, 0.85, 0.55 * sin], [1.35 * cos, 0.06, 1.35 * sin], 0.045, MAT.dark));
    g.add(mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.04, 16), MAT.dark, 1.35 * cos, 0.03, 1.35 * sin));
  }
  for (const side of [-1, 1]) {
    const panel = mesh(new THREE.BoxGeometry(1.1, 0.04, 0.6), MAT.panel, side * 1.25, 1.42, 0);
    panel.rotation.z = side * -0.25;
    g.add(panel);
    g.add(strut([side * 0.75, 1.2, 0], [side * 0.9, 1.35, 0], 0.03, MAT.dark));
  }
  g.add(strut([0, 1.25, 0], [0, 1.95, 0], 0.035, MAT.white));
  g.add(mesh(new THREE.BoxGeometry(0.3, 0.14, 0.14), MAT.dark, 0, 2.02, 0));
  g.add(strut([0.4, 0.7, 0], [0.4, 0.45, 0.5], 0.03, MAT.dark));
  return g;
}

/** Any machine we have no special shape for: a small beacon with a ring. */
function buildGeneric() {
  const g = new THREE.Group();
  g.add(mesh(new THREE.IcosahedronGeometry(0.7, 1), MAT.body));
  const ring = mesh(new THREE.TorusGeometry(1.1, 0.04, 8, 48), MAT.gold);
  ring.rotation.x = Math.PI / 2.4;
  g.add(ring);
  g.add(mesh(new THREE.SphereGeometry(0.12, 12, 8), MAT.glow, 0, 0.85, 0));
  return g;
}

const BUILDERS = { rover: buildRover, probe: buildProbe, lander: buildLander };

/** Build the model for a kind; an unknown kind gets the generic fallback. */
export function buildModel(kind) {
  const build = Object.hasOwn(BUILDERS, kind) ? BUILDERS[kind] : buildGeneric;
  const group = build();
  group.userData.kind = Object.hasOwn(BUILDERS, kind) ? kind : 'generic';
  return group;
}

/** Centre a model on the origin and scale it so its largest side is `size`. */
export function fitModel(group, size = 2.8) {
  const box = new THREE.Box3().setFromObject(group);
  const dims = box.getSize(new THREE.Vector3());
  const longest = Math.max(dims.x, dims.y, dims.z) || 1;
  const centre = box.getCenter(new THREE.Vector3());
  group.position.sub(centre);
  const holder = new THREE.Group();
  holder.add(group);
  holder.scale.setScalar(size / longest);
  holder.userData.kind = group.userData.kind;
  return holder;
}

/** Free GPU geometry. Materials are shared module-wide, so they are left alone. */
export function disposeModel(object) {
  object.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
  });
}
