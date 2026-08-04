# Employee Zero Knowledge Base — Reference for lee-kb Sprint 1

This documents the EXISTING knowledge-base implementation behind "Employee
Zero" (the AI Employee Factory's chief-of-staff agent), which lee-kb Sprint 1
reimplements with improved architecture. All claims below were verified
directly in the source/config listed; anything not found is marked so rather
than guessed.

Sources inspected: `ai-employee-factory/knowledge/sources.toml`,
`ai-employee-factory/.kb/manifest.json`, `kb-index/src/kb/{cli.py,mcp.py,
__main__.py,__init__.py}`, `ai-employee-factory/knowledge/{faq.md,
portfolio-scope.md,briefs/,dossiers/}`, `ai-employee-factory/{AGENTS.md,
CLAUDE.md,.mcp.json,tests/test_kb_venture.py,tests/check_kb_venture_smoke.py}`.

## Overview

The `kb` package (`kb-index/src/kb/`, v0.1.0) is stdlib-only Python: sqlite3
FTS5 for search, `tomllib` for config, `argparse` CLI, `subprocess` for git.
Zero pip dependencies. It builds a **derived, rebuildable** index over
Markdown scattered across many sibling git repos ("roots") and exposes it via
CLI (`python -m kb`) and a read-only MCP server (`python -m kb.mcp`). Package
docstring: "this package is the mechanism; `sources.toml` is the taxonomy...
putting one venture's roots in here would make them everyone's."

Extracted from the venture repo on 2026-07-27 (formerly `scripts/kb.py`
inside `ai-employee-factory`). The venture repo now holds only the
*deployment*: `knowledge/sources.toml`, `knowledge/faq.md`, `.kb/` build
output, and `.mcp.json` pointing at the installed package (`-m kb.mcp`), not
a path.

## Source Configuration (sources.toml)

`knowledge/sources.toml` (328 lines), `schema = 1`, one `[roots.*]` table per
root. Required per-root fields: `path`, `required`, `authority`, `trust`,
`owner`, `include`; optional `exclude`, `external`, `overrides`. Validated by
`load_sources_config` in `cli.py`.

- **`authority`**: `"canonical"` or `"derived"` (`AUTHORITY_RANK = {canonical:0, derived:1}`); canonical outranks derived in search ordering.
- **`trust`**: `"human_authored"`, `"curated"`, or `"model_produced"`. `model_produced` hits are tagged inline on every citation (`!model_produced`) — "never quotable as if a human curated it."
- Authority/trust are "DECLARATIONS by the config owner, never inferred from content" (file header comment).
- **Global default-deny** regardless of root config: `("code-reviews/**", ".agent-orch/**", ".agent-orch-scratch/**", "artifacts/**", "tmp/**", ".kb/**", ".git/**")`.
- **`external = true`** required for any root path resolving outside the workspace; build-time config validation fails otherwise.
- **`overrides`**: list of `{pattern, authority?, trust?}`; first match wins, letting individual files be promoted to `canonical` inside a `derived` root.
- Unconditional filename secrets filter (separate from TOML): `.env*`/`*.pem` always refused; non-markdown names containing `credential(s)/secret(s)/token` refused. Content is also regex-scanned for private keys, `api_key=`, `ghp_`, `sk-`, `xox[baprs]-` and refused even mid-build.

Excerpt:
```toml
[roots.factory]
path = "."
required = true
authority = "derived"
trust = "curated"
owner = "lee@leebase.com"
include = ["*.md", "consulting/*.md", "marketing/*.md", ...]
exclude = ["code-reviews/**", ".agent-orch/**", "artifacts/**", "tmp/**", ".kb/**"]

[[roots.factory.overrides]]
pattern = "knowledge/faq.md"
authority = "canonical"

[roots.pr-research]        # admitted 2026-07-23, third-party AI research
path = "../ai-process-reengeneering/research"
external = true
required = false
trust = "model_produced"   # flagged inline on every hit
```

**15 configured roots**: `factory`, `agent-orch`, `auto-orch`, `agent-board`,
`leeos`, `pr-business`, `jobsearch`, `lee-sf-rbac`, `erd-tool`, `drawdb`,
`ai-employee-book`, `tviq`, `linux-utilities`, `agent-in-a-box`,
`pr-research`. Only `factory` is non-external (`path = "."`); the other 14
are sibling repos (`external = true`, `path = "../<repo>"`). 9 of 15 are
`required = false`. All carry `owner = "lee@leebase.com"`; all `derived`
except per-file overrides promoting specific canonical docs; all `trust =
"curated"` except `pr-research` (`model_produced`). Inline comments record
real operational history (e.g. `jobsearch` widened 2026-07-20 after a search
miss forced a manual file read; `agent-in-a-box` split into its own root
2026-07-23 because it's a nested, gitignored repo the `jobsearch` globs never
reached).

## Build Pipeline (`python -m kb build`)

Entry: `main()` in `cli.py` via `__main__.py`. Config located by walking up
from CWD for `knowledge/sources.toml` (overridable with `--config`).

`cmd_build` steps:
1. Resolve every root path; missing `required` root aborts the build; missing optional root only warns and is recorded `"missing": true`.
2. Exclusive build lock (`.kb/build.lock`, `O_CREAT|O_EXCL`); stale lock (dead PID) cleared once, live concurrent build raises `SystemExit`.
3. Monotonic `generation` counter = previous manifest's generation + 1.
4. New index built in a fresh temp SQLite file under `.kb/`, live `index.sqlite` untouched until publish.
5. Per root, filesystem walk applies include/exclude globs, token-filename filter, symlink-escape guard. Git-ignore status for all candidates resolved in **one batched `git check-ignore -z --stdin` call** per root (perf fix: 13 roots/~1900 files had pushed `kb status` from <1s to 35s, past the MCP server's 30s timeout).
6. Each document is fetched, extracted, then **re-fetched/re-digested** as a mid-build mutation guard; drift retries once then aborts.
7. Content re-scanned for token-shaped secrets at index time; matches skipped and counted (`skipped_token_content`).
8. git HEAD captured before/after each root; a HEAD move mid-build aborts the build.
9. `validate_faq_pointers` parses `knowledge/faq.md`: every entry must have exactly one `Source: \`root:path[#Heading]\`` pointer resolving to a real file/heading — malformed or dangling pointer **fails the build**.
10. **Atomic publish**: `os.replace` temp DB onto `index.sqlite`, then generation-numbered temp manifest `os.replace`d onto `manifest.json`. Any exception before publish deletes only the temp DB — last-known-good files untouched.

**Chunking** (`MarkdownExtractor._split_markdown_blocks`): splits on ATX
headings (`#`–`######`) outside fenced code blocks; pre-heading content
becomes a `(document)` preamble block. Each block tracks `heading`, `level`,
an `occurrence` counter (repeats), `start_offset`. Chunker id is versioned:
`markdown-atx-v1:1`.

**Hashing/provenance**: content digest = SHA-256 over raw file bytes
(`documents.digest`). A separate **config fingerprint** = SHA-256 over raw
config bytes + normalized trust metadata + chunker id/version + schema
version (what `kb status` uses to detect `sources.toml` changes). Per-file
provenance (`compute_provenance`): if the root is itself a git repo root, a
12-char short SHA if content matches HEAD's blob exactly, `<sha>+dirty` if
working copy differs, else `"untracked"`. Stored per document (`commit_stamp`,
`dirty`, `untracked`) and per chunk.

## SQLite Schema and Index

`SCHEMA_VERSION = 1`. Tables (`create_schema`):
```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- keys: schema_version, generation, fingerprint, chunker

CREATE TABLE documents (
    id INTEGER PRIMARY KEY, root TEXT, path TEXT, digest TEXT,
    commit_stamp TEXT, dirty INTEGER, untracked INTEGER,
    authority TEXT, trust TEXT, media_type TEXT, UNIQUE(root, path));

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES documents(id),
    root TEXT, path TEXT, heading TEXT, occurrence INTEGER, text TEXT,
    authority TEXT, trust TEXT, commit_stamp TEXT, authority_rank INTEGER);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    heading, text, content='chunks', content_rowid='id', tokenize='porter');
```
`ensure_fts5` probes FTS5 at schema-creation time and hard-fails
(`SystemExit`) if unavailable. FTS rows are populated by explicit `INSERT
INTO chunks_fts(rowid, heading, text)` per chunk during build — no triggers,
no `content_rowid` rebuild command used.

`kb status`/`kb search` open the DB **read-only** (`file:...?mode=ro`) and
never write. `check_schema` distinguishes `corrupt`/`missing-schema`/
`bad-schema`/`wrong-schema`.

**Freshness** (`kb status`, exit `3`=stale, `1`=error, `0`=fresh): recomputes
config fingerprint and every current file's digest, diffs against what's
stored, per root. Any added/removed/changed file, fingerprint mismatch,
missing/corrupt/wrong-schema index, or missing required root marks
stale/rebuild-required. Status only diagnoses — never rebuilds.

## Search Surface

`kb search "<query>" [--limit N] [--json]`. Query normalization
(`fts_quote_query`): tokenize on `[A-Za-z0-9_]+`, quote each as an FTS5
literal; multi-token queries build `("phrase") OR (tok1 AND tok2 ...)` so an
exact phrase ranks above a loose AND match.

```sql
SELECT c.root, c.path, c.heading, c.commit_stamp, c.text, c.authority, c.trust,
       bm25(chunks_fts, 2.0, 1.0) AS rank
FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
WHERE chunks_fts MATCH ?
ORDER BY c.authority_rank ASC, rank ASC, c.root ASC, c.path ASC, c.heading ASC
LIMIT ?
```
`authority_rank` (canonical=0, derived=1) is the **primary sort key**, ahead
of BM25 — canonical always outranks derived regardless of text-match score.
Heading column weighted 2.0 vs text 1.0.

Hits render as `[root:path#heading @commit_stamp]` (`format_provenance_line`),
with `!model_produced` suffix when applicable.

`kb compile [--query Q | --root R] --output PATH [--force]` assembles
matching chunks (query: same ranking, top 100; root: all chunks, ordered by
path/heading) into one provenance-stamped Markdown bundle. Output is
sandboxed: must resolve under `tmp/kb-exports/`; refuses to overwrite
`sources.toml`, `faq.md`, `index.sqlite`, `manifest.json`, `build.lock`, or
any path aliasing an existing corpus document. No `--force` = exclusive
create (fails if exists); `--force` = atomic temp-write + replace. Re-checks
every chunk and the assembled bundle for token-shaped secrets before writing.

## MCP Surface

`kb.mcp` (`kb-index/src/kb/mcp.py`): stdlib JSON-RPC 2.0-over-stdio, protocol
`"2025-06-18"`, server name `employee-zero-kb`, version `1.0.0`. **Thin
subprocess wrapper** — every tool shells out to `sys.executable -m kb <args>`
(never imports `kb.cli` directly), 30s timeout, 1 MB output cap. Docstring:
"Read-only by construction: never invokes `kb build` or `kb compile`, never
writes any file." Workspace = `$KB_WORKSPACE` env var if set, else `Path.cwd()`.

Three tools:
1. **`kb_search`** — `{query: string (required), limit: int 1-20, default 5}`. Runs `kb status --json` preflight; status exit `1`/`4` (rebuild-required) → tool error advising `kb build`, search not attempted. Output: `{"results": [...], "index_state": "fresh"|"stale", "staleness"?: {...}}`. A `"stale"` index (status exit 3) still returns results, just labelled.
2. **`kb_status`** — no input; verbatim relay of `kb status --json`.
3. **`kb_compile_preview`** — `{query: string (required)}`. Same preflight, then `kb search` at `limit=20`, reformatted into a Markdown preview. Despite the name it never calls `kb compile` or writes a file — read-only reformatting of search hits.

Registration (`.mcp.json`): `{"mcpServers": {"employee-zero-kb": {"command": "python3", "args": ["-m", "kb.mcp"]}}}`.

## Consumers and Parity Requirements

Employee Zero's contract lives in `AGENTS.md`/`CLAUDE.md`. Verified
session-start sequence (`CLAUDE.md`):

1. `kb status` — exit 3 (stale) or 4 (rebuild-required) → `kb build` before answering; "Never answer from a stale index without saying so."
2. Read `STATUS.md`, `questions.md`.
3. **Answer from `knowledge/faq.md` first** (canonical, `Source:`-pointered); `kb search "<keywords>"` for anything deeper, preferred over grep/manual scanning ("returns provenance-stamped passages, canonical sources ranked first"); fall back to reading whole files only if both miss.
4. Portable briefing: `kb compile --query "<topic>" --output tmp/kb-exports/<name>.md --force`.
5. Mission/employee **operational status** questions are explicitly routed away from the KB to `python3 scripts/mission_status.py` (live, git-history-based) — "it indexes static docs, not live state."
6. `python3 scripts/dossier.py lint` — reconciles `knowledge/dossiers/` against ground truth; exit 1 = drifted, don't trust until fixed.

**FAQ** (`knowledge/faq.md`, 242 lines): curated Q&A, each entry with exactly
one `Source:` pointer, mechanically validated by `kb build`.

**Dossiers** (`knowledge/dossiers/README.md`): the "compiled" synthesis layer
— one page per standing topic, `authority = derived`. Each declares a
`reconcile:` YAML block (`sources`, `files_present`, `files_absent`,
`greps_absent`) checked by `scripts/dossier.py lint` against live
files/grep/mission status; drift or staleness fails the lint. Built after a
documented 2026-07-24 incident where stale docs claimed two missions were
"shipped." Commands: `dossier.py new/list/lint`. This lint mechanism lives
entirely in `ai-employee-factory/scripts/dossier.py` (534 lines) — **not**
part of the `kb` package.

**Deployment tests** (`ai-employee-factory/tests/`):
- `test_kb_venture.py`: `sources.toml` exists/parses/`schema==1`/has roots; `.mcp.json` server args start `["-m","kb.mcp"]` with no stale `scripts/` reference; FAQ `Source:` pointers parse via `kb.cli.parse_faq_pointers`; `python -m kb --help` succeeds via subprocess (proves real install).
- `check_kb_venture_smoke.py`: runs `kb build` then `kb status`, asserts stdout starts `"fresh\n"`.

No `skills/` or `src/` directory exists under `ai-employee-factory` — Employee
Zero's behavior comes from `AGENTS.md`/`CLAUDE.md` read directly, not from a
packaged skills system.

## Corpus Shape

From `.kb/manifest.json` (generation 249, latest build at inspection time):
**1,209 documents, 12,634 chunks, across the 15 configured roots**, chunker
`markdown-atx-v1:1`. Per-root docs/chunks: factory 53/437, agent-orch
99/1976, auto-orch 60/468, agent-board 6/295, leeos 47/629, pr-business 3/42,
jobsearch 402/4214 (largest root), lee-sf-rbac 19/112, erd-tool 35/234,
drawdb 6/93, ai-employee-book 70/815, tviq 61/552, linux-utilities 60/524,
agent-in-a-box 286/2204, pr-research 2/39. The commonly-quoted "~1,200 docs /
15 roots" is accurate; all 15 roots show `"missing": false`.

Canonical knowledge files under `knowledge/` (name / purpose, no content
copied): `faq.md` (curated Q&A with source pointers); `portfolio-scope.md`
(coverage contract listing every portfolio line a broad brief must address,
not itself a status ledger); `sources.toml` (build config); `dossiers/
README.md` (explains the dossier pattern); `dossiers/erd-tool.md` (the one
populated project dossier at inspection time); `briefs/*.md` (13 dated
chief-of-staff briefing snapshots, 2026-07-18 through 2026-08-02).

## Gaps vs lee-kb Architecture

Verified against the full `kb` package source and the venture deployment:

- **No receipts / query audit log.** No table records what was searched or
  returned, and no logging of MCP tool calls beyond stderr on failure.
- **No principal/permissions model.** `DocumentRef`/`FetchedDocument`
  dataclasses carry `acl`, `audience`, `classification` fields, but the only
  concrete producer (`LocalFilesAdapter.fetch`) sets all three to `None` —
  present in the type, never populated or enforced. The MCP server accepts
  any `tools/call` with no auth concept.
- **No first-class "projects" entity.** "Projects" exist only as informal
  `sources.toml` roots; there is no project table, ownership record, or
  cross-root grouping in the schema.
- **No sync journal / incremental update log.** Every build is a full
  from-scratch rebuild atomically swapped in; no per-document change history,
  and no prior-generation content is retained anywhere in `.kb/` — only the
  current `generation` counter and current manifest.
- **Synthesis-drift safety is bolted on, not in the mechanism.** The dossier
  reconcile/lint safeguard lives entirely in venture-specific
  `scripts/dossier.py`, outside the `kb` package; the package itself has no
  concept of a derived claim that must reconcile against ground truth.
- **Live/operational state is an explicit, documented boundary, not a gap**:
  `CLAUDE.md` and the `agent-board` root's config comment both state mission/
  health status must come from live checks (`mission_status.py`, board
  `/health`), "because index freshness alone cannot prove operational
  health."
