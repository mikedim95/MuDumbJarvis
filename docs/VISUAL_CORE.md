# Floating particle core

The first arrangement is one floating, slowly rotating particle circle. It
replaces the concentric Canvas 2D reactor in the existing HUD. The page layout,
command input, task history, authentication and original voice controls remain.

This adapts [audio-reactive-particle-field](https://github.com/zhisandesu/audio-reactive-particle-field),
pinned at `a1fba5dc0687ec8145acd83fe316103272863356` (MIT, copyright 2026
zhisan). The upstream source and license are retained under
`visual-core/vendor/audio-reactive-particle-field/`. Its shell/seam/halo roles,
spectral texture, traveling highlights, soft additive particle sprites,
filament highlights and spectrum analysis are adapted to circular geometry
and JARVIS state. The renderer uses the same Three.js version, without adding
React to the HUD or replacing FastAPI. Both upstream and Three.js licenses are
served at `server/hud/core/LICENSE.txt`.

## Behavior

- Cyan ambient motion in standby, teal listening, amber thinking/tool activity,
  cyan speech and a red blocked/error state. Activity comes from the existing
  direct-chat state and read-only Paperclip task snapshots.
- Slow three-dimensional rotation, gentle vertical floating, soft breathing
  and pointer repulsion. The center remains readable.
- Real audio analysis uses silent taps on the existing user-authorized input
  and output nodes, with 48 spectrum bins. The renderer never requests a
  microphone, creates/resumes an audio context, uploads audio or starts audio
  automatically. Idle breathing is animation, not fabricated audio data.
- 6,400 particles on desktop, 3,200 for initially compact viewports, a pixel
  ratio ceiling of 1.5 and a 30-frame-per-second render ceiling. Hidden tabs
  pause animation. Reduced-motion preference disables continuous movement.
- Without WebGL2, a smaller animated particle circle uses Canvas 2D. Task and
  chat controls do not depend on WebGL.

The `arrangements` registry in `visual-core/src/field.js` contains only `ring`.
Geometry creation, spectrum analysis and HUD state input are separate modules
so future shapes/combinations can reuse the same state/audio interfaces.
Additional arrangements and draggable UI windows are not implemented here.

## Build and verify

```sh
cd visual-core
npm ci --no-audit --no-fund
npm run build
```

This produces the self-contained `server/hud/core/visual-core.js` and license
file. No Node service or CDN is needed at runtime. The regular JARVIS Docker
build includes these checked-in assets.

`tests/visual_core_e2e.cjs` exercises the authenticated HUD, live read-only
Paperclip history/artifacts, moving frames, real browser audio analysis from a
silent test oscillator, direct-state transitions, reduced motion, mobile
layout and the no-WebGL fallback. Controlled browser signals are explicitly
test fixtures, not represented as agent execution. It makes no task/agent/
approval/chat mutations and requests no LLM inference.

From the deployment root, use `python3 deploy/check_visual_core.py` for the
deployed HUD, or add `--preview` or `--fallback` as needed. The helper uses the
existing `jarvis-command-center:browser-test` image and passes only the HUD
unlock token, not the entire deployment env file. `--preview` serves only the changed frontend files inside that browser
while keeping authenticated APIs live; no flag tests the deployed HUD;
`--fallback` disables WebGL for the fallback case. Screenshots and results
are stored under `docs/evidence/visual-core-*`.

## Frontend-only deployment and rollback

When other backend work remains uncommitted, preserve the current HUD image
and overlay only frontend assets:

```sh
docker tag jarvis-command-center:hud jarvis-command-center:hud-before-particle-core
docker build -f deploy/Dockerfile.hud-visual \
  --build-arg HUD_BASE=jarvis-command-center:hud-before-particle-core \
  -t jarvis-command-center:hud-particle-core .
docker tag jarvis-command-center:hud-particle-core jarvis-command-center:hud
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --no-deps jarvis
```

Verify the browser and existing APIs after the HUD restart. To roll back, tag
`jarvis-command-center:hud-before-particle-core` as `jarvis-command-center:hud`
and run the same `up -d --no-deps jarvis` command. Preserve the rollback tag;
do not overwrite it when repeating a deployment. This updates only the HUD
service and does not resume paused employees or the provisioning timer.
