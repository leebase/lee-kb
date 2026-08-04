# Lee Knowledge Base (lee-kb)

Lee Knowledge Base is a governed knowledge fabric for searching knowledge that
remains in its original systems. It connects sources, synchronizes a normalized
projection, and returns permission-aware evidence with provenance and freshness.

lee-kb is not a replacement for source systems, an execution engine, or an
authorization engine. Retrieval answers “what evidence exists?”; execution
authority remains with the system that owns the action.

## Current status

Sprint 1 (Personal Foundation) delivers one governed retrieval path: local
documents on disk synchronize into a normalized SQLite projection and are
searchable through lexical retrieval, with permission filtering, citations,
freshness reporting, and retrieval receipts on every result.

Delivered in this release:

- personal SQLite deployment, driven by the `lee-kb` CLI (`init`, `sync`, `search`)
- a local-file connector reading `sources.toml`-compatible configuration, for
  Markdown and plain-text documents
- deterministic chunking and BM25-ranked lexical retrieval
- fail-closed authorization: every search requires a principal, and
  unauthorized evidence is filtered before assembly, never returned
- source citations, freshness (sync age) reporting, and a persisted retrieval
  receipt for every piece of evidence released
- an append-only sync journal and tombstone-based deletion (no hard deletes)
- an offline golden-evaluation harness with a recorded lexical baseline (see
  `docs/golden-baseline.md`)

Explicitly deferred, not implemented in this release:

- **Office formats (`.docx`, `.xlsx`, `.pptx`).** These remain required v1
  product scope. `DocumentType` and the local-file connector's format-handler
  registry (`src/lee_kb/connectors/local_files.py`) already support adding
  them without redesign, but no parsing library is registered yet — new
  runtime dependencies need explicit approval first.
- **The curated golden benchmark.** `docs/golden-baseline.md` records a
  20-question corpus generated from this repository's own documents; it
  proves the evaluation harness, not Lee's real recurring Chief of Staff
  questions against the Employee Zero sources. That curated corpus is a
  follow-on task.
- Semantic search, reranking, the email connector, and multi-user deployment
  are later phases.

## Development setup

The project targets Python 3.10 or newer. Use a virtual environment, then
install the package with development tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Validation commands:

```bash
pytest
python -m black --check src tests
python -m ruff check src tests
```

## Usage

`lee-kb` reads its configuration from `~/.config/lee-kb/config.toml` by
default (override with `--config` or the `LEE_KB_CONFIG` environment
variable). Sync is user-driven; there is no background daemon.

```bash
lee-kb --help
lee-kb --version
```

### 1. Initialize configuration

```bash
lee-kb init
```

Writes a starter `config.toml` with a commented-out example root. Edit it to
declare one or more local-file source roots:

```toml
schema = 1
owner = "lee@leebase.com"

[roots.notes]
path = "/absolute/path/to/your/notes"
owner = "lee@leebase.com"
include = ["*.md", "*.txt"]
exclude = [".git/**"]
authority = "derived"
trust = "curated"
visibility = "private"
project = "default"
```

This format is compatible with the existing Employee Zero
`knowledge/sources.toml` root shape.

### 2. Synchronize

```bash
lee-kb sync                        # every configured root
lee-kb sync local_files notes      # just the "notes" root
lee-kb sync --config /path/to/sources.toml --workspace-root /path/to/workspace --database /path/to/projection.sqlite
```

Sync discovers new and changed files by content hash (not mtime), fetches and
chunks them, and persists items, chunks, permissions, and an append-only
journal entry to the configured SQLite database. Re-running `sync` with no
source changes reports everything as unchanged and creates no duplicate rows;
a changed file replaces its projection and journals the previous content
hash; a removed file is tombstoned, not hard-deleted, and excluded from
ordinary search.

`sync` accepts two additional overrides not exposed on `search`:

- `--workspace-root` resolves relative source-root paths against a given
  directory, overriding `workspace_root` in the config. This is what let a
  deployed `sources.toml` (whose roots are relative to its own workspace) be
  synchronized without rewriting the config.
- `--database` writes the synchronized SQLite projection to a specific path
  instead of the configured default, so a given config can be synced into an
  alternate or scratch database.

`search` has no `--database` flag; point it at a projection by setting
`database` in the config file passed via `--config`.

### 3. Search

```bash
lee-kb search "governed retrieval"
lee-kb search "governed retrieval" --project default --top-k 5 --principal lee@leebase.com
```

Every result is fail-closed: `search` requires a principal (defaulting to the
configured `owner`, then `lee@leebase.com`) and returns only evidence that
principal is permitted to see. Each result prints its ranked citation, source
URI, sync age, and a retrieval receipt number; denied and truncated results
are reported as counts, never silently dropped. Searching before the first
`sync` reports a clear error instead of a stack trace or an empty false
success.

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
| `src/lee_kb/` | Python package: contracts, connectors, repository, chunking, retrieval, governance, CLI |
| `tests/` | Automated tests, including `tests/golden/` |
| `docs/golden-baseline.md` | Recorded lexical baseline for the golden evaluation corpus |
| `code-reviews/` | Independent review artifacts |

## License

MIT. Copyright Lee Harrington.
