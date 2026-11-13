# JARVIS monitoring and operator controls

Phase 13 extends the existing FastAPI/HUD. Paperclip remains the only source of
employees, tasks, dependencies, approvals, logs and artifacts. There is no new
backend, task store, message broker or execution scheduler. The existing visual
theme and separate direct-chat flow remain. Polling runs every three seconds in
CEO objective or persistent-task mode.

Unlock `/hud/` with the existing HUD token, select a task from history and open
its monitoring sections. Employee cards show native IDs, roles, hierarchy,
availability, profile tools, model, resource limits and workspace authority.
The summary reports native active, queued, blocked, review and terminal states;
it does not manufacture a percentage. Direct-chat sidebar panels are labelled
separately because their session counters do not count CEO employees.

CEO plans, native dependency relationships, execution blockers and recovery
records come from the selected issue. Select a child in history to inspect its
artifacts, evidence and logs. Native parent/child IDs and execution IDs remain
visible. Polling restores the selected task after refresh, reconnect or server
restart; browser storage holds view preferences and an uncertain submission ID,
not task state.

Tool receipts are marked verified only after server-side signature, company,
issue-session, native run and comment-authorship checks. Running journals show
observed progress, not completed work. Completion receipts additionally require
a succeeded native run and a done native task. The tool's observed data and a
model-authored explanation remain different things. Valid provenance does not
prove generated code is correct or generated analysis is factual. Raw receipts
remain in Paperclip while the HUD uses an expandable projection.

Artifacts download through the authenticated backend after issue membership,
size and actual SHA-256 checks. Files are served as downloads with `nosniff`,
never executed as HTML. The log view reads bounded native execution-log chunks
and retains execution IDs and errors. Paperclip redaction and an additional
backend credential filter protect these projections. Adapter configurations,
secret references, private filesystem log references and API credentials are
not returned.

The resource section reads local Ollama `/api/ps` without starting inference or
changing its configuration. It reports loaded-model bytes and context length,
and shows an explicit idle/unloaded state. Twenty-four configured CPU threads
and one shared inference slot are policy values, not 24 concurrent agents.
Native runs can wait for that slot. Host CPU/load/RAM counters are read-only
observations and include other host applications. No Docker socket or host
credential mount was added to FastAPI.

Human controls use native authenticated Paperclip APIs:

| HUD action | Native authority |
| --- | --- |
| Retry same task | `POST /issues/{id}/retry`, stable request UUID and observed run ID |
| Preview/cancel tree | `POST /issues/{id}/tree-control/preview`, then `/tree-holds` with `mode=cancel` |
| Approve/reject | `POST /approvals/{id}/approve` or `/reject`, preserving decision note |
| Download artifact | Native issue attachment receipt and content endpoint |
| Inspect log | Native heartbeat run and bounded log endpoint |

Every control requires the existing HUD authentication and same-origin cookie
protections. Tasks, runs, artifacts and linked approvals are checked against the
configured company/project. Cancellation checks every previewed task before
mutating the tree. Retry delegates execution holds, stale observations and
idempotency to Paperclip. The HUD never silently creates another task to retry.
Approval controls display the scoped proposal and require a decision note.
Hiring approval checks the frozen capability/model/limits/hierarchy and native
configuration snapshot. Provisioning still belongs to the operator reconciler.
Sensitive-action approval records a decision; it does not unlock host tools or
execute the proposed external action.

The browser test uses explicitly labelled unassigned control fixtures, not
employees. It checks native approval/rejection audit records, cancellation,
known completed execution receipts, artifact bytes, native logs, a controlled
monitoring outage and recovery, and refresh persistence. Its automated approval
fixtures are not represented as human hiring approval. The actual human-approved
Software hire remains recorded in Phase 11 evidence.

```sh
# From the deployment checkout; no inference in the unit suite:
docker run --rm --user 1000:1000 --network none \
  -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD:/workspace" \
  -v "$PWD/server/config/server.local.example.yaml:/app/server/config/server.yaml:ro" \
  --workdir /workspace --entrypoint /opt/venv/bin/python \
  jarvis-command-center:hud -m pytest -q -p no:cacheprovider /workspace/tests

# Real authenticated Chromium control fixtures; operator-only credentials:
docker run --rm --network host --user 1000:1000 --env-file deploy/.env \
  -v "$PWD:/workspace" --tmpfs /tmp:size=256m \
  jarvis-command-center:browser-test tests/monitor_e2e.cjs
```

Logs remain inspectable with `docker logs jarvis-hud`, native Paperclip runs,
and the existing employee runtime service journal. Restart only JARVIS-owned
services. For a HUD rollback, the retained image is
`jarvis-command-center:hud-phase12-3bb184d`; retag it as
`jarvis-command-center:hud` and run the normal Compose command for `jarvis`
only. Restore the matching source/config from the Phase 12 commit separately.
Keep native history, workspaces and artifacts; do not replay completed work.

API references: [Paperclip issues](https://docs.paperclip.ing/reference/api/issues/),
[Paperclip approvals](https://docs.paperclip.ing/reference/api/approvals/).
Exact route schemas were also checked against the installed 2026.1106.0 source.
