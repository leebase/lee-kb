# Skill: Backlog Items

> Use this skill when research or implementation uncovers work outside the active sprint.

## When to create an item

Create a candidate when the idea is meaningful, not yet approved, changes public
behavior, or would expand the current first-release scope. Just do it when the
work is clearly inside the active sprint and is small enough to finish safely.

AI writes only to `backlog/candidates/`. The human curates candidates into
`approved/`, `parked/`, or another lifecycle directory.

## Required content

Copy `backlog/template.md` to
`backlog/candidates/BI-NNN-{kebab-title}.md` and fill every required field from
`backlog/schema.md`:

- source and one-sentence insight
- opportunity and why now
- smallest useful implementation
- measurable definition of done
- effort, build recipe, priority, dependencies, risks, and mitigations

Use `research/cerebras.kb` as a source when the idea comes from that research;
do not treat research as an automatic product requirement.

## Quality test

A future builder with no conversation history should understand what to build,
why it matters now, what is deliberately excluded, and how to verify it.

## Lifecycle

```text
candidates/ → human approval → approved/ → builder → implemented/
                          └──────→ parked/
```

An implemented item receives a completion note with the implementation and
verification references.
