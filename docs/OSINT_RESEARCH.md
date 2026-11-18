# Ongoing OSINT research

The owner authorized daily tools-and-methods research. The native routine is
**Daily OSINT tools and techniques research**, at **09:00 Europe/Athens**. Each
execution creates one CEO objective in the existing OSINT Tools Knowledge Base
project. Jarvis delegates to the existing OSINT employee, reviews actual evidence,
and publishes a result. There is no independent scheduler or inference loop in
the HUD. Native concurrency skips an overlapping execution and missed runs are
not replayed in a burst.

The routine now belongs to **General → Cron jobs**. Its catalog is shared General
knowledge. All five role runtimes can read a bounded checked index of that knowledge,
independently of the mission they are assigned. Mission-specific catalog additions
stay local and are not automatically merged into General research. The native
routine ID, schedule and previous results were preserved during this change.

The initial attempt, JAR-65, could retrieve only garak, PyRIT and Promptfoo and
produced three adjacent AI-assurance entries. The app now supports:

- Public GitHub repository discovery and official HTTPS documentation retrieval.
- Actual README/file contents for repository and GitHub blob URLs.
- Per-source native snapshots, timestamps, content hashes and retrieval errors.
- Prior catalogs belonging to the OSINT employee across company projects.
- Read-only native records/artifact excerpts explicitly referenced in an assignment.
- Cumulative JSON merging, deduplication, source provenance and coverage checks.

`research_sources` retains its existing registered capability name. Its actions
are `search`, `fetch`, `knowledge` and `records`; the old three-framework selector
remains compatible. No shell, tool installation or live-target investigation is
added. Public fetches pin TLS to validated public addresses, validate redirects,
exclude credentials/private networks, and bound response/evidence size.

The standard goal is [the research goal template](../deploy/OSINT_RESEARCH_GOAL.md).
It requires at least 15 distinct cumulative tools across six categories, with at
least three fresh retrieved sources per batch. It prioritizes new coverage on
later runs. Entries record purpose, documented capabilities, usage guidance,
access/cost prerequisites, limitations, source dates and documented-only status.
Reading documentation is never counted as hands-on execution.

The worker may publish `preserve_previous=true` with only new/updated entries;
the runtime merges full prior entries and calculates the actual coverage. A
partial catalog remains useful evidence, but cannot satisfy the required coverage.

Role prompts and standing directions live in native agent records; project
goals, comments, artifacts and signed receipts live in Paperclip. Hermes keeps
conversation history per role/task in its own `state.db`. This is structured
retrieval-augmented knowledge: a replacement model consumes saved context rather
than retraining. Vector embeddings and semantic search are not implemented.

The runtime signs execution receipts after the worker response. CEO verification
checks the complete receipts and native artifacts before supplying bounded review
context. Large source indexes are summarized with counts and hashes for the model;
full source snapshots, artifact receipts and signed originals remain in Paperclip.
Report and catalog excerpts take precedence over raw source snapshots in review.
Large multi-role reviews also use counted, hashed projections of repeated tool
calls. They retain every failure, the latest successful call for each tool kind,
the latest terminal tests, exact inventory and human quality notes. Full current
human instructions remain present; identical copies are referenced once. Prior
CEO planning prose and repeated role descriptions can be omitted from a compact
final review. Native verification still checks every original receipt and artifact.

The first recovered research batch is JAR-72, under the first manual kickoff of
the daily routine, JAR-71. Both are complete, and the native routine run is
`completed`, with no failure reason. The validated catalog has 16 tools across
nine categories, based on 20 fresh source references. All entries remain
documentation-only. The next scheduled run is November 18, 2026 at 09:00 Athens.

The recovered blockers were the three-repository source selector, missing native
record lookup, absent recurring dispatch, completion without coverage validation,
and an oversized CEO review payload. A separate handoff also exposed a legacy
validator that treated the phrase “three-framework-only schema” as a request to
retrieve three frameworks; counts now require an actual research directive.
The model-name reporting guard applies to model-inventory objectives only;
incidental inventory in a worker's diagnostics does not change a staffing
report's acceptance criteria. Successful completion clears obsolete blocker text.
Historical incomplete artifacts are preserved rather than rewritten as successes.

Evidence is in `docs/evidence/osint-native-validation.json` and
`docs/evidence/osint-daily-acceptance.json`. A read-only check of the real retrieval
function loaded all 16 current catalog entries and their checked source references
for a subsequent run (`osint-knowledge-retrieval.json`). The unrelated team handoff
JAR-67 uses explicitly referenced native records rather than duplicating research.

Verification: `python3 -m pytest -q tests` passed 624 tests with one skipped;
`corepack npm test --prefix csi-ui` passed 23 tests. The live browser check passed
desktop/mobile cron navigation and approval-only panel behavior with no native
writes or browser errors (`docs/evidence/cron-jobs-ui.json`). The approval lifecycle
in that check is a browser-only fixture, not a fabricated native approval.
The four-role receipt verification and context check is recorded separately in
`docs/evidence/four-role-context-validation.json`.

Final live acceptance: JAR-66 and its OSINT handoff JAR-67 are complete, alongside
daily batch JAR-71/JAR-72. Their obsolete blocker descriptors are empty. The latest
CEO execution succeeded and received its complete context at the actual Codex
request boundary. See `docs/evidence/osint-final-acceptance.json` and
`docs/evidence/osint-handoff-recovery.json`. Worker results were reused; no duplicate
research or staffing assignments were created for the parent review recovery.
