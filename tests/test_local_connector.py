"""Behavioral tests for the local-file connector.

These tests double as the connector's ingestion loop: they call
``list_changes``/``fetch``/``permissions`` the way a future ingestion engine
would, then persist through :class:`SQLiteRepository`, so a scenario that
compiles here also proves the contract methods compose correctly.
"""

import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.connectors import local_files as local_files_module
from lee_kb.connectors.base import ConnectorConfigError, ConnectorReadError
from lee_kb.connectors.local_files import (
    LocalFilesConnector,
    contains_token_shaped_secret,
    load_config,
)
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChangeType,
    Chunk,
    ChunkId,
    KnowledgeItem,
    KnowledgeItemId,
    Trust,
    compute_content_hash,
)
from lee_kb.repository import SQLiteRepository

SYNC_TIME = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def write_config(
    config_path,
    source_root,
    *,
    include=("*.md", "*.txt"),
    exclude=(),
    authority="derived",
    trust="curated",
    owner="lee@leebase.com",
) -> None:
    include_toml = ", ".join(f'"{pattern}"' for pattern in include)
    exclude_toml = ", ".join(f'"{pattern}"' for pattern in exclude)
    config_path.write_text(
        f"""
schema = 1

[roots.notes]
path = "{source_root.as_posix()}"
owner = "{owner}"
include = [{include_toml}]
exclude = [{exclude_toml}]
authority = "{authority}"
trust = "{trust}"
"""
    )


def make_connector(tmp_path, files, **config_kwargs) -> LocalFilesConnector:
    source_root = tmp_path / "source"
    source_root.mkdir()
    for relative, content in files.items():
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    config_path = tmp_path / "sources.toml"
    write_config(config_path, source_root, **config_kwargs)
    return LocalFilesConnector.from_config(config_path)


def build_item(connector, document, *, sync_timestamp) -> KnowledgeItem:
    item_id = KnowledgeItemId(connector.connector_id, document.source_object_id)
    return KnowledgeItem(
        item_id=item_id,
        project=document.project,
        source_locator=document.source_locator,
        document_type=document.document_type,
        content_hash=document.content_hash,
        source_timestamp=document.source_timestamp,
        sync_timestamp=sync_timestamp,
        permissions=connector.permissions(document.source_object_id),
        title=document.title,
        authority=document.authority,
        trust=document.trust,
    )


def build_chunk(item_id: KnowledgeItemId, document) -> Chunk:
    text = document.content
    return Chunk(
        chunk_id=ChunkId(item_id, 0, compute_content_hash(text)),
        project=document.project,
        text=text,
        chunker_id="whole-document-v1:1",
    )


def sync_all(connector, repository, *, cursor, sync_timestamp) -> str:
    """Apply one incremental sync pass and return the next cursor."""
    for change in connector.list_changes(cursor):
        item_id = KnowledgeItemId(connector.connector_id, change.source_object_id)
        if change.change_type is ChangeType.DELETED:
            repository.tombstone_item(item_id, sync_timestamp=sync_timestamp)
            continue
        document = connector.fetch(change.source_object_id)
        item = build_item(connector, document, sync_timestamp=sync_timestamp)
        repository.sync_item(item, (build_chunk(item_id, document),))
    return connector.checkpoint(connector.discover())


def initial_sync(connector, repository) -> str:
    return sync_all(connector, repository, cursor=None, sync_timestamp=SYNC_TIME)


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def test_initial_sync_persists_every_discovered_object(tmp_path, repository) -> None:
    connector = make_connector(
        tmp_path,
        {
            "architecture.md": "# Architecture\n\nSource systems stay authoritative.",
            "notes.txt": "Plain notes about the sprint.",
        },
    )

    cursor = initial_sync(connector, repository)

    architecture_id = KnowledgeItemId("local_files", "notes:architecture.md")
    notes_id = KnowledgeItemId("local_files", "notes:notes.txt")
    architecture = repository.get_item(architecture_id)
    notes = repository.get_item(notes_id)

    assert architecture is not None and not architecture.tombstone
    assert notes is not None and not notes.tombstone
    assert architecture.source_locator.uri.startswith("file://")
    assert len(repository.journal_entries()) == 2
    assert {entry.change_type for entry in repository.journal_entries()} == {
        ChangeType.CREATED
    }
    assert cursor  # a non-empty snapshot cursor was produced


def test_noop_resync_journals_nothing(tmp_path, repository) -> None:
    connector = make_connector(
        tmp_path,
        {"architecture.md": "# Architecture\n\nStable content."},
    )
    cursor = initial_sync(connector, repository)

    changes = connector.list_changes(cursor)
    next_cursor = sync_all(
        repository=repository,
        connector=connector,
        cursor=cursor,
        sync_timestamp=SYNC_TIME + timedelta(hours=1),
    )

    assert changes == ()
    assert next_cursor == cursor
    assert len(repository.journal_entries()) == 1


def test_changed_file_is_detected_and_updates_the_projection(
    tmp_path, repository
) -> None:
    connector = make_connector(
        tmp_path,
        {"architecture.md": "# Architecture\n\nOriginal content."},
    )
    cursor = initial_sync(connector, repository)
    item_id = KnowledgeItemId("local_files", "notes:architecture.md")
    original_hash = repository.get_item(item_id).content_hash

    (tmp_path / "source" / "architecture.md").write_text(
        "# Architecture\n\nRevised content after the sprint."
    )
    changes = connector.list_changes(cursor)

    assert len(changes) == 1
    assert changes[0].change_type is ChangeType.UPDATED
    assert changes[0].previous_content_hash == original_hash

    sync_all(
        repository=repository,
        connector=connector,
        cursor=cursor,
        sync_timestamp=SYNC_TIME + timedelta(hours=2),
    )

    updated = repository.get_item(item_id)
    assert updated.content_hash != original_hash
    assert repository.get_chunks(item_id)[0].text == (
        "# Architecture\n\nRevised content after the sprint."
    )
    entries = repository.journal_entries(item_id)
    assert [entry.change_type for entry in entries] == [
        ChangeType.CREATED,
        ChangeType.UPDATED,
    ]


def test_deleted_file_is_detected_and_tombstoned_via_repository(
    tmp_path, repository
) -> None:
    connector = make_connector(
        tmp_path,
        {
            "architecture.md": "# Architecture\n\nKept around.",
            "notes.txt": "Removed later.",
        },
    )
    cursor = initial_sync(connector, repository)
    notes_id = KnowledgeItemId("local_files", "notes:notes.txt")

    (tmp_path / "source" / "notes.txt").unlink()
    changes = connector.list_changes(cursor)

    assert len(changes) == 1
    assert changes[0].change_type is ChangeType.DELETED
    assert changes[0].source_object_id == "notes:notes.txt"

    sync_all(
        repository=repository,
        connector=connector,
        cursor=cursor,
        sync_timestamp=SYNC_TIME + timedelta(hours=3),
    )

    tombstoned = repository.get_item(notes_id)
    assert tombstoned.tombstone is True
    assert repository.search("Removed", project=DEFAULT_PROJECT) == ()
    entries = repository.journal_entries(notes_id)
    assert entries[-1].change_type is ChangeType.DELETED
    with pytest.raises(ConnectorReadError):
        connector.fetch("notes:notes.txt")


def test_include_exclude_and_format_registry_enforce_default_deny(tmp_path) -> None:
    connector = make_connector(
        tmp_path,
        {
            "architecture.md": "included by *.md",
            "notes.txt": "included by *.txt",
            "drafts/todo.md": "excluded by drafts/** even though it matches *.md",
            "config.secret.md": "excluded by *.secret.md",
            "diagram.png": "matches include but has no registered format handler",
            "readme.rst": "matches no include pattern at all",
        },
        include=("*.md", "*.txt", "*.png"),
        exclude=("drafts/**", "*.secret.md"),
    )

    discovered = {obj.source_object_id for obj in connector.discover()}

    assert discovered == {"notes:architecture.md", "notes:notes.txt"}


def test_single_star_include_matches_only_top_level_files(tmp_path) -> None:
    connector = make_connector(
        tmp_path,
        {
            "top-level.md": "included",
            "docs/nested.md": "must not be matched by *.md",
        },
        include=("*.md",),
    )

    discovered = {obj.source_object_id for obj in connector.discover()}

    assert discovered == {"notes:top-level.md"}


def test_double_star_directory_include_matches_zero_or_more_directories(
    tmp_path,
) -> None:
    connector = make_connector(
        tmp_path,
        {
            "top-level.md": "outside docs",
            "docs/a.md": "zero directories below docs",
            "docs/a/b.md": "one directory below docs",
        },
        include=("docs/**/*.md",),
    )

    discovered = {obj.source_object_id for obj in connector.discover()}

    assert discovered == {"notes:docs/a.md", "notes:docs/a/b.md"}


def test_global_default_deny_applies_to_every_root(tmp_path) -> None:
    denied_directories = (
        "code-reviews",
        ".agent-orch",
        ".agent-orch-scratch",
        "artifacts",
        "tmp",
        ".kb",
        ".git",
    )
    files = {f"{directory}/hidden.md": "denied" for directory in denied_directories}
    files["safe/visible.md"] = "allowed"
    connector = make_connector(tmp_path, files, include=("**/*.md",))

    discovered = {obj.source_object_id for obj in connector.discover()}

    assert discovered == {"notes:safe/visible.md"}


def test_root_overrides_apply_first_matching_authority_and_trust(tmp_path) -> None:
    source_root = tmp_path / "source"
    (source_root / "knowledge").mkdir(parents=True)
    (source_root / "knowledge" / "faq.md").write_text("canonical FAQ")
    (source_root / "knowledge" / "notes.md").write_text("derived notes")
    config_path = tmp_path / "sources.toml"
    config_path.write_text(
        f"""
schema = 1

[roots.notes]
path = "{source_root.as_posix()}"
owner = "lee@leebase.com"
include = ["**/*.md"]
authority = "derived"
trust = "curated"

[[roots.notes.overrides]]
pattern = "knowledge/faq.md"
authority = "canonical"
trust = "human_authored"

[[roots.notes.overrides]]
pattern = "knowledge/*.md"
authority = "derived"
trust = "model_produced"
"""
    )
    connector = LocalFilesConnector.from_config(config_path)

    discovered = {obj.source_object_id: obj for obj in connector.discover()}

    faq = discovered["notes:knowledge/faq.md"]
    notes = discovered["notes:knowledge/notes.md"]
    assert (faq.authority, faq.trust) == (
        Authority.CANONICAL,
        Trust.HUMAN_AUTHORED,
    )
    assert (notes.authority, notes.trust) == (
        Authority.DERIVED,
        Trust.MODEL_PRODUCED,
    )
    fetched = connector.fetch("notes:knowledge/faq.md")
    assert (fetched.authority, fetched.trust) == (
        Authority.CANONICAL,
        Trust.HUMAN_AUTHORED,
    )


def test_config_workspace_root_resolves_relative_source_paths(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    workspace_root = tmp_path / "workspace"
    (workspace_root / "docs").mkdir(parents=True)
    (workspace_root / "docs" / "source.md").write_text("workspace source")
    config_path = config_dir / "sources.toml"
    config_path.write_text(
        """
schema = 1
workspace_root = "../workspace"

[roots.notes]
path = "docs"
owner = "lee@leebase.com"
include = ["*.md"]
"""
    )

    roots = load_config(config_path)
    connector = LocalFilesConnector(roots)

    assert roots[0].path == (workspace_root / "docs").resolve()
    assert {obj.source_object_id for obj in connector.discover()} == {"notes:source.md"}


def test_relative_source_path_defaults_to_config_directory(tmp_path) -> None:
    config_dir = tmp_path / "config"
    (config_dir / "docs").mkdir(parents=True)
    (config_dir / "docs" / "source.md").write_text("config-relative source")
    config_path = config_dir / "sources.toml"
    config_path.write_text(
        """
schema = 1

[roots.notes]
path = "docs"
owner = "lee@leebase.com"
include = ["*.md"]
"""
    )

    roots = load_config(config_path)

    assert roots[0].path == (config_dir / "docs").resolve()


def test_unknown_config_keys_are_collected_across_all_levels(tmp_path) -> None:
    config_path = tmp_path / "sources.toml"
    config_path.write_text(
        """
schema = 1
unexpected_top = true

[roots.notes]
path = "."
owner = "lee@leebase.com"
include = ["*.md"]
unexpected_root = true

[[roots.notes.overrides]]
pattern = "faq.md"
unexpected_override = true
"""
    )

    with pytest.raises(ConnectorConfigError) as caught:
        load_config(config_path)

    message = str(caught.value)
    assert "unexpected_top" in message
    assert "unexpected_root" in message
    assert "unexpected_override" in message


def test_discover_skips_symlink_whose_target_escapes_the_root(tmp_path) -> None:
    """Discovery and fetch agree on containment (S1-R-10).

    A symlink inside a declared root whose resolved target escapes the root
    is never handed out by discover(), so every discovered object is
    fetchable under _resolve()'s containment rule.
    """
    connector = make_connector(tmp_path, {"inside.md": "inside the root"})
    source_root = tmp_path / "source"
    outside = tmp_path / "outside.md"
    outside.write_text("outside the declared root", encoding="utf-8")
    (source_root / "escape.md").symlink_to(outside)
    (source_root / "broken.md").symlink_to(tmp_path / "no-such-target.md")

    discovered = {obj.source_object_id for obj in connector.discover()}

    assert discovered == {"notes:inside.md"}
    with pytest.raises(ConnectorReadError):
        connector.fetch("notes:escape.md")


def test_sync_pass_skips_unfetchable_object_and_continues(
    tmp_path, repository, monkeypatch
) -> None:
    """One bad object degrades a sync pass instead of ending it (S1-R-10)."""
    from datetime import datetime as _datetime

    from lee_kb.main import _sync_connector

    connector = make_connector(
        tmp_path, {"good.md": "good document", "bad.md": "bad document"}
    )
    real_fetch = connector.fetch

    def flaky_fetch(source_object_id):
        if source_object_id.endswith("bad.md"):
            raise ConnectorReadError("simulated unreadable object")
        return real_fetch(source_object_id)

    monkeypatch.setattr(connector, "fetch", flaky_fetch)

    summary = _sync_connector(
        connector,
        repository,
        root_filter=None,
        sync_timestamp=_datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert summary.created == 1
    assert summary.skipped == 1
    assert len(summary.skipped_objects) == 1
    assert "bad.md" in summary.skipped_objects[0]
    hits = repository.search("good", project=DEFAULT_PROJECT, limit=5)
    assert {hit.item.item_id.source_object_id for hit in hits} == {"notes:good.md"}


def test_unhandled_formats_are_counted_per_lowercase_extension(tmp_path) -> None:
    """A document a user expects to be searchable must never disappear
    without a count -- office formats with no registered handler are
    counted per extension instead of silently vanishing from discover()."""
    connector = make_connector(
        tmp_path,
        {
            "keep.md": "indexable",
            "report.docx": "office format, not yet handled",
            "sheet.XLSX": "uppercase suffix normalizes to lowercase",
            "deck.pptx": "office format, not yet handled",
        },
        include=("*.md", "*.docx", "*.XLSX", "*.pptx"),
    )

    report = connector.discover_report()

    assert {obj.source_object_id for obj in report.objects} == {"notes:keep.md"}
    assert report.unhandled_formats == {".docx": 1, ".xlsx": 1, ".pptx": 1}


def test_discover_report_scopes_unhandled_formats_to_requested_root(tmp_path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "alpha.md").write_text("alpha")
    (root_b / "beta.docx").write_text("beta, unhandled format")
    config_path = tmp_path / "sources.toml"
    config_path.write_text(
        f"""
schema = 1

[roots.a]
path = "{root_a.as_posix()}"
owner = "lee@leebase.com"
include = ["*.md"]

[roots.b]
path = "{root_b.as_posix()}"
owner = "lee@leebase.com"
include = ["*.docx"]
"""
    )
    connector = LocalFilesConnector.from_config(config_path)

    report = connector.discover_report(root_name="b")

    assert report.objects == ()
    assert report.unhandled_formats == {".docx": 1}


def test_git_ignored_candidates_are_excluded_and_counted(tmp_path) -> None:
    connector = make_connector(
        tmp_path,
        {
            "keep.md": "kept",
            "build/output.md": "generated, listed in .gitignore",
        },
        include=("**/*.md",),
    )
    source_root = tmp_path / "source"
    subprocess.run(
        ["git", "init", "-q"], cwd=source_root, check=True, capture_output=True
    )
    (source_root / ".gitignore").write_text("build/\n")

    report = connector.discover_report()

    assert {obj.source_object_id for obj in report.objects} == {"notes:keep.md"}
    assert report.git_ignored == 1
    assert report.git_unresolved == 0


def test_non_git_root_degrades_gracefully_and_counts_unresolved(
    tmp_path, monkeypatch
) -> None:
    """git-ignore resolution must never crash or exclude anything when the
    root is not inside a git repository -- it degrades to an unresolved
    count. Simulated deterministically (rather than by placing a root
    outside the checkout) since git's exact non-repository exit status
    (128) is what the connector must handle."""
    connector = make_connector(tmp_path, {"note.md": "content in a non-git root"})

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            returncode=128,
            stdout=b"",
            stderr=b"fatal: not a git repository (or any parent up to mount point /)\n",
        )

    monkeypatch.setattr(local_files_module.subprocess, "run", fake_run)

    report = connector.discover_report()

    assert {obj.source_object_id for obj in report.objects} == {"notes:note.md"}
    assert report.git_unresolved == 1
    assert report.git_ignored == 0


def test_git_unavailable_degrades_gracefully(tmp_path, monkeypatch) -> None:
    connector = make_connector(tmp_path, {"note.md": "content"})

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("git executable not found")

    monkeypatch.setattr(local_files_module.subprocess, "run", fake_run)

    report = connector.discover_report()

    assert {obj.source_object_id for obj in report.objects} == {"notes:note.md"}
    assert report.git_unresolved == 1


def test_contains_token_shaped_secret_detects_conservative_patterns() -> None:
    assert contains_token_shaped_secret("api_key: sk-" + "a" * 24)
    assert contains_token_shaped_secret("token=ghp_" + "b" * 30)
    assert contains_token_shaped_secret("-----BEGIN RSA PRIVATE KEY-----")
    assert not contains_token_shaped_secret("just some ordinary prose about API design")


def test_sync_skips_and_counts_file_containing_token_shaped_secret(
    tmp_path, repository
) -> None:
    """Content matching a token-shaped pattern must never enter the
    projection: it is skipped at index time and counted, so indexing real
    repositories does not pull credentials into the search results."""
    from datetime import datetime as _datetime

    from lee_kb.main import _sync_connector

    connector = make_connector(
        tmp_path,
        {
            "good.md": "an ordinary document with no secrets",
            "leaked.md": "leaked credential: sk-" + "a" * 24,
        },
    )

    summary = _sync_connector(
        connector,
        repository,
        root_filter=None,
        sync_timestamp=_datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert summary.created == 1
    assert summary.skipped_token_content == 1
    hits = repository.search("leaked", project=DEFAULT_PROJECT, limit=5)
    assert hits == ()
    hits = repository.search("ordinary", project=DEFAULT_PROJECT, limit=5)
    assert {hit.item.item_id.source_object_id for hit in hits} == {"notes:good.md"}
