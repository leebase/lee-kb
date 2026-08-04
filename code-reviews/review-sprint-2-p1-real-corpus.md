# Code Review — Sprint 2 P1: Real-Corpus Parity Slice

**Reviewed at:** `7e74e56` (working tree clean)
**Reviewer role:** independent Reviewer (`agents/reviewer.md`, `skills/code-review.md`)
**Subject:** the P1a–P1d slice — deployed-`sources.toml` consumption
(`src/lee_kb/connectors/local_files.py`), silent-loss reporting
(`SyncSummary`/`DiscoveryReport` and their CLI surface in
`src/lee_kb/main.py`), the real-corpus measurement recorded in
`evidence/real-corpus-parity-report.md`, and the project-memory updates.

**Publication-safety note.** This review is itself a file in a public
repository. It reproduces only root names, counts, extensions, and timings —
no document titles, no document content, no file paths inside the corpus, and
no host-absolute paths. Where a finding concerns a disclosed path, the path is
described rather than quoted.

## Architecture Summary

`load_config()` parses the deployed `sources.toml` shape (schema 1, 15
`[roots.*]` tables, `overrides`, `external`, `required`) into frozen
`RootConfig` objects. `LocalFilesConnector.discover_report()` walks each root,
applies `GLOBAL_DEFAULT_DENY` → `include` → `exclude`
(`local_files.py:489-496`), enforces symlink containment
(`local_files.py:634-640`), resolves git-ignore status with one batched
`git check-ignore -z --stdin` per root (`local_files.py:522-556`), and then
either yields a `SourceObject` or increments one of `git_ignored`,
`unhandled_formats`, or `git_unresolved`. `main._sync_connector()` turns the
change list into transactional repository writes, applies the token-shaped
content tripwire, and folds the discovery report into `SyncSummary`, which
`cmd_sync()` prints (`main.py:311-334`). Retrieval is unchanged from Sprint 1:
`governance.retrieve()` remains the only public surface that produces an
`EvidenceBundle`.

## Checks Run

| Command | Executed by | Result |
|---------|-------------|--------|
| `python3 -m pytest tests/` | system validator (preserved) | exit 0 — 118 passed at `step_01`, 127 passed at `step_02` and `step_03` |
| `python3 -m pytest` | system validator (preserved) | exit 0 — 127 passed at `step_04` |
| `python3 -m black --check src tests` | system validator (preserved) | exit 0 — 18 files would be left unchanged |
| `python3 -m ruff check src tests` | system validator (preserved) | exit 0 — passes, with a deprecation warning about `pyproject.toml` linter settings (see S2-R-10) |
| `env PYTHONPATH=src python3 -m lee_kb.main sync --help` | system validator (preserved) | exit 0 — prints `--workspace-root` and `--database` |
| Reviewer probe: projection spot-check (read-only SQLite) | reviewer | exit 0 — see Verification |
| Reviewer probe: candidate/git-ignore re-derivation over the 15 configured roots | reviewer | exit 0 — see Verification |
| Reviewer probe: glob dialect, default-deny, override resolution | reviewer | exit 0 — see Verification |
| Reviewer probe: counter partition on a constructed corpus | reviewer | exit 0 — see Verification |
| Reviewer probe: independent office-format filesystem tally | reviewer | exit 0 — see Verification |
| `git check-ignore -v`, `git status --porcelain -uall`, `git log`/`git show` over the S2-R-01 repair | reviewer | exit 0 — see Verification |

Preserved system-validator records were summarized, not re-executed: validator
rerun is not permitted for this step.

## Findings

| ID | Severity | Category | Location | Problem | Proposed Fix |
|----|----------|----------|----------|---------|--------------|
| S2-R-02 | Medium | publication-safety | `playbooks/sprint_02_p1_real_corpus_parity.yaml:7,141` | A tracked file in this public repository contains absolute host paths to the private corpus workspace and to the deployed `sources.toml`. No document content or credentials are exposed, but the maintainer's local filesystem layout and the corpus location are. The S2-R-01 repair covered `.agent-orch-scratch/` and `.lee-kb/` and did not reach this file. | Replace the absolute paths with a placeholder or an environment variable resolved at run time, or keep playbooks outside the public repository. |
| S2-R-03 | Medium | efficiency | `src/lee_kb/main.py:188` and `:251`; `src/lee_kb/connectors/local_files.py:600-601,671-693` | One sync pass walks and byte-hashes the whole corpus twice: `list_changes()` calls `discover()` → `discover_report()`, and `_sync_connector` then calls `discover_report()` a second time purely to obtain the counters and the `unchanged` denominator. Changed files are read a third time by `fetch()`. On the real corpus this is ~2,400 full file reads for 1,213 documents, and it is the largest single contributor to the recorded 5:20 wall-clock and ~4.48 GiB peak RSS that the report now enshrines as the performance baseline. | Have `_sync_connector` take one `DiscoveryReport`, derive the change list from it, and pass its objects to the counter/`unchanged` computation; or cache the report on the connector for the duration of a pass. Re-record the baseline afterwards. |
| S2-R-04 | Medium | correctness | `src/lee_kb/connectors/local_files.py:568-580` (`__init__`), `:337-414` (`_parse_root`) | Nothing detects that one configured root's resolved path lies inside another's. Two roots in the deployed config are nested (one repo root inside another's tree, and one research root inside its parent root). Identity is `(connector, "root:relative")`, so the same file discovered under two roots becomes two knowledge items with two chunk sets and two independently citable evidence rows. Today duplication is avoided only by accident: one nested tree is git-ignored by its parent (293 of that root's 695 candidates), and the other pair is separated by non-overlapping `include` globs. The reviewer probe confirmed zero duplicates in the current projection — but git-ignore resolution already fails for 2 of 15 roots (`git_unresolved = 5`), and in an environment without git the nested tree would be indexed twice, adding ~293 duplicate documents with no warning. | Detect nested resolved root paths in `load_config()`/`LocalFilesConnector.__init__` and either reject the configuration or de-duplicate candidates by resolved absolute path; add a regression test for two roots where one contains the other. |
| S2-R-05 | Low | reporting-accuracy | `src/lee_kb/connectors/local_files.py:500-519` (class docstring) vs `:646-647`; `src/lee_kb/main.py:76-83,321-324` | `DiscoveryReport`'s class docstring states that every file is accounted for "in exactly one place" — either in `objects` or in one counter. `git_unresolved` deliberately violates that: unresolved candidates are still indexed, so they are counted *and* present in `objects` (the field docstring says so; the class docstring contradicts it). The same overlap reaches the CLI, which prints `1213 created, ..., 300 git-ignored, 5 git-ignore status unresolved` as if the numbers partitioned. `SyncSummary`'s docstring repeats the claim. Confirmed on the real corpus: the 5 unresolved candidates are inside the 1,213 indexed documents. | Correct both docstrings to state that `git_unresolved` is an overlay on `objects`, not a disjoint bucket, and label the CLI counter accordingly (e.g. "5 indexed with git-ignore status unresolved"). |
| S2-R-06 | Low | reporting-accuracy | `evidence/real-corpus-parity-report.md:65`; same claim in `context.md:140` | "Ten of the 15 roots have zero office-format files present" is off by one. An independent filesystem tally over the same 15 configured roots finds office-format files in six roots (`ai-employee-book` 21, `tviq` 9, `jobsearch` 5, `pr-business` 2, `agent-orch` 1, `factory` 1), leaving nine roots at zero. The headline total (39 = 32 `.docx` + 5 `.xlsx` + 2 `.pptx`) and the stated concentration both reproduce exactly. | Change "ten"/"the remaining 9 files are spread across four roots" to "nine roots have zero; six roots hold at least one" in the report and in `context.md` Open Question 2. |
| S2-R-07 | Low | reporting-accuracy | `evidence/real-corpus-parity-report.md:69` | "Twelve queries were run against the real projection" understates the run. The projection's own receipt table records 250 receipts over 13 distinct queries: the 12 reported queries were each executed twice, and a 13th query was executed once and is not mentioned anywhere in the report. The measurement is not invalidated — every reported query does appear, and each returned 10 evidence items — but the narrative cannot be reconciled with the audit trail as written. | State distinct queries and total executions separately, and either report the 13th query's result or note it as an exploratory run excluded from the sample. |
| S2-R-08 | Low | traceability | commit `4e9b989` | The entire P1a/P1b source deliverable — `local_files.py` +409 lines, `main.py` +85, `tests/test_local_connector.py` +349, `tests/test_cli.py` +82 — is committed under the message "fix(playbook): step 3 must run the corpus sync in the foreground", which describes a 4-line playbook edit in the same commit. `git log -- src/lee_kb/connectors/local_files.py` therefore gives no indication that the deployed-config parity and silent-loss work happened. | Record the actual content of `4e9b989` in `result-review.md` so the history is navigable, and keep playbook edits out of source commits going forward. |
| S2-R-09 | Low | documentation | `context.md:58` | "full test suite (109 tests, including the golden corpus) passes" is stale and contradicted by this run's preserved validator records, which report 118 passed at `step_01` and 127 passed at `step_02` through `step_04`. The Sprint 1 review already raised the 109 figure once (S1-R-19); it has now drifted further. | Update the count to the preserved figure, or drop the count and cite the validator record instead of restating a number that ages every sprint. |
| S2-R-10 | Low | tooling | `pyproject.toml:49-52` | `ruff check` passes (exit 0) but emits a deprecation warning on every run: the top-level `select` and `ignore` settings must move to `lint.select`/`lint.ignore`. A future ruff release turns this into an error, at which point the verification command that gates every step of this playbook fails for a reason unrelated to the code. | Move `select` and `ignore` under `[tool.ruff.lint]`. |
| S2-R-11 | Low | test-coverage | `tests/test_cli.py:188-213`; `tests/test_local_connector.py:499-612` | Two properties this slice depends on are unasserted. (1) No test covers the `git_ignored` / `git_unresolved` segments of the CLI summary line, although `unhandled_formats` and `skipped_token_content` are covered — the only evidence those segments print correctly is the real-corpus run. (2) No test asserts the ordering guarantee that a git-ignored file with an unregistered extension is counted once (as git-ignored) and not also as an unhandled format. Both hold today; the reviewer verified them by probe. | Add a CLI test asserting the git-ignore segments, and a connector test with a git-ignored `.docx` asserting `git_ignored == 1` and `unhandled_formats == {}`. |

No Critical or High finding survived verification. In particular, the
publication-safety check on `evidence/real-corpus-parity-report.md` — the check
the mission designates as at least High if it fails — passes: see Verification
item 5.

## Residual Risks

**Parity gaps that remain open.**

- **Office formats are still entirely unregistered.** `FORMAT_HANDLERS`
  (`local_files.py:203-208`) covers `.md`, `.markdown`, `.txt`, `.text` only.
  `DocumentType` still enumerates `.docx`/`.xlsx`/`.pptx` and the registry
  still accepts them without redesign, so this remains deferred implementation
  rather than a deferred contract, per the locked decision. The gap is now
  sized: 39 files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`) inside the 15 configured
  roots, concentrated in `ai-employee-book` (21) and `tviq` (9). Closing it
  needs both dependency approval *and* an `include`-pattern change on the
  affected roots; the report is right that neither alone suffices, and the
  reviewer confirmed independently that not one of the 15 roots declares a
  non-markdown `include` glob.
- **The unhandled-format histogram cannot see the gap it exists to measure.**
  The handler lookup runs *after* `include` matching
  (`local_files.py:632,653`), so a format no root asks for is filtered out a
  step earlier and never counted. The reviewer re-derived the histogram over
  all 15 roots and got `{}`, matching the report. The report is explicit that
  this zero is structural; the code is not — nothing in `discover_report()`
  warns that the histogram is vacuous when every `include` list is
  single-format.
- **Global default-deny is anchored at each root's top level only.**
  `GLOBAL_DEFAULT_DENY` entries such as `code-reviews/**` and `tmp/**` match
  `code-reviews/x.md` but not `sub/code-reviews/x.md`, because `**` expands to
  `(?:.*/)?` only when followed by `/` (`local_files.py:449-455`). This matches
  the Employee Zero reference dialect, so it is a parity-preserving limitation
  rather than a regression, and the reviewer confirmed the current projection
  contains zero items whose path carries a denied directory segment below the
  top level. It will bite the first time a denied directory name appears
  nested.
- **OR-matcher fetch-to-exhaustion is measured but unbounded.**
  `LexicalRetriever._search_project` (`retrieval.py:63-76`) doubles its limit
  until a short page returns; worst case ~1.5s at 1,213 documents. Behavior at
  a materially larger corpus is unmeasured, as the report states. Open
  Question 5 remains genuinely open.
- **Two ranking edge cases are unresolved by design.** 8 of 10 category queries
  returned the canonical top citation; 2 returned a topically adjacent
  document from the correct root. That is a BM25 limitation, correctly
  classified, and it stays open until the curated golden benchmark exists.

**Sprint 1 advisories still carried.** Re-checked against the current code and
still present: receipts are persisted before the `fail_on_stale` refusal
(`governance.py:187-205`, S1-R-13); denied and empty retrievals leave no
durable record (S1-R-12); `Repository.search()` remains a public, principal-free
content path (S1-R-17); `discover()` and `_resolve()` still resolve their root
base differently (`local_files.py:626` vs `:808-812`, S1-R-14 — still Next
Actions rank 2); `requires-python` still claims 3.10 while `tomllib` is
imported unconditionally (S1-R-15); the golden baseline metrics are still
unguarded by any test (S1-R-16). None was in this slice's scope and none is
re-filed here.

**Environmental fragility.** Git-ignore resolution is delegated to whatever
repository encloses a root, so a root that is not itself a git repository
inherits its parent's ignore rules; a reviewer probe confirmed that a
directory nested inside an ignoring repository is reported 100% ignored. On
the real corpus this is benign and visible (300 ignored, 5 unresolved), but it
means the projection's contents depend on the enclosing checkout, not only on
`sources.toml`.

## Verification

Each numbered item is a mission verification target. Evidence is from the code
at `7e74e56` and from the actual artifacts of this run.

1. **Glob semantics distinguish `*` from `**`, and the global default-deny is
   enforced for every root — verified.** `_compile_glob`
   (`local_files.py:438-482`) compiles `*` to `[^/]*` and `**/` to `(?:.*/)?`.
   Reviewer probe over eight cases: `*.md` matches `a.md` and rejects
   `sub/a.md`; `**/*.md` matches `a.md`, `sub/a.md`, and `x/y/z.md`;
   `docs/*.md` matches `docs/a.md` and rejects `docs/x/a.md`; `docs/**/*.md`
   matches both — all eight as expected. `_matches` (`:489-496`) tests
   `GLOBAL_DEFAULT_DENY` *before* `include`, so a root cannot opt a denied path
   back in: probing all seven denied prefixes against each of the 15 real roots
   with the `include` list widened to `**/*.md` produced zero admissions.
   Covered by `tests/test_local_connector.py:267,282,300`. Limitation recorded
   under Residual Risks.

2. **Per-root overrides apply first-match-wins and change stored authority —
   verified.** `RootConfig.metadata_for` (`:237-245`) returns on the first
   matching pattern; a probe with an overlapping pair
   (`knowledge/*.md` → canonical, then `knowledge/faq.md` → human_authored)
   returned `(canonical, curated)`, proving the first match wins and the later
   pattern is not merged in. The value reaches storage through both
   `_describe` (`:679`) and `fetch` (`:748`) into `KnowledgeItem.authority`
   (`main.py:225-237`). Reproduced end to end on the real projection: the
   deployed config declares exactly 13 overrides (12 in `factory`, 1 in
   `jobsearch`); the projection holds exactly 13 items with
   `authority = canonical`, distributed 12/1 across those same two roots; each
   declared override pattern matches exactly one stored item; and re-deriving
   authority from the config for all 13 stored canonical items reproduces
   `canonical` 13/13 with zero mismatches. Trust behaves the same way: 2
   `model_produced` items, both in `pr-research`, the only root so configured.

3. **Unhandled-extension, git-ignored and token-skipped counters are real,
   reach the CLI, and are not double-counted — verified, with one documentation
   defect.** The counters are incremented on mutually exclusive branches:
   git-ignored candidates `continue` before the handler lookup
   (`:650-652`), so an ignored file with an unregistered extension is counted
   once. A constructed probe confirmed it — a git repository containing an
   ignored `.docx`, an ignored `.md`, a kept `.md` and a kept `.xlsx` yielded
   `git_ignored=2`, `unhandled_formats={'.xlsx': 1, '(no extension)': 1}`, one
   object, with the ignored `.docx` appearing in exactly one counter. All five
   counters reach `SyncSummary` (`main.py:251-262`) and print
   (`main.py:317-331`); `skipped` and `skipped_token_content` print only when
   non-zero, which is why the real-corpus line omitted them. The token tripwire
   is a separate content-level check at `main.py:218-223`.
   The defect is that `git_unresolved` is *deliberately* not disjoint —
   unresolved candidates are still indexed — while the `DiscoveryReport` and
   `SyncSummary` docstrings claim a clean partition (finding S2-R-05).

4. **The report's numbers are reproducible from the run — verified by four
   independent spot-checks; two narrative counts are wrong.** Reading the
   projection read-only: **1,213** live items and **12,699** chunks, matching
   the report exactly; on-disk size **21,020,672 bytes**, matching to the byte;
   authority **13 canonical / 1,200 derived** and trust **1,211 curated / 2
   model_produced**, matching; and all 15 per-root document/chunk rows
   matching the report's table exactly. Re-deriving discovery over the 15 real
   roots from the config (candidate enumeration, containment, one batched
   `git check-ignore` per root, handler lookup — no hashing) independently
   reproduced **1,213 indexable, 300 git-ignored, 5 git-ignore-unresolved, and
   an empty unhandled-format histogram**, i.e. the exact sync summary line the
   report quotes, including which two roots produce the 5 unresolved
   candidates. An independent filesystem tally of office formats inside the 15
   root paths reproduced **39 files: 32 `.docx`, 5 `.xlsx`, 2 `.pptx`**, with
   `ai-employee-book` at 21 and `tviq` at 9. The two narrative counts that do
   not reproduce are recorded as S2-R-06 (nine roots at zero, not ten) and
   S2-R-07 (13 distinct queries and 25 executions recorded in the receipt
   table, against "twelve queries" in the prose). The performance figures
   (5:20.37 wall-clock, ~4.48 GiB peak RSS, per-query latencies) were not
   re-measured — doing so would require re-running the sync, which this step
   does not do; they are single-run observations and are labelled as such in
   the report.

5. **No document content, title, in-corpus path, or personal/credential-shaped
   detail appears in `evidence/real-corpus-parity-report.md` — verified.** The
   report contains root names, counts, extensions, byte sizes, timings, and
   category labels only. A scan for absolute paths, `file://` URIs, and home
   directories returns nothing. No document title, heading, or excerpt appears;
   the two ranking edge cases are described by category, not by document. The
   only personal identifier is the owner principal `lee@leebase.com`, which is
   the configured `owner` on every root and is already published throughout
   this repository (`README.md`, `src/lee_kb/main.py:48`, the test suite) — it
   is not new disclosure. No credential-shaped string appears, consistent with
   the run's zero token-tripwire hits. This check passes; the related
   disclosure that does exist is in a different file and is filed as S2-R-02.

6. **The projection is at a gitignored path and no corpus artifact is staged —
   verified, including the S2-R-01 repair.** `git check-ignore -v` resolves
   `.lee-kb` to `.gitignore:29` and `.agent-orch-scratch` to `.gitignore:28`;
   `*.sqlite` is additionally ignored repo-wide. The projection and the search
   config both live under `.lee-kb/`. `git status --porcelain -uall` is empty,
   so nothing corpus-derived is untracked-and-unignored or staged, and
   `git ls-files` lists no `.sqlite`, no `.lee-kb/`, and no
   `.agent-orch-scratch/` entry. Independently re-deriving the history claim:
   the only blob ever committed under either directory was a scratch root
   marker added in `fc757f4` and removed in `7e74e56`; reading that blob shows
   it holds two repository-local paths and a schema version — no corpus URIs,
   no query results, no document content. The S2-R-01 repair therefore holds as
   described. A residue remains that the repair did not address: absolute host
   paths in a tracked playbook (S2-R-02).

7. **Sprint 1 governed-retrieval invariants still hold — verified.** No
   retrieval-path file changed in this slice (`git diff 717b11b..HEAD` touches
   `connectors/local_files.py` and `main.py` only). Re-checked at HEAD:
   `retrieve()` raises `MissingPrincipalError` before any repository access
   (`governance.py:124-128`) and `SingleUserPermissionEvaluator` grants only on
   owner, explicit grant, group intersection, or PUBLIC visibility
   (`:85-97`) — fail-closed, with `PROJECT` visibility not an implicit grant.
   Permission filtering runs over provider candidates at `:148-155`, and the
   first `Evidence` is constructed at `:170` from the permitted list only, so
   authorization precedes evidence assembly. One `RetrievalReceipt` is
   persisted per released evidence item inside the same loop (`:187-198`), and
   `EvidenceBundle.__post_init__` enforces the one-receipt-per-evidence
   correspondence. `governance.retrieve` remains the only public callable
   returning an `EvidenceBundle`, guarded by the package-wide sweep in
   `tests/test_governance.py:210`. The real-corpus run is consistent with all
   of this: 250 receipts for 25 query executions at 10 evidence items each,
   every receipt carrying the single principal `lee@leebase.com`, and every one
   of the 1,213 permission rows recording that owner at `private` visibility.

## Remediation Roadmap

### Fix Now
- S2-R-02 — remove the absolute host paths from the tracked playbook.

### Fix Soon
- S2-R-03 — stop discovering the corpus twice per sync, then re-record the baseline.
- S2-R-04 — detect nested/overlapping root paths.
- S2-R-05, S2-R-06, S2-R-07 — correct the counter partition docstrings and the two narrative counts in the report and `context.md`.

### Fix Later
- S2-R-08, S2-R-09, S2-R-10, S2-R-11 — traceability, stale test count, ruff config, and the two missing tests.

## Test Additions Recommended

- [ ] CLI test asserting the `git-ignored` and `git-ignore status unresolved` segments of the sync summary line.
- [ ] Connector test: a git-ignored file with an unregistered extension is counted once (`git_ignored == 1`, `unhandled_formats == {}`).
- [ ] Connector test: two configured roots where one contains the other — assert the configuration is rejected or the file is indexed once.
- [ ] Sync test asserting the corpus is discovered once per pass (e.g. by counting `discover_report` invocations).
- [ ] Connector test pinning the top-level-only semantics of `GLOBAL_DEFAULT_DENY`, so the limitation is a decision rather than an accident.
