#!/usr/bin/env python3
"""Compute the real-integration vs unit test ratio across the project.

Implements the Phase 1 deliverable of
`research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md`.

Behavior
--------
Walks the project's Python test trees (excluding the LightRAG submodule's own
test suite and any worktrees), enumerates each `def test_*` (including class-
nested test methods), and combines file-level `pytestmark` declarations with
per-function `@pytest.mark.<name>` decorators to classify EACH TEST as one of:

  - real_integration : has any of `integration` | `e2e` | `live_llm` |
                       `live_llm_replay` | `aura`
  - unit             : has `unit` but no real-integration marker
  - untagged         : has neither

Counts are per-test (a file with one `@pytest.mark.live_llm` function and one
`@pytest.mark.unit` function contributes 1 to each bucket, not 2 to either).

Ratio = real_integration_count / (real_integration_count + unit_count).
Untagged tests are reported but excluded from the denominator (with a
warning if untagged ratio > 5% of total).

The lane-breakdown table uses a priority column policy (e2e > aura > live_llm
> live_llm_replay > integration > unit) so each test contributes to exactly
one column — Σ(columns) == Tests always holds.

CLI
---
    python scripts/test_coverage_ratio.py [--mode warn|fail]
                                          [--threshold 0.50]
                                          [--csv PATH]
                                          [--json]

Exit codes
----------
    0  - mode=warn always; mode=fail when ratio >= threshold
    1  - mode=fail and ratio < threshold

Implementation note
-------------------
Uses Python's `ast` module rather than `pytest --collect-only` because the
test suite spans three import roots (`mcp/`, `shrine-diet-bioactivity/`,
`shrine-diet-bioactivity/lightrag/`) with differing sys.path requirements;
a single pytest invocation can't collect them all without environment
setup. Static analysis is deterministic and CI-portable.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REAL_INTEGRATION_MARKERS = frozenset(
    {"integration", "e2e", "live_llm", "live_llm_replay", "aura"}
)
UNIT_MARKER = "unit"
SLOW_MARKER = "slow"
ALL_TRACKED_MARKERS = REAL_INTEGRATION_MARKERS | {UNIT_MARKER, SLOW_MARKER}

# Priority order for the lane-breakdown table — each test contributes to
# EXACTLY ONE column. Without this, a test tagged `[integration, aura, slow]`
# would double-count in three columns and the row would visibly violate
# Σ(columns) == Tests.
COLUMN_PRIORITY: tuple[str, ...] = (
    "e2e",
    "aura",
    "live_llm",
    "live_llm_replay",
    "integration",
    UNIT_MARKER,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Lane definition: (lane_name, root_path, recursive?, filename_glob)
# Order matters for stable output.
LANES: tuple[tuple[str, Path, bool, str], ...] = (
    ("mcp/tests/unit", REPO_ROOT / "mcp" / "tests" / "unit", True, "test_*.py"),
    ("mcp/tests/e2e", REPO_ROOT / "mcp" / "tests" / "e2e", True, "test_*.py"),
    (
        "shrine/eval/tests",
        REPO_ROOT / "shrine-diet-bioactivity" / "eval" / "tests",
        True,
        "test_*.py",
    ),
    (
        "shrine/agents/tests",
        REPO_ROOT / "shrine-diet-bioactivity" / "agents" / "tests",
        True,
        "test_*.py",
    ),
    (
        "shrine/lightrag",
        REPO_ROOT / "shrine-diet-bioactivity" / "lightrag",
        False,  # non-recursive: top-level test_*.py only (not lightrag/tests/ submodule)
        "test_*.py",
    ),
    (
        "shrine/scripts/tests",
        REPO_ROOT / "shrine-diet-bioactivity" / "scripts" / "tests",
        True,
        "test_*.py",
    ),
)


@dataclass(frozen=True)
class TestRecord:
    """One pytest test (function or class method) with its effective markers
    (file-level pytestmark ∪ per-function decorators)."""

    name: str
    markers: frozenset[str]

    @property
    def classification(self) -> str:
        if self.markers & REAL_INTEGRATION_MARKERS:
            return "real_integration"
        if UNIT_MARKER in self.markers:
            return "unit"
        return "untagged"

    @property
    def primary_column(self) -> str:
        for m in COLUMN_PRIORITY:
            if m in self.markers:
                return m
        return "untagged"


@dataclass(frozen=True)
class FileReport:
    path: Path
    lane: str
    file_markers: frozenset[str]
    tests: tuple[TestRecord, ...]

    @property
    def test_count(self) -> int:
        return len(self.tests)


@dataclass
class LaneStats:
    """Per-lane test counts. Columns are MUTUALLY EXCLUSIVE via COLUMN_PRIORITY,
    so Σ(columns) == test_count always holds. `slow` is an overlay marker
    tracked separately for visibility (a slow test still lands in its primary
    column)."""

    lane: str
    files: int = 0
    test_count: int = 0
    unit: int = 0
    integration: int = 0
    e2e: int = 0
    live_llm: int = 0
    live_llm_replay: int = 0
    aura: int = 0
    slow: int = 0  # overlay: tests with @pytest.mark.slow regardless of primary
    untagged: int = 0


def _extract_markers_from_value(node: ast.expr) -> set[str]:
    """Resolve `pytest.mark.X` / `pytest.mark.X(...)` / list-of-marks → marker names."""
    markers: set[str] = set()

    def _walk(n: ast.expr) -> None:
        if isinstance(n, (ast.List, ast.Tuple)):
            for elt in n.elts:
                _walk(elt)
            return
        # pytest.mark.NAME
        if isinstance(n, ast.Attribute):
            target = n
            if isinstance(target.value, ast.Attribute) and target.value.attr == "mark":
                markers.add(target.attr)
            return
        # pytest.mark.NAME(...)
        if isinstance(n, ast.Call):
            _walk(n.func)
            return

    _walk(node)
    return markers


def _extract_file_pytestmark(tree: ast.Module) -> set[str]:
    """Read top-level `pytestmark = pytest.mark.X` (or a list of marks)."""
    markers: set[str] = set()
    for stmt in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            if stmt.target is not None and stmt.value is not None:
                targets = [stmt.target]
                value = stmt.value
        if not targets or value is None:
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name) and tgt.id == "pytestmark":
                markers.update(_extract_markers_from_value(value))
    return markers


def _extract_test_records(
    tree: ast.Module, file_markers: frozenset[str]
) -> tuple[TestRecord, ...]:
    """Enumerate `def test_*` functions (including class-nested) and return a
    `TestRecord` for each with markers = file_markers ∪ per-function decorators.
    """
    records: list[TestRecord] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        per_func: set[str] = set()
        for deco in node.decorator_list:
            per_func.update(_extract_markers_from_value(deco))
        markers = frozenset(file_markers | per_func)
        records.append(TestRecord(name=node.name, markers=markers))
    return tuple(records)


def analyze_file(path: Path, lane: str) -> FileReport | None:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return None
    file_markers = frozenset(_extract_file_pytestmark(tree))
    tests = _extract_test_records(tree, file_markers)
    if not tests:
        return None
    return FileReport(path=path, lane=lane, file_markers=file_markers, tests=tests)


def collect_lane(lane: str, root: Path, recursive: bool, glob: str) -> list[FileReport]:
    if not root.is_dir():
        return []
    reports: list[FileReport] = []
    pattern = f"**/{glob}" if recursive else glob
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        # Skip nested submodule tests if a recursive lane accidentally crosses one.
        if "lightrag/tests" in path.as_posix() and lane != "shrine/lightrag":
            continue
        report = analyze_file(path, lane)
        if report is not None:
            reports.append(report)
    return reports


def summarize(reports: list[FileReport]) -> dict[str, LaneStats]:
    stats: dict[str, LaneStats] = {lane: LaneStats(lane=lane) for lane, *_ in LANES}
    for r in reports:
        s = stats[r.lane]
        s.files += 1
        s.test_count += r.test_count
        for t in r.tests:
            column = t.primary_column
            if column == "e2e":
                s.e2e += 1
            elif column == "aura":
                s.aura += 1
            elif column == "live_llm":
                s.live_llm += 1
            elif column == "live_llm_replay":
                s.live_llm_replay += 1
            elif column == "integration":
                s.integration += 1
            elif column == UNIT_MARKER:
                s.unit += 1
            else:
                s.untagged += 1
            if SLOW_MARKER in t.markers:
                s.slow += 1
    return stats


def _row(s: LaneStats) -> tuple[str, ...]:
    return (
        s.lane,
        str(s.files),
        str(s.test_count),
        str(s.unit),
        str(s.integration),
        str(s.e2e),
        str(s.live_llm),
        str(s.live_llm_replay),
        str(s.aura),
        str(s.slow),
        str(s.untagged),
    )


def render_table(stats: dict[str, LaneStats]) -> str:
    headers = (
        "Lane",
        "Files",
        "Tests",
        "Unit",
        "Integration",
        "E2E",
        "Live_LLM",
        "LLM_Replay",
        "Aura",
        "Slow*",
        "Untagged",
    )
    rows = [_row(s) for s in stats.values()]
    totals = LaneStats(lane="TOTAL")
    for s in stats.values():
        totals.files += s.files
        totals.test_count += s.test_count
        totals.unit += s.unit
        totals.integration += s.integration
        totals.e2e += s.e2e
        totals.live_llm += s.live_llm
        totals.live_llm_replay += s.live_llm_replay
        totals.aura += s.aura
        totals.slow += s.slow
        totals.untagged += s.untagged
    rows.append(_row(totals))

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def fmt(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    lines = [fmt(headers), fmt(tuple("-" * w for w in widths))]
    lines.extend(fmt(r) for r in rows[:-1])
    lines.append(fmt(tuple("-" * w for w in widths)))
    lines.append(fmt(rows[-1]))
    lines.append("")
    lines.append(
        "Columns are mutually exclusive (priority: e2e > aura > live_llm "
        "> live_llm_replay > integration > unit > untagged)."
    )
    lines.append("Σ(Unit..Untagged) == Tests per row.")
    lines.append("* Slow is an overlay marker — slow tests still appear in their primary column.")
    return "\n".join(lines)


def _file_classification(r: FileReport) -> str:
    """Per-file roll-up for the audit CSV. Mixed-marker files are flagged."""
    classifications = {t.classification for t in r.tests}
    if classifications == {"real_integration"}:
        return "real_integration"
    if classifications == {"unit"}:
        return "unit"
    if classifications == {"untagged"}:
        return "untagged"
    return "mixed:" + "+".join(sorted(classifications))


def write_csv(stats: dict[str, LaneStats], reports: list[FileReport], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["lane", "file", "test_count", "file_markers", "classification"]
        )
        for r in reports:
            writer.writerow(
                [
                    r.lane,
                    r.path.relative_to(REPO_ROOT).as_posix(),
                    r.test_count,
                    "|".join(sorted(r.file_markers)) or "-",
                    _file_classification(r),
                ]
            )
        writer.writerow([])
        writer.writerow(
            [
                "lane_summary",
                "files",
                "tests",
                "unit",
                "integration",
                "e2e",
                "live_llm",
                "live_llm_replay",
                "aura",
                "slow",
                "untagged",
            ]
        )
        for s in stats.values():
            writer.writerow(
                [
                    s.lane,
                    s.files,
                    s.test_count,
                    s.unit,
                    s.integration,
                    s.e2e,
                    s.live_llm,
                    s.live_llm_replay,
                    s.aura,
                    s.slow,
                    s.untagged,
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--mode",
        choices=("warn", "fail"),
        default="warn",
        help="warn: always exit 0; fail: exit 1 if ratio < threshold",
    )
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--csv", type=Path, default=None, help="Write per-file audit CSV")
    parser.add_argument("--json", action="store_true", help="Print summary as JSON")
    parser.add_argument(
        "--untagged-warn-ratio",
        type=float,
        default=0.05,
        help="Print warning if untagged tests exceed this fraction of total",
    )
    args = parser.parse_args(argv)

    all_reports: list[FileReport] = []
    for lane, root, recursive, glob in LANES:
        all_reports.extend(collect_lane(lane, root, recursive, glob))

    stats = summarize(all_reports)

    # Per-test counting: a file with one live_llm test + one unit test
    # contributes 1 to each bucket (not 2 to either).
    all_tests = [t for r in all_reports for t in r.tests]
    real = sum(1 for t in all_tests if t.classification == "real_integration")
    unit = sum(1 for t in all_tests if t.classification == "unit")
    untagged = sum(1 for t in all_tests if t.classification == "untagged")
    total = real + unit + untagged
    denominator = real + unit
    ratio = (real / denominator) if denominator else 0.0
    untagged_ratio = (untagged / total) if total else 0.0

    if args.csv is not None:
        write_csv(stats, all_reports, args.csv)

    if args.json:
        payload = {
            "real_integration_count": real,
            "unit_count": unit,
            "untagged_count": untagged,
            "total": total,
            "ratio": round(ratio, 4),
            "threshold": args.threshold,
            "mode": args.mode,
            "untagged_ratio": round(untagged_ratio, 4),
            "lanes": {
                s.lane: {
                    "files": s.files,
                    "tests": s.test_count,
                    "unit": s.unit,
                    "integration": s.integration,
                    "e2e": s.e2e,
                    "live_llm": s.live_llm,
                    "live_llm_replay": s.live_llm_replay,
                    "aura": s.aura,
                    "slow": s.slow,
                    "untagged": s.untagged,
                }
                for s in stats.values()
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render_table(stats))
        print()
        print(f"Real-integration tests: {real}")
        print(f"Unit tests:             {unit}")
        print(f"Untagged tests:         {untagged}")
        print(f"Total:                  {total}")
        print(f"Ratio (real / real+unit): {ratio:.1%}")
        print(f"Threshold:               {args.threshold:.0%}")
        print(f"Mode:                    {args.mode}")

    if untagged and untagged_ratio > args.untagged_warn_ratio:
        print(
            f"\nWARNING: {untagged}/{total} tests ({untagged_ratio:.1%}) lack a "
            "recognized marker. First 20 files with untagged tests:",
            file=sys.stderr,
        )
        listed = 0
        for r in all_reports:
            untagged_in_file = sum(1 for t in r.tests if t.classification == "untagged")
            if not untagged_in_file:
                continue
            rel = r.path.relative_to(REPO_ROOT).as_posix()
            print(f"  - {rel} ({untagged_in_file} untagged tests)", file=sys.stderr)
            listed += 1
            if listed >= 20:
                break

    if args.mode == "fail" and ratio < args.threshold:
        print(
            f"\nFAIL: ratio {ratio:.1%} < threshold {args.threshold:.0%}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
