# Code Review — Sprint 3, Round-Three Repair (positive contradiction signal, two-sided validation)

> Independent re-review, 2026-08-04. Reviewer role per `agents/reviewer.md` and
> `skills/code-review.md`. No implementation file was modified; every write in
> this step is inside `code-reviews/`.
>
> **Nothing below is accepted on the strength of the new regression fixtures,
> and nothing is accepted on a one-directional measurement.** The last two
> rounds each closed one direction and opened the other, so this review measures
> both: a false-conflict rate over reviewer-constructed *non-competing* pairs
> and a missed-contradiction rate over reviewer-constructed *contradicting*
> pairs, on the same corpora, against both the working tree and a
> `git archive HEAD` (a4f75b8) copy of the pre-round-three tree. Every corpus is
> reviewer wording that appears in no shipped fixture; each is written to disk,
> discovered and fetched through the real `LocalFilesConnector`, projected into
> real SQLite, and asked only through the public `answer()` surface — plus, for
> the worst finding, through the shipped `lee-kb sync` / `lee-kb ask` commands.
> Probe scripts and captured output live in this step's scratch space
> (`harness.py`, `probeA_two_directions.py`, `probeB_merge_refusal.py`,
> `probeC_absence.py`, `probeD_reconciliation.py`, `probeE_invariants.py`,
> `probeF_benchmark_corpus.py`, their `.out` files, `clitest/`, `pre-repair/`).
> Every command and exit code is listed under **Verification**.

## What This Slice Claimed

`code-reviews/review-sprint-3-repair-2.md` (verdict `fail`) raised one High
finding, **S3-R-15**: an undiscriminating branch in `_conflict_signal` reported
a `Conflict` whenever two same-topic statements' meaningful terms merely
*differed* above a similarity floor, measured at 5 of 6 constructed agreeing
pairs. This round claims it repaired by deleting that branch and replacing it
with two positive-evidence signals — a morphological-antonym check
(`restricted`/`unrestricted`) and a superset/elaboration rule applied to both
value words and meaningful terms — plus a widened synonym and value-word
vocabulary. It ships eight new regression items (27 collected, up from 19) and
a rewritten `docs/answer-benchmark-results.md` recommending **Ready after
specific follow-up**.

The direction the round measured did improve. The direction it did not measure
regressed, and the regression includes the original S3-R-01 defect this whole
sprint of repairs began with. Measured on identical corpora across both trees:

| Direction | Pre-round-three (`HEAD` a4f75b8) | This working tree |
|-----------|------------------------------:|------------------:|
| False conflicts over 8 non-competing pairs | 7/8 | **4/8** |
| Missed contradictions over 10 contradicting pairs | 0/10 | **5/10** |
| Contradictions merged into one self-contradictory claim | 0/10 | **2/10** |

Two same-authority sources reading *"The Nimbus archive is encrypted."* and
*"The Nimbus archive is not encrypted."* now merge into a single
`SYNTHESIZED` claim asserting both, with zero conflicts, and `lee-kb ask`
prints it as one confident answer.

## Findings

| ID | Severity | Category | Location | Problem | Proposed Fix |
|----|----------|----------|----------|---------|--------------|
| S3-R-17 | High | Correctness / confidently wrong output | `src/lee_kb/answer_conflict.py:420-434` (`_statements_mergeable` superset rule), `:332-338` (`_value_words_diverge` early return); consumed at `src/lee_kb/answer.py:416` (`_assemble_initial_claims`), user-visible via `src/lee_kb/main.py:550-556` | This round made "one statement is a strict superset of the other" mean *elaboration* in both `_statements_mergeable` and `_value_words_diverge`. A negation is a strict superset. When the negated word is **not** in the 27-entry `_VALUE_WORDS` list, `_value_words_diverge` returns `False` at line 335 because one side contributes no value word at all, `_morphological_antonyms_diverge` returns `False` (the difference set is empty on one side), and `_statements_mergeable` then returns `True` on `left_terms < right_terms` — so claim assembly **merges a statement with its own negation into one `SYNTHESIZED` claim citing both sources**, and `detect_conflicts` emits nothing. Measured directly on the predicates: `("The Nimbus archive is encrypted.", "The Nimbus archive is not encrypted.")` → `value_words_diverge=False, morphological=False, mergeable=True`; same for `never` (`"The Willow relay reports outages."` / `"...never reports outages."`). Measured end to end (probe A, reviewer corpora through the real connector and SQLite): 2 of 10 constructed contradicting pairs collapse to **1 claim, 1 merged claim, 0 conflicts**, with claim text `'The Nimbus archive is encrypted. The Nimbus archive is not encrypted.'`. **Both halves of the S3-R-01 fix are broken, not just detection**: probe B re-runs the same pairs with `lee_kb.answer.detect_conflicts` neutralised and the merge still happens, so the merge refusal is not independently holding. **Reproduced on the shipped surface**: `lee-kb sync` over two same-authority roots then `lee-kb ask "Is the Nimbus archive encrypted?"` prints one claim, `confidence: synthesized`, two citations under a single `[1]`, and no `Conflicts:` section — a reader is told two sources agree on a statement they directly contradict. The identical probe against a `git archive HEAD` (a4f75b8) copy of the pre-round-three tree yields 1 conflict and 2 singly-cited claims for both pairs, so this is a regression introduced by this round, not a pre-existing gap. This is the S3-R-01 shape (`code-reviews/review-sprint-3-governed-answer.md`) reappearing after two rounds of certified repair. | Treat negation as **polarity, not vocabulary**. Before the superset test in `_statements_mergeable`, strip a negation token set (`not`, `never`, `no`, `none`, `cannot`, `n't`) from both sides and compare polarity separately: if the de-negated term sets are equal or subset-related **and** the two sides' polarities differ, that is affirmative disagreement — refuse the merge and return a conflict signal, regardless of whether the negated word is in `_VALUE_WORDS`. `_value_words_diverge`'s negation branch already encodes this idea (`:340-346`) but is unreachable when either side has no value word; lift the polarity check out of it into `_conflict_signal` so it runs on every pair. Ship one regression fixture per shape asserting all three properties at once — exactly one `Conflict`, two singly-cited claims, and (with `detect_conflicts` neutralised) no merged claim — since a fixture asserting only the conflict count would have passed while this defect shipped. |
| S3-R-18 | High | Correctness / honest reporting (under-warning) | `src/lee_kb/answer_conflict.py:264-313` (`_conflict_signal`), specifically the deletion of the structural-divergence branch and the authority gate now on `:292-301` | Deleting the undiscriminating branch removed the **only** term-level signal that could see a substitution between two sources of the *same* declared authority. What replaced it — `_morphological_antonyms_diverge` — fires only on a `dis-`/`non-`/`un-` prefix pair, and the surviving structural test at `:292` is gated on `left.citation.authority is not right.citation.authority`. So a same-authority contradiction expressed as an ordinary substitution is now reported as two compatible claims with `result.conflicts == ()`. Measured (probe A, reviewer corpora, real connector and SQLite): **5 of 10** constructed contradicting pairs are missed, against **0 of 10** on the pre-round-three tree with the identical probe. Three are pure substitutions — *"…owned by the escalation desk."* vs *"…owned by the vendor desk."*; *"…falls on Tuesday."* vs *"…on Thursday."*; *"…stored in Frankfurt."* vs *"…stored in Dublin."* (the other two are S3-R-17). **Two of those three shapes are the evidence the previous round used to certify S3-R-10 repaired** — `code-reviews/review-sprint-3-repair-2.md`'s probe A used a weekday substitution (`Tuesday`/`Thursday`) and a proper-noun substitution (`security team`/`platform team`) — so this round silently withdrew a prior High finding's acceptance evidence without saying so. The defect also appears inside a multi-source corpus: probe D's `three-mutually-distinct` shape (Oslo / Lisbon / Athens across two authorities) reports 2 conflicts, not 3, because the Lisbon–Athens pair shares an authority. This contradicts `docs/answer-architecture.md:48` ("emit a `Conflict` for each disagreement"), and under-warning is worse than over-warning for this product: a reader who sees no `Conflicts:` section concludes the sources agree. The suite cannot catch it — all five family-5d contradicting fixtures are value-word, numeric, morphological-antonym, or cross-authority shapes; none is a same-authority substitution. | Implement the substitution gate the prior review proposed (its fix item **c**) instead of deleting the branch: fire when both sides supply **distinct fillers for the same slot in an otherwise-matching frame** — `len(left_only) == len(right_only) == 1` after synonym canonicalization, with the remaining terms equal — which catches proper-noun, weekday and place substitutions while leaving elaboration (superset), voice change (canonicalized) and added qualifiers alone. Gate it on that positive structure rather than on declared authority, and drop the authority gate from `:292` once it does (see S3-R-19). Add same-authority substitution cases to family 5d, and pin the missed-contradiction rate as a measured number, not a per-shape fixture count. |
| S3-R-19 | Medium | Correctness / honest reporting (over-warning residue) | `src/lee_kb/answer_conflict.py:292-301` (`_conflict_signal` authority branch), `:127` `_STRUCTURAL_DIVERGENCE_THRESHOLD`; fixtures at `tests/answers/test_answer_benchmarks.py:185-222` (`NON_COMPETING_CASES`) | The test S3-R-15 condemned — meaningful-term Jaccard ≥ 0.5 **and** unequal term sets, with no requirement that the difference be a disagreement — is still executed verbatim; it was not removed, it was moved behind an authority check. Cross-authority agreement is the single most common real shape (a canonical policy and a derived summary restating it), so gating on authority difference does not narrow the branch where it matters. Measured (probe A): **3 of 4** constructed cross-authority agreeing pairs are reported as conflicts while their same-authority twins are correctly silent — *"The escalation desk maintains the Sable incident log."* vs *"The Sable incident log is maintained by the escalation desk."* (voice change only, `maintains`/`maintained` absent from `_KNOWN_SYNONYM_SETS`), *"The Nimbus rota assigns triage to the duty engineer."* vs its passive restatement, and an added-attribution pair — each emitting *"…have different declared authority."* The suite pins none of this: all six `NON_COMPETING_CASES` construct two `SourceFixture`s with the default `Authority.DERIVED`, so family 5e proves the same-authority half only, and the benchmark document's claim for that family ("regardless of how much their surface text differs") is true only under that unstated restriction. The round's contradiction coverage also depends on the same hand list: the fix works for `owns`/`owned` because this round added `{own, owned, owning, owns}` to `_KNOWN_SYNONYM_SETS`, which is vocabulary widening of exactly the kind the last two rounds were failed for. | Apply the same positive-signal requirement to the authority branch: emit *"different declared authority"* only for pairs that already carry a term-level disagreement signal (substitution per S3-R-18, numeric, value-word, antonym, or polarity per S3-R-17), so declared authority becomes an **attribute** of a detected conflict rather than a detector in its own right. Add cross-authority variants of all six family-5e cases, and stop relying on `_KNOWN_SYNONYM_SETS` growth for morphology — a suffix-stripping normalization (`-s`, `-ed`, `-ing`) applied uniformly covers the class the hand list is chasing. |
| S3-R-20 | Medium | Correctness (over-warning) | `src/lee_kb/answer_conflict.py:339-346` (`_value_words_diverge` negation carve-out) | The negation carve-out added this round fires whenever the two sides' value-word sets differ in negation **and** share any non-negation value word, before the superset/elaboration rule at `:349` can suppress it. Emphatic agreement therefore reads as disagreement: *"The Fennel gate is required."* vs *"The Fennel gate is required, not optional."* → `value_words_diverge=True`, reported as *"Competing statements about fennel, gate use divergent value words."* (probe A, `emphatic-agreement-same-authority`, confirmed end to end). This is S3-R-12's elaboration shape re-entering through the exception carved beside the rule that closes it — the document claims S3-R-12 closed, and its named `required`/`required and approved` shape genuinely is (`mergeable=True`, verified), but the same class survives one word away. | Require the negated side's value words, minus the negation tokens, to be **equal to** the other side's rather than merely overlapping: `{mandate, not, optional} - {not} = {mandate, optional}` is a strict superset of `{mandate}` and is elaboration; `{mandate, not} - {not} = {mandate}` equals `{mandate}` and is genuine negation. Add `required` / `required, not optional` as a seventh family-5e case. |
| S3-R-21 | Medium | Documentation accuracy | `docs/answer-benchmark-results.md:8-35` (revision summary), `:66` (family 5e row), `:153-193` (Confidence Distribution), `:335-413` (Recommendation) | The document states the undiscriminating branch is "removed entirely" and replaced by positive signals. It is not removed: it runs at `answer_conflict.py:292-301` behind an authority gate, and produces 3 of 4 false conflicts on constructed cross-authority agreeing pairs (S3-R-19). Family 5e's row states its guarantee without recording that all six fixtures are same-authority, so a reader takes a half-measured property for a whole one. More consequentially, the document reports **only the direction this round improved**. This round's entire mechanism change is a trade between false conflicts and missed contradictions, and the document contains no missed-contradiction measurement at all — while 5 of my 10 constructed contradictions are now missed and 2 merge into one self-contradictory claim. The closing paragraph then asserts that the confidently-wrong-output class "(S3-R-01, S3-R-02, S3-R-03, S3-R-10, S3-R-11, S3-R-12, S3-R-15) are fixed and regression-tested across three repair rounds", when S3-R-01's exact shape is reproducible through `lee-kb ask` on the delivered tree. Everything the document *does* measure reproduces exactly — probe F rebuilds the twelve-document primary corpus and gets 11 claims, all `directly_evidenced`, **1** conflict total, 0 unresolved citations, matching the Confidence Distribution and its stated family-7 conflict-count correction. The recommendation **value**, *Ready after specific follow-up*, matches what I observe; its justification does not, and a reader using it to decide whether to release would believe the confidently-wrong class is closed when it is open. | Name the surviving authority-gated structural branch and say what it tests. Qualify family 5e to same-authority pairs. Report **both** rates every round — false conflicts over agreeing pairs and missed contradictions over contradicting pairs — with the corpora, so a one-directional improvement can never again read as a repair. Withdraw the claim that the confidently-wrong class is closed until S3-R-17 lands. |

### Prior High finding: partially repaired

**S3-R-15 (agreement reported as disagreement) — repaired for same-authority
pairs, still open for cross-authority pairs.** Measured on eight
reviewer-constructed non-competing pairs written to two source roots each and
asked through `answer()`: the false-conflict rate falls from **7/8** on the
pre-round-three tree to **4/8** here. All four same-authority agreeing pairs
that were flagged before are now silent, which is a genuine improvement and
matches what the new family-5e fixtures assert. The four that remain are three
cross-authority pairs going through the surviving structural test (S3-R-19) and
one emphatic-agreement pair going through the new negation carve-out
(S3-R-20). The pre-existing S3-R-12 shape the document claims closed
(`required` / `required and approved`) is genuinely closed — verified directly
on the predicate (`mergeable=True`) and end to end.

### Other prior repairs, re-derived and holding

- **S3-R-02 / S3-R-11 (absence).** Probe C: a control of two substantive
  same-topic sources yields 2 claims and `absence is None`. Adding an unrelated
  absence-shaped record (*"The Hyacinth microfilm index does not exist."*)
  changes nothing — 2 claims, both substantive claims intact, the absence
  sentence not surfaced at all. Adding a **responsive** absence record
  (*"A tier two Tamarind escalation ladder waiver does not exist."*) produces
  3 claims: the absence joins in rank order as its own singly-cited
  `DIRECTLY_EVIDENCED` claim and both substantive claims survive with their
  citations, none demoted to `evidence_omitted`. `probe C failures: none`.
- **S3-R-03 (reconciliation).** Probe D ran five shapes of three-to-four
  same-topic sources across two authorities, including one where the agreeing
  pair crosses authority and merges first. In every shape the maximum number of
  claims citing any one chunk is **1**, no surviving claim asserts both sides,
  every conflict side is present in `result.claims`, cited chunks are a subset
  of `evidence_used`, and `answer()` never raises. `probe D failures: none`.
- **Merge refusal, where it applies.** Probe B re-ran the eight same-authority
  contradicting pairs with `lee_kb.answer.detect_conflicts` neutralised: seven
  still produce two unmerged, singly-cited claims. The eighth is S3-R-17.

### Remediation Roadmap

**Fix Now** — S3-R-17, then S3-R-18. Until S3-R-17 lands, `lee-kb ask` can
return one confident claim asserting a statement and its negation, which is the
defect class this benchmark suite exists to prevent.

**Fix Soon** — S3-R-19 and S3-R-20 (the two remaining false-conflict
mechanisms), then S3-R-21, then the still-open S3-R-04 and S3-R-05.

**Fix Later** — S3-R-07, S3-R-08, S3-R-09.

### Test Additions Recommended

- [ ] Negated non-value-word pair (`X is encrypted.` / `X is not encrypted.`) → exactly 1 `Conflict`, 2 singly-cited claims, **and** no merged claim with `detect_conflicts` neutralised (S3-R-17).
- [ ] `never` variant of the same shape (`X reports outages.` / `X never reports outages.`) (S3-R-17).
- [ ] Same-authority proper-noun substitution (`owned by the escalation desk` / `by the vendor desk`) → 1 `Conflict` (S3-R-18).
- [ ] Same-authority weekday and place substitutions → 1 `Conflict` each (S3-R-18).
- [ ] Cross-authority variants of all six `NON_COMPETING_CASES` → `result.conflicts == ()` (S3-R-19).
- [ ] Emphatic agreement (`required` / `required, not optional`) → `result.conflicts == ()` (S3-R-20).
- [ ] A two-directional rate test: a fixed set of agreeing pairs and a fixed set of contradicting pairs, asserting an upper bound on false conflicts **and** an upper bound on missed contradictions, so no future round can improve one silently at the other's expense.

## Residual Risks

1. **Prior Medium findings that remain open.** `S3-R-04` — `Answer` still
   carries no withheld/truncated signal; `dataclasses.fields(Answer)` lists
   `question, principal, project, claims, confidence, receipt_ids,
   evidence_used, evidence_omitted, conflicts, absence, answered_at, prose,
   synthesis_provider_id` and nothing else, so withholding is visible only
   through `Absence.withheld_count`, which exists only when the answer has no
   claims. `S3-R-05` — `cmd_ask` (`src/lee_kb/main.py:619-625`) still calls
   `compute_answer()` with only `principal`, `project` and `top_k`, so
   `project_has_synchronized_content`, `corpus_fresh` and `resolution_failed`
   keep their defaults and the purpose-built `UNKNOWN` absence branch stays
   unreachable from the only shipped surface — probe E reaches it only by
   passing those arguments directly. `S3-R-12` and `S3-R-16` from
   `code-reviews/review-sprint-3-repair-2.md` are confirmed **closed** (the
   `required` / `required and approved` shape now merges cleanly; the benchmark
   document now names the family-7 conflict-count change), though S3-R-20 and
   S3-R-21 are adjacent new instances of the same two classes.
2. **Prior Low findings that remain open.** `S3-R-07` — the Provenance Examples
   still quote reformatted, heading-free claim text; every claim my probes
   produced from a headed document begins with the Markdown heading
   (`'# Tamarind Escalation Ladder\n\nThe Tamarind escalation ladder…'`), and
   probe F measures three claims for the fuzzy-name question where the document
   shows one. `S3-R-08` — `docs/answer-architecture.md:241` still reads "v1
   ships with no provider configured", while `answer()` defaults to
   `DEFAULT_SYNTHESIS_PROVIDER`. `S3-R-09` —
   `answer_evidence.py:215` still records `OUTSIDE_REQUESTED_PROJECT`
   omissions that reach the reader as `NOT_RELEVANT`. The Sprint 1/2 advisories
   (S1-R-14, S2-R-05 … S2-R-11) are untouched by this slice and remain open as
   recorded in `context.md`.
3. **The LLM-backed `SynthesisProvider` is unimplemented, pending dependency
   approval.** `answer()` ships with only `DeterministicSynthesisProvider`, a
   standard-library template renderer with no model call, so `lee-kb ask`
   returns structured template prose rather than natural-language synthesis. An
   LLM-backed provider requires a runtime model-client dependency, which is not
   approved under `AGENTS.md`'s "Add external runtime dependencies" guardrail
   (Open Question 6 in `context.md`). I verified that boundary rather than
   assuming it: `pyproject.toml`'s `project.dependencies` is `[]` (the only
   extra is `dev = [pytest>=7.0, black>=23.0, ruff>=0.1.0]`, build requires
   `setuptools>=61.0`, `wheel`); an AST walk over all **31** tracked `*.py`
   files finds exactly one non-stdlib, non-local import in the repository —
   `pytest`, in 13 test files; and a scan of `src/`, `tests/` and `tools/` for
   the model-client class (21 package names plus `claude-*`/`gpt-N` model-id
   shapes) returns exactly one hit, the English word "requests" inside a
   `governance.py:126` error string. Repository-wide, the remaining hits are
   four prior `code-reviews/` artifacts. No LLM client is imported.
4. **Live filesystem verification is deferred.** Every result in this review, in
   `docs/answer-benchmark-results.md` and in the delivered suite comes from
   temporary synthetic projections built for the test — including my own probes,
   which write throwaway roots under a temporary directory (and, for the CLI
   probe, under this step's scratch space) and sync them through the real
   connector into real SQLite. Nothing exercises `answer()` against a live,
   continuously-synchronized filesystem corpus over time: freshness drift,
   resync during use, tombstoning mid-question, concurrent sync. That
   verification path does not exist yet, so `answer()`'s behaviour under a
   moving corpus is unmeasured.
5. **`answer()` has still never been run against the real corpus.** `retrieve()`
   has a real-corpus baseline (`evidence/real-corpus-parity-report.md`, ~1,213
   documents); `answer()` has only the twelve-document synthetic fixture set
   plus small per-case corpora. Both of this round's open directions are
   corpus-shape sensitive: a real policy corpus holds far more cross-authority
   restatements (S3-R-19) and far more negated statements (S3-R-17) than
   twenty-seven fixtures do. This is Open Question 7.
6. **The see-saw is now the main risk, not any single finding.** Three
   consecutive rounds have each closed the previous round's High finding and
   opened a new one in the opposite direction: round two fixed merging and
   introduced over-warning; round three fixed over-warning and reintroduced
   merging. The mechanism is a hand-tuned word-list heuristic tested by
   per-shape fixtures, and per-shape fixtures cannot bound a rate. Until the
   suite measures both directions as rates over a fixed corpus set, a fourth
   round is as likely to trade back as to converge.
7. **Two Sprint 1/2 open questions are inherited unchanged.** The OR-matcher
   worst-case retrieval latency (~1.521s, Open Question 5) and permission-basis
   on receipts (Open Question 2) both apply to `answer()`, which calls
   `retrieve()` directly.

## Verification

### Preserved system-validator evidence (reported, not re-executed)

Validator rerun is not permitted for this step, so the eight preserved
`agent_orch.validators.command_succeeds@1` records are summarized from the
preserved artifact
(`.../step_03_independent_rereview_round_three/attempt-1/preserved-validator-evidence.json`)
— not re-run, and not restated from memory. All eight have exit status 0 and
`passed: true`.

| # | Command | Exit | Recorded result | Tied to |
|---|---------|-----:|-----------------|---------|
| 1 | `python3 -m pytest tests/` | 0 | `253 passed in 25.64s` | step_01 positive-contradiction-signal, criterion 1 (attempt 1) |
| 2 | `python3 -m pytest tests/` | 0 | `253 passed in 26.61s` | step_01, criterion 1 (attempt 2) |
| 3 | `python3 -m pytest` | 0 | `253 passed in 26.08s` | step_02 verification/docs, criterion 1 |
| 4 | `python3 -m black --check src tests tools` | 0 | `All done! ✨ 🍰 ✨` / `31 files would be left unchanged.` (stderr) | step_02, criterion 2 |
| 5 | `python3 -m ruff check src tests tools` | 0 | `All checks passed!`; emits the pre-existing `select`/`ignore` → `lint.*` deprecation warnings | step_02, criterion 3 |
| 6 | `python3 -m compileall -q src tests tools` | 0 | no output | step_02, criterion 4 |
| 7 | `python3 tools/check_disclosure.py` | 0 | `check_disclosure: clean — no host paths or credentials in tracked files.` | step_02, criterion 5 |
| 8 | `git diff --check` | 0 | no output | step_02, criterion 6 |

The product-verification commands are green. That is a real fact about the
delivered slice and it is not in tension with this review's verdict: S3-R-17
and S3-R-18 are shapes the suite contains no assertion about, which is finding
S3-R-21's point and residual risk 6's.

### Independent probes executed for this review

Each built a corpus on disk, discovered and fetched it through the real
`LocalFilesConnector`, and projected it into a real SQLite database — the
governed path was not mocked. Wording is reviewer-constructed and appears in no
shipped fixture.

| Probe | Command | Exit | What it establishes |
|-------|---------|-----:|---------------------|
| A | `python3 probeA_two_directions.py` | 0 | **Both rates, post-repair.** Eight non-competing pairs → **4 false conflicts** (3 cross-authority structural, 1 emphatic-agreement negation). Ten contradicting pairs → **5 missed**, of which **2 merge into one self-contradictory `SYNTHESIZED` claim** (`'The Nimbus archive is encrypted. The Nimbus archive is not encrypted.'`, and the same shape cross-authority). Numeric, value-word, morphological-antonym and cross-authority-substitution contradictions are all still caught. |
| A′ | `PROBE_SRC=<scratch>/pre-repair/src python3 probeA_two_directions.py` | 0 | **Pre-repair baseline — identical probe and corpora against a `git archive HEAD` (a4f75b8) copy.** **7 of 8** agreeing pairs emitted a conflict; **0 of 10** contradictions were missed and **0** merged. This is the trade the round made, measured in both directions. |
| B | `python3 probeB_merge_refusal.py` | 0 | **Merge refusal, both halves.** The eight same-authority contradicting pairs run normally and again with `lee_kb.answer.detect_conflicts` neutralised. Normal: 4 give 1 conflict + 2 singly-cited claims; 3 give 0 conflicts + 2 claims (S3-R-18); 1 gives 0 conflicts + 1 merged claim (S3-R-17). Neutralised: 7 of 8 still refuse to merge; the S3-R-17 pair merges with detection removed, so the merge refusal is not independently holding for it. |
| C | `python3 probeC_absence.py` | 0 | **Absence handling is additive and cannot suppress.** Control (2 substantive same-topic sources) → 2 claims, `absence is None`. + unrelated absence record → unchanged, 2 claims, the absence sentence not surfaced. + responsive absence record → **3** claims, the absence claim singly cited in rank order and both substantive claims intact. `probe C failures: none`. |
| D | `python3 probeD_reconciliation.py` | 0 | **Reconciliation holds.** Five three-to-four-source shapes across two authorities: max claims citing any one chunk is **1** everywhere, no claim asserts both sides, every conflict side present in `result.claims`, cited ⊆ used, no raise. `probe D failures: none`. Also shows S3-R-18 inside a multi-source corpus: the three-mutually-distinct shape reports 2 conflicts, not 3. |
| E | `python3 probeE_invariants.py` | 0 | **The sprint invariants hold.** E1: a transparent recording proxy shows the complete repository call set during `answer()` is `search` (from `lee_kb.retrieval`) then `record_receipt` ×2 (from `lee_kb.governance`) — identical to `retrieve()`'s on the same inputs — with **zero** calls originating in any `lee_kb.answer*` module; neutralizing `answer.retrieve` makes `answer()` raise rather than fall back. E2: 2 claims, **0** uncited, **0** unresolved citations, receipts == used ∪ omitted. E3: another principal's document → `INACCESSIBLE`, `withheld_count=1`, asserted **not** `NOT_FOUND`; silence → `NOT_FOUND`; `project_has_synchronized_content=False` → `UNKNOWN`; `resolution_failed=True` → `UNKNOWN`; four distinct detail strings. E4: `answer()`'s signature has **no** confidence parameter, confidence tracks evidence shape (term-identical sources → `synthesized`), and a claimless `Answer` with a non-`UNKNOWN` confidence is refused at construction. `probe E failures: none`. |
| F | `python3 probeF_benchmark_corpus.py` | 0 | **The benchmark document's published numbers reproduce exactly.** Rebuilding the twelve-document primary fixture corpus and asking the five family-7 questions gives **11 claims, all `directly_evidenced`, 0 `synthesized`, 1 conflict total (Meridian only), 0 unresolved citations** — matching the Confidence Distribution and its stated family-7 conflict-count correction. |
| — | inline `python3 -c` predicate probe | 0 | **Root cause, isolated from retrieval.** `_value_words_diverge` / `_morphological_antonyms_diverge` / `_statements_mergeable` on five hand pairs: the S3-R-12 shape is `mergeable=True` (closed); `encrypted`/`not encrypted` and `reports`/`never reports` are also `mergeable=True` (S3-R-17); `required`/`not required` is correctly `value_words_diverge=True`; `required`/`required, not optional` is wrongly `True` (S3-R-20). |
| CLI | `python3 -m lee_kb.main sync --config <scratch>/clitest/sources.toml --workspace-root <scratch>/clitest --database <scratch>/clitest/projection.sqlite` | 0 | `2 created`. Two same-authority `derived` roots holding the encrypted/not-encrypted pair. |
| CLI | `python3 -m lee_kb.main ask "Is the Nimbus archive encrypted?" --config <scratch>/clitest/sources.toml --principal lee` | 0 | **S3-R-17 is user-visible on the shipped surface.** One claim, `confidence: synthesized`, both sources cited under a single `[1]`, text asserting the statement and its negation, and **no** `Conflicts:` section. |
| — | `python3 -m pytest tests/answers/ --collect-only -q` | 0 | `27 tests collected in 0.07s` — confirms the claimed benchmark item count. Collection only; no test executed and no preserved validator command re-run. |

### Repository-wide invariant and disclosure scans

Run over the **class**, not a single pattern, and over **all 101 tracked files**
(`git ls-files`), not the delivered slice alone.

| Scan | Command | Result |
|------|---------|--------|
| Declared runtime dependencies | `python3 -c` reading `pyproject.toml` via `tomllib` | `project.dependencies == []`; the only extra is `dev = [pytest>=7.0, black>=23.0, ruff>=0.1.0]`; build requires `setuptools>=61.0`, `wheel`. **No runtime dependency was added.** |
| Every third-party import | AST walk over all **31** tracked `*.py` files, comparing each top-level import against `sys.stdlib_module_names` | The complete non-stdlib, non-local import set is `{pytest}` (13 test files). Nothing else. |
| LLM / model-client class | `git ls-files -z 'src/*' 'tests/*' 'tools/*' \| xargs -0 grep -InE '<21-package alternation + claude-*/gpt-N model-id shapes>'`, then repository-wide | **One** hit in product code, the English word "requests" in `src/lee_kb/governance.py:126`'s error string. Repository-wide, the only other files matching are four prior `code-reviews/` artifacts. **No LLM client is imported.** |
| `answer()` module imports | `grep` for `repository`/`retrieval` imports across the `answer*` modules | One match, `answer.py:91 from .repository import Repository`, inside the `if TYPE_CHECKING:` block — type-only. Corroborated dynamically by probe E1. |
| Absolute host paths | `git ls-files -z \| xargs -0 grep -InE '(/home/<u>\|/Users/<u>\|C:\\Users\\\|/root/<a>\|/var/folders/\|/private/var/\|/mnt/<a>\|/media/<a>\|/opt/<a>\|/srv/<a>)'` | **Zero** hits in `src/`, `tests/` or `tools/`. Every hit is a prior `code-reviews/` artifact quoting the closed S3-R-14 finding. S3-R-14 stays closed. |
| Delivered-slice scan | The same host-path and credential alternation over the six files this slice changed (`context.md`, `docs/answer-benchmark-results.md`, `result-review.md`, `src/lee_kb/answer.py`, `src/lee_kb/answer_conflict.py`, `tests/answers/test_answer_benchmarks.py`) | **Zero** hits. No new leak in anything this round delivered. |
| Credential shapes | `git ls-files -z \| xargs -0 grep -InE '(api[_-]?key\|secret[_-]?key\|client[_-]?secret\|access/refresh[_-]?token\|Bearer …\|password=\|private[_-]?key\|BEGIN … PRIVATE KEY\|AKIA…\|sk-…\|ghp_…\|xox[baprs]-\|eyJ…\|Authorization:)' | Four hits outside `code-reviews/`, all the connector's own secret **tripwire** and its tests: `research/employee-zero-kb-reference.md:44`, `src/lee_kb/connectors/local_files.py:158`, `tests/test_local_connector.py:711,713`. **No credential value anywhere.** |
| Private corpus content and artefacts | `grep -IlE 'ai-employee-factory\|ai-employee-book\|employee-zero\|Employee Zero\|tviq'` over all tracked files; plus `git ls-files \| grep -E '\.(sqlite\|db\|env\|pem\|key\|p12\|pfx\|crt)$\|\.lee-kb\|agent-orch-scratch'` | 30 files reference the corpus by **name** (project memory, architecture, playbooks, prior evidence) — root names and counts, no document content. **No** projection, key, environment or scratch artefact is tracked. |
| E-mail addresses | `git ls-files -z \| xargs -0 grep -IohE '<address pattern>' \| sort -u` | Exactly four distinct values: `anyone@example.com`, `intern@example.com`, `someone-else@example.com` (test placeholders) and `lee@leebase.com` (the published owner identity and documented default principal). No third-party address. |

### Review lenses and their outcome

| Lens | Outcome |
|------|---------|
| Governed surface exclusivity (`answer()` composes strictly over `retrieve()`) | Clean — probe E1: call-sequence identity with `retrieve()`, no repository call from any answer module, no fallback path, `repository` imported only under `TYPE_CHECKING`. |
| Citations and receipt closure | Clean — probes E2 and F: 0 uncited claims, 0 unresolved citations, receipts covering exactly used ∪ omitted. |
| Absence states | Clean — probe E3: three states distinguishable with distinct details, `INACCESSIBLE` never `NOT_FOUND`; probe C: the evidenced-absence path stays additive and cannot suppress a responsive answer. |
| Claim assembly and merge refusal | **S3-R-17.** Seven of eight same-authority contradictions stay unmerged with conflict detection neutralised; the negated-non-value-word pair merges into one claim asserting both sides, both with and without detection. |
| Conflict detection — false conflicts | **S3-R-19, S3-R-20.** Materially better than pre-repair (4/8 vs 7/8 on identical corpora) and fully repaired for same-authority pairs, but the condemned set-inequality test still runs behind an authority gate and the new negation carve-out mislabels emphatic agreement. |
| Conflict detection — missed contradictions | **S3-R-18.** 5 of 10 constructed contradictions missed, against 0 of 10 pre-repair; three are same-authority substitutions, two of which are the shapes the previous round used to certify S3-R-10 repaired. |
| Conflict reconciliation | Clean — probe D over five shapes across two authorities; one claim per chunk, no resurrected merge, no raise. |
| Confidence model | Clean — derived, not assertable (probe E4). |
| Dependency and LLM boundary | Clean — no runtime dependency added, no model client anywhere in product code (repository-wide over 101 tracked files, 31 Python files). |
| Disclosure and secrets | Clean — no absolute host path in `src/`, `tests/` or `tools/` and none in any file this slice changed, no credential value, no private corpus content, no tracked projection artefact. S3-R-14 stays closed. |
| Benchmark reproducibility and documentation | **S3-R-21.** Every number the document publishes re-derives exactly; the mechanism narrative around them does not, and the direction that regressed is not measured at all. |
| Tests and documentation | S3-R-21, plus the still-open S3-R-04, S3-R-05, S3-R-07, S3-R-08, S3-R-09 and the two-directional rate-test gap under Test Additions Recommended. |

### Readiness criteria

Recorded per this step's commissioning contract. Platform-owned post-execution
attestations (execution identity, executed route, validator authority,
semantic-judge execution, evidence-chain status) are produced after this step
returns and are **not** certified here; where the packet already carries a
record, it is reported, not re-derived.

| Criterion | State | Basis |
|-----------|-------|-------|
| Contradicting same-authority pairs yield a `Conflict` **and** two separately cited claims | `verified_false` | Probe A: 4 of 8 same-authority contradicting pairs yield no conflict; probe B: one of them merges into a single claim asserting both sides. |
| Merge refusal holds when conflict detection is bypassed | `verified_false` | Probe B: 7 of 8 hold; the negated-non-value-word pair merges with `detect_conflicts` neutralised (S3-R-17). |
| Conflict detection reports only real disagreement | `verified_false` | Probe A: 4 of 8 constructed non-competing pairs still emit a `Conflict` (3 cross-authority, 1 emphatic-agreement), against 7 of 8 pre-repair — improved, not closed (S3-R-19, S3-R-20). |
| Unrelated absence-shaped sentence does not suppress a multi-source answer | `verified_true` | Probe C: control/treatment; substantive claims and citations survive, and a responsive absence joins the answer additively. |
| Three same-topic sources across two authorities: one claim per chunk, no resurrected merge | `verified_true` | Probe D over five shapes; max citations per chunk 1, no both-sides claim, no raise. |
| `answer()` composes strictly over `governance.retrieve()` | `verified_true` | Probe E1 plus the import scan. |
| Every substantive claim carries a resolving citation | `verified_true` | Probes E2 and F: 0 uncited, 0 unresolved. |
| The three absence states remain distinguishable; `INACCESSIBLE` is never `NOT_FOUND` | `verified_true` | Probe E3, four distinct details. |
| Confidence is derived, not asserted | `verified_true` | Probe E4. |
| No runtime dependency added; no LLM client imported | `verified_true` | Repository-wide dependency, AST-import and model-client scans over all 101 tracked files. |
| No absolute host path, private corpus content, or credential-shaped detail in any tracked file | `verified_true` | Repository-wide class scans plus a delivered-slice scan; zero hits in `src/`, `tests/`, `tools/` or the six changed files. |
| Product verification commands green (per preserved system-validator records) | `verified_true` | Eight preserved records, all exit 0, summarized above. |
| Benchmark document's recommendation matches observed behaviour | `verified_false` | S3-R-21: the recommendation value is right; its justification claims a removed branch that still runs, states a same-authority-only guarantee unqualified, reports only the improved direction, and asserts the confidently-wrong class closed while S3-R-01's shape reproduces through `lee-kb ask`. |
| Semantic conformance independently judged | `not_evidenced` (`required_evidence`: `semantic_judge_execution`) | This playbook declares no `semantic_check` rule, so the packet marks that evidence class not applicable. |

### Verdict

**fail** — two High correctness findings, one of them a reintroduction of the
defect this repair sequence began with.

The round did what it was commissioned to do in the direction it measured.
Same-authority agreement is no longer reported as disagreement: on the identical
eight pairs, false conflicts fall from 7 to 4, and the four that cleared are
exactly the same-authority shapes S3-R-15 was filed against. S3-R-12 is
genuinely closed. Absence handling, reconciliation, governed exclusivity,
citation and receipt closure, absence distinguishability, derived confidence,
the dependency boundary and the disclosure surface all survived independent
probing, and every number `docs/answer-benchmark-results.md` publishes
re-derives exactly.

What it did not do is check the other direction. Replacing a too-broad signal
with two narrow positive ones removed the only detector for a same-authority
substitution (S3-R-18: 5 of 10 constructed contradictions now missed, against 0
of 10 before, including the two shapes the previous review used to certify
S3-R-10 repaired), and making "strict superset" mean elaboration made a
statement and its own negation mergeable whenever the negated word is outside a
27-word list (S3-R-17). The result is that `lee-kb ask` will print one
`synthesized` claim reading *"The Nimbus archive is encrypted. The Nimbus
archive is not encrypted."* with no conflict — S3-R-01, verbatim, three rounds
later. Meanwhile the condemned set-inequality test was not removed but gated on
declared authority, where it still fires on 3 of 4 cross-authority agreeing
pairs (S3-R-19), and the new negation carve-out reads emphatic agreement as
disagreement (S3-R-20).

Both fixes are bounded and local — treat negation as polarity rather than as an
added term, and gate the structural signal on a genuine substitution instead of
on authority — but the deeper issue is that three consecutive rounds have each
traded one direction for the other, because per-shape fixtures cannot bound a
rate. The next round should land with a two-directional measurement in the
suite, not two more fixtures.

Recommendation: **Ready after specific follow-up**, gated on S3-R-17 and
S3-R-18 landing together with a two-directional rate test, on S3-R-19 and
S3-R-20 closing the remaining false-conflict mechanisms, and on S3-R-21
correcting what the benchmark document claims was removed and what it leaves
unmeasured.

*Reviewed 2026-08-04. `tools/validate_verdict.py` was run against the
accompanying verdict before this review was finished.*
