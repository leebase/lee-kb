---
id: BI-006
title: Personal Corpus Scalability Baseline

source: user-request
source_insight: The current personal corpus is measured, but connector expansion could change sync and retrieval costs substantially.

opportunity: Identify the first real bottlenecks before continuous email or multiple connector instances make performance assumptions expensive to change.

why_now: The current projection has 1,235 documents and 18,601 chunks; the roadmap includes larger local and external personal sources.

minimal_impl: Build a reproducible synthetic scaling benchmark that records document/chunk counts, database size, full and incremental sync duration, peak memory, retrieval latency, and answer latency at useful personal-scale points without replacing storage or indexing.

definition_of_done:
  - Baseline results are recorded for the current corpus shape and synthetic 10,000-document and 100,000-document projections.
  - Full versus incremental sync costs and peak memory are measured separately.
  - Retrieval and deterministic answer latency are measured separately from synchronization.
  - Risks and thresholds for connector expansion are documented without claiming production capacity.

effort: M
build_recipe: builder_safe
priority: next

dependencies:
  - BI-001

risks: Synthetic data may misrepresent email and Office content, and premature optimization may expand scope.

mitigations: Preserve the current implementation as the baseline, label synthetic results clearly, and use measurements to prioritize only demonstrated bottlenecks.

tags:
  - performance
  - scalability
  - personal-second-brain

status: candidate
created_at: 2026-08-05T00:00:00Z
created_by: OpenCode
token_cost: 0
approved_at: ~
approved_by: ~
notes: ~
implemented_at: ~
implemented_by: ~
pr_url: ~
---

# Additional Context

This item is a measurement slice, not a mandate to add PostgreSQL, a service,
or enterprise deployment infrastructure.
