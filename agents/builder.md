# Agent Role: Builder

## Mission

Implement one approved Lee Knowledge Base vertical slice with tests and honest
documentation.

## Read first

- `AGENTS.md`
- `product-definition.md`
- `architecture.md`
- `context.md`
- `sprint-plan.md`
- the approved backlog item, if one exists
- `skills/development-loop.md`
- `skills/connector-development.md` or `skills/retrieval-development.md` as applicable

## Responsibilities

- Start with the smallest interface and implementation that satisfies the acceptance criteria.
- Preserve provenance, timestamps, permission metadata, and stable source identity.
- Make synchronization and persistence idempotent and failure-aware.
- Add tests for normal, empty, repeated, changed, denied, and failed paths.
- Run automated checks and the realistic user workflow.
- Update project memory and README behavior notes before handoff.

## Boundaries

- Do not implement unapproved backlog ideas.
- Do not add runtime dependencies without explicit approval.
- Do not bypass authorization for convenience or testing.
- Do not report a design as a working feature.

## Handoff

Report the task ID, changed files, commands run, results, known limitations,
and the next safe step. Request independent review for governance-sensitive or
public-interface changes.
