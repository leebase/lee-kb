---
id: BI-009
title: Governed Structured Query Contract and Offline Proof

source: research/glean-comparison.md
source_insight: >
  Structured facts can remain authoritative in their source and be retrieved
  live through a read-only provider instead of being copied into a document
  index.

opportunity: >
  Prove lee-kb can release live analytical evidence with the same explicit
  permission, provenance, freshness, receipt, audit, and failure guarantees as
  indexed evidence before connecting to an external warehouse.

why_now: >
  This is not current work. Retain the offline proof only as a fallback if
  BI-007 finds that a direct, governed adapter over Snowflake-native querying
  cannot satisfy lee-kb's evidence contracts.

minimal_impl: >
  Implement the approved BI-007 contract with one real local SQLite read-only
  provider over a synthetic semantic view declared by BI-008. Requests select
  an approved operation and typed parameters; they do not accept arbitrary SQL.
  Results become bounded live Evidence and durable receipts without creating
  synchronized KnowledgeItems or permitting writes.

definition_of_done:
  - A provider-neutral request and result contract requires principal, project, semantic asset, approved operation, typed parameters, timeout, and result bound.
  - The local provider enforces SQLite read-only mode and rejects arbitrary SQL, write statements, unknown assets, unknown operations, and unbounded requests.
  - Released rows have stable result identity, source and semantic-asset provenance, query timestamp, source freshness when available, and a resolvable citation or locator.
  - Permission denial occurs before provider execution, and empty, denied, timed-out, truncated, and provider-failed outcomes produce explicit query audit facts.
  - Every released evidence result has receipt closure; provider diagnostics and result values do not leak into metadata-only audit records.
  - A command or library smoke scenario executes the synthetic read path end to end with no network, credential, model, or new runtime dependency.

effort: L
build_recipe: builder_safe
priority: someday

dependencies:
  - BI-007
  - BI-008
  - External: Explicit approval for any additive public API or persisted receipt schema

risks: >
  Live querying can introduce SQL injection, data exfiltration, expensive or
  long-running scans, unstable results, and confusion between source access and
  lee-kb retrieval authorization.

mitigations: >
  Start with approved operations and typed parameters, a synthetic local view,
  pre-execution permission checks, read-only database enforcement, strict row
  and time bounds, fail-closed errors, and no arbitrary SQL surface.

tags:
  - structured-data
  - live-evidence
  - security
  - receipts

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

External warehouse connections are deliberately excluded. This candidate is
lower priority because a direct Snowflake-native route may make the generic
local provider proof unnecessary; revisit it only for a concrete gap.


Public examples of the source-side pattern:

- https://docs.glean.com/tools/connector/snowflake/query-snowflake-cortex-agent
- https://docs.glean.com/tools/connector/googlecloud
