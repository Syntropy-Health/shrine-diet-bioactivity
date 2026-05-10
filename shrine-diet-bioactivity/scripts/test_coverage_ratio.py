"""Compute and report the unit-vs-integration test ratio.

Usage:
    python scripts/test_coverage_ratio.py [--threshold 0.50] [--mode warn|fail]

Phase 1 of the integration-test coverage uplift plan registers a marker
taxonomy in ``pytest.ini``. This script runs ``pytest --collect-only -m <marker>``
for each marker and reports the ratio of integration-class tests
(``integration``, ``e2e``, ``live_llm``, ``live_llm_replay``, ``aura``) to the
sum of unit + integration tests.

Exit codes:
    0 — ratio at or above threshold (or warn mode)
    1 — ratio below threshold AND mode=fail
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_INTEGRATION_MARKERS = ("integration", "e2e", "live_llm", "live_llm_replay", "aura")
_UNIT_MARKERS = ("unit",)

# Match the pytest summary line in either form:
#   "407 tests collected in 10.47s"
#   "378/407 tests collected (29 deselected) in 3.67s"
# Captures the *collected* (first) number, not the total when filtered.
_COUNT_RE = re.compile(r"(\d+)(?:/\d+)?\s+tests?\s+collected")


def _collect(paths: list[str], marker: str | None = None) -> int:
    """Run pytest --collect-only and return the collected test count.

    Returns 0 if pytest exits non-zero with no count line (e.g. on import errors).
    """
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:warnings"]
    if marker is not None:
        cmd += ["-m", marker]
    cmd += paths
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    # Search bottom-up; the summary is on the last non-empty line(s)
    for line in reversed(output.splitlines()):
        match = _COUNT_RE.search(line)
        if match:
            return int(match.group(1))
        if "no tests ran" in line.lower():
            return 0
    return 0


def collect_marker_counts(test_paths: list[str]) -> dict:
    """Collect total + per-marker counts. Returns dict with unit, integration, untagged, total."""
    total = _collect(test_paths)

    unit_count = 0
    for marker in _UNIT_MARKERS:
        unit_count += _collect(test_paths, marker)

    integration_count = 0
    for marker in _INTEGRATION_MARKERS:
        integration_count += _collect(test_paths, marker)

    # An individual test may carry multiple markers in the integration set
    # (e.g. integration + aura). To get a true integration-class count we
    # use the union expression once, not the sum of per-marker collects.
    union_marker = " or ".join(_INTEGRATION_MARKERS)
    integration_total = _collect(test_paths, union_marker)

    untagged = max(total - unit_count - integration_total, 0)

    return {
        "unit": unit_count,
        "integration_total": integration_total,
        "integration_per_marker_sum": integration_count,
        "untagged": untagged,
        "total": total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.50,
                        help="Minimum fraction of (unit + integration) that must be integration. Default 0.50.")
    parser.add_argument("--mode", choices=["warn", "fail"], default="warn",
                        help="Exit non-zero when ratio < threshold (fail) vs print only (warn).")
    parser.add_argument("paths", nargs="*", default=["eval", "agents", "lightrag", "scripts"],
                        help="Paths to collect from (default: eval agents lightrag scripts).")
    args = parser.parse_args()

    # Resolve paths relative to the project root (parent of scripts/).
    project_root = Path(__file__).resolve().parents[1]
    resolved = [str((project_root / p).resolve()) for p in args.paths]

    counts = collect_marker_counts(resolved)

    denom = counts["unit"] + counts["integration_total"]
    print(f"Total tests:       {counts['total']}", flush=True)
    print(f"  unit:            {counts['unit']}", flush=True)
    print(f"  integration*:    {counts['integration_total']}", flush=True)
    print(f"    (per-marker sum, with double-counting: {counts['integration_per_marker_sum']})",
          flush=True)
    print(f"  untagged:        {counts['untagged']}", flush=True)

    if denom == 0:
        print("No tagged tests found — cannot compute ratio.", file=sys.stderr, flush=True)
        return 1

    ratio = counts["integration_total"] / denom
    print(f"  ratio (integration / (unit + integration)):"
          f" {ratio:.1%} (threshold: {args.threshold:.1%})",
          flush=True)

    untag_threshold = counts["total"] * 0.05
    if counts["untagged"] > untag_threshold:
        print(
            f"  WARNING: {counts['untagged']} tests untagged "
            f"(>{untag_threshold:.1f} = 5% of total)",
            file=sys.stderr,
            flush=True,
        )

    if ratio < args.threshold:
        delta = args.threshold - ratio
        print(f"  Below threshold by {delta:.1%}", file=sys.stderr, flush=True)
        if args.mode == "fail":
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
