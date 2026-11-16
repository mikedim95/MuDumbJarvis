import {createSpectrum} from './audio.js';
import {arrangements, createGPU, createFallback} from './field.js';

const canvas = document.getElementById('reactor'), wrap = document.getElementById('reactorWrap');
if (canvas && wrap) {
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const spectrum = createSpectrum(), pointer = {x: 20, y: 20};
  const controller = new AbortController(), {signal} = controller;
  let scene, currentCanvas = canvas, state = 'standby', task = window.JarvisTaskVisualState || null, disposed = false;
  let time = 0, lastDraw = 0, frame = 0, raf = 0, activity = 0.1, arrangement = 'ring';
  const styles = {
    standby: {color: '#00dfff', drive: 0.10}, listening: {color: '#19f0d8', drive: 0.5},
    thinking: {color: '#ffb647', drive: 0.65}, tool: {color: '#ffc96b', drive: 0.9},
    speaking: {color: '#00e5ff', drive: 0.5}, error: {color: '#ff667a', drive: 0.18},
  };
  function initFallback() {
    // A canvas that acquired a WebGL context cannot later acquire a 2D one.
    const replacement = currentCanvas.cloneNode(false);
    currentCanvas.replaceWith(replacement); currentCanvas = replacement;
    scene = createFallback(currentCanvas);
    wrap.dataset.renderer = scene?.kind || 'unavailable'; resize();
  }
  try { scene = createGPU(currentCanvas, innerWidth < 760); } catch { scene = null; }
  if (!scene) initFallback();
  else wrap.dataset.renderer = scene.kind;
  function resize() {
    if (!scene || disposed) return;
    const box = wrap.getBoundingClientRect();
    scene.resize(Math.max(1, box.width), Math.max(1, box.height)); schedule();
  }
  function readState() {
    const direct = window.JarvisCoreSignals?.read?.() || {state: 'standby', level: 0};
    const mode = document.getElementById('commandMode')?.value;
    if (mode === 'chat' || ['listening', 'speaking'].includes(direct.state)) return direct;
    if (task?.active) return {...direct, state: 'thinking', label: 'WORKING', hint: task.identifier};
    if (task?.status === 'blocked') return {...direct, state: 'error', label: 'BLOCKED', hint: 'REVIEW TASK DETAILS'};
    if (task) return {...direct, state: 'standby', label: ({todo:'QUEUED',backlog:'QUEUED',cancelled:'STOPPED',done:'COMPLETE',in_review:'APPROVAL'})[task.status] || task.status.toUpperCase(), hint: task.identifier};
    return {...direct, state: 'standby', label: 'STANDBY', hint: 'ENTER AN OBJECTIVE BELOW'};
  }
  function draw(timestamp) {
    raf = 0;
    if (disposed || document.hidden || !scene) return;
    if (!motion.matches && timestamp - lastDraw < 1000 / 30) { schedule(); return; }
    const delta = Math.min(0.08, Math.max(0.001, (timestamp - lastDraw) / 1000)); lastDraw = timestamp;
    if (!motion.matches) time += delta;
    const input = readState(); state = styles[input.state] ? input.state : 'standby';
    const style = styles[state]; activity += (style.drive - activity) * (1 - Math.exp(-delta * 4));
    const label = document.getElementById('stateLabel'), hint = document.getElementById('stateHint');
    if (input.label && label.textContent !== input.label) label.textContent = input.label;
    if (input.hint && hint.textContent !== input.hint) hint.textContent = input.hint;
    label.style.color = style.color;
    const channel = state === 'listening' ? 'input' : input.playing ? 'output' : null;
    const energy = spectrum.update(channel, delta);
    if (state === 'listening') energy.average = Math.max(energy.average, Math.min(1, input.level || 0));
    scene.render({time: motion.matches ? 0 : time, delta, activity, color: style.color,
      bins: spectrum.bins, energy, pointer, reduced: motion.matches});
    wrap.dataset.visualState = state; frame++;
    if (!motion.matches) schedule();
  }
  function schedule() { if (!raf && !disposed && !document.hidden) raf = requestAnimationFrame(draw); }
  function onTask(event) { task = event.detail; schedule(); }
  window.addEventListener('jarvis-task-visual-state', onTask, {signal});
  window.addEventListener('jarvis-core-state', schedule, {signal});
  wrap.addEventListener('pointermove', event => {
    if (motion.matches) return;
    const r = wrap.getBoundingClientRect(); pointer.x = (event.clientX - r.left) / r.width * 2 - 1;
    pointer.y = 1 - (event.clientY - r.top) / r.height * 2; schedule();
  }, {signal});
  wrap.addEventListener('pointerleave', () => { pointer.x = pointer.y = 20; }, {signal});
  currentCanvas.addEventListener('webglcontextlost', event => {
    event.preventDefault(); scene?.dispose(); initFallback(); schedule();
  }, {signal});
  const observer = new ResizeObserver(resize); observer.observe(wrap);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
    else { lastDraw = performance.now(); schedule(); }
  }, {signal});
  function motionChanged() { cancelAnimationFrame(raf); raf = 0; schedule(); }
  motion.addEventListener('change', motionChanged);
  function dispose() {
    if (disposed) return;
    disposed = true; cancelAnimationFrame(raf); controller.abort(); observer.disconnect();
    motion.removeEventListener('change', motionChanged); spectrum.dispose(); scene?.dispose();
  }
  window.addEventListener('pagehide', () => { cancelAnimationFrame(raf); raf = 0; }, {signal});
  window.addEventListener('pageshow', schedule, {signal});
  window.JarvisVisualCore = {
    attachAudio(kind, context, source) { try { return spectrum.attach(kind, context, source); } catch { return () => {}; } },
    setArrangement(name) {
      if (!Object.hasOwn(arrangements, name)) throw new RangeError('Unknown core arrangement');
      arrangement = name; schedule(); return arrangement;
    },
    snapshot: () => ({renderer: scene?.kind || 'unavailable', arrangement, state, frame,
      particles: scene?.count || 0, reducedMotion: motion.matches, hidden: document.hidden,
      motionTime: motion.matches ? 0 : time, audioEnergy: {...spectrum.energy}, disposed}),
    dispose,
  };
  resize(); schedule();
}
