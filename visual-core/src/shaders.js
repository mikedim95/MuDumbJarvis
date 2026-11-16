/* Adapted from AudioReactiveParticleField.tsx, zhisan (MIT), commit a1fba5dc.
 * Retains shell/seam/halo roles, spectral texture, traveling highlights,
 * smoothed breathing and soft additive point sprites; geometry is now a torus.
 */
export const vertex = /* glsl */ `
attribute float aSeed;
attribute float aRole;
attribute float aSlice;
uniform float uTime;
uniform float uPixelRatio;
uniform float uActivity;
uniform float uEnvelope;
uniform float uTransient;
uniform sampler2D uSpectrum;
uniform vec2 uPointer;
uniform vec3 uBands;
varying float vAlpha;
varying float vRole;
varying float vAccent;
#define TAU 6.283185307179586
void main() {
  vec3 local = position;
  float shell = 1.0 - step(0.5, aRole);
  float seam = step(0.5, aRole) * (1.0 - step(1.5, aRole));
  float halo = step(1.5, aRole);
  float angle = atan(local.y, local.x);
  float turn = uTime * (0.10 + uActivity * 0.12) * (1.0 - seam * 1.7 + halo * 0.55);
  local.xy = mat2(cos(turn), -sin(turn), sin(turn), cos(turn)) * local.xy;
  vec3 radial = normalize(vec3(local.xy, 0.0001));
  vec3 tangent = vec3(-radial.y, radial.x, 0.0);
  float traveling = pow(max(0.0, sin(angle * 2.4 - uTime * 1.18 + aSlice * 4.2)), 10.0);
  float counter = pow(max(0.0, cos(angle * 1.35 + uTime * 0.86 - aSlice * 11.0)), 14.0);
  float breath = sin(uTime * 0.82) * 0.012 + sin(uTime * 0.33 + 1.2) * 0.009;
  breath += uEnvelope * 0.045 + uBands.x * 0.035;
  local *= 1.0 + breath;
  float wave = sin(angle * 5.0 - uTime * 1.34 + aSlice * 5.4 + aSeed * 1.7);
  local += radial * wave * (0.012 + seam * 0.015 + uBands.y * 0.085);
  local += tangent * sin(aSlice * 11.0 + uTime * 1.36 + aSeed * 3.0) * 0.024;
  float energy = texture2D(uSpectrum, vec2(fract(angle / TAU + 0.5), 0.5)).r;
  float spike = energy * energy * (0.08 + halo * 0.22) + uTransient * (0.025 + halo * 0.08);
  local += radial * spike;
  local.z += sin(angle * 3.0 + uTime * 0.5 + aSeed * TAU) * 0.045;
  vec2 pointerDelta = local.xy - uPointer;
  float proximity = 1.0 - smoothstep(0.1, 1.05, length(pointerDelta));
  local.xy += normalize(pointerDelta + vec2(0.0001)) * proximity * 0.13;
  vec4 viewPosition = modelViewMatrix * vec4(local, 1.0);
  gl_Position = projectionMatrix * viewPosition;
  float shimmer = 0.5 + 0.5 * sin(uTime * 1.7 + aSeed * 47.0);
  float depthLight = smoothstep(-0.35, 0.35, local.z);
  vAlpha = (shell * 0.36 + seam * 0.58 + halo * 0.26 + traveling * 0.38 + counter * 0.18);
  vAlpha *= (0.60 + shimmer * 0.40) * (0.7 + depthLight * 0.3) * (1.0 + energy * 0.5);
  float size = mix(1.05, 2.45, aSeed) + seam * 0.55 + traveling * 0.65 + energy * 1.4;
  gl_PointSize = size * uPixelRatio * (7.7 / max(5.0, -viewPosition.z));
  vRole = aRole;
  vAccent = traveling * seam * 0.45 + energy * 0.25;
}
`;

// Upstream's soft point sprite with JARVIS's cyan/teal/state palette.
export const fragment = /* glsl */ `
uniform vec3 uColor;
varying float vAlpha;
varying float vRole;
varying float vAccent;
void main() {
  vec2 point = gl_PointCoord - 0.5;
  float radius = length(point);
  if (radius > 0.5) discard;
  float core = 1.0 - smoothstep(0.05, 0.48, radius);
  float halo = (1.0 - smoothstep(0.0, 0.5, radius)) * 0.42;
  float seam = step(0.5, vRole) * (1.0 - step(1.5, vRole));
  vec3 color = mix(uColor, vec3(0.80, 0.98, 1.0), seam * 0.32 + vAccent);
  gl_FragColor = vec4(color, (core + halo) * vAlpha);
}
`;

// Upstream's traveling filament highlight wrapped into circular orbital lanes.
export const filamentVertex = /* glsl */ `
attribute float aLine;
attribute float aT;
uniform float uTime;
uniform float uActivity;
uniform float uEnvelope;
varying float vAlpha;
void main() {
  float lane = aLine - 0.5;
  float orbit = aT * 6.28318530718 + lane * 0.3;
  float radius = 2.06 + lane * 0.36 + sin(orbit * 3.0 + lane * 8.0) * 0.018;
  radius *= 1.0 + sin(uTime * 0.82) * 0.012 + uEnvelope * 0.06;
  vec3 p = vec3(cos(orbit) * radius, sin(orbit) * radius, sin(orbit * 2.0 + lane * 12.0) * 0.12);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  float sweepPosition = fract(uTime * 0.045 + aLine * 0.21);
  float d = abs(aT - sweepPosition);
  d = min(d, 1.0 - d);
  float sweep = exp(-pow(d / 0.065, 2.0));
  vAlpha = 0.045 + sweep * (0.3 + uActivity * 0.12 + uEnvelope * 0.3);
}
`;
export const filamentFragment = /* glsl */ `
uniform vec3 uColor;
varying float vAlpha;
void main() { gl_FragColor = vec4(uColor, vAlpha); }
`;
