"""Smoke tests for the bootstrap command-line surface."""

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the package entry point from a source checkout."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "lee-kb.main", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_describes_governed_retrieval() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "governed knowledge fabric" in result.stdout
    assert "ingestion and retrieval pipeline" in result.stdout


def test_version_reports_package_version() -> None:
    result = run_cli("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == "lee-kb 0.1.0"
