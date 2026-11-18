# General and missions

The navigation is **Chat / Projects / General**.

- **Chat** is the existing brief conversation with Jarvis.
- **Projects** are missions. Open one to see Jarvis and the jobs he delegated
  in a tree. Each job shows its owner, current state, and a brief outcome
  when one has been recorded. You can send a follow-up below the tree.
- **General** holds team-wide directions. Open **Context**, **Cron jobs**, or
  **Agents** at the top of the left sidebar. Below them, choose a conversation or use **New
  chat**. Each conversation has its own Hermes history and browser draft.
  **General chat** retains the original Administrator conversation. The message
  bar stays at the bottom while you browse context or schedules.

In Chat and General you speak directly to Jarvis, the CEO. Assigning a task
opens its project after Paperclip confirms creation. Questions get a chat
answer. Ask explicitly when you want findings saved as shared General knowledge.

**Agents** shows Jarvis above the team's portrait row. Select a portrait to
see what the agent is doing, why it is waiting, or what needs attention.
Waiting covers ordinary dependencies and reviews. Blocked identifies a
guardrail or a problem such as missing access or evidence that needs attention.
Open a listed project to see its delegation tree. Select an agent in the tree
to return to their portrait. Jarvis can choose a portrait for each new hire
from the [portrait catalog](AGENT_PORTRAITS.md). Jobs started by a cron run show the schedule
that started them. An enabled timer can be idle between runs.

Agents lead reports with the result and include only requested or essential
details. Full deliverables and execution evidence stay available with the run.

Every role receives its standing directions and a bounded, hash-checked General
research index during authenticated execution preflight. Mission goals and local
findings are not automatically promoted. Research catalog lookup can combine
General knowledge with the current mission's catalog; it cannot automatically
read another mission's catalog. General research reads General catalogs only.
The index prioritizes recent catalog additions; full catalogs remain native files.

Missions have a temporary active context. Their completed history and files are
retained in Paperclip for review, but are not injected into new missions. Reuse
across missions needs an explicit owner request through General. This separation
changes context and retention, not tool permissions or approval requirements.

Schedules use native Paperclip routines. Reserved native variable defaults record
`jarvis_work_scope` and `jarvis_mission_id`; execution descriptions also retain a
scope marker, hidden by the HUD projection. Native issue ancestry gives workers
their scope. A mission's scheduled execution stays linked to that mission's
context without becoming a new top-level mission or waking an unrelated project.
Closing a mission through normal Jarvis completion/archive/cancellation pauses
its schedules. Reopening requires an explicit schedule resume. General schedules
are independent.

The existing daily OSINT routine was migrated in place to General, preserving
its native ID, history, catalog and 09:00 Europe/Athens schedule. No duplicate job
or research batch was created. General run results continue to open inline with
the full report and worker files.

Verification includes backend scope/filter/lifecycle tests, the read-only
`tests/general_workspace_e2e.cjs` browser check, the actual result-button check
`tests/cron_result_e2e.cjs`, and native General knowledge reads using all five
role runtime identities. Receipts and screenshots are under
`docs/evidence/general-*` and `docs/evidence/mission-cron-desktop.png`.
