# Agent intelligence and prompt architecture v2

Implemented in the existing Paperclip/Hermes integration. No framework, agent,
inference configuration, permission set, scheduler, or retrieval database was added.
The production audit was read-only. The reviewed migration was then **applied**
while all five roles were idle, with zero queued/running native work and zero active
runtime agents. All five idle containers were reloaded to activate cached plugin
code and local policies; readiness checks passed. No production objective, inference
evaluation, historical retry, or hold release was submitted for demonstration.
The private plan is `.runtime/prompt-v2-plan.json`; its rollback receipt is
`.runtime/backups/prompt-policies/20261119T083953Z-d1978e25/receipt.json`.
The hash-only preservation/readiness audit is `.runtime/prompt-v2-activation-audit.json`.

## What is authoritative: observed on 2026-11-19

The five active roles use **openai-codex / gpt-6.1-sol**, with one shared inference
slot. Native identity-bound inference selections match their local runtime configs.
`profiles.json` still contains a legacy local-model base value; it is not the
selected provider/model for this workforce. That file and its permission hashes
were left unchanged.

| Agent | Native instruction hash, prefix | SOUL hash, prefix | Saved prompt scopes | General revision |
|---|---|---|---|---|
| JARVIS | `831c9cca6501` | `831c9cca6501` | Direct Chat | 4 |
| Software | `57f79127d5c6` | `57f79127d5c6` | none | 3 |
| Systems | `f9e5a5506d93` | `f9e5a5506d93` | none | 1 |
| Security | `645a905f0f16` | `645a905f0f16` | none | 1 |
| Research | `bd96ba5c4803` | `2c22f7bb9bd5` | agent | 2 |

The CEO's native prompt and SOUL match `deploy/JARVIS_CEO_POLICY.md`.
`deploy/CEO_POLICY.md` is the older policy, still referenced by legacy bootstrap
and tests; both legacy files remain available. Software, Systems, and Security
have generated generic defaults. Research has a manually saved native prompt with
additional retrieval guidance and a stale OSINT identity, distinct from its local
generated SOUL. Its native prompt will remain byte-for-byte intact. Fresh registered
identity in preflight resolves name ambiguity without rewriting owner text.

All worker skill files were generated with nearly identical boilerplate. None of
the active role toolsets exposes `skill_view`, `skills_list`, or `skill_manage`.
Inspection of the installed Hermes renderer confirmed that it omits both the
skills index and auto-loaded skills without those tools. Merely writing better
SKILL.md files would not have made the procedures available.

Resolution path, verified against the local adapter and installed runtime code:

1. Paperclip Hermes gateway `buildRunBody` takes `adapterConfig.instructions`, then
   `payloadTemplate.instructions`, then its fallback. Active payload templates do
   not provide `system_message`. Hermes accepts `system_message` before `instructions`
   if an operator adds that alternative in the future; migration refuses to manage
   a shadowed native prompt.
2. Hermes assembles local `SOUL.md` identity, its own guidance, the caller's system
   message, context files, and runtime environment. SOUL is **not** replaced by the
   Paperclip instructions. These are fragments of the same assembled system prompt,
   not independent permissions or a guarantee that one prose fragment wins.
3. `paperclip_reporting.begin` authenticates company, employee, issue, and current
   execution. Its preflight supplies current task data, this agent's saved General
   directions, exact mission directions, bounded native knowledge, and evidence.
   Old conversation history is background, never a new task instruction.
4. Direct/General chats use their existing `administration.chat_instructions` saved
   scopes and HUD request grants. The CEO's custom Direct prompt is preserved.
   Chat receives `CEO_CHAT_ROLE`, reply style, and scoped current facts separately.
5. Tool guards, native ownership, sandbox controls, inference locking, and human
   approval checks enforce authority regardless of prompt wording.

The table above records the pre-migration audit, not the new policy hashes. Native
policy provenance now records version 2 for all five roles. Research's native hash
remains unchanged; its SOUL supplies the new default methodology. Protection checks
confirmed that all other native configuration and each runtime config.yaml were
unchanged. All five installed procedures were checked from their actual profile homes.

The UI's **System prompt** shows the native per-turn instruction fragment. **Saved
directions** are separate owner preferences. Neither is the entire Hermes payload.
The reconciler now preserves an unmarked native edit as well as a UI-saved override,
including a newer native edit that differs from the saved copy. Corrupt saved hashes
fail closed. Provisioning no longer overwrites existing SOUL or skill files.

## Versioned layers and real procedures

- **A:** `deploy/prompts/common.md`: evidence, authority, untrusted data, isolation,
  efficient tool use, bounded recovery, truthful execution, concise completion.
- **B:** `ceo.md`, `research.md`, `software.md`, `systems.md`, `security.md` in that
  directory. `deploy/prompt_policies.py` assembles A+B and registered identity.
- **C:** existing authenticated preflight, improved by `prompt_context.py`: current
  instruction, objective/mission, own directions, actual capabilities/tools,
  dependencies, deliverables, criteria, and bounded evidence. No company-wide task
  histories are copied into the execution. Unrelated goals are omitted in v2.

Managed native defaults contain A+B; their SOUL carries only stable identity, so
the policy is not duplicated. When a custom native prompt is retained, the generated
SOUL can carry A+B as defaults alongside it. A customized SOUL is also preserved.
If both are custom, the plan leaves them custom rather than silently imposing v2.

`deploy/skills/` contains five distinct procedures: executive delivery, source
research, isolated development, scoped administration, and isolated security
analysis. Initial provisioning seeds them; explicit migration upgrades recognized
generated copies. Unknown edits stay intact. On v2 preflight the runtime reads only
its fixed role skill from its own home and supplies the bounded procedure directly.
This avoids adding skill tools, filesystem permissions, or another Hermes instance.
Symlinked procedure paths fail closed; procedures are limited to 8 KiB.

The unused Documentation capability template is retained with its existing legacy
workflow. It was not hired, removed, granted tools, or added to the five-agent team.

## Handoff, completion, and recovery

V2 CEO delegation uses the existing `paperclip_ceo` tool with a `handoff` object:

```json
{
  "action": "delegate",
  "agent_id": "<existing-ready-specialist-UUID>",
  "title": "Verify the scoped change",
  "handoff": {
    "objective": "Verify the assigned implementation",
    "expected_outcome": "A reproducible acceptance result",
    "relevant_context": "Short native source/artifact references",
    "deliverables": "Checker source and concise verification report",
    "acceptance_criteria": "The specified positive and negative cases pass"
  },
  "depends_on": ["<actual-prerequisite-child-UUID>"]
}
```

The tool validates the contract and renders OBJECTIVE, EXPECTED OUTCOME, RELEVANT
CONTEXT, AVAILABLE TOOLS, DEPENDENCIES, DELIVERABLES, and ACCEPTANCE CRITERIA into
the native child description. Tools come from the registered profile plus the
already-available identity tool; dependencies come from scoped structured UUIDs,
not prose. Communication-only work retains its narrower existing exception.
Nested handoff headings, oversized copied documents, missing fields, foreign
dependencies, and non-reporting employees are rejected before creating work.
Legacy unstructured callers continue working outside the v2 policy. New structured
handoffs are also accepted from a legacy caller, allowing a gradual rollout.
For older sessions that put the complete five-field contract in `text`, the same
fields are normalized from JSON, one JSON escaping layer, or labeled text. Missing
fields, extra tool/dependency keys, nested headings and oversized payloads still fail
validation. Tool descriptions now direct v2 callers to the separate `handoff` object.
Selecting an already-associated project is a read-only no-op even when historical
children exist; moving that tree remains forbidden. Failed operations do not record
self-execution credit, and a failed delegation cannot mark its objective complete.
These paths are covered by `tests/test_delegation_compatibility.py`.

Native assignment idempotency and one existing employee per work package remain
unchanged. Corrections reuse the original child. Paperclip still controls all
dependency release, scheduling and continuation; inference concurrency is unchanged.

Workers return STATUS, RESULT, VERIFIED EVIDENCE, ARTIFACT REFERENCES, LIMITATIONS,
and REMAINING BLOCKERS. V2 validates this short report and rejects partial/blocked
completion; the existing stronger execution, successful-test, current-run artifact,
signature and hash checks still apply. Headings alone cannot satisfy execution.
Ordinary Markdown/case variations are accepted. Communication PONGs keep their
existing validation. The existing two verification continuations now instruct a
different bounded repair and reuse of valid evidence; they do not retry tasks or
override holds. CEOs still inspect and correct existing failed children, escalating
only when their existing authority cannot resolve the cause.

## Knowledge boundaries

No retrieval backend was replaced. `research_sources` knowledge/records retrieval,
native General catalogs, project ancestry, per-agent General directions, mission
documents, original artifacts and their integrity checks remain the existing system.
The new context labels separate instructions, procedures, shared references, mission
knowledge, task evidence and history. A retrieved native catalog is not automatically
owner-approved or tested; its actual recorded validation level governs the claim.
Knowledge proposals are deliverables, not automatic global prompt updates. No vector
database or automatic promotion of project findings was introduced.

## Activation and rollback

Use the **prompt-only** migration, not the Codex workforce bootstrap/configuration
script. The latter also performs credential/provider staging and is not an upgrade
entry point for this task.

From the repository root:

```sh
python3 deploy/migrate_prompt_policies.py --plan .runtime/prompt-v2-plan.json
```

Review that private JSON (it contains the exact before/after prompt and skill
texts). The printed summary omits private text. `--agent-id UUID` limits planning
to one existing role. The current plan preserves Research's owner prompt and all
saved directions/chat prompts; the other four native defaults are eligible.

Arrange an operator-controlled idle window with no new submissions or scheduled
dispatch for the selected roles. Check both native queued/running work and runtime
active agents. Do not release historical holds, resume paused agents, or interrupt
work to make the migration fit. Apply performs fresh native/file/source checks
under the same per-agent lock used by the HUD and reconciler, and refuses active
or queued agents. It does not control scheduling and is not a scheduler transaction;
keep that idle window through apply and reload.

```sh
python3 deploy/migrate_prompt_policies.py --apply .runtime/prompt-v2-plan.json
```

Apply changes only selected native prompt fields/policy provenance and recognized
SOUL/skill files. It backs up exact before/after values in a private receipt under
`.runtime/backups/prompt-policies/`. Saved overrides, General Context, model/provider,
credentials, runtime limits, tool permissions, schedules, task records, evidence,
and histories are not replaced. A concurrent edit or changed policy source requires
a fresh reviewed plan. Partial API/filesystem failure reports the rollback receipt.

Then reload only the selected **idle** Hermes containers during that same window
to load cached plugin/schema code and SOUL. No all-team restart or automatic resume
is included. The existing bind mounts already expose the plugin; no new image,
installation, profile permissions, or configuration is needed. Recheck readiness
without submitting an objective. Existing resumed Hermes sessions can retain their
cached system fragments; do not reset active/history sessions to force an upgrade.
Confirm the policy version and complete preflight in normal next-run context logs.

To revert during an idle window:

```sh
python3 deploy/migrate_prompt_policies.py --rollback <private-receipt.json>
```

Rollback changes only the migrated prompt fields/files and refuses subsequent owner
edits. Reload selected idle runtimes to pick up reverted local files. The receipt is
not a task-history backup; no task history is modified by either direction.

## Verification

`tests/test_prompt_migration.py` exercises actual assembly/resolution, native default
upgrades, unchanged custom native/SOUL/skills, corrupt and concurrent saved edits,
fresh-read reconciliation, active-run refusal, idempotency, backups and rollback.
It permits only native agent reads/patches; task, employee and schedule creation
cannot occur in these fixtures.

`tests/test_prompt_architecture.py` exercises authenticated preflight, role-skill
delivery without skill tools, direct CEO answers, scoped specialist handoffs,
real dependency UUIDs, duplicate prevention, invalid/out-of-scope rejection,
one current contract, direction isolation, bounded context and recovery, report
validation, and actual subprocess test output through the existing evidence guard.
It does not evaluate model reasoning through inference or submit live objectives.

Actual regression run: `python3 -m pytest -q tests` — **775 passed, 1 skipped**.
The optional host Hermes middleware import test is skipped because that package is
not installed in the host test environment; Hermes runs inside the existing images.
The latest focused prompt/provisioning/reconciliation run passed **65 tests**.
Existing FastAPI startup/shutdown deprecation warnings remain unrelated to this change.

Existing CEO, artifact, profile, employee guard, blocker, work-scope, General Context,
Administrator, inference, and cron suites remain regression coverage. Actual final
test results are recorded here and in the task delivery. Idle activation/readiness
was verified separately; deterministic tests do not establish measured improvements
in model reasoning. Existing task outcomes and holds were not changed by this upgrade.
