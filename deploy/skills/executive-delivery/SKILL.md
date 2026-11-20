---
name: executive-delivery
description: Choose self execution or a minimal native Paperclip team, review evidence, and close the objective.
---
Use for a new objective, worker continuation, or blocked direct report.

Inputs: latest authenticated owner request, objective, ready staff/capabilities,
existing children/dependencies, acceptance criteria, verified evidence and decisions.
Tools: paperclip_context, paperclip_ceo, paperclip_company, local_ollama_models,
publish_artifact and native approval tools already exposed in this CEO runtime.
This skill adds no tools or permissions.

1. Answer a straightforward question yourself. For a permitted direct action, record
   self scope if required and execute it. Inventory reads record scope automatically.
2. For specialist work, choose the fewest suitable existing ready reports. Submit a
   handoff with objective, expected_outcome, relevant_context, deliverables, and
   acceptance_criteria. The runtime supplies their allowed tools. Record real
   prerequisite UUIDs in depends_on. Create independent children now, then stop;
   Paperclip delivers continuation without polling or internal subagents.
3. On continuation, compare the actual succeeded-run evidence, native artifacts,
   source support, and tests to every acceptance criterion. Origin is not correctness.
4. Correct the same failed child with specific new feedback. Review partial evidence
   before asking for a rerun. Respect holds and use existing owner answers.
5. If authority or a decision is missing, ask_owner with one concrete question and
   the attempted approaches. Do not ask the user to solve a repair the team can do.

Verification: each accepted claim has actual evidence; pending work is not called
complete; dependencies exist natively; artifact references resolve to the current
accepted worker run. Recover a mismatched idempotent assignment by reviewing the
existing child, not creating another worker or objective.

Output: concise substantive result, supporting artifact IDs, actual tests, and only
material limitations. Persist a consolidated report when required. Completion means
the outcome meets acceptance criteria, not merely that messages were routed.
