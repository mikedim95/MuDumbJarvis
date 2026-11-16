import { useEffect, useMemo, useRef } from "react";
import type { MutableRefObject } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  ClampToEdgeWrapping,
  DataTexture,
  LinearFilter,
  RedFormat,
  ShaderMaterial,
  Vector2,
  Vector3,
} from "three";

export const SPECTRUM_BIN_COUNT = 48;

export type AudioEnergy = {
  average: number;
  high: number;
  low: number;
  mid: number;
  pulsePhase: number;
  transient: number;
};

export type AudioReactiveParticleFieldProps = {
  active: boolean;
  audioBinsRef: MutableRefObject<Float32Array>;
  audioEnergyRef: MutableRefObject<AudioEnergy>;
  compact: boolean;
};

type ParticleUniforms = {
  uActivity: { value: number };
  uBands: { value: Vector3 };
  uBurstAmount: { value: number };
  uEnvelope: { value: number };
  uPixelRatio: { value: number };
  uPointer: { value: Vector2 };
  uPulsePhase: { value: number };
  uPulseStrength: { value: number };
  uSpectrum: { value: DataTexture };
  uTime: { value: number };
};

type BurstUniforms = Omit<ParticleUniforms, "uPixelRatio" | "uPointer">;

const particleVertexShader = /* glsl */ `
  attribute float aSeed;
  attribute float aRole;
  attribute float aSlice;
  uniform float uTime;
  uniform float uPixelRatio;
  uniform float uActivity;
  uniform float uBurstAmount;
  uniform float uEnvelope;
  uniform float uPulsePhase;
  uniform float uPulseStrength;
  uniform sampler2D uSpectrum;
  uniform vec2 uPointer;
  uniform vec3 uBands;
  varying float vAlpha;
  varying float vAccent;
  varying float vRole;

  #define TAU 6.283185307179586

  void main() {
    vec3 center = vec3(0.24, 0.38, -2.04);
    vec3 local = position - center;
    float low = uBands.x;
    float mid = uBands.y;
    float high = uBands.z;

    float roleShell = 1.0 - step(0.5, aRole);
    float roleSeam = step(0.5, aRole) * (1.0 - step(1.5, aRole));
    float roleHalo = step(1.5, aRole);
    float angle = atan(local.z / 2.75, local.x / 6.42);
    float latitude = clamp(local.y / 3.86, -1.0, 1.0);

    float rotationSpeed =
      roleShell * 0.26 +
      roleSeam * mix(-0.34, 0.37, step(0.5, mod(aSlice * 11.0, 2.0))) +
      roleHalo * 0.46;
    float turn = uTime * rotationSpeed;
    float cosTurn = cos(turn);
    float sinTurn = sin(turn);
    local.xz = mat2(cosTurn, -sinTurn, sinTurn, cosTurn) * local.xz;

    float coherentBreath = sin(uTime * 0.82) * 0.052
      + sin(uTime * 0.33 + 1.2) * 0.042;
    float breathing = coherentBreath;
    breathing += sin(uTime * 0.72 + aSeed * 1.7) * 0.028;
    breathing += sin(uTime * 0.94 + aSlice * 0.8) * 0.032;
    breathing += sin(uTime * (1.12 + low * 0.94) + aSlice * 7.0)
      * uActivity
      * (0.03 + low * 0.11 + roleHalo * 0.03);
    breathing += uEnvelope * (0.038 + roleHalo * 0.032);
    // Melody pump: bass swells push the whole shell outward while quiet
    // passages let it sink back inward, so the ring breathes with the music.
    breathing += uActivity * (
      low * (0.09 + 0.09 * sin(uTime * 2.3 + aSlice * 3.6))
      + uEnvelope * 0.06
    );
    local *= 1.0 + breathing;

    vec3 radial = normalize(vec3(local.x / 6.42, local.y / 3.86, local.z / 2.75) + vec3(0.0001));
    float traveling = pow(
      max(0.0, sin(angle * 2.4 - uTime * (1.18 + mid * 0.7) + latitude * 4.2)),
      10.0
    );
    float counter = pow(
      max(0.0, cos(angle * 1.35 + uTime * 0.86 - aSlice * 11.0)),
      14.0
    );
    float fineWave = sin(angle * 8.0 + latitude * 17.0 - uTime * 1.78 + aSeed * 9.0);
    float idleWave = sin(angle * 3.2 - uTime * 1.34 + latitude * 5.4 + aSeed * 1.7);
    float waveFront = sin(angle * 4.4 - uTime * 1.12 + latitude * 7.2);
    local += radial * (
      roleShell * (
        fineWave * (0.055 + mid * 0.13)
        + idleWave * 0.095
        + waveFront * 0.065
      ) +
      roleSeam * (
        traveling * 0.27
        + mid * 0.1
        + idleWave * 0.13
        + waveFront * 0.09
      ) +
      roleHalo * (
        counter * 0.34
        + high * 0.15
        + idleWave * 0.18
        + waveFront * 0.12
      )
    );
    vec3 tangent = normalize(vec3(-radial.z, latitude * 0.08, radial.x) + vec3(0.0001));
    local += tangent * (
      roleShell * sin(latitude * 8.0 - uTime * 1.02 + aSeed * 2.0) * 0.055
      + roleSeam * sin(latitude * 11.0 + uTime * 1.36 + aSlice * 3.0) * 0.12
      + roleHalo * sin(latitude * 6.0 - uTime * 1.58 + aSeed * 4.0) * 0.16
    );

    // Ambient life: every grain keeps drifting and a slow shockwave ripple
    // sweeps through the field, so no part of the background sits frozen.
    local += radial * sin(uTime * (1.35 + aSeed * 1.9) + aSeed * TAU) * 0.075;
    float ripple = pow(
      max(0.0, sin(length(local.xy) * 0.82 - uTime * 1.85)),
      6.0
    );
    local += radial * ripple * (0.09 + uActivity * 0.07);

    // Wandering side lobe: a slow hot spot drifts around the shell with the
    // music, so density gently gathers on one side at a time (left, right,
    // top...) without ever pulling the whole ring off center.
    float wanderAngle =
      uTime * (0.16 + uBands.x * 0.1)
      + sin(uTime * 0.11 + 1.4) * 2.2
      + sin(uTime * 0.043) * 1.3;
    vec2 wanderDir = vec2(cos(wanderAngle), sin(wanderAngle));
    vec2 shellDir = normalize(local.xy + vec2(0.0001));
    float sideLobe = pow(max(0.0, dot(shellDir, wanderDir)), 2.8);
    float lobeGain = (0.1 + uActivity * 0.26)
      * (0.3 + uBands.y * 0.55 + uEnvelope * 0.5 + uBands.x * 0.3);
    local += radial * sideLobe * lobeGain;
    local += tangent * sideLobe * lobeGain * 0.35 * sin(uTime * 0.7 + aSeed * 5.0);

    // Hedgehog rim: each angular cell grows a spike whose length follows the
    // live spectrum, so the edge breaks outward like a sea urchin with the
    // melody instead of staying a smooth ring.
    float angleN = fract(angle / TAU + 0.5);
    float spikeCell = floor(angleN * 36.0);
    float cellEnergy = texture2D(
      uSpectrum,
      vec2((spikeCell + 0.5) / 36.0, 0.5)
    ).r;
    float spikeShape = pow(
      max(0.0, cos((angleN * 36.0 - spikeCell - 0.5) * TAU)),
      4.0
    );
    float hedgehog = spikeShape
      * cellEnergy
      * cellEnergy
      * (1.2 + high * 1.1 + mid * 0.42)
      * (0.18 + uActivity * 0.9);
    local += radial * hedgehog * (
      0.46 + roleShell * 0.3 + roleSeam * 0.52 + roleHalo * 0.8 + aSeed * 0.4
    );

    // Gentle swell cycle: a fully continuous profile — both crush and burst
    // are exactly zero at phase 0 and phase 1, so the phase wrap (and any
    // cycle-length change) can never teleport a particle. The inward pull is
    // a slight, slow dip; magnitude follows the melody envelope instead of
    // re-firing on every beat.
    float crushPulse =
      smoothstep(0.0, 0.16, uPulsePhase)
      * (1.0 - smoothstep(0.22, 0.52, uPulsePhase))
      * uActivity
      * uPulseStrength;
    float burstPulse = uBurstAmount;
    float particleDelay = clamp((aSeed - 0.5) * 0.16, -0.08, 0.08);
    float delayedCrush = max(
      0.0,
      crushPulse - max(0.0, particleDelay)
    );
    vec3 punctureDirection = normalize(vec3(0.82, 0.16, 0.55));
    float puncture = pow(max(0.0, dot(radial, punctureDirection)), 7.0);
    float fissure = puncture * smoothstep(
      0.16,
      0.92,
      0.5 + 0.5 * sin(latitude * 31.0 + angle * 7.0 + aSeed * 18.0)
    );
    float outerSpike = pow(
      max(
        0.0,
        sin(angle * 13.0 + latitude * 18.0 + floor(aSlice * 12.0) * 0.73)
      ),
      7.0
    );
    float splitSpike = pow(
      max(0.0, cos(angle * 21.0 - latitude * 11.0 + aSeed * 4.0)),
      10.0
    );
    float spikeField = max(outerSpike, splitSpike * 0.82);

    float crushDepth = min(0.14, delayedCrush * 0.2);
    local *= 1.0 - crushDepth;
    float crushSwirl = delayedCrush * 0.1;
    float swirlCos = cos(crushSwirl);
    float swirlSin = sin(crushSwirl);
    local.xz = mat2(swirlCos, -swirlSin, swirlSin, swirlCos) * local.xz;

    local *= 1.0 + burstPulse * (0.2 + aSeed * 0.11);
    float burstPrickle = spikeShape * burstPulse * (0.26 + aSeed * 0.3);
    local += radial * burstPrickle;
    local += radial
      * burstPulse
      * (
        0.36
        + low * 0.24
        + roleShell * spikeField * (0.62 + low * 0.55)
        + roleSeam * (0.26 + spikeField * 0.34)
        + roleHalo * (0.38 + spikeField * 0.5)
        + fissure * 0.98
      )
      * (0.62 + aSeed * 0.54);
    local += punctureDirection
      * fissure
      * burstPulse
      * (0.34 + high * 0.68 + uEnvelope * 0.3);

    vec3 worldPosition = center + local;
    vec2 pointerDelta = worldPosition.xy - uPointer;
    float pointerDistance = length(pointerDelta);
    float pointerInfluence = smoothstep(1.45, 0.08, pointerDistance);
    worldPosition.xy += normalize(pointerDelta + vec2(0.0001)) * pointerInfluence * 0.17;
    // The album cover floats at z ~1.3; grains must stay behind it so the
    // opaque sleeve occludes them instead of being overlaid.
    worldPosition.z = min(worldPosition.z, 0.72);

    vec4 viewPosition = modelViewMatrix * vec4(worldPosition, 1.0);
    gl_Position = projectionMatrix * viewPosition;

    float projectedRadius = length(vec2(local.x / 6.42, local.y / 3.86));
    float rim = smoothstep(0.62, 1.02, projectedRadius);
    float cutPattern = smoothstep(
      -0.58,
      0.46,
      sin(latitude * 20.0 + angle * 0.92 + floor(aSlice * 12.0) * 0.68)
    );
    float depthLight = smoothstep(-4.4, 0.3, worldPosition.z);
    float shimmer = 0.5 + 0.5 * sin(uTime * 2.1 + aSeed * 47.0);
    float movingLobe = pow(
      max(0.0, cos(angle * 0.92 - uTime * 0.78 + latitude * 1.8)),
      5.0
    );
    float movingRift = smoothstep(
      0.48,
      0.96,
      0.5 + 0.5 * sin(latitude * 10.0 - uTime * 1.24 + angle * 1.6)
    );

    float shellAlpha = (
      0.26
      + rim * 0.4
      + traveling * 0.88
      + movingLobe * 0.74
      + movingRift * 0.16
    ) * mix(0.58, 1.0, cutPattern);
    float seamAlpha =
      0.46
      + rim * 0.38
      + traveling * 1.18
      + counter * 0.54
      + movingLobe * 0.92;
    float haloAlpha =
      0.22
      + counter * 0.94
      + shimmer * 0.22
      + movingRift * 0.38;
    vAlpha = (
      roleShell * shellAlpha +
      roleSeam * seamAlpha +
      roleHalo * haloAlpha
    ) * mix(0.62, 1.06, depthLight)
      * (
        1.0
        + crushPulse * 0.4
        + burstPulse * (0.32 + fissure * 0.68 + spikeField * 0.3)
        + hedgehog * 1.15
      );
    vAlpha *= 0.72 + 0.28 * sin(uTime * (1.2 + aSeed * 2.4) + aSeed * 43.0);
    vAlpha *= 1.0 + sideLobe * (0.24 + uActivity * 0.34);

    float size = mix(1.08, 2.52, aSeed);
    size *= roleShell * 1.0 + roleSeam * 1.34 + roleHalo * 1.18;
    size +=
      traveling * 1.5
      + counter * 1.04
      + movingLobe * 0.7
      + movingRift * 0.28
      + high * 0.72
      + hedgehog * 1.5;
    size *= 1.0
      + crushPulse * 0.18
      + burstPulse * (0.28 + fissure * 0.7 + spikeField * 0.34);
    gl_PointSize = size * uPixelRatio * (15.4 / max(7.0, -viewPosition.z));

    vAccent = step(0.996, aSeed) * max(traveling, counter);
    vRole = aRole;
  }
`;

const particleFragmentShader = /* glsl */ `
  varying float vAlpha;
  varying float vAccent;
  varying float vRole;

  void main() {
    vec2 point = gl_PointCoord - 0.5;
    float radius = length(point);
    if (radius > 0.5) discard;
    float core = smoothstep(0.48, 0.05, radius);
    float halo = smoothstep(0.5, 0.0, radius) * 0.42;
    float shell = 1.0 - step(0.5, vRole);
    float seam = step(0.5, vRole) * (1.0 - step(1.5, vRole));
    float dust = step(1.5, vRole);
    vec3 color =
      shell * vec3(0.39, 0.69, 0.9) +
      seam * vec3(0.69, 0.88, 1.0) +
      dust * vec3(0.51, 0.78, 0.94);
    color = mix(color, vec3(0.97, 0.995, 1.0), halo + seam * 0.12);
    color = mix(color, vec3(0.96, 0.22, 0.16), vAccent);
    gl_FragColor = vec4(color, (core + halo) * vAlpha);
  }
`;

const burstVertexShader = /* glsl */ `
  attribute float aAngle;
  attribute float aEnd;
  attribute float aSeed;
  uniform float uActivity;
  uniform float uBurstAmount;
  uniform float uEnvelope;
  uniform float uPulsePhase;
  uniform float uPulseStrength;
  uniform sampler2D uSpectrum;
  uniform float uTime;
  uniform vec3 uBands;
  varying float vAlpha;
  varying float vHot;

  void main() {
    float crush =
      smoothstep(0.0, 0.16, uPulsePhase)
      * (1.0 - smoothstep(0.22, 0.52, uPulsePhase))
      * uActivity
      * uPulseStrength;
    float burst = uBurstAmount;
    float shardA = pow(
      max(0.0, sin(aAngle * 13.0 + aSeed * 5.4)),
      8.0
    );
    float shardB = pow(
      max(0.0, cos(aAngle * 21.0 - aSeed * 4.8)),
      12.0
    );
    float shard = max(shardA, shardB * 0.86);
    float idleBreath =
      sin(uTime * 0.46 + aAngle * 3.0 + aSeed * 2.0) * 0.022;
    float radiusScale =
      1.0
      - crush * 0.12
      + burst * (0.24 + shard * 0.2)
      + idleBreath;
    vec3 center = vec3(0.24, 0.38, -1.86);
    vec3 ellipse = vec3(
      cos(aAngle) * 6.46,
      sin(aAngle) * 3.9,
      sin(aAngle * 2.0 + aSeed * 3.0) * 0.24
    );
    vec3 radial = normalize(vec3(
      cos(aAngle),
      sin(aAngle) * 0.78,
      sin(aAngle * 2.0 + aSeed) * 0.12
    ));
    float cellEnergy = texture2D(
      uSpectrum,
      vec2(fract(aAngle / 6.283185307179586 + 0.5), 0.5)
    ).r;
    float spikeLength =
      0.018
      + uEnvelope * 0.052
      + cellEnergy * cellEnergy * uActivity * (0.42 + uBands.z * 0.5)
      + burst * (
        0.36
        + shard * (1.15 + uBands.x * 0.95)
        + uBands.y * 0.2
      );
    vec3 p = center + ellipse * radiusScale;
    p += radial * aEnd * spikeLength;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
    vAlpha =
      0.035
      + uEnvelope * 0.1
      + cellEnergy * cellEnergy * uActivity * 0.3
      + crush * 0.16
      + burst * (0.26 + shard * 0.5);
    vHot = max(burst * shard, cellEnergy * cellEnergy * uActivity * 0.6);
  }
`;

const burstFragmentShader = /* glsl */ `
  varying float vAlpha;
  varying float vHot;

  void main() {
    vec3 color = mix(
      vec3(0.35, 0.68, 0.88),
      vec3(0.96, 0.99, 1.0),
      vHot
    );
    gl_FragColor = vec4(color, vAlpha);
  }
`;

export default function AudioReactiveParticleField({
  active,
  audioBinsRef,
  audioEnergyRef,
  compact,
}: AudioReactiveParticleFieldProps) {
  const particleMaterialRef = useRef<ShaderMaterial>(null);
  const burstMaterialRef = useRef<ShaderMaterial>(null);
  const pulseClockRef = useRef(0);
  const spectrumUploadClockRef = useRef(0);
  const viewportWidth = useThree((state) => state.size.width);
  const count = compact ? 2800 : viewportWidth < 1180 ? 5600 : 9000;

  const spectrumTexture = useMemo(() => {
    const texture = new DataTexture(
      new Uint8Array(SPECTRUM_BIN_COUNT),
      SPECTRUM_BIN_COUNT,
      1,
      RedFormat,
    );
    texture.magFilter = LinearFilter;
    texture.minFilter = LinearFilter;
    texture.wrapS = ClampToEdgeWrapping;
    texture.needsUpdate = true;
    return texture;
  }, []);

  // The uniforms objects must stay referentially stable for the lifetime of
  // the materials: r3f re-applies a fresh inline `uniforms` literal on every
  // render, which silently detaches the GPU-side values from the ones the
  // frame loop keeps writing. Stable references keep both sides in sync.
  const particleUniforms = useMemo<ParticleUniforms>(
    () => ({
      uActivity: { value: 0 },
      uBands: { value: new Vector3() },
      uBurstAmount: { value: 0 },
      uEnvelope: { value: 0 },
      uPixelRatio: { value: 1 },
      uPointer: { value: new Vector2(20, 20) },
      uPulsePhase: { value: 1 },
      uPulseStrength: { value: 0 },
      uSpectrum: { value: spectrumTexture },
      uTime: { value: 0 },
    }),
    [spectrumTexture],
  );
  const burstUniforms = useMemo<BurstUniforms>(
    () => ({
      uActivity: { value: 0 },
      uBands: { value: new Vector3() },
      uBurstAmount: { value: 0 },
      uEnvelope: { value: 0 },
      uPulsePhase: { value: 1 },
      uPulseStrength: { value: 0 },
      uSpectrum: { value: spectrumTexture },
      uTime: { value: 0 },
    }),
    [spectrumTexture],
  );

  const geometry = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const seeds = new Float32Array(count);
    const roles = new Float32Array(count);
    const slices = new Float32Array(count);
    const center = new Vector3(0.24, 0.38, -2.04);

    const random = (index: number, salt: number) => {
      const value = Math.sin((index + 1) * (12.9898 + salt * 37.719)) * 43758.5453;
      return value - Math.floor(value);
    };

    for (let index = 0; index < count; index += 1) {
      const seed = random(index, 0.17);
      const rolePick = random(index, 1.31);
      const angle = random(index, 2.73) * Math.PI * 2;
      let x = 0;
      let y = 0;
      let z = 0;
      let role = 0;
      let slice = 0;

      if (rolePick < 0.58) {
        const latitude = random(index, 4.11) * 2 - 1;
        const section = Math.sqrt(Math.max(0.018, 1 - latitude * latitude));
        const shell = 0.96 + random(index, 5.93) * 0.105;
        const contour =
          Math.sin(angle * 5 + latitude * 9) * 0.018 +
          Math.sin(angle * 2 - latitude * 15) * 0.013;
        x = Math.cos(angle) * 6.42 * section * (shell + contour);
        y = latitude * 3.86 * shell;
        z = Math.sin(angle) * 2.75 * section * shell;
        role = 0;
        slice = (latitude + 1) * 0.5;
      } else if (rolePick < 0.9) {
        const sliceCount = 16;
        const sliceIndex = Math.floor(random(index, 4.11) * sliceCount);
        const latitude = -0.91 + (sliceIndex / (sliceCount - 1)) * 1.82;
        const section = Math.sqrt(Math.max(0.016, 1 - latitude * latitude));
        const thickness = (random(index, 5.93) - 0.5) * 0.018;
        const shell = 1.015 + (random(index, 8.47) - 0.5) * 0.055;
        const phase = sliceIndex * 0.047;
        x = Math.cos(angle + phase) * 6.55 * section * shell;
        y = (latitude + thickness) * 3.92 + Math.cos(angle * 2 + phase) * 0.045;
        z = Math.sin(angle + phase) * 2.84 * section * shell;
        role = 1;
        slice = sliceIndex / Math.max(1, sliceCount - 1);
      } else {
        const bandCount = 7;
        const band = Math.floor(random(index, 4.11) * bandCount);
        const phase = (band / bandCount) * Math.PI * 2;
        const latitude =
          Math.sin(angle * 0.68 + phase) * (0.42 + band * 0.028) +
          (random(index, 5.93) - 0.5) * 0.035;
        const section = Math.sqrt(Math.max(0.02, 1 - latitude * latitude));
        const shell = 1.07 + (random(index, 8.47) - 0.5) * 0.06;
        x = Math.cos(angle) * 6.68 * section * shell;
        y = latitude * 3.98 + Math.sin(angle * 2 + phase) * 0.08;
        z = Math.sin(angle) * 2.96 * section * shell;
        role = 2;
        slice = band / Math.max(1, bandCount - 1);
      }

      positions[index * 3] = center.x + x;
      positions[index * 3 + 1] = center.y + y;
      positions[index * 3 + 2] = center.z + z;
      seeds[index] = seed;
      roles[index] = role;
      slices[index] = slice;
    }

    const result = new BufferGeometry();
    result.setAttribute("position", new BufferAttribute(positions, 3));
    result.setAttribute("aSeed", new BufferAttribute(seeds, 1));
    result.setAttribute("aRole", new BufferAttribute(roles, 1));
    result.setAttribute("aSlice", new BufferAttribute(slices, 1));
    return result;
  }, [count]);

  const burstGeometry = useMemo(() => {
    const spokeCount = compact ? 176 : 320;
    const positions = new Float32Array(spokeCount * 2 * 3);
    const angles = new Float32Array(spokeCount * 2);
    const ends = new Float32Array(spokeCount * 2);
    const seeds = new Float32Array(spokeCount * 2);
    for (let spoke = 0; spoke < spokeCount; spoke += 1) {
      const angle = (spoke / spokeCount) * Math.PI * 2;
      const seed = (
        Math.sin((spoke + 1) * 24.754877666) * 43758.5453
      ) % 1;
      for (let end = 0; end < 2; end += 1) {
        const cursor = spoke * 2 + end;
        angles[cursor] = angle;
        ends[cursor] = end;
        seeds[cursor] = Math.abs(seed);
      }
    }
    const result = new BufferGeometry();
    result.setAttribute("position", new BufferAttribute(positions, 3));
    result.setAttribute("aAngle", new BufferAttribute(angles, 1));
    result.setAttribute("aEnd", new BufferAttribute(ends, 1));
    result.setAttribute("aSeed", new BufferAttribute(seeds, 1));
    return result;
  }, [compact]);

  useEffect(() => () => {
    geometry.dispose();
    burstGeometry.dispose();
    spectrumTexture.dispose();
  }, [burstGeometry, geometry, spectrumTexture]);

  useFrame(({ clock, gl, pointer }, delta) => {
    const frameParticleUniforms = (
      particleMaterialRef.current?.uniforms ?? particleUniforms
    ) as ParticleUniforms;
    const frameBurstUniforms = (
      burstMaterialRef.current?.uniforms ?? burstUniforms
    ) as BurstUniforms;
    const energy = audioEnergyRef.current;
    const bins = audioBinsRef.current;
    spectrumUploadClockRef.current += Math.min(delta, 0.05);
    if (
      bins.length === SPECTRUM_BIN_COUNT &&
      spectrumUploadClockRef.current >= 1 / 30
    ) {
      spectrumUploadClockRef.current %= 1 / 30;
      const data = spectrumTexture.image.data as Uint8Array;
      let changed = false;
      for (let index = 0; index < SPECTRUM_BIN_COUNT; index += 1) {
        const value = bins[index];
        const nextValue = Math.round(
          Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0)) * 255,
        );
        if (Math.abs(data[index] - nextValue) > 1) {
          data[index] = nextValue;
          changed = true;
        }
      }
      if (changed) spectrumTexture.needsUpdate = true;
    }
    // Continuous phase accumulator — never reset, never re-triggered. Beat
    // onsets and play/pause only reshape the strength envelope (melody
    // decides how wide the swell gets), so particle motion is uninterrupted
    // for the whole session and the phase wrap is invisible.
    const pulseCycle = active ? 4.8 : 9.6;
    pulseClockRef.current = (
      pulseClockRef.current + Math.min(delta, 0.05) / pulseCycle
    ) % 1;
    const pulsePhase = pulseClockRef.current;
    const pulseStrength = active
      ? Math.min(
        1.2,
        0.5 + energy.low * 0.4 + energy.mid * 0.18 + energy.average * 0.52,
      )
      : 0.3;
    const activityTarget = active ? 1 : 0.52;

    frameParticleUniforms.uTime.value = clock.elapsedTime * 0.72;
    frameParticleUniforms.uPixelRatio.value = Math.min(1.5, gl.getPixelRatio());
    frameParticleUniforms.uActivity.value += (
      activityTarget - frameParticleUniforms.uActivity.value
    ) * (1 - Math.exp(-delta * 3.8));
    frameParticleUniforms.uEnvelope.value += (
      energy.average - frameParticleUniforms.uEnvelope.value
    ) * (1 - Math.exp(-delta * 7.4));
    frameParticleUniforms.uPulsePhase.value = pulsePhase;
    frameParticleUniforms.uPulseStrength.value += (
      pulseStrength - frameParticleUniforms.uPulseStrength.value
    ) * (1 - Math.exp(-delta * 5.6));
    const burstRise = Math.min(1, Math.max(0, (pulsePhase - 0.4) / 0.26));
    const burstFall = 1 - Math.min(1, Math.max(0, (pulsePhase - 0.78) / 0.215));
    const burstProfile = (
      burstRise * burstRise * (3 - 2 * burstRise)
    ) * (
      burstFall * burstFall * (3 - 2 * burstFall)
    );
    frameParticleUniforms.uBurstAmount.value = burstProfile
      * frameParticleUniforms.uActivity.value
      * frameParticleUniforms.uPulseStrength.value;
    frameParticleUniforms.uBands.value.set(energy.low, energy.mid, energy.high);
    frameParticleUniforms.uPointer.value.set(pointer.x * 7.1, pointer.y * 4.2 + 0.38);

    frameBurstUniforms.uTime.value = clock.elapsedTime * 0.72;
    frameBurstUniforms.uActivity.value += (
      activityTarget - frameBurstUniforms.uActivity.value
    ) * (1 - Math.exp(-delta * 4.4));
    frameBurstUniforms.uEnvelope.value += (
      energy.average - frameBurstUniforms.uEnvelope.value
    ) * (1 - Math.exp(-delta * 8.2));
    frameBurstUniforms.uPulsePhase.value = pulsePhase;
    frameBurstUniforms.uPulseStrength.value += (
      pulseStrength - frameBurstUniforms.uPulseStrength.value
    ) * (1 - Math.exp(-delta * 6.2));
    frameBurstUniforms.uBurstAmount.value = burstProfile
      * frameBurstUniforms.uActivity.value
      * frameBurstUniforms.uPulseStrength.value;
    frameBurstUniforms.uBands.value.set(energy.low, energy.mid, energy.high);
  });

  return (
    <group>
      <points geometry={geometry} frustumCulled={false}>
        <shaderMaterial
          ref={particleMaterialRef}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
          uniforms={particleUniforms}
          vertexShader={particleVertexShader}
          fragmentShader={particleFragmentShader}
        />
      </points>
      <lineSegments geometry={burstGeometry} frustumCulled={false}>
        <shaderMaterial
          ref={burstMaterialRef}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
          uniforms={burstUniforms}
          vertexShader={burstVertexShader}
          fragmentShader={burstFragmentShader}
        />
      </lineSegments>
    </group>
  );
}
