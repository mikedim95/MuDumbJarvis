# JARVIS command center

Workspace: /home/kali/jarvis-command-center/jarvis_ai

Phase 1 topology: browser → existing JARVIS FastAPI backend (127.0.0.1:8765).
Hermes v0.23.1 runs as an isolated gateway using the existing local Ollama server.
Paperclip 2026.1106.0 is the persistent task orchestrator at http://localhost:3100.
See PHASES.md for verified acceptance evidence and changes.

## Install and start

1. Install Docker with Docker Compose.
2. Keep the existing `ollama` container running, with `ministral-3:3b` installed.
3. Run `./deploy/start.sh`. It creates missing configuration/secrets, builds,
   attaches Ollama to the private network, creates the separate model alias if
   absent, starts services and bootstraps Paperclip once.
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

## Paperclip

The container installs the official pinned npm release; upstream internals are
unchanged. Its embedded PostgreSQL database, backups and logs persist under
`.runtime/paperclip`. Operator login credentials are generated once in
`.runtime/operator.json` (mode 0600). The backend's permanent board API key stays
in `deploy/.env`; the agent receives only its own reporting key.

After first startup, bootstrap via the supported REST API:

```sh
docker run --rm --user 1000:1000 --network jarvis-command-center_default \
  -e PAPERCLIP_BOOTSTRAP_URL=http://paperclip:3100 \
  -v "$PWD:/workspace" --entrypoint /opt/venv/bin/python \
  jarvis-command-center:hud /workspace/deploy/bootstrap_paperclip.py
docker compose -f deploy/compose.yaml up -d
```

Run these commands from the repository root. Bootstrap creates JARVIS, General
Operations and JARVIS-01, and stores the Hermes API key through Paperclip's
encrypted secret management. `sessionKeyStrategy=issue` isolates tasks.
The built-in `hermes_gateway` adapter uses TLS through a private nginx proxy;
Paperclip trusts only the generated local certificate. No TLS verification
bypass is configured. The private certificate key is excluded from Git.

A supported Hermes lifecycle plugin checks out only its assigned issue and
atomically records its real reply and final disposition using Paperclip REST.
Failed/interrupted turns are blocked, never marked done. Ordinary chat cannot
enter that reporting path. Paperclip alone owns task state; the plugin stores
only ephemeral per-turn correlation and ordinary execution logs.

Live Phase 3 test (creates/replays one read-only, idempotent issue):

```sh
docker run --rm --user 1000:1000 --env-file deploy/.env \
  --network jarvis-command-center_default -v "$PWD:/workspace" \
  --entrypoint /opt/venv/bin/python jarvis-command-center:hud \
  /workspace/tests/live_phase3.py
```

## HUD tasks and API

Choose **Persistent task** next to the existing typed input. The agent list is
retrieved dynamically from Paperclip. Submitted tasks are assigned to the
selected agent (JARVIS-01 by default). Select a history entry to see its exact
Paperclip UUID, status, run errors and result comments. Active tasks refresh
every three seconds. Browser refresh/reconnect reloads authoritative history.
An uncertain submission retains its nonce and text so a retry uses the same
Paperclip idempotency key. Distinct intentional submissions get new keys.

**Direct chat** continues to use JARVIS's original Hermes Sessions integration,
with no Paperclip task creation or task session reuse. Both modes share one
bounded local runtime, so an occupied runtime may report a busy error.

Task endpoints require the existing HUD token/cookie, even if authentication
has accidentally been unconfigured. Cross-origin task creation is rejected.
API keys are never returned to the browser. No second task store was added.

| Endpoint | Behavior |
| --- | --- |
| POST /api/tasks | JSON input, request_id (UUID), optional agent_id; creates assigned task |
| GET /api/tasks | General Operations history from Paperclip |
| GET /api/tasks/{id} | Canonical issue state, comments and execution errors |
| GET /api/agents | Agent identity/status/capabilities, with no adapter secrets |

Read requests have a bounded retry; uncertain POSTs are retried only with the
original submission nonce. Upstream errors are shown without inventing a done
state. A failed execution and the issue's actual status are displayed separately.

API-only live test (does **not** establish browser acceptance):

```sh
docker run --rm --user 1000:1000 --env-file deploy/.env \
  --network jarvis-command-center_default -v "$PWD:/workspace" \
  --entrypoint /opt/venv/bin/python jarvis-command-center:hud \
  /workspace/tests/live_task_api.py
```

## Adding agents later

Register additional supported adapters/agents in Paperclip and grant their
runtime only the tools it needs. The HUD discovers them through GET /api/agents;
it does not hardcode model names, agent IDs or adapter types. New Hermes agents
need their own API/reporting credentials and runtime/session configuration.
OpenCode can use Paperclip's supported adapter; a future PentAGI adapter can
follow the same task/result contract. No PentAGI integration is installed now.
Filesystem modifications or external actions need explicit operator permission
and a deliberately provisioned, restricted tool/approval path first.
