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
is involved. Lexical matching ORs the query's content tokens (stopwords
stripped) and ranks by BM25, so paraphrase questions score by vocabulary
overlap rather than requiring every token to co-occur; the strict AND mode
remains available as `match="all"`. Positive questions are natural-language
paraphrases that reuse document word-forms (FTS5 does not stem), not pasted
extracts.

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
| operational-04 | Operational status | `architecture.md` | Hit | 2 |
| project-management-01 | Project management | `project-plan.md` | Hit | 1 |
| project-management-02 | Project management | `project-plan.md` | Hit | 1 |
| project-management-03 | Project management | `backlog/schema.md` | Hit | 2 |
| project-management-04 | Project management | `backlog/schema.md` | Hit | 4 |
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
- Expected-citation hit rate at 1: **16/20 (80.0%)**.
- Mean reciprocal rank: **0.888**.
- Negative controls: **3/3 correct**.
- Unauthorized candidates released: **0**; denied candidates observed: **3**.

Semantic or hybrid retrieval must beat the lexical rank-quality baseline
(80.0% hit-at-1 and 0.888 MRR) on Lee's curated corpus without reducing
top-10 recall or weakening project and authorization controls. The seed set's
100% hit-at-10 is saturated and is therefore not, by itself, evidence of a
semantic improvement. An earlier revision of this corpus used extract-style
questions and reported 85.0% hit-at-1 / 0.925 MRR; that figure flattered the
matcher (S1-R-11) and was re-recorded against paraphrase questions.

## Boundaries and audit semantics

This checkout contains facts about the deployed `jobsearch` source root but no
application or follow-up records. The four job-search questions therefore test
discoverability of the available corpus metadata, not real application
workflow coverage. Lee's curated replacement must supply genuine recurring
application questions and authoritative sources.

`RetrievalReceipt` records one released evidence item. For the no-evidence and
scoped-empty cases, `retrieve()` consequently returns zero item receipts rather
than fabricating a citation. The repository also persists a
`RetrievalAuditEvent` containing the query, principal, retrieval timestamp,
candidate count, denial count, release count, truncation, and outcome status.
This covers empty, fully denied, mixed permitted/denied, stale-refused, and
provider-failure results without exposing restricted source identity.


## Curated operator benchmark — 2026-08-09

The curated benchmark now runs through both `retrieve()` and deterministic
`answer()` without copying its question text or source pointers into this
public repository. `tools/run_curated_benchmark.py` reads the operator-maintained
question set at runtime, selects the stable commercial, strategy, product, and
platform sections, copies the SQLite projection with the SQLite backup API, and
queries only the copy. Output contains aggregate metrics and opaque case IDs.

The current operator run selected **20** cases against a projection of **1,314
live items and 20,438 chunks**. Fifteen expected source objects were present in
the projection; five were outside the configured projection scope and are
reported as source-missing rather than counted as retrieval hits.

| Surface / metric | Result |
|---|---:|
| `retrieve()` expected-source hit at 1 | 2/15 (13.33%) |
| `retrieve()` expected-source hit at 10 | 6/15 (40.00%) |
| `answer()` expected-source citation | 6/15 (40.00%) |
| `answer()` claims assembled | 139 |
| `answer()` conflicts reported | 103 |
| Retrieval failures | 0 |
| Answer failures | 0 |
| No-evidence control | `NOT_FOUND` |
| Unauthorized control | `INACCESSIBLE` |
| Strict-freshness control | `STALE_REFUSED` |

This is the first real-corpus baseline, not a quality pass: the low
expected-source recall and the five out-of-scope pointers identify the next
retrieval and source-scope investigations. The generated seed baseline above
remains the portable regression contract; this operator benchmark is
intentionally local because publishing real question text or source locators
would violate the repository disclosure rule.