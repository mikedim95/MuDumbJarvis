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

## Phase 4 — complete (2026-11-12)

Added server/task_api.py to the existing FastAPI application, with authenticated
POST /api/tasks, GET /api/tasks, GET /api/tasks/{id}, and GET /api/agents.
Paperclip remains authoritative; no local task database or scheduler exists.
Native issue idempotency protects retries, including uncertain POST responses.
Agent/project boundaries, mandatory HUD authentication and POST Origin checks
are enforced. Credentials remain server-side and are omitted from responses.

The existing HUD design/input now supports Direct chat and Persistent task
modes. Agent discovery is dynamic; history, comments, run errors and statuses
come from Paperclip. Polling runs every three seconds in task mode. Browser
storage holds only view preferences and an unacknowledged submission nonce;
refresh/reconnect reloads history. Direct chat retains separate Hermes sessions.

Modified files: server/server.py, server/task_api.py, server/hud/index.html,
server/hud/tasks.js, deploy/Dockerfile.jarvis, deploy/start.sh, deploy/compose.yaml,
deploy/hermes.config.example.yaml, .dockerignore, the reporting plugin,
README.md, COMMAND_CENTER.md, tests and evidence snapshots.

Observed verification:
- 20 automated tests pass, including tests packaged in the final HUD image.
- Live unauthenticated history returns 401; authenticated history and saved
  results return 200. HUD JavaScript is served successfully; JS syntax checked.
- Three real API trials of the requested inventory/recommendation prompt:
  JAR-3 / 886fde66-3bb3-4f9e-8ec8-cd65cd757d58,
  JAR-5 / 8ea14a70-8f37-4c8b-81f4-7636aecd9706,
  JAR-6 / ccd51df4-2119-45cf-a889-41e6ff2f9db2.
  All reached done with succeeded runs and persisted result comments. Each has
  an issue/run-correlated local_ollama_models audit containing eight models.
  Each submission was replayed and returned the same UUID without another issue.
- JAR-4 / 2d33efc6-446e-48b7-b4ff-fbb76032833e uses a one-second timeout
  override scoped to that issue only. Its actual run is timed_out/errorCode
  timeout and the issue is blocked; JARVIS exposes that error, never done.
- These three trials are API trials, distinct from browser acceptance.
- The user submitted JAR-7 / b5c84f82-095c-4235-ac40-0b963b301c7f through
  the HUD. Chromium/Playwright then verified its done state, visible exact
  retrieved model names/sizes, successful runtime, canonical Paperclip ID and
  persisted comments. Browser refresh restored the same task and result.
  Evidence: phase4-hud.json and hud-jar-7.png. No browser page errors occurred.

Blockers/fixes: the small model failed to discover the single deferred tool in
an initial attempt (JAR-2), which was rejected and corrected to blocked. Disabled
Hermes tool search through supported configuration to expose the inventory tool
directly. Completion now requires an actual successful inventory call for model
inventory tasks. Verified raw model names/sizes are appended to future result
comments separately from model-generated recommendations. This avoids treating
model-inferred context windows or performance claims as retrieved facts.
Paperclip also requires an unblockDescriptor for blocked writes; added it.
The expected-timeout case can happen before a Hermes turn starts, so its
canonical Paperclip run error may exist without a runtime comment.

Browser control originally had no connected browser. The user explicitly
authorized Playwright for the remaining browser verification. Used an isolated
Chromium test container with its package/image versions pinned together.
The screenshot also exposed misleading upstream static cloud/voice labels;
they now reflect the actual configuration, and the server machine label is
platform-neutral. The intentional timeout left the agent in error; cleared it
through Paperclip's supported clear-error route before the real user task.
Phase 4 ended before the remaining two HUD submissions and restart checks;
Phase 5 below completes those checks.

## Phase 5 — complete (2026-11-12)

Resumed the prior agent's uncommitted browser/restart work. Retained its
running Chromium test rather than creating duplicate verification tasks.
The exact requested inventory/recommendation prompt completed through the
actual JARVIS HUD at least three times:
- JAR-7 / b5c84f82-095c-4235-ac40-0b963b301c7f, user-submitted and re-observed.
- JAR-8 / 76a3de7f-f624-4a95-8e7d-6ca46e41af77, Chromium input + SEND TASK.
- JAR-9 / aa194673-bc9b-4ee2-827c-20ceddc13794, Chromium input + SEND TASK.

Each issue reached done with a succeeded Paperclip execution, persisted
JARVIS-01 result comments, an issue/run-correlated local_ollama_models audit
containing eight actual installed models, and a runtime log identifying
jarvis-hermes:3b / custom provider. The HUD displayed the same UUID and status
as canonical Paperclip. Results include exact tool-retrieved names and byte
sizes separately from model-generated recommendations. JAR-8's screenshot also
captures JAR-9 in_progress, demonstrating real sequential execution.

Restarted all four JARVIS services (HUD, Hermes, internal TLS proxy and
Paperclip), leaving the existing Ollama and PentAGI services running.
All returned healthy. Browser refresh and post-restart observations recovered
all three accepted task IDs, statuses and unchanged comments. The separate
API persistence test also verified the identical prior JAR-3/JAR-5/JAR-6 result
hashes and run records across the restart.

Chromium verified the actual one-second timeout fixture JAR-4 displays blocked
and ERROR: timeout, then sent Reply with READY only through Direct chat.
The runtime returned READY with a real run ID; the Paperclip task count stayed
unchanged. Task and direct-chat sessions remain separate. No browser page
errors were recorded.

Modified/configuration files:
- deploy/bootstrap_paperclip.py: concise instructions; exact retrieved facts and
  tentative recommendations. Deployed adapter instructions match this source.
- tests/hud_e2e.cjs: restart/failure/direct-chat checks, exact byte-size checks,
  and configurable trial count (three by default for future full reruns).
- tests/live_failure.py: clear only the intentional agent error using the
  supported Paperclip endpoint, preserving the failure history.
- tests/live_persistence.py: resolve prior completed issue IDs from evidence.
- README.md, COMMAND_CENTER.md, PHASES.md: access, restart, test and limitation
  documentation. All generated credentials stay in ignored local files.
- docs/evidence/: phase5-browser.json, phase5-runtime.json,
  restart-history.json, updated phase4-hud.json, and HUD screenshots of
  JAR-7/JAR-8/JAR-9, the blocked timeout and direct-chat READY.

Validation:
- 20 pytest integration tests passed; only upstream deprecation warnings.
- Updated browser helper syntax check passed; --observe passed again after
  the restart, including exact byte-size checks for JAR-7.
- Three HUD trials were checked against live authenticated history, persisted
  comments, succeeded runs and local-model/tool audits after the restart.
- JARVIS authenticated health 200; unauthenticated task history 401.
- Hermes authenticated health/models 200; unauthenticated models 401.
- Paperclip's official npm latest tag revalidated as 2026.1106.0.
- Credential scan of tracked and proposed files found no actual secret values.
- git diff --check passed.

Observed limits/fixes: CPU-only inventory jobs take several minutes; services
have bounded 900-second execution timeouts and serialize runtime access.
The small model can still generate unsupported capability/context/CLI claims.
These recommendations are not verified facts; the appended inventory is the
verified tool data. The operating guide documents this limitation and the
embedding-model distinction. The optional upstream Hermes Skills endpoint
continues to return 500; it does not affect inventory execution or task state.
No Hermes or Paperclip core changes were made. No MVP acceptance blocker remains.

The phase 5 browser batch contains two new tasks because JAR-7 was already
submitted through the HUD before this handoff. Together they establish the
required three complete HUD workflows. Future fresh full browser runs default
to three new tasks.

## CEO orchestration — complete (2026-11-12)

Extended the verified Phase 5 deployment with JARVIS-CEO and the existing
JARVIS-01 worker. Paperclip remains the sole task orchestrator and state store.
The HUD now offers CEO objective, Persistent task and Direct chat modes through
the existing authenticated FastAPI backend. Agents and delegated children are
discovered from Paperclip; no fixed specialist team or second database was added.

Fresh acceptance under the final deployed configuration:

- JAR-14 / 4ced33fc-58d1-4053-8303-02963c645763: the exact requested inventory
  objective. CEO chose self, recorded its plan, executed local_ollama_models
  against the existing local Ollama service and produced a technical report.
  Run b0dc4e22-b6e3-4258-aef7-e1bd0e669bb3 succeeded; no child or hire.
- JAR-15 / 00b34673-2995-460d-af5e-7622e5ee1b6d: the additional two-role
  objective. CEO run 3498ac8f-43b6-4506-9b43-f1c55d3afd26 recorded the plan and
  assigned JAR-16 / b76a924a-d1ed-4f06-9b84-68709bf8ad4f to JARVIS-01.
  Worker run 6c959144-3a31-43a8-a785-fd110477ba78 executed the real inventory
  tool, retrieved eight models, stored signed issue/session/run-bound evidence
  and succeeded.
- Paperclip automatically resumed CEO run 0d3512f0-266b-437f-ab95-61ae2fb869f1
  with source issue.children_completed and wakeReason issue_children_completed.
  Its supported Hermes preflight delivered the verified worker data for review.
  The CEO produced a substantive report containing all eight exact names and
  byte sizes. Both CEO runs succeeded and the parent reached done. No manual
  child-completion wake, result injection or extra employee was used.
- Actual Chromium validation matched HUD and canonical Paperclip IDs, plans,
  assignments, statuses, tool audits, signed evidence and results. Browser
  refresh restored history; the roster remained exactly the CEO and worker.

Restarted all five JARVIS services after execution finished. The post-restart
browser validation passed again without creating another objective. Both
accepted roots and their child retained identical statuses, result hashes and
run records. The existing Phase 5 persistence helper also passed unchanged
legacy task history. Health/authentication checks passed, including 401 for
unauthenticated history. Ollama and PentAGI retained their exact container IDs,
start times and configuration values; the comparison normalizes Docker's
non-semantic mount-list ordering. Neither service was restarted or modified.

Modified/configuration files:

- server/task_api.py and server/hud/{index.html,tasks.js}: server-selected CEO
  routing, dynamic role/reporting information, real child results/errors and
  three-second monitoring while preserving legacy worker tasks/direct chat.
- hermes-plugin/jarvis_readonly/{ceo_tools.py,paperclip_reporting.py,__init__.py,
  plugin.yaml}: identity-bound plan/delegate/review/hire requests, supported
  current-turn context, signed execution proof and guarded completion.
- deploy/{compose.yaml,hermes-tls.conf,init.py,start.sh,bootstrap_ceo.py,
  CEO_POLICY.md,hermes.ceo.config.example.yaml,.env.example}: one isolated CEO
  runtime, separate API/callback identities, Paperclip secret references,
  human hiring approval, native issue sessions and bounded timeouts.
- tests/{test_ceo_tools.py,test_paperclip_reporting.py,test_tasks.py,
  ceo_permissions.py,ceo_e2e.cjs,direct_chat_regression.cjs}: automated and opt-in
  live verification. README.md, COMMAND_CENTER.md and CEO_ORCHESTRATION.md
  document architecture, configuration, startup/restart and test commands.
- docs/evidence/ceo-browser.json, ceo-native-wake-final.json, ceo-restart.json,
  ceo-delivery.json and ceo-permissions.json contain final sanitized evidence.
  Rejected attempts remain separately recorded instead of counted as success.

Validation: 111 packaged Python tests passed, with three upstream deprecation
warnings. Live CEO/worker identity, goal/assignment reads and hiring boundaries
passed. The CEO reached the authenticated hire route's semantic guard (422),
while worker/anonymous attempts returned 403/401 without creating an employee.
The CEO could read a neutral approval but approving it returned 403. The final
permission rerun reused its already rejected fixture: two employees and one
rejected neutral approval before and after. No hiring approval was requested.
Source JavaScript syntax checks, repository credential scan and diff checks
passed. Paperclip and Hermes core source checkouts remain unmodified.

Direct chat executed in its separate api_ session and created no Paperclip task
or CEO turn. The first fresh trial returned exact READY and passed core browser
UI, task-count and session checks, then its final background-response scan was
interrupted by login navigation. A second returned HTTP 200 and READY with
model-generated boilerplate, failing an overly strict text-equality assertion.
These are recorded as observed_with_harness_limitations, not a full helper
pass. The future helper bounds response reads, starts its background scan after
login, captures real responses before assertions and uses the Phase 5 READY
containment check; that final helper revision was not rerun for this milestone.

Blockers/fixes: isolated per-agent callback keys work around the installed
Hermes gateway's missing callback JWT forwarding (upstream issue #9956).
An actual blocked-write 403 was caused by naming board as unblock owner;
self-owned blockers fix it. Native child completion requires a waiting parent
that Paperclip can wake, rather than an independently implemented scheduler.
Removed static payload input that hid native objective/wake data; supported
pre_llm_call context now supplies bounded authoritative state and verified
results. Explicit bounded history avoids replaying rejected assistant replies
while preserving issue sessions and durable audit transcripts. Test assumptions
were corrected to the installed child-array and version-2 proof contracts,
retaining exact actor/company/issue/run, HMAC and latest-worker-run checks.

No acceptance blocker remains for this authorized inventory workflow. The
current tool scope is deliberately read-only local inventory. New capabilities
need explicit operator provisioning and an execution-evidence contract; future
hires need human approval. Generated prose can still contain typos or unsupported
source/capability claims; the signed/appended tool data establishes the retrieved
facts. CPU-only inference is slow (the final CEO review took about 18.5 minutes).
Historical cancelled debugging jobs remain inspectable, including Paperclip's
legacy-execution quarantine; they are not accepted results or reused objectives.
The user's requested AIgoat performance comparison follows this separate commit.
