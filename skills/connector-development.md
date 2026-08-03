# Skill: Connector Development

> Use this skill when designing or implementing a source connector or ingestion path.

## Required contract

Every connector must make these responsibilities explicit:

- `discover()` — identify source objects and stable source IDs
- `list_changes()` — return new, changed, and deleted objects from a cursor or snapshot
- `fetch()` — retrieve source content and source timestamps
- `permissions()` — expose authorization metadata for each object
- `relationships()` — expose useful source relationships when available
- `refresh()` — perform targeted refresh when freshness requires it
- `health()` — report connectivity and source health
- `checkpoint()` — persist progress only after successful ingestion

Keep retrieval policy out of connectors. A connector describes the source; the
ingestion and retrieval layers apply common normalization and governance rules.

## Ingestion invariants

1. Create stable IDs from the source identity, not from mutable content.
2. Preserve canonical source references and source timestamps.
3. Hash content so unchanged objects are not reprocessed.
4. Normalize into a common knowledge-item shape before chunking.
5. Advance a cursor atomically with successful persistence.
6. Make repeated synchronization safe and observable.
7. Treat permission metadata as required input, not optional decoration.

## First-release guidance

The first connector is local files in a personal SQLite deployment. Keep it
small: explicit roots, supported text-like formats, deterministic IDs, clear
unreadable-file errors, and no background service until the synchronous path is
verified. Do not add a remote connector or external dependency without an
approved sprint task.

## Verification

Test discovery, new files, changed files, unchanged files, missing files,
duplicate sync, partial failure, source provenance, timestamps, permissions,
and cursor behavior. Run `skills/test-as-lee.md` for the full user workflow.
