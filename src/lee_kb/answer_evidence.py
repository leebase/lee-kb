"""Deterministic evidence selection over governed retrieval results.

This module is deliberately downstream of :func:`lee_kb.governance.retrieve`.
It accepts an :class:`~lee_kb.contracts.EvidenceBundle` -- never a repository,
retriever, or iterable of provider hits -- so every candidate it can inspect
has already passed permission filtering and has a persisted retrieval receipt.

Selection keeps the original :class:`~lee_kb.contracts.Evidence` values.  That
preserves the complete, independently useful provenance carried by retrieval:
knowledge-item and chunk identity, content hash, source locator, declared
authority and trust, and source and synchronization timestamps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .answer_contracts import (
    EvidenceRef,
    OmissionReason,
    OmittedEvidence,
    ReceiptId,
)
from .contracts import Evidence, EvidenceBundle

__all__ = [
    "DEFAULT_RELEVANCE_THRESHOLD",
    "DEFAULT_MAX_CHUNKS_PER_SOURCE",
    "SelectionOmissionReason",
    "EvidenceOmission",
    "EvidenceSelection",
    "select_evidence",
]

DEFAULT_RELEVANCE_THRESHOLD = 0.25
DEFAULT_MAX_CHUNKS_PER_SOURCE = 1

_TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)
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
        "do",
        "does",
        "for",
        "from",
        "how",
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
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


class SelectionOmissionReason(str, Enum):
    """The exhaustive reasons the mechanical selector may omit evidence."""

    BELOW_RELEVANCE_THRESHOLD = "below_relevance_threshold"
    REDUNDANT_SAME_SOURCE = "redundant_same_source"
    OUTSIDE_REQUESTED_PROJECT = "outside_requested_project"


@dataclass(frozen=True, slots=True)
class EvidenceOmission:
    """One permitted, receipted evidence item deliberately not selected.

    The whole evidence value is retained instead of only its reference.  This
    makes omission review possible without re-querying and guarantees that the
    selected and omitted sides together account for the exact governed bundle.
    """

    evidence: Evidence
    reason: SelectionOmissionReason
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, Evidence):
            raise TypeError("evidence must be an Evidence")
        if not isinstance(self.reason, SelectionOmissionReason):
            raise TypeError("reason must be a SelectionOmissionReason")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("detail must be a non-empty string")

    @property
    def chunk_id(self):
        return self.evidence.chunk_id

    def as_answer_omission(self) -> OmittedEvidence:
        """Return the lightweight omission view used by :class:`Answer`.

        The answer contract's broader ``NOT_RELEVANT`` category covers both a
        threshold rejection and the defensive project-scope rejection.  The
        precise selection reason remains present in ``detail``.
        """
        reason = (
            OmissionReason.REDUNDANT
            if self.reason is SelectionOmissionReason.REDUNDANT_SAME_SOURCE
            else OmissionReason.NOT_RELEVANT
        )
        return OmittedEvidence(
            evidence=EvidenceRef(
                chunk_id=self.evidence.chunk_id,
                source_locator=self.evidence.citation.source_locator,
            ),
            reason=reason,
            detail=self.detail,
        )


@dataclass(frozen=True, slots=True)
class EvidenceSelection:
    """A complete accounting of one governed evidence bundle."""

    evidence_used: tuple[Evidence, ...]
    evidence_omitted: tuple[EvidenceOmission, ...]
    receipt_ids: tuple[ReceiptId, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_used, tuple):
            raise TypeError("evidence_used must be a tuple")
        if not isinstance(self.evidence_omitted, tuple):
            raise TypeError("evidence_omitted must be a tuple")
        if not isinstance(self.receipt_ids, tuple):
            raise TypeError("receipt_ids must be a tuple")
        if not all(isinstance(item, Evidence) for item in self.evidence_used):
            raise TypeError("evidence_used must contain Evidence values")
        if not all(
            isinstance(item, EvidenceOmission) for item in self.evidence_omitted
        ):
            raise TypeError("evidence_omitted must contain EvidenceOmission values")

        used_ids = tuple(item.chunk_id for item in self.evidence_used)
        omitted_ids = tuple(item.chunk_id for item in self.evidence_omitted)
        considered = used_ids + omitted_ids
        if len(set(considered)) != len(considered):
            raise ValueError("evidence must be accounted for exactly once")
        if {receipt.chunk_id for receipt in self.receipt_ids} != set(considered):
            raise ValueError("receipt_ids must cover all selected and omitted evidence")

    @property
    def selected(self) -> tuple[Evidence, ...]:
        """Alias for the evidence retained for claim assembly."""
        return self.evidence_used

    @property
    def used(self) -> tuple[Evidence, ...]:
        """Short alias for callers that treat selection as a partition."""
        return self.evidence_used

    @property
    def omitted(self) -> tuple[EvidenceOmission, ...]:
        return self.evidence_omitted

    @property
    def answer_omissions(self) -> tuple[OmittedEvidence, ...]:
        """Omission references ready for the public :class:`Answer`."""
        return tuple(item.as_answer_omission() for item in self.evidence_omitted)


def select_evidence(
    bundle: EvidenceBundle,
    *,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    max_chunks_per_source: int = DEFAULT_MAX_CHUNKS_PER_SOURCE,
) -> EvidenceSelection:
    """Select the smallest useful, source-diverse subset of ``bundle``.

    Relevance is the fraction of meaningful question terms present in a
    chunk.  Evidence is considered in the bundle's governed fused-rank order;
    the first chunks from a source therefore always win its deterministic
    per-source allocation.  Every rejected item is retained with one explicit
    reason, so this function never silently drops evidence.
    """
    if not isinstance(bundle, EvidenceBundle):
        raise TypeError(
            "select_evidence requires an EvidenceBundle returned by governed "
            "retrieve()"
        )
    _validate_options(relevance_threshold, max_chunks_per_source)

    query_terms = _meaningful_terms(bundle.request.query)
    effective_projects = frozenset(bundle.request.effective_projects)
    source_counts: dict[object, int] = {}
    used: list[Evidence] = []
    omitted: list[EvidenceOmission] = []

    for evidence in bundle.evidence:
        if evidence.project not in effective_projects:
            omitted.append(
                EvidenceOmission(
                    evidence=evidence,
                    reason=SelectionOmissionReason.OUTSIDE_REQUESTED_PROJECT,
                    detail=(
                        f"project {evidence.project!r} is outside requested "
                        f"scope {tuple(bundle.request.effective_projects)!r}"
                    ),
                )
            )
            continue

        relevance = _relevance(evidence.text, query_terms)
        if relevance < relevance_threshold:
            omitted.append(
                EvidenceOmission(
                    evidence=evidence,
                    reason=SelectionOmissionReason.BELOW_RELEVANCE_THRESHOLD,
                    detail=(
                        f"query-term coverage {relevance:.3f} is below "
                        f"threshold {relevance_threshold:.3f}"
                    ),
                )
            )
            continue

        source_id = evidence.item_id
        if source_counts.get(source_id, 0) >= max_chunks_per_source:
            omitted.append(
                EvidenceOmission(
                    evidence=evidence,
                    reason=SelectionOmissionReason.REDUNDANT_SAME_SOURCE,
                    detail=(
                        "higher-ranked evidence from the same knowledge item "
                        "already supplies that source's allocation"
                    ),
                )
            )
            continue

        used.append(evidence)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1

    return EvidenceSelection(
        evidence_used=tuple(used),
        evidence_omitted=tuple(omitted),
        receipt_ids=tuple(ReceiptId.from_receipt(item) for item in bundle.receipts),
    )


def _validate_options(relevance_threshold: float, max_chunks_per_source: int) -> None:
    if isinstance(relevance_threshold, bool) or not isinstance(
        relevance_threshold, (int, float)
    ):
        raise TypeError("relevance_threshold must be a number")
    if not 0 <= relevance_threshold <= 1:
        raise ValueError("relevance_threshold must be between 0 and 1")
    if not isinstance(max_chunks_per_source, int) or isinstance(
        max_chunks_per_source, bool
    ):
        raise TypeError("max_chunks_per_source must be an int")
    if max_chunks_per_source < 1:
        raise ValueError("max_chunks_per_source must be at least 1")


def _meaningful_terms(text: str) -> frozenset[str]:
    tokens = tuple(token.casefold() for token in _TOKEN_PATTERN.findall(text))
    meaningful = frozenset(token for token in tokens if token not in _STOP_WORDS)
    return meaningful or frozenset(tokens)


def _relevance(text: str, query_terms: frozenset[str]) -> float:
    if not query_terms:
        return 0.0
    evidence_terms = _meaningful_terms(text)
    return len(query_terms & evidence_terms) / len(query_terms)
