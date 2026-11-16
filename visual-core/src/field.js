import * as THREE from 'three';
import {BIN_COUNT} from './audio.js';
import {vertex, fragment, filamentVertex, filamentFragment} from './shaders.js';

// A shape is geometry plus material attributes, independent of HUD/task state.
// Additional floating arrangements can provide another builder here later.
export const arrangements = {ring: {radius: 2.06, count: 6400, compactCount: 3200}};
export const random = (index, salt) => {
  const value = Math.sin((index + 1) * (12.9898 + salt * 37.719)) * 43758.5453;
  return value - Math.floor(value);
};
export function ringData(count) {
  const position = new Float32Array(count * 3), seed = new Float32Array(count);
  const role = new Float32Array(count), slice = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const pick = random(i, 1.31), angle = random(i, 2.73) * Math.PI * 2;
    const minor = random(i, 4.11) * Math.PI * 2;
    seed[i] = random(i, 0.17);
    role[i] = pick < 0.58 ? 0 : pick < 0.90 ? 1 : 2;
    slice[i] = role[i] === 1 ? Math.floor(random(i, 5.93) * 12) / 11 : random(i, 5.93);
    const tube = role[i] === 2 ? 0.23 + random(i, 8.47) * 0.16 : 0.10 + random(i, 8.47) * 0.12;
    const section = role[i] === 1 ? slice[i] * Math.PI * 2 : minor;
    const radius = arrangements.ring.radius + Math.cos(section) * tube;
    position.set([Math.cos(angle) * radius, Math.sin(angle) * radius, Math.sin(section) * tube], i * 3);
  }
  return {position, seed, role, slice};
}
function makeGeometry(data) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(data.position, 3));
  for (const [name, array] of [['aSeed', data.seed], ['aRole', data.role], ['aSlice', data.slice]])
    geometry.setAttribute(name, new THREE.BufferAttribute(array, 1));
  return geometry;
}
function makeFilaments() {
  const positions = [], lines = [], times = [];
  for (let lane = 0; lane < 6; lane++) {
    for (let p = 0; p < 240; p++) for (const t of [p / 240, (p + 1) / 240]) {
      positions.push(0, 0, 0); lines.push(lane / 5); times.push(t);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute('aLine', new THREE.Float32BufferAttribute(lines, 1));
  g.setAttribute('aT', new THREE.Float32BufferAttribute(times, 1));
  return g;
}
export function createGPU(canvas, compact) {
  const options = {alpha: true, antialias: false, powerPreference: 'low-power'};
  const context = canvas.getContext('webgl2', options);
  if (!context) return null;
  const renderer = new THREE.WebGLRenderer({canvas, context, ...options});
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  const scene = new THREE.Scene(), group = new THREE.Group();
  const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 40); camera.position.z = 7.8;
  scene.add(group);
  const count = compact ? arrangements.ring.compactCount : arrangements.ring.count;
  const spectrum = new THREE.DataTexture(new Uint8Array(BIN_COUNT), BIN_COUNT, 1, THREE.RedFormat);
  spectrum.minFilter = spectrum.magFilter = THREE.LinearFilter;
  spectrum.wrapS = THREE.ClampToEdgeWrapping; spectrum.needsUpdate = true;
  const uniforms = {
    uTime: {value: 0}, uPixelRatio: {value: renderer.getPixelRatio()}, uActivity: {value: 0.1},
    uEnvelope: {value: 0}, uTransient: {value: 0}, uBands: {value: new THREE.Vector3()},
    uPointer: {value: new THREE.Vector2(20, 20)}, uColor: {value: new THREE.Color('#00dfff')},
    uSpectrum: {value: spectrum},
  };
  const geometry = makeGeometry(ringData(count)), filaments = makeFilaments();
  const material = new THREE.ShaderMaterial({vertexShader: vertex, fragmentShader: fragment,
    uniforms, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending});
  const lineMaterial = new THREE.ShaderMaterial({vertexShader: filamentVertex, fragmentShader: filamentFragment,
    uniforms, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending});
  const points = new THREE.Points(geometry, material), lanes = new THREE.LineSegments(filaments, lineMaterial);
  points.frustumCulled = lanes.frustumCulled = false; group.add(points, lanes);
  let uploadClock = 0, width = 0, height = 0;
  function resize(w, h) {
    width = w; height = h;
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    uniforms.uPixelRatio.value = renderer.getPixelRatio();
  }
  function render(frame) {
    const {time, delta, activity, energy, bins, color, pointer, reduced} = frame;
    uniforms.uTime.value = time; uniforms.uActivity.value = activity;
    uniforms.uEnvelope.value = energy.average; uniforms.uTransient.value = energy.transient;
    uniforms.uBands.value.set(energy.low, energy.mid, energy.high);
    uniforms.uColor.value.set(color);
    const visibleHeight = 2 * Math.tan(44 * Math.PI / 360) * 7.8;
    uniforms.uPointer.value.set(pointer.x * visibleHeight * camera.aspect / 2, pointer.y * visibleHeight / 2);
    uploadClock += delta;
    if (uploadClock >= 1 / 30) {
      uploadClock = 0;
      for (let i = 0; i < BIN_COUNT; i++) spectrum.image.data[i] = Math.round(bins[i] * 255);
      spectrum.needsUpdate = true;
    }
    group.rotation.x = 0.24 + (reduced ? 0 : Math.sin(time * 0.24) * 0.11);
    group.rotation.y = -0.18 + (reduced ? 0 : Math.sin(time * 0.19 + 0.8) * 0.16);
    group.rotation.z = reduced ? 0 : time * 0.035;
    group.position.y = reduced ? 0 : Math.sin(time * 0.74) * 0.095 + Math.sin(time * 0.31) * 0.025;
    if (width && height) renderer.render(scene, camera);
  }
  function dispose() {
    geometry.dispose(); filaments.dispose(); material.dispose(); lineMaterial.dispose();
    spectrum.dispose(); renderer.dispose();
  }
  return {kind: 'webgl2', count, resize, render, dispose};
}

export function createFallback(canvas) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const count = 900, data = ringData(count);
  let w = 0, h = 0, dpr = 1;
  function resize(width, height) {
    dpr = Math.min(devicePixelRatio || 1, 1.5); w = width; h = height;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function render({time, activity, energy, color, reduced}) {
    ctx.clearRect(0, 0, w, h); ctx.globalCompositeOperation = 'lighter';
    const scale = Math.min(w, h) / 6.3, turn = time * (0.13 + activity * 0.12);
    const breath = 1 + Math.sin(time * 0.82) * 0.012 + energy.average * 0.06;
    const lift = reduced ? 0 : Math.sin(time * 0.74) * 0.095 * scale;
    const glow = ctx.createRadialGradient(w / 2, h / 2, scale * 1.85, w / 2, h / 2, scale * 2.5);
    glow.addColorStop(0, 'transparent'); glow.addColorStop(0.5, color + '10'); glow.addColorStop(1, 'transparent');
    ctx.fillStyle = glow; ctx.fillRect(0, 0, w, h); ctx.fillStyle = color;
    for (let i = 0; i < count; i++) {
      const x = data.position[i * 3], y = data.position[i * 3 + 1], z = data.position[i * 3 + 2];
      const tx = (x * Math.cos(turn) - y * Math.sin(turn)) * breath;
      const ty = (x * Math.sin(turn) + y * Math.cos(turn)) * breath;
      ctx.globalAlpha = 0.22 + 0.5 * (0.5 + 0.5 * Math.sin(time * 1.2 + data.seed[i] * 47));
      const size = 0.45 + data.seed[i] * 0.7;
      ctx.beginPath(); ctx.arc(w / 2 + tx * scale, h / 2 + ty * scale * 0.96 + z * scale * 0.24 + lift, size, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  }
  return {kind: 'canvas2d', count, resize, render, dispose() {ctx.clearRect(0, 0, w, h);}};
}
