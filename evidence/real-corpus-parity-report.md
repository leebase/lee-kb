# Real-Corpus Parity Report

Measures `lee-kb sync`/`lee-kb search` against Lee's real deployed
`ai-employee-factory/knowledge/sources.toml` configuration (15 roots, ~1,200
documents), the reference corpus described in
`research/employee-zero-kb-reference.md`. This report contains only
aggregate statistics, counts, extensions, timings, and root-level names —
no document titles, file paths beyond root names, or document content are
reproduced, per the public-repository constraint.

## Configuration

- Config: `ai-employee-factory/knowledge/sources.toml` (`schema = 1`, 15 `[roots.*]` tables) — the same deployed config documented in `research/employee-zero-kb-reference.md`.
- Workspace root: `ai-employee-factory` (`--workspace-root`).
- Database: `.lee-kb/real-corpus.sqlite`, deleted before this run so all counts describe a clean full sync (no prior state carried over).
- Command run, timed and synchronous: `/usr/bin/time -v env PYTHONPATH=src python3 -m lee_kb.main sync --config <sources.toml> --workspace-root <workspace> --database .lee-kb/real-corpus.sqlite`. Exit code 0.
- All 15 configured roots resolved to real, present directories on this machine; none reported missing.
- `lee-kb search` has no `--database` flag (only `sync` does); retrieval testing used a minimal `.lee-kb/search-real-corpus.toml` config (`database` pointed at the synced projection, `owner = "lee@leebase.com"`) passed via `--config`, and the default principal (`lee@leebase.com`) for every query.
- Preserved validator evidence for this step's lineage (not rerun): `pytest tests/` passed on all three independent runs (exit 0, ~7.9s/8.0s/9.0s), and `python3 -m lee_kb.main sync --help` succeeded on both independent runs (exit 0). These establish the CLI and test suite were healthy going into this real-corpus run; they are summarized here, not restated verbatim.

## Corpus Shape

- Total live knowledge items: **1,213**. Total chunks: **12,699**.
- Projection size on disk: **21,020,672 bytes (~20.0 MiB)**.
- Per-root document / chunk counts:

| Root | Documents | Chunks |
|---|---:|---:|
| agent-board | 6 | 295 |
| agent-in-a-box | 286 | 2,204 |
| agent-orch | 100 | 1,991 |
| ai-employee-book | 70 | 815 |
| auto-orch | 63 | 516 |
| drawdb | 6 | 93 |
| erd-tool | 35 | 234 |
| factory | 53 | 437 |
| jobsearch | 402 | 4,217 |
| lee-sf-rbac | 19 | 112 |
| leeos | 47 | 629 |
| linux-utilities | 60 | 524 |
| pr-business | 3 | 42 |
| pr-research | 2 | 39 |
| tviq | 61 | 551 |

- Authority: **13 canonical**, **1,200 derived**. The deployed config declares exactly 13 `[[roots.*.overrides]]` promotions (12 in `factory`, 1 in `jobsearch`) — verified: 13 items carry `authority = canonical` (12 in `factory`, 1 in `jobsearch`), so every declared override promotion took effect and none leaked into an unexpected root.
- Trust: **1,211 curated**, **2 model_produced** — the 2 model-produced items are exactly the 2 documents in the `pr-research` root, the only root configured `trust = "model_produced"`.

## What Was Not Indexed

CLI sync summary counters, **as measured in the original pre-repair run**: **1,213 created, 0 updated, 0 deleted, 0 unchanged, 300 git-ignored, 5 git-ignore status unresolved**. The post-repair re-measurement prints **14 git-ignored** (unresolved unchanged at 5); the 300 figure was inflated by both roots of each overlapping pair separately counting the same ignored candidates — see Performance and the S2-R-04 note in Parity Gaps. `skipped` (unfetchable objects) and `skipped (token-shaped content)` were both 0 and so did not print — no fetch failures and no content matched the credential-shaped-string tripwire anywhere in the real corpus. `git_unresolved` (5) means git-ignore status could not be determined for 5 candidates (non-git root or git unavailable there); per the connector's contract these are counted, not excluded, and remain in the 1,213 indexed documents.

Unhandled-format histogram (candidates that matched a root's `include` patterns but have no registered format handler): **empty (`{}`) across all 15 roots.**

This zero is a structural artifact, not evidence of a closed office-format gap. Every one of the 15 roots' `include` glob lists is markdown-only (`*.md` and directory-scoped `*.md` variants) — no root's config ever asks for `.docx`/`.xlsx`/`.pptx`. A file only reaches the "matched but no handler" check after it first matches an `include` pattern; office-format files never match, so they are excluded a step earlier and never counted anywhere by the connector, whether or not parsing support exists.

To size the real gap for Lee's Priority 2 decision, a direct, read-only filesystem count of office-format files sitting inside the 15 configured root paths (independent of `include`/`exclude`/git-ignore filtering) found:

| Extension | Count |
|---|---:|
| .docx | 32 |
| .xlsx | 5 |
| .pptx | 2 |
| **Total** | **39** |

Two roots account for most of it: `ai-employee-book` (21 `.docx`) and `tviq` (9 files spanning all three extensions); the remaining 9 files are spread across `agent-orch`, `pr-business`, `jobsearch`, and `factory`. Ten of the 15 roots have zero office-format files present. This count is a raw filesystem tally (not filtered by `include`/`exclude`/git-ignore), so it is an upper bound on what the connector would actually pick up once both parsing support and matching `include` patterns exist — but it is a real, non-zero number the connector-level measurement alone cannot see.

## Retrieval Behavior

Twelve queries were run against the real projection via `lee-kb search --config .lee-kb/search-real-corpus.toml`: two per golden-corpus category (operational status, project management, architecture, job search, knowledge discovery) plus two deliberately common-word queries for the OR-matcher stress test.

- All 12 queries returned governed evidence; none returned an empty result.
- Of the 10 category queries, **8** returned a top citation that was clearly the right document and root for the question. **2** (one job-search query, one knowledge-discovery query) returned a citation from the correct root and topically adjacent to the question, but not the specific canonical/expected document — in both cases the better document exists in the corpus but was outranked by a peripheral document sharing more literal vocabulary with the query. This is a lexical BM25 ranking limitation, not a discovery or indexing defect, and is a good candidate input for curating the real golden benchmark (Next Actions Queue rank 7).
- No result was denied by permissions in this run; the search principal (`lee@leebase.com`) matches the `owner` declared on every root, so authorization allowed everything discovered.

OR-matcher fetch-to-exhaustion (Priority 5): confirmed present and now measured on the real corpus. `LexicalRetriever._search_project` doubles its SQLite query limit (starting at 32) as long as a batch returns a full page, so a query matching a large fraction of the corpus re-queries several times before it can rank the result set. The single-common-word query ("the", which falls back to matching its literal token once stopword-stripping empties the token set) was the slowest of all 12 queries. The second common-word query ("what is the status of the project") retains two distinguishing content tokens after stopword stripping and was not unusually slow — see Performance below for the numbers.

## Performance

Sync (`/usr/bin/time -v`, full clean sync of the real corpus) — pre-repair baseline vs. this post-repair re-measurement (database deleted before the run, so this is also a clean full sync):

| Metric | Pre-repair (baseline) | Post-repair (this run) | Delta |
|---|---:|---:|---:|
| Wall-clock elapsed | 5:20.37 (320.37s) | 2:51.18 (171.18s) | −149.19s (−46.6%) |
| User time | 269.69s | 140.78s | −128.91s (−47.8%) |
| System time | 43.78s | 23.44s | −20.34s (−46.5%) |
| CPU utilization | 97% | 95% | −2 pts |
| Peak resident set size | 4,585,924 KB (~4.37 GiB) | 4,568,212 KB (~4.36 GiB) | −17,712 KB (−0.4%) |
| Swaps / major (I/O) page faults | none | none | unchanged |

The wall-clock and CPU-time drop tracks the S2-R-03 single-discovery-pass repair: the pre-repair sync ran full filesystem discovery (per-root `git check-ignore` batching plus content hashing of every candidate) twice in one sync — once while diffing changes, once again to build the discovery report — and the repair consolidated both onto a single discovery pass. Peak memory is materially unchanged (within 0.4%), which is consistent with that explanation: the repair removes redundant *work*, not redundant *data held in memory* at any one time.

Document and chunk totals from this run are identical to the pre-repair baseline: **1,213 documents, 12,699 chunks**, with identical per-root counts in every row of the Corpus Shape table above, and an identical projection size on disk (21,020,672 bytes). The S2-R-04 nested-root repair did not change which files are indexed as knowledge items in this corpus; see Parity Gaps for what it did change and why.

Sync summary counters also carried forward exactly except for two diagnostics: **1,213 created, 0 updated, 0 deleted, 0 unchanged** matched the baseline, but `git-ignored` dropped from 300 to **14** and `git-ignore status unresolved` stayed at **5**. See Parity Gaps for the explanation.

Retrieval (`lee-kb search`, wall-clock per query, real corpus already synced) — not re-measured this run (out of this step's scope, and document/chunk counts are unchanged so no retrieval-affecting shift is expected); figures below are carried forward unchanged from the pre-repair measurement:

| Query type | Count | Latency range | Mean |
|---|---:|---|---:|
| Category queries (2 per golden category) | 10 | 0.286s – 0.766s | 0.443s |
| Common-word stress queries | 2 | 0.465s – 1.521s | 0.993s |

The single-common-word query ("the") was the slowest of all 12 at **1.521s**, roughly 3.4x the category-query mean — the visible worst case of OR-matcher fetch-to-exhaustion on this corpus size. Not measured: latency behavior at a materially larger corpus size (e.g. after office-format ingestion), which would require re-running this same query set once that corpus exists.

## Parity Gaps

- Corpus shape closely tracks the Employee Zero reference snapshot in `research/employee-zero-kb-reference.md` (1,209 documents / 12,634 chunks at that inspection's generation 249) against this run's 1,213 documents / 12,699 chunks. 13 of 15 roots match the reference exactly or within a handful of chunks; the largest drift is in `auto-orch` (+3 documents, +48 chunks vs. the reference) and `agent-orch` (+1 document, +15 chunks vs. the reference) — consistent with ordinary content growth in those repos since the reference was captured, not a discovery gap, given the other 13 roots line up closely.
- All 13 declared canonical-override promotions took effect exactly as configured; none were skipped, and none leaked onto an unexpected item.
- Zero fetch failures and zero token-shaped-secret hits across the entire real corpus — a clean sync end to end on this pass.
- The office-format gap is real and larger than the connector's own summary line can show: 39 office-format files sit inside the configured root paths today, invisible to the sync summary because the deployed `include` patterns never request them. Closing this gap requires both approving parsing dependencies *and* extending the relevant roots' `include` patterns — either alone is insufficient.
- git-ignored (300 pre-repair, **14 post-repair**) and git-ignore-unresolved (5, unchanged) are both accounted for and non-blocking; unresolved candidates are still indexed, matching the connector's "count it, don't drop it" contract. The pre-repair 300 double-counted candidates in the two overlapping-root regions.
- OR-matcher fetch-to-exhaustion is now measured, not just theorized: worst case ~1.5s on the current ~1,213-document corpus. Whether this degrades materially once the office-format expansion increases corpus size is not measured here.
- Post-repair re-measurement (this run, database deleted first for a clean full sync): the S2-R-04 nested-root repair found two real overlaps in the deployed config — `jobsearch`/`agent-in-a-box` and `pr-business`/`pr-research` (confirmed via the connector's own health check, which reports root names only, no paths) — and now has the deepest matching root claim each overlapping file. This changed the sync's `git-ignored` diagnostic counter from 300 to 14 (`git-ignore status unresolved` stayed at 5), because pre-repair, both roots in each overlapping pair independently discovered and separately counted the same ignored candidates in the shared region. It did **not** change indexed document or chunk counts, per-root or total (see Performance) — the overlap region evidently held no file that both roots' `include` patterns matched outside of already-ignored candidates, so no duplicate knowledge item was ever actually created; the repair corrected an inflated diagnostic count and closed the class of bug (duplicate citable evidence for one file) rather than fixing an already-manifested duplication in this specific corpus.
- The S2-R-03 single-discovery-pass repair changed measured sync performance, not corpus shape: wall-clock dropped ~46.6% (5:20.37 → 2:51.18) with peak memory unchanged within noise, consistent with eliminating one of two redundant full discovery passes that the pre-repair sync ran per invocation.
- Preserved validator evidence for this step's lineage (not rerun here): `pytest tests/` passed on two independent runs (exit 0, 11.098397s and 11.557784s), tied to the S2-R-04 nested-root and S2-R-03 single-discovery-pass acceptance criteria; `pytest tests/golden/` passed on one independent run (exit 0, 8.119346s), tied to the S1-R-16 baseline-as-contract acceptance criterion. These establish the repaired code and the golden-corpus contract were healthy going into this real-corpus re-measurement.

## Recommended Next Actions

1. **Priority 2 (office-format libraries):** treat 39 files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`), concentrated in `ai-employee-book` and `tviq`, as the real target size. Approving parsing dependencies alone will not surface these — the affected roots' `include` patterns also need extending, since today they structurally exclude office extensions before any handler lookup happens.
2. **Priority 5 (OR-matcher):** the worst-case query (a single ubiquitous token) now has a real number on the real corpus (~1.5s). Decide whether that is acceptable as-is or worth a page-size cap / early-exit heuristic before the corpus grows further via office-format ingestion.
3. **Priority 7 (curate the real golden benchmark):** the two category queries whose top citation was topically adjacent but not canonical (job-search-log and README-map categories) are good raw material — they show a real ranking edge case on Lee's actual corpus, which the generated seed corpus in `docs/golden-baseline.md` cannot exercise.
4. Treat the **post-repair** sync wall-clock (**2:51.18**) and peak memory (**~4.36 GiB**) as the baseline for future full-resync performance work; the pre-repair figures (5:20.37, ~4.37 GiB) are retained above only for comparison. Peak memory is essentially unchanged by the S2-R-03 repair and remains an open question. Re-measure after the office-format roots are extended, since both figures will move with corpus size.
5. The original measurement pass surfaced no correctness defects in the sync itself (zero fetch failures, zero unexpected overrides, all 15 roots reachable). The independent review of that pass did surface defects, and three were subsequently repaired and re-measured here: S2-R-04 (nested roots could produce duplicate evidence), S2-R-03 (the corpus was walked twice per sync), and S2-R-13 (an unreachable required root failed silently).
