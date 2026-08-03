# Lee Knowledge Base (lee-kb)

Lee Knowledge Base is a governed knowledge fabric for searching knowledge that
remains in its original systems. It connects sources, synchronizes a normalized
projection, and returns permission-aware evidence with provenance and freshness.

lee-kb is not a replacement for source systems, an execution engine, or an
authorization engine. Retrieval answers “what evidence exists?”; execution
authority remains with the system that owns the action.

## Current status

The product definition, architecture, and initial research are recorded. The
implementation is at the foundation stage; ingestion and retrieval are not yet
available. The first release is intentionally small:

- personal deployment
- SQLite persistence
- local documents plus one additional connector
- lexical retrieval and chunking
- source citations, freshness reporting, and retrieval receipts

Semantic search, reranking, multi-user deployment, and enterprise connectors
are later phases.

## Development setup

The project targets Python 3.10 or newer. Use a virtual environment, then
install the package with development tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

The bootstrap CLI currently exposes its help and version metadata:

```bash
lee-kb --help
lee-kb --version
```

Validation commands:

```bash
pytest
python -m compileall -q src/lee-kb/*.py
black --check src
ruff check src
```

## AgentFlow workflow

Project memory is kept in the root documents. Start with `AGENTS.md`, then
`context.md`, `WHERE_AM_I.md`, `result-review.md`, and `sprint-plan.md`.

- `agents/` contains role instructions for research, planning, building, and review.
- `skills/` contains repeatable workflows for connectors, retrieval, testing, documentation, and backlog work.
- `backlog/candidates/` is where research-derived work waits for human curation.
- `research/` contains source material; it is not automatically an implementation requirement.

## Repository map

| Path | Purpose |
|------|---------|
| `product-definition.md` | Product vision, users, scope, and success criteria |
| `architecture.md` | Layer boundaries and provider abstractions |
| `project-plan.md` | Long-term phases and milestones |
| `sprint-plan.md` | Active tactical work |
| `src/lee-kb/` | Python package and bootstrap CLI |
| `tests/` | Automated tests |
| `code-reviews/` | Independent review artifacts |

## License

MIT. Copyright Lee Harrington.
