# Glean comparison and structured-data implications

**Reviewed:** 2026-08-11  
**Scope:** Compare the user-supplied Glean crash course with lee-kb's current product and architecture, validate the decision-relevant public claims, and identify candidate work. This is research, not roadmap approval.

## Evidence boundary

### Observed in public Glean sources

- Glean connectors fetch content and permission maps, parse source objects, and keep an indexed tenant projection current. Glean documents indexed, live, and hybrid connector access modes.
- Glean distinguishes connectors, which normally index content, from tools, which call source applications at query time to read live data or perform writes.
- Glean states that raw structured warehouse datasets such as Snowflake and Databricks are not indexed. Warehouse data stays in the source; tools retrieve it dynamically using metadata and context.
- Glean's Snowflake Cortex Agent tool calls an existing, customer-managed Cortex Agent and is read-only at the Glean tool boundary. The Snowflake agent may use Cortex Search and text-to-SQL over resources permitted to its configured role.
- Glean's Google Cloud tools query BigQuery live without an additional index. User OAuth preserves caller permissions; a service credential is an explicit alternative. The documented SQL path is read-only, and the natural-language paths have preview, timeout, truncation, scope, and statelessness limitations.
- Glean's Enterprise Graph uses connector content, metadata, entities, relationships, activity signals, and personal work patterns to support personalization and multi-hop reasoning.
- Glean tools have a separate execution-governance surface: admins select available tools, users can require per-call approval for writes, and tool usage is logged.

### Not treated as verified product requirements

- Exact model counts, market-share numbers, competitive claims, and the commercial conclusions in the supplied course were not needed for this comparison and were not independently validated.
- The supplied client examples and internal partner notes are confidential business context, not public evidence. Names, source details, and deal-specific claims are intentionally not copied into this public repository.
- A public vendor description establishes product behavior, not independent proof of result quality, permission correctness, or operational reliability in a particular deployment.

## Comparison

| Dimension | lee-kb today | Glean pattern | Implication |
|---|---|---|---|
| Product scope | Personal-first Second Brain; small shared projects later; no enterprise control plane | Enterprise-wide search, assistant, agents, administration, and many integrations | Do not copy Glean's deployment shape. Preserve SQLite and the personal release. |
| Source authority | Original source remains authoritative; SQLite is a disposable projection | Connected applications remain sources while indexed content is held in a tenant environment | Strong alignment. |
| Indexed knowledge | Local files, Office files, Outlook mail, and Calendar normalize to items and chunks | Connectors index documents, messages, metadata, permissions, and activity | Strong alignment in connector and projection principles; lee-kb is intentionally narrower. |
| Authorization | Fail-closed principal evaluation occurs before evidence release and before synthesis | Source permissions are mirrored for indexed search; live tools use configured user or service identity | Same headline goal. lee-kb has explicit release receipts and query audit events, but does not yet mirror general source ACL changes. |
| Evidence governance | Citations, source/sync/retrieval timestamps, freshness, per-evidence receipts, and query audit events are public contracts | Permission-aware results, references, connector freshness, and tool logs are platform controls | lee-kb should retain its stronger explicit evidence contract when adding any live path. |
| Answers | Deterministic claim assembly; optional source-bounded narration; failures become `UNKNOWN` | Assistant plans, retrieves, analyzes, creates artifacts, and invokes tools | lee-kb deliberately keeps evidence authority outside the model and execution authority outside the product. |
| Structured data | Product language lists database rows, Snowflake, and SQL databases as normalizable knowledge, but no warehouse access path exists | Raw warehouse datasets are normally queried live through tools; metadata or semantic assets provide context | This is the main unresolved architectural choice. Treating warehouse rows like documents by default would create duplication, freshness, cost, and authorization problems. |
| Semantic layer | No semantic-asset contract exists | Warehouse-native agents, semantic models, views, and configured context carry business meaning | Do not build a reusable lee-kb semantic layer now. If structured analytics become concrete, prefer Snowflake-native semantic models or agents and add only the smallest governed adapter. |
| Relationships | Connectors can emit relationship identifiers; architecture says the repository stores relationships, but current ingestion does not persist or retrieve them | Enterprise and personal graphs are core relevance and reasoning inputs | Benchmark a small relationship signal before building graph infrastructure. |
| Live versus indexed access | Retrieval is projection-first; synchronous connector refresh is opt-in, not a live query provider | Indexed, live, and hybrid access are explicit modes | Add no hidden live call to `retrieve()`. If approved, live structured evidence needs an explicit request, timeout, identity, freshness, and receipt boundary. |
| MCP | Thin stdio MCP surface exposes governed lexical evidence and status | MCP can expose permission-aware knowledge and data-analytics tools to external hosts | Existing MCP is a useful delivery surface, but it should not gain live query or write authority before the library contract exists. |
| Actions | Explicit non-goal: lee-kb is not an execution or workflow engine | Read and write tools support agent workflows | Keep write actions, ticket creation, messages, and workflow automation out of lee-kb. Agent-Orch remains the execution authority. |

## Product conclusion

Glean validates lee-kb's central direction: connect rather than migrate, preserve source authority, normalize cross-source evidence, enforce access before model use, and make retrieval useful to both people and agents.

The useful divergence is equally important. lee-kb should not become a smaller enterprise Glean. Its defensible shape is a local, inspectable evidence service with explicit provenance, freshness, receipts, and failure states. The operator expects to use Snowflake if structured analytics become necessary, so a generic database semantic layer is lower priority. The transferable lesson is only the boundary: keep volatile analytical facts authoritative in Snowflake rather than copying them into document chunks by default.

No architecture change is approved by this research. BI-007 remains an optional planning guardrail before any Snowflake work; it does not imply that lee-kb should build a semantic catalog, natural-language-to-SQL layer, or general database platform.

## Candidate sequence

1. **BI-007 — Structured Data Access Boundary (`next`, planning only):** retain a small governance decision before any Snowflake integration; do not build a database platform.
2. **BI-012 — Source Permission Change Conformance (`next`):** prove source ACL-only changes and revocations update the projection without content changes or leakage.
3. **BI-008 — Semantic Asset Manifest and Readiness Validator (`someday`):** revisit only if a concrete Snowflake use case cannot rely on Snowflake-native semantic objects.
4. **BI-009 — Governed Structured Query Contract and Offline Proof (`someday`):** retain as a fallback proof behind BI-007 and BI-008, not a near-term platform investment.
5. **BI-010 — Mixed Indexed and Live Evidence Benchmark (`someday`):** integrate only after a real governed live-query need exists.
6. **BI-011 — Relationship Persistence and Retrieval Benchmark (`someday`):** measure a bounded relationship signal without pursuing a Glean-style graph.

BI-008 through BI-010 are explicitly deprioritized. A future Snowflake path should first reuse Snowflake's native semantic and query facilities, then add only the lee-kb permission, provenance, freshness, receipt, and audit adapter that a concrete use case requires. None of these candidates authorizes a production connection, external data transmission, write action, enterprise graph, multi-tenant control plane, or new runtime dependency.


## Public references

- [Glean data flow and structured-data boundary](https://docs.glean.com/security/architecture/data-flow)
- [Glean connector responsibilities and indexed/live/hybrid modes](https://docs.glean.com/connectors/about)
- [Glean tools overview and execution governance](https://docs.glean.com/tools/tools-overview)
- [Glean Snowflake Cortex Agent tool](https://docs.glean.com/tools/connector/snowflake/query-snowflake-cortex-agent)
- [Glean Google Cloud and BigQuery tools](https://docs.glean.com/tools/connector/googlecloud)
- [Glean Enterprise Graph](https://www.glean.com/enterprise-context/enterprise-graph)
