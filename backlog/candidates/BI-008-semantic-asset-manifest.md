---
id: BI-008
title: Semantic Asset Manifest and Readiness Validator

source: research/glean-comparison.md
source_insight: >
  Correct conversational analytics depends on an approved semantic layer and
  operational context, not merely on technical connectivity to raw tables.

opportunity: >
  If a future Snowflake use case cannot rely directly on Snowflake-native
  semantic objects, provide a reusable, reviewable description of what may be
  queried and which security and cost limits apply.

why_now: >
  This is deliberately not current work. lee-kb is likely to use Snowflake and
  should prefer Snowflake-native semantic facilities; retain this candidate only
  if a concrete use case proves that a separate lee-kb manifest is necessary.

minimal_impl: >
  Add a versioned, secret-free manifest and deterministic validator for one
  synthetic semantic asset. The manifest identifies an approved view, model,
  dataset, or dashboard and records business metadata, ownership, principal
  policy, authentication mode reference, freshness target, query limits, and
  supported question shapes. It does not contain credentials, raw customer
  data, arbitrary executable SQL, or a network client.

definition_of_done:
  - The manifest schema covers stable asset identity, provider kind, source locator, owner, description, dimensions, measures, supported question shapes, allowed principals or groups, and authority.
  - Operational fields cover freshness target, timeout, row limit, cost or workload guard, and non-secret authentication-mode reference.
  - Validation rejects missing ownership, ambiguous asset identity, write-capable modes, unbounded result policy, credentials, and unsupported schema versions.
  - A synthetic example and focused tests prove deterministic parsing and safe diagnostics without adding a runtime provider dependency.
  - Documentation explains how the manifest differs from source data, a connector configuration, and a model prompt.

effort: M
build_recipe: builder_safe
priority: someday

dependencies:
  - BI-007

risks: >
  The manifest could become an unbounded semantic-modeling language or a place
  where secrets and customer business logic are accidentally committed.

mitigations: >
  Keep v1 declarative and metadata-only, reject executable content and secret
  fields, use a synthetic fixture, and defer provider-specific extensions until
  a real approved integration needs them.

tags:
  - structured-data
  - semantic-layer
  - configuration
  - governance

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

This is not a prerequisite for a Snowflake-native integration and must not grow
into a generic database semantic layer. Revisit it only when a concrete use
case demonstrates missing governance metadata that Snowflake cannot supply.

