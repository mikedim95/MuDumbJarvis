# Direct Chat and Projects

The current navigation and scope model is documented in
[General and missions](GENERAL_WORKSPACE.md): **Chat / Projects / General**.
General now owns the former Administrator chat, standing directions and shared
cron jobs; each mission has a separate schedules view. The notes below retain
the history of the initial two-mode implementation.

The default HUD has Direct Chat, Projects and a separate Cron Jobs page. Direct Chat opens by default; later visits
restore the last selected mode. The operations layout remains available at
`/hud/?layout=operations`.

## Direct Chat

Use Direct Chat for brief conversations and questions about Paperclip. Each
request receives a fresh, bounded, read-only snapshot of staff, native projects,
goal counts and recent goals. Mention a task identifier such as `JAR-57` for
its details. If a project is selected in Projects, its details are also available
in Direct Chat. The response includes snapshot provenance separately from the
confirmed Codex provider/model metadata.

Direct Chat uses its existing dedicated Hermes conversation. It can save an
agent's [General Context](GENERAL_CONTEXT.md) when you explicitly ask. It does not create
tasks, delegate workers, approve requests or resume projects. Even `/new`,
`@ceo` and approval-looking text remain conversation in this mode. Switch to
Projects to request execution. A Paperclip outage is reported as unavailable
context while ordinary conversation remains possible.

## Projects

Click **Projects** to see the list. Select a row to open only that project's
context, or use the large **New Project** button at the bottom to open an empty
context with the input prompt. The list disappears when a context is open;
**← Projects** returns to it. No project is created until you submit a goal.
Write a goal and click **Set Goal** to begin.

The **Administrator** button opens a separate chat for system prompts, staff
names, standing directions and starting CEO work. It has its own saved history
and returns to the list with **← Projects**. See [Administrator](ADMINISTRATOR.md).

The entire row opens the project; there is no right arrow. Each row also has a
separate **Delete** button that removes it from the list without opening it.
**Undo** restores the last removed row. Removal uses Paperclip's native
visibility field and persists across browser visits; saved context, comments,
worker results and artifacts remain intact. It does not change execution status.

Jarvis receives a persistent CEO objective in Paperclip, plans the work, assigns
the relevant existing workers, reviews execution evidence and publishes results.
Worker activity and published results appear in the selected project's conversation.
Automatic panels open only for approval requests, with native Approve/Reject controls.
Future hiring and approval boundaries are unchanged.

Use [Cron Jobs](CRON_JOBS.md) for recurring work. The [OSINT research workflow](OSINT_RESEARCH.md)
keeps a cumulative catalog and runs daily through native Paperclip scheduling.

Each project has its own active context: its goal, follow-up messages, child
assignments, native runs and artifacts. The CEO's Hermes session is keyed by
company, employee and objective ID. New projects create separate objective IDs
and sessions; updates append to the selected project's native conversation.
Choosing a list entry restores its existing context rather than starting it again.
Project state stays in Paperclip; browser storage holds only the selected view,
project reference and an unacknowledged request ID.

Switching projects keeps unfinished drafts separate while the page is open.
Switching modes also keeps Direct Chat and project messages separate. The last
selected project and its published result restore after a page reload. Changing
views does not stop or restart work. Opening Projects from the mode bar shows
the list. Old held objectives remain held.

In Projects, `/new <goal>` and `@ceo <goal>` still start separate objectives.
`/new` alone clears the selection. Explicit `/approve <UUID>` and `/reject <UUID>`
operate through the existing authenticated approval endpoint. `/chat <message>`
switches to Direct Chat.

## Deployment and checks

The HUD image is built with `deploy/Dockerfile.hud-ai`; it includes the new
`server/chat_context.py` and `server/hud/modes.js`. The frontend bundle is built
from `csi-ui` using `corepack npm ci --ignore-scripts` and `corepack npm run build`.
Retain all existing Codex workforce Compose overlays when recreating the HUD.
The prior image is saved as `jarvis-command-center:hud-before-two-modes`.

CEO review context now compacts large model-facing worker output excerpts while
retaining verified identities, exact inventories, artifact references/hashes,
tool outcomes and human rejection notes. Full signed evidence is still verified
before completion. The CEO gateway must restart to load this plugin change;
this does not retry old tasks.

`python3 -m pytest -q -p no:cacheprovider tests` passes 570 tests, with one skipped.
`corepack npm test` in `csi-ui` covers routing and project-list popup isolation. The live browser check
is `tests/two_modes_e2e.cjs`; its private receipt prevents duplicate test goals.
Evidence is saved under `docs/evidence/two-modes*`.

Live acceptance on November 17, 2026 passed: **JAR-57** delegated **JAR-58** to
Systems, verified its signed inventory read and artifact, then published the CEO
report and completed. Direct Chat read actual staff details without creating a
goal. Project/draft switching, selected-context reload, and desktop/mobile mode
navigation passed with no browser errors. Native provider journals confirm
different issue-scoped CEO sessions for JAR-57 and the previously completed
JAR-56. The check observed existing history without resuming old held work.

The list-to-context navigation is also verified by the read-only
`tests/project_navigation_e2e.cjs` check: empty new context, separate drafts,
reload persistence, the General Context viewer, and desktop/mobile layout.
Its receipts and screenshots are under `docs/evidence/project-*`.
