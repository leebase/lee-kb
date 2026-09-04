# KB-R1 — MCP parity surface

Status: implemented 2026-08-06. This is the successor-side MCP adapter only;
registration and cutover remain KB-R3 work.

## Parity surface

`kb-index` exposes a stdlib JSON-RPC 2.0 server over newline-delimited stdio,
using protocol version `2025-06-18`. Its three tools are preserved exactly:

| Tool | Input contract | Compatible output |
|---|---|---|
| `kb_search` | Required `query: string`; optional `limit: integer` from 1–20, default 5 | JSON text containing `results` and `index_state`; every result retains `root`, `path`, `heading`, `commit`, `text`, `authority`, and `trust` |
| `kb_status` | Empty object | JSON text containing `state` and `roots` |
| `kb_compile_preview` | Required `query: string` | Markdown text beginning with `# KB compile preview` and an `index_state` line |

The server also handles the incumbent handshake, `ping`, `tools/list`,
`tools/call`, JSON-RPC notifications, parse errors, and the incumbent invalid
parameter codes.

The adapter is implemented in `src/lee_kb/mcp.py` with no MCP runtime
dependency. It routes non-empty search and preview queries through governed
`retrieve()`. The incumbent `commit` field is populated with lee-kb's stable
source content hash; additive fields expose the item/chunk IDs, source
timestamps, sync timestamp, freshness, and permission-scoped receipt data.
Each released result has a `receipt` and `receipt_id`, and the search payload
also carries `receipts` and `receipt_count`. Preview keeps its incumbent text
shape and adds a `receipt: #N` line per released block.

`kb_status` reports configured local-root drift against the persisted
content-hash cursor. `fresh` and `stale` are usable search states; a missing or
invalid projection returns `rebuild-required`/`error` and search returns an
MCP tool error with the `lee-kb sync` remedy. Search and preview do not sync,
build, compile to a file, or mutate source files. They do persist the normal
lee-kb retrieval receipts and query audit events.

## Launch

Use the existing lee-kb configuration convention:

```bash
LEE_KB_CONFIG=/path/to/config.toml python3 -m lee_kb.mcp
```

After installing the package, the equivalent console entrypoint is:

```bash
LEE_KB_CONFIG=/path/to/config.toml lee-kb-mcp
```

The configured owner supplies the MCP retrieval principal. When roots declare
one project, that project is selected; otherwise the server uses the personal
`default` project unless `LEE_KB_MCP_PROJECT` is set. Synchronize the
projection separately with `lee-kb sync` before starting a session.

## Deliberately not done

- No `.mcp.json` was created or changed.
- No MCP registration, consumer cutover, or production operation was run.
- `kb-index` was not modified.
- The incumbent's file-writing `kb compile` command is not exposed; the parity
  tool is its existing read-only `kb_compile_preview` surface.
- Live mission status, dossier validation, and other consumer-side session
  steps remain outside the knowledge retrieval server.

## KB-R2 result (2026-08-08, revised same day after a perf fix)

Benchmarked against `kb-index` on the real `ai-employee-factory/knowledge/sources.toml`
corpus over live stdio JSON-RPC. Full method, numbers, root-cause diagnosis,
and post-fix re-measurement: `evidence/kb-r2-mcp-benchmark-report.md`.

**Go.** Functional/data parity holds — same corpus, comparable doc/chunk
counts, relevant provenance-complete results, additive receipts as designed.
The first pass found `kb_status` (and therefore every `kb_search` call,
which runs the same preflight) costing 148s against the real corpus versus
kb-index's 5.5s — a 27× regression. `cProfile` traced it to
`LocalFilesConnector.discover_report()`'s `os.walk` never pruning denied
directories before descending into them (one root's `.agent-orch-scratch/`
alone contributed 1.16M unnecessarily-walked files, despite already being in
`GLOBAL_DEFAULT_DENY`) — `kb-index` avoids this because its own walk already
prunes `dirnames` in place. Fixed same day by porting that same pruning
(`_dir_denied()`) plus a secondary fix to `_claiming_root()`'s nested-root
resolution (cached string-prefix comparison instead of repeated `pathlib`
containment checks). Full 374-test suite passes unchanged. Re-measured live
against the same real corpus: lee-kb now costs 3.9–4.2s per call across
`kb_status`/`kb_search`/`kb_compile_preview`, consistently **faster** than
kb-index's 5.5–5.6s.

KB-R3 (registration/cutover) remains separate, intentionally-undone
deployment work: `.mcp.json` was not touched by this benchmark.

Separately, kb-index's build-time `validate_faq_pointers` gate (every FAQ
`Source:` pointer must resolve) had no lee-kb equivalent — a cutover would
have silently dropped that enforcement. Closed via
`ai-employee-factory/scripts/faq_lint.py`, a standalone, engine-independent
reimplementation with no dependency on either KB package staying installed.
