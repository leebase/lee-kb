"""The governed ``answer()`` surface: claim assembly and deterministic synthesis.

``answer()`` is a thin, deterministic composition layered strictly on top of
:func:`lee_kb.governance.retrieve`. It calls that function and nothing else to
reach evidence -- never :mod:`lee_kb.retrieval` and never a
:class:`~lee_kb.repository.Repository` method directly -- so authorization,
receipt persistence, and project scoping are inherited rather than
reimplemented. A missing principal, a permission denial, project scoping, and
freshness evaluation all happen inside ``retrieve()``; this module cannot
widen or bypass any of them.

Pipeline, following ``docs/answer-architecture.md``:

    question -> plan (pass-through) -> retrieve() -> [EvidenceBundle]
             -> evidence selection -> absence classification
             -> claim assembly -> conflict detection -> confidence assignment
             -> optional narration -> Answer

Claim assembly never concatenates retrieved chunks into one blob. Each
selected piece of evidence is assigned to exactly one :class:`Claim`: evidence
from two different sources that says the same thing is merged into one
``SYNTHESIZED`` claim citing both; everything else stands as its own
``DIRECTLY_EVIDENCED`` claim. Conflict detection (:mod:`lee_kb.answer_conflict`)
then reconstitutes any merge that turns out to hide a real disagreement,
so two sources that disagree are always presented as two separate, cited
claims rather than one claim asserting both.

Design rules, unchanged from ``answer_contracts.py``:

- Standard library only. No runtime dependencies.
- ``answer()`` never imports :mod:`lee_kb.repository` or
  :mod:`lee_kb.retrieval` at runtime, only :func:`lee_kb.governance.retrieve`.

Synthesis seam: :class:`DeterministicSynthesisProvider` is the default
:class:`~lee_kb.answer_contracts.SynthesisProvider`. It is a template
renderer over already-assembled claims -- offline, LLM-free, and standard
library only. An LLM-backed provider is specified in
``docs/answer-architecture.md`` as the same protocol's other implementation,
but it is deliberately **not implemented here**: it requires a runtime
dependency (a model client) that has not been approved per
``AGENTS.md``'s "Add external runtime dependencies" guardrail. Adding it
later means writing one class with a ``narrate()`` method and registering it
via ``synthesis_provider=``; nothing in this module changes.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .answer_absence import AbsenceAssessment, AbsenceBasis, classify_absence
from .answer_conflict import (
    _meaningful_term_similarity,
    _statements_mergeable,
    detect_conflicts,
    retain_conflict_sides,
)
from .answer_contracts import (
    Absence,
    AbsenceKind,
    Answer,
    Claim,
    Confidence,
    Conflict,
    EvidenceRef,
    OmissionReason,
    OmittedEvidence,
    ReceiptId,
    SynthesisProvider,
    weakest_confidence,
)
from .answer_evidence import (
    DEFAULT_MAX_CHUNKS_PER_SOURCE,
    DEFAULT_RELEVANCE_THRESHOLD,
    EvidenceSelection,
    select_evidence,
)
from .contracts import (
    Citation,
    Evidence,
    EvidenceBundle,
    FreshnessRequirement,
    MetadataFilters,
    Principal,
)
from .governance import (
    MissingPrincipalError,
    PermissionEvaluator,
    RetrievalProviderError,
    retrieve,
)

if TYPE_CHECKING:
    from .repository import Repository

__all__ = [
    "DEFAULT_SYNTHESIS_SIMILARITY_THRESHOLD",
    "DEFAULT_SYNTHESIS_PROVIDER",
    "DeterministicSynthesisProvider",
    "MissingPrincipalError",
    "answer",
]

#: How similar two evidence texts (Jaccard over meaningful terms) must be
#: before claim assembly treats them as the same underlying statement from
#: two sources and merges them into one SYNTHESIZED claim.
DEFAULT_SYNTHESIS_SIMILARITY_THRESHOLD = 0.5

_TOKEN_PATTERN = re.compile(r"\w+(?:['’]\w+)?(?:-\w+)*", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


class DeterministicSynthesisProvider:
    """The default :class:`SynthesisProvider`: template rendering, no model call.

    ``narrate()`` only rephrases claims that assembly has already finalized --
    it cannot add a claim, drop a citation, resolve a conflict, or change a
    confidence label, because none of those are reachable from its one
    argument. Deterministic in its input's order: claim ``[N]`` in the output
    always corresponds to ``claims[N - 1]``.
    """

    provider_id = "lee_kb.answer.DeterministicSynthesisProvider"

    def narrate(self, claims: tuple[Claim, ...]) -> str:
        lines = []
        for index, claim in enumerate(claims, start=1):
            sources = ", ".join(
                _citation_label(citation) for citation in claim.citations
            )
            sources = sources or "no citation"
            lines.append(
                f"[{index}] {claim.text.strip()} "
                f"(confidence: {claim.confidence.value}; source: {sources})"
            )
        return "\n".join(lines)


DEFAULT_SYNTHESIS_PROVIDER = DeterministicSynthesisProvider()

#: Sentinel distinguishing "use the default provider" from an explicit
#: ``synthesis_provider=None`` (narration disabled, claims-only answer).
_UNSET = object()


def answer(
    repository: "Repository",
    question: str,
    *,
    principal: Principal | None = None,
    project: str,
    top_k: int = 10,
    filters: MetadataFilters | None = None,
    freshness: FreshnessRequirement | None = None,
    include_tombstoned: bool = False,
    permission_evaluator: PermissionEvaluator | None = None,
    clock: Callable[[], datetime] | None = None,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    max_chunks_per_source: int = DEFAULT_MAX_CHUNKS_PER_SOURCE,
    synthesis_similarity_threshold: float = DEFAULT_SYNTHESIS_SIMILARITY_THRESHOLD,
    project_has_synchronized_content: bool = True,
    corpus_fresh: bool | None = None,
    resolution_failed: bool = False,
    allow_provider_failure: bool = False,
    synthesis_provider: SynthesisProvider | None = _UNSET,  # type: ignore[assignment]
) -> Answer:
    """Answer ``question`` for ``principal`` over evidence from governed retrieval.

    The only path to evidence is :func:`lee_kb.governance.retrieve`, called
    with these arguments unchanged (v1 planning is a pass-through: the
    question becomes the query). A missing or invalid ``principal`` raises
    :class:`MissingPrincipalError` there, before this module does anything
    else -- ``answer()`` adds no permission logic and cannot widen scope.

    ``project_has_synchronized_content``, ``corpus_fresh``, and
    ``resolution_failed`` carry context :func:`~lee_kb.governance.retrieve`
    cannot infer from an empty bundle alone; they are forwarded to
    :func:`~lee_kb.answer_absence.classify_absence` unchanged.

    ``synthesis_provider`` defaults to :data:`DEFAULT_SYNTHESIS_PROVIDER`.
    Pass ``None`` explicitly to receive claims and citations with no prose.
    ``allow_provider_failure=True`` is an explicit surface-level choice to
    return ``UNKNOWN`` when the retrieval provider fails; it never retries via
    another provider or fabricates evidence.
    """
    try:
        bundle = retrieve(
            repository,
            question,
            principal=principal,
            project=project,
            top_k=top_k,
            filters=filters,
            freshness=freshness,
            include_tombstoned=include_tombstoned,
            permission_evaluator=permission_evaluator,
            clock=clock,
        )
    except RetrievalProviderError:
        if not allow_provider_failure:
            raise
        return _assemble_resolution_failure(
            question,
            principal=principal,
            project=project,
            clock=clock,
        )

    provider = (
        DEFAULT_SYNTHESIS_PROVIDER
        if synthesis_provider is _UNSET
        else synthesis_provider
    )

    selection = select_evidence(
        bundle,
        relevance_threshold=relevance_threshold,
        max_chunks_per_source=max_chunks_per_source,
    )
    assessment = classify_absence(
        bundle,
        selected_evidence=selection.selected,
        relevance_threshold=relevance_threshold,
        project_has_synchronized_content=project_has_synchronized_content,
        corpus_fresh=corpus_fresh,
        resolution_failed=resolution_failed,
    )

    if assessment is not None and not assessment.is_evidenced:
        return _assemble_absence(bundle, assessment)

    if not selection.selected:
        # select_evidence may legitimately filter every candidate (all below
        # the relevance threshold, or otherwise out of scope) even though the
        # governed bundle itself was non-empty. No claim can be grounded, so
        # this is an absence -- not an empty claims list with nothing to say
        # why, which Answer's construction-time invariants forbid outright.
        return _assemble_no_grounded_evidence(bundle, selection)

    return _assemble_evidenced_answer(
        bundle,
        selection,
        synthesis_similarity_threshold=synthesis_similarity_threshold,
        evidenced_absence_claim=(
            assessment.supporting_claim if assessment is not None else None
        ),
        provider=provider,
    )


def _assemble_resolution_failure(
    question: str,
    *,
    principal: Principal | None,
    project: str,
    clock: Callable[[], datetime] | None,
) -> Answer:
    """Return an honest UNKNOWN answer without fabricating an empty search."""
    if not isinstance(principal, Principal):
        raise MissingPrincipalError(
            "answer() requires a principal; anonymous requests are rejected"
        )
    answered_at = (clock or (lambda: datetime.now(timezone.utc)))()
    return Answer(
        question=question,
        principal=principal,
        project=project,
        claims=(),
        confidence=Confidence.UNKNOWN,
        receipt_ids=(),
        evidence_used=(),
        evidence_omitted=(),
        conflicts=(),
        absence=Absence(
            kind=AbsenceKind.UNKNOWN,
            question=question,
            detail="The question could not be resolved by the retrieval provider.",
            searched_projects=(project,),
        ),
        answered_at=answered_at,
    )


def _assemble_absence(bundle: EvidenceBundle, assessment: AbsenceAssessment) -> Answer:
    reason = (
        OmissionReason.STALE
        if assessment.basis is AbsenceBasis.UNRESOLVED
        and not bundle.freshness.requirement_satisfied
        else OmissionReason.NOT_RELEVANT
    )
    evidence_omitted = tuple(
        OmittedEvidence(
            evidence=EvidenceRef(
                chunk_id=item.chunk_id, source_locator=item.citation.source_locator
            ),
            reason=reason,
            detail=assessment.absence.detail,
        )
        for item in bundle.evidence
    )
    return Answer(
        question=bundle.request.query,
        principal=bundle.request.principal,
        project=bundle.request.project,
        claims=(),
        confidence=Confidence.UNKNOWN,
        receipt_ids=tuple(
            ReceiptId.from_receipt(receipt) for receipt in bundle.receipts
        ),
        evidence_used=(),
        evidence_omitted=evidence_omitted,
        conflicts=(),
        absence=assessment.absence,
        answered_at=bundle.retrieval_timestamp,
        withheld_count=bundle.denied_count,
        truncated=bundle.truncated,
    )


def _assemble_no_grounded_evidence(
    bundle: EvidenceBundle, selection: EvidenceSelection
) -> Answer:
    absence = Absence(
        kind=AbsenceKind.UNKNOWN,
        question=bundle.request.query,
        detail=(
            "Retrieved evidence did not clear the relevance threshold for "
            "claim assembly."
        ),
        searched_projects=bundle.request.effective_projects,
    )
    return Answer(
        question=bundle.request.query,
        principal=bundle.request.principal,
        project=bundle.request.project,
        claims=(),
        confidence=Confidence.UNKNOWN,
        receipt_ids=selection.receipt_ids,
        evidence_used=(),
        evidence_omitted=selection.answer_omissions,
        conflicts=(),
        absence=absence,
        answered_at=bundle.retrieval_timestamp,
        withheld_count=bundle.denied_count,
        truncated=bundle.truncated,
    )


def _assemble_evidenced_answer(
    bundle: EvidenceBundle,
    selection: EvidenceSelection,
    *,
    synthesis_similarity_threshold: float,
    evidenced_absence_claim: Claim | None,
    provider: SynthesisProvider | None,
) -> Answer:
    absence_chunk_ids = (
        frozenset(evidenced_absence_claim.cited_chunk_ids)
        if evidenced_absence_claim is not None
        else frozenset()
    )
    ordinary_evidence = tuple(
        evidence
        for evidence in selection.selected
        if evidence.chunk_id not in absence_chunk_ids
    )
    initial_claims = _assemble_initial_claims(
        ordinary_evidence, synthesis_similarity_threshold
    )
    if evidenced_absence_claim is not None:
        initial_claims = _rank_claims(
            initial_claims + (evidenced_absence_claim,), selection.selected
        )
    conflicts = detect_conflicts(selection, claims=initial_claims)
    final_claims = _reconcile_with_conflicts(initial_claims, conflicts)

    overall_confidence = weakest_confidence(
        tuple(claim.confidence for claim in final_claims)
    )
    evidence_used = tuple(
        EvidenceRef(chunk_id=item.chunk_id, source_locator=item.citation.source_locator)
        for item in selection.selected
    )
    prose, synthesis_provider_id = _narrate(provider, final_claims)

    return Answer(
        question=bundle.request.query,
        principal=bundle.request.principal,
        project=bundle.request.project,
        claims=final_claims,
        confidence=overall_confidence,
        receipt_ids=selection.receipt_ids,
        evidence_used=evidence_used,
        evidence_omitted=selection.answer_omissions,
        conflicts=conflicts,
        absence=None,
        answered_at=bundle.retrieval_timestamp,
        prose=prose,
        synthesis_provider_id=synthesis_provider_id,
        withheld_count=bundle.denied_count,
        truncated=bundle.truncated,
    )


def _narrate(
    provider: SynthesisProvider | None, claims: tuple[Claim, ...]
) -> tuple[str | None, str | None]:
    if provider is None:
        return None, None
    return provider.narrate(claims), _provider_id(provider)


def _provider_id(provider: SynthesisProvider) -> str:
    provider_id = getattr(provider, "provider_id", None)
    if isinstance(provider_id, str) and provider_id.strip():
        return provider_id
    return f"{type(provider).__module__}.{type(provider).__qualname__}"


def _assemble_initial_claims(
    selected: tuple[Evidence, ...], similarity_threshold: float
) -> tuple[Claim, ...]:
    """Group selected evidence into one claim per distinct statement.

    Evidence from two different sources merges into one SYNTHESIZED claim only
    when its differing meaningful terms are empty after known-synonym
    normalization and its overlap clears ``similarity_threshold``. Everything
    else becomes its own DIRECTLY_EVIDENCED claim. Merges are strictly pairwise
    so conflict reconciliation can always swap a merged claim for exactly the
    two single-evidence claims it came from.
    """
    claimed: set = set()
    claims: list[Claim] = []
    for index, evidence in enumerate(selected):
        if evidence.chunk_id in claimed:
            continue
        partner = None
        best_score = 0.0
        for candidate in selected[index + 1 :]:
            if candidate.chunk_id in claimed:
                continue
            if candidate.item_id == evidence.item_id:
                continue
            if not _statements_mergeable(evidence.text, candidate.text):
                continue
            score = _similarity(evidence.text, candidate.text)
            if score >= similarity_threshold and score > best_score:
                best_score = score
                partner = candidate
        if partner is not None:
            claimed.add(evidence.chunk_id)
            claimed.add(partner.chunk_id)
            claims.append(_synthesized_claim(evidence, partner))
        else:
            claimed.add(evidence.chunk_id)
            claims.append(_direct_claim(evidence))
    return tuple(claims)


def _reconcile_with_conflicts(
    initial_claims: tuple[Claim, ...], conflicts: tuple[Conflict, ...]
) -> tuple[Claim, ...]:
    """Swap out any merged claim that conflict detection had to split.

    ``detect_conflicts`` reconstitutes two single-evidence claims whenever a
    merge in ``initial_claims`` hid a real disagreement. Any such
    reconstituted claim is new (not in ``initial_claims``); its citation
    displaces the merged claim that used to cover the same evidence, so the
    merged claim is dropped and :func:`retain_conflict_sides` appends both
    real sides in its place.
    """
    initial_set = set(initial_claims)
    reconstituted = tuple(
        claim
        for conflict in conflicts
        for claim in conflict.claims
        if claim not in initial_set
    )
    displaced_chunk_ids = {
        chunk_id for claim in reconstituted for chunk_id in claim.cited_chunk_ids
    }
    kept = tuple(
        claim
        for claim in initial_claims
        if not (set(claim.cited_chunk_ids) & displaced_chunk_ids)
    )
    return retain_conflict_sides(kept, conflicts)


def _rank_claims(
    claims: tuple[Claim, ...], selected: tuple[Evidence, ...]
) -> tuple[Claim, ...]:
    evidence_rank = {
        evidence.chunk_id: index for index, evidence in enumerate(selected)
    }
    return tuple(
        sorted(
            claims,
            key=lambda claim: min(
                evidence_rank[chunk_id] for chunk_id in claim.cited_chunk_ids
            ),
        )
    )


def _direct_claim(evidence: Evidence) -> Claim:
    return Claim(
        text=evidence.text.strip(),
        citations=(evidence.citation,),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )


def _synthesized_claim(first: Evidence, second: Evidence) -> Claim:
    first_text = first.text.strip()
    second_text = second.text.strip()
    if _normalized_tokens(first_text) == _normalized_tokens(second_text):
        text = first_text
    else:
        text = f"{first_text} {second_text}"
    return Claim(
        text=text,
        citations=(first.citation, second.citation),
        confidence=Confidence.SYNTHESIZED,
    )


def _citation_label(citation: Citation) -> str:
    return (
        citation.title or citation.source_locator.label or citation.source_locator.uri
    )


def _normalized_tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_PATTERN.findall(text))


def _similarity(left: str, right: str) -> float:
    return _meaningful_term_similarity(left, right)
