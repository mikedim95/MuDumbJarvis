---
name: isolated-development
description: Inspect, implement, and verify a minimal software change in the assigned private workspace.
---
Use for code changes, reproducible demonstrations, and failed-test repairs.
Inputs: available source artifacts, objective, dependencies, interfaces, acceptance
criteria, and actual sandbox toolchain. Tools: read_worker_artifacts, read_file,
write_file, patch, terminal, publish_artifact. No host checkout or network access.

1. Discover completed sibling receipts with read_worker_artifacts({}); select an
   artifact_id. Read bounded pages until next_offset is null, or inspect its complete
   hash-checked workspace_path with read_file/terminal. Never read runtime spill files.
2. Inspect existing architecture and reproduce the relevant behavior. Sketch the
   smallest change and useful acceptance checks; preserve unrelated code.
3. Implement in the current issue workspace using explicit paths and foreground
   commands. Use single-file patch replacement. Keep command output bounded.
4. Run meaningful executable tests. Python unittest is installed; do not assume
   pytest. Inspect actual stdout/stderr and exit code. Diagnose failures before
   changing code, then rerun affected tests and relevant edge cases.
5. Publish changed source/config, tests and results. A task-relative or absolute path
   must refer to a real file in this issue's private workspace.

Verification: requested behavior and failure paths are exercised; no test assertions
are removed to conceal failures; source/config/results are persisted natively.
If promptfoo is explicitly required, use the installed offline echo provider with
deterministic assertions: promptfoo eval -c config.json --no-cache --no-write
--max-concurrency 1 --output results.json. No remote generation or model grading.
The isolation_checks.py operator fixture verifies sandbox controls, not application logic.

Recovery: inspect missing paths, tool schema or exact test failures. Reuse valid
existing files on correction. After two distinct unsuccessful approaches, report the
cause and preserved evidence to the CEO. Do not install tools or invent test results.

Output: the six standard completion fields, verified artifact IDs, actual test totals
and limits. Clearly label sandbox demonstration, integration, and deployment status.
