# Lee Knowledge Base Agent Roles

These role files define the handoffs in the AgentFlow workflow. Use the role
that matches the work; a single session may use more than one role, but the
reviewer should remain independent from the builder when possible.

```text
Researcher → Planner → Human approval → Builder → Reviewer
```

The human curates scope, approves security-sensitive choices, and decides when
work moves from `backlog/candidates/` into implementation.
