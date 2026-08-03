"""Deterministic document chunking for the first retrieval slice.

Markdown is split at ATX headings so a section and its heading stay together.
Plain text is split at blank lines.  Both strategies preserve source order and
assign zero-based ordinals after empty spans have been discarded.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import (
    Chunk,
    ChunkId,
    DocumentType,
    KnowledgeItemId,
    compute_content_hash,
)

__all__ = [
    "MARKDOWN_CHUNKER_ID",
    "PLAIN_TEXT_CHUNKER_ID",
    "chunk_document",
    "chunk_markdown",
    "chunk_plain_text",
]

MARKDOWN_CHUNKER_ID = "markdown-atx-v1:1"
PLAIN_TEXT_CHUNKER_ID = "plain-text-paragraph-v1:1"

_ATX_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(?P<title>.*?)(?:[ \t]+#+[ \t]*)?$")
_FENCE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")
_TOKEN = re.compile(r"\w+", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    heading: str | None = None


def chunk_document(
    text: str,
    *,
    item_id: KnowledgeItemId,
    project: str,
    document_type: DocumentType,
) -> tuple[Chunk, ...]:
    """Chunk normalized document text using its declared document type.

    Markdown uses heading sections.  Every other text-bearing document type
    falls back to deterministic paragraph chunks; format-specific extraction
    can introduce a separate versioned chunker later.
    """
    if not isinstance(document_type, DocumentType):
        raise TypeError("document_type must be a DocumentType")
    if document_type is DocumentType.MARKDOWN:
        return chunk_markdown(text, item_id=item_id, project=project)
    return chunk_plain_text(text, item_id=item_id, project=project)


def chunk_markdown(
    text: str,
    *,
    item_id: KnowledgeItemId,
    project: str,
) -> tuple[Chunk, ...]:
    """Split Markdown into stable, heading-aware source slices.

    ATX-looking lines inside fenced code blocks are content, not headings.
    Repeated heading labels retain a zero-based occurrence number so citations
    can distinguish them without affecting positional chunk identity.
    """
    _validate_inputs(text, item_id, project)
    headings: list[tuple[int, str]] = []
    fence_character: str | None = None
    fence_length = 0
    offset = 0

    for line in text.splitlines(keepends=True):
        visible_line = line.rstrip("\r\n")
        fence_match = _FENCE.match(visible_line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            offset += len(line)
            continue

        if fence_character is None:
            heading_match = _ATX_HEADING.match(visible_line)
            if heading_match is not None:
                title = heading_match.group("title").strip()
                if title:
                    headings.append((offset, title))
        offset += len(line)

    spans: list[_Span] = []
    if not headings:
        spans.append(_Span(0, len(text)))
    else:
        first_heading_start = headings[0][0]
        if text[:first_heading_start].strip():
            spans.append(_Span(0, first_heading_start))
        for index, (start, heading) in enumerate(headings):
            end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
            spans.append(_Span(start, end, heading))

    return _build_chunks(
        text,
        spans,
        item_id=item_id,
        project=project,
        chunker_id=MARKDOWN_CHUNKER_ID,
    )


def chunk_plain_text(
    text: str,
    *,
    item_id: KnowledgeItemId,
    project: str,
) -> tuple[Chunk, ...]:
    """Split plain text into stable paragraphs separated by blank lines."""
    _validate_inputs(text, item_id, project)
    spans: list[_Span] = []
    paragraph_start: int | None = None
    offset = 0

    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        if line.strip():
            if paragraph_start is None:
                paragraph_start = offset
        elif paragraph_start is not None:
            spans.append(_Span(paragraph_start, offset))
            paragraph_start = None
        offset = line_end

    # ``splitlines(keepends=True)`` covers every character except that an empty
    # string has no lines.  Use len(text) so a final line without a newline is
    # included in its paragraph.
    if paragraph_start is not None:
        spans.append(_Span(paragraph_start, len(text)))

    return _build_chunks(
        text,
        spans,
        item_id=item_id,
        project=project,
        chunker_id=PLAIN_TEXT_CHUNKER_ID,
    )


def _validate_inputs(text: str, item_id: KnowledgeItemId, project: str) -> None:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(item_id, KnowledgeItemId):
        raise TypeError("item_id must be a KnowledgeItemId")
    if not isinstance(project, str) or not project.strip():
        raise ValueError("project must be a non-empty string")


def _build_chunks(
    source: str,
    spans: Iterable[_Span],
    *,
    item_id: KnowledgeItemId,
    project: str,
    chunker_id: str,
) -> tuple[Chunk, ...]:
    chunks: list[Chunk] = []
    heading_occurrences: dict[str, int] = {}

    for span in spans:
        raw_text = source[span.start : span.end]
        leading = len(raw_text) - len(raw_text.lstrip())
        chunk_text = raw_text.strip()
        if not chunk_text:
            continue

        occurrence = 0
        if span.heading is not None:
            occurrence = heading_occurrences.get(span.heading, 0)
            heading_occurrences[span.heading] = occurrence + 1

        ordinal = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=ChunkId(
                    item_id=item_id,
                    chunk_ordinal=ordinal,
                    content_hash=compute_content_hash(chunk_text),
                ),
                project=project,
                text=chunk_text,
                chunker_id=chunker_id,
                heading=span.heading,
                occurrence=occurrence,
                start_offset=len(source[: span.start + leading].encode("utf-8")),
                token_count=len(_TOKEN.findall(chunk_text)),
            )
        )
    return tuple(chunks)
