# Lee’s Process — Working with AI Agents

> **Human–AI collaboration protocol for Lee Knowledge Base**

## Session lifecycle

### 1. Start of session

**Human:**

- Review `WHERE_AM_I.md` and `context.md`.
- Identify the highest-ranked task in `sprint-plan.md`.
- Confirm any decisions that require human approval.

**AI:**

- Read `AGENTS.md` and the active role file in `agents/`.
- Read `product-definition.md`, `architecture.md`, and relevant `research/` material.
- Re-read the sprint plan and any files changed earlier in the session.
- State the bounded objective and acceptance criteria.

### 2. During the session

Use the smallest useful loop:

1. Understand the product boundary and trust boundary.
2. Plan one vertical slice.
3. Implement incrementally.
4. Test realistic and unhappy paths.
5. Check permissions, provenance, freshness, and idempotency.
6. Update project memory before handing off.

Communication should be concise, specific, and honest about what is implemented
versus designed.

### 3. End of session

Update:

- [ ] `context.md` — current state, decisions, and next actions
- [ ] `sprint-plan.md` — task status and remaining scope
- [ ] `result-review.md` — what changed and how to verify it
- [ ] `WHERE_AM_I.md` — phase or milestone changes

If a durable technical decision was made, update `architecture.md` too.

## AgentFlow handoffs

| Handoff | Input | Output |
|---------|-------|--------|
| Researcher → Planner | Research source and extracted insight | Candidate backlog item or design question |
| Planner → Human | Bounded implementation proposal | Approval, scope change, or parking decision |
| Human → Builder | Approved backlog item and sprint acceptance criteria | Code, tests, and documentation |
| Builder → Reviewer | Delivered vertical slice and verification results | Independent findings and remediation items |

Role-specific instructions live in `agents/`; repeatable technical workflows
live in `skills/`.

## File update requirements

### Every meaningful work unit

| File | What to add |
|------|-------------|
| `context.md` | State, next action, decisions, blockers |
| `sprint-plan.md` | Task status or acceptance-criteria changes |
| `result-review.md` | Completed work and verification |

### When the direction changes

| File | When to update |
|------|----------------|
| `WHERE_AM_I.md` | Phase, milestone, or product status changes |
| `architecture.md` | Durable technical choice or boundary changes |
| `product-definition.md` | Product scope, users, or non-goals change |
| `feedback.md` | Review findings are received or actioned |

## Definition of done

A task is done when:

1. The requested behavior works or the documentation change is complete.
2. Tests and realistic user-path checks pass when applicable.
3. Permission, provenance, freshness, and receipt implications are addressed.
4. Project memory accurately describes the new state.
5. A future agent can continue without relying on this conversation.

## Quick orientation

```text
Read:  AGENTS.md → context.md → WHERE_AM_I.md → result-review.md → sprint-plan.md
Scope: product-definition.md + architecture.md + relevant research/
Roles: agents/
Workflows: skills/
Backlog: backlog/candidates/ → human approval → implementation
Review: code-reviews/ and feedback.md
```

*Keep this process document about collaboration; keep product decisions in the product and architecture documents.*
