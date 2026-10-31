// The one shared WebGL viewer. Loaded lazily by app.js so that a device without WebGL (or a
// failed import) never breaks the rest of the altar.
import * as THREE from './vendor/three.module.js';
import { buildModel, fitModel, disposeModel } from './models3d.js';

export function createViewer(container, reducedMotion) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); // throws without WebGL
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-hidden', 'true');
  container.append(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 50);
  camera.position.set(0, 1.4, 6);
  camera.lookAt(0, 0, 0);
  scene.add(new THREE.HemisphereLight(0xffe2b8, 0x241636, 1.5));
  const key = new THREE.DirectionalLight(0xfff0d0, 2.4);
  key.position.set(3, 5, 4);
  scene.add(key);
  const warm = new THREE.PointLight(0xffa94d, 18, 12);
  warm.position.set(-3, 1, 3);
  scene.add(warm);

  let current = null;
  let yaw = 0.7;
  let pitch = 0.18;
  let frame = 0;
  let last = 0;
  let dragging = false;
  let lastX = 0;

  const draw = () => {
    if (current) {
      current.rotation.y = yaw;
      current.rotation.x = pitch;
    }
    renderer.render(scene, camera);
  };

  const resize = () => {
    const w = container.clientWidth || 320;
    const h = container.clientHeight || 280;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    draw();
  };

  const loop = (now) => {
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    if (!dragging) yaw += dt * 0.45;
    draw();
    frame = requestAnimationFrame(loop);
  };

  canvas.addEventListener('pointerdown', (e) => {
    dragging = true;
    lastX = e.clientX;
    canvas.setPointerCapture?.(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    yaw += (e.clientX - lastX) * 0.01;
    lastX = e.clientX;
    if (reducedMotion) draw();
  });
  const endDrag = () => {
    dragging = false;
  };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // Keyboard users rotate with the arrow keys while the viewer has focus.
  container.addEventListener('keydown', (e) => {
    const step = 0.2;
    if (e.key === 'ArrowLeft') yaw -= step;
    else if (e.key === 'ArrowRight') yaw += step;
    else if (e.key === 'ArrowUp') pitch = Math.max(-0.6, pitch - step / 2);
    else if (e.key === 'ArrowDown') pitch = Math.min(0.6, pitch + step / 2);
    else return;
    e.preventDefault();
    draw();
  });

  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null;
  observer?.observe(container);

  return {
    /** Show the model for `kind`; returns the kind actually used ('generic' for unknown kinds). */
    show(kind) {
      if (current) {
        scene.remove(current);
        disposeModel(current);
      }
      current = fitModel(buildModel(kind));
      scene.add(current);
      resize();
      return current.userData.kind;
    },
    start() {
      cancelAnimationFrame(frame);
      resize();
      if (!reducedMotion) {
        last = performance.now();
        frame = requestAnimationFrame(loop);
      }
    },
    stop() {
      cancelAnimationFrame(frame);
    },
    dispose() {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      if (current) disposeModel(current);
      renderer.dispose();
      canvas.remove();
    },
  };
}
