"""Safe, deterministic extraction for the supported Office formats.

The parsers return normalized Markdown-like text.  The common chunker then
turns headings into stable citation references, so Office content follows the
same repository, retrieval, permission, and receipt path as text documents.
Only textual package parts are supported in this slice.  Embedded media,
objects, macros, external links, encrypted packages, and malformed archives
are rejected before any content is returned.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass
from io import BytesIO

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pptx import Presentation

from .base import ConnectorReadError, ReadFailureKind

__all__ = [
    "ParsedDocument",
    "OfficeParseError",
    "parse_docx",
    "parse_pptx",
    "parse_xlsx",
]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Normalized text plus safe source metadata extracted from one artifact."""

    content: str
    title: str | None = None


class OfficeParseError(ConnectorReadError):
    """A known Office parsing failure with a safe public classification."""


_OLE_COMPOUND_FILE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|[/\\])")
_EXTERNAL_RELATION = re.compile(rb"TargetMode\s*=\s*['\"]External['\"]", re.IGNORECASE)
_HEADING_STYLE = re.compile(r"(?:heading|title)\s*([1-6])?", re.IGNORECASE)
_UNSUPPORTED_PARTS = (
    "media/",
    "embeddings/",
    "activex/",
    "externallinks/",
    "vbaproject",
    "oleobject",
    "customui",
)
_NOTE_PLACEHOLDERS = frozenset(
    {
        "click to add notes",
        "click to add text",
        "slide image",
        "slide number",
    }
)


def _parse_error(kind: ReadFailureKind, detail: str) -> OfficeParseError:
    return OfficeParseError(detail, kind=kind)


def _validate_package(raw: bytes, extension: str) -> None:
    if not isinstance(raw, bytes):
        raise TypeError("Office parser input must be bytes")
    if raw.startswith(_OLE_COMPOUND_FILE_MAGIC):
        raise _parse_error(
            ReadFailureKind.UNSUPPORTED,
            f"password-protected or encrypted {extension} package is unsupported",
        )

    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            names = tuple(
                info.filename.replace("\\", "/") for info in archive.infolist()
            )
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise _parse_error(
            ReadFailureKind.MALFORMED,
            f"malformed {extension} package",
        ) from error

    unsupported = any(
        any(part.lower() in name.lower() for part in _UNSUPPORTED_PARTS)
        for name in names
    )
    if unsupported:
        raise _parse_error(
            ReadFailureKind.UNSUPPORTED,
            f"unsupported embedded content in {extension} package",
        )

    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            has_external_relation = any(
                name.lower().endswith(".rels")
                and _EXTERNAL_RELATION.search(archive.read(name))
                for name in names
            )
    except (OSError, KeyError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        raise _parse_error(
            ReadFailureKind.MALFORMED,
            f"malformed {extension} relationships",
        ) from error
    if has_external_relation:
        raise _parse_error(
            ReadFailureKind.UNSUPPORTED,
            f"external relationships in {extension} package are unsupported",
        )

    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            if archive.testzip() is not None:
                raise _parse_error(
                    ReadFailureKind.MALFORMED,
                    f"corrupt {extension} package member",
                )
    except OfficeParseError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        raise _parse_error(
            ReadFailureKind.MALFORMED,
            f"malformed {extension} package",
        ) from error


def _clean_text(value: object) -> str:
    if value is None or isinstance(value, bytes):
        return ""
    text = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return "".join(
        character
        for character in text
        if character in "\t\n" or unicodedata.category(character) not in {"Cc", "Cf"}
    ).strip()


def _clean_heading(value: object) -> str:
    return " ".join(_clean_text(value).split())


_ATX_HEADING_LINE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+")


def _escape_user_headings(value: object) -> str:
    """Keep user text from becoming Office citation structure."""
    text = _clean_text(value)
    return "\n".join(
        f"\\{line}" if _ATX_HEADING_LINE.match(line) else line
        for line in text.splitlines()
    )


def _safe_metadata_title(value: object) -> str | None:
    title = _clean_heading(value)
    if not title or _ABSOLUTE_PATH.match(title):
        return None
    return title[:500]


def _join_parts(parts: list[str]) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _heading(level: int, text: str) -> str:
    return f"{'#' * max(1, min(level, 6))} {text}"


def _iter_docx_blocks(element):
    """Yield supported block elements through transparent OOXML wrappers."""
    transparent = {"body", "sdt", "sdtContent", "customXml", "ins", "del"}
    for child in element.iterchildren():
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name in {"p", "tbl"}:
            yield child
        elif local_name in transparent:
            yield from _iter_docx_blocks(child)


def _docx_cell_text(cell) -> str:
    parts: list[str] = []
    for child in _iter_docx_blocks(cell._tc):
        if child.tag.endswith("}p"):
            text = _clean_text(Paragraph(child, cell).text)
            if text:
                parts.append(text)
            continue

        table = Table(child, cell)
        for row in table.rows:
            cells = []
            for nested_cell in row.cells:
                text = _docx_cell_text(nested_cell)
                if text:
                    cells.append(text)
            if cells:
                parts.append(" | ".join(cells))

    if parts:
        return _clean_text(" ".join(parts))
    return _clean_text(
        "".join(
            node.text or ""
            for node in cell._tc.iter()
            if node.tag.rsplit("}", 1)[-1] == "t"
        )
    )


def parse_docx(raw: bytes) -> ParsedDocument:
    """Extract headings, paragraphs, and table rows in document order."""
    _validate_package(raw, ".docx")
    try:
        document = Document(BytesIO(raw))
        parts: list[str] = []
        paragraph_number = 0
        table_number = 0

        for child in _iter_docx_blocks(document.element.body):
            if child.tag.endswith("}p"):
                paragraph = Paragraph(child, document)
                text = _clean_text(paragraph.text)
                if not text:
                    continue
                style_name = ""
                try:
                    style_name = str(paragraph.style.name or "")
                except (AttributeError, ValueError):
                    pass
                style_match = _HEADING_STYLE.search(style_name)
                if style_match:
                    level = int(style_match.group(1) or "1")
                    parts.append(_heading(level, _clean_heading(text)))
                else:
                    paragraph_number += 1
                    parts.append(
                        f"{_heading(3, f'Paragraph {paragraph_number}')}\n"
                        f"{_escape_user_headings(text)}"
                    )
            elif child.tag.endswith("}tbl"):
                table_number += 1
                table = Table(child, document)
                for row_number, row in enumerate(table.rows, start=1):
                    cells = []
                    for cell_number, cell in enumerate(row.cells, start=1):
                        cell_text = " ".join(_docx_cell_text(cell).split())
                        if cell_text:
                            cells.append(f"Cell {cell_number}: {cell_text}")
                    if cells:
                        row_heading = _heading(
                            3, f"Table {table_number} / Row {row_number}"
                        )
                        parts.append(f"{row_heading}\n" + " | ".join(cells))

        title = _safe_metadata_title(document.core_properties.title)
        return ParsedDocument(content=_join_parts(parts), title=title)
    except OfficeParseError:
        raise
    except Exception as error:
        raise _parse_error(
            ReadFailureKind.MALFORMED, "malformed .docx document"
        ) from error


def _xlsx_cell_text(formula_value: object, displayed_value: object) -> str:
    formula = _clean_text(formula_value)
    displayed = _clean_text(displayed_value)
    if not formula and not displayed:
        return ""
    if formula.startswith("="):
        if displayed:
            return f"{displayed} (formula: {formula})"
        return f"(formula: {formula}; displayed value unavailable)"
    return displayed or formula


def parse_xlsx(raw: bytes) -> ParsedDocument:
    """Extract non-empty worksheet cells as stable sheet/row/cell sections."""
    _validate_package(raw, ".xlsx")
    formula_workbook = None
    displayed_workbook = None
    try:
        formula_workbook = load_workbook(
            BytesIO(raw), read_only=True, data_only=False, keep_links=False
        )
        displayed_workbook = load_workbook(
            BytesIO(raw), read_only=True, data_only=True, keep_links=False
        )
        title = _safe_metadata_title(formula_workbook.properties.title)
        parts = [_heading(1, f"Workbook: {title}" if title else "Workbook")]

        for sheet_number, formula_sheet in enumerate(
            formula_workbook.worksheets, start=1
        ):
            displayed_sheet = displayed_workbook[formula_sheet.title]
            sheet_name = _clean_heading(formula_sheet.title) or f"Sheet {sheet_number}"
            parts.append(_heading(2, f"Sheet {sheet_number}: {sheet_name}"))
            displayed_rows = displayed_sheet.iter_rows()
            for row_index, row in enumerate(formula_sheet.iter_rows(), start=1):
                displayed_row = next(displayed_rows, ())
                row_number = getattr(row[0], "row", None) or row_index
                cell_parts = []
                for column_index, formula_cell in enumerate(row, start=1):
                    displayed_cell = (
                        displayed_row[column_index - 1]
                        if column_index <= len(displayed_row)
                        else None
                    )
                    column_number = (
                        getattr(formula_cell, "column", None) or column_index
                    )
                    coordinate = f"{get_column_letter(column_number)}{row_number}"
                    cell_text = _xlsx_cell_text(
                        formula_cell.value,
                        displayed_cell.value if displayed_cell is not None else None,
                    )
                    if cell_text:
                        cell_parts.append(f"{coordinate}: {cell_text}")
                if cell_parts:
                    row_heading = _heading(
                        3, f"Sheet {sheet_number}: {sheet_name} / Row {row_number}"
                    )
                    parts.append(f"{row_heading}\n" + " | ".join(cell_parts))
        return ParsedDocument(content=_join_parts(parts), title=title)
    except OfficeParseError:
        raise
    except Exception as error:
        raise _parse_error(
            ReadFailureKind.MALFORMED, "malformed .xlsx document"
        ) from error
    finally:
        if formula_workbook is not None:
            formula_workbook.close()
        if displayed_workbook is not None:
            displayed_workbook.close()


def _shape_text(shape: object) -> str:
    if not getattr(shape, "has_text_frame", False):
        return ""
    return _escape_user_headings(getattr(shape, "text", ""))


def _iter_shapes(shapes):
    """Yield text-bearing shapes through grouped-shape containers."""
    for shape in shapes:
        yield shape
        nested = getattr(shape, "shapes", None)
        if nested is not None:
            yield from _iter_shapes(nested)


def _slide_notes(slide: object) -> str:
    try:
        notes_slide = slide.notes_slide
    except Exception:
        return ""
    notes = []
    for shape in _iter_shapes(notes_slide.shapes):
        text = _shape_text(shape)
        if text and text.casefold() not in _NOTE_PLACEHOLDERS:
            notes.append(text)
    return "\n".join(notes).strip()


def parse_pptx(raw: bytes) -> ParsedDocument:
    """Extract slide titles, body text, tables, and speaker notes in order."""
    _validate_package(raw, ".pptx")
    try:
        presentation = Presentation(BytesIO(raw))
        title = _safe_metadata_title(presentation.core_properties.title)
        parts: list[str] = []
        for slide_number, slide in enumerate(presentation.slides, start=1):
            title_shape = slide.shapes.title
            title_shape_id = getattr(title_shape, "shape_id", None)
            slide_title = _clean_heading(title_shape.text) if title_shape else ""
            heading = f"Slide {slide_number}"
            if slide_title:
                heading += f": {slide_title}"
            parts.append(_heading(1, heading))

            body_number = 0
            table_number = 0
            for shape in _iter_shapes(slide.shapes):
                if title_shape_id is not None and shape.shape_id == title_shape_id:
                    continue
                text = _shape_text(shape)
                if text:
                    body_number += 1
                    parts.append(
                        f"{_heading(3, f'Slide {slide_number} / Body {body_number}')}\n"
                        + text
                    )
                if getattr(shape, "has_table", False):
                    table_number += 1
                    table = shape.table
                    for row_number, row in enumerate(table.rows, start=1):
                        cells = []
                        for cell_number, cell in enumerate(row.cells, start=1):
                            cell_text = " ".join(_clean_text(cell.text).split())
                            if cell_text:
                                cells.append(f"Cell {cell_number}: {cell_text}")
                        if cells:
                            row_heading = _heading(
                                3,
                                f"Slide {slide_number} / Table {table_number} "
                                f"/ Row {row_number}",
                            )
                            parts.append(f"{row_heading}\n" + " | ".join(cells))

            notes = _slide_notes(slide)
            if notes:
                parts.append(
                    f"{_heading(3, f'Slide {slide_number} / Speaker notes')}\n{notes}"
                )

        return ParsedDocument(content=_join_parts(parts), title=title)
    except OfficeParseError:
        raise
    except Exception as error:
        raise _parse_error(
            ReadFailureKind.MALFORMED, "malformed .pptx document"
        ) from error
