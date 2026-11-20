---
name: scoped-administration
description: Diagnose operational failures using bounded observations and reversible sandbox checks.
---
Use for reliability questions, dependency failures, resource issues, or an operational
change proposal. Inputs: exact symptom, affected environment, allowed scope, available
observations, desired state, acceptance criteria and rollback constraints.
Tools: terminal in the assigned isolated sandbox, local_ollama_models for model
metadata, publish_artifact, request_action_approval. No host or Docker access.

1. Identify where each observation comes from. Container routes/processes/limits
   describe the sandbox; model metadata describes the inventory endpoint.
2. Collect the minimum useful baseline. Form a falsifiable hypothesis and a bounded
   diagnostic separating it from alternatives. Inspect actual output and exit status.
3. Confirm or revise the hypothesis. Avoid dumping unrelated inventory or interpreting
   a sandbox limitation as a host fault.
4. Make a small reversible change only when authorized inside the sandbox. Capture
   before/after state. Otherwise publish an operator proposal with exact change,
   prerequisites, expected effect, impact, verification and rollback.
5. Validate the observed or proposed outcome against the acceptance criteria. Request
   native approval when needed; the request itself does not execute the change.

Verification: evidence supports the cause, the environment is labeled, actual changes
have before/after checks, and a proposed host fix is never described as deployed.
Recovery: refine the hypothesis using the actual failure; revert a failed permitted
intervention. After two distinct unsuccessful approaches preserve diagnostics and
send the CEO the unresolved cause and specific missing access/input.

Output: the six standard completion fields, diagnosis and evidence artifact IDs,
and a concise proposal/rollback where needed. Completion requires actual scoped
verification or a clearly labeled requested proposal, not an unsupported service claim.
