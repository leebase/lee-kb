# Code Review — Sprint 3, Governed `answer()` Surface

> Independent review, 2026-08-04. Reviewer role per `agents/reviewer.md` and
> `skills/code-review.md`. No implementation file was modified; every write in
> this step is inside `code-reviews/`.
>
> Every invariant below is backed by a probe this review **executed** against a
> real corpus written to disk, discovered through the real `LocalFilesConnector`
> and projected into a real SQLite database — not by reading the code alone.
> The probe scripts and their captured output live in this step's scratch space
> (`probe1_exclusivity.py` … `probe5_invariants.py` plus `.out` files); the
> commands and exit codes are listed under **Verification**.

## Architecture Summary

Sprint 3 adds five modules and one CLI subcommand on top of the already-shipped
governed retrieval path. `answer()` (`src/lee_kb/answer.py`) is a deterministic
composition: `question → retrieve() → classify_absence() → select_evidence() →
claim assembly → detect_conflicts() → reconciliation → optional narration →
Answer`. Authorization, project scoping, freshness reporting, and receipt
persistence are inherited from `governance.retrieve()` rather than
reimplemented. `answer_contracts.py` enforces provenance, disjointness, and
absence invariants at construction time; `answer_evidence.py` partitions the
governed bundle into selected and reasoned-omitted evidence;
`answer_absence.py` classifies `NOT_FOUND` / `INACCESSIBLE` / `UNKNOWN`;
`answer_conflict.py` emits pairwise conflicts with `newer` /
`more_authoritative` signals and no winner. `DeterministicSynthesisProvider` is
an offline template renderer over already-finalized claims. `lee-kb ask`
(`src/lee_kb/main.py:591` `cmd_ask`) is the user-facing surface.

The governance skeleton is sound, and everywhere I attacked it, it held: the
governed-surface exclusivity invariant (S1-R-01), fail-closed principal,
permission-filtering-before-assembly, one-receipt-per-released-item, the
three-way absence distinction, conflict retention without a winner, and derived
(never asserted) confidence are all proven below by executed probe.

Three High findings are defects in the layer built on that skeleton — claim
assembly, absence short-circuiting, and conflict reconciliation. Each produces a
confidently-labelled wrong answer, each was reproduced from a deliberately
constructed corpus, and one reproduces end to end through the shipped
`lee-kb ask` command against a real on-disk projection.

## Findings

| ID | Severity | Category | Location | Problem | Proposed Fix |
|----|----------|----------|----------|---------|--------------|
| S3-R-01 | High | Correctness / conflict detection | `src/lee_kb/answer_conflict.py:195` `_conflict_signal`; `src/lee_kb/answer.py:414` `_assemble_initial_claims` | Two sources of the **same** declared authority that directly contradict each other produce **no** `Conflict`, and — because their meaningful-term overlap clears the 0.5 similarity threshold — are merged into one `SYNTHESIZED` claim whose text asserts both sides at once. `_conflict_signal` fires only on differing `Authority`, or on explicit supersession wording in the newer text; a plain contradiction between two `DERIVED` documents matches neither, so it returns `None` before comparing what the statements actually say. **Constructed and proven** (probe 3b): two `DERIVED` documents, `"The deployment channel for Meridian is enabled."` and `"… is disabled."`, with different source timestamps, yield 1 claim, `confidence=SYNTHESIZED`, text `'# B\n\nThe deployment channel for Meridian is disabled. # A\n\n… is enabled.'`, and **0 conflicts**. Reproduced through the shipped CLI against a real projection (`lee-kb sync` then `lee-kb ask`), which prints that single self-contradictory claim under `Confidence: synthesized`, cites both files, and shows no Conflicts section. This violates the invariant stated in `src/lee_kb/answer.py:23-26`: "two sources that disagree are always presented as two separate, cited claims rather than one claim asserting both." Benchmark family 5 misses it because its two Meridian fixtures are deliberately `CANONICAL` vs `DERIVED` — probe 3a confirms that shape works correctly (2 claims, 1 conflict, both sides retained). | Add a third conflict signal for value-word divergence between same-subject statements, reusing the `_VALUE_WORDS` set already at `answer_conflict.py:58` (`enabled`/`disabled`, `required`/`optional`, `open`/`closed`, `not`/`never`): when two same-subject statements carry diverging value words, emit a `Conflict` regardless of authority or timestamp. Independently, refuse to merge two evidence items in `_assemble_initial_claims` when their value words diverge, whatever the Jaccard similarity — the merge is the more dangerous half, since it survives even if detection is later improved. Extend benchmark family 5 with a same-authority contradiction fixture asserting one `Conflict` and two separate cited claims. |
| S3-R-02 | High | Correctness / answer quality | `src/lee_kb/answer_absence.py:210` `classify_absence`, `:245` `_explicit_absence_evidence`; `src/lee_kb/answer.py:228` | The evidenced-absence path runs **before** evidence selection and short-circuits the entire pipeline. Its gate is one regex hit plus a **single** shared meaningful term with the question, evaluated over every retrieved chunk, and it bypasses `select_evidence()` entirely, so neither the relevance threshold nor per-source allocation applies. Any unrelated sentence matching a generic pattern (`does not exist`, `was not created`) therefore replaces the real answer. **Constructed and proven as a control/treatment A/B** (probe 2f plus its control run): the control corpus — two `CANONICAL` documents answering "What does harbor readiness require?" — returns 2 `DIRECTLY_EVIDENCED` claims citing both canonical sources. Adding one unrelated `DERIVED` note reading "The legacy harbor manifest does not exist." to the *identical* corpus collapses the answer to exactly 1 claim — the legacy note — still labelled `DIRECTLY_EVIDENCED`, citing only the derived source, with both canonical documents demoted to `evidence_omitted` under "Not part of the explicit statement answering this question." The reader receives a confidently-labelled non-answer and cannot tell the correct evidence was suppressed. Probe 2e shows the same short-circuit can also erase an `INACCESSIBLE` signal: a withheld document plus one absence-shaped public sentence reports neither the withholding nor the real question. | Run `select_evidence()` first and evaluate `_explicit_absence_evidence` only over selected evidence, so the relevance threshold and per-source allocation both apply. Additionally require the absence-bearing sentence itself to clear the same question-term coverage test `_relevance()` uses at `answer_evidence.py:283`, rather than sharing a single token, and require the matched chunk to be top-ranked in the governed bundle. Add a regression test for "absence-shaped sentence present but not responsive to the question" asserting the substantive claims survive. |
| S3-R-03 | High | Correctness / conflict reconciliation | `src/lee_kb/answer.py:452` `_reconcile_with_conflicts`; `src/lee_kb/answer_conflict.py:102` `detect_conflicts` | `detect_conflicts` builds its `evidence_claims` map once, before any reconstitution, so when one conflicting pair splits a merged claim, a **later** pair still resolves to the now-displaced merged claim. `_reconcile_with_conflicts` drops that merged claim from `kept`, but `retain_conflict_sides` re-appends it because a conflict still references it. **Constructed and proven** (probe 3c): three same-topic sources (one `CANONICAL` "enabled", two `DERIVED` "disabled") return **4 claims from 3 evidence items**; the chunks for `a.md` and `c.md` are each cited by **two** different claims (their reconstituted direct claim and the resurrected merged claim); the resurrected `SYNTHESIZED` claim asserts both "enabled" and "disabled"; and conflict #2 pairs that self-contradictory claim against the third source, which is meaningless to a reader. This also violates `detect_conflicts`'s own documented rule at `answer_conflict.py:179` — "selected evidence may support at most one assembled claim" — in the final `Answer`. `Answer._check_provenance` (`answer_contracts.py:532`) does not catch it, because it only requires claim citations to be a **subset** of `evidence_used`, never that a chunk is cited at most once. | Make reconstitution transitive: when a merged claim is split, update `evidence_claims` so every subsequent pair resolves to the reconstituted single-evidence claims, and re-key any already-emitted conflict that referenced the merged claim onto those sides. Then add an invariant to `Answer._check_provenance` that no chunk may be cited by more than one claim, so this class of defect fails at construction rather than surfacing as duplicated prose. Add a three-source benchmark fixture asserting exactly one claim per chunk. |
| S3-R-04 | Medium | Governance / honest reporting | `src/lee_kb/answer.py:360` `_assemble_evidenced_answer`; `src/lee_kb/answer_contracts.py` `Answer` | `Answer` carries no equivalent of `EvidenceBundle.denied_count` or `EvidenceBundle.truncated`. Withholding is visible only through `Absence.withheld_count`, which exists only when the answer has **no** claims. **Proven** (probe 6b): with one permitted and one denied matching item, `answer()` returns a normal single-claim `DIRECTLY_EVIDENCED` answer, `absence is None`, `evidence_omitted` empty, and `dataclasses.fields(Answer)` contains no `withheld`, `denied`, or `truncated` field at all. `docs/answer-architecture.md:73-76` argues the reader "is entitled to know" what was set aside; that guarantee currently holds for relevance and redundancy but not for permission denial or `top_k` truncation. | Add `withheld_count: int = 0` and `truncated: bool = False` to `Answer`, populated from `bundle.denied_count` / `bundle.truncated` on every assembly path — count only, no titles or locators, matching the `INACCESSIBLE` disclosure rule at `docs/answer-architecture.md:211` — and render both in `_print_answer`. |
| S3-R-05 | Medium | Correctness / absence semantics at the shipped surface | `src/lee_kb/main.py:591` `cmd_ask` (call site `:619`) | `cmd_ask` calls `compute_answer(repository, question, principal=, project=, top_k=)` and never supplies `project_has_synchronized_content`, `corpus_fresh`, or `resolution_failed`, so those defaults (`True`, `None`, `False`) are permanent for the only user-facing surface. **Proven** (probe 6c): `lee-kb ask "What is the quartz ledger?" --project never-synced` against a real on-disk projection prints `[not_found] The governed corpus search returned no matching evidence. searched projects: never-synced`. `classify_absence` has a purpose-built branch that would report exactly this as `UNKNOWN` ("The requested project has no synchronized content."), and `docs/answer-architecture.md:204-206` calls reporting `UNKNOWN` as `NOT_FOUND` "the most dangerous of the three." The correct state is reachable through the library API and unreachable through the CLI. | In `cmd_ask`, look up whether the requested project has any live items and pass `project_has_synchronized_content=` accordingly; pass `resolution_failed=True` when retrieval raises a provider error rather than letting it propagate. Add a CLI test for an unsynchronized project asserting `unknown`, not `not_found`. |
| S3-R-06 | Medium | Documentation accuracy | `docs/answer-benchmark-results.md:100-105` | The Confidence Distribution table states `DIRECTLY_EVIDENCED = 12` "across the five questions in family 7". **Independent reproduction** (probe 4d — rebuilding the same eight synthetic fixtures through the real connector and repository and asking the same five questions) gives **9** `DIRECTLY_EVIDENCED` and 1 `SYNTHESIZED`: 10 claims, all citations resolving. The table's own "Where" cell explains the gap — it counts the documentation-steward question's three claims twice ("documentation-steward question again via the cross-repository test (3, same claims)"). Same defect class as S2-R-17, repaired last sprint. | Correct the count to 9 and rewrite the "Where" cell as `documentation-steward (3), fuzzy-name (3), Orbital Archive absence (1), both Meridian sides (2)`, stating explicitly that family 3 re-asks family 1's question and its claims are not additional. |
| S3-R-07 | Low | Documentation accuracy / output quality | `docs/answer-benchmark-results.md:71-83`; `src/lee_kb/answer.py:482` `_direct_claim`, `:490` `_synthesized_claim` | Claim text is the raw chunk (`evidence.text.strip()`), so every claim begins with the source's markdown heading and keeps its hard line wraps; merged claims concatenate two whole chunks, headings included. The document says its examples are "reproduced directly … by calling `answer()` in-process", but Example 1 quotes a heading-free, re-wrapped version. **Proven** (probe 4e): the real claim text is `'# Documentation Steward Naming Decision\n\nThe full official name is …'`. Example 1 also presents the question as producing one claim; probe 4d shows it produces three. | Either strip the leading heading in `_direct_claim` (it is already carried on `Citation.heading`) or quote the claim verbatim in the document, and state that the example shows one of three claims. |
| S3-R-08 | Low | Documentation accuracy | `docs/answer-architecture.md:241` | "v1 ships with no provider configured: `answer()` returns claims and citations, and prose is optional." The delivered `answer()` defaults `synthesis_provider` to `DEFAULT_SYNTHESIS_PROVIDER` (`answer.py:159`, `:215-219`), so prose is produced on every evidenced answer unless the caller passes `synthesis_provider=None`. The governance intent (no LLM in v1) holds; the normative sentence does not describe the code. | Update to: "v1 ships with `DeterministicSynthesisProvider` configured by default — offline, template-rendered, LLM-free; pass `synthesis_provider=None` for a claims-only answer." |
| S3-R-09 | Low | Retrieval quality / reporting | `src/lee_kb/answer_evidence.py:111` `as_answer_omission` | `SelectionOmissionReason.OUTSIDE_REQUESTED_PROJECT` is reported to the reader as `OmissionReason.NOT_RELEVANT`. A project-scope rejection is a governance/scoping decision, not a relevance judgement; the distinction survives only in free-text `detail`. The docstring acknowledges the collapse, which makes it deliberate but still lossy for a machine consumer filtering on `reason`. | Add an `OUT_OF_SCOPE` member to `OmissionReason` and map to it, or document in `docs/answer-architecture.md` that `reason` is a coarse public view and `detail` is authoritative. |

### Remediation Roadmap

**Fix Now** — S3-R-01, S3-R-02, S3-R-03. Each produces a confidently-labelled
wrong answer on the sprint's headline surface, each is reachable from ordinary
corpus shapes, and S3-R-01 reproduces through the shipped CLI. All three should
land with a benchmark fixture, because the existing seven families pass over all
three.

**Fix Soon** — S3-R-04 and S3-R-05 (honest-reporting gaps the architecture
document already commits to), then S3-R-06.

**Fix Later** — S3-R-07, S3-R-08, S3-R-09.

### Test Additions Recommended

- [ ] Benchmark family 5 extension: same-authority contradiction → one `Conflict`, two separate cited claims, no merged claim (S3-R-01).
- [ ] Benchmark fixture: three same-topic sources → exactly one claim per chunk, no claim asserting both sides (S3-R-03).
- [ ] `tests/test_answer_absence.py`: an absence-shaped sentence that is not responsive to the question must not suppress the substantive claims (S3-R-02).
- [ ] `tests/test_answer.py`: a partially-denied result must report the withheld count on the `Answer` (S3-R-04).
- [ ] `tests/test_cli.py`: `lee-kb ask --project <never-synced>` must report `unknown`, not `not_found` (S3-R-05).

## Residual Risks

1. **The LLM-backed `SynthesisProvider` is unimplemented, pending dependency
   approval.** `answer()` ships with only `DeterministicSynthesisProvider`, a
   standard-library template renderer with no model call. An LLM-backed provider
   requires a runtime model-client dependency, which is not approved under
   `AGENTS.md`'s "Add external runtime dependencies" guardrail (Open Question 6
   in `context.md`). I verified that boundary rather than assuming it:
   `pyproject.toml`'s `project.dependencies` is `[]`; the only non-stdlib,
   non-local import across all 19 tracked Python files is `pytest` (a dev
   extra); and a repository-wide scan of all 78 tracked files for `anthropic`,
   `openai`, `langchain`, `litellm`, `cohere`, `mistralai`, `ollama`,
   `google.generativeai`, `transformers`, `huggingface`,
   `sentence_transformers`, `tiktoken`, `vertexai`, `bedrock`, `llama_cpp`,
   `httpx`, `requests`, `torch`, and `gpt-N`/`claude-*` model-id shapes returns
   zero hits in product code. The seam is real, but until a provider exists,
   `lee-kb ask` returns template prose, not natural-language synthesis — a
   reader expecting synthesis gets structure instead.
2. **Live filesystem verification is deferred.** Every result in this review, in
   the benchmark document, and in the delivered test suite comes from temporary
   synthetic projections built for the test — including my own probes, which
   write throwaway roots under a temporary directory and sync them through the
   real connector into real SQLite. Nothing exercises `answer()` against a live,
   continuously-synchronized filesystem corpus over time: freshness drift,
   resync during use, tombstoning mid-question, concurrent sync. That
   verification path does not exist yet, so `answer()`'s behavior under a moving
   corpus is unmeasured.
3. **`answer()` has never been run against the real corpus.** `retrieve()` has a
   real-corpus baseline (`evidence/real-corpus-parity-report.md`, ~1,213
   documents); `answer()` has only the eight-document synthetic fixture set.
   Claim-assembly behavior, conflict and absence rates, and latency at real scale
   are unknown. The three High findings are corpus-shape sensitive, and a real
   corpus holds far more absence-shaped sentences and same-authority
   near-duplicates than eight fixtures do, so I expect their incidence there to
   be materially higher than in the suite.
4. **Two Sprint 1/2 open questions are inherited unchanged.** The OR-matcher
   worst-case retrieval latency (~1.521s, Open Question 5) and permission-basis
   on receipts (Open Question 2) both apply to `answer()`, which calls
   `retrieve()` directly.
5. **The benchmark corpus cannot catch the defects it was written beside.** All
   three High findings survive a green 12/12 benchmark run and a green 235-test
   suite. The families are well chosen for the behaviors they target, but
   conflict coverage is a single cross-authority pair, and the absence family
   uses a corpus where the absence-shaped sentence *is* the correct answer.
   Repairs should land with fixtures, or the next regression will pass the same
   way.

## Verification

### Preserved system-validator evidence (reported, not re-executed)

Validator rerun is not permitted for this step, so the 14 preserved
`agent_orch.validators.command_succeeds@1` records are summarized from the
preserved artifact (`preserved-validator-evidence.json`) — not re-run, and not
restated from memory. All 14 have exit status 0 and `passed: true`.

| # | Command | Exit | Recorded result | Tied to |
|---|---------|-----:|-----------------|---------|
| 1 | `python3 -m pytest tests/` | 0 | 186 passed in 13.79s | step_01 contracts, criterion 1 |
| 2 | `env PYTHONPATH=src python3 -c "from lee_kb import answer_contracts"` | 0 | import succeeds, no output | step_01 contracts, criterion 2 |
| 3 | `python3 -m pytest tests/` | 0 | 193 passed in 14.75s | step_02 evidence selection |
| 4 | `python3 -m pytest tests/` | 0 | 204 passed in 15.79s | step_03 absence/conflict |
| 5 | `python3 -m pytest tests/` | 0 | 204 passed in 16.09s | step_03 absence/conflict |
| 6 | `python3 -m pytest tests/` | 0 | 223 passed in 19.02s | step_04 assembly and CLI, criterion 1 |
| 7 | `env PYTHONPATH=src python3 -m lee_kb.main ask --help` | 0 | `ask` help renders; `--database` documented | step_04 assembly and CLI, criterion 2 |
| 8 | `python3 -m pytest tests/answers/` | 0 | 12 passed in 0.40s | step_05 regression fixtures, criterion 1 |
| 9 | `python3 -m pytest tests/` | 0 | 235 passed in 19.46s | step_05 regression fixtures, criterion 2 |
| 10 | `python3 -m pytest` | 0 | 235 passed in 20.56s | step_06 verification/benchmark/docs, criterion 1 |
| 11 | `python3 -m black --check src tests tools` | 0 | 30 files would be left unchanged | step_06, criterion 2 |
| 12 | `python3 -m ruff check src tests tools` | 0 | clean; emits `select`/`ignore` → `lint.*` deprecation warnings | step_06, criterion 3 |
| 13 | `python3 -m compileall -q src tests tools` | 0 | no output | step_06, criterion 4 |
| 14 | `git diff --check` | 0 | no whitespace errors | step_06, criterion 5 |

`docs/answer-benchmark-results.md`'s two quoted figures — `12 passed in 0.40s`
and `235 passed in 19.46s` — match records 8 and 9 exactly. The document's
recommendation is **"Ready after specific follow-up"**, which is inside this
step's declared recommendation vocabulary. (The mission text says "one of the
three permitted values" while the commissioning contract declares four; the
value used is valid under either reading.)

### Independent probes executed for this review

Each ran against a corpus written to disk, discovered and fetched through the
real `LocalFilesConnector`, and projected into a real SQLite database — the
governed path was not mocked. All exited 0.

| Probe | Command | Exit | What it establishes |
|-------|---------|-----:|---------------------|
| 1 | `python3 probe1_exclusivity.py` | 0 | **Governed surface exclusivity (S1-R-01) holds.** A transparent recording proxy wrapped the repository: the complete set of repository calls during `answer()` is `search` (from `lee_kb.retrieval`) then `record_receipt` ×2 (from `lee_kb.governance`) — **identical to the call sequence produced by `retrieve()` alone on the same inputs**, and **no repository call originates in any `lee_kb.answer*` module**. Neutralizing `answer.retrieve` makes `answer()` raise rather than fall back, proving there is no alternate evidence path. Spying `LexicalRetriever.search` shows its only caller during `answer()` is `lee_kb.governance`. The single `repository` import in the answer modules (`answer.py:86`) is inside `if TYPE_CHECKING:`. |
| 2 | `python3 probe2_absence.py` | 0 | **The three absence states are produced from distinguishable inputs and do not collapse — and the evidenced-absence path defeats them.** An **inaccessible** case was constructed (matching document owned by another principal): reported `INACCESSIBLE`, `withheld_count=1`, `UNKNOWN` confidence, and asserted **not** `NOT_FOUND`. Silence → `NOT_FOUND` with `UNKNOWN` confidence; `project_has_synchronized_content=False` → `UNKNOWN`; `resolution_failed=True` → `UNKNOWN`; each carries a distinct detail string. The control/treatment A/B in 2f is finding S3-R-02; 2e shows the same path can erase an `INACCESSIBLE` signal. |
| 3 | `python3 probe3_conflict.py` | 0 | **Conflict retention holds for the benchmark shape and breaks for two constructed shapes.** 3a (`CANONICAL` vs `DERIVED`): 2 claims, 1 conflict, both sides retained and cited, no `winner` attribute on `Conflict`, `more_authoritative=Side.LEFT`, `newer=Side.NEITHER`. 3b (same authority, plain contradiction) → finding S3-R-01. 3c (three sources) → finding S3-R-03, with a per-chunk citation count printed showing two chunks each cited by two claims. |
| 4 | `python3 probe4_confidence_provenance.py` | 0 | **Confidence is derived, not asserted; citations resolve; omissions are real.** The same question over one directly-quoted chunk yields `DIRECTLY_EVIDENCED`; over two independent sources stating the same thing it yields `SYNTHESIZED` — different evidence shape, different confidence, same caller. `answer()`'s signature has **no** confidence parameter, so a caller cannot assert one. Over the rebuilt benchmark corpus and its five questions: 10 claims, **0 unresolved citations** (every `item_id` and `chunk_id` resolves to a real item and chunk in the repository), and `receipt_ids` covers **exactly** `evidence_used ∪ evidence_omitted` for all five. `evidence_omitted` is genuinely populated rather than always empty: the harbor-readiness question carries two real `redundant` omissions with stated reasons, and probe 2f produced two more. Benchmark Examples 1 and 2 and the Conflict Example were each reproduced independently (Example 1 with the text discrepancy that is S3-R-07); the confidence distribution reproduced as 9+1, which is S3-R-06. |
| 5 | `python3 probe5_invariants.py` | 0 | **Sprint 1 and Sprint 2 invariants still hold under `answer()`.** Fail-closed principal: omitted, `None`, and a bare `str` principal each raise `MissingPrincipalError` before any repository access. Permission filtering precedes evidence assembly: a denied item's text appears in no claim and its chunk appears in neither `evidence_used` nor `evidence_omitted` — unreachable, not merely unrendered. One receipt per released evidence item, and the projection's `retrieval_receipts` table holds exactly one row after one `answer()`, with **zero** rows referencing the denied item. Nested/overlapping roots: each file claimed by exactly one root (parent→`top.md`, child→`inner.md`). Health-gated sync: a missing required root reports `healthy=False`, `missing required roots: ghost`. |
| 6 | `python3 -m lee_kb.main sync --database …` then `python3 -m lee_kb.main ask …` | 0 | **S3-R-01 reproduces through the shipped CLI**, not only in-process: two same-authority contradicting documents synced through `lee-kb sync` and asked through `lee-kb ask` print one `synthesized` claim asserting both "disabled" and "enabled", citing both files, with no Conflicts section. |
| 7 | in-process `dataclasses.fields(Answer)` + denied-item answer; `python3 -m lee_kb.main ask … --project never-synced` | 0 | Findings S3-R-04 (no withholding signal anywhere on `Answer`) and S3-R-05 (the CLI cannot reach the `UNKNOWN` absence branch). |

### Repository-wide dependency and disclosure scans

Run over the **class**, not a single pattern, and over **all 78 tracked files**
(`git ls-files`), not the delivered slice alone.

| Scan | Command | Result |
|------|---------|--------|
| Declared runtime dependencies | `python3 -c` reading `pyproject.toml` via `tomllib` | `project.dependencies == []`. The only extra is `dev = [pytest, black, ruff]`; build requires `setuptools`, `wheel`. **No runtime dependency was added.** |
| Every third-party import | AST walk over all 19 tracked `*.py` files, comparing each top-level import against `sys.stdlib_module_names` | The complete non-stdlib, non-local import set is `{pytest}` (7 test files). Nothing else. |
| LLM / model-client class | `git ls-files -z \| xargs -0 grep -InE '<19-term alternation>'` covering clients, SDKs, local runtimes, tokenizers, cloud model endpoints, and `gpt-N`/`claude-*` model-id shapes | **Zero hits** in `src/`, `tests/`, `docs/`, or `tools/`. Hits exist only in `playbooks/*.yaml` (Agent-Orch crew model selection, not product code), `research/` and `architecture.md` (prose), and `code-reviews/` (this scan's own vocabulary). |
| Network / execution capability | `grep -rInE 'socket\|urllib\|http\.client\|subprocess\|os\.system\|popen\|eval(\|exec('` over `src/` | One hit: `connectors/local_files.py:556` runs `git check-ignore -z --stdin` with a fixed argv and piped stdin (Sprint 1/2 code; no shell, no user-controlled binary). No network capability anywhere in `src/`. |
| Absolute host paths | `git ls-files -z \| xargs -0 grep -InE '(/home/[a-z]\|/Users/[A-Za-z]\|C:\\Users\|/root/\|/var/folders/\|/private/var/)'` | One hit outside `code-reviews/`: `tests/test_contracts.py:62`, a synthetic `file:///home/lee/{synthetic-id}` fixture URI. **Zero** in any Sprint 3 delivered file. |
| Credential shapes | `git ls-files -z \| xargs -0 grep -InE '(api[_-]?key\|secret[_-]?key\|access[_-]?token\|bearer \|password\|client[_-]?secret\|private[_-]?key\|BEGIN … PRIVATE KEY\|AKIA[0-9A-Z]{16}\|sk-…\|ghp_…\|xox[baprs]-\|eyJ….)'` | Three hits, all the connector's own secret **tripwire** and its test: `research/employee-zero-kb-reference.md:44` (the rule), `connectors/local_files.py:158` (the pattern docstring), `tests/test_local_connector.py:711,713` (assertions exercising it). No credential value anywhere. |
| Private corpus content | `grep -IlE 'ai-employee-factory\|ai-employee-book\|employee-zero\|Employee Zero\|tviq\|knowledge/sources\.toml'` over all tracked files; plus `git ls-files \| grep -E '\.sqlite\|\.db$\|\.lee-kb\|\.env'` | 24 files reference the corpus by **name** (project memory, architecture, prior reviews) — root names and counts, no document content. No `.sqlite`, `.db`, `.lee-kb`, or `.env` artefact is tracked. `research/cerebras.kb` is a research prose document, not a projection. |
| Sprint 3 delivered files, all classes at once | combined `grep -InE` over the 15 delivered/modified Sprint 3 files | No host path, no credential shape, no third-party e-mail. The only address is the published owner identity `lee@leebase.com` (the documented default principal and config contract, `main.py:58`), plus `@example.com` placeholders in tests. **No leak found; nothing rises to a High disclosure finding.** |

### Review lenses and their outcome

| Lens | Outcome |
|------|---------|
| Governed surface exclusivity (S1-R-01) | Clean — probe 1 (call-sequence identity with `retrieve()`, no answer-module repository access, no fallback path). |
| Authorization and fail-closed behavior | Clean — probe 5a/5b. |
| Provenance, citations, and receipts | Clean — probe 4d (0 unresolved citations, exact receipt coverage) and probe 5c/5d. |
| Absence states | S3-R-02. The three states are distinguishable and asserted non-collapsing (probe 2a–2d); the evidenced-absence short-circuit defeats correct answers. |
| Conflict handling | S3-R-01, S3-R-03. Correct for the benchmark shape (3a); broken for same-authority contradiction and three-source topics. |
| Confidence model | Clean — proven derived, not asserted (probe 4a–4c). |
| Benchmark reproducibility | S3-R-06, S3-R-07. Examples and the conflict example reproduce; the confidence distribution does not; the recommendation value is valid. |
| Dependency and LLM boundary | Clean — no runtime dependency added, no LLM client anywhere (repository-wide). |
| Disclosure and secrets | Clean — repository-wide scan across path, credential, corpus-content, and artefact classes found no leak. |
| Sprint 1 and 2 invariants | Clean — all six re-verified by probe 5 under the new surface. |
| Tests and documentation | S3-R-05, S3-R-08, S3-R-09, plus the fixture gaps in Test Additions Recommended. |

### Verdict

**fail** — three High findings. All three are correctness defects in the
sprint's headline surface that a green 12/12 benchmark run and a green 235-test
suite do not catch, and each produces a confidently-labelled wrong answer: a
single claim asserting both "enabled" and "disabled" (S3-R-01, reproduced
through `lee-kb ask`), a responsive answer replaced by an unrelated
absence-shaped sentence (S3-R-02, shown as a control/treatment A/B), and a
resurrected merged claim double-citing two chunks (S3-R-03).

The governance skeleton this sprint builds on is sound and survived every attack
I made on it. The defects sit in claim assembly, absence short-circuiting, and
conflict reconciliation — each bounded, each with a concrete proposed fix and a
named regression fixture. Recommendation: **Ready after specific follow-up**,
gated on S3-R-01, S3-R-02, and S3-R-03 landing with their fixtures. The slice
should not be released to a reader as it stands.

*Reviewed 2026-08-04. `tools/validate_verdict.py` was run against the
accompanying verdict before this review was finished.*
