# Verified implementation phases

## Phase 1 — complete (2026-11-11)

Source: eadmin2/jarvis_ai at 88998de, cloned with Git.
Read README.md, docs/SETUP.md and docs/ARCHITECTURE.md; inspected the HUD,
server/server.py and its persistent Hermes session integration.

Changes: optional/lazy voice imports; text-only WebSockets; graceful disconnect
handling; authenticated /api/health; Linux Docker service with /opt/venv Python
virtual environment, loopback publication, persistent logs, restricted container,
local config template, generated server-side credentials, and phase tests.
Voice behavior remains enabled by default in the upstream configuration.
The local config disables voice and cloud fallback.

Evidence:
- User confirmed the JARVIS HUD renders at http://localhost:8765/hud/.
- Live HUD HTTP 200; authenticated health HTTP 200 with voice_enabled=false.
- Unauthenticated health HTTP 401.
- pytest tests/test_phase1.py: 3 passed. Browser WebSocket authentication,
  untrusted Origin rejection, text-only startup and proxy allowlist checked.
- Docker dependency installation is isolated in /opt/venv.

Blockers/fixes: no connected browser automation surface; the user performed
visual confirmation. Test found an upstream WebSocket disconnect loop; fixed
by terminating on the disconnect event. Existing PentAGI was not modified.

## Phase 2 — complete (2026-11-11)

Hermes v0.23.1 official Docker image pinned to amd64 manifest SHA
1a355ebc8981a4b72a28f4e47e347ba4f0f172b43dc876e5768d175a07c67b22.
Source inspection pinned to tag v0.23.1 (3b421578).
No preexisting Hermes installation was found. Existing Ollama models/configuration
were inspected; a new jarvis-hermes:3b alias uses existing Ministral weights
with a separate 65,536-token context. The original models were not replaced.

Hermes uses http://ollama-models:11434/v1 on an internal Docker network,
with one new network attachment on the existing Ollama container. Its API is
key-protected; API_SERVER_KEY was generated using secrets.token_urlsafe(40).
It has no host files or Docker socket mounted. Only the jarvis_readonly toolset
is enabled on the API; shell, write, external web and delegation tools are off.
The plugin is a supported Hermes extension; Hermes core was not modified.

Evidence: authenticated health 200 (version 0.23.1); unauthenticated models 401;
active toolset discovery contains local_ollama_models only. A real Hermes
Chat Completions turn returned HTTP 200 / finish_reason=stop with retrieved
model names and sizes. Audit: docs/evidence/phase2-tool.json. The Ollama
OpenAI-compatible endpoint also returned READY, and ollama ps reported 65,536
context. No cloud LLM is configured; the agent network blocks external routing.

Observed fix: use an explicit 64K model alias, since Hermes rejects small context
windows. Initial cold load was slow on CPU; subsequent cached tool turns ran.

Direct JARVIS chat verified via /api/chat: HTTP 200, text READY, run ID
run_77d0da14b6e24296b894393f0f4352c8. The direct conversation session is stored
in server/logs/hermes_sessions.json and is separate from future Paperclip tasks.

## Phase 3 — verified (2026-11-11)

Paperclip stable release 2026.1106.0 (source d69631b), installed from its
published npm package in a non-root Linux container. Embedded PostgreSQL is
persistent under .runtime/paperclip; no separate database service was added.
Paperclip internals remain unchanged. Created authenticated operator, JARVIS
company, General Operations project, and JARVIS-01 using documented REST routes.
Hermes credentials use an encrypted Paperclip secret_ref, not adapter plaintext.
The agent receives only its own API key; the HUD backend holds the board key.

Changes: deploy/Dockerfile.paperclip, compose.yaml, init.py, .env.example,
bootstrap_paperclip.py, hermes-tls.conf, supported Hermes reporting plugin,
reporting tests, live_phase3.py, COMMAND_CENTER.md and evidence snapshots.
Generated credentials, certificates, databases and private keys are Git-ignored.

Evidence:
- Paperclip health 200, authenticated/private deployment, upstream build commit
  d69631b01b9c658f80bf8bed389863dce82643e1.
- JARVIS-01 lifecycle ready after authenticated TLS gateway health check.
- Issue JAR-1 / 86e0f800-6f54-44fb-a799-99982ef783dc moved from todo to
  in_progress to done; final comment authored by JARVIS-01 records actual
  jarvis-hermes:3b (2.75 GiB) and pentagi-basilisk:7b (4.36 GiB).
- Paperclip execution 79ff6a76-c812-47e0-925d-de504188f65f dispatched Hermes
  run_011b6c278c0b417d99e2f2b34e9a76ce into an issue-scoped session.
- Hermes log verifies model jarvis-hermes:3b / custom provider / local Ollama
  endpoint and actual local_ollama_models execution for this exact issue.
- Evidence: docs/evidence/phase3-task.json and phase3-runtime.json.
- 8 automated tests pass (startup/auth/WebSocket plus reporting boundaries,
  assignment checks, failure disposition and callbacks across worker threads).

Blockers/fixes: standard Docker image includes several large toolchains; used
supported pinned npm distribution instead. npm requires explicit embedded
PostgreSQL symlink hydration. Paperclip's lifecycle verifier rejects a warning
from non-loopback plaintext Hermes; added a private TLS proxy with a generated
trusted certificate, with no verification bypass. Hermes hooks can execute on
different workers; correlation uses session + turn identity in ephemeral memory.
The first CPU prompt took 248 seconds; subsequent tool-selection calls used
cached context and took about 20 seconds each. Existing PentAGI was untouched.

Restart verification: recreated Hermes, JARVIS and Paperclip services; the live
test replayed the identical idempotency key, recovered the same JAR-1 UUID and
its final comment, and retrieved a persisted succeeded Paperclip run.
