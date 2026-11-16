# J.A.R.V.I.S — Voice + HUD for Hermes Agent

**Unfinished Phase 14 work remains paused.** See the [remaining work and handoff](docs/REMAINING_WORK.md). The separately authorized [particle core](docs/VISUAL_CORE.md) is live; the [Codex CEO demo](docs/CODEX_DEMO.md) uses cloud inference through the existing Hermes runtime while old objectives and local workers remain paused.

## Local command-center deployment

This workspace adds a text-only Linux deployment using the existing FastAPI
backend. Persistent tasks follow this path:

`HUD → JARVIS FastAPI → Paperclip → Hermes → local Ollama`

The **CEO objective** mode assigns one objective to JARVIS-CEO. The CEO records
its plan in Paperclip, performs simple work itself, or delegates a persistent
child to the existing JARVIS-01 worker. Paperclip wakes the CEO to review signed
execution evidence and consolidate the result. Future hires require human
approval. See [CEO architecture, configuration and verification](docs/CEO_ORCHESTRATION.md).

The verified CEO baseline is commit `a0f7fc7`. A subsequent local performance
profile, `jarvis-hermes-aigoat24:3b`, is selected in the existing runtimes for
the verified JAR-35/JAR-36 compatibility workflow. A clean native test measured 2.44× decode
throughput; one real worker task took 80.089 seconds versus 352.719 seconds on
the original profile. The worker comparison includes different batch/output
settings and has documented prose limitations. Fresh JAR-35 passed the actual
HUD self-execution test with verified inventory and no child tasks. JAR-36
passed real JAR-37 worker execution, native CEO wake and a visible final
report; refresh preserved both objectives and the roster stayed at two.
A five-service restart preserved the complete task history; direct chat passed
with its existing history preserved, and AIgoat was restored. See
[measurements, profile selection and rollback](docs/OLLAMA_TUNING.md).
CEO and worker have separate contexts but share the selected model's single
inference slot; calls can queue. Twenty-four CPU threads accelerate one call
and do not provide 24 concurrent agents.

For simple inventory work, the CEO's actual read-tool choice records its
self-work scope in Paperclip before the read. Delegation similarly records
the chosen assignment scope before creating a child. These records identify
runtime-derived scope separately from model-authored rationale; no separate
planning-tool call or execution evidence is fabricated.

Paperclip is the only task orchestrator and task database. Direct Hermes chat
uses separate sessions. The accepted staffing/runtime extension reuses the
Research worker and one human-approved Software employee. Research has scoped
primary-source tools; Software executes through Hermes SSH in a private,
non-root container with no host mounts or external route. Unrestricted host
access and external actions are unavailable. Other roles remain reusable
capability templates and require human approval before hiring.
No cloud LLM or voice subscription is configured for this deployment.

See [dynamic staffing](docs/DYNAMIC_AGENTS.md) and
[runtime isolation, verification and rollback](docs/RUNTIME_ISOLATION.md).
Phase 12 passed 213 regression tests and live JAR-41/JAR-42 runtime checks.
The three-framework comparative report still requires factual review; verified
execution provenance alone does not approve generated analysis. The
[monitoring HUD](docs/MONITORING.md) adds employees, native dependencies,
signed tool receipts, artifact downloads, execution logs, local resources and
authenticated approval/cancellation/retry controls. Phase 14 complete multi-role
objective acceptance remains in progress.
See the [Phase 14 verification ledger](docs/PHASE14_VERIFICATION.md) for actual
task IDs, failed attempts and remaining acceptance, and
[local inference selection](docs/INFERENCE_SELECTION.md) for the current
JARVIS-only 24-thread 7B profile, provenance and rollback. Earlier measured
Mistral results above describe the preserved baseline rather than current
Phase 14 acceptance.

With Docker/Compose installed and the existing `ollama` container running with
`ministral-3:3b`, start from this directory:

```sh
./deploy/start.sh
```

Open http://localhost:8765/hud/ and unlock with `JARVIS_HUD_TOKEN` from
`deploy/.env`. Choose **CEO objective** and submit one objective. The CEO
chooses direct work or a scoped assignment to the existing worker, and the HUD
shows Paperclip's plan, hierarchy, progress and final result. **Persistent task**
remains available to assign a task directly to **JARVIS-01**. Choose **Direct
chat** for ordinary conversation in its separate session. Task history and
results come from Paperclip and survive browser refresh and service restart.
Paperclip's operator UI is http://localhost:3100; its generated login is in
`.runtime/operator.json`.

For remote access, use the SSH tunnel in [COMMAND_CENTER.md](docs/COMMAND_CENTER.md#access-from-another-computer).

Configuration: `server/config/server.yaml`, `.runtime/hermes/config.yaml`,
`.runtime/hermes-ceo/config.yaml`,
and server-side `deploy/.env`. Secret-free templates are in `deploy/` and
`server/config/`. Generated secrets and runtime data are excluded from Git.
Fresh-install source defaults retain `jarvis-hermes:3b`; selecting an already
installed copied profile is an explicit operator action through
`deploy/select_ollama_profile.py`.

```sh
docker compose -f deploy/compose.yaml restart
docker compose -f deploy/compose.yaml logs --tail=100 -f
docker exec jarvis-hud /opt/venv/bin/python -m pytest -q -p no:cacheprovider /app/tests
```

See [deployment and live test commands](docs/COMMAND_CENTER.md) and
[phase evidence, changes and fixes](docs/PHASES.md). The upstream voice/HUD
documentation continues below; its optional capabilities are disabled in this
local MVP configuration.

---

A self-hosted, Iron-Man-style voice assistant and command center built on top of
[Hermes Agent](https://github.com/NousResearch/hermes-agent) (NousResearch's
open-source autonomous agent). Talk to a *real* agent — one with persistent
memory, terminal access, web search, file tools, and 80+ skills — through a
glowing arc-reactor HUD in any browser on your LAN, or a push-to-talk client.

**Everything runs on your own hardware.** The only cloud calls are your LLM
provider (via Hermes) and ElevenLabs for the voice. Speech-to-text is fully
local (Whisper on CPU).

## Demo

[![Watch the J.A.R.V.I.S demo](https://img.youtube.com/vi/YNI9pm3h6x8/hqdefault.jpg)](https://youtu.be/YNI9pm3h6x8)

▶ **[Watch the demo on YouTube](https://youtu.be/YNI9pm3h6x8)** — live transcription, agent tool calls, holographic media panels, and the cinematic boot, all in real time.

## What it does


Click the ring and speak. Your words transcribe **live on screen** while you
talk. The transcript goes to Hermes Agent, which actually *does things* — reads
and writes files, runs commands, searches the web, remembers you across
sessions — and the reply streams back as speech, sentence by sentence, while
the rest is still being generated. Typical round trip: 3–5 seconds.

The HUD around the ring is a real control center:

- **Live agent activity** — watch tool calls happen with command previews
- **STOP button** — halt a runaway agent turn mid-tool-call (Esc works too)
- **Approval cards** — dangerous commands pause for your ALLOW/DENY
- **Interrupt-aware barge-in** — cut it off mid-sentence; it knows exactly
  what you heard and what you didn't
- **Embedded dashboards** — Hermes' kanban board and session browser pop up
  in animated viewers, fully interactive
- **Holographic media panels** — say *"show me a video of how arc reactors
  work, on screen"* and a panel swoops in from Z-depth, traces its frame,
  materializes through a scanline, and plays the video. The agent drives it
  through a bundled Hermes plugin (`hud_display`); panels can fly into
  left/right thirds, and "clear the screen" sweeps them away
- **Usage tracking** — tokens/day, turns, ElevenLabs quota bar
- **Machines panel** — live CPU/GPU stats for the host and remote workers
- **Cinematic boot** — press `B`: panels flicker in, ring spins up,
  "Systems online. Good morning."
- **Privacy filter** — secret-shaped strings are redacted before any text
  reaches cloud TTS
- **Optional GPU ears** — point it at any NVIDIA machine on your LAN running
  the included sidecar and transcription jumps to `large-v3-turbo` at ~0.2 s,
  with automatic fallback to local Whisper when that machine is off
- **Mobile-ready** — responsive layout + Add to Home Screen = full-screen
  Jarvis app on your phone

## Architecture

```
 Browser HUD (any LAN device)          Host machine (tested on macOS / Apple Silicon)
 ── https/wss :443 ──────────┐   ┌──────────────────────────────────────┐
   mic · speaker · panels    ├──►│ voice pipeline server (this repo)    │
                             │   │  STT: faster-whisper (local, free)   │   ┌─────────────────┐
 Push-to-talk client         │   │  TTS: ElevenLabs Flash (streaming)   ├──►│ Hermes Agent     │
 ── ws :8765 ────────────────┘   │  HUD + auth + dashboard TLS proxy    │   │  API :8642 (lo)  │
                                 └──────────────────────────────────────┘   │  memory · tools  │
                                                                             │  skills · cron   │
                                                                             └─────────────────┘
```

One brain, many faces: voice and typed chat share a single persistent Hermes
session, so each knows what you said to the other — and memory survives every
restart.

## Requirements

- A machine for the server (tested: Mac mini, Apple Silicon). Linux should
  work with minor changes (launchd → systemd).
- [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) installed and
  configured with an LLM provider
- Python 3.11+
- An [ElevenLabs](https://elevenlabs.io) API key (free tier works; ~0.5
  credits/char on Flash)
- Any modern browser on the LAN

## Install

Full walkthrough in [docs/SETUP.md](docs/SETUP.md). Short version:

```bash
# 1. Enable the Hermes Agent API server
cat >> ~/.hermes/.env <<EOF
API_SERVER_ENABLED=true
API_SERVER_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
JARVIS_HUD_TOKEN=$(python3 -c 'import secrets;print("jarvis-"+secrets.token_hex(3))')
ELEVENLABS_API_KEY=your-key-here
EOF
hermes gateway   # or set up its LaunchAgent / service

# 2. This repo
git clone https://github.com/YOURNAME/jarvis-hermes-hud
cd jarvis-hermes-hud/server
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn requests pyyaml numpy anthropic \
    RealtimeSTT faster-whisper silero-vad websockets psutil
cp config/server.example.yaml config/server.yaml   # edit: your ElevenLabs voice_id etc.
scripts/make-certs.sh                              # self-signed TLS (browser mic needs it)
scripts/make-boot-audio.sh YourName                # one-time boot greeting synthesis

# 3. Run
.venv/bin/python server.py
# open https://YOUR_HOST/hud/ → accept cert → enter your JARVIS_HUD_TOKEN → talk
```

For auto-start on boot, see [launchd/](launchd/) (macOS) — the plists document
two non-obvious macOS traps (external-drive TCC and log paths) that cost us an
evening.

## Usage

| Action | How |
|---|---|
| Talk | Click the ring (or Space) · speak · click again to send |
| Stop the agent | red ■ STOP button or Esc |
| Barge in | click the ring while it's speaking |
| Typed chat | input bar at the bottom (same conversation as voice) |
| Cinematic boot | press `B` |
| Kanban / dashboards | VIEWS panel → animated pop-up viewers |
| Phone | open the HUD → Add to Home Screen |

## Repo layout

```
server/          FastAPI voice pipeline + HUD host (the core of this project)
server/hud/      single-file HUD (vanilla JS, no build step)
server/scripts/  start/stop/health/smoke + cert & boot-audio generators
client/          optional Windows/Linux push-to-talk Python client (wake word capable)
worker/          optional GPU sidecars: big-model STT server + stats agent for the Machines panel
hermes-plugin/   Hermes tool plugin: lets the agent summon/dismiss HUD media panels
launchd/         macOS auto-start templates with hard-won TCC + FD-limit notes
docs/            SETUP, ARCHITECTURE (protocols/endpoints), TROUBLESHOOTING
```

## Security model

- The Hermes API key never reaches the browser: the HUD talks through a
  strict allowlist proxy on the voice server.
- All HUD endpoints + dashboard proxy + browser WebSockets are gated by a
  token (cookie, entered once per device).
- Hermes' API binds to loopback only; the dashboard binds to loopback only.
- Secret-shaped strings are redacted before text leaves for cloud TTS.
- LAN-only by design — do not port-forward this to the internet.

## Credits & license

Built on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous
Research. HUD aesthetics inspired by
[jarvis-dashboard](https://github.com/AndrewKochulab/jarvis-dashboard).
STT by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) /
[RealtimeSTT](https://github.com/KoljaB/RealtimeSTT). Voice by
[ElevenLabs](https://elevenlabs.io).

MIT — see [LICENSE](LICENSE). Use it, fork it, build your own Jarvis.

## Local command-center deployment

See [COMMAND_CENTER.md](docs/COMMAND_CENTER.md) for the Linux deployment, phase evidence, and integration work.
