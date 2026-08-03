# Skill: Development Loop

> Use this skill when implementing a feature or fix.

Every change should move through this loop:

```text
1. SCOPE → 2. DESIGN → 3. IMPLEMENT → 4. TEST → 5. TEST AS LEE
→ 6. FIX → 7. DOCUMENT → 8. HAND OFF
```

## 1. Scope

- Read `product-definition.md`, `architecture.md`, and the active task in `sprint-plan.md`.
- Confirm the change is within the current first-release boundary.
- Identify source-system trust boundaries and any permission, provenance, or freshness implications.

## 2. Design

- Define the smallest public interface before writing internals.
- Keep connector, ingestion, repository, search, authorization, and retrieval responsibilities separate.
- Preserve replaceable provider boundaries; do not introduce a database- or model-specific assumption without an architecture decision.
- Write concrete acceptance criteria, including failure and repeated-operation behavior.

## 3. Implement

- Build one vertical slice at a time.
- Handle external and persistence failures explicitly.
- Make synchronization idempotent and advance cursors only after successful ingestion.
- Never pass evidence to an AI model before permission filtering.

## 4. Test

Run the checks available in the repository:

```bash
pytest
python3 -m compileall -q src/lee-kb/*.py
black --check src
ruff check src
```

Add or update tests for changed behavior. Include empty input, missing source,
changed source, repeated sync, denied evidence, and partial-failure cases where
they apply.

## 5. Test as Lee

Follow `skills/test-as-lee.md`. Start at the real entry point and verify that a
user can complete the entire workflow, inspect source citations, understand
freshness, and see a clear error for invalid or unavailable input.

## 6. Fix

Repair failures in the implementation, not by weakening the test or hiding the
error. Repeat automated and user-path checks until clean.

## 7. Document

Follow `skills/documentation.md`. Update project memory, the README when user
behavior changes, and `architecture.md` for durable technical decisions.

## 8. Hand off

Report changed files, verification commands and results, remaining risks, and
the next bounded task. Do not claim planned behavior is implemented.
