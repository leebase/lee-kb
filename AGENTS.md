# Agent Guide: Lee Knowledge Base

> **For AI agents working on Lee Knowledge Base (lee-kb).**
>
> This project uses **AgentFlow**: a documentation-driven workflow for turning
> research into small, reviewable increments of a governed knowledge fabric.

## Product and Architecture

Read these before making a product or technical decision:

- `product-definition.md` — vision, users, first release, and non-goals
- `architecture.md` — system boundaries, provider interfaces, and data flow
- `research/` — source material and implementation patterns worth evaluating

The original source systems remain authoritative. lee-kb stores a searchable
projection and must preserve provenance, permissions, and freshness.

## Startup Protocol

At the start of every session, in order:

1. Read `AGENTS.md` for guardrails and workflow.
2. Read `context.md` for current session state.
3. Read `WHERE_AM_I.md` for product-level orientation.
4. Read `result-review.md` for the latest completed work.
5. Read `sprint-plan.md` for the active sprint and next task.
6. Read `product-definition.md`, `architecture.md`, and relevant research before changing scope or design.

## AgentFlow Roles

Role instructions live in `agents/`:

| Role | Responsibility | Primary outputs |
|------|----------------|-----------------|
| Researcher | Mine research and record useful, testable insights | `backlog/candidates/`, research notes |
| Planner | Turn approved work into a bounded sprint and resolve design questions | `sprint-plan.md`, architecture updates |
| Builder | Implement one approved vertical slice and its tests | source, tests, documentation |
| Reviewer | Independently check correctness, security, scope, and evidence governance | `code-reviews/`, `feedback.md` |

The human remains the curator and retains approval authority for scope,
security-sensitive operations, and backlog promotion.

## Skills

Load the relevant skill file when the trigger applies. Do not rely on memory.

| Trigger | Skill |
|---------|-------|
| Implementing a feature or fix | `skills/development-loop.md` |
| Designing or implementing a connector or ingestion path | `skills/connector-development.md` |
| Designing retrieval, evidence, freshness, or receipts | `skills/retrieval-development.md` |
| Mining `research/` into implementation candidates | `skills/research-mining.md` |
| About to validate a user workflow | `skills/test-as-lee.md` |
| Updating project memory or preparing a commit | `skills/documentation.md` |
| Creating a backlog item | `skills/backlog.md` |
| Closing a sprint or reviewing a release | `skills/code-review.md` |

## Task Rehydration

Before continuing a task mid-session:

1. Re-read `sprint-plan.md`.
2. Re-read every file modified earlier in the session.
3. Confirm the objective and its acceptance criteria before proceeding.

## Guardrails

### Allowed

- Modify code and documentation inside this repository.
- Add tests for new behavior.
- Add research notes and backlog candidates under the documented workflow.
- Update project memory and decision records.

### Requires explicit approval

- Add external runtime dependencies.
- Make breaking changes to public interfaces or persisted schemas.
- Delete files or discard user changes.
- Promote backlog items out of `backlog/candidates/`.
- Connect to external systems, transmit source content, or perform production operations.

### Product invariants

- Connect instead of migrate; source systems remain authoritative.
- Normalize source artifacts into knowledge items and chunks with provenance.
- Enforce authorization before evidence reaches an AI model.
- Retrieval never grants execution authority.
- Report source, synchronization, and retrieval timestamps where relevant.
- Keep search, embedding, reranking, and persistence behind replaceable interfaces.
- Start with the personal SQLite release; do not build enterprise infrastructure early.

## Communication Style

- Be concise, specific, and actionable.
- Name files and acceptance criteria when reporting work.
- Surface security, freshness, provenance, and scope concerns immediately.
- Do not claim a feature is implemented when only its design exists.

## Documentation Contract

At the end of each meaningful work unit:

- Update `context.md` with current state and next actions.
- Update `sprint-plan.md` when task status changes.
- Add a `result-review.md` entry for completed work.
- Update `WHERE_AM_I.md` when the project phase or milestone changes.
- Record durable technical decisions in `architecture.md`.

*Project guide aligned with the Lee Knowledge Base definition on 2026-08-03.*
