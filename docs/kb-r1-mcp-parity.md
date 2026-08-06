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

## KB-R2 handoff

Benchmark both servers against the same small fixture and the approved
Employee Zero corpus before cutover. The benchmark should compare tool-call
latency, fresh/stale status behavior, top-k citation identity, authority/trust
ordering, empty and denied queries, preview text, and receipt/audit accounting.
It should also record the intentional semantic differences: `lee-kb` is
permission-aware and requires a configured principal, its `commit` is a
content hash rather than a git stamp, and its status describes the SQLite
projection plus local-root cursor drift. KB-R2 should decide whether those
differences are acceptable for the session protocol and define the sanitized
evidence needed before KB-R3 registration.
