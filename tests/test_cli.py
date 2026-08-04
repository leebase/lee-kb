"""End-to-end tests for the lee-kb CLI surface: init, sync, and search.

These tests drive the real entry point (``python -m lee_kb.main``) the way a
user would, per skills/test-as-lee.md: a small local corpus, synchronization
through the actual command, and a query that inspects cited, governed
evidence.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(
    *arguments: str, env_overrides: dict | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the package entry point from a source checkout."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    if env_overrides:
        environment.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "lee_kb.main", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def workspace(tmp_path):
    return {
        "config_path": tmp_path / "config.toml",
        "corpus": tmp_path / "notes",
    }


def _env(workspace) -> dict:
    return {"LEE_KB_CONFIG": str(workspace["config_path"])}


def _write_config(workspace, *, include=("*.md",), owner="lee@leebase.com") -> None:
    workspace["corpus"].mkdir(exist_ok=True)
    include_toml = ", ".join(f'"{pattern}"' for pattern in include)
    workspace["config_path"].write_text(
        f"""
schema = 1
owner = "lee@leebase.com"

[roots.notes]
path = "{workspace['corpus'].as_posix()}"
owner = "{owner}"
include = [{include_toml}]
visibility = "private"
project = "default"
"""
    )


def test_init_writes_starter_config(workspace) -> None:
    result = run_cli("init", env_overrides=_env(workspace))

    assert result.returncode == 0
    assert workspace["config_path"].exists()
    assert "schema = 1" in workspace["config_path"].read_text()


def test_init_refuses_to_overwrite_without_force(workspace) -> None:
    run_cli("init", env_overrides=_env(workspace))
    result = run_cli("init", env_overrides=_env(workspace))

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert "Traceback" not in result.stderr


def test_init_honors_explicit_config_flag(tmp_path) -> None:
    config_path = tmp_path / "custom" / "config.toml"

    result = run_cli("init", "--config", str(config_path))

    assert result.returncode == 0
    assert config_path.exists()


def test_sync_missing_config_reports_actionable_error(workspace) -> None:
    result = run_cli("sync", env_overrides=_env(workspace))

    assert result.returncode != 0
    assert "config" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_sync_and_search_end_to_end(workspace) -> None:
    workspace["corpus"].mkdir()
    (workspace["corpus"] / "architecture.md").write_text(
        "# Architecture\n\nlee-kb is a governed knowledge fabric for retrieval."
    )
    _write_config(workspace)

    sync_result = run_cli("sync", env_overrides=_env(workspace))
    assert sync_result.returncode == 0
    assert "1 created" in sync_result.stdout

    # Re-running sync with no changes is idempotent and journals nothing new.
    resync_result = run_cli("sync", env_overrides=_env(workspace))
    assert resync_result.returncode == 0
    assert "1 unchanged" in resync_result.stdout

    search_result = run_cli("search", "governed", env_overrides=_env(workspace))

    assert search_result.returncode == 0
    assert "architecture.md" in search_result.stdout
    assert "receipt #" in search_result.stdout
    assert "synced" in search_result.stdout


def test_sync_source_scoped_to_one_root(workspace) -> None:
    workspace["corpus"].mkdir()
    (workspace["corpus"] / "notes.md").write_text("# Notes\n\ncontent")
    _write_config(workspace)
    run_cli("sync", env_overrides=_env(workspace))

    result = run_cli(
        "sync", "local_files", "missing-root", env_overrides=_env(workspace)
    )

    assert result.returncode != 0
    assert "missing-root" in result.stderr


def test_sync_workspace_root_flag_overrides_relative_root_base(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    workspace_root = tmp_path / "workspace"
    (workspace_root / "docs").mkdir(parents=True)
    (workspace_root / "docs" / "architecture.md").write_text("workspace content")
    config_path = config_dir / "sources.toml"
    config_path.write_text(
        """
schema = 1
workspace_root = "../wrong-workspace"

[roots.notes]
path = "docs"
owner = "lee@leebase.com"
include = ["*.md"]
"""
    )

    result = run_cli(
        "sync",
        "--config",
        str(config_path),
        "--workspace-root",
        str(workspace_root),
    )

    assert result.returncode == 0
    assert "1 created" in result.stdout


def test_sync_database_flag_writes_projection_at_requested_path(workspace) -> None:
    workspace["corpus"].mkdir()
    (workspace["corpus"] / "architecture.md").write_text("database override")
    _write_config(workspace)
    database_path = workspace["config_path"].parent / "projection" / "custom.sqlite"

    result = run_cli(
        "sync",
        "--database",
        str(database_path),
        env_overrides=_env(workspace),
    )

    assert result.returncode == 0
    assert database_path.is_file()
    assert not (workspace["config_path"].parent / "knowledge.sqlite").exists()


def test_sync_reports_unhandled_formats_in_summary(workspace) -> None:
    workspace["corpus"].mkdir()
    (workspace["corpus"] / "notes.md").write_text("# Notes\n\nindexable")
    (workspace["corpus"] / "report.docx").write_text("office document placeholder")
    _write_config(workspace, include=("*.md", "*.docx"))

    result = run_cli("sync", env_overrides=_env(workspace))

    assert result.returncode == 0
    assert "1 created" in result.stdout
    assert "1 unhandled format" in result.stdout
    assert ".docx" in result.stdout


def test_sync_reports_skipped_token_shaped_content(workspace) -> None:
    workspace["corpus"].mkdir()
    (workspace["corpus"] / "notes.md").write_text("# Notes\n\nindexable")
    (workspace["corpus"] / "leaked.md").write_text("credential leaked: sk-" + "a" * 24)
    _write_config(workspace)

    result = run_cli("sync", env_overrides=_env(workspace))

    assert result.returncode == 0
    assert "1 created" in result.stdout
    assert "1 skipped (token-shaped content)" in result.stdout


def test_search_without_sync_reports_actionable_error(workspace) -> None:
    _write_config(workspace)

    result = run_cli("search", "anything", env_overrides=_env(workspace))

    assert result.returncode != 0
    assert "sync" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_search_denies_evidence_for_unauthorized_principal(workspace) -> None:
    workspace["corpus"].mkdir()
    (workspace["corpus"] / "architecture.md").write_text(
        "# Architecture\n\nprivate content for lee only."
    )
    _write_config(workspace)
    run_cli("sync", env_overrides=_env(workspace))

    result = run_cli(
        "search",
        "private",
        "--principal",
        "someone-else@example.com",
        env_overrides=_env(workspace),
    )

    assert result.returncode == 0
    assert "No evidence found" in result.stdout


def test_search_default_principal_is_configured_owner(workspace) -> None:
    workspace["corpus"].mkdir()
    (workspace["corpus"] / "architecture.md").write_text(
        "# Architecture\n\nunique-search-token appears here."
    )
    _write_config(workspace)
    run_cli("sync", env_overrides=_env(workspace))

    result = run_cli("search", "unique-search-token", env_overrides=_env(workspace))

    assert result.returncode == 0
    assert "architecture.md" in result.stdout
