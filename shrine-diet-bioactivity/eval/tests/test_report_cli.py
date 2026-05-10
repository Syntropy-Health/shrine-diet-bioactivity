"""Tests for eval/report.py __main__ CLI (Task F7).

Exercises the argparse CLI via subprocess so the actual __main__ block
is executed — no LLM calls, no filesystem side-effects on success paths
(mocked at the module boundary).

Tests:
  1. --help exits 0 and documents expected flags.
  2. Neither --latest nor --results-dir exits non-zero.
  3. Both --latest and --results-dir provided exits non-zero (mutually exclusive).
  4. --results-dir pointing to a non-existent path exits non-zero.
  5. --latest pointing to an empty directory exits non-zero (no run subdirs).
"""
from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PYTHON = sys.executable


def _run_cli(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_PYTHON, "-m", "eval.report", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),  # shrine-diet-bioactivity/
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Test 1 — --help exits 0 and lists expected flags
# ---------------------------------------------------------------------------


def test_report_cli_help_exits_zero_and_lists_flags():
    """--help must exit 0 and mention --latest and --results-dir."""
    result = _run_cli("--help")
    assert result.returncode == 0, f"--help returned non-zero: {result.stderr}"
    combined = result.stdout + result.stderr
    for flag in ("--latest", "--results-dir"):
        assert flag in combined, f"Flag {flag!r} not mentioned in --help output"


# ---------------------------------------------------------------------------
# Test 2 — no mode flag at all exits non-zero
# ---------------------------------------------------------------------------


def test_report_cli_no_mode_flag_exits_nonzero():
    """Running without --latest or --results-dir must exit non-zero."""
    result = _run_cli()
    assert result.returncode != 0, (
        "Expected non-zero exit when neither --latest nor --results-dir is given, got 0"
    )


# ---------------------------------------------------------------------------
# Test 3 — both --latest and --results-dir together exits non-zero
# ---------------------------------------------------------------------------


def test_report_cli_both_flags_together_exits_nonzero(tmp_path: Path):
    """Providing both --latest and --results-dir must exit non-zero
    (they are mutually exclusive)."""
    result = _run_cli(
        "--latest", str(tmp_path),
        "--results-dir", str(tmp_path),
    )
    assert result.returncode != 0, (
        "Expected non-zero exit when both --latest and --results-dir provided, got 0"
    )


# ---------------------------------------------------------------------------
# Test 4 — --results-dir pointing to non-existent path exits non-zero
# ---------------------------------------------------------------------------


def test_report_cli_nonexistent_results_dir_exits_nonzero(tmp_path: Path):
    """Pointing --results-dir at a path that does not exist must exit non-zero."""
    result = _run_cli("--results-dir", str(tmp_path / "does_not_exist"))
    assert result.returncode != 0, (
        "Expected non-zero exit when --results-dir path does not exist, got 0"
    )


# ---------------------------------------------------------------------------
# Test 5 — --latest with no timestamped subdirs exits non-zero
# ---------------------------------------------------------------------------


def test_report_cli_latest_with_empty_results_dir_exits_nonzero(tmp_path: Path):
    """--latest pointing to a directory with no timestamped run subdirs must
    exit non-zero (nothing to render)."""
    # tmp_path is a real dir but has no subdirs
    result = _run_cli("--latest", str(tmp_path))
    assert result.returncode != 0, (
        "Expected non-zero exit when --latest dir has no run subdirs, got 0"
    )
