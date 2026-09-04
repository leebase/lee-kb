---
id: BI-010
title: Mixed Indexed and Live Evidence Benchmark

source: research/glean-comparison.md
source_insight: >
  The useful structured-data experience combines current quantitative results
  with indexed qualitative context while keeping each source's authority and
  permission boundary visible.

opportunity: >
  Verify that one lee-kb answer can combine a live metric with documents, mail,
  or other synchronized knowledge without flattening different timestamps,
  citations, omissions, or failure modes into unsupported prose.

why_now: >
  This is the observable product outcome behind structured-data demand, but it
  should be attempted only after the live evidence contract works independently.

minimal_impl: >
  Extend the permanent synthetic answer benchmark with one question that needs
  both a BI-009 local structured result and ordinary indexed evidence. Preserve
  the two acquisition modes through evidence selection, claim assembly,
  citations, freshness reporting, receipts, conflicts, and provider failure.

definition_of_done:
  - A synthetic user journey cannot be answered completely by either indexed or live evidence alone.
  - The answer cites both evidence modes and reports source, query or synchronization, and retrieval timestamps without inventing one shared freshness value.
  - Receipts and query audit events close for both released paths and no denied evidence reaches claim assembly.
  - Conflicting structured and unstructured statements remain separate evidence and do not gain a heuristic winner.
  - Live timeout, denial, empty result, and provider failure produce an incomplete or UNKNOWN answer rather than a deterministic substitute presented as current data.
  - The benchmark fails when the live result is silently cached as an authoritative synchronized item or when indexed prose is used as a current metric.

effort: M
build_recipe: builder_safe
priority: someday

dependencies:
  - BI-009

risks: >
  A mixed answer path could hide partial failure, compare facts measured at
  different times, or let polished synthesis overstate a weak semantic query.

mitigations: >
  Keep acquisition mode and timestamps explicit, reuse conflict and omission
  contracts, fail closed on missing live evidence, and benchmark only synthetic
  bounded data before any external provider.

tags:
  - structured-data
  - answers
  - benchmark
  - provenance

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

This candidate measures the integrated user contract. It does not add natural-
language-to-SQL, an external provider, background refresh, or write actions.
