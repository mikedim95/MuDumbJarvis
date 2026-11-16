# Live CSI workspace

Open **CSI LIVE WORKSPACE** in the HUD's Views panel. Choose a Paperclip case
from the top bar. The dock restores, focuses, and opens individual windows.
Drag their title bars, resize their lower corners, minimize, or close them.
Title-bar arrow keys move a window; Shift + arrows resize it. Compact displays
show one selected panel at a time so controls remain usable on a phone.

The CEO uplink submits a new persistent objective through the existing JARVIS
task controller. It retains native request idempotency and issue-scoped Hermes
execution. **Agent Channel** displays the selected task's actual executor,
published plan, and response. A worker's reply is never labelled as the CEO's.
Read Reply uses an available **local device voice**, after a user click. When
the browser has no local voice, the interface explicitly offers text only.
Direct Hermes chat remains in its existing separate HUD mode/session.

## Architecture

```text
Paperclip native issues / employees / runs / comments / artifacts
  → authenticated FastAPI GET /api/tasks/{id}/events
  → bounded deterministic event snapshot, polled every 3 seconds
  → React CSI windows / graph / operation log / timeline

CSI CEO uplink → existing JarvisTasks controller → POST /api/tasks
  → Paperclip → existing Hermes Gateway → scoped tools + Codex demo inference
```

There is no additional backend framework, task database, orchestrator, event
broker, or WebSocket infrastructure. Paperclip remains authoritative. The event
API is a read projection of existing records, protected by the same task
authentication and company/project scope. The original command center,
particle core, approvals, and monitoring controls remain available on return.

Each snapshot contains a source task, executor identities, traceable events,
native artifact metadata, and relationship nodes/edges. Event IDs are stable
across identical reads. Newly recorded objects/updates highlight their relevant
window; repeated polling does not replay unchanged discoveries. A window a user
closed stays closed and can be restored from the dock.

Browser storage contains only the selected case, window geometry, visibility,
focus, and seen event IDs. It does not contain copies of findings, task state,
credentials, or results. Refresh restores those preferences and re-fetches the
case from Paperclip. Switching cases aborts the old request and clears the old
case's displayed data. Polling pauses when the document is hidden; errors are
shown explicitly and any retained snapshot is marked stale.

## Windows and factual meaning

| Window | Data source and behavior |
| --- | --- |
| Identity Analysis | Actual registered executor name, native ID, role, availability, provider, and model. Identity matches require explicit verified tool findings. |
| Recovered Files | Native Paperclip uploaded artifacts, downloadable through authenticated integrity checking. The title does not imply deleted-file recovery. |
| Analysis Warning | Actual task blockers, failed/interrupted executions, and verified tool errors. Clean cases do not show a false alert. |
| Operation Log | Read-only xterm.js display of recorded events, public updates, and authenticated tool output. No terminal input or host shell exists. |
| Links Detected | React Flow graph of actual tasks, executors, runs, artifacts, parent relationships, and recorded dependencies. Editing the graph cannot change Paperclip. |
| Case Timeline | vis-timeline view of actual record timestamps. Items are presentation-only and cannot edit native dates. |
| Network Trace | SVG relationships for recorded retrieved source URLs/hosts or explicit verified trace data. No inferred IP ownership, packet routes, or geographic positions. |
| Evidence Metadata | Native file name, ID, source task/run/creator, byte count, timestamp, and SHA-256. Downloads verify bytes and hash on the server. |
| Decryption | Explicit verified tool-reported decryption events only; no synthetic progress, random percentages, or simulated cracking. |
| Agent Channel | Current task executor's published plan and reply, optional local speech, with the persistent CEO uplink below. |

## Event contract

`GET /api/tasks/{id}/events` returns:

```json
{
  "task_id": "native-task-uuid",
  "source": "Paperclip",
  "snapshot_id": "deterministic-sha256",
  "task": {"id": "native-task-uuid", "status": "in_progress"},
  "agents": [],
  "events": [{
    "id": "stable-event-id",
    "type": "task.progress",
    "task_id": "native-task-uuid",
    "occurred_at": "native-record-timestamp",
    "title": "Recorded update",
    "data": {},
    "provenance": "native_record",
    "source_ref": {"issue_id": "native-task-uuid"}
  }],
  "graph": {"nodes": [], "edges": []},
  "artifacts": []
}
```

Native event types include `identity.updated`, `task.progress`, `task.failed`,
`analysis.warning`, `evidence.file_recovered`, `evidence.metadata`,
`timeline.updated`, and `graph.node_discovered`. Published summaries are labelled
`agent_summary`; structured findings come only from `verified_tool_output`.
Execution provenance establishes where data came from; it does not make every
model interpretation a verified conclusion.

`identity.partial_match_found`, `network.trace`, and `decryption.progress` may
come from explicit `discoveries`/`events` objects inside successful signed tool
results. Native source references can also produce a network source-host event,
with their limited meaning attached. A sentence in a model summary is never
parsed into a discovery, an invented percentage, or a new relationship.

The projection is bounded to 25 related tasks, 400 events, 160 graph nodes, and
240 edges; truncation is disclosed. Full history remains in Paperclip. Raw
receipt blobs and explicitly marked private reasoning are omitted from public
updates. Known secrets are redacted server-side. React renders text as text;
timeline labels use DOM text nodes; xterm output strips ASCII and C1 control
sequences including clipboard/OSC commands.

The CEO's successful inventory read publishes an immediate signed native tool
receipt. It changes neither task status nor scheduling. This lets the live
feed display actual tool data before the final report is consolidated.

## Libraries and build

Cyberdeck UI was downloaded at commit
`a4c84e6380a3c2918fb131a810b0da493b6b0877`. Actual shared tokens, HUD Card,
Profile Card, Modal, and Status Badge styles are vendored with their unchanged
originals and MIT license. React owns the floating lifecycle. No upstream
demo site, CDN scripts, analytics, or extra web server are loaded.

The isolated `csi-ui/` package pins React, react-rnd, Motion, React Flow,
xterm.js, and vis-timeline in its lockfile. Build output is local static JS/CSS
under `server/hud/csi/`; third-party license notices are retained.

```sh
cd csi-ui
npm ci --no-audit --no-fund
npm run build
npm test
```

## Verification

Run from the server repository:

```sh
# Real existing case data; no task mutation or inference.
python3 deploy/check_csi_windows.py

# Submit exactly one authorized new demo objective through the CSI uplink.
python3 deploy/check_csi_windows.py --live

# Observe that existing objective; never submit another one.
python3 deploy/check_csi_windows.py --verify-only
python3 deploy/verify_csi_execution.py
```

The live harness stores its intent before submitting and retains the native
request ID. If a response is lost, observation mode recovers exactly one
matching native task rather than creating replacement work. Browser-only XSS
and HTTP-outage fixtures are clearly distinguished from actual task evidence.
Private failure screenshots/DOM are written only under ignored `.runtime/`.
Public receipts and screenshots live in `docs/evidence/csi-windows-*.json/png`.

The initial browser pass verified real libraries, actual artifacts and hashes,
all window controls, geometry/closed-state restoration, blocked-task warnings,
mobile bounds, reduced motion, and recovery from an intercepted outage. It made
zero backend mutations. Unit and exact-commit checks are recorded separately
with the final delivery evidence; no configuration-only acceptance is claimed.

The real CSI uplink objective is **JAR-49**
(`f24886ef-2d89-423f-b18d-20c89786792b`). Native run
`1fa9a582-f22a-4c84-967c-ea06a7966574` succeeded and Hermes run
`run_f51e76e094384f3986c447d1f89f995c` completed in **47.219 seconds**.
Five observed requests used Codex `gpt-6.1-sol`, with full task context. The
signed inventory comment was recorded before completion and appears as a
verified tool event; the report lists all ten live Ollama models accurately.
Artifact `c00fdfab-69c1-4048-b902-3b34b1434ec4` has SHA-256
`ac11386834a322d1011377a3f963d2e7c468aa79206eefa5794c5573ac5c35b9`.
Refresh and a HUD restart preserve this case, receipt, graph, and report.

See `csi-windows-initial-live.json` for the original one-submission browser
observation, `csi-windows-live.json` for subsequent read-only checks, and
`csi-execution.json` for independent run/provider/tool/artifact correlation.
314 tests pass on the exact selected commit, 331 on the full working checkout,
and five frontend state/security tests pass. The difference is earlier
unfinished Phase 14 changes deliberately left outside this feature commit.

## Deployment and rollback

Only HUD presentation/API code and the narrowly scoped CEO inventory reporting
hook change. Existing model configuration, tool permissions, hiring approvals,
shared local inference slot, AIGoat, and PentAGI remain untouched. Old Phase 14
objectives retain their native pause holds; workers and the staffing timer
remain paused. The approved Codex demo stays isolated from direct local chat.

`deploy/Dockerfile.hud-csi` overlays only CSI files onto the preserved image
`jarvis-command-center:hud-before-csi`. Build with a minimal context containing
the files it copies; never include private configuration or `.runtime` data.
Restart only `jarvis` using the existing Compose files/env. The first hook load
also restarts only the idle CEO, after confirming no active runs.

To roll the UI back, tag `jarvis-command-center:hud-before-csi` as
`jarvis-command-center:hud` and recreate only `jarvis --no-deps`. Existing native
tasks, reports, and tool receipts stay intact. If reverting the inventory
reporting hook, restore only that feature's hunk while preserving earlier
unfinished changes, confirm the CEO is idle, and restart only its container.
No rollback should resume old objectives or clear Paperclip history.

Primary library references: [Cyberdeck UI](https://github.com/riagoncalves/cyberdeck-ui),
[react-rnd](https://github.com/bokuweb/react-rnd), [Motion](https://motion.dev/docs/react-animate-presence),
[React Flow](https://reactflow.dev/learn), [xterm.js](https://xtermjs.org/docs/guides/import/),
[vis-timeline](https://visjs.github.io/vis-timeline/docs/timeline/).
