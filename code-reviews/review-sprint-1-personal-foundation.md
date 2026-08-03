# Code Review — Sprint 1: Personal Foundation

**Reviewer role:** independent Reviewer (`agents/reviewer.md`, `skills/code-review.md`)
**Date:** 2026-08-03
**Scope reviewed:** `src/lee_kb/` (contracts, connectors, repository, chunking,
retrieval, governance, CLI), `tests/`, `tests/golden/`,
`docs/sprint-1-contracts.md`, `docs/golden-baseline.md`, `result-review.md`.
**Verdict:** **fail** — one High finding. The delivered governed path is sound;
the package also ships a second, ungoverned evidence path beside it.

## Architecture Summary

One vertical slice is delivered end to end: `LocalFilesConnector` discovers and
fetches Markdown/plain-text files declared in a `sources.toml`-shaped config,
`chunk_document` produces deterministic heading- or paragraph-aligned chunks,
`SQLiteRepository` persists a latest-state projection plus an append-only
synchronization journal and a retrieval-receipt ledger, and
`governance.retrieve()` composes permission evaluation, BM25 lexical retrieval,
evidence assembly, freshness reporting, and receipt persistence into one call.
`lee-kb init｜sync｜search` is the v1 surface and uses the governed call.

### Invariants verified against code

| Invariant | Result | Evidence |
|---|---|---|
| Authorization is fail-closed | **Holds** on the governed path | `governance.py:124-128` raises `MissingPrincipalError` before any repository access; `SingleUserPermissionEvaluator.is_permitted` (`governance.py:85-97`) grants only owner, explicit principal, group intersection, or `PUBLIC` — `PROJECT` visibility is deliberately not an implicit grant |
| Authorization precedes evidence assembly | **Holds** on the governed path | `governance.py:148-155` filters provider candidates; `Evidence`/`Citation`/`RetrievalReceipt` construction starts at line 160, after the filter |
| …on every public path | **Fails** | see finding **S1-R-01** |
| Receipts written for every retrieval, with the locked fields | **Partially holds** | `governance.py:187-198` persists one `RetrievalReceipt` per evidence item via `repository.record_receipt`; the record carries item ID, chunk ID, content hash, source locator, retrieval timestamp, principal, project, and query (`contracts.py:583-617`, persisted in full at `repository.py:656-688`), matching the locked identity decision and `docs/sprint-1-contracts.md:236-256`. Gaps: **S1-R-01** (a public path persists none) and **S1-R-02** (receipts survive a refused retrieval) |
| Provenance survives end to end | **Holds** | `SourceLocator` is captured at fetch (`connectors/local_files.py:379-394`), stored (`repository.py:389-434`), rehydrated (`repository.py:709-743`), and reaches both `Citation` and `RetrievalReceipt`; `contracts.py:314-317` forbids a locator whose connector disagrees with the item ID |
| Freshness triplet survives end to end | **Holds** | `source_timestamp` + `sync_timestamp` on every `Evidence`, `retrieval_timestamp` on the bundle and on every receipt; all three are round-tripped through SQLite as ISO-8601 and re-parsed (`repository.py:733-734`, `794`); `contracts.py:100-104` rejects naive datetimes. Asserted by `tests/test_retrieval.py:148-160` |
| Identity follows the locked tuples | **Holds** | `KnowledgeItemId(connector_id, source_object_id)` and `ChunkId(item_id, chunk_ordinal, content_hash)` (`contracts.py:230-273`); the repository's primary keys mirror them (`repository.py:107-160`); `tests/test_contracts.py:167-201` covers them |
| Project scoping is enforced | **Holds for narrowing; does not prevent widening** | `project` is non-defaulted on `KnowledgeItem`, `Chunk`, `JournalEntry`, and `RetrieveRequest`; `repository.search` constrains `i.project = ?` (`repository.py:640`); `EvidenceBundle.__post_init__` rejects evidence outside `request.effective_projects` (`contracts.py:657-663`). See finding **S1-R-05** |
| Sync journal is append-only | **Holds in code; unenforced in the schema** | only `INSERT` touches `synchronization_journal` (`repository.py:519-536`). See finding **S1-R-06** |
| Tombstones exclude items from search | **Holds** | `repository.py:641` (`AND (? OR i.tombstone = 0)`); `tombstone_item` never hard-deletes, so receipts stay resolvable (`repository.py:330-374`). Confirmed by probe (PROBE4: 1 → 0 evidence after tombstone) and `tests/test_repository.py:109` |
| No unapproved runtime dependencies | **Holds** | `pyproject.toml:23-25` declares no runtime dependencies; an AST scan of `src/` found zero non-stdlib imports |

## Findings

Nine findings. One High (gate-failing), four Medium, four Low. Every finding
below was reproduced against the delivered code, not inferred from reading it;
the probe script and its output are described under Verification.

### S1-R-01 — High — Governance / unauthorized evidence

**File:** `src/lee_kb/retrieval.py`
**Location:** `LexicalRetriever.retrieve()` (lines 65-133) and the module-level
`retrieve()` (lines 151-164), both exported in `__all__` (line 26)

**Problem.** The package ships two public functions named `retrieve` that
return the same type. `governance.retrieve()` is governed.
`retrieval.retrieve()` is not: it performs **no permission evaluation** and
**persists no receipts**. It mints `RetrievalReceipt` objects (lines 104-115)
and returns them inside a contract-valid `EvidenceBundle`, but never calls
`repository.record_receipt`, so the bundle carries receipt-shaped objects that
exist nowhere in the audit ledger.

Reproduced: with one `PRIVATE` item owned by `lee`, principal `mallory` got
**0 evidence and `denied_count=1`** through `governance.retrieve()`, and
**1 evidence item containing the full private text** through
`retrieval.retrieve()`. Receipt rows persisted by that call: **0**.

This contradicts three governing statements: the AGENTS.md product invariant
"Enforce authorization before evidence reaches an AI model"; the locked
decision "Library is the product; CLI is the v1 surface; MCP server is Phase 2
— all surfaces exercise the same public retrieval API" (`context.md`); and the
receipt invariant this sprint claims (`result-review.md:28-31`). Nothing in the
delivered CLI uses this path, so **no shipped surface currently leaks** — the
severity is that the Phase-2 MCP author, or any library consumer, finds a
public `retrieve(repository, request) -> EvidenceBundle` that is
indistinguishable by shape from the governed one. `retrieval.py:1-7` warns that
"callers must permission-filter", but a docstring is not a control, and no test
asserts this path denies anyone.

**Proposed fix.** Reduce `LexicalRetriever` to a candidate provider: keep
`search()`, remove `LexicalRetriever.retrieve()` and the module-level
`retrieve()` from `__all__` (or delete them outright — `governance.retrieve()`
already duplicates their body). Move `tests/test_retrieval.py`'s bundle-level
assertions onto the governed call. Add a test that iterates every public
bundle-producing entry point and asserts an unauthorized principal receives no
evidence from any of them.

### S1-R-02 — Medium — Governance / receipt accuracy

**File:** `src/lee_kb/governance.py`
**Location:** `retrieve()`, lines 187-205

**Problem.** Receipts are persisted inside the evidence loop (line 197), then
the `fail_on_stale` check runs (lines 204-205) and can raise
`StaleEvidenceError`. The caller receives nothing, but the receipt rows remain.
Reproduced: a `fail_on_stale=True` request raised `StaleEvidenceError` and left
**1 additional receipt row** recording an evidence release that never happened.
The ledger is the artifact that answers "what evidence left the platform"; it
now over-reports.

**Proposed fix.** Compute the freshness report and evaluate the `fail_on_stale`
gate before writing any receipt, or persist the receipt batch inside a single
repository transaction that the stale check can abort.

### S1-R-03 — Medium — Packaging / correctness on a declared-supported runtime

**File:** `pyproject.toml`
**Location:** `requires-python = ">=3.10"` (line 10) and the
`Programming Language :: Python :: 3.10` classifier (line 19)

**Problem.** `src/lee_kb/main.py:20` and
`src/lee_kb/connectors/local_files.py:62` import `tomllib`, which is standard
library only from Python 3.11. On a 3.10 interpreter — which the package
declares it supports and pip will happily install onto — both the CLI and the
local-file connector fail at import with `ModuleNotFoundError`. The verification
evidence for this sprint was produced on 3.12, so the suite cannot catch it.

**Proposed fix.** Set `requires-python = ">=3.11"` and drop the 3.10 classifier.
A `tomli` fallback for 3.10 would be a new runtime dependency and needs the
approval this project requires.

### S1-R-04 — Medium — Evaluation / documented baseline is not enforced

**File:** `docs/golden-baseline.md`
**Location:** the per-question rank table (lines 25-49) and the Baseline
section (lines 51-57), against `tests/golden/test_golden_corpus.py:148-170`

**Problem.** The document records 85.0% hit-at-1, 0.925 MRR, and a rank per
question, and states these are the numbers semantic retrieval must beat. The
harness asserts only that the expected source and token appear **somewhere in
the governed top-10** (`matching_evidence` is truthy). Nothing computes or
asserts hit-at-1 or MRR. Every positive question could regress from rank 1 to
rank 10 and the suite would stay green while the document still claims 0.925
MRR. The recorded ranks are a manual transcription, not generated evidence —
which is exactly the property a baseline needs before it is used as an
adoption gate for a future retriever.

**Proposed fix.** Have the harness compute hit-at-1 and MRR from the returned
`fused_rank`s, assert a floor, and write the per-question table as a generated
artifact so the document cannot drift from the harness.

### S1-R-05 — Medium — Governance / project scoping widens rather than narrows

**File:** `src/lee_kb/contracts.py`
**Location:** `RetrieveRequest.__post_init__` (lines 463-466) and
`effective_projects` (lines 468-471), consumed at `retrieval.py:57-60`

**Problem.** `MetadataFilters.projects` is documented as a filter but behaves
as a scope *replacement*: `effective_projects` returns the filter list when set,
and validation only requires that the list **contain** the request project.
Reproduced: `project="default"` with
`filters=MetadataFilters(projects=("default", "restricted"))` returned evidence
from `restricted`. With no principal→project entitlement model in v1, whether a
retrieval stays inside its project rests entirely on the caller. This is a
known gap — `docs/sprint-1-contracts.md:382-385` raises it as Open Question 1 —
but it is unresolved in delivered code and the CLI exposes `--project` freely.

**Proposed fix.** Until an entitlement basis exists, intersect instead of
replace: `effective_projects` should never exceed `{request.project}`, and any
filter project outside it should be rejected at construction. Add a test that a
filter cannot reach a project the request did not scope.

### S1-R-06 — Low — Persistence / append-only is a convention, not a constraint

**File:** `src/lee_kb/repository.py`
**Location:** `synchronization_journal` DDL (lines 189-198)

**Problem.** The journal is append-only because the code only inserts. The
schema permits `UPDATE` and `DELETE`. Reproduced: a single
`DELETE FROM synchronization_journal` through the repository's own connection
removed all 3 rows. A future migration, a repair script, or a consumer holding
the same SQLite file can silently erase the record of what changed.

**Proposed fix.** Add `BEFORE UPDATE` and `BEFORE DELETE` triggers on
`synchronization_journal` (and, for the same reason, on `retrieval_receipts`)
that `RAISE(ABORT, 'journal is append-only')`.

### S1-R-07 — Low — Correctness / receipt IDs are inferred, not returned

**File:** `src/lee_kb/main.py`
**Location:** `_lookup_receipt_ids`, lines 284-294

**Problem.** The CLI reads the **entire** `retrieval_receipts` table on every
search (`repository.list_receipts()`), takes the last *n* rows, and zips them
positionally with the evidence. It is correct only while nothing else writes
receipts, and it loads the full receipt history into memory on every query — a
cost that grows without bound as the ledger is used as intended.

**Proposed fix.** Have `governance.retrieve()` return the persisted receipt IDs
(or add `Repository.record_receipts()` returning the batch of IDs) and hand
them to the printer instead of inferring them.

### S1-R-08 — Low — Design / cross-module private import

**File:** `src/lee_kb/governance.py`
**Location:** line 39, `from .retrieval import _freshness_report`

**Problem.** The governed surface depends on a name the retrieval module marks
private and excludes from `__all__`. Once S1-R-01's fix trims
`retrieval.retrieve()`, this is the only remaining coupling — and it is the
fragile kind.

**Proposed fix.** Promote it to `freshness_report()` in `retrieval.__all__`, or
move it to a shared `freshness` module both import.

### S1-R-09 — Low — Failure handling / unhandled error paths in the CLI

**File:** `src/lee_kb/main.py`
**Location:** `cmd_search`, lines 363-375

**Problem.** Only `MissingPrincipalError` is caught. `sqlite3.DatabaseError` on
a corrupt or foreign projection, and `StaleEvidenceError` once freshness flags
are exposed, reach the user as a traceback. `cmd_sync` handles its equivalents
(lines 257-259); `cmd_search` does not.

**Proposed fix.** Catch `sqlite3.Error` and `StaleEvidenceError` in `cmd_search`
and report them the way the "no synchronized knowledge found" path already
does.

### What is correct and worth keeping

- Fail-closed defaults are genuine, not decorative: `PermissionSet` defaults to
  `PRIVATE` with empty allow lists (`contracts.py:193-212`), `PROJECT`
  visibility is explicitly *not* an implicit grant (`governance.py:72-83`), and
  the connector's include/exclude matching is default-deny
  (`connectors/local_files.py:244-249`).
- `EvidenceBundle.__post_init__` (`contracts.py:638-674`) is the strongest
  control in the codebase: it makes evidence without a citation, evidence
  without a receipt, a receipt for a different principal, evidence outside the
  request scope, and mis-ordered ranks all structurally unrepresentable.
- Change detection uses content hashes rather than mtimes
  (`connectors/local_files.py:326-359`), and the cursor advances in the same
  transaction as the content it describes (`repository.py:289-328`), so a
  partial sync is resumable rather than silently incomplete — covered by
  `tests/test_repository.py:144`.
- Tombstone-then-resync correctly journals a new `CREATED` event rather than an
  `UPDATED` one (`repository.py:303-311`).
- The golden harness's negative controls are real controls: the out-of-scope
  and unauthorized cases first prove the matching evidence *exists* outside the
  permitted path before asserting the governed call returns nothing
  (`tests/golden/test_golden_corpus.py:188-221`).
- Documentation is honest about what was not done: `result-review.md:97-100`
  and `docs/golden-baseline.md:1-7` both state plainly that the corpus is a
  generated seed proving the harness, and that no real Employee Zero import has
  run.

## Residual Risks

1. **Deferred office-format handlers (`.docx`/`.xlsx`/`.pptx`).**
   `DocumentType` enumerates them (`contracts.py:147-156`) but `FORMAT_HANDLERS`
   registers only `.md`, `.markdown`, `.txt`, `.text`
   (`connectors/local_files.py:117-122`). Unregistered suffixes are silently
   skipped during `discover()` (`local_files.py:297-299`) — a user pointing a
   root at a folder of Word documents gets `0 created` and no warning that
   anything was ignored. The contract and registry are genuinely extensible, so
   this is deferred implementation as `context.md` records, not a redesign risk;
   the *silence* is the risk. Consider reporting skipped-by-format counts in the
   sync summary. This also blocks the stated v1 parity criterion until the
   parsing libraries are approved.
2. **The curated golden benchmark does not exist yet.** The seed corpus draws
   its questions from this repository's own documents, so editing
   `product-definition.md` or `architecture.md` can move the baseline. Combined
   with S1-R-04, the recorded rank-quality numbers should not yet be treated as
   a load-bearing adoption gate for semantic retrieval.
3. **No real-corpus run.** Sprint 1 was verified against fixtures and a manual
   scratch corpus. `LexicalRetriever._search_project` deliberately fetches to
   exhaustion, doubling the SQL `LIMIT` until the result set is short
   (`retrieval.py:135-148`); on ~1,200 documents with a common term this reads
   every matching chunk and its item and permission rows into Python on every
   query. That is a correctness-motivated choice, but its cost is unmeasured at
   Employee Zero scale.
4. **The principal is caller-asserted.** `lee-kb search --principal <anyone>`
   (`main.py:360`) sets the identity that authorization is evaluated against,
   with no authentication. This is inherent to a personal CLI on a
   single-user machine, and matches the locked "CLI defaults to Lee" decision —
   but the fail-closed evaluator provides no protection against the local
   caller. Any multi-user or service surface must supply an authenticated
   principal, never a flag.
5. **Tombstoned content stays retrievable behind a flag.**
   `include_tombstoned=True` returns chunks of items deleted at the source
   (confirmed by probe), with no policy gate and no distinct marking in CLI
   output. Correct per the "tombstone, not purge" decision, but "deleted at the
   source yet still quotable" needs a governance answer before a consumer
   surface exposes the flag.
6. **The receipt does not record why access was granted.** Documented as
   Open Question 2 in `docs/sprint-1-contracts.md:386-390`. Until a
   `permission_basis` field exists, a receipt proves *that* a principal received
   a chunk, not under which grant — which limits its value in an audit.
7. **Single-writer assumptions.** `SQLiteRepository` opens a plain connection
   with no busy timeout or WAL mode (`repository.py:224-228`), and S1-R-07's
   receipt-ID inference assumes no concurrent writer. Fine for one CLI process;
   not yet safe for the Phase-2 MCP server.
8. **`sync` reports `unchanged` by subtraction.** `main.py:212` computes
   `unchanged = len(discovered) - created - updated`, which is accurate only
   while `discover()` and `list_changes()` see an identical file set. A file
   created between the two scans makes the count wrong rather than the sync
   wrong.

## Verification

`skills/code-review.md` Phase 1 requires running the project's checks before
judging quality. Under this run's evidence policy, the product-validation
commands below were executed independently by the Agent-Orch system validator
and are **preserved, not re-executed by this review** (validator rerun is not
permitted for this step). They are summarized from
`preserved-validator-evidence.json`. The last two rows are checks this review
ran itself, because no preserved record covers them.

| Command | Exit | Result | Source |
|---|---:|---|---|
| `python3 -m pytest` | 0 | 106 passed | preserved (`step_09_full_verification_docs`) |
| `python3 -m pytest tests/golden/` | 0 | 24 passed | preserved (`step_08_golden_corpus`) |
| `python3 -m pytest tests/` | 0 | passed | preserved; note one earlier record for this command is exit 2 (`step_01_define_contracts` attempt-1), superseded by the passing later attempt |
| `python3 -m pytest tests/test_repository.py tests/test_contracts.py` | 0 | 54 passed | preserved (`step_03_sqlite_repository`) |
| `python3 -m pytest tests/test_local_connector.py tests/test_repository.py` | 0 | 10 passed | preserved (`step_04_local_file_connector`) |
| `python3 -m pytest tests/test_retrieval.py tests/test_local_connector.py` | 0 | 12 passed | preserved (`step_05_chunking_lexical`) |
| `python3 -m pytest tests/test_governance.py tests/test_retrieval.py` | 0 | 12 passed | preserved (`step_06_governance_receipts`) |
| `python3 -m black --check src tests` | 0 | clean | preserved (`step_09_full_verification_docs`) |
| `python3 -m ruff check src tests` | 0 | clean | preserved (`step_09_full_verification_docs`) |
| `env PYTHONPATH=src python3 -m lee_kb.main --help` | 0 | CLI help renders | preserved (`step_07_cli_surface`) |
| `env PYTHONPATH=src python3 -c "from lee_kb import contracts"` | 0 | imports cleanly | preserved (`step_01_define_contracts`) |
| `python3 .agent-orch-scratch/92579701f324/step_10_independent_review/attempt-1/depscan.py` | 0 | `third-party runtime imports: none` — AST scan of every module under `src/` against `sys.stdlib_module_names` | this review |
| `env PYTHONPATH=src python3 .agent-orch-scratch/92579701f324/step_10_independent_review/attempt-1/probe.py` | 0 | five invariant probes, output below | this review |

The suite is green and the tests are substantive: 106 tests covering repeated
sync, changed source, deleted source, denied evidence, empty input, missing
principal, out-of-project evidence, and cursor non-advance on failure. What
the suite does **not** cover is what this review's probes target — the behavior
of the *ungoverned* public path, and the invariants that hold only by
convention.

### Probe script and results

`probe.py` (written to this step's scratch directory, outside the governed
write scope) builds a temporary SQLite projection containing one `PRIVATE`
item owned by `lee` in project `default` and one item in project `restricted`,
then exercises five behaviors. Verbatim output:

```
PROBE1 governed evidence: 0
PROBE1 governed denied_count: 1
PROBE1 ungoverned evidence: 1
PROBE1 ungoverned text leaked: ['zebraflux payroll numbers.']
PROBE1 ungoverned receipts in bundle: 1
PROBE1 receipts persisted in repo: 0
PROBE2 raised: StaleEvidenceError
PROBE2 receipts written despite refusal: 1
PROBE3 projects reached: ['default', 'restricted']
PROBE4 default evidence after tombstone: 0
PROBE4 include_tombstoned evidence: 1
PROBE5 journal rows 3 -> 0 after DELETE
```

- **PROBE1** → S1-R-01. `governance.retrieve()` denied principal `mallory`;
  `retrieval.retrieve()` returned the private text to the same principal and
  persisted zero receipts.
- **PROBE2** → S1-R-02. A refused (`fail_on_stale`) retrieval still wrote a
  receipt.
- **PROBE3** → S1-R-05. `filters.projects` reached outside the request project.
- **PROBE4** → confirms the tombstone invariant holds by default, and documents
  Residual Risk 5.
- **PROBE5** → S1-R-06. The journal accepted a `DELETE`.

### Reviewer conduct

No implementation file was modified. All writes are confined to
`code-reviews/`; the probe and dependency-scan scripts live in this step's
scratch directory.

## Remediation Roadmap

### Fix Now (before the sprint is closed)

- **S1-R-01** — remove or privatize the ungoverned `retrieve()` path and add a
  test asserting every public bundle-producing entry point denies an
  unauthorized principal.

### Fix Soon

- **S1-R-02** — evaluate freshness before persisting receipts.
- **S1-R-03** — raise `requires-python` to `>=3.11`.
- **S1-R-04** — compute and assert hit-at-1 / MRR in the golden harness.
- **S1-R-05** — make `filters.projects` narrow rather than widen.

### Fix Later

- **S1-R-06** — append-only triggers on the journal and receipt tables.
- **S1-R-07** — return receipt IDs from `retrieve()`.
- **S1-R-08** — make `_freshness_report` a public or shared name.
- **S1-R-09** — handle `sqlite3.Error` and `StaleEvidenceError` in `cmd_search`.

## Test Additions Recommended

- [ ] For every public function returning an `EvidenceBundle`, assert an
      unauthorized principal receives no evidence (closes S1-R-01 permanently).
- [ ] Assert that a `fail_on_stale` refusal leaves the receipt ledger unchanged.
- [ ] Assert `filters.projects` cannot reach a project outside `request.project`.
- [ ] Assert `UPDATE`/`DELETE` on `synchronization_journal` is rejected.
- [ ] Golden harness: assert a hit-at-1 and MRR floor, and generate the
      per-question table consumed by `docs/golden-baseline.md`.
- [ ] Connector: assert that files whose suffix has no registered handler are
      reported as skipped rather than silently dropped.
