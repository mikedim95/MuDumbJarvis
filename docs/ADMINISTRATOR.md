# Administrator

Open **General** and choose a conversation in the left sidebar. The original
Administrator history appears under **General chat**. To change a prompt,
open the agent profile's **Context**, expand **System prompt**, and send
the requested change in the bottom message bar. An explicitly named target takes precedence.

Examples:

- “Rename JARVIS Research to JARVIS OSINT.”
- “Update the selected system prompt to answer more directly and act on clear requests.”
- “Show the CEO system prompt, then add this instruction: …”
- “Keep this standing direction for all workers: record which tools worked best.”
- “Start a project with this goal: …”

The panel supports the CEO and its existing workers, plus separate Direct Chat
and Administrator prompts. Role prompts are stored in native Paperclip
`adapterConfig.instructions`, which the Hermes gateway adapter sends on each
execution. Chat prompts are stored in the CEO's `metadata.jarvis.system_prompts`
and sent as Hermes `instructions` on each chat turn. Saved edits apply on the next
turn; a running worker keeps the prompt with which its execution started.

Changes preserve the rest of the agent configuration. Native metadata retains
recent prompt versions and former names. Standing directions use the same
per-agent durable [general context](GENERAL_CONTEXT.md) as Direct Chat. Within
Administrator, clear standing instructions need no special phrases. Questions
and suggestions alone should not cause settings changes.

New assignments open as CEO-owned projects, including requests phrased as
questions such as “Can you compare these tools for me?” Retrying the same
submitted message reuses its native idempotency key. Creating a project returns a link to
its separate project context; Administrator itself is never a project task.

## Integration

The HUD provides authenticated `/api/admin/config`, `/api/admin/history` and
`/api/admin/chat`. The conversation is reserved as `jarvis-administrator-v1`,
with Hermes session key `jarvis:administrator:chat`. Direct Chat cannot select
this conversation. Session creation is serialized and the mapping is written
atomically to retain both conversations during concurrent first turns.

`jarvis_administrator` calls `/api/admin/tool` using the existing chat runtime
credential. Only the HUD can grant an active Administrator request. Direct Chat
and workers cannot promote their own requests. The chat runtime receives no
Paperclip board credential. Writes target only the configured company, CEO and
current direct reports. Prompt replacements require the current content hash;
native configuration is reread and merged before saving.

The HUD and employee runtime reconciler share a per-agent filesystem lock in
`server/logs/agent-config-locks`. Reconciliation merges only its runtime fields
into the latest native metadata and honors saved owner role prompts. Container
checks cannot restore stale notes or replace an edited prompt with a generated
default. The human chat runtime permits up to 24 tool turns for team-wide edits.

Versioned role defaults and specialist procedures are documented in
[prompt architecture v2](PROMPT_ARCHITECTURE_V2.md). Its explicit migration preserves
owner-saved prompts, unmarked native prompt edits, customized local files, and General
directions. Reconciliation seeds absent files and preserves existing native prompts;
changing a repository default is not an implicit migration. The System prompt viewer
shows the native per-turn fragment, not Hermes's complete SOUL/preflight payload.

Execution failures also have inline owner controls. Click the agent's `!` badge
to see **Action needed**, or use the affected job in the project Overview tree.
**Retry task** submits an explicit native retry. For an older failed Hermes run,
**Resolve block** opens the native resolution form: record the verified outcome,
confirm the previous execution has stopped, and choose **Save and continue**.
This preserves prior work and resumes the same task; it does not mark the task
complete or release an owner stop hold. Stale runs, active execution and other
companies remain protected. Draft resolution text survives activity refreshes.

The progress checker respects execution-recovery blocks and records one native
progress-request marker per unchanged work state, preventing repeated idle CEO
wakes. Retry submission IDs persist only until acknowledged: uncertain responses
reuse their ID, while a later deliberate retry gets a new native intent.

Artifact access repairs use the existing `research_sources` tool. With
`action=records`, native receipt discovery is paginated and stays inline. Pass
one assignment-named `issue_ids` reference plus `artifact_id`, `offset` and
`limit` to read the full original text in bounded pages. Sandbox profiles can
also receive a hash-checked copy in their own issue's `inputs` directory. The
reader verifies native company, issue, worker/run attribution, size and SHA-256;
an unfinished source remains unfinished. The completed-sibling acceptance gate
is unchanged. Operator-provisioned copies retain original attachment IDs and
native receipts; approval alone never counts as a completed access repair.
Completion requirements are derived from the handoff's objective and expected
outcome. An available `local_ollama_models` capability or an old correction
mentioning inventory does not turn documentation work into an inventory task;
actual inventory requests still require a successful native inventory read.
Worker status accepts a clear `done` label with harmless punctuation or a scope
caption. Explicit partial, failed or blocked qualifiers still fail, and all
tool-execution, publication and artifact verification requirements remain.

Hermes also freezes complete tool schemas per session. Restarting a runtime
alone preserves an old schema. For an existing idle Research/Security task,
plan its bounded-reader migration with
`python3 -m deploy.migrate_tool_schemas --issue-id <uuid>`, then use `--apply`
and reload that idle runtime before continuation. This uses native SessionDB
tool-pin updates, backs up the old schema, rejects conflicting parameter edits,
and preserves tool names, custom descriptions, prompts and conversation history.
New sessions receive the current registered schema directly. Provider-payload
telemetry records parameter names so activation can be checked at inference time.

The owner can change instructions and names through this panel. Execution tools,
model bindings, employee profiles and existing hiring approvals remain governed
by their runtime configuration. The default prompts favor constructive action
on clear requests and avoid invented authorization rules or unsolicited lectures.

Backend coverage: `tests/test_administration.py`. Browser verification:
`tests/administrator_e2e.cjs`. Its `--apply-setup` option performs the requested
Research-to-OSINT rename and saves the cooperative Direct Chat prompt; the
default run inspects navigation and existing native state without mutating it.

### Additional document access

In the agent column, open a reader-capable employee and expand **Document
permissions**. Select the assignment, source task and file, then choose **Allow
document**. Requested reads also appear in the native approval queue. **Deny**
declines a request and **Revoke** stops subsequent reads through a grant.
The permission binds the employee, assignment, source task, attachment UUID
and native SHA-256. Each page requires a fresh decision check. Previously
delivered text may remain in execution history. These controls cover additional
read access to text documents within the native project. Package installation,
network access and standing profile tools have independent controls.

Workers with a records tool use one source issue and a query of
`request document <attachment UUID>` or `read document <attachment UUID>`.
Requests display the actual source and filename. Owner overrides use a
revision-checked Paperclip document on the receiving task. Updating the document
does not post to the task conversation or start an execution.

Software can use **Document permissions** to receive individual files from a
sibling assignment under the same parent. Its `read_worker_artifacts` tool
verifies the author, producing run and file hash before copying an allowed file
to the receiving assignment’s private `inputs/` directory. This lets a reviewer
check a draft while the author’s task is still open. Revoking a grant stops
future granted reads. Copies already delivered remain in the assignment.

### Approved Debian packages

The operator builds the project image with `python3 deploy/project_cli_service.py --build`
and enables the lifecycle service with `python3 deploy/install-runtime-service.py --projects-only`.
It starts a project when the CEO opens a native mission, reconciles native changes,
and keeps its running container up after successful completion. Archiving or cancelling
the mission stops the container and preserves its volume. The project CLI panel and
Jarvis chat read the current bridge IPv4 address from the lifecycle service.
The Codex sign-in stays in the current app. Worker shell calls carry a signed
assignment identity to the operator and run as UID 1000 inside the project's Kali CLI.

Open a project’s **Overview → Development tools** to approve versions of pytest,
GNU Make, shfmt, gojq or tree for the project. **All listed tools** selects the
whole set. Save once. A terminal-equipped employee on that project can publish
`package-request.json` with `{"package":"python3-pytest"}` and use the returned
`./.jarvis-bin/pytest` to run its own tests. Project grants pin exact executable
hashes. Clearing a grant stops future installations under it. Copies already
installed stay in their assignment. General jobs have their own approval scope.

A worker can request `install package <name>` through its existing approval tool.
Outside a project grant, the three pinned workspace utilities use their existing
assignment approval. The CEO forwards other package requests to the owner.
**Yes** queues APT for that assignment. The package service
also recognizes existing accepted requests. APT resolves exact package names and
dependencies against signed Debian repositories and configures the package offline.

The installed command is available through `./.jarvis-bin/<name>` in the issue
workspace. Every new APT environment supports `--package-version`. Nmap supports
`--version`. jq supports filters on standard input. Each environment runs without
a network or a mount of the project files. Installing a package and authorizing
additional command operations are separate decisions.

The package service verifies the command from the assigned workspace and records
the Debian version, image digest, command output and its SHA-256 on the native
issue. The agent profile and project tree read this receipt. Paperclip continues
to own task status. An unavailable package or failed installation has a recorded
reason and retry time. Closing, hiding or reassigning the job retires its endpoint.

`python3 deploy/install-runtime-service.py --packages-only` installs the `jarvis-approved-packages.timer`
user unit. Its provisioning runs independently of the employee lifecycle service.
