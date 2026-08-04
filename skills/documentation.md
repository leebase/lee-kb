# Skill: Documentation Update

> Use this skill after validation and before handing work off.

Documentation is the durable handoff between stateless agents. Keep it factual:
separate implemented behavior from design, planned work, and open questions.

## Required updates

| File | Update when | Include |
|------|-------------|---------|
| `context.md` | Every meaningful work unit | Current state, decisions, blockers, next action |
| `sprint-plan.md` | A task starts, changes, or completes | Status and acceptance-criteria evidence |
| `result-review.md` | Work is completed | What changed, why it matters, how to verify |
| `WHERE_AM_I.md` | Phase or milestone changes | Product progress, risks, and next milestone |
| `README.md` | User behavior or setup changes | Accurate commands and capabilities |
| `architecture.md` | Durable technical decision | Decision, rationale, consequences, alternatives |
| `feedback.md` | Review feedback is received or actioned | Finding, owner, status, and rationale |

## Handoff entry format

```markdown
## YYYY-MM-DD — Short description

### What Was Built
What exists now that did not exist before.

### Why It Matters
Which product or governance requirement it advances.

### How to Verify
Exact commands and expected outcomes.
```

## Documentation checks

- Remove stale placeholders and generic scaffold claims.
- Keep product scope in `product-definition.md`; keep technical decisions in `architecture.md`.
- Link new work to a sprint task or backlog item.
- Record source IDs, timestamps, permission behavior, and receipt fields when retrieval behavior changes.
- Do not update status to complete until the stated verification has actually run.

## Publication rule (this repository is public)

Every tracked file — including project memory, playbooks, and evidence — is
published. Before committing, run a repository-wide scan for absolute host
paths, not a pattern-specific one:

```bash
git ls-files -z | xargs -0 grep -nEI "(/Volumes/|/Users/|/home/|/mnt/|/media/|[A-Z]:\\\\)"
```

Findings S2-R-01, S2-R-02, and S2-R-12 were all this same disclosure class,
caught in three separate places (gitignore coverage, playbooks, project
memory). Each earlier scan was narrowed to the pattern that had just been
found, so the next instance survived. Scan for the class, not the instance.

Permitted: root-level source names and aggregate statistics. Never: corpus
locations, document titles or content, credentials, or a real host path.
Illustrative placeholder paths in docstrings and test fixtures are fine when
they are obviously not a real location.
