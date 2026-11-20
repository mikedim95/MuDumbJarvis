---
name: source-research
description: Resolve a technical research question using reusable evidence and primary sources.
---
Use for technical discovery, comparisons, existing-evidence handoffs, and recurring
research updates. Inputs: scoped question, decision to support, required coverage,
named prior records, source/version constraints, deliverable format and criteria.
Tools: research_sources, local_ollama_models for an assigned inventory question,
and publish_artifact. No shell or external writes are available.

1. Check relevant prior material: action=knowledge for reusable catalogs;
   action=records with explicitly assigned issue identifiers for a handoff.
2. List gaps. On recurring jobs, seek new versions, changed guidance, contradictions,
   or missing coverage rather than copying the old report.
3. Discover with action=search; fetch selected primary URLs with action=fetch (up to
   six per call). Inspect returned dates, versions, source text, and retrieval errors.
4. Compare documented capabilities, prerequisites, limits, and evidence quality.
   Resolve contradictions against the current original documentation. State unknowns.
5. Publish concise findings and, when assigned, a validated cumulative catalog.
   Use the existing preserve_previous mechanism to retain valid entries. Propose
   additions with scope and validation level; do not silently make them trusted memory.

Verification: every consequential claim is supported by fetched or explicitly reused
source evidence. Documentation is labeled documented_only/actually_tested=false;
reading a source never counts as running its software. Video descriptions are not
transcripts. Check catalog coverage and the actual publish receipt.

Recovery: inspect the exact schema/error; correct a URL or use another authoritative
source. Do not refetch an inaccessible URL unchanged or claim unavailable access
without trying the currently authorized record lookup. Report remaining gaps.

Output: STATUS, RESULT, VERIFIED EVIDENCE, ARTIFACT REFERENCES, LIMITATIONS,
REMAINING BLOCKERS. Include practical recommendations, source URLs and only the
new findings needed by the CEO; full source artifacts remain authoritative.
