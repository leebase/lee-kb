"""Tests for the governed answer() surface: assembly over retrieve()."""

from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.answer import DEFAULT_SYNTHESIS_PROVIDER, answer
from lee_kb.answer_contracts import AbsenceKind, Confidence, OmissionReason, Side
from lee_kb.chunking import MARKDOWN_CHUNKER_ID
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    Authority,
    Chunk,
    ChunkId,
    DocumentType,
    FreshnessRequirement,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    Principal,
    SourceLocator,
    compute_content_hash,
)
from lee_kb.governance import MissingPrincipalError, RetrievalProviderError
from lee_kb.repository import SQLiteRepository

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
LEE = Principal("lee")


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def add_source(
    repository,
    name: str,
    text: str,
    *,
    owner: str = "lee",
    authority: Authority = Authority.DERIVED,
    source_timestamp: datetime = NOW,
) -> None:
    item_id = KnowledgeItemId("local_files", name)
    content_hash = compute_content_hash(text)
    repository.sync_item(
        KnowledgeItem(
            item_id=item_id,
            project=DEFAULT_PROJECT,
            source_locator=SourceLocator(
                "local_files", f"file:///knowledge/{name}", name
            ),
            document_type=DocumentType.MARKDOWN,
            content_hash=content_hash,
            source_timestamp=source_timestamp,
            sync_timestamp=NOW - timedelta(hours=1),
            permissions=PermissionSet(owner=owner),
            title=name,
            authority=authority,
        ),
        (
            Chunk(
                chunk_id=ChunkId(item_id, 0, content_hash),
                project=DEFAULT_PROJECT,
                text=text,
                chunker_id=MARKDOWN_CHUNKER_ID,
            ),
        ),
    )


def ask(repository, question: str, *, principal=LEE, **kwargs):
    return answer(
        repository,
        question,
        principal=principal,
        project=DEFAULT_PROJECT,
        clock=lambda: NOW,
        **kwargs,
    )


def test_answer_refuses_without_a_principal(repository) -> None:
    add_source(repository, "policy.md", "Retention policy is ninety days.")

    with pytest.raises(MissingPrincipalError):
        ask(repository, "retention policy", principal=None)


def test_answer_refuses_when_principal_is_the_wrong_type(repository) -> None:
    with pytest.raises(MissingPrincipalError):
        ask(repository, "retention policy", principal="lee")


def test_receipt_is_written_for_a_claim_bearing_answer(repository) -> None:
    add_source(repository, "policy.md", "Retention policy is ninety days long.")

    result = ask(repository, "retention policy days")

    assert result.claims
    assert result.receipt_ids
    persisted = {
        (receipt.knowledge_item_id, receipt.chunk_id, receipt.content_hash)
        for _row_id, receipt in repository.list_receipts()
    }
    for receipt_id in result.receipt_ids:
        assert (
            receipt_id.knowledge_item_id,
            receipt_id.chunk_id,
            receipt_id.content_hash,
        ) in persisted


def test_receipt_accounting_holds_for_an_empty_absent_answer(repository) -> None:
    add_source(repository, "policy.md", "A synchronized operating policy exists.")

    result = ask(repository, "an entirely unrelated missing telescope topic")

    assert result.is_absent
    assert result.absence.kind is AbsenceKind.NOT_FOUND
    assert result.claims == ()
    # No evidence was released, so retrieve() persisted zero receipts -- and
    # the answer must not fabricate any to fill the gap.
    assert result.receipt_ids == ()
    assert repository.list_receipts() == ()


def test_receipt_is_written_when_evidence_exists_but_is_all_omitted(
    repository,
) -> None:
    add_source(repository, "status.md", "Launch status telescope is approved.")

    result = ask(
        repository,
        "launch status telescope",
        freshness=FreshnessRequirement(max_staleness=timedelta(minutes=1)),
    )

    assert result.is_absent
    assert result.absence.kind is AbsenceKind.UNKNOWN
    assert result.claims == ()
    assert result.receipt_ids
    assert len(result.evidence_omitted) == len(result.receipt_ids)
    persisted_row_count = len(repository.list_receipts())
    assert persisted_row_count == len(result.receipt_ids)


def test_multi_source_synthesis_attributes_a_claim_to_more_than_one_source(
    repository,
) -> None:
    add_source(
        repository,
        "a-policy.md",
        "The retention policy requires ninety days of storage.",
    )
    add_source(
        repository,
        "b-policy.md",
        "Retention policy mandates ninety days storage retained.",
    )

    result = ask(repository, "retention policy storage days")

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.confidence is Confidence.SYNTHESIZED
    source_items = {citation.item_id for citation in claim.citations}
    assert len(source_items) == 2
    assert len(claim.citations) == 2


def test_every_substantive_claim_carries_at_least_one_citation(repository) -> None:
    add_source(repository, "alpha.md", "The launch window opens at dawn.")
    add_source(repository, "beta.md", "Crew assignments were finalized yesterday.")

    result = ask(repository, "launch window crew assignments")

    assert result.claims
    for claim in result.claims:
        assert claim.confidence is not Confidence.UNKNOWN
        assert len(claim.citations) >= 1


def test_conflicting_sources_stay_as_two_cited_claims_with_no_winner(
    repository,
) -> None:
    add_source(
        repository,
        "canonical.md",
        "Launch window is 90 minutes.",
        authority=Authority.CANONICAL,
        source_timestamp=NOW - timedelta(days=300),
    )
    add_source(
        repository,
        "derived.md",
        "Launch window is 30 minutes.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )

    result = ask(repository, "launch window minutes")

    assert len(result.claims) == 2
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert not hasattr(conflict, "winner")
    assert set(conflict.claims) == set(result.claims)
    assert conflict.more_authoritative is not Side.NEITHER
    for claim in result.claims:
        assert len(claim.citations) == 1
        assert claim.confidence is Confidence.DIRECTLY_EVIDENCED


def test_answer_confidence_is_the_weakest_claim_confidence(repository) -> None:
    add_source(
        repository,
        "canonical.md",
        "Launch window is 90 minutes.",
        authority=Authority.CANONICAL,
        source_timestamp=NOW - timedelta(days=300),
    )
    add_source(
        repository,
        "derived.md",
        "Launch window is 30 minutes.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )

    result = ask(repository, "launch window minutes")

    assert result.confidence is Confidence.DIRECTLY_EVIDENCED
    assert result.confidence is not Confidence.SYNTHESIZED


def test_answer_is_directly_evidenced_only_when_every_claim_is(repository) -> None:
    add_source(repository, "single.md", "The rollout completed on schedule.")

    result = ask(repository, "rollout schedule")

    assert len(result.claims) == 1
    assert result.claims[0].confidence is Confidence.DIRECTLY_EVIDENCED
    assert result.confidence is Confidence.DIRECTLY_EVIDENCED


def test_default_synthesis_provider_produces_attributed_prose(repository) -> None:
    add_source(repository, "single.md", "The rollout completed on schedule.")

    result = ask(repository, "rollout schedule")

    assert result.prose is not None
    assert result.synthesis_provider_id == DEFAULT_SYNTHESIS_PROVIDER.provider_id
    assert "single.md" in result.prose
    assert result.freshness is not None
    assert result.freshness.requirement_satisfied is True


def test_synthesis_provider_none_disables_narration(repository) -> None:
    add_source(repository, "single.md", "The rollout completed on schedule.")

    result = ask(repository, "rollout schedule", synthesis_provider=None)

    assert result.prose is None
    assert result.synthesis_provider_id is None
    assert result.claims


def test_synthesis_provider_failure_is_unknown_without_fallback(repository) -> None:
    add_source(repository, "single.md", "The rollout completed on schedule.")

    class FailingProvider:
        provider_id = "test.failing-provider"

        def narrate(self, claims):
            raise RuntimeError("provider diagnostic must not escape")

    result = ask(
        repository,
        "rollout schedule",
        synthesis_provider=FailingProvider(),
    )

    assert result.is_absent
    assert result.absence.kind is AbsenceKind.UNKNOWN
    assert result.confidence is Confidence.UNKNOWN
    assert result.claims == ()
    assert result.prose is None
    assert result.synthesis_provider_id == "test.failing-provider"
    assert result.freshness is not None
    assert result.freshness.requirement_satisfied is True
    assert result.receipt_ids
    assert result.evidence_used == ()
    assert result.evidence_omitted
    assert {omitted.reason for omitted in result.evidence_omitted} == {
        OmissionReason.SYNTHESIS_FAILURE
    }
    assert "provider diagnostic" not in (result.absence.detail or "")

    assert len(result.evidence_omitted) == len(result.receipt_ids)
    assert {omitted.chunk_id for omitted in result.evidence_omitted} == {
        receipt_id.chunk_id for receipt_id in result.receipt_ids
    }
    assert result.withheld_count == 0
    assert result.truncated is False
    assert "rollout completed" not in (result.absence.detail or "")


def test_denied_evidence_is_reported_inaccessible_not_not_found(repository) -> None:
    add_source(
        repository,
        "restricted.md",
        "The restricted telescope launch plan exists.",
        owner="another-principal",
    )

    result = ask(repository, "restricted telescope launch plan")

    assert result.is_absent
    assert result.absence.kind is AbsenceKind.INACCESSIBLE
    assert result.absence.withheld_count == 1
    assert result.claims == ()


def test_answer_reports_withheld_count_alongside_a_permitted_claim(repository) -> None:
    add_source(
        repository,
        "public.md",
        "The restricted telescope launch plan exists and is scheduled.",
    )
    add_source(
        repository,
        "private.md",
        "The restricted telescope launch plan is approved by another principal.",
        owner="another-principal",
    )

    result = ask(repository, "restricted telescope launch plan")

    assert result.claims
    assert result.absence is None
    assert result.withheld_count == 1
    assert result.truncated is False


def test_answer_reports_top_k_truncation_without_inventing_withholding(
    repository,
) -> None:
    add_source(repository, "first.md", "The launch plan is ready for review.")
    add_source(repository, "second.md", "The launch plan is ready for approval.")

    result = ask(repository, "launch plan ready", top_k=1)

    assert result.claims
    assert result.withheld_count == 0
    assert result.truncated is True


def test_answer_can_fail_closed_as_unknown_when_provider_resolution_fails(
    repository, monkeypatch
) -> None:
    import lee_kb.answer as answer_module

    def failed_retrieve(*args, **kwargs):
        raise RetrievalProviderError("simulated provider outage")

    monkeypatch.setattr(answer_module, "retrieve", failed_retrieve)

    result = ask(repository, "provider outage question", allow_provider_failure=True)

    assert result.is_absent
    assert result.absence.kind is AbsenceKind.UNKNOWN
    assert "retrieval provider" in result.absence.detail


def test_answer_module_does_not_import_repository_or_retrieval_at_runtime() -> None:
    import lee_kb.answer as answer_module

    # answer() must reach evidence only through lee_kb.governance.retrieve --
    # never lee_kb.repository or lee_kb.retrieval directly. Repository is
    # imported solely under typing.TYPE_CHECKING for the type hint, so at
    # runtime neither module's names are bound in this module's namespace.
    assert not hasattr(answer_module, "Repository")
    assert not hasattr(answer_module, "LexicalRetriever")
    assert not hasattr(answer_module, "SQLiteRepository")
