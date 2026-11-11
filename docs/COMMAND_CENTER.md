# JARVIS command center

Workspace: /home/kali/jarvis-command-center/jarvis_ai

Phase 1 topology: browser → existing JARVIS FastAPI backend (127.0.0.1:8765).
Hermes v0.23.1 now runs as an isolated gateway using the existing local Ollama server. Paperclip is the next phase.
See PHASES.md for verified acceptance evidence and changes.

## Install and start

1. Install Docker with Docker Compose.
2. Run `python3 deploy/init.py` to create local configuration and secrets.
3. Run `docker compose -f deploy/compose.yaml up --build -d`.
4. Open http://localhost:8765/hud/ and enter JARVIS_HUD_TOKEN from deploy/.env.
   This is a local secret; do not commit or share it.

Restart: `docker compose -f deploy/compose.yaml restart`
Logs: `docker compose -f deploy/compose.yaml logs --tail=100 -f`
Tests: `docker exec jarvis-hud /opt/venv/bin/python -m pytest -q -p no:cacheprovider /app/tests`

Python dependencies are isolated in /opt/venv inside the container. Voice is
optional: the local template disables it; the original example and voice code
remain available. No cloud keys or fallback are configured. State is under
server/logs; secrets are server-side in deploy/.env. The published port is local
only; API and browser WebSockets retain HUD authentication and Origin checks.

## Hermes / Ollama

`deploy/start.sh` starts services and connects the existing Ollama container to
the private agent network without changing its existing networks or settings.
The Hermes API uses http://hermes:8642 internally; the browser never receives
its API_SERVER_KEY. Inspect it through the JARVIS allowlist proxy or inside the
service network. Active API tools are restricted to local_ollama_models.

A separate jarvis-hermes:3b alias of the installed ministral-3:3b weights sets
num_ctx=65536 and four CPU threads. Existing model definitions are retained.
The alias definition is deploy/Modelfile.hermes. Initial CPU loads can be slow.
Hermes state is isolated under .runtime/hermes; plugin source is read-only.
No host workspace or Docker socket is mounted into the agent container.
