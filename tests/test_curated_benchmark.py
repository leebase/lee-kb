"""Focused, corpus-independent tests for the public benchmark helpers."""

from __future__ import annotations

from dataclasses import dataclass

from tools.run_curated_benchmark import (
    build_report,
    parse_faq,
    select_stable_cases,
    source_matches,
    strip_source_fragment,
)


@dataclass(frozen=True)
class ItemId:
    source_object_id: str


@dataclass(frozen=True)
class Citation:
    item_id: ItemId


def test_source_pointer_parsing_strips_fragment_and_keeps_memory_fields() -> None:
    cases = parse_faq("""# FAQ
## Commercial
**Which plan?**
Answer.
Source: `commercial.md#pricing`

**No pointer**
Answer only.
## Platform
**What is it?**
Source: platform.md#overview
""")
    assert len(cases) == 2
    assert cases[0].question == "Which plan?"
    assert cases[0].expected_source_id == "commercial.md"
    assert cases[1].expected_source_id == "platform.md"
    assert strip_source_fragment("<platform.md#overview>") == "platform.md"


def test_stable_section_selection_is_source_ordered_and_renumbers_opaque_ids() -> None:
    cases = parse_faq("""## Other
**other**
Source: other.md
## Platform
**platform one**
Source: platform.md#one
### Nested
**platform two**
Source: platform.md#two
## Commercial
**commercial**
Source: commercial.md
""")
    selected = select_stable_cases(cases)
    assert [case.question for case in selected] == [
        "platform one",
        "platform two",
        "commercial",
    ]
    assert [case.case_id for case in selected] == ["case-001", "case-002", "case-003"]


def test_source_matching_uses_source_object_id_not_locator_text() -> None:
    citation = Citation(ItemId("canonical/faq.md"))
    assert source_matches("canonical/faq.md#commercial", citation)
    assert not source_matches("other.md", citation)
    assert source_matches("canonical/faq.md", ItemId("canonical/faq.md"))


def test_report_is_aggregate_and_redacted() -> None:
    report = build_report(
        projection={"knowledge_items": 4, "live_items": 4, "chunks": 9},
        selected_cases=3,
        source_present=2,
        source_missing=1,
        retrieve_hit_at_1=1,
        retrieve_hit_at_10=2,
        retrieve_eligible=2,
        retrieve_failures=0,
        answer_source_citation_hits=2,
        answer_eligible=2,
        answer_failures=0,
        claim_total=3,
        conflict_total=0,
        retrieve_latency_ms=[1.0, 2.0],
        answer_latency_ms=[3.0],
        case_ids=["case-001", "case-002", "case-003"],
        controls={
            "no_evidence": "not_found",
            "unauthorized": "inaccessible",
            "strict_stale": "stale",
        },
    )
    assert report["cases"] == {
        "selected": 3,
        "source_present": 2,
        "source_missing": 1,
        "case_ids": ["case-001", "case-002", "case-003"],
    }
    assert report["retrieval"]["hit_at_1"]["hits"] == 1
    assert report["answer"]["claim_total"] == 3
    assert report["controls"]["unauthorized"] == "inaccessible"
    serialized = str(report)
    for secret in ("Which plan?", "commercial.md", "claim prose", "/private/workspace"):
        assert secret not in serialized
