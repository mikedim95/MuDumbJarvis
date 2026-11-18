# Phase 14 verification ledger — in progress

Phase 14 is **not accepted**. Phases 11, 12 and 13 are committed as
`e4c60d0`, `3bb184d` and `cda2cad`. The Phase 14 changes and experiments remain
uncommitted until real workflows pass. No generated paragraph or model probe
counts as a completed multi-role workflow.

The exact acceptance objective was submitted through the authenticated HUD as
JAR-44 (`f79972eb-c989-4845-bafa-7bd4e11a0eef`). Its CEO created two native
children and reused the existing employees:

| Native issue | Responsibility | Current verified outcome |
| --- | --- | --- |
| JAR-44 | CEO planning, delegation and consolidation | Blocked; no accepted final report |
| JAR-45 (`7dc24648-d025-4450-8957-bcd8b25262d7`) | Primary-source framework research | Real sources retrieved; generated comparison rejected; correction blocked |
| JAR-46 (`a6aa67b4-4cd6-454a-aa4f-747fa972bd7b`) | Isolated demonstration and tests | Real files written, but tests failed; queued behind corrected research |

The first CEO run `65942eb9-07ea-4b84-8780-d810a595b928` produced a plan
without tool calls and was blocked. Run
`9992ef90-ecb5-4950-8333-5a07c9f24270` created both children but put a
dependency in prose instead of recording a native dependency. The operator
later repaired the dependency explicitly; that repair is not attributed to the
CEO. Run `46911618-8dd5-472c-8ff4-d281481b3966` really executed through the
new local 7B profile, but produced only a waiting update. It remains a failed
acceptance attempt despite the native runtime run succeeding.

Research's first run `9f238f2b-4742-4b97-a8af-3ef2c9ef87f8` retrieved real
garak, PyRIT and promptfoo sources and persisted native attachments. Human
quality-review comment `ccc1b1a3-48f9-4950-9b78-2b404a5abca8` rejected
unsupported licensing, architecture, offline-target and integration claims.
Paperclip automatically reopened the same child. Its correction run
`2d05d054-01d7-443c-b3a5-d622b82498bb` did not perform successful research.
Valid source provenance does not validate model-authored claims.

Software run `81d2fac6-e82c-4558-9e78-74d9ab823fbd`, Hermes
`run_c53032987ab14690a9fe414349333e36`, wrote actual source files but failed
tests and used mistyped task paths. It ended failed. The operator independently
checked the terminal cwd behavior and added an explicit authenticated cwd on
each terminal call. A native legacy execution hold was reconciled only after
the actual failed Hermes/native state and retained file hashes were checked.
These controlled recovery steps preserve the same task IDs and history.

An early browser retry selected a stale task control while another task's
monitoring loaded. Its native retry intent failed against the Software hold;
it did not launch a new execution. Selecting a task now clears controls
immediately, and the browser driver waits for a matching task ID before retry.

The local model selection and its limits are documented in
[INFERENCE_SELECTION.md](INFERENCE_SELECTION.md). Original Ollama manifests,
AIGoat and PentAGI were preserved. Tool/host authority and the original human
Software hiring approval were unchanged.

Hermes' installed `pre_verify` hook runs only after code-file edits. The CEO
has no code-edit tools, so an experimental CEO hook could not nudge prose-only
responses. That unused hook was removed. Finalization still blocks incomplete
objectives. The integration now observes the real provider request separately
from preparing preflight context. `model-context.jsonl` records only scope,
model, context length/hash and whether the full context was present; it does
not log prompt bodies or credentials. Hook output is bounded at 32,768
characters to preserve the integration's at-most-32,000-character CEO context.
A read-only size fixture measured the current recovery context at 9,832
characters before the latest clarification, below the old 10,000 limit;
truncation is not claimed as the cause of that retry.

Relevant evidence is under `docs/evidence/phase14-*.json`. The operator's
private `.runtime/phase14-trial-1.json` records the resumable browser submission
and observations. It is excluded from Git. The acceptance driver never retries
automatically and reuses the same root on an explicit recovery retry:

```sh
docker run --rm --network host --user 1000:1000 --env-file deploy/.env \
  -v "$PWD:/workspace" --tmpfs /tmp:size=256m \
  jarvis-command-center:browser-test tests/dynamic_e2e.cjs --trial=1
```

`--retry` requests one explicit native retry through the HUD. `--trial=2` and
`--trial=3` each create one new objective only if that trial has no saved root.
No trial may be accepted without independently reviewing actual source facts,
artifact bytes/hashes, tests, native run ownership and the final CEO report.
Remaining acceptance includes three completed workflows, real correction and
consolidation, employee-hire rejection, restart persistence, direct-chat
regression, final preservation/security checks and the Phase 14 Git commit.
