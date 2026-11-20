# General Context

Open an agent's profile and choose **Context** to see its standing directions
and system prompt. General directions apply across missions; project directions
belong only to the selected mission. Saved directions supplement the system prompt;
they are not its replacement. See [prompt architecture v2](PROMPT_ARCHITECTURE_V2.md)
for the complete runtime resolution and explicit migration procedure.

Ask explicitly to save a direction, for example:

- “Add to your general context: keep replies concise.”
- “Save in Research's general context: distinguish verified facts from assumptions.”
- “Replace Software's general context with: include actual test results in reports.”

Ordinary conversation and questions do not save directions. Mention the agent
by name, or select an agent in the General Context viewer and explicitly ask to
save a general direction for it. Explicit “your”/“yourself” instructions address
Jarvis. Appending is the default; replacing or clearing requires an explicit
request. The UI displays the saved native revision.

Each context is stored in that agent's Paperclip metadata at
`jarvis.general_context`. Revisions persist across browser/service restarts and
apply across projects. Each employee's authenticated turn preflight reads its
own directions; Jarvis's direct conversation and CEO project preflight read his
own. Goals, project conversations, assigned work and artifacts stay issue-scoped.
General directions are preferences and do not grant tools, host access, hiring
authority or exceptions to runtime controls.

The direct runtime's `general_context` tool uses the existing HUD backend.
Paperclip credentials remain there. A short-lived request grant is created
from the authenticated latest user message, with bounded target agents and
operations. Only the exact callback accepts the direct runtime's API identity;
that identity does not authorize other HUD endpoints. A native save receipt is
required before reporting a saved update. Normal conversations receive a
read-only grant. Replacements validate the current revision, repeated tool
calls are idempotent within a turn, and five previous revisions are retained.
Notes are limited to 8,000 characters per agent.
Saved changes are read on the agent's next turn; they do not interrupt or
restart work already in progress.

Clicking an agent shows its current native assignment and a short last-activity
summary in both General and project views. Project filtering happens before
history retrieval. Only the selected profile reads recent assignment histories
(the three most recently updated jobs plus its current job). Published updates
are labelled separately from signed tool actions; raw payloads and private model
reasoning are excluded. Native activity is refreshed every eight seconds while
the agents column is visible. Pending owner questions stay first, and opening a
long question brings both its input and Reply action into the scrollable view.

Backend tests cover explicit versus conversational requests, per-agent scope,
metadata-policy preservation, revision conflicts and callback isolation.
`tests/project_navigation_e2e.cjs` verifies the actual General Context viewer.
Live Codex calls also verified native saves and clearing for Jarvis and Software;
temporary verification notes were removed afterward. Sanitized receipts are in
`docs/evidence/general-context-live.json`. The complete backend suite passes
559 tests (one skipped), and the frontend suite passes 21 tests.

## Communication-check repair

The first manual project **JAR-59** created ping children JAR-60 through JAR-63.
They initially replied but were blocked by capability-work verification. A
communication-only path now requires an actual `agent_identity` call and PONG
containing the registered name. Both native parent and child must have an
acknowledgment-only scope. These turns permit identity and optional
acknowledgment publication only; their signed receipt proves contact, not
research, diagnostics, code or tests. Mixed work requests retain the original
execution requirements. The CEO revalidates employee/task/run identity and
registered role before accepting each receipt.

The same four children were retried using native retry receipts. All four
completed, the CEO reviewed their actual signed responses, and JAR-59 completed.
Unrelated old objectives and stop holds were not released.

## General chat knowledge

Ask in General, for example, “Save the findings from JAR-84 in General knowledge.”
JARVIS can publish excerpts of the named project's public CEO replies. A request
referring to the only active project resolves against visible CEO missions.
A publication receipt identifies the source and the durable copy in the CEO's
native Paperclip metadata (`jarvis.knowledge_publications`). General chat
retrieves those notes in every conversation, including new threads. Publication
does not create a mission or change standing directions. Retried excerpts are
deduplicated. A new research assignment can still run as General work.
