"""Fail-closed authorization, project scoping, and receipt tests for
lee_kb.governance.retrieve().
"""

from datetime import datetime, timezone

import pytest

from lee_kb.chunking import chunk_document
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    DocumentType,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    Principal,
    SourceLocator,
    Visibility,
    compute_content_hash,
)
from lee_kb.governance import MissingPrincipalError, retrieve
from lee_kb.repository import SQLiteRepository

SOURCE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
RETRIEVAL_TIME = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)

OWNER = Principal("lee")
STRANGER = Principal("mallory")


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def sync_markdown(
    repository,
    source_object_id: str,
    text: str,
    *,
    project: str = DEFAULT_PROJECT,
    owner: str = "lee",
    visibility: Visibility = Visibility.PRIVATE,
    allowed_principals: tuple[str, ...] = (),
) -> KnowledgeItem:
    item_id = KnowledgeItemId("local_files", source_object_id)
    item = KnowledgeItem(
        item_id=item_id,
        project=project,
        source_locator=SourceLocator(
            connector_id="local_files",
            uri=f"file:///knowledge/{source_object_id}",
            label=source_object_id,
        ),
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash(text),
        source_timestamp=SOURCE_TIME,
        sync_timestamp=SYNC_TIME,
        permissions=PermissionSet(
            owner=owner,
            visibility=visibility,
            allowed_principals=allowed_principals,
        ),
        title=source_object_id,
    )
    chunks = chunk_document(
        text,
        item_id=item_id,
        project=project,
        document_type=DocumentType.MARKDOWN,
    )
    repository.sync_item(item, chunks)
    return item


def run(
    repository, query: str, *, principal=OWNER, project: str = DEFAULT_PROJECT, **kwargs
):
    return retrieve(
        repository,
        query,
        principal=principal,
        project=project,
        clock=lambda: RETRIEVAL_TIME,
        **kwargs,
    )


def test_missing_principal_fails_closed(repository) -> None:
    sync_markdown(repository, "notes.md", "unique lexeme zephyrgrove")

    with pytest.raises(MissingPrincipalError):
        retrieve(
            repository,
            "zephyrgrove",
            project=DEFAULT_PROJECT,
            clock=lambda: RETRIEVAL_TIME,
        )

    with pytest.raises(MissingPrincipalError):
        run(repository, "zephyrgrove", principal=None)


def test_unknown_principal_receives_no_evidence(repository) -> None:
    sync_markdown(repository, "private.md", "confidential lexeme quorvane")

    bundle = run(repository, "quorvane", principal=STRANGER)

    assert bundle.evidence == ()
    assert bundle.denied_count == 1


def test_denied_evidence_never_appears_in_a_bundle(repository) -> None:
    sync_markdown(repository, "private.md", "shared lexeme brindlewick")
    sync_markdown(
        repository,
        "public.md",
        "shared lexeme brindlewick",
        owner="lee",
        allowed_principals=("mallory",),
    )

    bundle = run(repository, "brindlewick", principal=STRANGER)

    assert len(bundle.evidence) == 1
    assert (
        bundle.evidence[0].citation.source_locator.uri == "file:///knowledge/public.md"
    )
    assert bundle.denied_count == 1
    assert all(
        evidence.citation.source_locator.uri != "file:///knowledge/private.md"
        for evidence in bundle.evidence
    )


def test_receipt_persisted_for_every_evidence_item_including_empty_results(
    repository,
) -> None:
    item = sync_markdown(repository, "receipted.md", "traceable lexeme oakspindle")

    bundle = run(repository, "oakspindle")

    assert len(bundle.receipts) == 1
    receipt = bundle.receipts[0]
    assert receipt.knowledge_item_id == item.item_id
    assert receipt.chunk_id == bundle.evidence[0].chunk_id
    assert receipt.content_hash == bundle.evidence[0].chunk_id.content_hash
    assert receipt.source_locator == item.source_locator
    assert receipt.retrieval_timestamp == RETRIEVAL_TIME
    assert receipt.principal == OWNER

    stored_id, stored_receipt = repository.list_receipts(item.item_id)[0]
    assert stored_id > 0
    assert stored_receipt == receipt

    empty_bundle = run(repository, "nonexistenttoken")

    assert empty_bundle.evidence == ()
    assert empty_bundle.receipts == ()
    assert repository.list_receipts() == ((stored_id, stored_receipt),)


def test_out_of_project_evidence_is_excluded(repository) -> None:
    sync_markdown(
        repository, "alpha.md", "cross project lexeme thistlemark", project="alpha"
    )
    sync_markdown(
        repository, "beta.md", "cross project lexeme thistlemark", project="beta"
    )

    bundle = run(repository, "thistlemark", project="alpha")

    assert len(bundle.evidence) == 1
    assert bundle.evidence[0].project == "alpha"
    assert all(evidence.project == "alpha" for evidence in bundle.evidence)


def _public_bundle_producers():
    """Every public callable in lee_kb whose return annotation is EvidenceBundle.

    Guards against S1-R-01 regressions: a second public evidence surface that
    bypasses permission evaluation must fail this sweep, not a code review.
    """
    import importlib
    import inspect
    import pkgutil

    import lee_kb

    producers = []
    for info in pkgutil.walk_packages(lee_kb.__path__, "lee_kb."):
        module = importlib.import_module(info.name)
        for name in getattr(module, "__all__", ()):
            obj = getattr(module, name)
            if inspect.isfunction(obj):
                if "EvidenceBundle" in str(inspect.signature(obj).return_annotation):
                    producers.append((info.name, name))
            elif inspect.isclass(obj):
                for method_name, method in inspect.getmembers(obj, inspect.isfunction):
                    if method_name.startswith("_"):
                        continue
                    annotation = inspect.signature(method).return_annotation
                    if "EvidenceBundle" in str(annotation):
                        producers.append((f"{info.name}.{name}", method_name))
    return sorted(producers)


def test_governed_retrieve_is_the_only_public_evidence_surface(repository) -> None:
    assert _public_bundle_producers() == [("lee_kb.governance", "retrieve")]

    sync_markdown(repository, "private.md", "sweeptoken secret content")
    bundle = retrieve(
        repository,
        "sweeptoken",
        principal=STRANGER,
        project=DEFAULT_PROJECT,
        clock=lambda: RETRIEVAL_TIME,
    )
    assert bundle.evidence == ()
    assert bundle.denied_count >= 1
