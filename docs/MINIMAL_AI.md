# Minimal JARVIS AI interface

The default HUD opens on the floating AI core and direct chat. Operational
dashboards stay out of the normal conversation view. Genuine tool activity and
errors can open contextual popup windows as they occur; no findings, progress,
or agent thoughts are simulated. Published responses remain in the chat.

The operator interface is still available at `/hud/?layout=operations`.
That explicit view contains the existing task history, approvals, monitoring,
and CSI workspace. It is separate from the default conversation screen.

## Codex direct chat

Direct chat now targets the existing dedicated Hermes profile
`.runtime/hermes`, configured with provider `openai-codex` and model
`gpt-6.1-sol`. Hermes retains its scoped tools and conversation history. This
uses Codex inference through Hermes; it does not inherit the memory or private
context of this interactive Codex conversation.

The FastAPI request explicitly supplies the configured provider, model, and
`require_model_lock: true`. This replaces stale session model selections while
preserving the session's messages. After execution, the backend validates the
actual provider and model reported by Hermes' final runtime metadata before
accepting the reply. A configuration label alone is not execution evidence.

There is **no local inference fallback**. The direct profile clears both
`fallback_providers` and legacy `fallback_model`. Reading installed Ollama model
metadata with an authorized tool does not mean Ollama generated the answer.
Provider failure produces a readable error instead of silently selecting a
local model or displaying a raw runtime envelope.

The CEO keeps its separate Hermes profile, API identity, and Paperclip
issue-scoped sessions. Ordinary chat does not create or assign a Paperclip
objective. Existing paused workers and stopped orchestration work remain
paused.

## Configuration and restart

Run commands from `/home/kali/jarvis-command-center/jarvis_ai` on the server.

`deploy/configure_codex_chat.py --apply` has already been run for this setup.
The helper defaults to a dry run. It backs up the private direct-chat profile
and session map before changing its model configuration. It imports the
existing **server-side** Codex CLI OAuth login through Hermes' credential-store
helper; no workstation credentials are copied and no secrets reach the
frontend or Git.

```sh
# Inspect the intended configuration without changing it.
python3 deploy/configure_codex_chat.py

# Restart only the HUD and direct-chat runtime, retaining all relevant overlays.
docker compose --env-file deploy/.env --env-file deploy/codex-demo.env \
  -f deploy/compose.yaml -f deploy/compose.codex-demo.yaml \
  -f deploy/compose.codex-chat.yaml up -d --no-deps jarvis hermes
```

Keep `compose.codex-chat.yaml` in the startup command. It supplies the backend's
explicit Codex selection, gives the direct runtime provider connectivity, and
removes unnecessary Paperclip execution credentials from that chat container.
It does not reconfigure the CEO profile or alter Ollama models.

If OAuth access expires or is revoked, a valid fresh login is required on the
server. Repair the server-side login and profile credentials; never substitute
local inference silently. The original login file remains sensitive material.

## Verification

```sh
python3 deploy/check_minimal_codex.py
```

This check exercises actual authenticated HUD chat and a real tool-triggered
popup without creating a Paperclip objective. The real browser check passed on
November 16, 2026: three confirmed Codex replies took 2.612, 2.636, and 10.707
seconds. The third performed a real `local_ollama_models` metadata read and
opened its operation panel through the authenticated backend socket. Ordinary
replies opened no panels; desktop and mobile checks found no browser errors.
The existing task IDs were unchanged and no Paperclip task was created.

Evidence: `docs/evidence/minimal-codex-chat.json`,
`docs/evidence/minimal-codex-runtime.json`, and `minimal-ai-*.png` screenshots.
The tool-bearing Hermes run is `run_4ced4d5bede14f56a0b6c020db4ffebd`.
The original direct session `api_1794464162_4c830cc5` remains in use; switching
models did not recreate its history. Private pre-switch backups are under
`.runtime/backups/codex-chat/20261116T111025Z/`.

The exact selected source passes 338 backend tests; the frontend passes five
tests. The live service rejects unauthenticated sockets even without an Origin
header. Native clients must supply `X-Jarvis-Token`; browsers use the existing
authenticated cookie and origin checks. Canonical task snapshots clear stale
connection warnings after a successful refresh.

## UI rollback

The previous HUD image is retained as
`jarvis-command-center:hud-before-minimal-ai`. To restore that UI:

```sh
docker tag jarvis-command-center:hud-before-minimal-ai jarvis-command-center:hud
docker compose --env-file deploy/.env --env-file deploy/codex-demo.env \
  -f deploy/compose.yaml -f deploy/compose.codex-demo.yaml \
  -f deploy/compose.codex-chat.yaml up -d --no-deps jarvis
```

This rolls back the screen while **keeping the Codex chat overlay**. Do not
remove the overlay as part of a visual rollback: that could restore an unwanted
local route. Native task history, prior chat messages, and stored artifacts are
independent of the presentation image.
