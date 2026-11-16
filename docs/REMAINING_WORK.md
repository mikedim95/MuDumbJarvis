# JARVIS — remaining work and stopped-state handoff

Written: 2026-11-16. Last implementation evidence: 2026-11-13.

**Unfinished Phase 14 work remains stopped at the user's request.** The user said “pause” and clarified
“stop.” The November 16 request authorizes documenting the handoff only.
This note is not permission to retry those objectives or continue Phase 14.

Subsequent explicit authorization on November 16 covers the floating particle
core and a separate Codex-powered CEO demo. The particle core is deployed in
commit `41a57fe`. The Codex demo reuses only the CEO; Research and Software stay
paused, the staffing timer stays stopped, and native pause holds preserve the
three unfinished CEO objectives. See [Codex demo](CODEX_DEMO.md). This separate
demo does not count toward the unfinished Phase 14 acceptance workflows.

The later November 16 CSI popup request additionally authorizes the floating
window workspace and its real event projection, using the existing backend.
It does not resume the stopped orchestration trials. See [CSI workspace](CSI_WINDOWS.md).

## Locations and recorded stop

- Deployment: `kali@100.101.41.44`, repository
  `/home/kali/jarvis-command-center/jarvis_ai`.
- Canonical handoff: `docs/REMAINING_WORK.md` in that repository.
- Durable local copy: `/home/wam/JARVIS_HANDOFF.md`.
- Temporary source mirror with some undeployed edits: `/tmp/jarvis-dynamic`.
  Preserve/review those edits before relying on this temporary directory.
- Private chronological worklog: `.runtime/PHASES11_14_WORKLOG.md`.
- Private stop record: `.runtime/phase14-user-pause.json`.

The stop record is timestamped **2026-11-13 17:15:52 UTC**. Native pause
requests were made for the CEO, Research and Software employees; the
`jarvis-employee-runtimes.timer` user timer was stopped; the trial-1 browser
observer container was stopped. The authenticated Hermes API accepted a stop
request for the owned CEO run below and returned `stopping`. Its final terminal
state was not checked after the user's stop instruction. Do not assume an
interrupted run has no reconciliation hold.

HUD and Paperclip were left available for review. PentAGI, AIGoat and the shared
Ollama service were not stopped. Service state has not been revalidated as part
of this documentation request.

## Verified baseline

| Phase | Commit | Verified scope |
| --- | --- | --- |
| 11 | `e4c60d0` | Capability profiles and native approval-gated staffing |
| 12 | `3bb184d` | Isolated Hermes employees, actual tools/tests, signed execution receipts and native artifacts |
| 13 | `cda2cad` | Authenticated monitoring, native controls, evidence/log/artifact access and browser persistence |

The current repository HEAD was read as `cda2cad` on November 16. Phase 14
has substantial **uncommitted** changes; preserve them. Do not reset/clean the
checkout or present it as the completed Phase 13 implementation.

Earlier live successes remain valid: JAR-41 retrieved an actual source-module
inventory; JAR-42 completed eight isolation checks, two program tests and three
offline Promptfoo echo-provider cases, with independent verification. Those
checks do not establish acceptance of the larger Phase 14 objective.

The last full regression suite passed **267 tests**. A later targeted suite
passed **129 tests**. Subsequent local-only request-observer edits were not
rerun or deployed before stopping; do not describe them as tested.

**Phase 14 acceptance: zero of three complete workflows accepted.**

## Existing objective and identities — reuse these

Exact submitted objective:

> Research three open-source AI security frameworks, compare their capabilities
> and architectures, produce a technical report, create a minimal isolated
> demonstration, and execute tests.

| Record | Native ID | Last implementation finding |
| --- | --- | --- |
| JAR-44, CEO objective | `f79972eb-c989-4845-bafa-7bd4e11a0eef` | No accepted consolidated report; latest attempt stopped by the user |
| JAR-45, Research child | `7dc24648-d025-4450-8957-bcd8b25262d7` | Real sources retrieved; unsupported comparison claims rejected; correction blocked |
| JAR-46, Software child | `a6aa67b4-4cd6-454a-aa4f-747fa972bd7b` | Actual files written, but tests failed; native research dependency repaired by the operator |

- Company: `1da0bc85-d81f-4e61-b73e-1569f5eced85`.
- Project: `7d2a3c33-9561-4dfa-bc82-044dce2484ea`.
- CEO employee: `50a7204d-39f5-4e4a-98bb-ff07cf4e526e`.
- Research employee: `09f66b7a-d435-4332-be9a-9223055d0bef`.
- Software employee: `a5780699-e4d4-4256-b93e-2bbcf46da59b`.
- Latest stopped native CEO run:
  `16fa1bd5-20fb-4b30-afc6-a67d603bd24a`.
- Corresponding Hermes run: `run_237fe3f11af74fa5b786702e8c5cc93a`.
- Trial state: `.runtime/phase14-trial-1.json`. Trials 2 and 3 had not been
  submitted in this work session. Confirm saved state before creating anything.

## The actual blockers

1. **CEO action selection:** initial attempts narrated plans without executing
   them. A later run created both children but put a dependency in prose instead
   of a native structured argument. Another run returned a waiting update rather
   than requesting corrections on blocked children. The operator's dependency
   repair is not autonomous CEO evidence.
2. **Research accuracy:** source retrieval worked, but the generated comparison
   made unsupported licensing, architecture, integration and compatibility
   claims. Native quality-review comment
   `ccc1b1a3-48f9-4950-9b78-2b404a5abca8` rejects those claims. Execution
   provenance does not validate a paragraph's accuracy.
3. **Software execution:** real files were written, but mistyped issue paths,
   incorrect artifact arguments and failed tests prevented acceptance. The
   integration now binds every terminal call to its authenticated issue cwd;
   this fix still needs a successful full Phase 14 recovery workflow.
4. **Inference diagnosis:** shared CPU inference adds latency, but its precise
   contribution to the stalled attempt is unproven. A live PentAGI TCP
   connection can be idle. Interrupted usage counters of zero do not establish
   that a request never ran. Do not repeat either claim as a diagnosis.

## Configuration and fixes at the stop

The selected JARVIS model was `jarvis-hermes-qwen24:7b`, a new alias reusing
installed 7.6B weights and the existing tool template. All original nine model
manifests were preserved. JARVIS clients share one selected alias, 24 CPU
threads and one inference sequence; 24 threads do not mean 24 simultaneous
agents. Model-only selection is signed and recorded separately from frozen
employee authority and human hire approval.

Latest configuration work restored Paperclip's native `buildInput` by setting
CEO `payloadTemplate.input` to null, retaining its two-message history anchor.
It also selected the supported named local provider
`custom:jarvis-local-ollama`, using the same local endpoint and
`extra_body.max_tokens: 768`. The live runner confirmed a **768-token ceiling**
during the last attempt. That is a resource observation, not workflow success.

Alias/Hermes defaults declare a 65,536-token context. A 32,768-token loaded
runner was also observed. Verify the effective request window before claiming
it matches the declaration. An earlier observed 8,192-token output budget was
not reliably attributed to a particular client.

The CEO's full 11,414-character preflight context was confirmed in the actual
provider request. The latest request was approximately 64,592 characters
overall (Hermes estimate: 16,148 input tokens). Prompt length and local model
behavior require measurement before further tuning.

The experimental CEO `pre_verify` hook was removed: installed Hermes invokes
that hook only after code-file edits, and the CEO has no code-edit tools.
Finalization still blocks incomplete work. Hook output now permits 32,768
characters for an integration context bounded at 32,000 characters.

Two local-only edits need review after explicit permission to resume:

- `/tmp/jarvis-dynamic/hermes-plugin/jarvis_readonly/paperclip_reporting.py`
  unwraps the actual Hermes observer envelope `{method, body}` before examining
  tools and output limits; associated cases are in `tests/test_ceo_tools.py`.
  The deployed observer had examined the envelope's top level. Consequently,
  empty `available_function_names` and null `request_max_tokens` in those old
  logs **do not prove tools or limits were absent from the request**. Test and
  deploy the correction only when the affected runtime is idle.
- `/tmp/jarvis-dynamic/deploy/hermes.ceo.config.example.yaml` was updated to
  include the named provider, reply limit and hook-output bound. It was not
  synchronized to the deployment checkout before stopping.

Some narrative docs predate the latest cancellation/configuration changes.
Reconcile them against this handoff, the private worklog and actual receipts.

## Remaining work, in order — after explicit resume only

1. **Inventory the preserved state.** Read Git status/diffs, pause and trial
   records, native issue/run statuses, Hermes terminal state and any execution
   holds. Check current user instructions. Do not blindly run bootstrap/start,
   resume all agents, retry a job or discard local changes.
2. **Make the observer accurate.** Review the local-only envelope fix and CEO
   example, run relevant tests, synchronize reviewed files and reload only idle
   JARVIS runtimes. Confirm actual outgoing function definitions, reply ceiling,
   complete context, model and endpoint. Keep credentials out of logs/frontend.
3. **Recover the exact stopped objective safely.** Before resolving a native
   legacy-execution hold, establish provider termination and actual action
   outcomes. Reconciliation evidence must distinguish native checkout/status
   bookkeeping from model actions. A `restored` recovery requires an actionable
   native source status such as `todo`; `blocked` was rejected by the native
   schema. Restoring `todo` can itself trigger continuation. Inspect admission
   before requesting an additional retry; preserve all existing IDs.
4. **Obtain real CEO repair and completion.** Require actual scoped correction
   calls on existing children, accurate research grounded in retrieved primary
   sources, a native prerequisite relationship, actual isolated demonstration
   and passing tests, persisted worker artifacts, and CEO review/consolidation.
   Do not write substitute agent answers or manually mark the objective done.
5. **Complete three real workflows.** Finish trial 1 with its failure/recovery
   history clearly labeled, then submit clean trials 2 and 3 through the HUD.
   Verify native plans/assignments, minimum employee reuse, local Hermes tool
   execution, dependencies, results, hashes/authorship/run bindings, errors and
   final display. Separately fact-check every accepted report. Label toy
   demonstrations and deterministic assertions honestly.
6. **Finish persistence and regression checks.** After owned jobs are idle,
   verify browser refresh and JARVIS/Paperclip service restart preserve task,
   agent and artifact relationships; check direct chat remains separate and
   functional; verify failures/cancellation/recovery remain visible. Confirm
   resource serialization and role/tool/network/host restrictions.
7. **Close delivery.** Update architecture, installation, configuration,
   secret-free examples, test commands and rollback documentation to the actual
   implementation. Rerun appropriate integration checks, protected-service/model
   preservation audit, secret scan and Git diff checks. Commit Phase 14 only
   when its acceptance criteria really pass; otherwise record remaining
   blockers without claiming completion.

Approval testing already has evidence: the real human-approved Software hire
is `80bebd62-f765-421e-bab7-9ebbf313e9df`. A separate operator-authored
negative hire proposal `61a68c62-a3e6-44f4-abd5-f514a7f6912c` was rejected
through the HUD on JAR-47 without creating an employee. That negative fixture
is not an autonomous CEO hire or a new human decision. Preserve the distinction;
do not create unnecessary employees merely to repeat these checks.

## Evidence, controls and safeguards

- Public receipts: `docs/evidence/phase14-*.json`, including isolated
  cancellation, CEO cancellation reconciliation, bounded-runtime configuration,
  model selection, preservation, quality review and browser/hire-rejection tests.
- Background and implementation notes: `docs/PHASE14_VERIFICATION.md`,
  `docs/INFERENCE_SELECTION.md`, `docs/RUNTIME_ISOLATION.md`,
  `docs/MONITORING.md`, `docs/DYNAMIC_AGENTS.md`, `docs/CEO_ORCHESTRATION.md`.
- Acceptance observer: `tests/dynamic_e2e.cjs`; fixture stage files are private
  under `.runtime`. If its saved trial root is missing, the driver can create a
  new objective. Inspect state before invoking it; `--retry` requests a mutation.
- Reviewed configuration backups include
  `.runtime/backups/phase14/inference-20261113T162100Z-1a6f53`,
  `.runtime/backups/phase14/context-20261113T164720Z`, and
  `.runtime/backups/phase14/reply-bound-20261113T170810Z`.
  Use documented rollback procedures and retain native configuration history;
  never restore by deleting approval or execution history.
- Server-side secrets remain in `deploy/.env` and private runtime files. Do not
  copy credentials into this note, Git, frontend responses or public evidence.

Paperclip remains the only task database/orchestrator; Hermes the runtime;
Ollama the local inference provider; the existing FastAPI backend the integration
layer. Preserve authentication, direct-chat separation, frozen permissions and
human approval gates. Never give employees unrestricted Kali access. Do not
modify or interrupt PentAGI or AIGoat, replace original model definitions, add a
fixed large team, introduce another orchestrator/database, or use Hermes internal
subagents as a substitute for persistent Paperclip delegation.
