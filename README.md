# Lee Knowledge Base (lee-kb)

Lee Knowledge Base is a personal-first, governed Second Brain for knowledge
that remains in its original systems. It connects sources, synchronizes a
normalized projection, and returns permission-aware evidence with provenance
and freshness.

It is designed to grow from Lee's personal deployment to small shared projects,
not to become an enterprise administration platform.

lee-kb is not a replacement for source systems, an execution engine, or an
authorization engine. Retrieval answers “what evidence exists?”; execution
authority remains with the system that owns the action.

## Current status

Sprint 1 (Personal Foundation) delivers one governed retrieval path: local
documents on disk synchronize into a normalized SQLite projection and are
searchable through lexical retrieval, with permission filtering, citations,
freshness reporting, and retrieval receipts on every result. Office formats
now use the same governed path. Sprint 3 adds a
second, higher-level surface on top of that same retrieval path: `lee-kb ask`
returns a governed, cited *answer* — assembled claims, confidence,
conflicts, and absences — instead of raw evidence rows. See
`docs/answer-architecture.md` for the design and
`docs/answer-benchmark-results.md` for benchmark results.

Delivered in this release:

- personal SQLite deployment, driven by the `lee-kb` CLI (`init`, `sync`,
  `auth`, `search`, `ask`)
- a local-file connector reading `sources.toml`-compatible configuration, for
  Markdown, plain-text, Word, Excel, and PowerPoint documents
- deterministic Office extraction for `.docx`, `.xlsx`, and `.pptx`, with
  paragraph, sheet/cell, slide, and speaker-note citation references (see
  `docs/office-ingestion.md`)
- deterministic chunking and BM25-ranked lexical retrieval
- fail-closed authorization: every search or ask requires a principal, and
  unauthorized evidence is filtered before assembly, never returned
- source citations, freshness (sync age) reporting, and a persisted retrieval
  receipt for every piece of evidence released, plus a query-level audit event
  for empty, denied, stale-refused, and provider-failure outcomes
- an append-only sync journal and tombstone-based deletion (no hard deletes)
- a reusable Microsoft Graph foundation: delegated device-code authentication,
  secure token lifecycle, retry/throttling/rate limiting, pagination, delta
  recovery, and normalized errors
- a live-capable one-folder Outlook/Microsoft 365 transport wired through the
  common connector, SQLite checkpoint, citation, freshness, and audit path
  (real account proof remains operator-run and is not part of the offline suite)
- an offline golden-evaluation harness with a recorded lexical baseline (see
  `docs/golden-baseline.md`)
- the governed `answer()` surface (`lee-kb ask`): claim assembly, conflict
  identification without a winner, authoritative-absence classification, and
  deterministic, offline synthesis — no LLM call, no unaccounted-for
  evidence (see `docs/answer-architecture.md` and
  `docs/answer-benchmark-results.md`)

Explicitly deferred, not implemented in this release:

- **An LLM-backed synthesis provider for `ask`.** `SynthesisProvider` is a
  one-method protocol (`docs/answer-architecture.md`, Synthesis Providers)
  specified for exactly this purpose. `answer()` ships with only
  `DeterministicSynthesisProvider`, a template renderer with no model call —
  it is offline and auditable, but not natural prose. An LLM-backed
  implementation is unimplemented pending explicit runtime-dependency
  approval.
- **The curated golden benchmark.** `docs/golden-baseline.md` records a
  20-question corpus generated from this repository's own documents; it
  proves the evaluation harness, not Lee's real recurring Chief of Staff
  questions against the Employee Zero sources. That curated corpus is a
  follow-on task, and it does not yet exist for `ask` either — see
  `docs/answer-benchmark-results.md`.
- **Live filesystem verification of `ask` over time.** `ask`'s benchmark
  suite (`tests/answers/`) runs against a temporary, synthetic SQLite
  projection built for the test; nothing yet exercises `ask` against a live,
  continuously-synchronized filesystem corpus (freshness drift, resync
  during use, and so on) — a deferred extension.
- OneDrive and OneNote connectors, semantic search, reranking, and multi-user
  deployment are later phases. OneNote is explicitly not implemented in this
  sprint.

## Personal Connector Roadmap

The connector conformance and capability mapping slice is delivered. The next
operator-gated step is a real Outlook mailbox proof; the source roadmap is:

- local project directories, including `/projects`;
- selected OneDrive folders;
- Outlook/Microsoft 365 mail;
- OneNote notebooks and pages;
- Gmail.

These sources remain authoritative. Each connector will preserve stable source
identity, incremental state, permission metadata, freshness, deletion versus
temporary failure, and governed citations. The shared Microsoft Graph
foundation and Outlook transport are implemented; OneDrive remains a future
connector, and OneNote is design-only.

## Development setup

The project targets Python 3.11 or newer. Use a virtual environment, then
install the package with development tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Validation commands:

```bash
pytest
BLACK_NUM_WORKERS=1 python -m black --check src tests tools
python -m ruff check src tests tools
python -m compileall -q src tests tools
```

## Usage

`lee-kb` reads its configuration from `~/.config/lee-kb/config.toml` by
default (override with `--config` or the `LEE_KB_CONFIG` environment
variable). Sync is user-driven; there is no background daemon.

```bash
lee-kb --help
lee-kb --version
```

### Microsoft Graph Outlook

Configure a public/native Microsoft client, one account binding, and one
Outlook folder in `config.toml`; keep tokens out of the file:

```toml
[microsoft_graph]
client_id = "public-native-app-client-id"
tenant = "common"
scopes = ["Mail.Read", "User.Read"]

[microsoft_graph.accounts.personal]
user_id = "lee@example.com"

[outlook.inbox]
account = "personal"
folder_id = "<mail-folder-id>"
folder_name = "Inbox"
project = "default"
```

Use the device flow and then the same governed retrieval surfaces:

```bash
lee-kb auth login --account personal
lee-kb sync outlook inbox
lee-kb search "launch review" --principal lee@example.com
lee-kb ask "what did I say about the launch review?" --principal lee@example.com
lee-kb auth revoke --account personal
```

The default Linux token store uses the OS Secret Service and fails closed when
it is unavailable. See `docs/microsoft-graph.md` for token lifecycle,
checkpoint recovery, OneDrive readiness, and the explicit OneNote deferral.

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

Temporary root, subtree, or file read failures are reported as skipped and are
not treated as deletions. A root-scoped sync also reports files claimed by a
more-specific overlapping root. After the last synchronized item is deleted,
`ask` reports a searched `not_found`; a project that has never synchronized
remains `unknown`.

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

### 4. Ask

```bash
lee-kb ask "what blocks the documentation steward gate?"
lee-kb ask "what blocks the documentation steward gate?" --project default --top-k 10 --principal lee@leebase.com
```

`ask` calls the same governed `retrieve()` surface as `search`, then layers
claim assembly, conflict identification, and confidence assignment on top
(`src/lee_kb/answer.py`; design in `docs/answer-architecture.md`). Unlike
`search`, which prints raw ranked evidence, `ask` prints an assembled answer:

- claims (or deterministic, offline synthesized prose over them — no LLM
  call in this release), each with its own confidence level
  (`directly_evidenced`, `synthesized`, `inferred`, or `unknown`)
- citations for every claim
- any conflicts between claims, with both sides and no winner picked
- an explicit absence (`not_found`, `inaccessible`, or `unknown`) instead of
  claims when nothing can be answered — never a silent empty result
- how many additional retrieved-but-unused evidence items were considered,
  and a reference to the retrieval receipt(s) behind the answer

`ask` is fail-closed exactly like `search`: a missing or unauthorized
principal is rejected before any evidence is touched, and evidence a
principal cannot see is reported only as a withheld count, never its
content. `ask` accepts `--database` (see the `sync` overrides above);
`search` does not.

### 5. MCP

lee-kb provides the incumbent-compatible MCP surface through stdio JSON-RPC:

```bash
LEE_KB_CONFIG=/path/to/config.toml python3 -m lee_kb.mcp
# or, after installation:
LEE_KB_CONFIG=/path/to/config.toml lee-kb-mcp
```

It exposes `kb_search`, `kb_status`, and the read-only
`kb_compile_preview` tools. `kb_search` preserves the incumbent result fields
and adds governed citations, freshness, and retrieval receipts. See
`docs/kb-r1-mcp-parity.md` for the exact contract and the explicit
registration/cutover boundary.

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
| `src/lee_kb/` | Python package: contracts, connectors, repository, chunking, retrieval, governance, `answer()`, CLI |
| `tests/` | Automated tests, including `tests/golden/` and `tests/answers/` |
| `docs/golden-baseline.md` | Recorded lexical baseline for the golden evaluation corpus |
| `docs/answer-architecture.md` | Normative design for the governed `answer()` surface |
| `docs/answer-benchmark-results.md` | Benchmark results for `answer()` against its seven fixture families |
| `code-reviews/` | Independent review artifacts |

## License

MIT. Copyright Lee Harrington.
