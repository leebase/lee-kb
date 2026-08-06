"""Deterministic conflict identification over selected governed evidence.

Conflict detection orders competing statements by recency and declared
authority, but never resolves them.  Every emitted
:class:`~lee_kb.answer_contracts.Conflict` retains both claims and both sets of
citations; :func:`retain_conflict_sides` is the assembly helper that makes the
same invariant explicit when claims are combined downstream.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from itertools import combinations, permutations

from .answer_contracts import Claim, Confidence, Conflict, ConflictSide
from .answer_evidence import EvidenceSelection
from .contracts import Evidence

__all__ = [
    "detect_conflicts",
    "identify_conflicts",
    "retain_conflict_sides",
]

_TOKEN_PATTERN = re.compile(r"\w+(?:['’]\w+)?(?:-\w+)*", re.UNICODE)
_NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:,\d{3})*(?:\.\d+)?(?!\w)")
_NUMBER_QUANTITY_PATTERN = re.compile(
    r"(?<!\w)(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)"
    r"\s*(?P<unit>%|[^\W\d_]+(?:-[^\W\d_]+)*)",
    re.UNICODE,
)
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
        "been",
        "being",
        "by",
        "can",
        "for",
        "from",
        "could",
        "did",
        "do",
        "does",
        "has",
        "have",
        "had",
        "in",
        "is",
        "it",
        "may",
        "might",
        "must",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
        "will",
        "would",
    }
)
_VALUE_WORDS = frozenset(
    {
        "active",
        "allow",
        "allowed",
        "approved",
        "blocked",
        "closed",
        "created",
        "deny",
        "denied",
        "disable",
        "disabled",
        "enable",
        "enabled",
        "forbid",
        "forbidden",
        "inactive",
        "cannot",
        "never",
        "not",
        "no",
        "none",
        "off",
        "on",
        "open",
        "optional",
        "permit",
        "permitted",
        "prohibit",
        "prohibited",
        "required",
    }
)
_KNOWN_SYNONYM_SETS = (
    frozenset({"mandate", "mandated", "mandates", "require", "required", "requires"}),
    frozenset({"retain", "retained", "retaining", "retains", "retention"}),
    frozenset({"own", "owned", "owning", "owns"}),
    frozenset({"list", "listed", "listing", "lists"}),
    frozenset({"enable", "enabled", "on"}),
    frozenset({"disable", "disabled", "off"}),
    frozenset({"allow", "allowed", "permit", "permitted"}),
    frozenset({"deny", "denied", "forbid", "forbidden", "prohibit", "prohibited"}),
    frozenset({"day", "days"}),
    frozenset({"hour", "hours"}),
    frozenset({"minute", "minutes"}),
    frozenset({"week", "weeks"}),
    frozenset({"month", "months"}),
    frozenset({"year", "years"}),
)
_SYNONYM_CANONICAL = {
    term: min(synonyms) for synonyms in _KNOWN_SYNONYM_SETS for term in synonyms
}
_VALUE_OPPOSITIONS = frozenset(
    {
        frozenset({"active", "inactive"}),
        frozenset({"approved", "blocked"}),
        frozenset({"approved", "denied"}),
        frozenset({"closed", "open"}),
        frozenset({"disable", "enable"}),
        frozenset({"allow", "deny"}),
        frozenset({"mandate", "optional"}),
    }
)
_NEGATION_WORDS = frozenset({"cannot", "never", "no", "none", "not"})


def detect_conflicts(
    selection: EvidenceSelection,
    claims: tuple[Claim, ...] | None = None,
) -> tuple[Conflict, ...]:
    """Return pairwise conflicts present in selected governed evidence.

    When assembled ``claims`` are supplied, each evidence item is mapped to the
    claim citing it.  Without them, one directly evidenced claim is constructed
    per selected item.  The latter is useful before the full answer assembler
    exists and preserves the same citations and ordering.

    Two same-topic statements conflict only on positive disagreement evidence:
    the same quantity has different numbers, their polarity or known value
    words diverge, a prefixed antonym or one-slot substitution differs, or the
    newer statement explicitly supersedes earlier material.  Declared
    authority describes a detected disagreement; it is never a disagreement
    signal by itself.  These are detection signals only; the returned
    ``Conflict`` contract has no winner.
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

    if _negation_diverges(left.text, right.text):
        return (
            "Competing statements about "
            f"{', '.join(sorted(shared_topic))} use divergent polarity."
        )

    if _value_words_diverge(left.text, right.text):
        return (
            "Competing statements about "
            f"{', '.join(sorted(shared_topic))} use divergent value words."
        )

    if _morphological_antonyms_diverge(left.text, right.text):
        return (
            "Competing statements about "
            f"{', '.join(sorted(shared_topic))} use opposing terms."
        )

    if _substitution_diverges(left.text, right.text):
        if left.citation.authority is not right.citation.authority:
            detail = "have different declared authority."
        else:
            detail = "use different terms."
        return (
            "Competing statements about " f"{', '.join(sorted(shared_topic))} {detail}"
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

    return None


def _normalized_text(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_PATTERN.findall(text))


def _subject_terms(text: str) -> frozenset[str]:
    return _canonical_terms(
        frozenset(
            token
            for token in _normalized_text(text)
            if token not in _STOP_WORDS
            and token not in _VALUE_WORDS
            and not _SUPERSESSION_PATTERN.fullmatch(token)
        )
    )


def _value_words_diverge(left: str, right: str) -> bool:
    return _compare_value_words(left, right) == "conflict"


def _negation_diverges(left: str, right: str) -> bool:
    if _non_value_term_polarities_diverge(left, right):
        return True
    return _compare_value_words(left, right) == "conflict"


def _negated_value_words_agree(left: str, right: str) -> bool:
    """Recognize a complete positive/negated value-word agreement."""
    return _compare_value_words(left, right) == "agree"


def _compare_value_words(left: str, right: str) -> str | None:
    """Compare complete value-word sets, returning agreement or conflict."""
    left_polarities = _value_word_polarities(left)
    right_polarities = _value_word_polarities(right)
    if not left_polarities or not right_polarities:
        return None

    common_values = left_polarities.keys() & right_polarities.keys()
    if any(
        left_polarities[value] != right_polarities[value] for value in common_values
    ):
        return "conflict"

    left_only = tuple(sorted(left_polarities.keys() - right_polarities.keys()))
    right_only = tuple(sorted(right_polarities.keys() - left_polarities.keys()))
    if len(left_only) != len(right_only):
        return None
    if not left_only:
        return None

    pairings = tuple(
        pairing
        for pairing in permutations(right_only)
        if all(
            frozenset({left_value, right_value}) in _VALUE_OPPOSITIONS
            for left_value, right_value in zip(left_only, pairing)
        )
    )
    if not pairings:
        return None
    if any(
        any(
            left_polarities[left_value] == right_polarities[right_value]
            for left_value, right_value in zip(left_only, pairing)
        )
        for pairing in pairings
    ):
        return "conflict"
    return "agree"


def _value_word_polarities(text: str) -> dict[str, bool]:
    """Return each canonical value word and whether its local token is negated."""
    tokens = _normalized_text(text)
    polarities: dict[str, bool] = {}
    for index, token in enumerate(tokens):
        if token not in _VALUE_WORDS or token in _NEGATION_WORDS:
            continue
        canonical = _SYNONYM_CANONICAL.get(token, token)
        polarities[canonical] = index > 0 and _is_negation_token(tokens[index - 1])
    return polarities


def _non_value_term_polarities(text: str) -> dict[str, bool]:
    tokens = _normalized_text(text)
    polarities: dict[str, bool] = {}
    for index, token in enumerate(tokens):
        if token in _STOP_WORDS or token in _VALUE_WORDS or _is_negation_token(token):
            continue
        canonical = _SYNONYM_CANONICAL.get(token, token)
        term = _normalize_inflected_term(canonical)
        polarities[term] = index > 0 and _is_negation_token(tokens[index - 1])
    return polarities


def _non_value_term_polarities_diverge(left: str, right: str) -> bool:
    left_polarities = _non_value_term_polarities(left)
    right_polarities = _non_value_term_polarities(right)
    return any(
        left_polarities[term] != right_polarities[term]
        for term in left_polarities.keys() & right_polarities.keys()
    )


def _is_negation_token(token: str) -> bool:
    return token in _NEGATION_WORDS or token.endswith("n't")


def _numbers_diverge(left: str, right: str) -> bool:
    left_quantities = _numeric_quantities(left)
    right_quantities = _numeric_quantities(right)
    for unit in left_quantities.keys() & right_quantities.keys():
        if left_quantities[unit] != right_quantities[unit]:
            return True

    # A single unitless value can still be compared when the surrounding frame
    # is otherwise the same (for example, "version is 2" / "version is 3").
    left_values = _numeric_values(left)
    right_values = _numeric_values(right)
    if len(left_values) != 1 or len(right_values) != 1 or left_values == right_values:
        return False
    if left_quantities or right_quantities:
        return False
    left_frame = frozenset(
        term for term in _subject_terms(left) if not term.isdecimal()
    )
    right_frame = frozenset(
        term for term in _subject_terms(right) if not term.isdecimal()
    )
    return bool(left_frame and left_frame == right_frame)


def _numeric_values(text: str) -> frozenset[Decimal]:
    return frozenset(
        Decimal(number.replace(",", "")) for number in _NUMBER_PATTERN.findall(text)
    )


def _numeric_quantities(text: str) -> dict[str, frozenset[Decimal]]:
    quantities: dict[str, set[Decimal]] = {}
    for match in _NUMBER_QUANTITY_PATTERN.finditer(text):
        raw_unit = match.group("unit").casefold()
        unit = _SYNONYM_CANONICAL.get(raw_unit, raw_unit)
        quantities.setdefault(unit, set()).add(
            Decimal(match.group("number").replace(",", ""))
        )
    return {unit: frozenset(values) for unit, values in quantities.items()}


def _morphological_antonyms_diverge(left: str, right: str) -> bool:
    left_terms = _canonical_meaningful_terms(left)
    right_terms = _canonical_meaningful_terms(right)
    left_only = left_terms - right_terms
    right_only = right_terms - left_terms
    if len(left_only) != 1 or len(right_only) != 1:
        return False
    left_term = next(iter(left_only))
    right_term = next(iter(right_only))
    return _is_prefixed_antonym(left_term, right_term) or _is_prefixed_antonym(
        right_term, left_term
    )


def _is_prefixed_antonym(negative: str, positive: str) -> bool:
    for prefix in ("dis", "non", "un"):
        if negative.startswith(prefix) and len(negative) - len(prefix) >= 4:
            return negative[len(prefix) :] == positive
    return False


def _substitution_diverges(left: str, right: str) -> bool:
    left_counts = Counter(_canonical_meaningful_term_sequence(left))
    right_counts = Counter(_canonical_meaningful_term_sequence(right))
    left_only = left_counts - right_counts
    right_only = right_counts - left_counts
    if sum(left_only.values()) != 1 or sum(right_only.values()) != 1:
        return False
    return bool(left_counts.keys() & right_counts.keys())


def _statements_mergeable(left: str, right: str) -> bool:
    """Return whether statements are equivalent or one strictly elaborates."""
    if (
        _numbers_diverge(left, right)
        or _negation_diverges(left, right)
        or _value_words_diverge(left, right)
        or _morphological_antonyms_diverge(left, right)
        or _substitution_diverges(left, right)
    ):
        return False
    left_terms = _canonical_meaningful_terms(left)
    right_terms = _canonical_meaningful_terms(right)
    return (
        left_terms == right_terms
        or left_terms < right_terms
        or right_terms < left_terms
    )


def _meaningful_term_similarity(left: str, right: str) -> float:
    left_terms = _canonical_meaningful_terms(left)
    right_terms = _canonical_meaningful_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _meaningful_terms(text: str) -> frozenset[str]:
    return frozenset(
        token for token in _normalized_text(text) if token not in _STOP_WORDS
    )


def _canonical_meaningful_terms(text: str) -> frozenset[str]:
    return frozenset(_canonical_meaningful_term_sequence(text))


def _canonical_meaningful_term_sequence(text: str) -> tuple[str, ...]:
    return tuple(
        (
            canonical
            if canonical in _VALUE_WORDS or canonical in _NEGATION_WORDS
            else _normalize_inflected_term(canonical)
        )
        for canonical in (
            _SYNONYM_CANONICAL.get(token, token)
            for token in _normalized_text(text)
            if token not in _STOP_WORDS
        )
    )


def _normalize_inflected_term(term: str) -> str:
    """Collapse common English inflections for structural comparison."""
    if len(term) <= 4:
        return term
    if term.endswith("ied"):
        return f"{term[:-3]}y"
    if term.endswith("ies"):
        return f"{term[:-3]}y"
    if term.endswith("ing"):
        stem = term[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if term.endswith("ed"):
        stem = term[:-2]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if term.endswith(("ches", "shes", "sses", "xes", "zes")):
        return term[:-2]
    if term.endswith("es"):
        return term[:-1]
    if term.endswith("s"):
        return term[:-1]
    return term


def _canonical_terms(terms: frozenset[str]) -> frozenset[str]:
    return frozenset(_SYNONYM_CANONICAL.get(term, term) for term in terms)
