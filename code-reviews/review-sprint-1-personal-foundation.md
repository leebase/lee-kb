# Code Review — Sprint 1: Personal Foundation

**Reviewer role:** independent Reviewer (`agents/reviewer.md`, `skills/code-review.md`)
**Date:** 2026-08-03
**Commit reviewed:** `3219f93` (`fix(S1-R-01): remove ungoverned public retrieve() paths from retrieval module`)
**Scope reviewed:** `src/lee_kb/` (contracts, connectors, repository, chunking,
retrieval, governance, CLI), `tests/`, `tests/golden/`, `pyproject.toml`,
`docs/sprint-1-contracts.md`, `docs/golden-baseline.md`, `context.md`
(Decisions Locked).
**Verdict:** **fail** — two High findings.

Every claim below was re-derived from the delivered code in this attempt; no
conclusion is inherited. The governance core is correct and the prior High
finding (S1-R-01) is genuinely fixed. The two Highs are in the ingestion driver
and the lexical matcher, not in governance.

## Architecture Summary

One vertical slice is delivered end to end. `LocalFilesConnector` discovers and
fetches Markdown/plain-text files declared in a `sources.toml`-shaped config;
`chunk_document` produces deterministic heading- or paragraph-aligned chunks;
`SQLiteRepository` persists a latest-state projection plus an append-only
synchronization journal and a retrieval-receipt ledger; and
`governance.retrieve()` composes permission evaluation, BM25 lexical retrieval,
evidence assembly, freshness reporting, and receipt persistence into one call.
`lee-kb init｜sync｜search` is the v1 surface and reaches evidence only through
the governed call.

**The prior High finding is fixed and now regression-guarded.**
`lee_kb.retrieval` exports only `LEXICAL_RETRIEVER`, `LexicalRetriever`, and
`StaleEvidenceError` (`retrieval.py:24`); `LexicalRetriever` has `search()` only
and returns `SearchHit` rows, never evidence. My own package-wide sweep for
public callables annotated to return `EvidenceBundle` (probe P11) returned
`lee_kb.governance.retrieve` plus `lee_kb.main.governed_retrieve` — which is the
same function object, imported under an alias at `main.py:35`. One evidence
surface, guarded by `tests/test_governance.py:210`.

### Product invariants verified against the delivered code

| Invariant | Result | Evidence |
|---|---|---|
| Authorization is fail-closed | **Holds** | `governance.py:124-128` raises `MissingPrincipalError` before any repository access; probes P1/P1b: raised for both an omitted and an explicit `principal=None`, 0 receipt rows. `SingleUserPermissionEvaluator.is_permitted` (`governance.py:85-97`) grants only owner, explicit principal, group intersection, or `PUBLIC`. `PROJECT` visibility is deliberately **not** an implicit grant — probe P4: a non-owner got 0 evidence and `denied_count=1` against a `PROJECT`-visible item, and 1 evidence only once a `PUBLIC` item was added |
| Authorization precedes evidence assembly | **Holds** | `governance.py:148-155` filters provider candidates; the first `Evidence`/`Citation`/`RetrievalReceipt` is constructed at `governance.py:160-198`, strictly after the filter. Probe P2: the repository returned 1 raw candidate for the query, the governed call returned `evidence=0`, `denied_count=1`, and receipt rows stayed at 0 |
| Receipts for every **released** evidence item, with the locked fields | **Holds** | `governance.py:187-198` persists one receipt per evidence item via `repository.record_receipt`. Probe P3: rows 0→1, all eight locked fields from `docs/sprint-1-contracts.md:241-250` correct, and the persisted row round-trips equal to the returned receipt. `EvidenceBundle.__post_init__` (`contracts.py:638-674`) enforces one receipt per evidence item, same order, same chunk ID, same principal, same timestamp |
| A durable record for **every** retrieval | **Does not hold** | Denied and empty retrievals persist nothing (probe P2), and a `fail_on_stale` refusal persists receipts and then raises (probe P5) — see **S1-R-12** and **S1-R-02** |
| Provenance survives end to end | **Holds** | `SourceLocator` is captured at fetch (`connectors/local_files.py:379-394`), persisted (`repository.py:389-434`), rehydrated (`repository.py:709-743`), and reaches both `Citation` and `RetrievalReceipt`. `contracts.py:314-317` rejects an item whose locator connector disagrees with its item ID; `Citation.__post_init__` (`contracts.py:506-514`) rejects a chunk/item mismatch. Probe P3 confirmed the locator survives into the persisted receipt intact |
| Freshness triplet survives end to end | **Holds** | `source_timestamp` and `sync_timestamp` on every `Evidence` (`governance.py:182-183`), `retrieval_timestamp` on the bundle and every receipt (`governance.py:192, 213`), all round-tripped through SQLite as ISO-8601 (`repository.py:733-734, 794`). `contracts.py:100-104` rejects naive datetimes; `governance._require_aware` (`governance.py:220-224`) rejects a naive clock. Probe P5b read all three back off a live bundle (`oldest_sync=2030-01-01T09:00+00:00`, `newest_source=2030-01-01T09:00+00:00`, `staleness=3:00:00`) |
| Identity follows the locked tuples | **Holds** | `KnowledgeItemId(connector_id, source_object_id)` and `ChunkId(item_id, chunk_ordinal, content_hash)` (`contracts.py:230-273`) match the locked decision in `context.md`; the repository primary keys mirror them (`repository.py:125`, `repository.py:156`). Receipts store item ID + chunk ID + hash + locator + timestamp (`contracts.py:583-617`), so they stay verifiable after re-chunking |
| Project scoping is enforced | **Holds as locked** | `project` is required with no default on `KnowledgeItem`, `Chunk`, `JournalEntry`, `RetrieveRequest`, and `RetrievalReceipt` (`contracts.py:87-92` and each `__post_init__`); `repository.search` constrains `i.project = ?` (`repository.py:640`); the repository rejects a chunk whose project differs from its item (`repository.py:381-382`, probe P9: rejected); `EvidenceBundle` rejects evidence outside `request.effective_projects` (`contracts.py:657-663`). Probe P6a: a `default`-scoped query returned only `default` evidence. Probe P6c: a filter set that omits the request project is rejected, so the scope cannot be silently swapped. Deliberate widening is the locked contract but is not entitlement-checked — see **S1-R-05** |
| Sync journal is append-only | **Holds in the delivered code** | Only `_append_journal` writes the table, and only via `INSERT` (`repository.py:519-536`); no path in `src/` updates or deletes a row. Probe P8: a repeated sync of unchanged content left the journal at 1 row, and a real edit appended `updated`. No DB-level constraint backs the property — see **S1-R-06** |
| Tombstones exclude items from search | **Holds** | `repository.py:641` (`AND (? OR i.tombstone = 0)`); `tombstone_item` (`repository.py:330-374`) flips the flag and journals `deleted` without removing the row, so receipts stay resolvable. Probe P7a: evidence 1→0 after tombstoning, 1 again with `include_tombstoned=True`, row retained with `tombstoned_at` set |
| Retrieval grants no execution authority | **Holds** | `retrieve()` returns data only. A scan of `src/lee_kb` for `eval`, `exec`, `subprocess`, `os.system`, `popen`, `socket`, `urllib`, and `requests` matched one string literal in an error message (`governance.py:126`) and nothing else |
| No unapproved runtime dependencies (stdlib only) | **Holds** | `pyproject.toml:23-25` declares an empty runtime dependency list; `pytest`/`black`/`ruff` are dev extras. Probe P10 parsed every module under `src/lee_kb` with `ast` and checked each absolute import root against `sys.stdlib_module_names`: *none* third-party. `FORMAT_HANDLERS` registers no office parser, so the deferred `.docx`/`.xlsx`/`.pptx` scope pulled in nothing |
| `docs/golden-baseline.md` reflects the harness results | **Holds** | I rebuilt the harness projection independently (same roots, chunker, and governed `retrieve()`) and recomputed the metrics: hit-at-10 **20/20 (100.0%)**, hit-at-1 **17/20 (85.0%)**, **MRR 0.925**, negative controls **3/3** with `denied_count=1` on the unauthorized case. Every value matches `docs/golden-baseline.md:53-57`, and every per-question rank matches the table at `docs/golden-baseline.md:25-49` (ranks of 2 for `project-management-02`, `project-management-04`, and `architecture-02`; rank 1 elsewhere). Accurate, but unasserted — see **S1-R-13**, and see **S1-R-11** for why the number is not a representative bar |

## Findings

Twelve findings: two High (gate-failing), four Medium, six Low. Every one was
reproduced against the delivered code in this attempt; the probe scripts and
their captured output are named under Verification.

### S1-R-10 — High — Correctness / unhandled failure

**File:** `src/lee_kb/connectors/local_files.py`
**Location:** `LocalFilesConnector.discover()` (lines 286-301) vs.
`LocalFilesConnector._resolve()` (lines 433-447), consumed by
`main._sync_connector()` (line 180) and `main.cmd_sync()` (lines 257-259)

**Problem.** Discovery and fetch disagree about which objects exist.
`discover()` walks `root.path.rglob("*")` and accepts anything `is_file()`
returns true for — and `is_file()` follows symlinks. `_resolve()` then calls
`.resolve()` on the candidate and rejects it when the *resolved* target lies
outside the root (`local_files.py:438-442`). A symlink inside a configured root
is therefore discovered, reported by `list_changes()` as `created`, and raises
`ConnectorReadError` the moment `fetch()` touches it. `_sync_connector` calls
`fetch` unguarded, so the error reaches `cmd_sync`, which prints `sync failed`
and exits 1.

Reproduced end to end (`probe_high_findings.py`): with `notes/ok.md` and
`notes/shared.md` symlinked to a file outside the root —

```
discover() -> ['notes:ok.md', 'notes:shared.md']
list_changes(None) -> [('notes:ok.md', 'created'), ('notes:shared.md', 'created')]
fetch('notes:ok.md')     -> ok
fetch('notes:shared.md') -> ConnectorReadError: source_object_id escapes its root
`lee-kb sync` attempt 1: exit=1   projection: ['notes:ok.md']
`lee-kb sync` attempt 2: exit=1   projection: ['notes:ok.md']
```

Two properties make this High rather than Medium. The condition is **permanent**
— nothing removes the offending object from discovery, so every subsequent sync
fails identically. And the pass is **not rolled back**: `ok.md` sorted first was
committed and stayed committed, so the projection is left half-synchronized
while the command reports failure. The error names a `source_object_id`, not a
filesystem path the user can act on.

This blocks the top-ranked next action in `context.md` — importing the Employee
Zero corpus (~1,200 documents, 15 source roots). One symlink in any root stops
the entire import.

**Proposed fix.**

1. Make discovery and fetch agree on one containment rule: either have
   `discover()` resolve each candidate and skip (or explicitly report) files
   whose resolved target escapes the root, so an unfetchable object is never
   handed out; or treat a symlink inside a declared root as in-policy and relax
   `_resolve` accordingly. Either is defensible; the two must match.
2. Have `_sync_connector` catch `ConnectorReadError` per object, count it in
   `SyncSummary` as `skipped`, and report the skipped objects with their paths,
   so one bad object degrades the pass instead of ending it.
3. Add tests for a symlink pointing out of the root, and for a sync pass in
   which one object fails to fetch.

### S1-R-11 — High — Retrieval quality / incorrect normal-use behavior

**File:** `src/lee_kb/repository.py`
**Location:** `_fts_query()` (lines 806-812), consumed by
`SQLiteRepository.search()` (line 640)

**Problem.** `_fts_query` tokenizes the query with `\w+` and joins **every**
token with `AND`, including stopwords. Every word must occur in a single chunk
or the query returns nothing. This is a matching-policy choice, not a BM25
limitation — BM25 ranks an OR-set.

Reproduced against a document that plainly contains the answer
(`probe_high_findings.py`; the indexed text is *"The current state of Agent-Orch
is green: the orchestrator is running nightly and no step has failed this
week."*):

| Query | Evidence returned |
|---|---:|
| `What is the current state of Agent-Orch?` | **0** |
| `What is the present state of Agent-Orch?` | **0** |
| `How is Agent-Orch doing right now?` | **0** |
| `Please tell me the current state of Agent-Orch?` | **0** |
| `Agent-Orch state` (keywords only) | 1 |

The first row is the sharpest case: every content word of that question is in
the chunk, and the whole query still returns nothing because the single word
`What` is not. The FTS translation the probe printed:

```
"What" AND "is" AND "the" AND "current" AND "state" AND "of" AND "Agent" AND "Orch"
```

The same behavior reproduces on the golden projection (`probe_baseline.py`):
`what changed this week?` returns 1 evidence item, `What has changed this week?`
returns 0, `Could you tell me what changed this week please?` returns 0.

Two consequences:

1. **Normal use is silently wrong.** `lee-kb search "<question>"` prints
   `No evidence found.` (`main.py:299`) for a normally phrased question whose
   answer is indexed, and nothing in the output distinguishes "the corpus has no
   answer" from "one of your words was absent from the chunk". The v1 acceptance
   criterion in `context.md` is that the Chief of Staff can switch off the old
   `kb` commands without losing capability; question-shaped queries failing
   closed is a direct threat to it.
2. **It makes the recorded baseline unrepresentative.** The seed questions were
   drawn from the same documents they retrieve, so their tokens co-occur by
   construction — exactly the condition this matcher requires. The 85.0%
   hit-at-1 and 0.925 MRR figures are real (I reproduced them rank for rank),
   but they measure verbatim-token lookup, not question answering.
   `docs/golden-baseline.md:59-63` asks semantic retrieval to beat that bar; the
   bar as measured does not represent the workload it will be compared on.

**Proposed fix.** Change the matcher to `OR` with BM25 ranking (or FTS5 `NEAR` /
minimum-should-match), strip a small stopword set before building the query, and
keep the strict `AND` path available as an explicit mode. Add golden cases whose
questions are paraphrases rather than extracts, and re-record
`docs/golden-baseline.md` against them. Also distinguish, in the CLI's empty
result message, whether the query matched nothing or was filtered by permissions
or scope.

### S1-R-02 — Medium — Governance / audit integrity

**File:** `src/lee_kb/governance.py`
**Location:** receipt-persistence loop (lines 187-198) vs. the `fail_on_stale`
refusal (lines 204-205)

**Problem.** Receipts are persisted inside the evidence loop, before the
freshness refusal runs. With `FreshnessRequirement(fail_on_stale=True)` over
stale evidence, `retrieve()` raises `StaleEvidenceError` having already written
one receipt per candidate evidence item, so the ledger records evidence as
released to a caller who received an exception instead. Reproduced (probe P5):
receipt rows went 1 → 2 across a call that released nothing.

The direction is over-recording, not under-recording, so this is not a
disclosure defect — but a receipt claiming a release that never happened
undermines the ledger's value as the artifact an auditor reads.

**Proposed fix.** Reorder `retrieve()`: assemble evidence, compute the freshness
report, enforce `fail_on_stale`, and only then persist receipts. Add a test
asserting that a `StaleEvidenceError` leaves the receipt count unchanged.

### S1-R-12 — Medium — Governance / audit completeness

**File:** `src/lee_kb/governance.py`
**Location:** permission filter (lines 148-155) and `denied_count` (line 215);
`retrieval_receipts` schema (`repository.py:200-217`)

**Problem.** A denied or empty retrieval leaves nothing durable. `denied_count`
exists only on the in-memory `EvidenceBundle`; no row is written anywhere. Probe
P2: a non-owner querying a private item produced `denied_count=1` and **0**
persisted rows, and the golden harness's `negative-unauthorized` control behaves
identically. The ledger answers "what evidence was released?" but cannot answer
"did anyone attempt to reach evidence they were not entitled to?" — and repeated
denied attempts are precisely what an auditor of a governed retrieval platform
looks for.

This is consistent with the locked contract (`RetrievalReceipt` is defined per
released evidence item, `docs/sprint-1-contracts.md:236-259`) and is
acknowledged in `docs/golden-baseline.md:73-79`, so it is a scope gap rather
than a contract violation — but the gap sits in the audit story the product
sells.

**Proposed fix.** Add a query-level access record — query, principal, project,
retrieval timestamp, returned count, denied count — written on every governed
call including the empty and denied cases. It pairs naturally with the deferred
`permission_basis` field (`docs/sprint-1-contracts.md:386-390`).

### S1-R-05 — Medium — Governance / scoping

**File:** `src/lee_kb/contracts.py`
**Location:** `RetrieveRequest.__post_init__` (lines 463-466) and
`effective_projects` (lines 468-471)

**Problem.** `MetadataFilters.projects` widens the query scope and the only check
is that it contains `request.project`. No layer verifies that the principal is
entitled to the added projects. Reproduced (probe P6b): a request with
`project="default"` and `filters.projects=("default", "restricted")` returned
evidence from `restricted`. The guard that does exist works — probe P6c
confirmed a filter set omitting the request project is rejected, so the scope
cannot be silently *swapped*, only widened.

In the delivered single-user model this is bounded: every widened candidate must
still pass `SingleUserPermissionEvaluator.is_permitted`, so the widening
principal reaches only items it already owns or was granted. It is a tenancy
weakness, not a present authorization bypass. It becomes a real hole the moment
a multi-project, multi-principal evaluator lands, because
`docs/sprint-1-contracts.md:326-344` designates the project as the tenancy
boundary for customer deployments.

**Proposed fix.** Resolve Open Question 1 (`docs/sprint-1-contracts.md:382-385`)
before the second principal exists: either restrict v1 to exactly one project
per request, or require the `PermissionEvaluator` to authorize each project in
`effective_projects` and record the granted set on the bundle.

### S1-R-06 — Medium — Persistence / durability of a locked property

**File:** `src/lee_kb/repository.py`
**Location:** `_SCHEMA` `synchronization_journal` DDL (lines 189-198)

**Problem.** "Latest-state projection plus append-only sync journal" is a locked
decision in `context.md`, and the delivered code honors it. Nothing at the schema
level enforces it. Probe P7c: an ordinary `sqlite3` connection to the same file
ran `UPDATE synchronization_journal SET change_type='purged'` followed by
`DELETE FROM synchronization_journal`, taking the table from 2 rows to 0 with no
error. Every other structural invariant in this schema *is* enforced in the DDL
(`CHECK (tombstone IN (0,1))` at `repository.py:122`, foreign keys with
`ON DELETE CASCADE`, uniqueness), which makes the one table whose entire purpose
is immutability the only unguarded one.

**Proposed fix.** Add `BEFORE UPDATE` and `BEFORE DELETE` triggers on
`synchronization_journal` that `RAISE(ABORT, ...)`, matching the enforcement
level the rest of the schema already uses, and add a test asserting a direct
`DELETE` fails.

### S1-R-18 — Low — Packaging metadata contradicts the code

**File:** `pyproject.toml`
**Location:** `requires-python = ">=3.10"` (line 10) and the
`Programming Language :: Python :: 3.10` classifier (line 19)

**Problem.** `src/lee_kb/main.py:20` and
`src/lee_kb/connectors/local_files.py:62` both `import tomllib`, which is
standard library only from Python 3.11. On 3.10 the package installs cleanly and
then fails at import with `ModuleNotFoundError: No module named 'tomllib'` — on
the CLI entry point and on the connector, i.e. everything. `context.md` names
`~/.config/lee-kb/config.toml` a public contract and expects client deployments
to depend on this package, so the declared floor is not a cosmetic detail.

**Proposed fix.** Either raise `requires-python` to `>=3.11` and drop the 3.10
classifier, or add a `tomli` fallback import guarded on the version — the former
is consistent with the stdlib-only rule.

### S1-R-13 — Low — Tests / documentation drift

**File:** `tests/golden/test_golden_corpus.py`
**Location:** `test_positive_question_returns_expected_citation_and_token`
(lines 148-170)

**Problem.** `docs/golden-baseline.md:25-57` publishes a per-question rank table,
85.0% hit-at-1, and MRR 0.925. The harness asserts only that the expected source
and token appear *somewhere* in the governed top-10 (lines 155-165) — nothing
computes hit-at-1 or MRR, and nothing checks a rank. I recomputed the metrics
independently and they match exactly, so the document is accurate today; nothing
keeps it accurate. A ranking or chunking change would leave the harness green
while the published baseline drifts, and that baseline is the stated bar for
adopting semantic retrieval.

**Proposed fix.** Have the harness compute hit-at-1, hit-at-10, and MRR and
assert them against values pinned in the test or in `corpus.toml`.

### S1-R-14 — Low — Correctness / fragile reconstruction

**File:** `src/lee_kb/main.py`
**Location:** `_lookup_receipt_ids()` (lines 284-294)

**Problem.** The CLI recovers receipt IDs by reading *every* receipt in the
database and taking the last `len(bundle.evidence)` rows, then zipping them
positionally with the evidence. `retrieve()` discards the IDs `record_receipt()`
already returns (`governance.py:197`), so the CLI re-derives them from an
ordering assumption documented in a comment. Correct for today's single-process
CLI; wrong under any concurrent writer, including the Phase-2 MCP server named
in `context.md` — it would print receipt IDs belonging to another principal's
retrieval next to this one's evidence, which is exactly the mislabeling the
ledger exists to prevent.

**Proposed fix.** Have `retrieve()` return the persisted receipt IDs (a parallel
tuple, or a `chunk_id -> receipt_id` mapping on the bundle) and delete the tail
heuristic.

### S1-R-15 — Low — Dead code

**File:** `src/lee_kb/retrieval.py`
**Location:** `LexicalRetriever.__init__` (lines 36-43)

**Problem.** `self._clock` is assigned and never read; it became dead when the
S1-R-01 fix removed the evidence-producing path that used it.
`governance.py:144` still constructs the retriever with
`clock=lambda: retrieval_timestamp`, so the call site reads as though the
retriever participates in timestamping when it does not. Ruff does not flag it
because it is an attribute assignment rather than an unused local.

**Proposed fix.** Remove the `clock` parameter from `LexicalRetriever.__init__`
and the argument at the `governance.py:144` call site.

### S1-R-16 — Low — Connector configuration semantics

**File:** `src/lee_kb/connectors/local_files.py`
**Location:** `_matches()` (lines 244-249)

**Problem.** Include/exclude matching uses `fnmatchcase` against the
root-relative POSIX path, where `*` crosses directory separators. I confirmed
that `include = ["*.md"]` discovers `sub/deep.md` as well as `top.md`, which is
not what a user writing a top-level pattern expects; and the documented
`exclude = [".git/**"]` (`main.py:63`, `local_files.py:19`) works only because
`**` degenerates to `*` under `fnmatch`, not because recursive globbing is
implemented. Default-deny still holds and over-inclusion is confined to
registered text formats, so the impact is configuration surprise rather than
exposure — but across 15 real source roots, surprise about which files get
ingested is worth removing before the import.

**Proposed fix.** Either document the `fnmatch` semantics in the module docstring
and the starter config, or switch to recursive-glob semantics
(`PurePath.full_match`, or handle `**` distinctly from `*`).

### S1-R-17 — Low — Missing test for a security-relevant guard

**File:** `tests/test_local_connector.py`
**Location:** whole file — no case exercises `_resolve`'s containment guard at
`local_files.py:438-442`

**Problem.** `_resolve` rejects a `source_object_id` whose resolved path leaves
its root; that is the connector's containment guarantee. I confirmed it fires
for an out-of-root symlink target (probe above). No test covers it — the five
connector tests cover discovery, no-op resync, change detection, deletion, and
the include/exclude registry, none of them containment. The guard could be
weakened by a future change (including the S1-R-10 fix, which touches exactly
this code) with no test failing.

**Proposed fix.** Add tests asserting `ConnectorReadError` for relative-path
traversal out of the root and for an out-of-root symlink target, landing them
with the S1-R-10 fix so the two changes to this guard are pinned against each
other.

## Residual Risks

- **Deferred office-format handlers (`.docx`/`.xlsx`/`.pptx`).** `DocumentType`
  enumerates all three (`contracts.py:152-154`), but `FORMAT_HANDLERS`
  (`local_files.py:117-122`) registers only `.md`, `.markdown`, `.txt`, `.text`
  — I confirmed the registry contents directly. Per `context.md`, office formats
  are *deferred implementation, not deferred contract*, and remain required v1
  parity scope pending dependency approval (Open Question 2 / Next Action 3). The
  registry does genuinely support extension without redesign: a handler needs
  only a `document_type` and a `decode` callable. Three caveats for the approval:
  office extraction defines a new normalization, which changes every chunk ID it
  produces (`docs/sprint-1-contracts.md:391-395`); files matching an include
  pattern but lacking a handler are silently skipped by `discover()`
  (`local_files.py:297-299`) — I verified that a root containing only `.docx`
  files discovers nothing and syncs "successfully" with no explanation; and the
  parsing libraries are new runtime dependencies, which the stdlib-only rule and
  `AGENTS.md` put behind explicit human approval.
- **The CLI's principal is asserted, not authenticated.** `--principal` accepts
  any string (`main.py:360-361`), so anyone with read access to the SQLite file
  can retrieve as anyone. Correct for a single-user personal deployment where
  filesystem permissions are the real boundary — but this must not survive into
  a multi-user deployment or the Phase-2 MCP server, where the principal must
  arrive from an authenticated channel.
- **The golden corpus proves the harness, not retrieval quality.** Stated
  honestly in `docs/golden-baseline.md:1-7` and `context.md`. **S1-R-11**
  sharpens it: the seed questions were extracted from the documents they
  retrieve, which is the one condition the current matcher requires, so the
  corpus is structurally favorable to the retriever being measured. Curate the
  replacement *before* running any semantic-versus-lexical comparison.
- **The Employee Zero corpus has never been ingested.** Open Question 4 in
  `context.md` is accurate. Beyond S1-R-10, two behaviors are unmeasured at
  1,200-document scale: `LexicalRetriever._search_project` (`retrieval.py:63-76`)
  deliberately fetches to exhaustion with a doubling limit, rehydrating a full
  `KnowledgeItem` per row, so a common term over a large corpus materializes the
  whole match set before filtering; and `_sync_connector` re-encodes and rewrites
  the entire snapshot cursor once per changed object (`main.py:200-201`), which
  is O(n) work per item and O(n²) per full sync. Both are fine at fixture scale
  and should be measured on the first real import.
- **Receipts are written one transaction per evidence item.** `record_receipt`
  opens its own transaction (`repository.py:657`) and `retrieve` calls it inside
  the evidence loop, so a failure partway through leaves some receipts persisted
  and returns no bundle. Low likelihood locally; worth making the receipt set
  atomic with the bundle once the audit record is load-bearing.
- **Journal retention is unbounded.** Open Question 6
  (`docs/sprint-1-contracts.md:404-406`) is still open and correctly scoped — a
  non-issue at 1,200 documents, a real one under the email connector's
  re-ingest-on-every-reply pattern.
- **Freshness is reported but never enforced by default.** `is_stale` is true
  only when the caller sets `max_staleness` (`retrieval.py:126`), so the default
  CLI path prints an age and nothing more. That matches the locked decision
  ("freshness reporting makes staleness visible instead"), but nothing in the
  product surfaces a source root that silently stopped synchronizing.
- **Lint configuration is on a deprecated schema.** The preserved `ruff` run
  passed but warned that the top-level `select`/`ignore` keys
  (`pyproject.toml:51-52`) are deprecated in favour of `lint.select`/
  `lint.ignore`. Harmless today; it will become a hard error on a future ruff
  release and silently drop the configured rule set.

## Verification

Per this step's mission packet, `allow_validator_rerun` is **false**: I did not
re-execute any system-validator command. The validator results below are
summarized from the preserved evidence artifact at
`/home/lee/projects/lee-kb-agent-orch-runs/604128ba80f6/steps/step_10_independent_review/attempt-2/preserved-validator-evidence.json`
and are attributed to it. The checks in the first table are my own and were
executed in this attempt.

### Checks I executed

| Command | Exit | Result |
|---|---:|---|
| `env PYTHONPATH=src python3 .agent-orch-scratch/604128ba80f6/step_10_independent_review/attempt-2/probe_invariants.py` | 0 | Eleven invariant probes (P1–P11); individual results below |
| `env PYTHONPATH=src python3 .agent-orch-scratch/604128ba80f6/step_10_independent_review/attempt-2/probe_baseline.py` | 0 | Rebuilt the golden projection and recomputed the baseline: hit-at-10 20/20 (100.0%), hit-at-1 17/20 (85.0%), MRR 0.925, negative controls 3/3 (`denied_count=1` on the unauthorized case) — matching `docs/golden-baseline.md` value for value and rank for rank. Also showed paraphrase collapse: `what changed this week?` → 1 evidence, `What has changed this week?` → 0, `Could you tell me what changed this week please?` → 0 |
| `env PYTHONPATH=src python3 .agent-orch-scratch/604128ba80f6/step_10_independent_review/attempt-2/probe_high_findings.py` | 0 | Reproduced S1-R-10 (`lee-kb sync` exit 1 on two consecutive attempts, projection left holding only `notes:ok.md`) and S1-R-11 (four of five phrasings of a question the indexed document answers returned 0 evidence) |
| Inline `python3` probe (format registry, glob semantics) | 0 | `FORMAT_HANDLERS` = `['.markdown', '.md', '.text', '.txt']`; `include=["*.md","*.docx"]` discovered `r:sub/deep.md` and `r:top.md`; `include=["*.docx"]` discovered nothing |
| `grep -rnE "\b(eval\|exec\|subprocess\|os\.system\|popen\|urllib\|socket\|requests)\b" src/lee_kb` | 0 | One match, a string literal in an error message (`governance.py:126`) — no execution or network path in the retrieval product |

Individual results from `probe_invariants.py`:

| Probe | Result |
|---|---|
| P1 / P1b missing principal | `MissingPrincipalError` for both an omitted principal and an explicit `principal=None`; 0 receipt rows |
| P2 unauthorized principal | 1 raw repository candidate, governed `evidence=0`, `denied_count=1`, receipt rows 0→0 |
| P3 / P3b receipt fields | 1 evidence item, rows 0→1, all eight locked fields correct, persisted row equals returned receipt, citations and receipts mirror evidence |
| P4 `PROJECT` visibility | `evidence=0`, `denied_count=1`; 1 evidence only after a `PUBLIC` item was added — `PROJECT` is not an implicit grant |
| P5 / P5b `fail_on_stale` | `StaleEvidenceError` raised; receipt rows 1→2 for zero released evidence (**S1-R-02**). Freshness triplet readable on a normal call |
| P6a / P6b / P6c project scope | narrow scope → `['default']`; widened scope → `['default', 'restricted']` (**S1-R-05**); a filter set omitting the request project is rejected |
| P7a / P7b tombstone + journal | evidence 1→0, 1 with `include_tombstoned`, row retained with `tombstoned_at`; journal `['created', 'deleted']` |
| P7c journal mutability | `UPDATE` + `DELETE` from a plain `sqlite3` connection took the journal 2→0 rows (**S1-R-06**) |
| P8 repeat sync | journal 1 row → 1 row after an identical resync; `['created','updated']` after a real edit |
| P9 chunk/item project mismatch | rejected at write time (`a chunk project must match its owning item`) |
| P10 dependency scan | AST scan of `src/lee_kb` against `sys.stdlib_module_names`: third-party runtime imports **none** |
| P11 evidence-surface sweep | `[('lee_kb.governance', 'retrieve'), ('lee_kb.main', 'governed_retrieve')]` — the same function object under an alias (`main.py:35`); one public evidence surface |

### System-validator results (preserved record — not re-executed by me)

Fourteen records are preserved; thirteen passed and one failed.

| Command | Exit | Recorded outcome | Source step |
|---|---:|---|---|
| `python3 -m pytest tests/` | 2 | `1 error in 0.09s` — collection `ModuleNotFoundError: No module named 'lee_kb'` | step_01_define_contracts, attempt 1 |
| `env PYTHONPATH=src python3 -c "from lee_kb import contracts"` | 0 | no output | step_01_define_contracts, attempt 1 |
| `python3 -m pytest tests/` | 0 | `51 passed in 0.12s` | step_01_define_contracts, attempt 2 |
| `env PYTHONPATH=src python3 -c "from lee_kb import contracts"` | 0 | no output | step_01_define_contracts, attempt 2 |
| `python3 -m pytest tests/test_repository.py tests/test_contracts.py` | 0 | `54 passed in 0.51s` | step_03_sqlite_repository |
| `python3 -m pytest tests/test_local_connector.py tests/test_repository.py` | 0 | `10 passed in 0.79s` | step_04_local_file_connector |
| `python3 -m pytest tests/test_retrieval.py tests/test_local_connector.py` | 0 | `12 passed in 0.80s` | step_05_chunking_lexical |
| `python3 -m pytest tests/test_governance.py tests/test_retrieval.py` | 0 | `12 passed in 0.88s` | step_06_governance_receipts |
| `python3 -m pytest tests/` | 0 | `82 passed in 3.07s` | step_07_cli_surface |
| `env PYTHONPATH=src python3 -m lee_kb.main --help` | 0 | help text printed | step_07_cli_surface |
| `python3 -m pytest tests/golden/` | 0 | `24 passed in 1.98s` | step_08_golden_corpus |
| `python3 -m pytest` | 0 | `106 passed in 5.39s` | step_09_full_verification_docs |
| `python3 -m black --check src tests` (recorded as `BLACK_NUM_WORKERS=1 …`) | 0 | `18 files would be left unchanged.` | step_09_full_verification_docs |
| `python3 -m ruff check src tests` | 0 | `All checks passed!`, with a deprecation warning about top-level `select`/`ignore` | step_09_full_verification_docs |

The one failure is the earliest record — `python3 -m pytest tests/` on
`step_01_define_contracts` attempt 1, failing collection because `src` was not on
the path before the package existed. The same command at exit 0 on attempt 2 of
that step supersedes it, and the full suite is recorded green
(`106 passed`) at the reviewed commit.

No implementation file was modified during this review. All writes were confined
to `code-reviews/`; probe scripts and their captured output live under
`.agent-orch-scratch/604128ba80f6/step_10_independent_review/attempt-2/`.

## Remediation Roadmap

### Fix Now (gate-failing)
- **S1-R-10** — reconcile `discover()`/`_resolve()` and make `_sync_connector`
  skip-and-report instead of aborting. Blocks the real-corpus import.
- **S1-R-11** — replace AND-of-all-tokens matching, then re-record the baseline
  against paraphrased questions.

### Fix Soon
- **S1-R-02** — enforce `fail_on_stale` before persisting receipts.
- **S1-R-12** — add a query-level access record covering denied and empty calls.
- **S1-R-06** — add append-only triggers to `synchronization_journal`.
- **S1-R-05** — resolve Open Question 1 before a second principal exists.
- **S1-R-18** — correct the declared Python floor.

### Fix Later
- **S1-R-13** — assert the golden metrics in the harness.
- **S1-R-14** — return receipt IDs from `retrieve()`.
- **S1-R-16** — fix or document glob semantics.
- **S1-R-15** — remove the dead clock.

## Test Additions Recommended

- [ ] Symlink inside a configured root: `discover()` and `fetch()` agree (S1-R-10).
- [ ] One unfetchable object does not abort a sync pass; it is counted and reported (S1-R-10).
- [ ] Root-escape guard: relative traversal and out-of-root symlink both raise (S1-R-17).
- [ ] Paraphrased and stopword-bearing questions return the evidence they should (S1-R-11).
- [ ] `StaleEvidenceError` leaves the receipt count unchanged (S1-R-02).
- [ ] A denied retrieval leaves a durable access record (S1-R-12).
- [ ] Direct `DELETE`/`UPDATE` against `synchronization_journal` is rejected (S1-R-06).
- [ ] Golden harness computes and asserts hit-at-1, hit-at-10, and MRR (S1-R-13).
- [ ] A root containing only unhandled formats reports why nothing was ingested (residual risk).
