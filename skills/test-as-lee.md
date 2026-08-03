# Skill: Test As Lee

> Use this skill before declaring a feature complete or handing it to a reviewer.

The goal is to test the product as a user of governed evidence, not only as a
developer of individual functions.

## Bootstrap checks

Until the first retrieval path exists, run:

```bash
lee-kb --help
lee-kb --version
python3 -m compileall -q src/lee-kb/*.py
pytest
```

Once ingestion and retrieval exist, start with the real CLI or service entry
point documented in `README.md` and `sprint-plan.md`.

## User-path protocol

1. Prepare a small realistic local corpus with a known source and one changed file.
2. Run synchronization through the actual entry point.
3. Verify the projection contains normalized items, chunks, metadata, source IDs, and timestamps.
4. Run an exact-token query and inspect ranked evidence.
5. Confirm each result cites the original source and reports freshness.
6. Confirm the retrieval receipt records the query, selected evidence, permissions, and retrieval time.

## Unhappy paths

Exercise at least these cases:

- empty directory or empty document
- unreadable or missing file
- malformed input or invalid configuration
- repeated synchronization with no changes
- changed content with the same path
- interrupted ingestion or persistence failure
- evidence denied by the authorization layer
- stale evidence when a freshness requirement is present

The expected result is either a correct, idempotent outcome or a concise,
actionable error. No traceback, silent data loss, unauthorized evidence, or
false success message should remain.

## Completion check

Ask: “Would Lee be comfortable showing this workflow to someone who expects
source citations, permission safety, and honest freshness?” If not, fix the
behavior before documenting completion.
