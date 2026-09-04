---
id: BI-011
title: Relationship Persistence and Retrieval Benchmark

source: research/glean-comparison.md
source_insight: >
  Glean uses people, project, content, and activity relationships as relevance
  context, while lee-kb connectors can emit relationship identifiers that are
  not currently persisted or used by retrieval.

opportunity: >
  Determine whether a small, inspectable relationship signal improves personal
  cross-source questions before investing in graph storage, entity inference,
  or personalized ranking infrastructure.

why_now: >
  Outlook and Calendar already expose deterministic relationships, and the
  architecture already claims relationship persistence, creating a bounded gap
  that can be measured with current source types.

minimal_impl: >
  After explicit schema approval, persist connector-emitted typed relationships
  in an additive SQLite migration and build one optional relationship expansion
  experiment over synthetic Outlook, Calendar, and local-document fixtures.
  Compare governed retrieval quality and latency with the expansion disabled
  and enabled; do not add an enterprise graph or model-inferred entities.

definition_of_done:
  - Relationship identity, type, direction, source item, target, provenance, update, and deletion semantics are documented and enforced.
  - An additive migration persists current connector relationships without changing ordinary lexical results when expansion is disabled.
  - Permission evaluation applies independently to every expanded target and prevents relationship identifiers from disclosing denied source identity.
  - A synthetic benchmark measures hit-at-k, latency, duplicate rate, and false expansion for at least one thread, event-attendee, and project-reference question family.
  - The result records a go, revise, or stop decision for relationship-assisted retrieval; it does not assume a graph database.
  - Existing retrieval receipts identify the evidence actually released, not merely the relationship path used to find it.

effort: L
build_recipe: builder_safe
priority: someday

dependencies:
  - BI-001
  - External: Explicit approval for the additive persisted relationship schema

risks: >
  Relationship expansion can leak restricted entity names, create popularity
  bias, amplify noisy links, and add graph complexity without measurable recall.

mitigations: >
  Use source-declared relationships only, evaluate authorization on targets,
  keep expansion optional and bounded, preserve the lexical baseline, and stop
  if the synthetic benchmark shows no material gain.

tags:
  - relationships
  - retrieval
  - benchmark
  - permissions

status: candidate
created_at: 2026-08-11T19:29:15Z
created_by: OhMyPi-GleanReview
token_cost: 0
approved_at: ~
approved_by: ~
notes: ~
implemented_at: ~
implemented_by: ~
pr_url: ~
---

# Additional Context

This is deliberately smaller than Glean's Enterprise Graph. Personal graphs,
activity-based personalization, machine-learned entity inference, graph
databases, and enterprise multi-hop orchestration are excluded until evidence
from this benchmark justifies another candidate.

Public pattern source:

- https://www.glean.com/enterprise-context/enterprise-graph
