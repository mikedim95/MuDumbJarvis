# JARVIS CEO and Codex specialists

JARVIS is the Paperclip CEO and the default conversational interface. The HUD
keeps one input and Send. Paperclip owns objectives, employees, dependencies,
approvals, comments, execution status and artifacts; Hermes runs the scoped
tools. Every selected employee uses `openai-codex / gpt-6.1-sol`. Ollama remains
available for read-only inventory and its existing configurations are preserved.

```text
User → JARVIS HUD → authenticated FastAPI → Paperclip JARVIS CEO
                                           ↓ native child assignments
                                  selected Codex/Hermes specialists
                                           ↓ tools and artifacts
                                  Paperclip → JARVIS review → user
```

## Talk to JARVIS

The current HUD provides explicit **Direct Chat** and **Projects** modes.
Direct Chat is the default conversation with read-only Paperclip context.
In Projects, each selected goal has its own persistent CEO/worker context.
See [the current two-mode interface](TWO_MODES.md). The ordinary-message CEO
routing described below now applies within **Projects**.

### Local Codex handover — November 17, 2026

The shared Hermes credential store now uses the existing login from this local
session's `CODEX_HOME` (`/home/kali/.codex-nektarios`). All six inference runtimes
resolve the same current login. The source CLI login was left unchanged, and
the previous shared store is backed up privately under
`.runtime/backups/local-codex-handover/20261117T061949Z/`. Direct chat, the CEO
and the four specialists keep their existing identities, tools and separate
contexts. This does not copy the interactive Codex conversation into Hermes.

Real authenticated browser chat confirmed `openai-codex / gpt-6.1-sol` and a
successful `local_ollama_models` tool call. New read-only CEO task **JAR-56**
completed and persisted `local-codex-handover.md`, containing all ten actual
model names and byte sizes. Its first final reply omitted the model names, so
the existing completion guard blocked it; one follow-up on the same task
corrected the reply without weakening that guard. The final result is visible
after browser reload. Native Hermes/Paperclip run links, report hash, current
login resolution and the verification window's balanced inference-slot events
were checked. Evidence is in `docs/evidence/local-codex-handover.json` and
`local-codex-handover.png`. A pre-existing root-owned direct-chat inference
journal was returned to the runtime user so that it can record new admissions.

This verifies the login handover and simple CEO execution, not full workforce
acceptance. **JAR-51 remains blocked**: its four completed child results produce
a review projection larger than the CEO's 32,000-character context bound.
That consolidation issue and older objectives were left unchanged. No employee
was hired or given additional authority during this handover.

Ordinary messages now go to the CEO. The first creates a persistent objective;
later messages continue that objective through native Paperclip comments. CEO
and worker updates appear in the conversation and automatic agent panels.
These are published updates and verified tool records, never simulated thoughts
or invented progress.

```text
/new Compare the approved security frameworks, create a small isolated demo,
run tests, and have Security review the actual code before reporting back.
```

Use `/new <objective>` or `@ceo <objective>` for a separate objective. `/new`
alone clears the current objective selection without deleting native history.
Use `/chat <message>` for the separate direct Codex conversation; that mode
does not create Paperclip work or share CEO issue context.

Ask naturally to create or select a Paperclip project, inspect staff, request a
missing capability, or propose removing a direct report. Project/repository
records do not grant filesystem access or publish code. New hires and removals
produce native proposals. The human decides with `/approve <approval-UUID>` or
`/reject <approval-UUID>`. JARVIS cannot approve its own proposals. Retry the
identical text after an uncertain request so its saved nonce is reused.

## Initial staff and authority

The user explicitly authorized a CEO with at least four specialist reports.
The existing Research and Software employees are reused. The two missing
specialists have native operator-authored hire approvals tied to that request;
the system does not claim that a model autonomously requested those hires.
Future hires still require a fresh human decision.

| Employee | Native ID | Scope |
| --- | --- | --- |
| JARVIS, CEO | `50a7204d-39f5-4e4a-98bb-ff07cf4e526e` | Plan, select the minimum suitable staff, delegate, manage native projects, review evidence and consolidate results |
| JARVIS Research | `09f66b7a-d435-4332-be9a-9223055d0bef` | Approved public sources and local model metadata; issue reports |
| JARVIS Software | `a5780699-e4d4-4256-b93e-2bbcf46da59b` | Build and test code in its own isolated workspace |
| JARVIS Systems | `5c82ec12-85e9-40be-99bb-158f0ea5e012` | Read model metadata and diagnose its sandbox; no Kali administration |
| JARVIS Security | `364450b8-c2b3-4afc-970e-ec6c0ea81618` | Review published code and test isolated fixtures; no external scanning |

Each employee has its own identity, API secret, profile, tool allowlist and
issue-scoped context. Sandboxes are non-root, have no host directories or Docker
socket, and have no external route. Runtime containers can reach Codex; their
shell/file tools, where allowed, operate through SSH inside the isolated
sandbox. Runtime credentials are never forwarded into fixture commands.

The current Research source catalog covers **garak, PyRIT and promptfoo**.
This is not an unrestricted web-search implementation. Systems diagnostics
describe its container unless a tool explicitly supplies verified host metadata.
Fixture code must not call an LLM provider directly; the employees' authorized
Codex inference is supplied through Hermes. Sensitive host/external actions
remain unavailable without a separately approved and scoped implementation.

## Authentication, inference and dormancy

An operator-signed version-3 selection binds each employee ID and role to its
approved capability hash, the Codex model and required human approvals. It does
not expand that capability's tools. Historical version-1 local and version-2
read-only demo receipts remain valid under their original authority.

All profiles borrow the single native Hermes OAuth store under
`.runtime/codex-shared`. Native refresh locking and write-through prevent
multiple copied rotating grants from racing. Only each container's own profile
is mounted below that root; other employees' memory and sessions are not shared.
Existing `/opt/data` aliases retain legacy SSH/plugin paths. No credentials are
included in Git, the frontend, or public evidence.

A shared kernel lock at `/opt/jarvis-codex/inference.lock` surrounds each physical
main-model request through Hermes' supported `llm_execution` middleware. Its
release is protected by `finally`, including provider errors. Missing lock
configuration fails closed. Automatic compression, prepare-ahead, memory LLM
and title-generation calls are disabled because they bypass this middleware in
the pinned Hermes version. Local inference fallback is disabled. Requests may
queue, but there is no second task scheduler or queue database.

The pinned Hermes `v0.23.1` named profiles require the supported configuration
`gateway.standalone: true` when running in separate gateway containers. This is
an installed-version compatibility setting; Hermes and Paperclip internals are
not patched. Each gateway permits one run, and employees use no timer inference.
The operator lifecycle reconciler provisions approved employees and stops owned
runtime/sandbox containers after native termination. It does not create tasks
or delete profiles, workspaces or history.

Paperclip redacts metadata fields whose names contain `authorization`. Initial
operator-hire validation therefore uses the real native requester/decider,
unchanged approved reason and capability snapshot, plus the signed employee
selection. It does not depend on a redacted marker or rewrite approved payloads.
New setup markers use the non-secret key `bootstrap_request`.

## Startup, logs and verification

Run from `/home/kali/jarvis-command-center/jarvis_ai`. Initial staging has already
been applied with a private backup at
`.runtime/backups/codex-workforce/20261116T120951Z`. The helper defaults to a dry
run, refuses active executions, retains old holds and leaves employees paused
until their runtime checks pass. Do not rerun setup as a task-submission method.

```sh
python3 deploy/configure_codex_workforce.py
sh deploy/restart_workforce.sh
```

The restart helper retains all required overlays and only reconciles the HUD,
direct-chat and CEO Compose services. Owned employee runtimes are managed by
`staffing.py`, rather than Compose. A deliberate idle-runtime refresh is:

```sh
python3 deploy/staffing.py --apply --refresh-idle-runtimes --leave-paused --agent-id EMPLOYEE_UUID
```

Use the native adapter/health checks before resuming the selected employee. The
operator timer manages later approved hires; stopping it pauses lifecycle
provisioning, not Paperclip's task authority.

```sh
systemctl --user status jarvis-employee-runtimes.timer
journalctl --user -u jarvis-employee-runtimes.service --no-pager -n 60
docker logs --tail 100 jarvis-hermes-ceo
docker logs --tail 100 jarvis-hud

# Existing receipt means observe rather than duplicate the acceptance task.
python3 deploy/check_workforce.py --verify-only
```

Private `.runtime/codex-workforce-task.json` preserves acceptance intent and
request IDs. Public browser evidence is written to
`docs/evidence/codex-workforce-hud.json` and its screenshot. Runtime model traces,
signed tool receipts, native runs and artifact hashes must also be checked;
configuration or assistant prose alone does not establish success. Per-profile
`logs/inference-slot.jsonl` contains request/slot correlation without prompts
or credentials. **At this documentation checkpoint, initial staffing is staged
and runtime provisioning is in progress; the four-role live workflow has not
yet been accepted.**

Old objectives JAR-2, JAR-4, JAR-29, JAR-32, JAR-44 and JAR-47 retain native
manual holds. They are not resumed by this rollout. Earlier unfinished Phase 14
acceptance is distinct from the newly authorized Codex workforce verification.
AIGoat, PentAGI and Ollama are outside this change.

## Modified integration and rollback

The change uses `configure_codex_workforce.py`, `staffing.py`, the workforce
Compose overlay and secret-free env example; signed inference policy and
middleware; CEO/company/employee tool hooks; existing FastAPI task/approval
routes; and the minimal HUD conversation/automatic-panel components. No second
backend, task database, orchestrator or message broker is introduced.

To roll back, first stop `jarvis-employee-runtimes.timer`, pause the five native
employees and finish or explicitly cancel active runs. Keep every old task hold.
Restore the backed-up native configuration and metadata for the original CEO,
Research and Software identities from the private backup. Keep the two new
employees paused, with their approvals, tasks and files intact. Stop only their
label-matched owned containers; do not delete any workspace or history.

Restore the corresponding private profile config/SOUL files and the previous
inference selection. OAuth refresh state can rotate: use a current server login
rather than replay an expired backup grant. Remove the workforce overlay/env
selection only after restoring matching native/runtime policies. Retain the
Codex chat overlay if returning to the prior Codex demo.

The pre-workforce HUD image is available by immutable image ID
`sha256:f638d0e87a84629f1809d3783016807da5ec2b229c04ea203dc7179354777e90`,
corresponding to source `102e551`. It predates the default-CEO conversation and
new workforce APIs; restoring it disables those UI features but does not erase
Paperclip history. Recreate only the intended services with the reviewed prior
overlays, verify health, and resume only the explicitly selected demo CEO.
Never automatically release old holds or resume old worker objectives.
