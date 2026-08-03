# Skill: Code Review

> Use this skill before closing a sprint or preparing a release.
>
> Review-only rule: do not modify implementation files or commit while acting
> as the independent reviewer. Write findings to `code-reviews/` and
> `feedback.md`.

## Phase 0: Map the project

Read `AGENTS.md`, `product-definition.md`, `architecture.md`, `sprint-plan.md`,
and the changed files. Identify:

- entry points and user-visible commands
- connectors and external systems
- persisted data and migration risks
- trust boundaries and permission checks
- source provenance and freshness paths

## Phase 1: Run checks

Run the commands that exist for the project:

```bash
python3 -m compileall -q src/lee-kb/*.py
pytest
black --check src
ruff check src
```

If a command is unavailable or no tests exist, record that as a finding rather
than implying the project is healthy.

## Phase 2: Review lenses

### Correctness and failure handling

- Are source changes, cursors, and persistence updates idempotent?
- Can a partial failure leave an inconsistent projection?
- Are missing or stale sources reported honestly?

### Governance and security

- Is authorization evaluated before evidence assembly and model access?
- Can a connector bypass the common permission or provenance path?
- Does retrieval accidentally grant execution authority?
- Are source content, credentials, and file paths handled safely?

### Retrieval quality

- Are lexical, semantic, and reranking providers kept replaceable?
- Are evidence bundles cited, deduplicated, and understandable?
- Are source, synchronization, and retrieval timestamps retained?

### Tests and documentation

- Are happy paths, empty input, repeated sync, changed source, denied evidence, and failures covered?
- Do README, sprint memory, and architecture match actual behavior?

## Phase 3: Write the review

Create `code-reviews/review-YYYY-MM-DD.md` with:

```markdown
# Code Review — YYYY-MM-DD

## Architecture Summary
...

## Checks Run
| Command | Result |
|---------|--------|

## Findings
| ID | Severity | Category | Location | Problem | Proposed Fix |
|----|----------|----------|----------|---------|--------------|

## Remediation Roadmap
### Fix Now
### Fix Soon
### Fix Later

## Test Additions Recommended
- [ ] ...
```

Use specific file/function locations and honest severity. High-severity
findings include unauthorized evidence, data loss, or incorrect normal-use
behavior; style concerns are low severity.
