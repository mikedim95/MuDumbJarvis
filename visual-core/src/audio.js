/* Browser-only analysis adapted from upstream useAudioSpectrum.ts (MIT).
 * Taps existing, user-authorized audio nodes. Never opens a microphone,
 * creates/resumes an AudioContext, uploads audio, or plays a synthetic track.
 */
export const BIN_COUNT = 48;
const clamp = n => Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
export function createSpectrum() {
  const bins = new Float32Array(BIN_COUNT);
  const energy = {average: 0, low: 0, mid: 0, high: 0, transient: 0};
  const channels = new Map();
  let lastDrive = 0;
  function attach(kind, context, source) {
    if (!context || !source || !['input', 'output'].includes(kind)) return () => {};
    let channel = channels.get(kind);
    if (!channel || channel.context !== context) {
      if (channel) { channel.analyser.disconnect(); channel.sink.disconnect(); }
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.72;
      const sink = context.createGain(); sink.gain.value = 0;
      analyser.connect(sink); sink.connect(context.destination);
      channel = {context, analyser, sink, sources: new Set(), frequencies: new Uint8Array(512), time: new Uint8Array(1024)};
      channels.set(kind, channel);
    }
    if (!channel.sources.has(source)) { source.connect(channel.analyser); channel.sources.add(source); }
    return () => { try { source.disconnect(channel.analyser); } catch {} channel.sources.delete(source); };
  }
  function update(kind, delta) {
    const channel = channels.get(kind);
    let low = 0, mid = 0, high = 0, average = 0;
    const response = (current, target, attack = 14, release = 5) =>
      current + (target - current) * (1 - Math.exp(-delta * (target > current ? attack : release)));
    if (channel?.context.state === 'running' && channel.sources.size) {
      const {analyser, frequencies: f, time: t, context} = channel;
      analyser.getByteFrequencyData(f); analyser.getByteTimeDomainData(t);
      const width = context.sampleRate / analyser.fftSize;
      const lo = Math.min(f.length - 2, Math.max(2, Math.round(190 / width)));
      const mi = Math.min(f.length - 1, Math.max(lo + 1, Math.round(2100 / width)));
      const hi = Math.min(f.length, Math.max(mi + 1, Math.round(12000 / width)));
      const band = (start, end, exponent = 0.72) => {
        let sum = 0;
        for (let i = start; i < end; i++) sum += Math.pow(f[i] / 255, exponent);
        return sum / Math.max(1, end - start);
      };
      low = clamp(band(1, lo) * 1.38); mid = clamp(band(lo, mi) * 1.55); high = clamp(band(mi, hi) * 2.12);
      let rms = 0; for (const sample of t) rms += ((sample - 128) / 128) ** 2;
      average = clamp(Math.sqrt(rms / t.length) * 4.6 + band(1, hi) * 0.42);
      for (let i = 0; i < bins.length; i++) {
        const start = Math.max(1, Math.floor((i / bins.length) ** 1.55 * (hi - 1)));
        const end = Math.min(hi, Math.max(start + 1, Math.floor(((i + 1) / bins.length) ** 1.55 * (hi - 1))));
        bins[i] = response(bins[i], Math.pow(band(start, end, 1), 0.82));
      }
    } else { for (let i = 0; i < bins.length; i++) bins[i] = response(bins[i], 0); }
    const drive = low * 0.54 + mid * 0.32 + average * 0.14;
    energy.transient = response(energy.transient, clamp(Math.max(0, drive - lastDrive) * 14), 18, 5.5);
    lastDrive = drive;
    for (const [key, target] of Object.entries({low, mid, high, average})) energy[key] = response(energy[key], target);
    return energy;
  }
  function dispose() {
    for (const c of channels.values()) {
      for (const source of c.sources) { try { source.disconnect(c.analyser); } catch {} }
      c.analyser.disconnect(); c.sink.disconnect();
    }
    channels.clear();
  }
  return {bins, energy, attach, update, dispose};
}
