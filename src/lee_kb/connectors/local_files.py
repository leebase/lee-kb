"""Local-file connector: the first-release connector for lee-kb.

Reads a ``sources.toml`` configuration compatible with the Employee Zero
``knowledge/sources.toml`` shape (see
``research/employee-zero-kb-reference.md``): a table of named roots, each
with a filesystem ``path``, an include glob list, an optional exclude glob
list, and declared ``authority``/``trust``/``owner`` metadata. Matching is
default-deny: a file is only discovered if it matches at least one
``include`` pattern and no ``exclude`` pattern.

Configuration shape::

    schema = 1

    [roots.notes]
    path = "/home/lee/notes"
    owner = "lee@leebase.com"
    include = ["*.md", "*.txt"]
    exclude = [".git/**", "tmp/**"]
    authority = "canonical"   # "canonical" | "derived", default "derived"
    trust = "human_authored"  # "human_authored" | "curated" | "model_produced",
                               # default "curated"
    visibility = "private"    # "private" | "project" | "public", default "private"
    project = "default"       # default DEFAULT_PROJECT
    required = true           # default true; missing path fails health()

Format handlers
----------------

Discovery and fetch only recognize file extensions registered in
``FORMAT_HANDLERS``. The v1 registry covers Markdown and plain text only;
office formats (``docx``, ``xlsx``, ``pptx``) are deliberately not
registered here even though :class:`lee_kb.contracts.DocumentType`
enumerates them — the parsing libraries they need are new runtime
dependencies and are deferred pending explicit approval (see Open Question 4
in ``docs/sprint-1-contracts.md``). Extend the registry by adding a
``FormatHandler`` to ``FORMAT_HANDLERS`` keyed by lowercase file suffix
(including the leading dot); a handler needs only a ``document_type`` and a
``decode`` callable from raw bytes to text.

Change detection
----------------

There is no native change feed for a filesystem, so
:meth:`LocalFilesConnector.list_changes` takes a snapshot cursor: a JSON
object mapping ``source_object_id`` to its last-known ``content_hash``,
produced by :meth:`LocalFilesConnector.checkpoint`. Diffing the current
:meth:`LocalFilesConnector.discover` result against that snapshot yields
created, updated, and deleted objects without depending on mtimes, which are
unreliable across copies, clones, and restores.

Nested roots
------------

Configured roots may overlap, but one resolved file is claimed by exactly one
root. When a file matches more than one root, the most specific (deepest)
resolved root wins; equal-depth ties are resolved by root name. This keeps
``source_object_id`` stable across discovery passes and prevents one source
document from producing independently citable duplicate evidence. Nested-root
detection is reported by :meth:`LocalFilesConnector.health`.

Discovery reporting
--------------------

A document a user expects to be searchable must never disappear without a
count. :meth:`LocalFilesConnector.discover` returns only the objects that
made it through; :meth:`LocalFilesConnector.discover_report` returns the
same objects plus every reason something did not, matching the Employee
Zero reference (``research/employee-zero-kb-reference.md``, "Build
Pipeline"):

- ``unhandled_formats`` -- a candidate matched a root's include patterns but
  no :data:`FORMAT_HANDLERS` entry exists for its lowercase suffix, counted
  per suffix. This is how the size of the office-format hole is measured
  before parsing dependencies are approved.
- ``git_ignored`` -- a candidate git reports as ignored, excluded from the
  projection like the reference build. Resolved per root with one batched
  ``git check-ignore -z --stdin`` call rather than one process per file.
- ``git_unresolved`` -- a candidate whose git-ignore status could not be
  determined (the root is not inside a git repository, git is unavailable,
  or an ancestor ignore rule suppresses the configured root itself). Never
  excluded on this basis alone -- resolution failure degrades to "count it,
  don't drop it," not a crash.

Token-shaped secret content (credentials that must never enter the
projection even when the file itself is otherwise indexable) is a separate,
content-level check applied at sync time; see
:func:`contains_token_shaped_secret`.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import tomllib

from ..contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChangeType,
    DocumentType,
    PermissionSet,
    SourceLocator,
    Trust,
    Visibility,
    compute_content_hash,
)
from .base import (
    Connector,
    ConnectorConfigError,
    ConnectorReadError,
    FetchedDocument,
    HealthStatus,
    ObjectChange,
    SourceObject,
)

__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "FormatHandler",
    "FORMAT_HANDLERS",
    "GLOBAL_DEFAULT_DENY",
    "OverrideConfig",
    "RootConfig",
    "DiscoveryReport",
    "contains_token_shaped_secret",
    "load_config",
    "LocalFilesConnector",
]

#: Version of the sources.toml shape this loader accepts.
CONFIG_SCHEMA_VERSION = 1

_AUTHORITY_BY_VALUE = {member.value: member for member in Authority}
_TRUST_BY_VALUE = {member.value: member for member in Trust}
_VISIBILITY_BY_VALUE = {member.value: member for member in Visibility}

#: Reference-wide exclusions. A root cannot opt these paths back in.
GLOBAL_DEFAULT_DENY = (
    "code-reviews/**",
    ".agent-orch/**",
    ".agent-orch-scratch/**",
    "artifacts/**",
    "tmp/**",
    ".kb/**",
    ".git/**",
)

#: Small, conservative, documented pattern set for content that must never
#: enter the projection unexamined -- mirrors the unconditional content scan
#: in the Employee Zero reference (private keys, `api_key=`, `ghp_`, `sk-`,
#: `xox[baprs]-`). Deliberately narrow: this is a credential-shaped-string
#: tripwire, not general secret scanning, so it stays cheap to reason about
#: and does not flood the sync summary with false positives.
_TOKEN_SHAPED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
)


def contains_token_shaped_secret(content: str) -> bool:
    """Return True if ``content`` contains a token-shaped secret pattern.

    Applied at sync time before content is chunked and indexed, so
    credentials in Lee's real repositories do not enter the projection.
    """
    return any(pattern.search(content) for pattern in _TOKEN_SHAPED_PATTERNS)


_TOP_LEVEL_KEYS = frozenset({"schema", "roots", "owner", "database", "workspace_root"})
_ROOT_KEYS = frozenset(
    {
        "path",
        "owner",
        "include",
        "exclude",
        "authority",
        "trust",
        "visibility",
        "project",
        "required",
        "external",
        "overrides",
    }
)
_OVERRIDE_KEYS = frozenset({"pattern", "authority", "trust"})


@dataclass(frozen=True, slots=True)
class FormatHandler:
    """Decodes one file format into normalized text for a document type."""

    document_type: DocumentType
    decode: Callable[[bytes], str]


def _decode_text(raw: bytes) -> str:
    return raw.decode("utf-8")


#: Registered file-format handlers, keyed by lowercase suffix (with dot).
#: Add entries here to support new text-like formats; do not add office
#: formats without approval (see the module docstring).
FORMAT_HANDLERS: dict[str, FormatHandler] = {
    ".md": FormatHandler(DocumentType.MARKDOWN, _decode_text),
    ".markdown": FormatHandler(DocumentType.MARKDOWN, _decode_text),
    ".txt": FormatHandler(DocumentType.PLAIN_TEXT, _decode_text),
    ".text": FormatHandler(DocumentType.PLAIN_TEXT, _decode_text),
}


@dataclass(frozen=True, slots=True)
class OverrideConfig:
    """First-match metadata override for a path within a root."""

    pattern: str
    authority: Authority | None = None
    trust: Trust | None = None


@dataclass(frozen=True, slots=True)
class RootConfig:
    """One configured source root."""

    name: str
    path: Path
    owner: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    authority: Authority = Authority.DERIVED
    trust: Trust = Trust.CURATED
    visibility: Visibility = Visibility.PRIVATE
    project: str = DEFAULT_PROJECT
    required: bool = True
    external: bool = False
    overrides: tuple[OverrideConfig, ...] = ()

    def metadata_for(self, relative_posix: str) -> tuple[Authority, Trust]:
        """Return declared metadata after applying the first matching override."""
        for override in self.overrides:
            if _glob_match(relative_posix, override.pattern):
                return (
                    override.authority or self.authority,
                    override.trust or self.trust,
                )
        return self.authority, self.trust


def load_config(
    config_path: str | Path, *, workspace_root: str | Path | None = None
) -> tuple[RootConfig, ...]:
    """Parse a sources.toml file into root configurations.

    Raises :class:`ConnectorConfigError` on a missing schema declaration, an
    unsupported schema version, or a root missing a required field.
    """
    config_path = Path(config_path)
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConnectorConfigError(f"config file not found: {config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConnectorConfigError(f"invalid TOML in {config_path}: {error}") from error

    unknown_keys = _collect_unknown_keys(data)
    if unknown_keys:
        raise ConnectorConfigError(
            "unsupported configuration keys: " + ", ".join(unknown_keys)
        )

    schema = data.get("schema")
    if schema != CONFIG_SCHEMA_VERSION:
        raise ConnectorConfigError(
            f"unsupported sources.toml schema {schema!r}; "
            f"expected {CONFIG_SCHEMA_VERSION}"
        )

    raw_roots = data.get("roots")
    if not isinstance(raw_roots, dict) or not raw_roots:
        raise ConnectorConfigError("sources.toml must declare at least one root")

    root_base = _resolve_workspace_root(
        config_path, data.get("workspace_root"), workspace_root
    )

    roots = []
    for name, raw_root in raw_roots.items():
        roots.append(_parse_root(name, raw_root, root_base))
    return tuple(roots)


def _collect_unknown_keys(data: dict) -> list[str]:
    unknown = [
        f"top-level {key!r}" for key in sorted(set(data).difference(_TOP_LEVEL_KEYS))
    ]
    raw_roots = data.get("roots")
    if not isinstance(raw_roots, dict):
        return unknown
    for name, raw_root in raw_roots.items():
        if not isinstance(raw_root, dict):
            continue
        unknown.extend(
            f"root {name!r} {key!r}"
            for key in sorted(set(raw_root).difference(_ROOT_KEYS))
        )
        overrides = raw_root.get("overrides")
        if not isinstance(overrides, list):
            continue
        for index, override in enumerate(overrides):
            if not isinstance(override, dict):
                continue
            unknown.extend(
                f"root {name!r} override {index} {key!r}"
                for key in sorted(set(override).difference(_OVERRIDE_KEYS))
            )
    return unknown


def _resolve_workspace_root(
    config_path: Path,
    configured: object,
    explicit: str | Path | None,
) -> Path:
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        return candidate.resolve()
    if configured is None:
        return config_path.parent.resolve()
    if not isinstance(configured, str) or not configured.strip():
        raise ConnectorConfigError("workspace_root must be a non-empty path string")
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve()


def _parse_root(name: str, raw: object, root_base: Path) -> RootConfig:
    if not isinstance(raw, dict):
        raise ConnectorConfigError(f"root {name!r} must be a table")

    raw_path = raw.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConnectorConfigError(f"root {name!r} is missing a non-empty path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = root_base / path
    path = path.resolve()

    owner = raw.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise ConnectorConfigError(f"root {name!r} is missing a non-empty owner")

    include = raw.get("include")
    if (
        not isinstance(include, list)
        or not include
        or not all(isinstance(pattern, str) and pattern for pattern in include)
    ):
        raise ConnectorConfigError(
            f"root {name!r} must declare a non-empty include pattern list"
        )

    exclude = raw.get("exclude", [])
    if not isinstance(exclude, list) or not all(
        isinstance(pattern, str) and pattern for pattern in exclude
    ):
        raise ConnectorConfigError(f"root {name!r} has an invalid exclude list")

    authority = _lookup(
        raw, f"root {name!r}", "authority", _AUTHORITY_BY_VALUE, Authority.DERIVED
    )
    trust = _lookup(raw, f"root {name!r}", "trust", _TRUST_BY_VALUE, Trust.CURATED)
    visibility = _lookup(
        raw,
        f"root {name!r}",
        "visibility",
        _VISIBILITY_BY_VALUE,
        Visibility.PRIVATE,
    )

    project = raw.get("project", DEFAULT_PROJECT)
    if not isinstance(project, str) or not project.strip():
        raise ConnectorConfigError(f"root {name!r} has an invalid project")

    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise ConnectorConfigError(f"root {name!r} has a non-boolean required flag")

    external = raw.get("external", False)
    if not isinstance(external, bool):
        raise ConnectorConfigError(f"root {name!r} has a non-boolean external flag")

    raw_overrides = raw.get("overrides", [])
    if not isinstance(raw_overrides, list):
        raise ConnectorConfigError(f"root {name!r} has an invalid overrides list")
    overrides = tuple(
        _parse_override(name, index, override)
        for index, override in enumerate(raw_overrides)
    )

    return RootConfig(
        name=name,
        path=path,
        owner=owner,
        include=tuple(include),
        exclude=tuple(exclude),
        authority=authority,
        trust=trust,
        visibility=visibility,
        project=project,
        required=required,
        external=external,
        overrides=overrides,
    )


def _parse_override(root_name: str, index: int, raw: object) -> OverrideConfig:
    label = f"root {root_name!r} override {index}"
    if not isinstance(raw, dict):
        raise ConnectorConfigError(f"{label} must be a table")
    pattern = raw.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ConnectorConfigError(f"{label} is missing a non-empty pattern")
    authority = _lookup(raw, label, "authority", _AUTHORITY_BY_VALUE, None)
    trust = _lookup(raw, label, "trust", _TRUST_BY_VALUE, None)
    return OverrideConfig(pattern=pattern, authority=authority, trust=trust)


def _lookup(raw: dict, context: str, field: str, table: dict, default):
    value = raw.get(field)
    if value is None:
        return default
    if not isinstance(value, str) or value not in table:
        raise ConnectorConfigError(f"{context} has an unrecognized {field} {value!r}")
    return table[value]


@lru_cache(maxsize=512)
def _compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile the reference path-glob dialect to a full-match regex."""
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            end = index
            while end < len(pattern) and pattern[end] == "*":
                end += 1
            if end - index >= 2:
                if end < len(pattern) and pattern[end] == "/":
                    pieces.append("(?:.*/)?")
                    end += 1
                else:
                    pieces.append(".*")
            else:
                pieces.append("[^/]*")
            index = end
            continue
        if character == "?":
            pieces.append("[^/]")
        elif character == "[":
            end = index + 1
            if end < len(pattern) and pattern[end] in "!^":
                end += 1
            if end < len(pattern) and pattern[end] == "]":
                end += 1
            while end < len(pattern) and pattern[end] != "]":
                end += 1
            if end >= len(pattern):
                pieces.append(r"\[")
            else:
                stuff = pattern[index + 1 : end].replace("\\", r"\\")
                if stuff.startswith("!"):
                    stuff = "^" + stuff[1:]
                elif stuff.startswith("^"):
                    stuff = "\\" + stuff
                pieces.append(f"(?!/)[{stuff}]")
                index = end
        else:
            pieces.append(re.escape(character))
        index += 1
    return re.compile("".join(("^", *pieces, "$")))


def _glob_match(relative_posix: str, pattern: str) -> bool:
    return _compile_glob(pattern).fullmatch(relative_posix) is not None


def _matches(
    relative_posix: str, include: Sequence[str], exclude: Sequence[str]
) -> bool:
    if any(_glob_match(relative_posix, pattern) for pattern in GLOBAL_DEFAULT_DENY):
        return False
    if not any(_glob_match(relative_posix, pattern) for pattern in include):
        return False
    return not any(_glob_match(relative_posix, pattern) for pattern in exclude)


@dataclass(slots=True)
class DiscoveryReport:
    """Everything one :meth:`LocalFilesConnector.discover_report` pass found.

    Every file under a declared root is accounted for in exactly one place:
    it is either in ``objects``, or counted in ``unhandled_formats``,
    ``git_ignored``, or ``git_unresolved`` -- so "what did you NOT index,
    and why?" always has an answer.
    """

    objects: tuple[SourceObject, ...]
    #: Lowercase file suffix (e.g. ``".docx"``) to count of matching
    #: candidates with no registered :data:`FORMAT_HANDLERS` entry.
    unhandled_formats: dict[str, int]
    #: Candidates git reports as ignored, excluded from ``objects``.
    git_ignored: int = 0
    #: Candidates whose git-ignore status could not be resolved (the root
    #: is not inside a git repository, git is unavailable, or an ancestor
    #: ignore rule suppresses the configured root). Included in ``objects``
    #: when otherwise eligible -- unresolved is never treated as ignored.
    git_unresolved: int = 0


def _git_ignored_relatives(
    root_path: Path, relatives: Sequence[str]
) -> tuple[frozenset[str], bool]:
    """Resolve git-ignore status for candidates under one root.

    Issues a single batched ``git check-ignore -z --stdin`` call rather than
    one process per file. Returns the subset of ``relatives`` git reports as
    ignored, and whether resolution succeeded. Degrades gracefully -- never
    raises -- when the root is not inside a git repository or git is
    unavailable, or when an ancestor ignore rule suppresses the configured
    root itself; callers must count that as unresolved, not as "not ignored"
    or a crash.
    """
    if not relatives:
        return frozenset(), True
    # Include the declared root itself in the same batch. If an ignore rule
    # above the root suppresses ``.`` then every descendant would otherwise
    # appear ignored, even though the root was explicitly configured as a
    # source. Treat that situation as unresolved so discovery remains
    # fail-visible and does not silently drop the entire root.
    checked_paths = (".", *relatives)
    payload = b"\x00".join(path.encode("utf-8") for path in checked_paths) + b"\x00"
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-z", "--stdin"],
            cwd=root_path,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset(), False
    # 0 = one or more paths ignored, 1 = none ignored, anything else
    # (typically 128, "not a git repository") is unresolved.
    if result.returncode not in (0, 1):
        return frozenset(), False
    ignored = {
        chunk.decode("utf-8", errors="replace")
        for chunk in result.stdout.split(b"\x00")
        if chunk
    }
    if "." in ignored:
        return frozenset(), False
    return frozenset(ignored), True


def _split_object_id(source_object_id: str) -> tuple[str, str]:
    if ":" not in source_object_id:
        raise ConnectorReadError(
            f"malformed source_object_id (expected 'root:path'): {source_object_id!r}"
        )
    root_name, _, relative = source_object_id.partition(":")
    return root_name, relative


def _find_nested_roots(
    roots: Sequence[RootConfig],
) -> tuple[tuple[str, str], ...]:
    """Return deterministic ``(parent, child)`` pairs for overlapping roots."""
    resolved = tuple((root, root.path.resolve()) for root in roots)
    nested: list[tuple[str, str]] = []
    for index, (left, left_path) in enumerate(resolved):
        for right, right_path in resolved[index + 1 :]:
            if left_path == right_path:
                parent, child = sorted((left.name, right.name))
                nested.append((parent, child))
            elif left_path in right_path.parents:
                nested.append((left.name, right.name))
            elif right_path in left_path.parents:
                nested.append((right.name, left.name))
    return tuple(sorted(nested))


class LocalFilesConnector(Connector):
    """Connector over one or more local filesystem roots."""

    def __init__(
        self,
        roots: Sequence[RootConfig],
        *,
        connector_id: str = "local_files",
    ) -> None:
        if not roots:
            raise ConnectorConfigError("at least one root is required")
        self._connector_id = connector_id
        self._roots_by_name = {root.name: root for root in roots}
        self._resolved_paths_by_name = {
            root.name: root.path.resolve() for root in self._roots_by_name.values()
        }
        self._nested_roots = _find_nested_roots(tuple(self._roots_by_name.values()))

    @classmethod
    def from_config(
        cls,
        config_path: str | Path,
        *,
        connector_id: str = "local_files",
        workspace_root: str | Path | None = None,
    ) -> "LocalFilesConnector":
        """Build a connector from a sources.toml file."""
        return cls(
            load_config(config_path, workspace_root=workspace_root),
            connector_id=connector_id,
        )

    @property
    def connector_id(self) -> str:
        return self._connector_id

    def discover(self) -> tuple[SourceObject, ...]:
        return self.discover_report().objects

    def discover_report(self, *, root_name: str | None = None) -> DiscoveryReport:
        """Discover objects and report every candidate that did not make it.

        With ``root_name`` set, scans only that configured root (used by
        ``lee-kb sync <connector> <root>`` so the report matches the scope
        of the sync). Raises :class:`ConnectorReadError` for an unknown
        root name.
        """
        if root_name is not None and root_name not in self._roots_by_name:
            raise ConnectorReadError(f"unknown root: {root_name!r}")
        roots = (
            (self._roots_by_name[root_name],)
            if root_name is not None
            else tuple(self._roots_by_name.values())
        )

        objects: list[SourceObject] = []
        unhandled_formats: dict[str, int] = {}
        git_ignored = 0
        git_unresolved = 0
        for root in roots:
            if not root.path.is_dir():
                continue
            root_base = root.path.resolve()
            candidates: list[tuple[str, Path]] = []
            for file_path in sorted(root.path.rglob("*")):
                if not file_path.is_file():
                    continue
                relative = file_path.relative_to(root.path).as_posix()
                if not _matches(relative, root.include, root.exclude):
                    continue
                resolved = file_path.resolve()
                if root_base not in resolved.parents and resolved != root_base:
                    # Same containment rule as _resolve(): a candidate whose
                    # resolved target escapes its declared root (e.g. a
                    # symlink out of the tree) is never handed out, so
                    # discovery and fetch agree on which objects exist.
                    continue
                if self._claiming_root(root, resolved) is not root:
                    continue
                candidates.append((relative, file_path))

            ignored, resolved_ok = _git_ignored_relatives(
                root_base, [relative for relative, _ in candidates]
            )
            if not resolved_ok:
                git_unresolved += len(candidates)

            for relative, file_path in candidates:
                if resolved_ok and relative in ignored:
                    git_ignored += 1
                    continue
                handler = FORMAT_HANDLERS.get(file_path.suffix.lower())
                if handler is None:
                    suffix = file_path.suffix.lower() or "(no extension)"
                    unhandled_formats[suffix] = unhandled_formats.get(suffix, 0) + 1
                    continue
                try:
                    objects.append(self._describe(root, relative, file_path, handler))
                except ConnectorReadError:
                    # One unreadable candidate degrades discovery to a skip;
                    # it must not abort the whole pass.
                    continue
        return DiscoveryReport(
            objects=tuple(objects),
            unhandled_formats=unhandled_formats,
            git_ignored=git_ignored,
            git_unresolved=git_unresolved,
        )

    def _claiming_root(self, discovered_root: RootConfig, resolved: Path) -> RootConfig:
        """Choose the deterministic root identity for one resolved file."""
        matches = [discovered_root]
        for root in self._roots_by_name.values():
            if root is discovered_root or not root.path.is_dir():
                continue
            root_base = self._resolved_paths_by_name[root.name]
            if root_base != resolved and root_base not in resolved.parents:
                continue
            candidate_relative = resolved.relative_to(root_base).as_posix()
            if _matches(candidate_relative, root.include, root.exclude):
                matches.append(root)
        return min(
            matches,
            key=lambda root: (
                -len(self._resolved_paths_by_name[root.name].parts),
                root.name,
            ),
        )

    def _describe(
        self, root: RootConfig, relative: str, file_path: Path, handler: FormatHandler
    ) -> SourceObject:
        try:
            raw = file_path.read_bytes()
            stat = file_path.stat()
        except OSError as error:
            raise ConnectorReadError(f"cannot read {file_path}: {error}") from error
        authority, trust = root.metadata_for(relative)
        return SourceObject(
            source_object_id=f"{root.name}:{relative}",
            source_locator=SourceLocator(
                connector_id=self._connector_id,
                uri=file_path.as_uri(),
                label=relative,
            ),
            document_type=handler.document_type,
            content_hash=compute_content_hash(raw),
            source_timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            project=root.project,
            authority=authority,
            trust=trust,
        )

    def list_changes(self, cursor: str | None = None) -> tuple[ObjectChange, ...]:
        previous = _decode_snapshot(cursor)
        current = {obj.source_object_id: obj.content_hash for obj in self.discover()}

        changes: list[ObjectChange] = []
        for source_object_id, content_hash in current.items():
            previous_hash = previous.get(source_object_id)
            if previous_hash is None:
                changes.append(
                    ObjectChange(
                        source_object_id,
                        ChangeType.CREATED,
                        content_hash=content_hash,
                    )
                )
            elif previous_hash != content_hash:
                changes.append(
                    ObjectChange(
                        source_object_id,
                        ChangeType.UPDATED,
                        content_hash=content_hash,
                        previous_content_hash=previous_hash,
                    )
                )
        for source_object_id, previous_hash in previous.items():
            if source_object_id not in current:
                changes.append(
                    ObjectChange(
                        source_object_id,
                        ChangeType.DELETED,
                        previous_content_hash=previous_hash,
                    )
                )
        return tuple(sorted(changes, key=lambda change: change.source_object_id))

    def fetch(self, source_object_id: str) -> FetchedDocument:
        root, relative, file_path = self._resolve(source_object_id)
        handler = FORMAT_HANDLERS.get(file_path.suffix.lower())
        if handler is None:
            raise ConnectorReadError(
                f"no format handler registered for {file_path.suffix!r}: "
                f"{source_object_id}"
            )
        try:
            raw = file_path.read_bytes()
            stat = file_path.stat()
        except OSError as error:
            raise ConnectorReadError(f"cannot read {file_path}: {error}") from error
        try:
            content = handler.decode(raw)
        except UnicodeDecodeError as error:
            raise ConnectorReadError(f"cannot decode {file_path}: {error}") from error

        authority, trust = root.metadata_for(relative)
        return FetchedDocument(
            source_object_id=source_object_id,
            source_locator=SourceLocator(
                connector_id=self._connector_id,
                uri=file_path.as_uri(),
                label=relative,
            ),
            document_type=handler.document_type,
            content=content,
            content_hash=compute_content_hash(raw),
            source_timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            project=root.project,
            title=Path(relative).name,
            authority=authority,
            trust=trust,
        )

    def refresh(self, source_object_id: str) -> FetchedDocument:
        # Local reads are already live: there is no separate refresh path
        # to distinguish from an ordinary fetch.
        return self.fetch(source_object_id)

    def permissions(self, source_object_id: str) -> PermissionSet:
        root, _relative, _file_path = self._resolve(source_object_id)
        return PermissionSet(owner=root.owner, visibility=root.visibility)

    def relationships(self, source_object_id: str) -> tuple[str, ...]:
        # The local filesystem has no relationship model in v1.
        self._resolve(source_object_id)
        return ()

    def health(self) -> HealthStatus:
        missing_required = tuple(
            root.name
            for root in self._roots_by_name.values()
            if root.required and not root.path.is_dir()
        )
        healthy = not missing_required
        reachability_detail = (
            "all roots reachable"
            if healthy
            else f"missing required roots: {', '.join(missing_required)}"
        )
        detail = reachability_detail
        if self._nested_roots:
            pairs = ", ".join(
                f"{parent} -> {child}" for parent, child in self._nested_roots
            )
            detail += (
                "; nested roots detected "
                f"(deepest matching root claims overlaps): {pairs}"
            )
        return HealthStatus(
            healthy=healthy,
            checked_at=datetime.now(timezone.utc),
            detail=detail,
            missing_required_roots=missing_required,
        )

    def checkpoint(self, objects: Sequence[SourceObject]) -> str:
        snapshot = {obj.source_object_id: obj.content_hash for obj in objects}
        return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))

    def _resolve(self, source_object_id: str) -> tuple[RootConfig, str, Path]:
        root_name, relative = _split_object_id(source_object_id)
        root = self._roots_by_name.get(root_name)
        if root is None:
            raise ConnectorReadError(f"unknown root in source_object_id: {root_name!r}")
        file_path = (root.path / relative).resolve()
        if root.path not in file_path.parents and file_path != root.path:
            raise ConnectorReadError(
                f"source_object_id escapes its root: {source_object_id!r}"
            )
        if not file_path.is_file():
            raise ConnectorReadError(
                f"source object no longer exists: {source_object_id}"
            )
        return root, relative, file_path


def _decode_snapshot(cursor: str | None) -> dict[str, str]:
    if cursor is None:
        return {}
    try:
        snapshot = json.loads(cursor)
    except json.JSONDecodeError as error:
        raise ConnectorConfigError(f"invalid cursor: {error}") from error
    if not isinstance(snapshot, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in snapshot.items()
    ):
        raise ConnectorConfigError("invalid cursor: expected a JSON object of strings")
    return snapshot
