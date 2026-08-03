# Skill: Research Mining

> Use this skill when turning material in `research/` into project decisions or backlog candidates.

## Process

1. Read the relevant research source completely.
2. Separate observed facts from interpretation and from proposed product behavior.
3. Map each useful pattern to `product-definition.md` or `architecture.md`.
4. Identify tradeoffs, prerequisites, scale assumptions, and security implications.
5. Keep only insights relevant to the current phase in the active sprint.
6. Put unapproved implementation ideas in `backlog/candidates/` using the backlog skill.

## Current research lens

`research/cerebras.kb` is useful for evaluating:

- meeting data where it already lives
- normalization before embedding
- complementary lexical and semantic signals
- incremental ingestion and source-specific freshness
- shared evidence shapes and source-scoped projects
- retrieval fan-out and reranking patterns

It is not a mandate to copy Cerebras’s infrastructure. In particular, the
first release remains personal, SQLite-backed, local-first, and lexical.

## Output quality

Every extracted insight should state what it changes, what it does not change,
how it can be verified, and whether it requires human approval before entering
the roadmap.
