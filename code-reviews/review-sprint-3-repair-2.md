# Code Review — Sprint 3, Round-Two Repair (invert merge rule, additive absence)

> Independent re-review, 2026-08-04. Reviewer role per `agents/reviewer.md` and
> `skills/code-review.md`. No implementation file was modified; every write in
> this step is inside `code-reviews/`.
>
> **Nothing below is accepted on the strength of the new regression fixtures.**
> Both prior High findings were re-derived from corpora I wrote for this review,
> using wording that appears in no shipped fixture, written to disk, discovered
> and fetched through the real `LocalFilesConnector`, projected into real
> SQLite, and asked only through the public `answer()` surface — plus, for one
> finding, through the shipped `lee-kb sync` / `lee-kb ask` commands. Where a
> claim is about a change in behaviour, I ran the *same* probe against a
> `git archive HEAD` copy of the pre-repair tree so the delta is measured, not
> asserted. Probe scripts and captured output live in this step's scratch space
> (`probeA_contradiction.py`, `probeB_absence.py`, `probeC_reconciliation.py`,
> `probeD_invariants.py`, `probeE_falsepositive.py`,
> `probeF_benchmark_corpus.py`, an inline probe G, plus `.out` files, `clitest/`
> and `pre-repair/`). Every command and exit code is listed under
> **Verification**.

## What This Slice Claimed

`code-reviews/review-sprint-3-repair.md` (verdict `fail`) raised two High
correctness findings. This round claims both repaired: **S3-R-10** by inverting
the merge rule to merge only on demonstrated term-equivalence and adding a
numeric-divergence conflict signal, and **S3-R-11** by making an evidenced
absence an *additional* claim in rank order rather than a replacement. It ships
four new regression items (19 collected, up from 15) and a rewritten
`docs/answer-benchmark-results.md` recommending **Ready after specific
follow-up**.

My independent re-derivation finds **both prior High findings genuinely and
generally repaired** — not shape-bound this time. Probe A attacks S3-R-10 with
four constructed contradiction shapes, none of which reuse the fixture wording,
and verifies *both* halves of the fix, including with conflict detection
neutralized entirely. Probe B attacks S3-R-11 with a top-ranked absence record
of my own construction, and the substantive answer survives.

The cost of that repair is a new defect. The third change this round made to
`_conflict_signal` — an unmentioned structural-divergence branch — reports
**agreement as disagreement** on ordinary paraphrase, elaboration and voice
change. Measured against the pre-repair tree with an identical probe, the rate
on constructed non-competing pairs went from 1 in 6 to 5 in 6, and the defect is
now live inside the project's own benchmark corpus and visible through
`lee-kb ask`.

## Findings

| ID | Severity | Category | Location | Problem | Proposed Fix |
|----|----------|----------|----------|---------|--------------|
| S3-R-15 | High | Correctness / honest reporting | `src/lee_kb/answer_conflict.py:259-267` (`_conflict_signal` structural-divergence branch), `:85` `_STRUCTURAL_DIVERGENCE_THRESHOLD`, `:317` `_statements_mergeable`; user-visible at `src/lee_kb/main.py:568-577` | The branch this round added at the end of `_conflict_signal` emits *"Competing statements about … differ in meaningful terms."* whenever two same-topic statements have a meaningful-term Jaccard of at least 0.5 **and** unequal term sets. Set inequality is not disagreement, so mere difference is reported as conflict. **Independently measured** (probe E: six constructed non-competing pairs, each written to two same-authority source roots, discovered through the real connector into real SQLite, then the identical probe and corpora re-run against a `git archive HEAD` (41476a6) copy of the pre-repair tree): **5 of 6** agreeing pairs now emit a `Conflict`, against **1 of 6** pre-repair. *"The platform team owns the Perseus runbook."* vs *"The Perseus runbook is owned by the platform team."* — identical meaning, differing only in voice — is reported as competing, because `owns` ≠ `owned` (Jaccard 0.667). So is *"The Halcyon policy retains audit logs."* vs the same sentence plus *"under section 4."*, where one side is a strict elaboration of the other (0.625), and *"The Vega ingest queue runs in the north region."* against the same sentence plus a time qualifier (0.667). The defect is **reachable from the project's own benchmark fixtures**: probe F rebuilds the twelve-document primary corpus and asks the five family-7 questions; *"What does harbor readiness require from the cobalt checklist?"* now emits a conflict between the duplicate-repository statement and the independent-audit statement whose own text reads *"The independent audit **confirms** that harbor readiness requires the cobalt checklist."* Family-7 conflicts go from **3 pre-repair to 4 post-repair** on the identical corpus. **Reproduced end to end through the shipped CLI**: `lee-kb sync` then `lee-kb ask "Who owns the Perseus runbook?"` prints both agreeing statements as two `directly_evidenced` claims and then lists them under a `Conflicts:` heading with *"newer: neither; more authoritative: neither"*. The suite cannot catch this: the only negative fixture, `tests/test_answer_conflict.py:208`, uses a pair at Jaccard 0.4 — *below* the 0.5 gate — so it passes without ever exercising the branch, and no fixture asserts that agreeing statements produce no conflict. Two of the three new family-5d fixtures (`enabled-versus-turned-off` at exactly 0.500, `permitted-versus-forbidden` at 0.600) pass through **this same undiscriminating branch**, not through any antonym test, so they green-light the defect rather than bounding it. Calibration, stated plainly: no claim text is wrong, nothing is suppressed, every citation still resolves, and the failure direction is over-warning rather than under-warning — on claim-level correctness alone this would be Medium, and the prior review rated its narrower pre-existing form (S3-R-12) Medium. It is filed **High** because this round widened it fivefold on constructed non-competing pairs, moved it into the benchmark corpus's own published results, and made it user-visible on the only shipped surface: a reader cannot tell which entries under `Conflicts:` are real disagreements, and a machine consumer filtering on `conflicts` receives mostly noise. | Require a positive contradiction signal instead of set inequality. (a) Treat a strict superset of meaningful terms as **elaboration**, not divergence, and apply the same superset rule to `_value_words_diverge`, which also closes the pre-existing S3-R-12 Corvus shape. (b) Normalize light morphology (`owns`/`owned`, `list`/`listed`, `retains`/`retained`) before comparing term sets, so a paraphrase is not a disagreement — `_KNOWN_SYNONYM_SETS` already has the right shape and only needs to stop being a two-entry hand list. (c) Gate the branch on a genuine **substitution**: both sides must supply distinct fillers for the same slot in an otherwise matching frame (both a number, both a value word, both a proper noun), rather than merely differing. (d) Add permanent regression fixtures for agreeing pairs — elaboration, voice change, added qualifier — each asserting `result.conflicts == ()`, and pin the expected conflict count for the family-7 harbor-readiness question, so this class cannot regress silently again. Raising `_STRUCTURAL_DIVERGENCE_THRESHOLD` alone is **not** a fix: the Kestrel fixture sits at exactly 0.500 and would break first. |
| S3-R-16 | Medium | Documentation accuracy | `docs/answer-benchmark-results.md:8-25` (revision summary), `:55` (family 5d row), `:237-240` (Conflict Examples), `:299-312` (Recommendation §1) | The benchmark document describes this round's conflict-detection work as two changes — inverting the merge rule and adding a numeric-divergence signal — and never mentions the third, the meaningful-term structural-divergence branch. Probe G measures which branch actually fires for each fixture: the numeric signal fires only for Lyra; **Kestrel and Vega both fire the structural branch**. The document nonetheless describes those two as reproducing "the same shape for antonym pairs outside the fixed vocabulary", when the branch that catches them performs no antonym test at all and fires identically on elaboration and voice change. Family 5d's stated guarantee is therefore true as measured but is *not* evidence of the property the row claims to prove. Separately, the document reports the family-7 behaviour change it likes (10 claims → 11; `SYNTHESIZED` 9+1 → 11+0 — probe F reproduces both figures exactly, pre and post) but not the change on the same question that it does not: conflicts 3 → 4. And Recommendation §1 still presents S3-R-12 as the single narrow remaining conflict defect, scoped to the value-word and authority branches, when a broader one now ships; the closing paragraph's assertion that no confidently-wrong-output defect remains no longer holds. The recommendation **value**, *Ready after specific follow-up*, matches what I observe; its stated justification does not, and a reader using this document to decide whether to release would understate the open correctness surface. | Name the structural-divergence branch in the revision summary and in the family 5d row, and describe what it actually tests (term-set inequality above a similarity floor), not antonymy. Report the family-7 conflict-count change alongside the confidence-distribution change, since both come from the same repair on the same question. Replace Recommendation §1 with S3-R-15, noting S3-R-12 as its narrower subset, and drop the closing sentence's implication that no confidently-wrong-output defect remains. |

### Prior High findings confirmed repaired

**S3-R-10 (contradiction merged into one self-contradictory claim) — repaired,
both halves, verified beyond its fixtures.** Probe A ran four same-authority
two-source corpora, none reusing the shipped Kestrel/Vega/Lyra/Equinox wording:
an out-of-vocabulary antonym (`restricted`/`unrestricted`), a weekday
substitution (`Tuesday`/`Thursday`), a numeric interval (`6 hours`/`24 hours`),
and a proper-noun substitution (`security team`/`platform team`). In all four,
**half one** holds — exactly one `Conflict`, exactly two claims, each singly
cited, one per source root — and **half two** holds: with
`lee_kb.answer.detect_conflicts` replaced by a function returning `()`, all four
*still* produce two separate `DIRECTLY_EVIDENCED` claims and zero merged claims.
That is precisely what the prior review warned about — the merge surviving even
if detection improves — and it does not survive here. Probe E′ confirms the
inversion is what changed: the control contradiction
(`restricted`/`unrestricted`) merges into one claim with zero conflicts at
`HEAD` and splits correctly in the working tree.

**S3-R-11 (evidenced absence replacing a responsive answer) — repaired.**
Probe B's control asks *"What does the quill publication standard require?"*
over two `CANONICAL` sources and gets two claims. The treatment adds one short
`CANONICAL` record reading *"The quill publication standard microfiche archive
does not exist."* — same topic, different aspect, deliberately short so it wins
the governed rank, and it does: it is `evidence_used[0]`. The answer is now
**3 claims**, not 1: the absence record appears first as its own singly-cited
`DIRECTLY_EVIDENCED` claim and **both substantive claims survive with their
citations**, with no substantive source demoted to `evidence_omitted`. A further
run confirms an absence-shaped sentence about an unrelated topic is not surfaced
at all. The top-rank heuristic removed from `classify_absence` is genuinely no
longer needed, exactly as the prior review proposed.

**Reconciliation (S3-R-03) holds under the new merge rule.** Probe C ran five
shapes of three-to-four same-topic sources across two authorities — one
canonical + two identical derived; two identical canonical + one derived; a
shape where the *agreeing* pair is cross-authority and merges first; three
mutually distinct statements; and 2+2 with two agreeing pairs. In all five, the
maximum number of claims citing any one chunk is **1**, no surviving claim
asserts both sides, every conflict side is present in `result.claims`, cited
chunks equal used-evidence chunks, and `answer()` never raises.

### Remediation Roadmap

**Fix Now** — S3-R-15, with the class-level negative fixtures described in its
proposed fix. Until then the `Conflicts:` section of `lee-kb ask` cannot be
trusted, and the benchmark corpus publishes one false conflict of its own.

**Fix Soon** — S3-R-16, then the still-open S3-R-04 and S3-R-05.

**Fix Later** — S3-R-07, S3-R-08, S3-R-09.

### Test Additions Recommended

- [ ] Agreeing pair, strict elaboration (`X retains logs.` / `X retains logs under section 4.`) → `result.conflicts == ()` (S3-R-15).
- [ ] Agreeing pair, voice change (`A owns B.` / `B is owned by A.`) → `result.conflicts == ()` (S3-R-15).
- [ ] Agreeing pair, added qualifier → `result.conflicts == ()` (S3-R-15).
- [ ] Agreeing pair with asymmetric value words (`required` / `required and approved`) → `result.conflicts == ()` (S3-R-12, subsumed by S3-R-15).
- [ ] Pin the expected conflict count for the family-7 harbor-readiness question, so a widening of conflict detection cannot pass silently again (S3-R-15).
- [ ] A same-authority contradiction fixture whose similarity sits well above 0.5, so family 5d does not depend on a case sitting exactly on the threshold.

## Residual Risks

1. **Prior Medium findings that remain open.** `S3-R-04` — `Answer` still
   carries no withheld/truncated signal; `dataclasses.fields(Answer)` lists
   `question, principal, project, claims, confidence, receipt_ids,
   evidence_used, evidence_omitted, conflicts, absence, answered_at, prose,
   synthesis_provider_id` and nothing else, so withholding is visible only
   through `Absence.withheld_count`, which exists only when the answer has no
   claims. `S3-R-05` — `cmd_ask` (`src/lee_kb/main.py:619`) still calls
   `compute_answer()` with only `principal`, `project` and `top_k`, so
   `project_has_synchronized_content`, `corpus_fresh` and `resolution_failed`
   keep their defaults and the purpose-built `UNKNOWN` absence branch stays
   unreachable from the only shipped surface — probe D3 reaches it only by
   passing those arguments directly. `S3-R-12` remains open as the narrower
   value-word case of S3-R-15 (probe E pair P4 reproduces it against both trees)
   and should be closed by the same fix.
2. **Prior Low findings that remain open.** `S3-R-07` — the Provenance Examples
   still quote reformatted, heading-free claim text, and probe F measures three
   claims for the fuzzy-name question where the document shows one. `S3-R-08` —
   `docs/answer-architecture.md:241` still reads "v1 ships with no provider
   configured", while `answer()` defaults to `DEFAULT_SYNTHESIS_PROVIDER`.
   `S3-R-09` — `answer_evidence.py:111 as_answer_omission` still reports
   `OUTSIDE_REQUESTED_PROJECT` to the reader as `NOT_RELEVANT`. `S3-R-06` and
   `S3-R-14` stay closed: probe F reproduces the corrected Confidence
   Distribution exactly, and the repository-wide host-path scan finds no hit in
   `src/`, `tests/` or `tools/`.
3. **The LLM-backed `SynthesisProvider` is unimplemented, pending dependency
   approval.** `answer()` ships with only `DeterministicSynthesisProvider`, a
   standard-library template renderer with no model call, so `lee-kb ask`
   returns structured template prose rather than natural-language synthesis. An
   LLM-backed provider requires a runtime model-client dependency, which is not
   approved under `AGENTS.md`'s "Add external runtime dependencies" guardrail
   (Open Question 6 in `context.md`). I verified that boundary rather than
   assuming it: `pyproject.toml`'s `project.dependencies` is `[]` (the only
   extra is `dev = [pytest>=7.0, black>=23.0, ruff>=0.1.0]`); an AST walk over
   all **31** tracked `*.py` files finds exactly one non-stdlib, non-local
   import in the entire repository — `pytest`, in 13 test files; and a
   repository-wide scan of all **98** tracked files for the model-client class
   (`anthropic`, `openai`, `langchain`, `llama_index`, `litellm`, `cohere`,
   `mistralai`, `ollama`, `generativeai`, `transformers`, `huggingface`,
   `sentence_transformers`, `tiktoken`, `vertexai`, `bedrock`, `llama_cpp`,
   `httpx`, `requests`, `aiohttp`, `urllib3`, `torch`, plus `claude-*`/`gpt-N`
   model-id shapes) returns exactly one hit in `src/`, `tests/` or `tools/` —
   the English word "requests" inside a `governance.py` error string. The
   remaining hits are `playbooks/*.yaml`, `research/`, `architecture.md`,
   `evidence/` and `code-reviews/`, none of them product code.
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
   plus small per-case corpora. S3-R-15 is corpus-shape sensitive in the
   direction that matters: a real policy corpus contains far more near-duplicate
   restatements, elaborations and cross-references than fourteen fixtures do, so
   I expect its false-conflict incidence there to be materially higher than the
   single instance visible in the benchmark corpus. This is Open Question 7.
6. **The suite still cannot catch the defect it was written beside.** S3-R-15
   survives a green 245-test suite and a green 19/19 benchmark run, exactly as
   S3-R-10 and S3-R-11 survived a green 241-test suite. The pattern is now three
   rounds old: each round's fixtures pin the shape the finding was reported
   against, and the round's *new* behaviour goes unpinned in the opposite
   direction. Negative fixtures — asserting what must **not** be reported — are
   the missing half.
7. **Two Sprint 1/2 open questions are inherited unchanged.** The OR-matcher
   worst-case retrieval latency (~1.521s, Open Question 5) and permission-basis
   on receipts (Open Question 2) both apply to `answer()`, which calls
   `retrieve()` directly.

## Verification

### Preserved system-validator evidence (reported, not re-executed)

Validator rerun is not permitted for this step, so the eight preserved
`agent_orch.validators.command_succeeds@1` records are summarized from the
preserved artifact
(`.../step_03_independent_rereview_round_two/attempt-2/preserved-validator-evidence.json`)
— not re-run, and not restated from memory. All eight have exit status 0 and
`passed: true`.

| # | Command | Exit | Recorded result | Tied to |
|---|---------|-----:|-----------------|---------|
| 1 | `python3 -m pytest tests/` | 0 | `245 passed in 23.04s` | step_01 invert-merge/additive-absence, criterion 1 (attempt 1) |
| 2 | `python3 -m pytest tests/` | 0 | `245 passed in 23.29s` | step_01, criterion 1 (attempt 2) |
| 3 | `python3 -m pytest` | 0 | `245 passed in 24.07s` | step_02 verification/docs, criterion 1 |
| 4 | `python3 -m black --check src tests tools` | 0 | `All done! ✨ 🍰 ✨` / `31 files would be left unchanged.` | step_02, criterion 2 |
| 5 | `python3 -m ruff check src tests tools` | 0 | `All checks passed!`; emits the pre-existing `select`/`ignore` → `lint.*` deprecation warnings | step_02, criterion 3 |
| 6 | `python3 -m compileall -q src tests tools` | 0 | no output | step_02, criterion 4 |
| 7 | `python3 tools/check_disclosure.py` | 0 | `check_disclosure: clean — no host paths or credentials in tracked files.` | step_02, criterion 5 |
| 8 | `git diff --check` | 0 | no output | step_02, criterion 6 |

The product-verification commands are green. That is a real fact about the
delivered slice and it is not in tension with this review's verdict: S3-R-15 is
a shape the suite does not assert against, which is finding S3-R-16's point and
residual risk 6's.

### Independent probes executed for this review

Each built a corpus on disk, discovered and fetched it through the real
`LocalFilesConnector`, and projected it into a real SQLite database — the
governed path was not mocked.

| Probe | Command | Exit | What it establishes |
|-------|---------|-----:|---------------------|
| A | `python3 probeA_contradiction.py` | 0 | **S3-R-10 repaired, both halves.** Four same-authority two-source corpora in reviewer wording (`restricted`/`unrestricted`, `Tuesday`/`Thursday`, `6 hours`/`24 hours`, `security team`/`platform team`). Half 1: each yields exactly 1 `Conflict`, 2 claims, each singly cited, one per root. Half 2: with `lee_kb.answer.detect_conflicts` neutralized, each **still** yields 2 unmerged claims — the merge refusal is independent of detection. `probe A failures: none`. |
| B | `python3 probeB_absence.py` | 0 | **S3-R-11 repaired.** Control (two `CANONICAL` quill sources) → 2 claims. Treatment (identical corpus + one short same-topic `CANONICAL` "does not exist" record) → the record ranks **first** in the governed bundle and the answer is **3** claims: the absence record as its own singly-cited `DIRECTLY_EVIDENCED` claim plus both substantive claims, with no substantive source demoted to `evidence_omitted`. An unrelated absence sentence is not surfaced at all. 7/7 checks pass. |
| C | `python3 probeC_reconciliation.py` | 0 | **Reconciliation holds under the new merge rule.** Five shapes of three-to-four same-topic sources across two authorities, including one where the agreeing pair is cross-authority and merges first: in every case max citations of any one chunk is **1**, no claim asserts both sides, every conflict side is present in `result.claims`, cited chunks equal used chunks, and `answer()` never raises. `probe C failures: none`. |
| D | `python3 probeD_invariants.py` | 0 | **The sprint invariants hold.** D1: a transparent recording proxy shows the complete repository call set during `answer()` is `search` (from `lee_kb.retrieval`) then `record_receipt` ×2 (from `lee_kb.governance`) — identical to the sequence `retrieve()` alone produces on the same inputs — with **zero** calls originating in any `lee_kb.answer*` module; neutralizing `answer.retrieve` makes `answer()` raise rather than fall back, so no alternate evidence path exists. D2: 2 claims, **0** uncited, **0** unresolved citations, `receipt_ids` == `evidence_used ∪ evidence_omitted`. D3: a document owned by another principal → `INACCESSIBLE`, `withheld_count=1`, `UNKNOWN`, asserted **not** `NOT_FOUND`; silence → `NOT_FOUND`; `project_has_synchronized_content=False` → `UNKNOWN`; `resolution_failed=True` → `UNKNOWN`; four distinct detail strings. D4: `answer()`'s signature has **no** confidence parameter, and confidence tracks evidence shape (term-identical sources → `synthesized`; differing sources → two `directly_evidenced`). `probe D failures: none`. |
| E | `python3 probeE_falsepositive.py <repo>/src` | 0 | **S3-R-15, post-repair measurement.** Six constructed non-competing pairs plus one control contradiction: **5 of 6** agreeing pairs emit a `Conflict` (voice change, elaboration, added qualifier, added attribute, inflected paraphrase); the sixth, whose term sets are exactly equal, merges cleanly. The control contradiction is detected. |
| E′ | `python3 probeE_falsepositive.py <scratch>/pre-repair/src` | 0 | **S3-R-15, pre-repair baseline — identical probe and corpora against a `git archive HEAD` (41476a6) copy.** **1 of 6** agreeing pairs emits a `Conflict` (the pre-existing S3-R-12 value-word shape) — and the control contradiction is **missed**, merging into one claim. This is the trade the round made, measured in both directions. |
| F | `python3 probeF_benchmark_corpus.py <repo>` | 0 | **The benchmark document's numbers reproduce, and the defect reaches its corpus.** Rebuilding the twelve-document primary fixture corpus and asking the five family-7 questions gives **11 claims, all `directly_evidenced`, 0 `synthesized`, 0 unresolved citations** — matching the document exactly. It also gives **4** conflicts, one of them between the duplicate-repository harbor statement and the independent-audit statement that says it *confirms* that statement. |
| F′ | `python3 probeF_benchmark_corpus.py <scratch>/pre-repair` | 0 | **Pre-repair baseline for the same corpus:** 10 claims (9 `directly_evidenced` + 1 `synthesized`) and **3** conflicts. Confirms both the document's stated confidence-distribution change and the unreported conflict-count change 3 → 4. |
| G | inline `python3 -` branch attribution | 0 | **Which conflict branch fires for each fixture.** Kestrel 0.500 → structural; Vega 0.600 → structural; Lyra 0.667 → numeric; harbor-readiness 0.625 → structural; elaboration 0.625 → structural; voice change 0.667 → structural. Basis for S3-R-16 and for the "raising the threshold is not a fix" note in S3-R-15. |
| CLI | `python3 -m lee_kb.main sync --config <scratch>/clitest/sources.toml` | 0 | `2 created`. Two `CANONICAL` roots holding the voice-change pair. |
| CLI | `python3 -m lee_kb.main ask "Who owns the Perseus runbook?" --config <scratch>/clitest/sources.toml` | 0 | **S3-R-15 is user-visible on the shipped surface.** Prints both agreeing statements as two `directly_evidenced` claims, then a `Conflicts:` section quoting both with *"newer: neither; more authoritative: neither"*. |
| — | `python3 -m pytest tests/answers/ --collect-only -q` | 0 | `19 tests collected in 0.07s` — confirms the claimed benchmark item count. Collection only; no test executed and no preserved validator command re-run. |

### Repository-wide invariant and disclosure scans

Run over the **class**, not a single pattern, and over **all 98 tracked files**
(`git ls-files`), not the delivered slice alone.

| Scan | Command | Result |
|------|---------|--------|
| Declared runtime dependencies | `python3 -c` reading `pyproject.toml` via `tomllib` | `project.dependencies == []`; the only extra is `dev = [pytest>=7.0, black>=23.0, ruff>=0.1.0]`; build requires `setuptools>=61.0`, `wheel`. **No runtime dependency was added.** |
| Every third-party import | AST walk over all **31** tracked `*.py` files, comparing each top-level import against `sys.stdlib_module_names` | The complete non-stdlib, non-local import set is `{pytest}` (13 test files). Nothing else. |
| LLM / model-client class | `git ls-files -z \| xargs -0 grep -InE '<22-term alternation + claude-*/gpt-N model-id shapes>'` scoped to `src/ tests/ tools/`, then repository-wide | **One** hit in product code, and it is the English word "requests" in `src/lee_kb/governance.py:126`'s error string. Repository-wide hits are confined to `playbooks/*.yaml`, `research/`, `architecture.md`, `evidence/` and `code-reviews/`. **No LLM client is imported.** |
| `answer()` module imports | `grep` for `repository`/`retrieval` imports across the five `answer*` modules | One match, `answer.py:90 from .repository import Repository`, inside the `if TYPE_CHECKING:` block — type-only, not a runtime import. Corroborated dynamically by probe D1. |
| Network / execution capability | `grep -rInE 'import socket\|urllib\|http\.client\|smtplib\|ftplib\|import subprocess\|os\.system\|popen\|eval(\|exec('` over `src/` | One source: `connectors/local_files.py:95 import subprocess`, used to run `git check-ignore` with a fixed argv and piped stdin (Sprint 1/2 code; no shell, no user-controlled binary). No network capability anywhere in `src/`. |
| Absolute host paths | `git ls-files -z \| xargs -0 grep -InE '(/home/<u>\|/Users/<u>\|C:\\Users\\\|/root/<a>\|/var/folders/\|/private/var/\|/mnt/<a>/\|/media/<a>/\|/opt/<a>/\|/srv/<a>/\|~/<a>/<b>)'` | **Zero** hits in `src/`, `tests/` or `tools/` other than the documented public config contract `~/.config/lee-kb/config.toml` and `tools/check_disclosure.py`'s own pattern literals. S3-R-14's `tests/test_contracts.py` hit is gone. The remaining repository-wide hits are prior `code-reviews/` artifacts quoting that finding, plus `README.md`, `architecture.md`, `context.md`, `docs/decisions.md` and `main.py` citing the config contract. **No new leak; nothing in the round-two delivered files.** |
| Credential shapes | `git ls-files -z \| xargs -0 grep -InE '(api[_-]?key\|secret[_-]?key\|client[_-]?secret\|access/refresh[_-]?token\|Bearer …\|password=\|private[_-]?key\|BEGIN … PRIVATE KEY\|AKIA…\|sk-…\|ghp_…\|xox[baprs]-\|eyJ…\|Authorization:)'` | Four hits outside `code-reviews/`, all the connector's own secret **tripwire** and its tests: `research/employee-zero-kb-reference.md:44` (the rule), `connectors/local_files.py:158` (the pattern docstring), `tests/test_local_connector.py:711,713` (assertions exercising it). **No credential value anywhere.** |
| Private corpus content and artefacts | `grep -IlE 'ai-employee-factory\|ai-employee-book\|employee-zero\|Employee Zero\|tviq\|knowledge/sources\.toml'` over all tracked files; plus `git ls-files \| grep -E '\.(sqlite\|sqlite3\|db\|env\|pem\|key\|p12\|pfx\|crt)$\|\.lee-kb\|\.kb/\|\.agent-orch-scratch'` | 28 files reference the corpus by **name** (project memory, architecture, playbooks, prior evidence) — root names and counts, no document content. **No** `.sqlite`, `.db`, `.env`, `.pem`, key artefact or scratch directory is tracked. |
| E-mail addresses | `git ls-files -z \| xargs -0 grep -IohE '<address pattern>' \| sort -u` | Exactly four distinct values: `anyone@example.com`, `intern@example.com`, `someone-else@example.com` (test placeholders) and `lee@leebase.com` (the published owner identity and documented default principal). No third-party address. |

### Review lenses and their outcome

| Lens | Outcome |
|------|---------|
| Governed surface exclusivity (`answer()` composes strictly over `retrieve()`) | Clean — probe D1: call-sequence identity with `retrieve()`, no repository call from any answer module, no fallback path, `repository` imported only under `TYPE_CHECKING`. |
| Citations and receipt closure | Clean — probes D2 and F: 0 uncited claims, 0 unresolved citations, receipts covering exactly used ∪ omitted. |
| Absence states | Clean — probe D3: three states distinguishable with distinct details, `INACCESSIBLE` never `NOT_FOUND`; probe B: the evidenced-absence path is now additive and cannot suppress a responsive answer. **S3-R-11 repaired.** |
| Claim assembly and merge refusal | Clean — probe A, both halves, on four constructed shapes; the merge refusal holds with conflict detection removed entirely. **S3-R-10 repaired.** |
| Conflict detection | **S3-R-15.** Contradiction detection is materially better than pre-repair; disagreement *reporting* is materially worse — 5 of 6 constructed agreeing pairs are reported as competing, against 1 of 6 pre-repair, and one instance now ships inside the benchmark corpus. |
| Conflict reconciliation | Clean — probe C over five shapes; one claim per chunk, no resurrected merge, no raise. |
| Confidence model | Clean — derived, not assertable (probe D4). |
| Dependency and LLM boundary | Clean — no runtime dependency added, no model client anywhere in product code (repository-wide over 98 tracked files, 31 Python files). |
| Disclosure and secrets | Clean — no absolute host path in `src/`, `tests/` or `tools/`, no credential value, no private corpus content, no tracked projection artefact. S3-R-14 is closed. |
| Benchmark reproducibility and documentation | **S3-R-16.** Every number I re-derived reproduces exactly, pre and post; the narrative around which repair produced them does not, and one measured change on the same question goes unreported. |
| Tests and documentation | S3-R-16, plus the still-open S3-R-04, S3-R-05, S3-R-07, S3-R-08, S3-R-09, S3-R-12 and the negative-fixture gap under Test Additions Recommended. |

### Readiness criteria

Recorded per this step's commissioning contract. Platform-owned post-execution
attestations (execution identity, executed route, validator authority,
semantic-judge execution, evidence-chain status) are produced after this step
returns and are **not** certified here; where the packet already carries a
record, it is reported, not re-derived.

| Criterion | State | Basis |
|-----------|-------|-------|
| S3-R-10 contradiction repair complete, both halves | `verified_true` | Probe A: four constructed shapes; conflict + two singly-cited claims, and merge refusal holds with detection neutralized. |
| S3-R-11 additive-absence repair complete | `verified_true` | Probe B: control/treatment; a top-ranked same-topic absence record joins the answer and both substantive claims survive. |
| Conflict reconciliation: one claim per chunk, no resurrected merge | `verified_true` | Probe C over five shapes across two authorities. |
| Conflict detection reports only real disagreement | `verified_false` | Probe E vs E′: 5/6 constructed agreeing pairs reported as conflicts, against 1/6 pre-repair; probe F: reaches the project's own benchmark corpus; reproduced through `lee-kb ask`. |
| `answer()` composes strictly over `governance.retrieve()` | `verified_true` | Probe D1 plus the import scan. |
| Every substantive claim carries a resolving citation | `verified_true` | Probes D2 and F: 0 uncited, 0 unresolved. |
| The three absence states remain distinguishable; `INACCESSIBLE` is never `NOT_FOUND` | `verified_true` | Probe D3. |
| Confidence is derived, not asserted | `verified_true` | Probe D4. |
| No runtime dependency added; no LLM client imported | `verified_true` | Repository-wide dependency, AST-import and model-client scans over all 98 tracked files. |
| No absolute host path, private corpus content, or credential-shaped detail in any tracked file | `verified_true` | Repository-wide class scans; S3-R-14 closed; no hit in `src/`, `tests/` or `tools/`. |
| Product verification commands green (per preserved system-validator records) | `verified_true` | Eight preserved records, all exit 0, summarized above. |
| Benchmark document's recommendation matches observed behaviour | `verified_false` | S3-R-16: the recommendation value is right; its stated justification omits the branch that produced both the gain and the regression, and one measured change on the same question. |
| Semantic conformance independently judged | `not_evidenced` (`required_evidence`: `semantic_judge_execution`) | This playbook declares no `semantic_check` rule, so the packet marks that evidence class not applicable. |

### Verdict

**fail** — one High correctness finding introduced by this round.

Both prior High findings are genuinely repaired, and this time the repairs
generalize: I attacked S3-R-10 with four contradiction shapes none of which
appear in any fixture, verified the merge refusal survives with conflict
detection removed entirely, and could not reproduce the defect. S3-R-11 is
closed by construction — making the evidenced absence additive removes the
suppression path rather than narrowing its gate — and reconciliation, governed
exclusivity, citation and receipt closure, absence distinguishability, derived
confidence, the dependency boundary and the disclosure surface all survived
independent probing.

The round nonetheless ships a regression. Making conflict detection fire on
term-set inequality above a similarity floor buys the contradiction coverage
S3-R-10 demanded and pays for it by calling ordinary paraphrase a disagreement:
measured on the same six constructed pairs against both trees, false conflicts
went from 1 in 6 to 5 in 6; the benchmark corpus's own harbor-readiness question
now reports a conflict between a statement and the audit that confirms it; and
`lee-kb ask` prints two identical-meaning sentences under a `Conflicts:`
heading. The fix is bounded and local — require a positive contradiction signal
rather than set inequality, and add the negative fixtures that would have caught
this — but it is not yet done, and the benchmark document does not tell a reader
it is outstanding.

Recommendation: **Ready after specific follow-up**, gated on S3-R-15 landing
with the negative fixtures named above and on S3-R-16 correcting what the
benchmark document attributes to which change.

*Reviewed 2026-08-04. `tools/validate_verdict.py` was run against the
accompanying verdict before this review was finished.*
