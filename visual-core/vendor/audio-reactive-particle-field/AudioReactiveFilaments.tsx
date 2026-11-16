import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  ShaderMaterial,
  Vector3,
} from "three";
import type { AudioEnergy } from "./AudioReactiveParticleField";
import type { MutableRefObject } from "react";

type AudioReactiveFilamentsProps = {
  active: boolean;
  audioEnergyRef: MutableRefObject<AudioEnergy>;
  compact: boolean;
};

const vertexShader = /* glsl */ `
  attribute float aLine;
  attribute float aSeed;
  attribute float aT;
  uniform float uActivity;
  uniform float uEnvelope;
  uniform float uTime;
  uniform vec3 uBands;
  varying float vAlpha;
  varying float vAccent;

  #define PI 3.141592653589793
  #define TAU 6.283185307179586

  void main() {
    float lane = (aLine - 0.5) * 0.72;
    float envelope = pow(max(0.0, sin(aT * PI)), 0.36);
    float phase = lane * 0.86;
    float orbit = aT * TAU * 1.13 + phase;
    float detail = sin(aT * TAU * 3.4 + aSeed) * 0.1;
    float x = mix(-8.9, 8.9, aT);
    float y = 0.36
      + sin(orbit) * envelope * 1.58
      + lane * (0.32 + envelope * 0.72)
      + detail;
    float z = -2.08
      + cos(orbit) * envelope * 3.08
      + lane * 0.46;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(x, y, z, 1.0);

    float traveling = pow(max(0.0, sin(aT * TAU * 1.6 + phase)), 9.0);
    float counter = pow(max(0.0, cos(aT * TAU * 1.25 - phase)), 13.0);
    float sweepPosition = fract(uTime * 0.07);
    float sweepDistance = abs(aT - sweepPosition);
    float sweep = exp(-pow(sweepDistance / 0.06, 2.0));
    float sweepTrail = exp(-pow(max(0.0, sweepDistance - 0.06) / 0.17, 2.0));
    float sweepGain = 1.35 + uActivity * 0.9 + uEnvelope * 1.3 + uBands.x * 0.7;
    vAlpha = 0.13 + envelope * 0.3 + traveling * 0.42 + counter * 0.2
      + sweep * sweepGain
      + sweepTrail * (0.22 + uEnvelope * 0.4);
    vAccent = max(max(traveling, counter * 0.72), sweep);
  }
`;

const fragmentShader = /* glsl */ `
  varying float vAlpha;
  varying float vAccent;

  void main() {
    vec3 color = mix(
      vec3(0.45, 0.72, 0.9),
      vec3(0.985, 1.0, 1.0),
      vAccent
    );
    gl_FragColor = vec4(color, vAlpha);
  }
`;

export default function AudioReactiveFilaments({
  active,
  audioEnergyRef,
  compact,
}: AudioReactiveFilamentsProps) {
  const materialRef = useRef<ShaderMaterial>(null);
  const geometry = useMemo(() => {
    const lineCount = compact ? 8 : 14;
    const pointsPerLine = compact ? 176 : 340;
    const segmentCount = lineCount * (pointsPerLine - 1);
    const vertices = new Float32Array(segmentCount * 2 * 3);
    const lineIds = new Float32Array(segmentCount * 2);
    const seeds = new Float32Array(segmentCount * 2);
    const tValues = new Float32Array(segmentCount * 2);
    let vertexCursor = 0;
    let attributeCursor = 0;

    for (let line = 0; line < lineCount; line += 1) {
      const lineN = line / Math.max(1, lineCount - 1);
      for (let point = 0; point < pointsPerLine - 1; point += 1) {
        const start = point / (pointsPerLine - 1);
        const end = (point + 1) / (pointsPerLine - 1);
        vertices.set([start, lineN, line * 0.173, end, lineN, line * 0.173], vertexCursor);
        lineIds[attributeCursor] = lineN;
        lineIds[attributeCursor + 1] = lineN;
        seeds[attributeCursor] = line * 0.173;
        seeds[attributeCursor + 1] = line * 0.173;
        tValues[attributeCursor] = start;
        tValues[attributeCursor + 1] = end;
        vertexCursor += 6;
        attributeCursor += 2;
      }
    }

    const result = new BufferGeometry();
    result.setAttribute("position", new BufferAttribute(vertices, 3));
    result.setAttribute("aLine", new BufferAttribute(lineIds, 1));
    result.setAttribute("aSeed", new BufferAttribute(seeds, 1));
    result.setAttribute("aT", new BufferAttribute(tValues, 1));
    return result;
  }, [compact]);

  const uniforms = useMemo(() => ({
    uActivity: { value: 0 },
    uBands: { value: new Vector3() },
    uEnvelope: { value: 0 },
    uTime: { value: 0 },
  }), []);

  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame(({ clock }, delta) => {
    const material = materialRef.current;
    if (!material) return;
    const energy = audioEnergyRef.current;
    material.uniforms.uTime.value = clock.elapsedTime;
    material.uniforms.uActivity.value += (
      Number(active) - material.uniforms.uActivity.value
    ) * (1 - Math.exp(-delta * 3.8));
    material.uniforms.uEnvelope.value += (
      Math.min(1.2, energy.average + energy.transient * 0.24)
      - material.uniforms.uEnvelope.value
    ) * (1 - Math.exp(-delta * 7.2));
    material.uniforms.uBands.value.set(
      Math.min(1.2, energy.low + energy.transient * 0.16),
      Math.min(1.2, energy.mid + energy.transient * 0.12),
      Math.min(1.2, energy.high + energy.transient * 0.18),
    );
  });

  return (
    <lineSegments geometry={geometry} frustumCulled={false}>
      <shaderMaterial
        ref={materialRef}
        transparent
        depthWrite={false}
        blending={AdditiveBlending}
        uniforms={uniforms}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
      />
    </lineSegments>
  );
}
