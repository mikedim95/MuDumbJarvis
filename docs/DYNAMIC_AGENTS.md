# Dynamic agents and monitoring

Phases 11–14 extend the verified CEO baseline (`e4b7e00`). Phase 11 passed its
staffing/runtime acceptance checks on 13 November 2026; Phases 12–14 are not yet
accepted. Existing Paperclip and Hermes source
repositories, Ollama configuration/models, AIGoat and PentAGI remain protected.

## Authority and runtime lifecycle

Paperclip remains the only employee roster, approval system, task database and
orchestrator. The existing FastAPI backend is the authenticated HUD gateway.
Capability templates live in `hermes-plugin/jarvis_readonly/profiles.json`:
Research, Software Development, System Administration, Documentation and
Security Analysis. Templates do not create employees.

The CEO reuses suitable employees and handles simple inventory work directly.
An essential missing capability uses the native approval-aware
`POST /api/companies/{companyId}/agent-hires` flow. The proposal contains a
versioned capability hash, model, resource limits, authority and reporting
line. Pending or rejected candidates have no runtime or execution credentials.
The CEO cannot approve its own request. A pending matching profile is reused
across objectives rather than creating duplicate candidate employees.

An operator-owned user service (`jarvis-employee-runtimes.timer`) reconciles
**approved employee runtime configuration only**. It does not select, create,
assign, retry, complete or schedule tasks. It verifies the human-approved
Paperclip snapshot, creates per-employee keys and Hermes state, and announces
runtime readiness using a native Paperclip comment. Paperclip performs all
subsequent wakeups and task orchestration.

Every managed employee has an independent Hermes home, credentials, session
database, logs, tools and skills. Native `hermes_gateway` remains the adapter;
its session strategy is `issue`. Memory learning is disabled. No timer
heartbeats or inference run while employees are idle. State/history is retained.
The existing JARVIS-01 employee keeps its ID and task history and is reused for
Research in a separate runtime; the original user-facing chat is separate.

Code/file tools use Hermes' existing SSH execution backend to reach a private
container, never Kali. Execution containers are non-root, read-only outside
their workspace/tmpfs, drop all capabilities, have no credentials or Docker
socket, and use Docker's internal **isolated** gateway mode so the host bridge
has no reachable gateway address. They have no external route or DNS forwarding.
Only the owning Hermes runtime shares that private execution network. The
runtime parent holds API credentials; its model-facing tools cannot execute
in that parent. Each role has explicit toolsets and CPU/memory/PID limits.

All employees select the existing `jarvis-hermes-aigoat24:3b` alias and share
Ollama's one inference slot. No model/server concurrency setting is changed.
Twenty-four inference threads do not imply concurrent agent model calls.

## Operator commands

From `/home/kali/jarvis-command-center/jarvis_ai`:

```sh
docker build -f deploy/Dockerfile.employee-sandbox -t jarvis-command-center:employee-sandbox-v3 .
python3 deploy/staffing.py                    # no mutation: show the plan
python3 deploy/staffing.py --apply            # reconcile approved employees only
python3 deploy/install-runtime-service.py
sudo loginctl enable-linger kali             # user service survives logout/reboot
systemctl --user status jarvis-employee-runtimes.timer
journalctl --user -u jarvis-employee-runtimes.service
```

`--adopt-existing research --apply` is an explicit one-time migration of the
pre-existing worker, not a general hiring bypass. Its exception cannot grant
an unapproved coding profile. New employees require native human approval.

Do not edit generated `.runtime` secrets into source. API keys are kept in
private files, container environment and Paperclip secret references. No board
credential or Docker socket is mounted into AI runtimes or execution containers.

## Verification so far

The original 131 tests plus new profile, approval and tool-boundary checks pass
as **168 tests** (three existing upstream deprecation warnings).
The native staffing fixture is JAR-38
(`61b95c0b-bc96-46e8-ab66-51b2e9198cfc`). Its first attempt preserved a real
gateway DNS failure. The proxy syntax was fixed and validated using `nginx -t`;
both original gateway health routes returned HTTP 200. Native recovery required
an operator evidence reconciliation before retrying the same task. The audit
thread explicitly corrects an unsuccessful run-list probe; the actual evidence
is the recorded DNS failure before HTTP delivery and its gateway-event window.
An initial model response described hiring without calling a tool and was
correctly blocked. It is not accepted as a hire or execution result.

The existing employee's managed Research runtime completed real JAR-39
(`b4c7a9f2-6a26-41fb-8935-cff666996fa6`) through JARVIS and the new gateway route.
The CEO subsequently made a real `request_employee` call in native run
`a77af36e-02c9-4cf0-a320-53a6449a2f9d`, using local Ollama. Paperclip created
pending approval `80bebd62-f765-421e-bab7-9ebbf313e9df` for JARVIS-DEV-01,
candidate `a5780699-e4d4-4256-b93e-2bbcf46da59b`. The user explicitly approved
that scoped employee on 13 November 2026. The native approval receipt records
the instruction and approved capability hash. Provisioning then passed the
native Hermes adapter environment check with independent credentials, private
workspace and 2 CPU / 2 GiB limits on both runtime and execution containers.
Exactly three employees exist: CEO, the reused Research worker, and this
approved Software Development employee. The other profiles remain templates.

JAR-38 was retired as a cancelled staffing fixture after the hire was approved;
it is not claimed as a completed coding objective. The first Software smoke
test, JAR-40 (`3ae256e0-3994-4252-919b-b44031eacf7e`), exposed two real upstream
defaults: the builtin write root `/opt/data` and gateway cwd `/root` differed
from the approved SSH sandbox workspace `/workspace`. The owned failed run was
stopped, recorded as blocked, independently inspected, and reconciled using
Paperclip's supported recovery API. No source file or passing tests existed.
The guard now binds the native task cwd before builtin SSH dispatch, rejects
out-of-workspace cwd overrides, and sets the role's builtin file-safe root.
The same issue completed in native run `c2f5ca60-3e0d-41e6-afd7-23d6b79ee7f2`,
Hermes run `run_dd13c6dabbd44ae7b169d05869c4132c`. Its issue-scoped Hermes
transcript contains actual `agent_identity`, `write_file` and `terminal` calls.
The agent wrote a 302-byte Python file and executed two unittest cases with
exit code 0 and `OK`. An independently labeled operator rerun also passed.
Authenticated JARVIS returned the same task ID, employee and succeeded run.
Missing and invalid gateway credentials returned 401; valid credentials
returned 200 for that exact execution.

One intermediate adapter run succeeded after only identity and prose describing
future work. It was explicitly rejected, its task disposition corrected to
blocked, and its history preserved. Managed Software completion now requires
admitted successful terminal execution and real passing unittest/pytest output
when tests are requested. Identity and prose cannot satisfy that check. The
supported `pre_verify` hook adds a bounded reminder after edits; upstream invokes
that hook only after file mutations, so it is not relied on for text-only turns.
Authenticated employee context separately supplies the real assignment.
The final model prose mistyped its employee UUID; native identity and tool
receipts remain authoritative. Generic signed execution/artifact presentation
and the declared public-source/artifact tools are Phase 12 work, not claimed
as delivered by this staffing phase.

Evidence is in `docs/evidence/phase11-native-hire-pending.json`,
`phase11-research-runtime.json`, `phase11-sandbox-transport.json` and
`phase11-preservation.json`, `phase11-human-approval.json`,
`phase11-approved-runtime.json`, `phase11-software-initial-failure.json` and
`phase11-software-recovery.json`, `phase11-text-only-rejected.json`,
`phase11-restart-delivery-recovery.json` and `phase11-software-runtime.json`.
The first dedicated hire call had an incorrect
legacy tool label in the custom audit; its actual name is proved by the Hermes
core trace. Future audit labels have been fixed and tested, and historical logs
have not been rewritten. Native failure/recovery history is retained.

## Modified configuration and rollback

Phase 11 adds the profile registry, employee guard/identity tool, native hiring
helper, isolated workspace image and operator runtime provisioner. It extends
the existing nginx gateway with an internal employee route; existing worker
and CEO routes were verified healthy. `bootstrap_ceo.py` now preserves an
already managed worker's capability configuration. `paperclip_reporting.py`
and `employee_tools.py` bind authenticated assignment context, scoped tool
receipts and fail-closed managed completion. Role/profile, hiring, tool-boundary
and completion regression tests are under `tests/`. No task database or task
scheduler was added.

The operator user service is enabled, and the user's prior `Linger=no` setting
was changed to `yes` so this service can run after logout or boot. Its unit
files are in `~/.config/systemd/user`; native Paperclip state and per-employee
configuration remain under their existing stores.

For rollback, first disable `jarvis-employee-runtimes.timer`. Wait for owned
employee work to finish. Restore the worker's pre-migration gateway configuration
using Paperclip's native agent configuration revisions, and remove only its
`metadata.jarvis` managed binding through the authenticated operator API. The
original direct-chat/worker runtime and its old credentials are retained;
no histories or model files were deleted. Stop only containers labeled
`io.jarvis.employee` for the rolled-back employees, retain their state, and
restore the prior JARVIS source revision. Restore the prior user-linger setting
if the runtime service is removed. Do not delete native approval/task history.

Official references: [Paperclip agents and hiring](https://docs.paperclip.ing/reference/api/agents/),
[approvals](https://docs.paperclip.ing/reference/api/approvals/),
[Hermes Gateway adapter](https://docs.paperclip.ing/reference/adapters/hermes-gateway/),
[Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles),
[Docker isolated gateway mode](https://docs.docker.com/engine/network/port-publishing/).
