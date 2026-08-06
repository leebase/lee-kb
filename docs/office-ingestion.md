# Office Ingestion

Office documents enter through the existing `LocalFilesConnector` and the
existing `main._sync_connector()` ingestion path. There is no Office-specific
repository, search, permission, or answer path.

## Approved Dependencies

The bundled runtime capability declares:

| Format | Package | Version |
|---|---|---:|
| `.docx` | `python-docx` | `1.2.0` |
| `.xlsx` | `openpyxl` | `3.1.5` |
| `.pptx` | `python-pptx` | `1.0.2` |

The packages are used only for deterministic parsing. They do not execute
macros, formulas, links, or embedded objects. `python-pptx`'s transitive
`XlsxWriter` requirement is installed by the package manager; it is not used
by lee-kb at ingestion time.

## Parser Contract

`src/lee_kb/connectors/office.py` returns a `ParsedDocument` containing
normalized text and an optional safe metadata title. The local connector's
`FormatHandler` retains its text-only `decode` attribute and adds a structured
`parse` callable. Office text is normalized into deterministic headings before
the common `OFFICE_CHUNKER_ID` chunker runs.

- DOCX preserves body order, heading levels, non-empty paragraphs, table order,
  row numbers, and cell numbers, including nested table cells. A safe
  core-properties title is retained. User body text that begins with Markdown
  heading syntax is escaped before chunking, so it remains searchable without
  becoming a citation heading.
- XLSX records workbook title when safe, worksheet order and names, non-empty
  cells, row/cell references, formulas, and cached displayed values when
  available. Formulas are read, never evaluated. External links and embedded
  package parts are rejected.
- PPTX records slide order, titles, text-bearing body shapes, table rows, and
  speaker notes. Speaker notes are intentionally supported, and body/note text
  that looks like a Markdown heading is escaped before chunking. Visual OCR,
  images, charts with embedded workbooks, and other embedded objects are not.

Representative citation labels are stable normalized references rather than
guesses about byte offsets:

```text
guide.docx       heading = "Paragraph 1"
forecast.xlsx    heading = "Sheet 1: Forecast / Row 4"
roadmap.pptx     heading = "Slide 1 / Body 1"
```

The source root and relative path remain in `SourceLocator.label`; document
type, authority, trust, source timestamp, raw artifact hash, chunk hash, and
receipt fields remain the same fields used for Markdown.

## Discovery Scope

Only six roots with Office files gained narrow extension patterns in the
deployed `knowledge/sources.toml`:

- `factory`: `consulting/*.xlsx`
- `agent-orch`: `*.pptx`
- `pr-business`: `docs/**/*.docx`
- `jobsearch`: `**/*.docx`
- `ai-employee-book`: `.docx` variants of its existing
  `Building Autonomous AI Employees` include paths only
- `tviq`: `docs/**/*.pptx`, `projects/**/*.docx`,
  `snowflakeintelligence/**/*.docx`, `ingestion-template/**/*.xlsx`, and
  `log-project/**/*.xlsx`

Existing generated/output and temporary protections remain active. In
particular, `tviq` keeps `outputs/**` excluded and excludes the generated
`log-project/already_processed/**` area. Format-specific global denies protect
Office lock files, AppleDouble files, and hidden Office files. No wildcard for
general binary files was added.

## Failure Semantics

`ReadFailureKind` is safe to report and contains no raw exception, document
content, or host path:

- `unsupported`: encrypted/password-protected packages, macros, embedded
  objects/media, external links, or another deliberately unsupported package
  feature;
- `unreadable`: bytes cannot be read or decoded;
- `malformed`: the archive or parser input is invalid;
- `temporarily_inaccessible`: a source disappears or cannot be accessed during
  a pass;
- `deleted`: not a parser failure; a discovered object missing on the next
  complete discovery pass becomes the existing tombstone journal event.

Discovery accounts Office candidates outside include scope and protected by
exclusions separately from handler failures. A discovery read failure keeps
its source ID out of deletion diffing, so temporary access failure cannot be
misreported as deletion. The public `list_changes()` contract uses the same
failure-aware diff, including blocked root/subtree prefixes. A fetch/parser
failure leaves the prior projection and cursor unchanged for retry.

When a sync is scoped to one configured root, overlapping files remain owned by
the deepest matching root. The report and CLI count candidates claimed by a
different, more specific root instead of silently omitting them or duplicating
their source identity.

## Real Corpus Accounting

The direct live inventory contains 39 unique Office files. The first clean
post-handler sync accounted for all of them without exporting content:

| Classification | `.docx` | `.xlsx` | `.pptx` | Total |
|---|---:|---:|---:|---:|
| Indexed | 7 | 3 | 0 | 10 |
| Unsupported embedded content | 4 | 0 | 1 | 5 |
| Git-ignored | 0 | 0 | 1 | 1 |
| Existing generated/excluded scope | 0 | 2 | 0 | 2 |
| Deliberately outside `ai-employee-book` include scope | 21 | 0 | 0 | 21 |
| **Total** | **32** | **5** | **2** | **39** |

The indexed 10 are persisted as normal governed items and chunks. The other
29 are visible as explicit inventory, exclusion, or failure classifications;
none is silently absent from the accounting.
