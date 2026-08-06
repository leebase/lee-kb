"""End-to-end governed ingestion tests for the Office format handlers."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest
from docx import Document as DocxDocument
from openpyxl import Workbook
from pptx import Presentation

from lee_kb.answer import answer
from lee_kb.chunking import chunk_document
from lee_kb.connectors.local_files import LocalFilesConnector
from lee_kb.contracts import DEFAULT_PROJECT, DocumentType, KnowledgeItemId, Principal
from lee_kb.governance import retrieve
from lee_kb.main import _sync_connector
from lee_kb.repository import SQLiteRepository

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def _write_config(path, source_root, *, include, project="default") -> None:
    patterns = ", ".join(f'"{pattern}"' for pattern in include)
    path.write_text(f"""
schema = 1

[roots.notes]
path = "{source_root.as_posix()}"
owner = "lee"
include = [{patterns}]
project = "{project}"
""")


def _connector(tmp_path, files, *, include):
    source_root = tmp_path / "sources"
    source_root.mkdir(parents=True)
    for name, payload in files.items():
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    config = tmp_path / "sources.toml"
    _write_config(config, source_root, include=include)
    return LocalFilesConnector.from_config(config)


def _docx_bytes(text: str, *, heading: str = "Document") -> bytes:
    document = DocxDocument()
    document.add_heading(heading, level=1)
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Forecast"
    sheet["A1"] = "Revenue"
    sheet["B1"] = 42
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pptx_bytes(text: str = "Release readiness is confirmed.") -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Roadmap"
    slide.placeholders[1].text = text
    buffer = BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def test_office_files_use_discovery_parser_chunk_search_and_answer_path(
    tmp_path,
) -> None:
    connector = _connector(
        tmp_path,
        {
            "guide.docx": _docx_bytes(
                "The quarterly plan assigns the launch owner.", heading="Quarterly plan"
            ),
            "forecast.xlsx": _xlsx_bytes(),
            "roadmap.pptx": _pptx_bytes(),
        },
        include=("*.docx", "*.xlsx", "*.pptx"),
    )
    report = connector.discover_report()

    assert {obj.document_type for obj in report.objects} == {
        DocumentType.DOCX,
        DocumentType.XLSX,
        DocumentType.PPTX,
    }
    assert report.unhandled_formats == {}

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        summary = _sync_connector(
            connector,
            repository,
            root_filter=None,
            sync_timestamp=NOW,
        )
        assert summary.created == 3

        quarterly = retrieve(
            repository,
            "quarterly plan launch owner",
            principal=Principal("lee"),
            project="default",
            clock=lambda: NOW,
        )
        assert quarterly.evidence
        assert quarterly.evidence[0].citation.source_locator.label == "guide.docx"
        assert quarterly.evidence[0].citation.heading == "Paragraph 1"

        forecast = answer(
            repository,
            "forecast revenue",
            principal=Principal("lee"),
            project="default",
            clock=lambda: NOW,
        )
        assert forecast.claims
        assert any(
            citation.heading == "Sheet 1: Forecast / Row 1"
            for claim in forecast.claims
            for citation in claim.citations
        )

        roadmap = answer(
            repository,
            "roadmap release readiness",
            principal=Principal("lee"),
            project="default",
            clock=lambda: NOW,
        )
        assert roadmap.claims
        assert any(
            citation.heading == "Slide 1 / Body 1"
            for claim in roadmap.claims
            for citation in claim.citations
        )


def test_office_and_markdown_conflict_keeps_both_citations(tmp_path) -> None:
    connector = _connector(
        tmp_path,
        {
            "office.docx": _docx_bytes("Launch window is 30 minutes."),
            "policy.md": b"# Policy\n\nLaunch window is 90 minutes.",
        },
        include=("*.docx", "*.md"),
    )

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        _sync_connector(connector, repository, root_filter=None, sync_timestamp=NOW)
        result = answer(
            repository,
            "launch window minutes",
            principal=Principal("lee"),
            project="default",
            clock=lambda: NOW,
        )

    assert len(result.claims) == 2
    assert len(result.conflicts) == 1
    labels = {
        citation.source_locator.label
        for claim in result.claims
        for citation in claim.citations
    }
    assert labels == {"office.docx", "policy.md"}


def test_unrelated_office_absence_text_does_not_create_an_authoritative_absence(
    tmp_path,
) -> None:
    connector = _connector(
        tmp_path,
        {
            "answer.md": (
                b"# Harbor readiness\n\nHarbor readiness requires two reviews."
            ),
            "unrelated.docx": _docx_bytes("The legacy inventory does not exist."),
        },
        include=("*.docx", "*.md"),
    )

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        _sync_connector(connector, repository, root_filter=None, sync_timestamp=NOW)
        result = answer(
            repository,
            "What does harbor readiness require?",
            principal=Principal("lee"),
            project="default",
            clock=lambda: NOW,
        )

    assert result.absence is None
    assert any("requires two reviews" in claim.text for claim in result.claims)


def test_duplicate_root_protection_applies_to_docx(tmp_path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (inner / "shared.docx").write_bytes(_docx_bytes("One governed Office source."))
    config = tmp_path / "sources.toml"
    config.write_text(f"""
schema = 1

[roots.outer]
path = "{outer.as_posix()}"
owner = "lee"
include = ["**/*.docx"]

[roots.inner]
path = "{inner.as_posix()}"
owner = "lee"
include = ["**/*.docx"]
""")
    connector = LocalFilesConnector.from_config(config)

    report = connector.discover_report()

    assert [obj.source_object_id for obj in report.objects] == ["inner:shared.docx"]


def test_nested_docx_table_text_is_retained(tmp_path) -> None:
    document = DocxDocument()
    outer_table = document.add_table(rows=1, cols=1)
    outer_cell = outer_table.cell(0, 0)
    outer_cell.text = "Outer cell text"
    nested_table = outer_cell.add_table(rows=1, cols=1)
    nested_table.cell(0, 0).text = "Nested cell text"
    payload = BytesIO()
    document.save(payload)

    connector = _connector(
        tmp_path,
        {"nested.docx": payload.getvalue()},
        include=("*.docx",),
    )
    fetched = connector.fetch("notes:nested.docx")

    assert "Outer cell text" in fetched.content
    assert "Nested cell text" in fetched.content


@pytest.mark.parametrize("prefix", ["#", "##", "###", "####", "#####", "######"])
def test_office_body_heading_syntax_cannot_create_fake_citations(
    tmp_path, prefix
) -> None:
    docx_connector = _connector(
        tmp_path / "docx",
        {"body.docx": _docx_bytes(f"{prefix} user supplied text")},
        include=("*.docx",),
    )
    docx = docx_connector.fetch("notes:body.docx")
    docx_chunks = chunk_document(
        docx.content,
        item_id=KnowledgeItemId("local_files", "notes:body.docx"),
        project=DEFAULT_PROJECT,
        document_type=DocumentType.DOCX,
    )

    pptx_connector = _connector(
        tmp_path / "pptx",
        {"body.pptx": _pptx_bytes(f"{prefix} user supplied text")},
        include=("*.pptx",),
    )
    pptx = pptx_connector.fetch("notes:body.pptx")
    pptx_chunks = chunk_document(
        pptx.content,
        item_id=KnowledgeItemId("local_files", "notes:body.pptx"),
        project=DEFAULT_PROJECT,
        document_type=DocumentType.PPTX,
    )

    assert f"\\{prefix} user supplied text" in docx.content
    assert f"\\{prefix} user supplied text" in pptx.content
    assert all(chunk.heading != "user supplied text" for chunk in docx_chunks)
    assert all(chunk.heading != "user supplied text" for chunk in pptx_chunks)
