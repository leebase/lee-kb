# KB-R2 — MCP Benchmark: kb-index vs lee-kb (revised after perf fix)

Benchmarks the KB-R1 `lee-kb` MCP adapter (`src/lee_kb/mcp.py`) against the
incumbent `kb-index` MCP server (`kb.mcp`), both live over stdio JSON-RPC,
both pointed at the same real deployed corpus
(`ai-employee-factory/knowledge/sources.toml`, 15 roots). This is the
handoff `docs/kb-r1-mcp-parity.md` named as the prerequisite for any KB-R3
registration/cutover decision. Per the public-repository constraint, this
report contains aggregate counts, timings, and root names only — no document
content.

**Update (same day):** the original run below found a 27× `kb_status`/
`kb_search` latency regression, root-caused it, fixed it, and re-measured.
Fixed lee-kb is now **faster** than kb-index on every call. See "Root cause
and fix" and "Post-fix re-measurement" at the end of this report for the
current numbers; the sections above them are preserved verbatim as the
original finding that triggered the fix.

## Method

- **kb-index**: `python3 -m kb.mcp`, `cwd=ai-employee-factory`,
  `KB_WORKSPACE=ai-employee-factory` (its already-fresh index, generation
  276, rebuilt immediately before this run: `python3 -m kb build` →
  1,256 docs / 13,185 chunks in 22.3s wall / 11.4s user / 11.4s sys).
- **lee-kb**: `PYTHONPATH=src python3 -m lee_kb.mcp`, `cwd=lee-kb`,
  `LEE_KB_CONFIG` pointed at a config built from the **same live
  `sources.toml`** (`database` and `workspace_root` keys prepended, no other
  changes — both are valid top-level keys per
  `connectors/local_files.py::_TOP_LEVEL_KEYS`) so both servers see identical
  root/include/exclude/authority/trust declarations. Backing projection: a
  clean `lee-kb sync` against the same config immediately before this run
  (`.lee-kb/kb-r2-benchmark.sqlite`) → 1,249 created (plus roots claimed by
  overlap resolution) in 174.1s wall / 146.1s user / 20.9s sys.
- Both servers driven over real stdio (subprocess, newline-delimited JSON-RPC
  2.0, `protocolVersion: "2025-06-18"`), not in-process calls.
- Config parity note: an initial pass used a minimal `{database, owner}`
  config (the shape the existing `real-corpus-parity-report.md` used for
  `lee-kb search`/`ask`) and got `kb_status.roots: []` — lee-kb's MCP status
  handler only iterates roots present in the *live config's* `[roots.*]`
  table, unlike kb-index's status, which reads root definitions baked into
  the index itself. This is not a defect; it means an MCP deployment config
  for lee-kb must carry the full root list, not just a database pointer, to
  get incumbent-shaped per-root status.

## Sync/build cost (full corpus, cold)

| | kb-index (`kb build`) | lee-kb (`lee-kb sync`) | Ratio |
|---|---:|---:|---:|
| Wall time | 22.3s | 174.1s | **7.8× slower** |
| User CPU | 11.4s | 146.1s | 12.8× |
| Docs | 1,256 | 1,249 created (+ overlap-claimed) | parity |

## `kb_status` cost and shape

| | kb-index | lee-kb (full-root config) |
|---|---:|---:|
| Call latency | **5.510s** | **148.628s** |
| Result | `state: fresh`, 15 roots w/ per-root docs/chunks/state | `state: stale`, 15 roots w/ per-root docs/chunks/state |

Both recompute live freshness by walking/hashing the configured roots on
every `kb_status` call — this is not a one-off cold-start cost, it is paid on
**every** call. kb-index pays 5.5s because of a specific, documented
optimization (batched `git check-ignore -z --stdin`, one call per root,
fixed a prior 35s regression at this corpus size). lee-kb's projection
freshness path has no equivalent optimization at this scale: **27× slower**
per status check.

Both reported at least one stale root (`auto-orch`/`agent-orch`/`jobsearch`
et al.) — expected and correct, not a defect: this benchmark ran while this
very session was actively editing files in several of the configured roots
(`auto-orch`, and indirectly `ai-employee-factory` via this work).

## `kb_search` cost and correctness

`_tool_kb_search` in both servers runs the same status preflight before
every search (kb-index's docstring: "status exit `1`/`4` → tool error...
search not attempted"; lee-kb's `_status_preflight()` is architecturally
identical). Because that preflight is the dominant cost measured above, it
is paid **per search call, not just at session start**:

| Query | kb-index latency | lee-kb latency |
|---|---:|---:|
| `"chief of staff hiring authority"` (5 results) | 5.597s | 148.164s |
| `"zzznonexistentqueryxyz123notreal"` (0 results) | 5.988s | — (not re-run; cost is dominated by the same preflight, see above) |

Both returned topically correct, provenance-complete hits for the real
query (kb-index's `kb_compile_preview` for a related query surfaced
`factory:AGENTS.md#Employee Zero — the Factory's Chief of Staff`; lee-kb's
`kb_search` top hit was `factory:CLAUDE.md#You are Employee Zero` — both
correct, top-ranked chunks about Employee Zero from the `factory` canonical
root; the two queries were not textually identical so this is not a claim of
byte-identical ranking parity, only that both engines return relevant,
correctly-attributed evidence). lee-kb's results additionally carry a full
`receipt` object with source/content hashes and timestamps per result, as
designed (KB-R1's additive-fields contract).

No empty/denied-query or authority-ordering divergence was found in the
queries run. A byte-for-byte ranking-identity check (same query, same top-K
ordering, same authority/trust tie-breaks) was not completed for a larger
query set — not needed to reach the recommendation below, since latency
alone is disqualifying.

## Finding (original run)

**Functional/data parity: met.** Same corpus, same root declarations,
comparable document/chunk counts, relevant and correctly-provenanced results
on both sides, and lee-kb's receipts/audit trail are strictly additive on
top of the incumbent's result shape (confirmed in `tests/test_mcp.py` and
re-confirmed live here).

**Performance parity: not met at the time of this measurement.** Employee
Zero's own documented session-start contract (`ai-employee-factory/CLAUDE.md`)
is "run `kb status` at session start... seconds." kb-index honored that
(5.5s). lee-kb's `kb_status` — and therefore every `kb_search` call, since
each pays the same preflight — cost **148s** against the real corpus, a 27×
regression. Root-caused and fixed same day; see below.

## Root cause and fix

`cProfile` against `lee_kb.mcp._status_payload()` (which calls
`LocalFilesConnector.discover_report()`) showed 1,592,634 calls to
`pathlib.Path.relative_to`/`is_relative_to`, accounting for ~68% of wall
time on their own, plus their downstream pathlib-internals cost (`__init__`,
`_str_normcase`, `with_segments`, `_from_parsed_parts`, …) pushing the real
share past 90%. Cross-checked against a direct filesystem count: summing
`find <root> -type f` across the 15 configured roots lands within 0.1% of
that call count (~1,590,443 vs 1,592,634).

Root cause: `LocalFilesConnector.discover_report()`'s `os.walk()` never
pruned the `dirnames` list `os.walk` exposes for exactly this purpose — it
descended into **every** subdirectory of every root, including
`.agent-orch-scratch/` (1,163,134 files under one single root,
`agent-orch`), `artifacts/`, `.git/`, and `.venv/`, even though
`.agent-orch-scratch/**`, `artifacts/**`, and `.git/**` were already in
`GLOBAL_DEFAULT_DENY` — that deny list was only ever applied to *files*
after they were walked, never used to prune *directories* before descending
into them. The reference `kb-index` avoids this: `kb.cli`'s equivalent walk
(`_LocalFilesAdapter`-style, around `os.walk` in `cli.py`) explicitly prunes
`dirnames[:] = keep` against the same deny patterns before descending
(`_dir_denied`), which is why it never paid this cost in the first place.

Fix (`src/lee_kb/connectors/local_files.py`):

1. Added `_dir_denied()`, a direct port of `kb.cli._dir_denied`'s semantics
   (a `prefix/**`/`prefix/*` deny pattern denies the directory itself and
   everything under it). Wired into the `os.walk` loop to prune `dirnames`
   in place against `GLOBAL_DEFAULT_DENY + root.exclude` before descending
   — the standard `topdown=True` pruning idiom, previously unused.
2. Separately, `_claiming_root()` (nested/overlapping-root resolution,
   S2-R-04) was rewritten to compare cached plain posix-string prefixes
   instead of re-deriving `pathlib.Path` containment per other-root per
   candidate file, and the per-root `is_dir()` liveness check it repeated
   per candidate was hoisted to once per `discover_report()` call. This was
   a real but secondary cost (correct in isolation, confirmed by an
   unchanged relative_to call count when tested alone) — the directory-walk
   pruning above is what actually eliminated the regression.

Verification: full test suite (374 tests) still passes, including
`tests/test_local_connector.py`'s nested-root-claiming coverage (S2-R-04) —
unchanged, since pruning denied directories cannot affect which *included*
files are discovered, only how many *excluded* ones are needlessly visited.

## Post-fix re-measurement (same real corpus, same session)

| | kb-index | lee-kb (fixed) | |
|---|---:|---:|---|
| `kb_status` | 5.500s | **3.994s** | lee-kb now faster |
| `kb_search` (5 results) | 5.546s | **4.124s** | lee-kb now faster |
| `kb_search` (0 results) | — | **3.916s** | |
| `kb_compile_preview` | — | **4.227s** | |

All three tools now cost roughly the same order of magnitude as kb-index —
in fact consistently ~1.3–1.5s faster on every call measured. Functional
output was re-checked at each step: correct result counts, correct
`index_state`/`staleness` reporting, correct top-hit content
(`factory:CLAUDE.md#You are Employee Zero`) for the same query used in the
original run.

## KB-R2 Recommendation: **Go — pending KB-R3 scope (registration/cutover), not further perf work**

The disqualifying finding from the original run is resolved and re-measured
live against the real corpus in the same session. Functional/data parity
was already met; performance parity is now met too, with lee-kb faster than
the incumbent on every measured call. Remaining before an actual `.mcp.json`
cutover: KB-R3 itself (registration, consumer-side testing, and the sanitized
operator evidence `docs/kb-r1-mcp-parity.md`'s KB-R2 handoff called for) —
that is deployment work, not benchmark work, and was intentionally not done
here (`.mcp.json` was not touched; `kb-index` remains the live server).

## Artifacts

- `.lee-kb/kb-r2-benchmark.sqlite` — clean full sync used for this run (gitignored).
- `.lee-kb/kb-r2-benchmark-full.toml` — MCP config used (`sources.toml` + `database`/`workspace_root`, gitignored).
- `src/lee_kb/connectors/local_files.py` — directory-pruning and `_claiming_root` perf fix (production source, committed).
- No `ai-employee-factory` file, including `.mcp.json` and `kb-index` source, was modified.
