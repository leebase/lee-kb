"""Deterministic conflict identification over selected governed evidence.

Conflict detection orders competing statements by recency and declared
authority, but never resolves them.  Every emitted
:class:`~lee_kb.answer_contracts.Conflict` retains both claims and both sets of
citations; :func:`retain_conflict_sides` is the assembly helper that makes the
same invariant explicit when claims are combined downstream.
"""

from __future__ import annotations

import re
from decimal import Decimal
from itertools import combinations

from .answer_contracts import Claim, Confidence, Conflict, ConflictSide
from .answer_evidence import EvidenceSelection
from .contracts import Evidence

__all__ = [
    "detect_conflicts",
    "identify_conflicts",
    "retain_conflict_sides",
]

_TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)
_NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:,\d{3})*(?:\.\d+)?(?!\w)")
_SUPERSESSION_PATTERN = re.compile(
    r"\b(?:supersed\w*|replac\w*|no longer|instead of|revis(?:e|ed|ion))\b",
    re.IGNORECASE,
)
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
_VALUE_WORDS = frozenset(
    {
        "active",
        "approved",
        "blocked",
        "closed",
        "created",
        "denied",
        "disabled",
        "enabled",
        "inactive",
        "never",
        "not",
        "open",
        "optional",
        "required",
    }
)
_KNOWN_SYNONYM_SETS = (
    frozenset({"mandate", "mandated", "mandates", "require", "required", "requires"}),
    frozenset({"retain", "retained", "retaining", "retains", "retention"}),
)
_SYNONYM_CANONICAL = {
    term: min(synonyms) for synonyms in _KNOWN_SYNONYM_SETS for term in synonyms
}
_STRUCTURAL_DIVERGENCE_THRESHOLD = 0.5


def detect_conflicts(
    selection: EvidenceSelection,
    claims: tuple[Claim, ...] | None = None,
) -> tuple[Conflict, ...]:
    """Return pairwise conflicts present in selected governed evidence.

    When assembled ``claims`` are supplied, each evidence item is mapped to the
    claim citing it.  Without them, one directly evidenced claim is constructed
    per selected item.  The latter is useful before the full answer assembler
    exists and preserves the same citations and ordering.

    Two same-topic statements conflict when their text differs and their
    numbers, meaningful terms, or known value words diverge; their declared
    authority differs; or the newer statement explicitly says it
    supersedes/replaces earlier material. These are detection signals only;
    the returned ``Conflict`` contract has no winner.
    """
    if not isinstance(selection, EvidenceSelection):
        raise TypeError("detect_conflicts requires an EvidenceSelection")
    if claims is not None:
        if not isinstance(claims, tuple):
            raise TypeError("claims must be a tuple")
        if not all(isinstance(claim, Claim) for claim in claims):
            raise TypeError("claims must contain Claim values")

    evidence_claims = {
        evidence.chunk_id: _claim_for_evidence(evidence, claims)
        for evidence in selection.selected
    }
    detected: list[tuple[Evidence, Evidence, str]] = []

    for left_evidence, right_evidence in combinations(selection.selected, 2):
        signal = _conflict_signal(left_evidence, right_evidence)
        if signal is None:
            continue
        left_claim = evidence_claims[left_evidence.chunk_id]
        right_claim = evidence_claims[right_evidence.chunk_id]
        # A claim participating in a conflict cannot stay merged, even when
        # its citations agree with one another: each governed source remains a
        # separately inspectable side once that assertion is disputed. Update
        # the map immediately so later pairs resolve transitively to the
        # single-evidence claims rather than resurrecting either merge.
        merged_claims = {
            claim for claim in (left_claim, right_claim) if len(claim.citations) > 1
        }
        for merged_claim in merged_claims:
            for evidence in selection.selected:
                if evidence_claims[evidence.chunk_id] == merged_claim:
                    evidence_claims[evidence.chunk_id] = _direct_claim(evidence)
        detected.append((left_evidence, right_evidence, signal))

    # Resolve all detected pairs through the final map. This also re-keys a
    # pair detected before its merged side was split onto the reconstituted
    # single-evidence claim for the evidence that actually formed that side.
    found: list[Conflict] = []
    seen_claim_pairs: set[frozenset[Claim]] = set()
    for left_evidence, right_evidence, signal in detected:
        left_claim = evidence_claims[left_evidence.chunk_id]
        right_claim = evidence_claims[right_evidence.chunk_id]
        pair = frozenset((left_claim, right_claim))
        if pair in seen_claim_pairs:
            continue
        seen_claim_pairs.add(pair)
        found.append(
            Conflict(
                left=ConflictSide(
                    claim=left_claim,
                    source_timestamp=left_evidence.source_timestamp,
                    authority=left_evidence.citation.authority,
                ),
                right=ConflictSide(
                    claim=right_claim,
                    source_timestamp=right_evidence.source_timestamp,
                    authority=right_evidence.citation.authority,
                ),
                detail=signal,
            )
        )
    return tuple(found)


# The architecture and mission use both verbs.  Keep one implementation.
identify_conflicts = detect_conflicts


def retain_conflict_sides(
    claims: tuple[Claim, ...], conflicts: tuple[Conflict, ...]
) -> tuple[Claim, ...]:
    """Return ``claims`` with every conflict side retained exactly once.

    Existing claim order is preserved.  Missing left and right sides are
    appended in conflict order, making it impossible for assembly to keep the
    preferred-looking side while silently losing its competitor.
    """
    if not isinstance(claims, tuple):
        raise TypeError("claims must be a tuple")
    if not isinstance(conflicts, tuple):
        raise TypeError("conflicts must be a tuple")
    if not all(isinstance(claim, Claim) for claim in claims):
        raise TypeError("claims must contain Claim values")
    if not all(isinstance(conflict, Conflict) for conflict in conflicts):
        raise TypeError("conflicts must contain Conflict values")

    retained = list(claims)
    for conflict in conflicts:
        for claim in conflict.claims:
            if claim not in retained:
                retained.append(claim)
    return tuple(retained)


def _claim_for_evidence(evidence: Evidence, claims: tuple[Claim, ...] | None) -> Claim:
    if claims is not None:
        matching = tuple(
            claim for claim in claims if evidence.chunk_id in claim.cited_chunk_ids
        )
        if len(matching) > 1:
            raise ValueError(
                "selected evidence may support at most one assembled claim"
            )
        if matching:
            return matching[0]
    return _direct_claim(evidence)


def _direct_claim(evidence: Evidence) -> Claim:
    return Claim(
        text=evidence.text.strip(),
        citations=(evidence.citation,),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )


def _conflict_signal(left: Evidence, right: Evidence) -> str | None:
    left_text = _normalized_text(left.text)
    right_text = _normalized_text(right.text)
    if left_text == right_text:
        return None

    shared_topic = _subject_terms(left.text) & _subject_terms(right.text)
    if not shared_topic:
        return None

    if _numbers_diverge(left.text, right.text):
        return (
            "Competing statements about "
            f"{', '.join(sorted(shared_topic))} use different numeric values."
        )

    if _value_words_diverge(left.text, right.text):
        return (
            "Competing statements about "
            f"{', '.join(sorted(shared_topic))} use divergent value words."
        )

    if left.citation.authority is not right.citation.authority:
        return (
            "Competing statements about "
            f"{', '.join(sorted(shared_topic))} have different declared authority."
        )

    if left.source_timestamp == right.source_timestamp:
        newer = None
    else:
        newer = left if left.source_timestamp > right.source_timestamp else right
    if newer is not None and _SUPERSESSION_PATTERN.search(newer.text):
        return (
            "A newer statement about "
            f"{', '.join(sorted(shared_topic))} explicitly supersedes older material."
        )

    if _meaningful_term_similarity(
        left.text, right.text
    ) >= _STRUCTURAL_DIVERGENCE_THRESHOLD and not _statements_mergeable(
        left.text, right.text
    ):
        return (
            "Competing statements about "
            f"{', '.join(sorted(shared_topic))} differ in meaningful terms."
        )
    return None


def _normalized_text(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_PATTERN.findall(text))


def _subject_terms(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _normalized_text(text)
        if token not in _STOP_WORDS
        and token not in _VALUE_WORDS
        and not _SUPERSESSION_PATTERN.fullmatch(token)
    )


def _value_words_diverge(left: str, right: str) -> bool:
    left_values = frozenset(_normalized_text(left)) & _VALUE_WORDS
    right_values = frozenset(_normalized_text(right)) & _VALUE_WORDS
    return bool(left_values and right_values and left_values != right_values)


def _numbers_diverge(left: str, right: str) -> bool:
    left_values = _numeric_values(left)
    right_values = _numeric_values(right)
    if not left_values or not right_values or left_values == right_values:
        return False

    left_subject = frozenset(
        term for term in _subject_terms(left) if not term.isdecimal()
    )
    right_subject = frozenset(
        term for term in _subject_terms(right) if not term.isdecimal()
    )
    if not left_subject or not right_subject:
        return False
    subject_similarity = len(left_subject & right_subject) / len(
        left_subject | right_subject
    )
    return subject_similarity >= _STRUCTURAL_DIVERGENCE_THRESHOLD


def _numeric_values(text: str) -> frozenset[Decimal]:
    return frozenset(
        Decimal(number.replace(",", "")) for number in _NUMBER_PATTERN.findall(text)
    )


def _statements_mergeable(left: str, right: str) -> bool:
    """Return whether differences are empty after known synonym normalization."""
    left_terms = _meaningful_terms(left)
    right_terms = _meaningful_terms(right)
    if left_terms == right_terms:
        return True
    return _canonical_terms(left_terms) == _canonical_terms(right_terms)


def _meaningful_term_similarity(left: str, right: str) -> float:
    left_terms = _meaningful_terms(left)
    right_terms = _meaningful_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _meaningful_terms(text: str) -> frozenset[str]:
    return frozenset(
        token for token in _normalized_text(text) if token not in _STOP_WORDS
    )


def _canonical_terms(terms: frozenset[str]) -> frozenset[str]:
    return frozenset(_SYNONYM_CANONICAL.get(term, term) for term in terms)
