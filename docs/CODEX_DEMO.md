# Codex-powered CEO demo

The user explicitly requested Codex in place of local inference for a demo.
The existing CEO uses `gpt-6.1-sol`, with Hermes' normal `openai-codex` provider
and its existing server-side Codex login. This is a separate model session with
Paperclip context, rather than a copy of the interactive Codex conversation.

`HUD → authenticated FastAPI → Paperclip CEO → hermes_gateway → Hermes tools → Codex cloud inference`

Paperclip remains the only task database and scheduler. Hermes retains tool
execution and issue-scoped sessions. The CEO can read company/task context,
record a self plan, query the read-only local model inventory, and publish
internal text artifacts. A signed, employee-bound version-2 policy plus a
pre-tool guard rejects hiring, delegation, approval requests, and host/external
actions during this demo. No Codex shell/app-server tools are enabled.

Research and Software remain paused; no new employees are created. The operator
timer remains stopped. Native manual pause holds protect JAR-29, JAR-32, and
JAR-44 and their descendants. Their existing failures and reconciliation holds
are not repaired, retried, or counted as successful Phase 14 work.

Local Ollama's 24-thread, single-slot configuration, models, direct Hermes chat,
AIGoat, and PentAGI are preserved. The demo's inventory query reads Ollama
metadata; its LLM generation goes to Codex. The HUD labels the CEO provider
separately from the local resource panel. Cloud response time does not measure
local inference performance.

## Configuration and startup

Run commands from `/home/kali/jarvis-command-center/jarvis_ai` on the server.
The preparation helper defaults to a dry run and leaves all employees paused:

```sh
python3 deploy/configure_codex_demo.py
python3 deploy/configure_codex_demo.py --apply
```

This has already been applied for the delivered demo. Do not apply again.
It creates private `deploy/codex-demo.env`, backs up the CEO's native agent
configuration and private files under `.runtime/backups/codex-demo/`, imports
the existing server login via Hermes' credential-store helper, and stages the
signed model selection. Credentials never reach the frontend or Git. No
workstation login is copied and the source Codex login is not changed.

Restart only the two changed services, retaining the demo overlay:

```sh
docker compose --env-file deploy/.env --env-file deploy/codex-demo.env \
  -f deploy/compose.yaml -f deploy/compose.codex-demo.yaml \
  up -d --no-deps jarvis hermes-ceo
docker logs --tail 100 jarvis-hermes-ceo
docker logs --tail 100 jarvis-hud
```

The overlay gives only the CEO outbound connectivity for the authorized cloud
provider. Its API remains behind the existing authenticated TLS gateway. The
native agent still uses `hermes_gateway` with Paperclip-managed secret references.
Its max concurrent runs and Hermes gateway limit remain one. There is no local
fallback. An expired/revoked Codex login causes an authentication failure and
needs server-side reauthentication; do not substitute a local model silently.

## Verification

```sh
# Observe the already submitted task; never creates another objective.
python3 deploy/check_codex_demo.py --verify-only
python3 deploy/verify_codex_demo.py

# Read-only visual regression check.
python3 deploy/check_visual_core.py
```

`tests/codex_demo_e2e.cjs` authenticates through the real HUD and submits one
objective. A durable receipt prevents duplicate submission; verification mode
reuses its ID. It checks actual completion, report bytes and SHA-256, provider
labels, paused workers, browser errors, and history after refresh. Browser
success is cross-checked with native execution records and Hermes' provider
and tool journals. See `docs/evidence/codex-demo-hud.json` and
`docs/evidence/codex-demo-execution.json` for actual IDs and timings.

JAR-48 (`69c12f12-4670-46de-85a2-695437e80255`) completed in 48.228 seconds.
Paperclip run `fb38ce52-a3f3-4c9a-b3a6-2e6bb28605b2` succeeded; Hermes run
`run_7c4399ad1fb3420c82ec4d1c6eba6249` completed. Five actual provider requests
used `openai-codex`, `gpt-6.1-sol`, and `chatgpt.com`, with full authenticated
task context. The native report contains all 10 actual model names and sizes.
Its SHA-256 is `9bae3410a56af8a061529b4cb8877d439b67ad43b073366fa16790bf09137bbc`.
The same task and report remained available after a HUD service restart.

Paperclip's gateway accounting currently labels the model unknown and leaves
cost unpriced. Provider/model identity above comes from the actual Hermes
request observer, rather than that generic gateway field. No cloud cost or
apples-to-apples local speed benchmark is claimed.

The demo inventory and native roster are verified tool data. Recommendations,
interpretation, and narrative in the report remain model-generated. A cloud
connection probe alone is not accepted as Paperclip execution evidence.

## Rollback

1. Pause the CEO through Paperclip. Ensure there are no queued/running native
   executions before changing its runtime; cancel an active new demo through
   the authenticated HUD if needed. Keep workers and the operator timer paused.
2. Use the timestamped private backup's `agent.json` to restore the CEO's
   `adapterConfig` and `metadata` with native `PATCH /api/agents/{id}` as the
   board. Preserve the demo issue, logs, artifact, and history.
3. Restore that backup's `config.yaml`, `SOUL.md`, and `auth.json` into
   `.runtime/hermes-ceo/`, preserving ownership and mode 0600. Remove the demo
   env file only after restoring native configuration.
4. Restart **only** `hermes-ceo` with the base Compose file and `deploy/.env`,
   without the Codex overlay. It returns to the original local model; do not
   resume employees or release old tree holds automatically.
5. The HUD can retain its provider display support. To restore the exact
   particle-only image, tag `jarvis-command-center:hud-particle-core` as
   `jarvis-command-center:hud` and recreate only `jarvis`.

To restore the previous static HUD instead, use the preserved image
`jarvis-command-center:hud-before-particle-core`; agent settings are independent
of that visual rollback.

Provider behavior follows the [official Hermes provider documentation](https://hermes-agent.nousresearch.com/docs/integrations/providers).
The cloud login is sensitive credential material; see [Codex authentication](https://developers.openai.com/codex/auth/).
