---
id: BI-007
title: Structured Data Access Boundary

source: research/glean-comparison.md
source_insight: >
  Glean separates indexed knowledge from live structured-data tools, while
  lee-kb currently names database rows as normalized knowledge without defining
  when warehouse data should be indexed or queried live.

opportunity: >
  Establish a narrow indexed-versus-live governance boundary before any
  optional Snowflake integration commits lee-kb to raw-row duplication or
  hidden query-time calls.

why_now: >
  This is a planning guardrail only: if Snowflake work is selected later, the
  source-authority and evidence boundaries should be decided before provider
  code. It does not make structured analytics a current product priority.

minimal_impl: >
  Produce an approval-ready architecture decision that classifies structured
  artifacts, defines explicit indexed versus live responsibilities, and sketches
  a read-only governed evidence contract with identity, provenance, freshness,
  timeout, cost, receipt, audit, and failure semantics. Do not implement a
  provider or change a persisted schema in this item.

definition_of_done:
  - A decision matrix classifies files, warehouse rows, query results, semantic models, dashboards, and metadata as indexed, live, hybrid, or unsupported by default.
  - The proposed live-read boundary cannot run implicitly inside ordinary projection-only retrieval and cannot authorize writes.
  - Permission identity, source attribution, query timestamp, result freshness, receipt closure, audit facts, timeouts, row limits, and provider failures have explicit semantics.
  - The decision explains how a live result can become normalized Evidence without pretending it is a synchronized KnowledgeItem.
  - Alternatives include raw-row ingestion, warehouse-native querying, and metadata-only indexing, with personal-release costs and risks.
  - Any public API or persisted-schema change remains an explicit human approval gate.

effort: M
build_recipe: planner_only
priority: next

dependencies:
  - External: Human approval of the structured-data architecture decision

risks: >
  A premature abstraction could leak execution authority into retrieval, hide
  external latency and cost, or overfit one vendor's semantic layer.

mitigations: >
  Keep the decision provider-neutral, read-only, explicit per request, and
  compatible with the current SQLite personal profile; require fail-closed
  permission, provenance, freshness, receipt, and audit semantics.

tags:
  - structured-data
  - architecture
  - governance
  - personal-second-brain

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

This candidate adopts one boundary observed in Glean, not Glean's enterprise
platform. The expected structured-data direction is Snowflake-first: reuse
Snowflake-native semantic and query facilities, then add only the smallest
governed lee-kb adapter a concrete use case requires. Write tools, a lee-kb
semantic platform, agent workflows, enterprise tenancy, and production
warehouse connections are excluded.


Public evidence:

- https://docs.glean.com/security/architecture/data-flow
- https://docs.glean.com/connectors/about
- https://docs.glean.com/tools/tools-overview
