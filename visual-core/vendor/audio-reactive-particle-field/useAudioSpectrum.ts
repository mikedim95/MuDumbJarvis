import { useCallback, useEffect, useRef, useState } from "react";
import {
  SPECTRUM_BIN_COUNT,
  type AudioEnergy,
} from "../components/AudioReactiveParticleField";

type MeterSnapshot = Pick<AudioEnergy, "average" | "low" | "mid" | "high">;

const initialEnergy = (): AudioEnergy => ({
  average: 0,
  high: 0,
  low: 0,
  mid: 0,
  pulsePhase: 0,
  transient: 0,
});

export function useAudioSpectrum() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const audioBinsRef = useRef(new Float32Array(SPECTRUM_BIN_COUNT));
  const audioEnergyRef = useRef<AudioEnergy>(initialEnergy());
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const frameRef = useRef(0);
  const dynamicsRef = useRef({
    lastBeatAt: Number.NEGATIVE_INFINITY,
    lastDrive: 0,
    lastTimestamp: 0,
  });
  const lastMeterUpdateRef = useRef(0);
  const [synthetic, setSyntheticState] = useState(true);
  const syntheticRef = useRef(true);
  const [playing, setPlaying] = useState(false);
  const [fileName, setFileName] = useState("No local file loaded");
  const [meter, setMeter] = useState<MeterSnapshot>({
    average: 0,
    high: 0,
    low: 0,
    mid: 0,
  });

  const setSynthetic = useCallback((next: boolean) => {
    syntheticRef.current = next;
    setSyntheticState(next);
    if (next && audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause();
    }
  }, []);

  const ensureAudioGraph = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return false;
    if (!audioContextRef.current) {
      const context = new AudioContext();
      const source = context.createMediaElementSource(audio);
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.72;
      source.connect(analyser).connect(context.destination);
      audioContextRef.current = context;
      analyserRef.current = analyser;
      sourceRef.current = source;
    }
    if (audioContextRef.current.state === "suspended") {
      await audioContextRef.current.resume();
    }
    return true;
  }, []);

  const loadFile = useCallback(async (file: File) => {
    const audio = audioRef.current;
    if (!audio) return;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const url = URL.createObjectURL(file);
    objectUrlRef.current = url;
    audio.src = url;
    audio.load();
    setFileName(file.name);
    setSynthetic(false);
    await ensureAudioGraph();
    await audio.play();
  }, [ensureAudioGraph, setSynthetic]);

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio?.src) return;
    setSynthetic(false);
    await ensureAudioGraph();
    if (audio.paused) await audio.play();
    else audio.pause();
  }, [ensureAudioGraph, setSynthetic]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onPause);
    return () => {
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onPause);
    };
  }, []);

  useEffect(() => {
    const frequencyData = new Uint8Array(512);
    const timeData = new Uint8Array(1024);
    const update = (timestamp: number) => {
      const seconds = timestamp / 1000;
      const bins = audioBinsRef.current;
      const energy = audioEnergyRef.current;
      const analyser = analyserRef.current;
      let low = 0;
      let mid = 0;
      let high = 0;
      let average = 0;

      if (syntheticRef.current) {
        const bpm = 108;
        const beatPhase = (seconds * bpm / 60) % 1;
        const offbeatPhase = (beatPhase + 0.5) % 1;
        const kick = Math.exp(-beatPhase * 9.5);
        const snare = Math.exp(-offbeatPhase * 13.5);
        const phrase = 0.5 + 0.5 * Math.sin(seconds * 0.42 - 0.8);
        const swell = 0.5 + 0.5 * Math.sin(seconds * 1.08 + 0.3);
        low = Math.min(1, 0.2 + kick * 0.72 + swell * 0.1);
        mid = Math.min(1, 0.17 + kick * 0.2 + snare * 0.54 + phrase * 0.12);
        high = Math.min(1, 0.13 + snare * 0.46 + Math.pow(swell, 5) * 0.34);
        average = Math.min(1, low * 0.48 + mid * 0.34 + high * 0.18);
        for (let index = 0; index < bins.length; index += 1) {
          const position = index / Math.max(1, bins.length - 1);
          const ridge = 0.5 + 0.5 * Math.sin(seconds * (1.8 + position * 4.6) - position * 19);
          const comb = Math.pow(0.5 + 0.5 * Math.sin(seconds * 5.4 + index * 0.81), 5);
          const bassShape = Math.exp(-position * 3.8) * kick;
          const upperShape = Math.pow(position, 0.72) * (snare * 0.62 + high * 0.38);
          const target = Math.min(
            1,
            Math.pow(0.07 + ridge * 0.4 + comb * 0.34 + bassShape * 0.62 + upperShape * 0.42, 0.76),
          );
          bins[index] += (target - bins[index]) * (target > bins[index] ? 0.52 : 0.13);
        }
      } else if (analyser && playing) {
        analyser.getByteFrequencyData(frequencyData);
        analyser.getByteTimeDomainData(timeData);
        const sampleRate = audioContextRef.current?.sampleRate ?? 48000;
        const binWidth = sampleRate / analyser.fftSize;
        const lowEnd = Math.max(2, Math.round(190 / binWidth));
        const midEnd = Math.max(lowEnd + 1, Math.round(2100 / binWidth));
        const highEnd = Math.min(frequencyData.length, Math.round(12000 / binWidth));
        const bandAverage = (start: number, end: number, exponent = 1) => {
          let total = 0;
          for (let index = start; index < end; index += 1) {
            total += Math.pow(frequencyData[index] / 255, exponent);
          }
          return total / Math.max(1, end - start);
        };
        low = Math.min(1, bandAverage(1, lowEnd, 0.72) * 1.38);
        mid = Math.min(1, bandAverage(lowEnd, midEnd, 0.72) * 1.55);
        high = Math.min(1, bandAverage(midEnd, highEnd, 0.72) * 2.12);
        let rms = 0;
        for (const sample of timeData) rms += Math.pow((sample - 128) / 128, 2);
        const spectralAverage = bandAverage(1, highEnd, 0.72);
        average = Math.min(1, Math.sqrt(rms / timeData.length) * 4.6 + spectralAverage * 0.42);
        for (let index = 0; index < bins.length; index += 1) {
          const start = Math.max(1, Math.floor(Math.pow(index / bins.length, 1.55) * (highEnd - 1)));
          const end = Math.max(start + 1, Math.floor(Math.pow((index + 1) / bins.length, 1.55) * (highEnd - 1)));
          const target = Math.pow(bandAverage(start, Math.min(highEnd, end)), 0.82);
          bins[index] += (target - bins[index]) * (target > bins[index] ? 0.44 : 0.15);
        }
      } else {
        for (let index = 0; index < bins.length; index += 1) bins[index] *= 0.94;
      }

      const response = (current: number, next: number, attack: number, release: number) => (
        current + (next - current) * (next > current ? attack : release)
      );
      energy.low = response(energy.low, low, 0.42, 0.13);
      energy.mid = response(energy.mid, mid, 0.4, 0.14);
      energy.high = response(energy.high, high, 0.46, 0.17);
      energy.average = response(energy.average, average, 0.38, 0.12);

      const dynamics = dynamicsRef.current;
      const deltaSeconds = dynamics.lastTimestamp > 0
        ? Math.min(0.08, Math.max(1 / 120, (timestamp - dynamics.lastTimestamp) / 1000))
        : 1 / 60;
      const drive = low * 0.54 + mid * 0.32 + average * 0.14;
      const flux = Math.max(0, drive - dynamics.lastDrive);
      const beatPhase = (seconds * 108 / 60) % 1;
      if (syntheticRef.current) {
        energy.pulsePhase = beatPhase;
      } else if (playing) {
        const sinceLastBeat = timestamp - dynamics.lastBeatAt;
        if (sinceLastBeat > 360 && ((flux > 0.012 && drive > 0.1) || sinceLastBeat > 1380)) {
          energy.pulsePhase = 0;
          dynamics.lastBeatAt = timestamp;
        } else {
          energy.pulsePhase = Math.min(1, energy.pulsePhase + deltaSeconds / 1.08);
        }
      } else {
        energy.pulsePhase = Math.min(1, energy.pulsePhase + deltaSeconds / 1.4);
      }
      const pulseBloom = energy.pulsePhase > 0.12 && energy.pulsePhase < 0.72
        ? Math.sin(((energy.pulsePhase - 0.12) / 0.6) * Math.PI)
        : 0;
      const transientTarget = Math.min(1, Math.max(flux * 14, pulseBloom * (0.28 + drive * 0.72)));
      energy.transient += (transientTarget - energy.transient) * (
        1 - Math.exp(-deltaSeconds * (transientTarget > energy.transient ? 18 : 5.5))
      );
      dynamics.lastDrive = drive;
      dynamics.lastTimestamp = timestamp;

      if (timestamp - lastMeterUpdateRef.current > 100) {
        lastMeterUpdateRef.current = timestamp;
        setMeter({ average: energy.average, low: energy.low, mid: energy.mid, high: energy.high });
      }
      frameRef.current = requestAnimationFrame(update);
    };
    frameRef.current = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frameRef.current);
  }, [playing]);

  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    void audioContextRef.current?.close();
  }, []);

  return {
    active: synthetic || playing,
    audioBinsRef,
    audioEnergyRef,
    audioRef,
    fileName,
    loadFile,
    meter,
    playing,
    setSynthetic,
    synthetic,
    togglePlayback,
  };
}
