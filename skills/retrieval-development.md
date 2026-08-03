# Skill: Retrieval Development

> Use this skill when designing or implementing search, evidence, freshness, or receipts.

## Retrieval order

The minimum governed pipeline is:

```text
question → permission evaluation → metadata filters → lexical retrieval
→ ranking → freshness evaluation → evidence bundle → citations → receipt
```

Semantic search, reranking, context expansion, and LLM synthesis are later
providers or consumers. They must not weaken the permission or provenance path.

## Evidence requirements

Every evidence item should retain:

- stable knowledge-item and chunk IDs
- original source reference
- source timestamp and synchronization timestamp
- retrieval timestamp
- permission decision or applicable principal
- retrieval score and ranking reason where available
- enough context to inspect the original source

The evidence bundle must distinguish authoritative current information from
historical context and report uncertainty when freshness or conflicts matter.

## Provider boundaries

Define interfaces for lexical search, semantic search, reranking, and
persistence. The first implementation may use SQLite and lexical search, but
retrieval consumers should depend on the interface rather than its backend.

## Receipt requirements

A retrieval receipt should make the request auditable: who or what asked,
when it was evaluated, which filters and permissions applied, which evidence
was selected, what freshness status was observed, and which source references
were returned. Do not store more source content than the product requires.

## Verification

Test exact terms, empty results, duplicate chunks, denied items, stale items,
changed source content, conflicting timestamps, deterministic ranking, and
receipt creation. Confirm no unauthorized evidence reaches the evidence bundle.
