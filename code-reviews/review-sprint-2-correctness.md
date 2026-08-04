# Code Review — Sprint 2 Correctness and Performance Repairs

**Reviewed at:** `19b8d4d` (working tree clean apart from this review's own files)
**Reviewer role:** independent Reviewer (`agents/reviewer.md`, `skills/code-review.md`)
**Subject:** the S2-R-04 (nested/overlapping-root correctness), S2-R-03 (single
discovery pass per sync) and S1-R-16 (golden baseline as an executable
contract) repairs, the post-repair real-corpus re-measurement recorded in
`evidence/real-corpus-parity-report.md`, and the project-memory updates that
describe them.

**Publication-safety note.** This review is itself a tracked file in a public
repository. It reproduces only root names, counts, timings, commit hashes, and
paths inside this repository. Where a finding concerns a disclosed host path,
the path is described, never quoted.

## Architecture Summary

`LocalFilesConnector.__init__` resolves every configured root once
(`_resolved_paths_by_name`, `local_files.py:619`) and precomputes overlapping
pairs (`_find_nested_roots`, `:588`). `discover_report()` (`:645`) walks each
root, applies `GLOBAL_DEFAULT_DENY` → `include` → `exclude`, enforces symlink
containment, and then asks `_claiming_root` (`:715`) which single root owns the
resolved file — deepest resolved root wins, equal-depth ties broken by root
name — so a file inside an overlap region is emitted by exactly one root and its
`source_object_id` stays stable. `health()` (`:844`) appends the detected nested
pairs to its detail string, and `cmd_sync` (`main.py:351`) prints that detail to
stderr before every sync.

`_sync_connector` (`main.py:230`) now calls `connector.discover_report()`
exactly once (`:239`) and derives the change list from that single report via
`_changes_from_objects` (`:167`), which reimplements the connector's
snapshot-cursor diff plus the root filter that `_sync_connector` previously
applied afterwards. `connector.list_changes()` is no longer on the sync path.

`tests/golden/test_golden_corpus.py::test_recorded_baseline_metrics_are_enforced_by_the_harness`
recomputes hit-at-1 / hit-at-10 / MRR over the 20 positive golden questions
through `governance.retrieve()` and compares them symmetrically (`math.isclose`,
`abs_tol=0.01`) against values parsed live out of `docs/golden-baseline.md`
(`_parse_recorded_baseline`).

The retrieval path is untouched: `git diff 7e74e56..HEAD --` over
`governance.py`, `retrieval.py`, `repository.py` and `contracts.py` is empty.

## Checks Run

Preserved system-validator records (independently executed by the platform;
validator rerun is not permitted for this step, `allow_validator_rerun: false`,
so these are summarized from the preserved artifact, not re-executed):

| Command | Step | Result |
|---------|------|--------|
| `python3 -m pytest tests/` | `step_01` (S2-R-04) | exit 0 — 130 passed in 10.48s |
| `python3 -m pytest tests/` | `step_02` (S2-R-03) | exit 0 — 131 passed in 10.92s |
| `python3 -m pytest tests/golden/` | `step_03` (S1-R-16) | exit 0 — 25 passed in 7.51s |
| `python3 -m pytest tests/` | `step_04` (re-measurement) | exit 0 — 132 passed in 11.97s |
| `python3 -m pytest` | `step_05` (verification) | exit 0 — 132 passed in 12.12s |
| `python3 -m black --check src tests tools` | `step_05` | exit 0 — 19 files would be left unchanged |
| `python3 -m ruff check src tests tools` | `step_05` | exit 0 — all checks passed, with the `pyproject.toml` linter-settings deprecation warning (open finding S2-R-10) |

Checks this reviewer executed:

| Command | Result |
|---------|--------|
| `pytest …::test_recorded_baseline_metrics_are_enforced_by_the_harness` | exit 0 — 1 passed (control before mutation testing) |
| Same test, mutant retriever reversing the provider's final order | exit 1 — 1 failed, `operational-01 lost its top-10 citation entirely` |
| Same test, mutant demoting exactly one question from rank 1 to rank 2 | exit 1 — 1 failed, `hit_at_1 drifted … observed 0.5500, recorded 0.6000` |
| Same test, `BASELINE_DOC_PATH` redirected to a copy edited to 80.0% | exit 1 — 1 failed, `observed 0.6000, recorded 0.8000` |
| Same test, `BASELINE_DOC_PATH` redirected to a copy with the hit-at-1 bullet deleted | exit 1 — 1 failed, `Could not parse the Baseline section…` |
| Reviewer probe: overlapping-root claiming, determinism, order independence, identical-path tie-break, scoped discovery | exit 0 — Verification 1 |
| Reviewer probe: instrumented five-pass sync (`discover_report`, `rglob`, `git check-ignore`, hashes, `fetch`) plus cursor / tombstone / skip-and-report / token-tripwire behaviour | exit 0 — Verification 2 |
| Reviewer probe: read-only re-derivation of the real corpus's discovery counters with and without claiming | exit 0 — Verification 4 |
| `/usr/bin/time -v env PYTHONPATH=src python3 -m lee_kb.main sync --config <corpus> --workspace-root <workspace> --database <scratch>.sqlite` | exit 0 — independent clean full re-sync, Verification 4 |
| Reviewer probe: governed-retrieval invariants exercised behaviourally | exit 0 — Verification 6 |
| Repository-wide leak scan over all 75 tracked files + full-history scan | exit 0 — Verification 5 |
| `python3 tools/validate_verdict.py code-reviews/review-sprint-2-correctness.verdict.json` | exit 0 — satisfies the gate's required shape |

The reviewer re-sync wrote only to this step's scratch space; it did not touch
`.lee-kb/real-corpus.sqlite` or any tracked file.

## Findings

| ID | Severity | Category | Location | Problem | Proposed Fix |
|----|----------|----------|----------|---------|--------------|
| S2-R-14 | Medium | publication-safety | git history: `playbooks/sprint_02_p1_real_corpus_parity.yaml` at `9cca4df`, `4e9b989`, `7e74e56`, `b980cdd`; `.agent-orch-scratch/.agent-orch-scratch-root.json` at 8 commits from `fc757f4` to `4e9b989`; `context.md` at `95f63c9` and earlier | S2-R-01, S2-R-02 and S2-R-12 sanitized the *working tree* by rewriting files forward; the absolute host paths they removed are still in the commits. Four commits carry the absolute path to the private corpus configuration and to the factory workspace root; eight carry the absolute path of this checkout. The remote `github.com/leebase/lee-kb` is at `95f63c9`, an ancestor of local `HEAD`, so those 14 commits are unpushed and publish verbatim on the first `git push`. A third path shape — a `/Volumes/…` mount recorded as the working directory in `context.md` — is **already published**, because it is present at `95f63c9` itself and at two earlier remote commits. Project memory (`context.md` Environment Notes) records the disclosure class as repaired. | Rewrite the 14 unpushed commits before the first push (squash to a sanitized set, or `git filter-repo` to drop `.agent-orch-scratch` and rewrite the playbook blob), then re-verify with a scan over `git rev-list --all`. The already-published `/Volumes` path cannot be recalled by a rewrite; decide explicitly whether it matters. Extend the scan rule in `skills/documentation.md:50` so it walks every reachable tree, not only the checkout. |
| S2-R-15 | Medium | correctness | `src/lee_kb/connectors/local_files.py:683-684`, `:715-733` (`_claiming_root`); `src/lee_kb/main.py:81-88`, `:230-311` | In a scoped sync (`lee-kb sync local_files <root>`), `_claiming_root` still consults every configured root, so a file inside an overlap region is skipped by the root being synced and never scanned by the claiming root, which is out of scope for the pass. It lands in no counter. Reproduced: two overlapping roots over a three-file tree, `discover_report(root_name="parent")` returns 1 object; the other 2 files — both matched by the parent's own `include` — are neither indexed nor counted (`git_ignored=0`, `unhandled_formats={}`). This contradicts the `DiscoveryReport` docstring ("accounted for in exactly one place", `local_files.py:514`) and the `SyncSummary` docstring ("must never disappear without a count", `main.py:84-85`). The stderr nested-root notice tells the operator overlaps exist, not that this pass lost files to one. | Count claim-losses in `DiscoveryReport` (e.g. `claimed_by_other_root`) and print the segment; or, when `root_name` is set and the claiming root is outside the requested scope, let the requested root claim the file for that pass. Add a scoped-sync regression test over two overlapping roots asserting every on-disk candidate is either indexed or counted. |
| S2-R-16 | Medium | correctness | `src/lee_kb/connectors/local_files.py:702-707` (the `discover_report` `ConnectorReadError` handler); `src/lee_kb/main.py:199-209` (`_changes_from_objects` deletion diff) and `:249-255` (`tombstone_item`) | An already-indexed document that becomes temporarily unreadable is removed from the searchable projection with no counter and is misreported to the operator as a deletion. `discover_report()` catches `ConnectorReadError` from `_describe` and `continue`s without incrementing anything; `_changes_from_objects` then sees the id missing from `current` and emits `DELETED`; `_sync_connector` tombstones the item and drops its cursor entry. Reproduced on a six-document corpus: `chmod 000` on one indexed file makes the next pass print `0 created, 0 updated, 1 deleted, 3 unchanged` with `skipped=0`, `git_ignored=1` (the pre-existing ignored file) and `unhandled={'.rst': 1}` — no counter moves for the unreadable file — the item is tombstoned, and it returns as `1 created` on the following readable pass. Pre-existing: the pre-repair `list_changes()` → `discover()` path behaved identically, so S2-R-03 did not introduce it. The S1-R-10 fetch-time skip-and-report guard sits downstream of this hole and never sees the object. | Add a `read_failures` counter to `DiscoveryReport` and `SyncSummary`, increment it where the `ConnectorReadError` is currently swallowed, print it in the sync summary line, and exclude read-failed `source_object_id`s from the `DELETED` diff so a transient permission or I/O error cannot tombstone a live item. Add a sync test covering an already-indexed file that becomes unreadable. |
| S2-R-17 | Medium | reporting-accuracy | `evidence/real-corpus-parity-report.md:50`, `:111`, `:122`, `:123` (against `:94` and `:113`) | The customer-facing measurement artifact states two different values for the same post-repair counter and carries two statements the same edit invalidated. "What Was Not Indexed" (`:50`) and Parity Gaps (`:111`) both present **300 git-ignored** as this run's CLI counter, while Performance (`:94`) and the S2-R-04 note (`:113`) say **14**. The reviewer's own clean full re-sync prints `14 git-ignored` (Verification 4), so 14 is current and `:50`/`:111` are stale pre-repair text. Recommended Next Actions #4 (`:122`) still tells the reader to treat ~5m20s and ~4.5 GiB as the baseline, in a document whose Performance table now records 2:51.18. Recommended Next Actions #5 (`:123`) still reads "No correctness defects were found in this pass" in a document that now records three repaired defects. | Re-scope `:50` and `:111` to the pre-repair run or update them to 14 with a pointer to the Performance explanation; update #4 to the post-repair baseline; re-word #5 so it refers to the original measurement pass rather than the document as a whole. |
| S2-R-18 | Low | reporting-accuracy | `context.md:70`; `result-review.md:34`, `:157` | Three places in project memory restate the pre-repair peak RSS as "~4.48 GiB". `4,585,924 KB` is 4.373 GiB. Commit `19b8d4d` corrected exactly this parenthetical inside `evidence/real-corpus-parity-report.md:87` (`~4.48 GiB` → `~4.37 GiB`) without correcting the copies in project memory. The underlying KB figure is consistent everywhere, so only the derived unit is wrong. | Change all three occurrences to ~4.37 GiB, or cite `4,585,924 KB` without a GiB conversion so the derived figure cannot drift again. |
| S2-R-19 | Low | traceability | commit `19b8d4d` (message vs contents) | The entire deliverable under review — `local_files.py` +93, `main.py` +85, `tests/test_local_connector.py` +128, `tests/test_cli.py` +99, `tests/golden/test_golden_corpus.py` +90 — is committed under the message `fix(S2-R-12, S2-R-13): remove host path from project memory; refuse sync on unreachable required root`, which names neither S2-R-04, S2-R-03 nor S1-R-16 and describes a different pair of findings. `git log -- src/lee_kb/connectors/local_files.py` gives no indication the nested-root work happened. This is a recurrence of S2-R-08, filed by the previous review against `4e9b989` for the same reason and still open. | Amend or annotate `19b8d4d` before pushing so the message names all five findings, and record "one commit message per finding set" as a standing rule in `skills/documentation.md` rather than a per-sprint correction. |
| S2-R-20 | Low | verification-evidence | `evidence/real-corpus-parity-report.md:79-94` (Performance table) | No `/usr/bin/time -v` transcript was preserved for the post-repair run and no system validator executed the sync, so as delivered the headline −46.6% claim — repeated as measured fact in `context.md`, `result-review.md`, `sprint-plan.md` and the customer-facing narrative — rested on a single unpreserved worker observation. The figures themselves hold: an independent clean full re-sync by this reviewer reproduced them within 3% (Verification 4). The defect is evidence discipline, not accuracy. | Write the `/usr/bin/time -v` block (which contains no corpus content) to a file under `evidence/` and cite it from the Performance section, or add a system validator that runs the timed sync, so the performance claim carries a record rather than an assertion. |
| S2-R-21 | Low | documentation | `docs/golden-baseline.md:34-41`, `:44` (per-question results table) | Eight of the twenty per-question rows carry a duplicated `Hit` cell — six columns instead of five, e.g. `\| operational-04 \| Operational status \| architecture.md \| Hit \| Hit \| 2 \|`. The S1-R-16 gate parses only the three Baseline bullets, so this table is an ungated drift surface inside a document that is now a contract. | Repair the eight malformed rows, and extend `_parse_recorded_baseline` (or add a second assertion) to check the per-question rank column, so the whole recorded document is gated rather than three lines of it. |

**No Critical or High finding survived verification.** Two severity calls
diverge from the previous review cycle of this same slice and are stated
explicitly so they can be argued with:

- **S2-R-14 is Medium, not High.** The mission's "treat any leak as at least a
  High finding" rule is scoped to *tracked files*; the repository-wide
  tracked-file scan passes cleanly (Verification 5). What remains is the same
  class of disclosure in unpushed history. Its content is filesystem layout
  plus the account name `lee`, which this repository already publishes in
  `README.md`, `src/lee_kb/main.py:61` and 39 occurrences of
  `lee@leebase.com` — no credential, no document content, no corpus document
  path. The previous review rated this identical disclosure *in a tracked file
  of a live public repository* (S2-R-02) as Medium; its residue in commits that
  have not been pushed cannot reasonably outrank that. It is still a real
  pre-push blocker and is listed under Fix Now.
- **S2-R-16 is Medium, not High.** By this project's rubric
  (`skills/code-review.md`) High means unauthorized evidence, data loss, or
  incorrect normal-use behaviour. Nothing is lost: the source system remains
  authoritative, the item is tombstoned rather than purged so receipts stay
  resolvable, and the projection self-heals on the next readable sync
  (reproduced: the item returns as `1 created`). The precedent sometimes cited
  for High here, S1-R-10, was rated High because one unreadable file aborted
  the *entire* sync; this is a miscount plus a self-healing single-item drop
  outside normal use. It nonetheless violates the connector's own stated
  "never disappear without a count" invariant and produces a false deletion
  report, so it is Fix Now.

## Residual Risks

**Parity gaps that remain open — unchanged by this slice.**

- **Office-format support remains open and entirely unimplemented.**
  `FORMAT_HANDLERS` (`local_files.py:214-219`) covers `.md`, `.markdown`,
  `.txt`, `.text` only. `.docx`/`.xlsx`/`.pptx` remain deferred implementation,
  not deferred contract, per the locked decision: `DocumentType` still
  enumerates them and the registry still accepts a handler without redesign.
  The gap is sized at 39 files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`) inside the 15
  configured roots, and closing it needs both dependency approval **and** an
  `include`-pattern change on the affected roots — the reviewer's re-derivation
  of discovery over all 15 real roots returned an empty unhandled-format
  histogram, confirming that office files are excluded a step before any
  handler lookup. This remains Next Actions rank 1 and is explicitly open.
- **The curated golden benchmark remains open.** `tests/golden/` runs a
  20-question corpus generated from this repository's own documents plus three
  negative controls. S1-R-16 has made its recorded metrics an executable
  contract, which raises the value of the harness but does not change what the
  harness measures: it proves the evaluation framework, not Lee's real Chief of
  Staff questions against Employee Zero sources. This remains open.

**Risks introduced or sharpened by the S2-R-04 repair.**

- **Existing projections will churn on the first post-repair sync.** Any
  projection built before the repair holds overlap-region items under the
  parent root's `source_object_id`. The first post-repair sync diffs them away
  as `DELETED` (tombstoned, so receipts stay resolvable) and re-creates them
  under the claiming root, producing a large `deleted` + `created` count that is
  documented nowhere. The real-corpus re-measurement did not exercise this
  because the database was deleted first, and neither did the reviewer's
  re-sync, for the same reason.
- **A file's claiming root is decided independently of whether that root will
  actually index it.** `_claiming_root` runs before the git-ignore and handler
  checks, so in principle a claiming root that suppresses a file its parent
  would have kept removes it from the projection. On the real corpus this is
  benign — the reviewer's re-derivation shows document count identical (1,213)
  with claiming enabled and disabled — but the decision order makes the
  divergence reachable.
- **`health()` labels two roots configured at the *identical* path as a nested
  pair.** Verified: two roots on one path report `nested roots detected …:
  alpha -> zulu`. Claiming stays deterministic through the name tie-break
  (`alpha` wins, verified), but the wording tells an operator the roots are
  nested when they are duplicates.
- **The `git-ignored` counter is now a weaker signal.** It fell from 300 to 14
  on the real corpus because the overlap region is no longer counted twice.
  That is correct, but an operator watching the number as a proxy for "how much
  is git-ignore suppressing" now sees a much smaller figure for the same corpus.

**Sprint 1 and Sprint 2 advisories still carried at `19b8d4d`.** Receipts are
persisted before the `fail_on_stale` refusal (S1-R-13); denied and empty
retrievals leave no durable record (S1-R-12); `Repository.search()` remains a
public, principal-free content path (S1-R-17); `discover()` and `_resolve()`
still resolve their root base differently (S1-R-14 — Next Actions rank 2, and
now the substrate `_claiming_root` sits on, since it compares resolved paths
while the surrounding walk builds relatives from the unresolved one);
`requires-python` still claims 3.10 while `tomllib` is imported unconditionally
(S1-R-15). Sprint 2 advisories S2-R-05 through S2-R-11 are all still present and
unrepaired, including S2-R-06 (`evidence/real-corpus-parity-report.md:65` still
says "Ten of the 15 roots have zero office-format files") and S2-R-10 (the
`ruff` deprecation warning still emitted by the preserved `step_05` record).
None was in this slice's scope and none is re-filed here.

**Environmental fragility.** Git-ignore resolution is still delegated to
whatever repository encloses a root, so the projection's contents depend on the
enclosing checkout, not only on `sources.toml`. Five candidates on the real
corpus remain `git-ignore status unresolved` and are indexed anyway, per the
connector's count-it-don't-drop-it contract.

## Verification

Each numbered item is a mission verification target. Evidence is from the code
at `19b8d4d`, from reviewer probes in this step's scratch space, and from the
run's own artifacts.

1. **S2-R-04 is really fixed: an overlapping file is indexed exactly once under
   a deterministic claiming root, and the condition is operator-visible —
   verified, with one scoped-sync gap (S2-R-15).** A constructed tree of three
   Markdown files under two overlapping roots (`parent`, and `parent/child`),
   both configured `include = ["**/*.md"]`, yields exactly three objects —
   `child:deep/deep.md`, `child:shared.md`, `parent:only_parent.md` — resolving
   to three distinct on-disk files, so no file is claimed twice and none is
   dropped. The deeper root wins, as designed. The claim is stable across
   repeated discovery passes and independent of declaration order (reversing the
   root tuple produces the identical id set). When the child's `include` no
   longer matches the shared region (`docs/*.md`), the parent correctly
   reclaims both files — the deepest root only wins where it would actually
   have matched. Two roots configured at the *same* path resolve by name
   tie-break, deterministically (`alpha` claims all three). Operator visibility
   is real and not merely available: `cmd_sync` calls `connector.health()`
   before every sync and prints the detail to stderr; the reviewer's own full
   real-corpus sync emitted `lee-kb: all roots reachable; nested roots detected
   (deepest matching root claims overlaps): jobsearch -> agent-in-a-box,
   pr-business -> pr-research`. In-repo regression coverage exists
   (`tests/test_local_connector.py:539`, `:576`). The gap is that files
   reassigned by claiming are not counted in a *scoped* sync: with
   `root_name="parent"` the probe returned 1 object of 3 candidates and every
   counter at zero for the other two (S2-R-15).

2. **S2-R-03 is really fixed: exactly one discovery pass per sync, with cursor
   semantics, skip-and-report, tombstoning and every CLI counter preserved —
   verified, and one pre-existing hole exposed (S2-R-16).** An instrumented
   six-pass sync over an eight-candidate corpus counted, per pass:
   `discover_report` 1, `Path.rglob` 1, `git check-ignore` subprocesses 1.
   Content hashing is now once per candidate in discovery plus once per
   *changed* object in `fetch` (pass 1: 12 hashes = 6 discovery + 6 fetch;
   pass 2, unchanged corpus: 7 = 6 discovery + 1 fetch of the perpetually
   re-skipped token-shaped file) — the second full-corpus hash pass is gone, while the
   third read of changed files that the original finding described is unchanged,
   as intended. Cursor semantics hold: pass 2 with no change reports
   `0 created, 0 updated, 0 deleted, 5 unchanged`; changing one file and
   deleting another reports `0 created, 1 updated, 1 deleted, 3 unchanged` with
   `corpus:doc2.md` tombstoned rather than purged (`tombstone = 1`, row still
   present), and the `unchanged` denominator tracks correctly through each pass.
   The token-shaped-content tripwire still refuses to index its file, still
   leaves the cursor untouched, and still re-reports every pass
   (`skipped_token_content=1` on all six passes, zero rows for it in
   `knowledge_items`). `git_ignored=1` and `unhandled_formats={'.rst': 1}` are
   stable across every pass. The in-repo guard
   `tests/test_cli.py:185-221` asserts `invocation_count == 1` independently.
   What the same probe exposed is that a candidate whose read fails *during
   discovery* is dropped with no counter and then diffed as a deletion — filed
   as S2-R-16, reproduced in pass 4 and self-healed in pass 5.

3. **S1-R-16 is really fixed: the baseline assertion fails on a simulated
   ranking regression, and the recorded document and the test cannot drift apart
   silently on the gated metrics — verified.** The test passes unmutated
   (control, exit 0, 1 passed). Under a mutant retriever that reverses the
   provider's final order it fails (exit 1,
   `operational-01 lost its top-10 citation entirely`). Under the subtlest
   regression its tolerance claims to catch — swapping the top two hits for
   exactly *one* of the twenty questions, demoting it from rank 1 to rank 2 — it
   also fails, with the intended message: `hit_at_1 drifted from the
   docs/golden-baseline.md gate: observed 0.5500, recorded 0.6000 (tolerance
   0.01)`. So the gate is not merely passing today. Drift between the document
   and the test is closed in both directions on the three gated metrics:
   redirecting `BASELINE_DOC_PATH` to a copy of the document with hit-at-1
   edited to 80.0% fails (`observed 0.6000, recorded 0.8000`), proving the gate
   reads the document live rather than a second hardcoded copy; and deleting the
   hit-at-1 bullet fails with the explicit `Could not parse the Baseline
   section…` assertion rather than silently skipping the check. The comparison
   is `math.isclose`, so an unrecorded *improvement* fails as loudly as a
   regression. The residual drift surface is the per-question rank table, which
   is ungated and currently malformed — filed as S2-R-21.

4. **The re-measured figures are reproducible from the run, and the change in
   corpus shape is explained — verified, including the performance figures.**
   *Counts:* reading `.lee-kb/real-corpus.sqlite` read-only reproduces the
   report exactly — **1,213** live knowledge items, **0** tombstoned, **12,699**
   chunks, **15** roots, a per-root document count matching every row of the
   Corpus Shape table, **21,020,672 bytes** on disk, authority **13 canonical /
   1,200 derived**, trust **1,211 curated / 2 model_produced**.
   *Performance:* rather than accept the worker's assertion, the reviewer ran an
   independent clean full sync of the same corpus into scratch under
   `/usr/bin/time -v` (exit 0). It reproduced the report's post-repair figures
   within noise: wall-clock **2:46.28** against the reported 2:51.18, user
   **136.56s** against 140.78s, system **22.68s** against 23.44s, CPU **95%**
   against 95%, peak RSS **4,566,972 KB** against 4,568,212 KB (0.03% apart),
   zero swaps and zero major page faults. That re-sync also reproduced the
   corpus shape independently of the existing projection: 1,213 items, 12,699
   chunks, 21,020,672 bytes, the same authority and trust splits. The −46.6%
   improvement claim is therefore reproducible from the run, not merely
   asserted; what is missing is a *preserved artifact* for the original
   measurement, filed as S2-R-20.
   *Shape change:* the reviewer re-derived discovery over all 15 real roots
   (enumeration, containment, one batched `git check-ignore` per root, handler
   lookup — no content reads, no hashing) twice: with `_claiming_root` active
   and with it bypassed. With claiming: `indexable=1213, git_ignored=14,
   git_unresolved=5, unhandled={}`. Without claiming: `indexable=1213,
   git_ignored=300, git_unresolved=5, unhandled={}`. This reproduces both the
   pre-repair 300 and the post-repair 14 from the same code and corpus, and
   proves the report's explanation exactly: the S2-R-04 repair changed only the
   diagnostic counter, because the overlap region held no candidate that both
   roots' `include` patterns matched outside already-ignored files. The
   reviewer's own sync summary line, `1213 created, 0 updated, 0 deleted, 0
   unchanged, 14 git-ignored, 5 git-ignore status unresolved`, confirms 14 is
   the current value and that the report's `:50` and `:111` are stale
   (S2-R-17). The projection holds **0** retrieval receipts, consistent with a
   clean re-sync and no queries; the carried-forward retrieval latencies
   therefore have no audit trail in the current projection, which the report
   states plainly.

5. **Repository-wide leak scan — the tracked-file criterion passes; the same
   class in git history does not (S2-R-14).** Over all **75** tracked files at
   `19b8d4d`, not a spot check: a scan for `/home/`, `/Users/`, `/Volumes/`,
   Windows user paths and `file:///` URIs returns 11 hits, every one synthetic
   or self-referential — the `path = "/home/lee/notes"` configuration example in
   the `local_files` module docstring, `file:///home/lee/…`,
   `file:///knowledge/…`, `file:///workspace/…` and `file:///x` fixtures across
   four test modules, and the scan rule itself in `skills/documentation.md:50`.
   None discloses a real corpus location or host layout. A credential-shape scan
   (`sk-…`, `ghp_…`, `AKIA…`, `xox…`, PEM markers) matches exactly two tracked
   lines: the tripwire's own regex in `local_files.py:163` and the assertion
   exercising it in `tests/test_local_connector.py:697`. The only e-mail address
   is `lee@leebase.com` (39 occurrences, the published owner) plus three
   `@example.com` placeholders; no phone-, SSN- or card-shaped string appears.
   A content cross-check against the real projection — 888 distinct document
   titles over 12 characters, and every chunk line of 70+ characters from a
   4,000-chunk sample — grepped against every tracked file surfaced only
   `OPERATE.md` (2 lines) and
   `playbooks/templates/repair_before_review_feature_delivery.yaml` (3 lines),
   and in both cases the matching chunks come from the `agent-orch` root, i.e.
   Agent-Orch's own operating documentation that this repository legitimately
   carries and that the corpus indexes back; both files were added at `fc757f4`,
   the onboarding commit, before any corpus work. `git status --porcelain -uall`
   is clean and `git ls-files` lists no `.sqlite`, `.lee-kb/` or
   `.agent-orch-scratch/` entry. The mission criterion — no absolute host path,
   document content, or personal/credential-shaped detail in any tracked file —
   therefore passes. Extending the identical scan across `git rev-list --all` is
   what fails: four commits carry the absolute path to the private corpus
   configuration and the factory workspace root, eight carry the absolute path
   of this checkout, and a third path shape recorded as the working directory in
   `context.md` is present at the published remote tip `95f63c9` and at two
   earlier remote commits — filed as S2-R-14, with the correction that this last
   one is already public rather than merely pending.

6. **Sprint 1 governed-retrieval invariants still hold — verified
   behaviourally.** No retrieval-path file changed in this slice:
   `git diff 7e74e56..HEAD` over `governance.py`, `retrieval.py`,
   `repository.py` and `contracts.py` is empty. Exercised live rather than
   inferred from test names, against a two-item projection owned by different
   principals: `retrieve()` without a principal raises `MissingPrincipalError`
   (`governance.py:125`) before any repository access — fail-closed; the
   permitted principal receives `evidence=1, denied_count=1` and the denied
   item's label appears in no citation, so permission filtering
   (`governance.py:151`) precedes evidence assembly (`:171`); exactly one
   receipt is persisted per released evidence item (repository delta 1 for 1
   evidence, `bundle.receipts` 1); and a fully unauthorized principal gets
   `evidence=0, denied=2` with **zero** receipts persisted, so no
   evidence-shaped record is fabricated for a refused request. A walk of every
   module in the `lee_kb` package finds `lee_kb.governance.retrieve` as the only
   public function returning an `EvidenceBundle`.

7. **Platform evidence handed to this step — summarized, not certified.** The
   evaluator packet records, for all five producer steps, a selected route
   matching the executed route (`producer_route_executed`, `verified_true`), a
   before/after repository identity comparison that passed with zero differences
   (`valid_root_git_directory`), and preserved validator authority (7
   independently executed `command_succeeds@1` records, all `exit_status: 0`,
   all `passed: true`, each bound to a named acceptance criterion). The
   pre-invocation evidence-chain snapshot is `ok=true` across 2 entries and 23
   artifacts with no divergence; it is explicitly not the approval-boundary or
   terminal attestation. `semantic_judge_execution` is `not_applicable` — this
   playbook declares no `semantic_check` rule. The previous attempt of *this*
   step carries `validator_authority_verified` `verified_false` with
   `checks_run_match: true`, i.e. its reported checks did not contradict the
   preserved record; the failure was the verdict gate itself. Post-execution
   attestations for this attempt are produced after it returns and are not
   certified here.

## Readiness

| Criterion | State | Basis |
|---|---|---|
| S2-R-04 repaired: one file, one deterministic claiming root, operator-visible | `verified_true` | Verification 1 |
| S2-R-03 repaired: one discovery pass; cursor, skip-and-report, tombstoning, counters preserved | `verified_true` | Verification 2 |
| S1-R-16 repaired: baseline fails on a simulated regression; document and test cannot drift on the gated metrics | `verified_true` | Verification 3 |
| Re-measured counts reproducible; corpus-shape change explained | `verified_true` | Verification 4 |
| Re-measured performance figures reproducible from the run rather than asserted | `verified_true` | Verification 4 — independent timed re-sync within 3% on every metric |
| No absolute host path, document content, or personal/credential-shaped detail in any tracked file | `verified_true` | Verification 5 — repository-wide over all 75 tracked files |
| Sprint 1 governed-retrieval invariants hold | `verified_true` | Verification 6 |
| Producer route, repository identity, validator authority for the five producer steps | `verified_true` | Verification 7, evaluator evidence packet |

**Verdict:** `pass` — no Critical or High finding survived verification, and all
three repairs under review are correct and independently reproduced.

**Recommendation:** `Ready after specific follow-up` — sanitize the 14 unpushed
commits before the first `git push` (S2-R-14), stop discovery-time read failures
from tombstoning live items (S2-R-16), account for claim-losses in a scoped sync
(S2-R-15), and reconcile the contradicting statements in the customer-facing
evidence report (S2-R-17). None of these requires rework of the S2-R-04,
S2-R-03 or S1-R-16 repairs themselves.

## Remediation Roadmap

### Fix Now
- S2-R-14 — sanitize the 14 unpushed commits before the repository is pushed.
- S2-R-16 — count discovery-time read failures and keep them out of the deletion diff.

### Fix Soon
- S2-R-15 — count or reassign claim-losses in a scoped sync.
- S2-R-17 — reconcile the git-ignored counter and the stale statements in the evidence report.

### Fix Later
- S2-R-18, S2-R-19, S2-R-20, S2-R-21 — the RSS unit conversion in project memory, the commit-message traceability recurrence, the missing timing artifact, and the malformed golden-baseline table.

## Test Additions Recommended

- [ ] Sync test: an already-indexed file that becomes unreadable is counted, not tombstoned (S2-R-16).
- [ ] Scoped-sync test over two overlapping roots: every on-disk candidate is either indexed or counted (S2-R-15).
- [ ] Connector test: a root pair configured at the identical path, asserting the name tie-break and the reported detail wording.
- [ ] Golden-harness assertion that the per-question rank table in `docs/golden-baseline.md` matches observed ranks (S2-R-21).
- [ ] Migration test: a projection built under the pre-repair claiming rule re-syncs to the post-repair rule without losing receipt resolvability.
