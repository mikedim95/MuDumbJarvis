# Cron Jobs

Open **General → Cron jobs** for team-wide routines, or open a mission under
**Projects → [mission] → Cron jobs** for schedules local to that mission. These views display native
scheduled jobs, cron expressions, time zones, next runs, recent results and links
to each execution's project context. Jobs can be created, edited, paused, resumed,
run immediately or archived. Archiving stops future dispatch and retains history.

**Open latest run** opens that execution's project context and restores its
published reply immediately. Select the CEO report under **Reports and research files**
to read the full text. It opens automatically when the run has no published reply.
Worker reports, the cumulative catalog and source snapshots also have previews and downloads.
These results remain in the project conversation; they do not open floating
panels. Reopening or reloading a run restores its saved result without restarting
work or duplicating replies.

Schedules are Paperclip routines with schedule triggers. The owner-facing API is
`/api/cron-jobs`. Authenticated writes use the same origin checks as other task
operations. Only the current company's CEO-owned routines/projects are exposed;
routine secrets and environment values are excluded from the UI projection.

New schedules run daily at 09:00 Europe/Athens by default. A numeric five-field
cron expression and IANA time zone can be edited. The app uses native
`skip_if_active` concurrency, `skip_missed` catch-up and an `always` activity gate.
Each execution is a real issue with its own context; project artifacts retain
knowledge between runs. No browser tab needs to remain open.

General jobs contribute reusable knowledge across missions. Mission jobs use the
selected mission's context and do not publish its findings into General. Completed,
cancelled, hidden or held missions cannot start/resume scheduled work. Closing a
mission through the CEO or archiving/cancelling it in Jarvis pauses its local jobs;
General jobs continue. Existing jobs retain their scope; create a separate job to
change scope. Results retain their original scope in the native execution record.

Creating a job starts it paused until its trigger is saved. Editing temporarily
pauses dispatch and restores its prior status after a successful save. Repeating
a creation with the same title/project reuses the native job. Immediate runs use
native idempotency keys; uncertain requests retain their nonce for retry.

Administrator chat can also use `list_schedules`, `schedule_project` and
`set_schedule_status`. Ordinary Direct Chat does not gain scheduling permissions.

Automatic floating panels are reserved for pending approval requests. Native
progress, errors and result comments stay in the normal conversation and job
records. Approve/Reject buttons use the existing authenticated native decision
endpoint. Project waiting labels distinguish active worker handoffs from actual
blocked work without modifying native task states.

The read-only browser check `tests/cron_result_e2e.cjs` exercises the actual
**Open latest run** button, compares the displayed report and worker catalog with
native artifact bytes, verifies project isolation, repeated navigation, result
restoration and desktop/mobile layout. Its receipt and screenshots are in
`docs/evidence/cron-result-*`. No native tasks, approvals or schedules are mutated.
