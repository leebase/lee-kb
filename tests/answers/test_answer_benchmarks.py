"""Permanent offline regressions for the seven governed-answer families.

Every document in this module is synthetic.  The harness writes distinct source
roots under pytest's temporary directory, discovers and fetches them through the
local-file connector, projects connector output into temporary SQLite, and asks
questions only through the public :func:`lee_kb.answer.answer` surface.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from lee_kb.answer import answer
from lee_kb.answer_contracts import Confidence, OmissionReason
from lee_kb.chunking import chunk_document
from lee_kb.connectors.local_files import LocalFilesConnector, RootConfig
from lee_kb.contracts import (
    Authority,
    ChangeType,
    KnowledgeItem,
    KnowledgeItemId,
    Principal,
)
from lee_kb.repository import SQLiteRepository

PROJECT = "answer-benchmarks"
PRINCIPAL = Principal("lee")
CONNECTOR_ID = "benchmark_local_files"
SOURCE_TIME = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
ANSWER_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SourceFixture:
    root: str
    filename: str
    content: str
    authority: Authority = Authority.DERIVED


SOURCES = (
    SourceFixture(
        "naming-repository",
        "naming-decision.md",
        """# Documentation Steward Naming Decision

The full official name is Documentation Steward Coordination Service.
Its identifiers are DSCS and steward-coordinator. The naming decision assigns
the steward-manifest work package to the Documentation Steward Coordination
Service.
""",
    ),
    SourceFixture(
        "gate-repository",
        "blocking-gate.md",
        """# Documentation Steward Blocking Gate

The documentation steward blocking gate remains blocked until the
steward-manifest work described by the naming decision is implemented and the
DSCS identifier is registered.
""",
    ),
    SourceFixture(
        "status-repository",
        "current-status.md",
        """# Documentation Steward Current Status

The current documentation steward status says naming is approved, DSCS
registration is in progress, and the blocking gate remains blocked.
""",
    ),
    SourceFixture(
        "absence-repository",
        "orbital-archive-decision.md",
        """# Orbital Archive Decision

The planning record names the Orbital Archive dossier. The Orbital Archive
dossier was never created.
""",
    ),
    SourceFixture(
        "canonical-operations",
        "meridian-channel.md",
        """# Meridian Deployment Channel

The deployment channel for Meridian is enabled.
""",
        authority=Authority.CANONICAL,
    ),
    SourceFixture(
        "field-operations",
        "meridian-field-note.md",
        """# Meridian Deployment Channel

The deployment channel for Meridian is disabled.
""",
        authority=Authority.DERIVED,
    ),
    SourceFixture(
        "duplicate-repository",
        "harbor-readiness.md",
        """# Harbor Readiness Summary

Harbor readiness requires the cobalt checklist.

# Harbor Readiness Detail

Harbor readiness requires the cobalt checklist.

# Harbor Readiness Appendix

Harbor readiness requires the cobalt checklist.
""",
    ),
    SourceFixture(
        "independent-audit",
        "harbor-audit.md",
        """# Harbor Readiness Audit

The independent audit confirms that harbor readiness requires the cobalt
checklist.
""",
    ),
    SourceFixture(
        "legacy-harbor-notes",
        "legacy-manifest.md",
        """# Legacy Harbor Notes

The legacy harbor manifest does not exist.
""",
    ),
    SourceFixture(
        "canonical-navigation",
        "solstice-route.md",
        """# Solstice Navigation Route

The navigation route for Solstice uses the eastern corridor.
""",
        authority=Authority.CANONICAL,
    ),
    SourceFixture(
        "derived-navigation-a",
        "solstice-route.md",
        """# Solstice Navigation Route

The navigation route for Solstice uses the western corridor.
""",
    ),
    SourceFixture(
        "derived-navigation-b",
        "solstice-route.md",
        """# Solstice Navigation Route

The navigation route for Solstice uses the western corridor.
""",
    ),
)

SAME_AUTHORITY_SOURCES = (
    SourceFixture(
        "same-authority-a",
        "equinox-channel-enabled.md",
        """# Equinox Deployment Channel

The deployment channel for Equinox is enabled.
""",
    ),
    SourceFixture(
        "same-authority-b",
        "equinox-channel-disabled.md",
        """# Equinox Deployment Channel

The deployment channel for Equinox is disabled.
""",
    ),
)


NON_COMPETING_CASES = (
    (
        "paraphrase-by-voice",
        "Who owns the Perseus runbook?",
        "The platform team owns the Perseus runbook.",
        "The Perseus runbook is owned by the platform team.",
    ),
    (
        "elaboration-by-added-clause",
        "What does the Halcyon policy retain?",
        "The Halcyon policy retains audit logs.",
        "Audit logs are retained by the Halcyon policy under section 4.",
    ),
    (
        "synonym-restatement",
        "What does the Cygnus review require?",
        "The Cygnus review mandates signed approval.",
        "The Cygnus review requires signed approval.",
    ),
    (
        "differing-detail-level",
        "Where does the Vega ingest queue run?",
        "The Vega ingest queue runs in the north region.",
        "The Vega ingest queue runs in the north region during overnight imports.",
    ),
    (
        "same-fact-from-two-roots",
        "Who is the Aquila registry deployment owner?",
        "The Aquila registry lists the deployment owner as operations.",
        "The deployment owner is listed as operations in the Aquila registry.",
    ),
    (
        "formatting-only",
        "What is the Orion release cadence?",
        "Orion release cadence: weekly.",
        "Orion release cadence -- weekly.",
    ),
    (
        "emphatic-agreement",
        "What is the Fennel gate requirement?",
        "The Fennel gate is required.",
        "The Fennel gate is required, not optional.",
    ),
    (
        "negated-opposite-agreement",
        "What is the Fennel gate requirement?",
        "The Fennel gate is required.",
        "The Fennel gate is not optional.",
    ),
)


CONTRADICTING_CASES = (
    (
        "enabled-versus-turned-off",
        "What is the state of the release gate for Kestrel?",
        "The release gate for Kestrel is enabled.",
        "The release gate for Kestrel is turned off.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "permitted-versus-forbidden",
        "What is the export policy for Vega?",
        "The export policy for Vega is permitted.",
        "The export policy for Vega is forbidden.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "numeric-divergence",
        "What is the retention window for Lyra in days?",
        "The retention window for Lyra is 30 days.",
        "The retention window for Lyra is 90 days.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "canonical-versus-derived",
        "Which corridor does the Draco route use?",
        "The Draco route uses the eastern corridor.",
        "The Draco route uses the western corridor.",
        Authority.CANONICAL,
        Authority.DERIVED,
    ),
    (
        "morphological-antonym-outside-word-list",
        "Is the Phoenix deployment restricted?",
        "The Phoenix deployment is restricted.",
        "The Phoenix deployment is unrestricted.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "negated-non-value-word",
        "Is the Nimbus archive encrypted?",
        "The Nimbus archive is encrypted.",
        "The Nimbus archive is not encrypted.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "compound-value-divergence",
        "What is the Fennel gate state?",
        "The Fennel gate is required and approved.",
        "The Fennel gate is not optional and denied.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "never-non-value-word",
        "Does the Willow relay report outages?",
        "The Willow relay reports outages.",
        "The Willow relay never reports outages.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "same-authority-proper-noun-substitution",
        "Who owns the Juniper escalation?",
        "The Juniper escalation is owned by the escalation desk.",
        "The Juniper escalation is owned by the vendor desk.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "same-authority-weekday-substitution",
        "When does the Rowan report fall?",
        "The Rowan report falls on Tuesday.",
        "The Rowan report falls on Thursday.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
    (
        "same-authority-place-substitution",
        "Where is the Cedar archive stored?",
        "The Cedar archive is stored in Frankfurt.",
        "The Cedar archive is stored in Dublin.",
        Authority.DERIVED,
        Authority.DERIVED,
    ),
)


@pytest.fixture(scope="module")
def benchmark_repository(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("answer-benchmarks")
    roots = _write_sources(workspace, SOURCES)
    connector = LocalFilesConnector(tuple(roots), connector_id=CONNECTOR_ID)
    database = workspace / "knowledge.sqlite"
    with SQLiteRepository(database) as repository:
        _sync(connector, repository, expected_sources=len(SOURCES))
        yield repository


@pytest.fixture(scope="module")
def same_authority_repository(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("same-authority-conflict")
    roots = _write_sources(workspace, SAME_AUTHORITY_SOURCES)
    connector = LocalFilesConnector(
        tuple(roots), connector_id=f"{CONNECTOR_ID}_same_authority"
    )
    database = workspace / "knowledge.sqlite"
    with SQLiteRepository(database) as repository:
        _sync(
            connector,
            repository,
            expected_sources=len(SAME_AUTHORITY_SOURCES),
        )
        yield repository


def _write_sources(workspace, sources: tuple[SourceFixture, ...]):
    roots = []
    for fixture in sources:
        root_path = workspace / fixture.root
        root_path.mkdir()
        document_path = root_path / fixture.filename
        document_path.write_text(fixture.content, encoding="utf-8")
        timestamp = SOURCE_TIME.timestamp()
        os.utime(document_path, (timestamp, timestamp))
        roots.append(
            RootConfig(
                name=fixture.root,
                path=root_path,
                owner=PRINCIPAL.principal_id,
                include=("*.md",),
                authority=fixture.authority,
                project=PROJECT,
            )
        )
    return roots


def _sync(
    connector: LocalFilesConnector,
    repository: SQLiteRepository,
    *,
    expected_sources: int,
) -> None:
    """Project connector output through the same deterministic offline pattern."""
    discovered = connector.discover()
    changes = connector.list_changes()
    assert len(discovered) == expected_sources
    assert len(changes) == expected_sources

    for change in changes:
        assert change.change_type is ChangeType.CREATED
        document = connector.fetch(change.source_object_id)
        item_id = KnowledgeItemId(connector.connector_id, document.source_object_id)
        item = KnowledgeItem(
            item_id=item_id,
            project=document.project,
            source_locator=document.source_locator,
            document_type=document.document_type,
            content_hash=document.content_hash,
            source_timestamp=document.source_timestamp,
            sync_timestamp=SYNC_TIME,
            permissions=connector.permissions(document.source_object_id),
            title=document.title,
            authority=document.authority,
            trust=document.trust,
        )
        chunks = chunk_document(
            document.content,
            item_id=item_id,
            project=document.project,
            document_type=document.document_type,
        )
        repository.sync_item(item, chunks)

    assert connector.checkpoint(discovered)


def _ask(repository: SQLiteRepository, question: str, **options):
    top_k = options.pop("top_k", 20)
    return answer(
        repository,
        question,
        principal=PRINCIPAL,
        project=PROJECT,
        top_k=top_k,
        clock=lambda: ANSWER_TIME,
        **options,
    )


def _ask_sources(workspace, sources: tuple[SourceFixture, ...], question: str):
    roots = _write_sources(workspace, sources)
    connector = LocalFilesConnector(
        tuple(roots), connector_id=f"{CONNECTOR_ID}_{workspace.name}"
    )
    with SQLiteRepository(workspace / "knowledge.sqlite") as repository:
        _sync(connector, repository, expected_sources=len(sources))
        return _ask(repository, question)


DOCUMENTATION_STEWARD_QUESTION = (
    "What is the documentation steward official name and identifier, what "
    "blocks its gate, and what is its current status?"
)


def test_documentation_steward_shape_combines_three_roots(
    benchmark_repository,
) -> None:
    result = _ask(benchmark_repository, DOCUMENTATION_STEWARD_QUESTION)
    answer_text = " ".join(claim.text for claim in result.claims)

    assert "Documentation Steward Coordination Service" in answer_text
    assert "steward-manifest" in answer_text
    assert "registration is in progress" in answer_text
    assert {
        citation.item_id.source_object_id.split(":", 1)[0]
        for claim in result.claims
        for citation in claim.citations
    } >= {"naming-repository", "gate-repository", "status-repository"}


def test_fuzzy_partial_name_finds_the_full_official_name(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "What is the full official name of documentation steward?",
    )

    matching = tuple(
        claim
        for claim in result.claims
        if "Documentation Steward Coordination Service" in claim.text
    )
    assert matching
    assert any(
        citation.item_id.source_object_id == "naming-repository:naming-decision.md"
        for claim in matching
        for citation in claim.citations
    )


def test_cross_repository_synthesis_attributes_at_least_three_roots(
    benchmark_repository,
) -> None:
    result = _ask(benchmark_repository, DOCUMENTATION_STEWARD_QUESTION)
    attributed_roots = {
        citation.item_id.source_object_id.split(":", 1)[0]
        for claim in result.claims
        for citation in claim.citations
    }

    assert len(attributed_roots) >= 3
    assert (
        len(
            {
                citation.source_locator.uri
                for claim in result.claims
                for citation in claim.citations
            }
        )
        >= 3
    )


def test_authoritative_absence_is_a_cited_evidenced_not_found(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "Was the Orbital Archive dossier created?",
    )

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert "never created" in claim.text
    assert claim.confidence is Confidence.DIRECTLY_EVIDENCED
    assert len(claim.citations) == 1
    assert (
        claim.citations[0].item_id.source_object_id
        == "absence-repository:orbital-archive-decision.md"
    )
    # A cited negative statement is the evidenced NOT_FOUND path. It is not a
    # silent empty-result absence, which would have no claims or citations.
    assert result.absence is None
    assert result.confidence is not Confidence.UNKNOWN


def test_conflicting_evidence_reports_both_sides_without_a_winner(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "Is the deployment channel for Meridian enabled or disabled?",
    )

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert not hasattr(conflict, "winner")
    assert {
        citation.item_id.source_object_id
        for claim in conflict.claims
        for citation in claim.citations
    } == {
        "canonical-operations:meridian-channel.md",
        "field-operations:meridian-field-note.md",
    }
    assert (
        "enabled" in conflict.left.claim.text or "enabled" in conflict.right.claim.text
    )
    assert (
        "disabled" in conflict.left.claim.text
        or "disabled" in conflict.right.claim.text
    )
    assert set(conflict.claims) <= set(result.claims)


def test_same_authority_value_word_contradiction_stays_as_two_claims(
    same_authority_repository,
) -> None:
    result = _ask(
        same_authority_repository,
        "Is the deployment channel for Equinox enabled or disabled?",
    )

    assert len(result.conflicts) == 1
    assert len(result.claims) == 2
    assert all(len(claim.citations) == 1 for claim in result.claims)
    assert {
        citation.item_id.source_object_id
        for claim in result.claims
        for citation in claim.citations
    } == {
        "same-authority-a:equinox-channel-enabled.md",
        "same-authority-b:equinox-channel-disabled.md",
    }
    claim_texts = tuple(claim.text.casefold() for claim in result.claims)
    assert any("enabled" in text and "disabled" not in text for text in claim_texts)
    assert any("disabled" in text and "enabled" not in text for text in claim_texts)


@pytest.mark.parametrize(
    ("case_name", "question", "left_statement", "right_statement"),
    NON_COMPETING_CASES,
    ids=tuple(case[0] for case in NON_COMPETING_CASES),
)
def test_non_competing_statement_pairs_produce_no_conflicts(
    tmp_path,
    case_name,
    question,
    left_statement,
    right_statement,
) -> None:
    sources = (
        SourceFixture("agreeing-left", f"{case_name}-left.md", left_statement),
        SourceFixture("agreeing-right", f"{case_name}-right.md", right_statement),
    )

    result = _ask_sources(tmp_path, sources, question)

    assert result.conflicts == ()


@pytest.mark.parametrize(
    (
        "case_name",
        "question",
        "left_statement",
        "right_statement",
        "left_authority",
        "right_authority",
    ),
    CONTRADICTING_CASES,
    ids=tuple(case[0] for case in CONTRADICTING_CASES),
)
def test_contradicting_statement_pairs_produce_one_conflict_with_cited_sides(
    tmp_path,
    case_name,
    question,
    left_statement,
    right_statement,
    left_authority,
    right_authority,
) -> None:
    sources = (
        SourceFixture(
            "contradicting-left",
            f"{case_name}-left.md",
            left_statement,
            authority=left_authority,
        ),
        SourceFixture(
            "contradicting-right",
            f"{case_name}-right.md",
            right_statement,
            authority=right_authority,
        ),
    )

    result = _ask_sources(tmp_path, sources, question)

    assert len(result.conflicts) == 1
    assert len(result.claims) == 2
    assert all(len(claim.citations) == 1 for claim in result.claims)
    assert {
        citation.item_id.source_object_id.split(":", 1)[0]
        for claim in result.claims
        for citation in claim.citations
    } == {"contradicting-left", "contradicting-right"}
    assert set(result.conflicts[0].claims) == set(result.claims)


def test_negated_non_value_word_refuses_merge_when_conflict_detection_is_bypassed(
    tmp_path, monkeypatch
) -> None:
    import lee_kb.answer as answer_module

    sources = (
        SourceFixture(
            "negation-left",
            "encrypted.md",
            "The Nimbus archive is encrypted.",
        ),
        SourceFixture(
            "negation-right",
            "not-encrypted.md",
            "The Nimbus archive is not encrypted.",
        ),
    )
    monkeypatch.setattr(answer_module, "detect_conflicts", lambda *_args, **_kwargs: ())

    result = _ask_sources(tmp_path, sources, "Is the Nimbus archive encrypted?")

    assert result.conflicts == ()
    assert len(result.claims) == 2
    assert all(len(claim.citations) == 1 for claim in result.claims)


def test_conflict_detection_has_no_false_conflicts_or_missed_contradictions(
    tmp_path,
) -> None:
    false_conflicts = 0
    for authority_pair in (
        (Authority.DERIVED, Authority.DERIVED),
        (Authority.CANONICAL, Authority.DERIVED),
    ):
        for case in NON_COMPETING_CASES:
            case_name, question, left_statement, right_statement = case
            workspace = tmp_path / f"agreeing-{authority_pair[0].value}-{case_name}"
            workspace.mkdir()
            sources = (
                SourceFixture(
                    "agreeing-left",
                    f"{case_name}-left.md",
                    left_statement,
                    authority=authority_pair[0],
                ),
                SourceFixture(
                    "agreeing-right",
                    f"{case_name}-right.md",
                    right_statement,
                    authority=authority_pair[1],
                ),
            )
            result = _ask_sources(workspace, sources, question)
            false_conflicts += bool(result.conflicts)

    missed_contradictions = 0
    merged_contradictions = 0
    for case in CONTRADICTING_CASES:
        (
            case_name,
            question,
            left_statement,
            right_statement,
            left_authority,
            right_authority,
        ) = case
        workspace = tmp_path / f"contradicting-{case_name}"
        workspace.mkdir()
        sources = (
            SourceFixture(
                "contradicting-left",
                f"{case_name}-left.md",
                left_statement,
                authority=left_authority,
            ),
            SourceFixture(
                "contradicting-right",
                f"{case_name}-right.md",
                right_statement,
                authority=right_authority,
            ),
        )
        result = _ask_sources(workspace, sources, question)
        missed_contradictions += not bool(result.conflicts)
        merged_contradictions += any(
            len(claim.citations) > 1 for claim in result.claims
        )

    assert false_conflicts == 0
    assert missed_contradictions == 0
    assert merged_contradictions == 0


def test_top_ranked_absence_statement_is_additive_to_substantive_answer(
    tmp_path,
) -> None:
    sources = (
        SourceFixture(
            "aurora-checklist",
            "requirements.md",
            (
                "The aurora readiness review requires the cobalt checklist. "
                "Operators complete its telemetry, rollback, communications, "
                "and observability sections before launch."
            ),
            authority=Authority.CANONICAL,
        ),
        SourceFixture(
            "aurora-approval",
            "approval.md",
            (
                "The aurora readiness review requires signed launch approval. "
                "The operations lead records the approval after the final "
                "resilience exercise and stakeholder briefing."
            ),
            authority=Authority.CANONICAL,
        ),
        SourceFixture(
            "aurora-dossier",
            "dossier.md",
            "The aurora readiness review dossier does not exist.",
            authority=Authority.CANONICAL,
        ),
    )

    control_workspace = tmp_path / "control"
    control_workspace.mkdir()
    control = _ask_sources(
        control_workspace,
        sources[:2],
        "What does the aurora readiness review require?",
    )
    assert any("cobalt checklist" in claim.text.casefold() for claim in control.claims)
    assert any(
        "signed launch approval" in claim.text.casefold() for claim in control.claims
    )

    treatment_workspace = tmp_path / "treatment"
    treatment_workspace.mkdir()
    result = _ask_sources(
        treatment_workspace,
        sources,
        "What does the aurora readiness review require?",
    )

    assert (
        result.evidence_used[0].chunk_id.item_id.source_object_id.split(":", 1)[0]
        == "aurora-dossier"
    )
    claim_texts = tuple(claim.text.casefold() for claim in result.claims)
    assert any("cobalt checklist" in text for text in claim_texts)
    assert any("signed launch approval" in text for text in claim_texts)
    absence_claims = tuple(
        claim for claim in result.claims if "does not exist" in claim.text.casefold()
    )
    assert len(absence_claims) == 1
    assert result.claims[0] == absence_claims[0]
    assert absence_claims[0].confidence is Confidence.DIRECTLY_EVIDENCED
    assert len(absence_claims[0].citations) == 1
    assert {
        citation.item_id.source_object_id.split(":", 1)[0]
        for claim in result.claims
        for citation in claim.citations
    } >= {"aurora-checklist", "aurora-approval", "aurora-dossier"}


def test_unresponsive_absence_shaped_sentence_does_not_replace_answer(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "What does harbor readiness require?",
    )

    assert result.absence is None
    assert any("cobalt checklist" in claim.text for claim in result.claims)
    assert {
        citation.item_id.source_object_id
        for claim in result.claims
        for citation in claim.citations
    } >= {
        "duplicate-repository:harbor-readiness.md",
        "independent-audit:harbor-audit.md",
    }


def test_three_source_conflict_cites_each_chunk_in_exactly_one_claim(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "Which corridor does the Solstice navigation route use?",
        top_k=3,
    )

    source_ids = {
        "canonical-navigation:solstice-route.md",
        "derived-navigation-a:solstice-route.md",
        "derived-navigation-b:solstice-route.md",
    }
    citation_counts = Counter(
        citation.chunk_id
        for claim in result.claims
        for citation in claim.citations
        if citation.item_id.source_object_id in source_ids
    )
    assert len(result.claims) == 3
    assert all(len(claim.citations) == 1 for claim in result.claims)
    assert not any(
        "eastern" in claim.text.casefold() and "western" in claim.text.casefold()
        for claim in result.claims
    )
    assert len(citation_counts) == 3
    assert set(citation_counts.values()) == {1}


def test_duplicate_source_cannot_dominate_or_repeat_its_claim(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "What does harbor readiness require from the cobalt checklist?",
    )
    duplicate_source = "duplicate-repository:harbor-readiness.md"
    duplicate_citations = tuple(
        citation
        for claim in result.claims
        for citation in claim.citations
        if citation.item_id.source_object_id == duplicate_source
    )

    assert len(duplicate_citations) == 1
    assert (
        sum(
            "Harbor readiness requires the cobalt checklist" in claim.text
            for claim in result.claims
        )
        == 1
    )
    redundant = tuple(
        omitted
        for omitted in result.evidence_omitted
        if omitted.evidence.item_id.source_object_id == duplicate_source
    )
    assert len(redundant) == 2
    assert {omitted.reason for omitted in redundant} == {OmissionReason.REDUNDANT}
    assert all(omitted.detail for omitted in redundant)


PROVENANCE_QUESTIONS = (
    DOCUMENTATION_STEWARD_QUESTION,
    "What is the full official name of documentation steward?",
    "Was the Orbital Archive dossier created?",
    "Is the deployment channel for Meridian enabled or disabled?",
    "What does harbor readiness require from the cobalt checklist?",
)


@pytest.mark.parametrize("question", PROVENANCE_QUESTIONS)
def test_every_positive_claim_has_resolvable_provenance_and_accounted_omissions(
    benchmark_repository,
    question,
) -> None:
    result = _ask(benchmark_repository, question)

    assert result.claims
    for claim in result.claims:
        assert claim.confidence is not Confidence.UNKNOWN
        assert claim.citations
        for citation in claim.citations:
            item = benchmark_repository.get_item(citation.item_id)
            assert item is not None
            assert citation.source_locator == item.source_locator
            assert any(
                chunk.chunk_id == citation.chunk_id
                for chunk in benchmark_repository.get_chunks(citation.item_id)
            )

    assert {receipt.chunk_id for receipt in result.receipt_ids} == {
        evidence.chunk_id for evidence in result.evidence_used
    } | {omitted.chunk_id for omitted in result.evidence_omitted}
    if len(result.receipt_ids) > len(result.evidence_used):
        assert result.evidence_omitted
        assert all(
            omitted.reason in OmissionReason and omitted.detail
            for omitted in result.evidence_omitted
        )


def test_benchmark_corpus_is_entirely_synthetic() -> None:
    assert len(SOURCES) == 12
    assert {fixture.root for fixture in SOURCES} == {
        "naming-repository",
        "gate-repository",
        "status-repository",
        "absence-repository",
        "canonical-operations",
        "field-operations",
        "duplicate-repository",
        "independent-audit",
        "legacy-harbor-notes",
        "canonical-navigation",
        "derived-navigation-a",
        "derived-navigation-b",
    }
