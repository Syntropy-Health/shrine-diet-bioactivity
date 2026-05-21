"""Phase 4 — re-render reproducibility (Category F).

Plan ref: research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md
test #16 — test_report_rerender_summary_md_byte_diff.

Re-renders the committed paper-grade run `20260504T042540Z` and asserts the
regenerated `summary.md` + `paired_tests.md` METRIC TABLES match the
committed copies: cell text (system names, metric names, column headers)
byte-exact, numeric values within tolerance.

Why tolerance, not byte-diff (the plan's literal ask):
  1. The committed artifacts were rendered with bootstrap B=1000 (the
     `paired_tests.md` header states it); the eval.report CLI now hard-uses
     B=10000. This test calls `render_report()` directly with
     `n_bootstrap=1000` to match — so the only residual numeric drift is
     numpy-version RNG variation, bounded by `_FLOAT_TOL`.
  2. The renderer's prose/header lines changed format since the committed
     run (e.g. "Bootstrap iterations: 1000" → "Bootstrap iterations:
     B = ..."). Those lines are excluded; only the metric TABLES are
     compared — the tables are what "reproducibility" actually means here.
  3. `paired_tests.md`'s p-value columns (`p_raw`, `p_adj`) use the
     Davison-Hinkley (k+1)/(B+1) estimator, which was adopted AFTER the
     committed artifacts were rendered (committed p-values use the older
     plain-bootstrap estimate). Those two columns are excluded from value
     comparison — their column POSITION is still structurally checked.
     The reproducible content (`mean_diff`, `CI_lo`, `CI_hi`) is compared.

A structural change (renamed system, dropped column, NaN cell, formula
change moving a metric > tolerance) still fails the test.

Local-only (no network); marked `integration` + `slow` (the bootstrap
across 6 systems takes tens of seconds → nightly lane, not the fast
per-PR `-m "integration and not slow"` lane).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
from eval.report import (  # type: ignore[import-not-found]
    build_source_attribution_runner,
    load_run_scenarios,
    render_report,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_REPO_ROOT = Path(__file__).resolve().parents[4]
_RESULTS_DIR = (
    _REPO_ROOT / "research-journal" / "shared" / "results" / "20260504T042540Z"
)

# The committed artifacts were rendered with bootstrap B=1000.
_COMMITTED_N_BOOTSTRAP = 1000
# Tolerance for a single numeric cell. Generous enough for numpy-version RNG
# drift at matched B + seed, tight enough to catch a real metric regression.
_FLOAT_TOL = 0.01

_FLOAT = re.compile(r"\d+\.\d+")
_NUMRUN = re.compile(r"\d+\.?\d*")


def _load_run_results(results_dir: Path) -> dict[str, list[ResearchSynthesis]]:
    """Replicate eval.report's CLI loading: manifest → per-system predictions."""
    manifests = sorted(results_dir.glob("manifest-*.json"))
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    scenario_ids: list[str] = manifest["scenario_ids"]
    systems: list[str] = manifest["systems"]

    run_results: dict[str, list[ResearchSynthesis]] = {}
    for sys_name in systems:
        sys_dir = results_dir / sys_name
        preds: list[ResearchSynthesis] = []
        for scen_id in scenario_ids:
            pred_path = sys_dir / f"{scen_id}.json"
            if pred_path.exists():
                preds.append(
                    ResearchSynthesis.model_validate_json(
                        pred_path.read_text(encoding="utf-8")
                    )
                )
        run_results[sys_name] = preds
    return run_results


def _source_attribution_runner(run_results: dict[str, list[ResearchSynthesis]]):
    """Committed summary shows a computed Provenance column, so the original
    render used the source-attribution cypher runner. Rebuild it."""
    edge_to_source: dict[tuple[str, str, str], str] = {}
    for preds in run_results.values():
        for pred in preds:
            for chain in pred.candidate_chains:
                for e in chain.edges:
                    edge_to_source[(e.src, e.edge, e.tgt)] = e.source_id or ""
    return build_source_attribution_runner(edge_to_source)


def _table_rows(md: str) -> list[list[str]]:
    """Markdown table rows as cell lists, excluding `--- | ---` separators."""
    rows: list[list[str]] = []
    for line in md.splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):  # separator row
            continue
        rows.append(cells)
    return rows


def _assert_cell_matches(committed: str, rerender: str, where: str) -> None:
    """A cell's non-numeric skeleton must match exactly; its numeric values
    must match within tolerance."""
    assert _NUMRUN.sub("#", committed) == _NUMRUN.sub("#", rerender), (
        f"{where}: cell structure differs\n"
        f"  committed: {committed!r}\n  rerender:  {rerender!r}"
    )
    c_floats = [float(x) for x in _FLOAT.findall(committed)]
    r_floats = [float(x) for x in _FLOAT.findall(rerender)]
    assert len(c_floats) == len(r_floats), f"{where}: float count differs"
    for cf, rf in zip(c_floats, r_floats):
        assert abs(cf - rf) <= _FLOAT_TOL, (
            f"{where}: {cf} vs {rf} exceeds tolerance {_FLOAT_TOL}\n"
            f"  committed: {committed!r}\n  rerender:  {rerender!r}"
        )


def _assert_tables_match(
    committed_md: str,
    rerender_md: str,
    fname: str,
    skip_value_cols: frozenset[int] = frozenset(),
) -> None:
    """Compare every markdown table row. `skip_value_cols` columns still have
    their cell COUNT checked (structure) but not their value (used for the
    method-drifted p-value columns)."""
    c_rows = _table_rows(committed_md)
    r_rows = _table_rows(rerender_md)
    assert len(c_rows) == len(r_rows), (
        f"{fname}: table row count differs — "
        f"committed={len(c_rows)} rerender={len(r_rows)}"
    )
    for i, (c_row, r_row) in enumerate(zip(c_rows, r_rows)):
        assert len(c_row) == len(r_row), (
            f"{fname} row {i}: cell count differs "
            f"({len(c_row)} vs {len(r_row)})"
        )
        for j, (c_cell, r_cell) in enumerate(zip(c_row, r_row)):
            if j in skip_value_cols:
                continue
            _assert_cell_matches(c_cell, r_cell, f"{fname} row {i} col {j}")


def test_report_rerender_summary_md_byte_diff(tmp_path: Path) -> None:
    """eval.report re-render reproduces the committed metric tables."""
    if not _RESULTS_DIR.is_dir():
        pytest.skip(f"results dir not present: {_RESULTS_DIR}")

    run_results = _load_run_results(_RESULTS_DIR)
    assert run_results, "no predictions loaded from results dir"

    # load_run_scenarios resolves the benchmark relative to the REAL results
    # dir (results_dir.parents[1]/datasets/...), which exists in-repo.
    run_scenarios = load_run_scenarios(_RESULTS_DIR)
    min_len = min(len(v) for v in run_results.values())
    if min_len < len(run_scenarios):
        run_scenarios = run_scenarios[:min_len]

    render_report(
        run_results,
        run_scenarios,
        out_dir=tmp_path,
        cypher_runner=_source_attribution_runner(run_results),
        n_bootstrap=_COMMITTED_N_BOOTSTRAP,
        seed=42,
    )

    # summary.md — every metric cell compared.
    _assert_tables_match(
        (_RESULTS_DIR / "summary.md").read_text(encoding="utf-8"),
        (tmp_path / "summary.md").read_text(encoding="utf-8"),
        "summary.md",
    )

    # paired_tests.md — columns are
    #   0:System 1:Metric 2:mean_diff 3:CI_lo 4:CI_hi 5:p_raw 6:p_adj
    # Skip the two p-value columns (Davison-Hinkley estimator post-dates the
    # committed artifact); compare effect sizes + CIs.
    _assert_tables_match(
        (_RESULTS_DIR / "paired_tests.md").read_text(encoding="utf-8"),
        (tmp_path / "paired_tests.md").read_text(encoding="utf-8"),
        "paired_tests.md",
        skip_value_cols=frozenset({5, 6}),
    )
