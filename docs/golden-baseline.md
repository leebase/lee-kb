# Golden Corpus Lexical Baseline

This is the deterministic, offline Sprint 1 seed baseline. The seed corpus is
drawn from this repository's real product, architecture, planning, research,
and backlog documents. It proves the evaluation harness; it is not Lee's
curated golden benchmark. Lee must replace or refine these twenty prompts with
recurring Chief of Staff questions against the Employee Zero source corpus.

## Method

`tests/golden/test_golden_corpus.py` uses the local-file connector to ingest the
declared Markdown sources into a temporary SQLite projection, chunks them with
the production deterministic chunker, and sends every question through
`governance.retrieve()`. No network, model, embedding, or mutable shared index
is involved.

A positive question is a **hit** when its declared source and evidence token
occur in the governed top-10 evidence. Rank is the first matching citation's
lexical rank. Negative controls pass only when governed retrieval returns no
evidence; the scope and authorization controls first prove that matching
source evidence exists outside the permitted path.

## Per-question results

| ID | Category | Expected source | Result | Rank |
|---|---|---|---:|---:|
| operational-01 | Operational status | `product-definition.md` | Hit | 1 |
| operational-02 | Operational status | `product-definition.md` | Hit | 1 |
| operational-03 | Operational status | `architecture.md` | Hit | 1 |
| operational-04 | Operational status | `architecture.md` | Hit | 1 |
| project-management-01 | Project management | `project-plan.md` | Hit | 1 |
| project-management-02 | Project management | `project-plan.md` | Hit | 2 |
| project-management-03 | Project management | `backlog/schema.md` | Hit | 1 |
| project-management-04 | Project management | `backlog/schema.md` | Hit | 2 |
| architecture-01 | Architecture | `architecture.md` | Hit | 1 |
| architecture-02 | Architecture | `architecture.md` | Hit | 2 |
| architecture-03 | Architecture | `architecture.md` | Hit | 1 |
| architecture-04 | Architecture | `architecture.md` | Hit | 1 |
| job-search-01 | Job search | `research/employee-zero-kb-reference.md` | Hit | 1 |
| job-search-02 | Job search | `research/employee-zero-kb-reference.md` | Hit | 1 |
| job-search-03 | Job search | `research/employee-zero-kb-reference.md` | Hit | 1 |
| job-search-04 | Job search | `research/employee-zero-kb-reference.md` | Hit | 1 |
| knowledge-discovery-01 | Knowledge discovery | `product-definition.md` | Hit | 1 |
| knowledge-discovery-02 | Knowledge discovery | `product-definition.md` | Hit | 1 |
| knowledge-discovery-03 | Knowledge discovery | `product-definition.md` | Hit | 1 |
| knowledge-discovery-04 | Knowledge discovery | `architecture.md` | Hit | 1 |
| negative-no-evidence | No corpus evidence | None | Pass: empty | — |
| negative-out-of-scope | Project scope | `docs/project-onboarding.md` in `scope-control` | Pass: empty | — |
| negative-unauthorized | Authorization | `product-definition.md`, private to `lee` | Pass: denied | — |

## Baseline

- Expected-citation hit rate at 10: **20/20 (100.0%)**.
- Expected-citation hit rate at 1: **17/20 (85.0%)**.
- Mean reciprocal rank: **0.925**.
- Negative controls: **3/3 correct**.
- Unauthorized candidates released: **0**; denied candidates observed: **1**.

Semantic or hybrid retrieval must beat the lexical rank-quality baseline
(85.0% hit-at-1 and 0.925 MRR) on Lee's curated corpus without reducing
top-10 recall or weakening project and authorization controls. The seed set's
100% hit-at-10 is saturated and is therefore not, by itself, evidence of a
semantic improvement.

## Boundaries and audit semantics

This checkout contains facts about the deployed `jobsearch` source root but no
application or follow-up records. The four job-search questions therefore test
discoverability of the available corpus metadata, not real application
workflow coverage. Lee's curated replacement must supply genuine recurring
application questions and authoritative sources.

Sprint 1 `RetrievalReceipt` records one released evidence item. For the
no-evidence and scoped-empty cases, `retrieve()` consequently returns zero item
receipts rather than fabricating a citation. The returned `EvidenceBundle`
still retains the query, principal, project, retrieval timestamp, freshness
result, and denial count as the empty query's audit envelope. A separately
persisted query-level receipt would require a future contract change outside
this harness's write scope.
