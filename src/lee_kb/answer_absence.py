"""Classify governed retrieval outcomes without collapsing absence states.

The classifier consumes an :class:`~lee_kb.contracts.EvidenceBundle`, so it
can only reason over evidence already released by permission filtering.  It
never inspects provider candidates or restricted source metadata.

An explicit source statement that an artifact was never created is represented
as an evidenced ``NOT_FOUND`` assessment.  Its supporting statement remains a
directly evidenced :class:`~lee_kb.answer_contracts.Claim` with citations.  A
silent corpus miss remains ``UNKNOWN`` confidence even though the search itself
is authoritative: silence proves only that the governed search found nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .answer_contracts import Absence, AbsenceKind, Claim, Confidence
from .answer_evidence import (
    DEFAULT_RELEVANCE_THRESHOLD,
    _meaningful_terms,
    _relevance,
)
from .contracts import Citation, Evidence, EvidenceBundle

__all__ = [
    "AbsenceBasis",
    "AbsenceAssessment",
    "classify_absence",
]

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_EXPLICIT_ABSENCE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bnever (?:been )?created\b",
        r"\b(?:was|were|is|are|has|have) not (?:been )?created\b",
        r"\b(?:does|do) not exist\b",
        r"\b(?:doesn't|don't) exist\b",
        r"\bnot authoriz\w* (?:the )?creation\b",
        r"\bcreation (?:is|was|has been) not authoriz\w*\b",
        r"\bno\s+[^.!?\n]{1,100}\s+(?:was|were|has been|have been) created\b",
    )
)


class AbsenceBasis(str, Enum):
    """What observation supports an absence classification."""

    SILENCE = "silence"
    EVIDENCED = "evidenced"
    WITHHELD = "withheld"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class AbsenceAssessment:
    """One classified absence plus any governed supporting statement.

    ``supporting_claim`` is populated only for an ``EVIDENCED`` absence.  It
    deliberately uses the ordinary claim and citation contracts so later
    answer assembly cannot turn a cited negative fact into an uncited message.
    """

    absence: Absence
    basis: AbsenceBasis
    confidence: Confidence
    supporting_claim: Claim | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.absence, Absence):
            raise TypeError("absence must be an Absence")
        if not isinstance(self.basis, AbsenceBasis):
            raise TypeError("basis must be an AbsenceBasis")
        if not isinstance(self.confidence, Confidence):
            raise TypeError("confidence must be a Confidence")
        if self.supporting_claim is not None and not isinstance(
            self.supporting_claim, Claim
        ):
            raise TypeError("supporting_claim must be a Claim")

        evidenced = self.basis is AbsenceBasis.EVIDENCED
        if evidenced != (self.supporting_claim is not None):
            raise ValueError("only an EVIDENCED absence may carry a supporting claim")
        if evidenced:
            if self.absence.kind is not AbsenceKind.NOT_FOUND:
                raise ValueError("an evidenced absence must be NOT_FOUND")
            if self.confidence is not Confidence.DIRECTLY_EVIDENCED:
                raise ValueError("an evidenced absence must be DIRECTLY_EVIDENCED")
        elif self.confidence is not Confidence.UNKNOWN:
            raise ValueError("an absence without supporting evidence is UNKNOWN")

        expected_basis = {
            AbsenceKind.INACCESSIBLE: AbsenceBasis.WITHHELD,
            AbsenceKind.UNKNOWN: AbsenceBasis.UNRESOLVED,
        }.get(self.absence.kind)
        if expected_basis is not None and self.basis is not expected_basis:
            raise ValueError(
                f"{self.absence.kind.name} requires a {expected_basis.name} basis"
            )

    @property
    def kind(self) -> AbsenceKind:
        return self.absence.kind

    @property
    def is_evidenced(self) -> bool:
        return self.basis is AbsenceBasis.EVIDENCED

    @property
    def citations(self) -> tuple[Citation, ...]:
        if self.supporting_claim is None:
            return ()
        return self.supporting_claim.citations


def classify_absence(
    bundle: EvidenceBundle,
    *,
    selected_evidence: tuple[Evidence, ...] | None = None,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    project_has_synchronized_content: bool = True,
    corpus_fresh: bool | None = None,
    resolution_failed: bool = False,
) -> AbsenceAssessment | None:
    """Classify whether ``bundle`` represents one of the three absences.

    ``None`` means released evidence can answer the question and makes no
    explicit absence statement.  The caller supplies
    ``project_has_synchronized_content=False`` when project-level sync state is
    known to be empty; an empty retrieval alone cannot distinguish that state
    from a real corpus miss.  ``corpus_fresh`` can carry a broader corpus-level
    freshness decision when the empty bundle has no evidence timestamps.

    ``selected_evidence`` narrows explicit-absence detection to evidence that
    already passed the caller's allocation and relevance policy. The matched
    absence sentence must itself clear ``relevance_threshold``. Its governed
    rank does not change whether that cited statement is presented.

    Permission denial has first priority for an empty result.  Consequently a
    result with ``denied_count > 0`` can never be misreported as ``NOT_FOUND``.
    """
    if not isinstance(bundle, EvidenceBundle):
        raise TypeError("classify_absence requires a governed EvidenceBundle")
    if selected_evidence is not None:
        if not isinstance(selected_evidence, tuple):
            raise TypeError("selected_evidence must be a tuple")
        if not all(isinstance(item, Evidence) for item in selected_evidence):
            raise TypeError("selected_evidence must contain Evidence values")
        governed_ids = {item.chunk_id for item in bundle.evidence}
        if any(item.chunk_id not in governed_ids for item in selected_evidence):
            raise ValueError("selected_evidence must come from the governed bundle")
    if isinstance(relevance_threshold, bool) or not isinstance(
        relevance_threshold, (int, float)
    ):
        raise TypeError("relevance_threshold must be a number")
    if not 0 <= relevance_threshold <= 1:
        raise ValueError("relevance_threshold must be between 0 and 1")
    _require_bool(project_has_synchronized_content, "project_has_synchronized_content")
    if corpus_fresh is not None:
        _require_bool(corpus_fresh, "corpus_fresh")
    _require_bool(resolution_failed, "resolution_failed")

    question = bundle.request.query
    searched_projects = tuple(bundle.request.effective_projects)

    if not bundle.evidence and bundle.denied_count > 0:
        return AbsenceAssessment(
            absence=Absence(
                kind=AbsenceKind.INACCESSIBLE,
                question=question,
                detail="Matching material was withheld by permission filtering.",
                withheld_count=bundle.denied_count,
            ),
            basis=AbsenceBasis.WITHHELD,
            confidence=Confidence.UNKNOWN,
        )

    if (
        resolution_failed
        or not project_has_synchronized_content
        or corpus_fresh is False
        or not bundle.freshness.requirement_satisfied
    ):
        if resolution_failed:
            detail = "The question could not be resolved by the retrieval provider."
        elif not project_has_synchronized_content:
            detail = "The requested project has no synchronized content."
        else:
            detail = "The corpus does not satisfy the requested freshness."
        return AbsenceAssessment(
            absence=Absence(
                kind=AbsenceKind.UNKNOWN,
                question=question,
                detail=detail,
                searched_projects=searched_projects,
            ),
            basis=AbsenceBasis.UNRESOLVED,
            confidence=Confidence.UNKNOWN,
        )

    supporting = _explicit_absence_evidence(
        bundle,
        bundle.evidence if selected_evidence is None else selected_evidence,
        relevance_threshold,
    )
    if supporting:
        claim = Claim(
            text=" ".join(statement for _, statement in supporting),
            citations=tuple(evidence.citation for evidence, _ in supporting),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        )
        return AbsenceAssessment(
            absence=Absence(
                kind=AbsenceKind.NOT_FOUND,
                question=question,
                detail="The corpus explicitly states that the requested artifact "
                "was not created.",
                searched_projects=searched_projects,
            ),
            basis=AbsenceBasis.EVIDENCED,
            confidence=Confidence.DIRECTLY_EVIDENCED,
            supporting_claim=claim,
        )

    if bundle.evidence:
        return None

    return AbsenceAssessment(
        absence=Absence(
            kind=AbsenceKind.NOT_FOUND,
            question=question,
            detail="The governed corpus search returned no matching evidence.",
            searched_projects=searched_projects,
        ),
        basis=AbsenceBasis.SILENCE,
        confidence=Confidence.UNKNOWN,
    )


def _explicit_absence_evidence(
    bundle: EvidenceBundle,
    selected_evidence: tuple[Evidence, ...],
    relevance_threshold: float,
) -> tuple[tuple[Evidence, str], ...]:
    question_terms = _meaningful_terms(bundle.request.query)
    matches: list[tuple[Evidence, str]] = []
    for evidence in selected_evidence:
        for raw_sentence in _SENTENCE_BOUNDARY.split(evidence.text):
            sentence = raw_sentence.strip()
            if not sentence:
                continue
            if not any(
                pattern.search(sentence) for pattern in _EXPLICIT_ABSENCE_PATTERNS
            ):
                continue
            if _relevance(sentence, question_terms) < relevance_threshold:
                continue
            matches.append((evidence, sentence))
            break
    return tuple(matches)


def _require_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")
