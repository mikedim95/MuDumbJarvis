# Administrator

Open **General** and choose a conversation in the left sidebar. The original
Administrator history appears under **General chat**. To change a prompt,
open **Context**, select the agent or chat, expand **System prompt**, and send
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

The owner can change instructions and names through this panel. Execution tools,
model bindings, employee profiles and existing hiring approvals remain governed
by their runtime configuration. The default prompts favor constructive action
on clear requests and avoid invented authorization rules or unsolicited lectures.

Backend coverage: `tests/test_administration.py`. Browser verification:
`tests/administrator_e2e.cjs`. Its `--apply-setup` option performs the requested
Research-to-OSINT rename and saves the cooperative Direct Chat prompt; the
default run inspects navigation and existing native state without mutating it.
