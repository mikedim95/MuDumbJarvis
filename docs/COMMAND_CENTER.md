# JARVIS command center

Workspace: /home/kali/jarvis-command-center/jarvis_ai

Phase 1 topology: browser → existing JARVIS FastAPI backend (127.0.0.1:8765).
Hermes, Paperclip and local Ollama will be connected in the following phases.
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
