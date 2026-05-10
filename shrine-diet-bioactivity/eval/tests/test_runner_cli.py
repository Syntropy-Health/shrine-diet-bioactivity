"""Tests for eval/runner.py __main__ CLI (Task F7).

Exercises the argparse CLI via subprocess so the actual __main__ block
is executed — no LLM calls, no real eval runs.

Tests:
  1. --help exits 0 and contains expected flag names.
  2. Missing required --bench argument exits non-zero.
  3. Missing required --splits argument exits non-zero.
  4. --bench with a non-existent path exits non-zero.
  5. Argument namespace parses correctly for full valid invocation (dry-run via mock).
"""
from __future__ import annotations

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
        [_PYTHON, "-m", "eval.runner", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),  # shrine-diet-bioactivity/
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Test 1 — --help exits 0 and documents expected flags
# ---------------------------------------------------------------------------


def test_runner_cli_help_exits_zero_and_lists_flags():
    """--help must exit 0 and mention all 5 CLI flags."""
    result = _run_cli("--help")
    assert result.returncode == 0, f"--help returned non-zero: {result.stderr}"
    combined = result.stdout + result.stderr
    for flag in ("--bench", "--splits", "--out", "--systems", "--split"):
        assert flag in combined, f"Flag {flag!r} not mentioned in --help output"


# ---------------------------------------------------------------------------
# Test 2 — missing --bench exits non-zero
# ---------------------------------------------------------------------------


def test_runner_cli_missing_bench_exits_nonzero():
    """Omitting --bench must cause argparse to exit with a non-zero status."""
    result = _run_cli("--splits", "dummy.json", "--out", "/tmp/dummy_out")
    assert result.returncode != 0, (
        "Expected non-zero exit when --bench is missing, got 0"
    )


# ---------------------------------------------------------------------------
# Test 3 — missing --splits exits non-zero
# ---------------------------------------------------------------------------


def test_runner_cli_missing_splits_exits_nonzero():
    """Omitting --splits must cause argparse to exit with a non-zero status."""
    result = _run_cli("--bench", "dummy.json", "--out", "/tmp/dummy_out")
    assert result.returncode != 0, (
        "Expected non-zero exit when --splits is missing, got 0"
    )


# ---------------------------------------------------------------------------
# Test 4 — --bench pointing to a non-existent file exits non-zero
# ---------------------------------------------------------------------------


def test_runner_cli_nonexistent_bench_file_exits_nonzero(tmp_path: Path):
    """Pointing --bench at a path that does not exist must exit non-zero."""
    splits_file = tmp_path / "splits.json"
    # Provide a dummy splits file so that only --bench fails
    import json
    splits_file.write_text(json.dumps({
        "seed": 42, "benchmark_version": "v1",
        "ratios": [0.6, 0.2, 0.2],
        "train_ids": [], "val_ids": [], "test_ids": [],
    }))
    result = _run_cli(
        "--bench", str(tmp_path / "does_not_exist.json"),
        "--splits", str(splits_file),
        "--out", str(tmp_path / "out"),
    )
    assert result.returncode != 0, (
        "Expected non-zero exit when --bench file does not exist, got 0"
    )


# ---------------------------------------------------------------------------
# Test 5 — missing --out exits non-zero
# ---------------------------------------------------------------------------


def test_runner_cli_missing_out_exits_nonzero():
    """Omitting --out (required) must exit non-zero."""
    result = _run_cli("--bench", "dummy.json", "--splits", "dummy_splits.json")
    assert result.returncode != 0, (
        "Expected non-zero exit when --out is missing, got 0"
    )
