"""Results reporter for DietResearchBench-Clinical (Task F6).

Given the results dict produced by the runner and the scenario list, renders:
  summary.md            — 6 systems × 6 metrics table with bootstrap 95% CI
  reliability_diagram.png — confidence vs accuracy (one line per system)
  per_system/<sys>/per_metric.json — full numerical breakdown per system
  paired_tests.md       — Diet-OS vs each baseline, paired bootstrap p-values
                          with Bonferroni correction

Public API
----------
render_report(results, scenarios, out_dir, *, cypher_runner=None,
              n_bootstrap=1000, seed=42) -> dict
    Returns a JSON-serialisable dict of
    {metric_name: {system_name: {mean, ci_lo, ci_hi}}}.

bootstrap_ci(values, n_iter=1000, seed=42, alpha=0.05) -> tuple[float, float]
    Percentile bootstrap; default 95% CI.
"""
from __future__ import annotations

# Bootstrap sys.path so this module works when invoked directly as
# `python3 -m eval.report` without a prior conftest.py (e.g. CLI, Makefile).
# When pytest runs, conftest.py has already done this — the inserts are no-ops.
import sys as _sys
from pathlib import Path as _Path
_REPO = _Path(__file__).resolve().parent.parent  # shrine-diet-bioactivity/
for _sub in ("", "lightrag", "agents"):
    _p = str(_REPO / _sub) if _sub else str(_REPO)
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
# Pyright thinks the for-loop body might not execute; the tuple is hardcoded
# 3 elements so _sub/_p are always bound at runtime. Same silencing pattern
# as agents/run_case_study.py and eval/runner.py.
del _sys, _Path, _REPO  # type: ignore[name-defined]

import json
import math
import random
from pathlib import Path
from typing import Any, Callable

# Use Agg backend BEFORE any other matplotlib import to allow headless PNG
# rendering in CI environments without a display.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)

from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
from eval.metrics import (  # type: ignore[import-not-found]
    bilingual_coverage,
    defer_accuracy,
    expected_calibration_error,
    hdi_safety_recall,
    provenance_faithfulness,
    verdict_agreement_kappa,
)
from eval.scenario import Scenario  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_METRICS = [
    "verdict_kappa",
    "ece",
    "hdi_recall",
    "provenance",
    "defer_acc",
    "bilingual",
]

_METRIC_LABELS = {
    "verdict_kappa": "Verdict κ",
    "ece": "ECE",
    "hdi_recall": "HDI Recall",
    "provenance": "Provenance",
    "defer_acc": "Defer Acc",
    "bilingual": "Bilingual",
}

# ---------------------------------------------------------------------------
# Provenance: source-attribution runner
# ---------------------------------------------------------------------------

KNOWN_KG_SOURCE_PREFIXES = (
    "cmaup:", "duke:", "herb2:", "symmap:", "hdi-safe-50:",
)


def build_source_attribution_runner(
    edge_to_source: dict[tuple[str, str, str], str],
) -> Callable[[str, str, str], bool]:
    """Build a cypher_runner that returns True iff edge.source_id starts
    with a known KG-dataset prefix.

    Edges retrieved by Layer-B/C MCP traversals carry source_id like
    'cmaup:plant_disease', 'duke:found_in_food', etc. — these are
    KG-faithful by construction (the gateway just queried them). Any
    other prefix (e.g., 'llm:...', '') indicates an edge that did NOT
    come from the live KG.

    Per Paper 1 §E2: this is the v1 provenance proxy. Full Cypher
    round-trip verification deferred to v2 (would call back into MCP
    Layer-B for each edge, ~2.5 min on free-tier).
    """
    def runner(src: str, edge: str, tgt: str) -> bool:
        source_id = edge_to_source.get((src, edge, tgt), "")
        return any(source_id.startswith(p) for p in KNOWN_KG_SOURCE_PREFIXES)
    return runner


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------


def bootstrap_ci(
    values: list[float],
    n_iter: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap; default 95% CI (alpha=0.05).

    Args:
        values: List of numeric sample values.
        n_iter: Number of bootstrap iterations (default 1000).
        seed:   Random seed for reproducibility.
        alpha:  Significance level — CI covers 1 - alpha (default 0.05 → 95%).

    Returns:
        (lo, hi) — lower and upper percentile bounds of the bootstrap
        distribution of the mean.
    """
    n = len(values)
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_iter):
        sample = [values[rng.randint(0, n - 1)] for _ in range(n)]
        boots.append(sum(sample) / n)
    boots.sort()
    lo_idx = int(n_iter * alpha / 2)
    hi_idx = int(n_iter * (1 - alpha / 2))
    return boots[lo_idx], boots[hi_idx]


# ---------------------------------------------------------------------------
# Internal: compute raw per-bootstrap metric values for a single system
# ---------------------------------------------------------------------------


def _compute_metric_value(
    metric: str,
    predictions: list[ResearchSynthesis],
    scenarios: list[Scenario],
    cypher_runner: Any,
) -> float:
    """Evaluate one metric for one system on a fixed (pred, scen) list."""
    if metric == "verdict_kappa":
        return verdict_agreement_kappa(predictions, scenarios)
    elif metric == "ece":
        return expected_calibration_error(predictions, scenarios)
    elif metric == "hdi_recall":
        return hdi_safety_recall(predictions, scenarios)
    elif metric == "provenance":
        if cypher_runner is None:
            return float("nan")
        return provenance_faithfulness(predictions, cypher_runner)
    elif metric == "defer_acc":
        return defer_accuracy(predictions, scenarios)
    elif metric == "bilingual":
        return bilingual_coverage(predictions, scenarios)
    else:
        raise ValueError(f"Unknown metric: {metric!r}")


def _bootstrap_metric(
    metric: str,
    predictions: list[ResearchSynthesis],
    scenarios: list[Scenario],
    cypher_runner: Any,
    n_bootstrap: int,
    seed: int,
) -> tuple[float | None, float | None, float | None]:
    """Bootstrap the mean and 95% CI for a single (metric, system) cell.

    Returns (mean, ci_lo, ci_hi) as floats, or (None, None, None) if the
    metric is undefined (NaN) for this system/scenario combination.
    """
    n = len(predictions)
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_bootstrap):
        indices = [rng.randint(0, n - 1) for _ in range(n)]
        preds_s = [predictions[i] for i in indices]
        scens_s = [scenarios[i] for i in indices]
        val = _compute_metric_value(metric, preds_s, scens_s, cypher_runner)
        if not math.isnan(val):
            boots.append(val)

    if not boots:
        return None, None, None

    mean_val = sum(boots) / len(boots)
    boots.sort()
    alpha = 0.05
    lo_idx = int(len(boots) * alpha / 2)
    hi_idx = int(len(boots) * (1 - alpha / 2))
    # Clamp indices to valid range
    hi_idx = min(hi_idx, len(boots) - 1)
    return mean_val, boots[lo_idx], boots[hi_idx]


# ---------------------------------------------------------------------------
# Internal: reliability diagram
# ---------------------------------------------------------------------------


def _render_reliability_diagram(
    results: dict[str, list[ResearchSynthesis]],
    scenarios: list[Scenario],
    out_path: Path,
) -> None:
    """Render a reliability (calibration) diagram and save as PNG.

    x-axis: mean predicted confidence in each bin (10 bins over [0,1])
    y-axis: empirical accuracy in each bin
    Diagonal y=x for perfect calibration.
    One coloured line per system.
    """
    n_bins = 10
    bin_edges = [i / n_bins for i in range(n_bins + 1)]

    fig, ax = plt.subplots(figsize=(7, 6))

    # Perfect calibration reference line
    ax.plot([0, 1], [0, 1], "k--", linewidth=1.2, label="Perfect calibration")

    for sys_name, preds in results.items():
        bin_mean_confs: list[float] = []
        bin_accuracies: list[float] = []

        for i in range(n_bins):
            lo = bin_edges[i]
            hi = bin_edges[i + 1]
            indices = [
                j
                for j, p in enumerate(preds)
                if lo <= p.confidence < hi or (hi >= 1.0 and p.confidence == 1.0)
            ]
            if not indices:
                continue
            mean_conf = sum(preds[j].confidence for j in indices) / len(indices)
            # Accuracy: fraction where majority verdict == gold verdict
            correct = sum(
                1
                for j in indices
                if _majority_verdict_local(preds[j]) == scenarios[j].gold.expected_panel_verdict
            )
            accuracy = correct / len(indices)
            bin_mean_confs.append(mean_conf)
            bin_accuracies.append(accuracy)

        if bin_mean_confs:
            ax.plot(bin_mean_confs, bin_accuracies, marker="o", markersize=4, label=sys_name)

    ax.set_xlabel("Mean predicted confidence (bin)")
    ax.set_ylabel("Empirical accuracy")
    ax.set_title("Reliability diagram — confidence vs accuracy")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def _majority_verdict_local(rs: ResearchSynthesis) -> str:
    """Local copy so report.py has no circular dependency on metrics.py."""
    counts: dict[str, int] = {}
    for rv in rs.panel.verdicts:
        counts[rv.verdict] = counts.get(rv.verdict, 0) + 1
    if not counts:
        return "abstain"
    return max(counts.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# Internal: paired bootstrap test (diet_os vs baseline on one metric)
# ---------------------------------------------------------------------------


def _paired_bootstrap_pvalue(
    diet_os_scores: list[float],
    baseline_scores: list[float],
    n_iter: int,
    seed: int,
) -> tuple[float, float, float, float]:
    """Paired bootstrap: p-value that diet_os is NOT better than baseline.

    For each bootstrap iteration, resample (diet_os_score, baseline_score)
    pairs with replacement and compute mean difference = mean(diet_os) - mean(baseline).
    p-value = fraction of iterations where difference <= 0.

    Returns:
        (mean_diff, ci_lo, ci_hi, p_value)
    """
    n = len(diet_os_scores)
    rng = random.Random(seed)
    diffs: list[float] = []

    for _ in range(n_iter):
        indices = [rng.randint(0, n - 1) for _ in range(n)]
        d_mean = sum(diet_os_scores[i] for i in indices) / n
        b_mean = sum(baseline_scores[i] for i in indices) / n
        diffs.append(d_mean - b_mean)

    mean_diff = sum(diffs) / len(diffs)
    diffs.sort()
    alpha = 0.05
    lo_idx = int(n_iter * alpha / 2)
    hi_idx = int(n_iter * (1 - alpha / 2))
    hi_idx = min(hi_idx, len(diffs) - 1)
    ci_lo = diffs[lo_idx]
    ci_hi = diffs[hi_idx]
    p_value = sum(1 for d in diffs if d <= 0) / len(diffs)
    return mean_diff, ci_lo, ci_hi, p_value


def _per_scenario_metric(
    metric: str,
    predictions: list[ResearchSynthesis],
    scenarios: list[Scenario],
    cypher_runner: Any,
) -> list[float]:
    """Compute per-scenario metric values for paired tests.

    For most metrics, we produce a binary score per prediction (correct=1 /
    incorrect=0) so we have one value per (pred, scenario) pair.  This lets
    the paired bootstrap resample at the scenario level.

    Special cases:
      verdict_kappa — use binary correct/incorrect (not kappa, which needs a list)
      ece           — use per-prediction |accuracy - confidence| gap
      hdi_recall    — 1/0 per severe-HDI prediction, NaN elsewhere
      provenance    — fraction of verified edges per prediction
      defer_acc     — 1/0 per prediction
      bilingual     — 1/0 per tcm_bilingual prediction, NaN elsewhere
    """
    out: list[float] = []
    for p, s in zip(predictions, scenarios):
        if metric == "verdict_kappa":
            # Binary correct/incorrect
            val = float(_majority_verdict_local(p) == s.gold.expected_panel_verdict)
        elif metric == "ece":
            # Per-prediction |correct - confidence|
            correct = float(_majority_verdict_local(p) == s.gold.expected_panel_verdict)
            val = abs(correct - p.confidence)
        elif metric == "hdi_recall":
            if s.gold.expected_hdi_severity != "severe":
                out.append(float("nan"))
                continue
            flagged = _majority_verdict_local(p) == "reject" or p.defer_to_clinician
            val = float(flagged)
        elif metric == "provenance":
            if cypher_runner is None:
                out.append(float("nan"))
                continue
            total = sum(len(chain.edges) for chain in p.candidate_chains)
            if total == 0:
                val = 1.0
            else:
                matched = sum(
                    1
                    for chain in p.candidate_chains
                    for edge in chain.edges
                    if cypher_runner(edge.src, edge.edge, edge.tgt)
                )
                val = matched / total
        elif metric == "defer_acc":
            val = float(p.defer_to_clinician == s.gold.expected_defer)
        elif metric == "bilingual":
            if s.category != "tcm_bilingual":
                out.append(float("nan"))
                continue
            import re
            _cjk = re.compile(r"[一-鿿]")
            has_cjk = any(
                _cjk.search(edge.src) or _cjk.search(edge.tgt)
                for chain in p.candidate_chains
                for edge in chain.edges
            )
            val = float(has_cjk)
        else:
            val = float("nan")
        out.append(val)
    return out


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def render_report(
    results: dict[str, list[ResearchSynthesis]],
    scenarios: list[Scenario],
    out_dir: Path,
    cypher_runner: Any = None,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> dict:
    """Render runner outputs into evaluation report artifacts.

    Args:
        results:       {system_name: [ResearchSynthesis, ...]} from the runner.
        scenarios:     List of Scenario ground-truth objects; same length/order
                       as each system's prediction list.
        out_dir:       Directory under which to write all artifacts.
        cypher_runner: Optional callable (src, edge, tgt) -> bool for
                       provenance_faithfulness.  If None, the metric is skipped.
        n_bootstrap:   Bootstrap iterations for CI and paired tests (default 1000).
        seed:          Random seed for reproducibility.

    Returns:
        JSON-serialisable dict of
        {metric: {system: {mean, ci_lo, ci_hi}}}
        where NaN cells are represented as None.

    Artifacts written:
        <out_dir>/summary.md
        <out_dir>/reliability_diagram.png
        <out_dir>/per_system/<sys>/per_metric.json
        <out_dir>/paired_tests.md
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    systems = list(results.keys())

    # ------------------------------------------------------------------
    # 1. Compute bootstrap statistics for every (metric, system) cell
    # ------------------------------------------------------------------
    # stats[metric][system] = {mean, ci_lo, ci_hi}
    stats: dict[str, dict[str, dict[str, Any]]] = {m: {} for m in _METRICS}

    for metric in _METRICS:
        for sys in systems:
            preds = results[sys]
            mean_val, ci_lo, ci_hi = _bootstrap_metric(
                metric, preds, scenarios, cypher_runner, n_bootstrap, seed
            )
            # Convert to None for JSON-safety if undefined
            stats[metric][sys] = {
                "mean": mean_val,
                "ci_lo": ci_lo,
                "ci_hi": ci_hi,
            }

    # ------------------------------------------------------------------
    # 2. Write per_system/<sys>/per_metric.json
    # ------------------------------------------------------------------
    for sys in systems:
        sys_dir = out_dir / "per_system" / sys
        sys_dir.mkdir(parents=True, exist_ok=True)
        per_metric: dict[str, Any] = {}
        for metric in _METRICS:
            cell = stats[metric][sys]
            per_metric[metric] = cell["mean"]  # None if undefined
        (sys_dir / "per_metric.json").write_text(json.dumps(per_metric, indent=2))

    # ------------------------------------------------------------------
    # 3. Write summary.md
    # ------------------------------------------------------------------
    _write_summary_md(out_dir / "summary.md", systems, stats)

    # ------------------------------------------------------------------
    # 4. Write reliability_diagram.png
    # ------------------------------------------------------------------
    _render_reliability_diagram(results, scenarios, out_dir / "reliability_diagram.png")

    # ------------------------------------------------------------------
    # 5. Write paired_tests.md
    # ------------------------------------------------------------------
    _write_paired_tests_md(
        out_dir / "paired_tests.md",
        results,
        scenarios,
        systems,
        cypher_runner,
        n_bootstrap,
        seed,
    )

    # ------------------------------------------------------------------
    # 6. Return JSON-able dict
    # ------------------------------------------------------------------
    return dict(stats)


# ---------------------------------------------------------------------------
# Helpers: markdown writers
# ---------------------------------------------------------------------------


def _fmt_cell(mean: float | None, ci_lo: float | None, ci_hi: float | None) -> str:
    """Format a table cell: 'mean [lo, hi]' or '—' if undefined."""
    if mean is None or (isinstance(mean, float) and math.isnan(mean)):
        return "—"
    lo_str = f"{ci_lo:.3f}" if ci_lo is not None else "?"
    hi_str = f"{ci_hi:.3f}" if ci_hi is not None else "?"
    return f"{mean:.3f} [{lo_str}, {hi_str}]"


def _write_summary_md(
    path: Path,
    systems: list[str],
    stats: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Write the 6-systems × 6-metrics summary table."""
    lines: list[str] = [
        "# DietResearchBench-Clinical — Evaluation Summary\n",
        f"Systems: {', '.join(systems)}  \n",
        "All values: mean [95% CI bootstrap]. '—' = metric undefined for this system/split.\n",
        "",
    ]

    # Header row
    metric_col_headers = [_METRIC_LABELS.get(m, m) for m in _METRICS]
    header = "| System | " + " | ".join(metric_col_headers) + " |"
    divider = "| --- | " + " | ".join(["---"] * len(_METRICS)) + " |"
    lines.append(header)
    lines.append(divider)

    # One row per system — column keys must match _METRICS list
    for sys in systems:
        cells = [
            _fmt_cell(
                stats[m][sys]["mean"],
                stats[m][sys]["ci_lo"],
                stats[m][sys]["ci_hi"],
            )
            for m in _METRICS
        ]
        row = f"| {sys} | " + " | ".join(cells) + " |"
        lines.append(row)

    # Metric key
    lines += [
        "",
        "## Metric abbreviations",
        "",
        "| Key | Full name |",
        "| --- | --- |",
    ]
    for key, label in _METRIC_LABELS.items():
        lines.append(f"| {key} | {label} |")

    lines.append("")
    path.write_text("\n".join(lines))


def _write_paired_tests_md(
    path: Path,
    results: dict[str, list[ResearchSynthesis]],
    scenarios: list[Scenario],
    systems: list[str],
    cypher_runner: Any,
    n_bootstrap: int,
    seed: int,
) -> None:
    """Write paired bootstrap tests — diet_os vs each baseline.

    p-values are Bonferroni-adjusted by n_baselines (number of non-diet_os systems).
    """
    if "diet_os" not in results:
        path.write_text("# Paired tests\n\n*No diet_os system in results — skipped.*\n")
        return

    baselines = [s for s in systems if s != "diet_os"]
    n_baselines = len(baselines)

    diet_os_preds = results["diet_os"]

    lines: list[str] = [
        "# DietResearchBench-Clinical — Paired Bootstrap Tests\n",
        "Comparison: Diet-OS vs each baseline system.  \n",
        "Null hypothesis: Diet-OS performs no better than the baseline (mean_diff ≤ 0).  \n",
        f"Bonferroni correction applied: n_baselines = {n_baselines}, "
        f"adjusted α = {0.05 / n_baselines:.4f} per comparison.  \n",
        f"Bootstrap iterations: {n_bootstrap}  \n",
        "",
        "| System | Metric | mean_diff | CI_lo | CI_hi | p_raw | p_adj (Bonferroni) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    for baseline in baselines:
        baseline_preds = results[baseline]
        for metric in _METRICS:
            # Compute per-scenario scores for both systems
            d_scores_raw = _per_scenario_metric(metric, diet_os_preds, scenarios, cypher_runner)
            b_scores_raw = _per_scenario_metric(metric, baseline_preds, scenarios, cypher_runner)

            # Filter out NaN pairs
            paired = [
                (d, b)
                for d, b in zip(d_scores_raw, b_scores_raw)
                if not math.isnan(d) and not math.isnan(b)
            ]

            if not paired:
                lines.append(
                    f"| {baseline} | {metric} | — | — | — | — | — |"
                )
                continue

            d_scores = [p[0] for p in paired]
            b_scores = [p[1] for p in paired]

            mean_diff, ci_lo, ci_hi, p_raw = _paired_bootstrap_pvalue(
                d_scores, b_scores, n_bootstrap, seed
            )
            p_adj = min(p_raw * n_baselines, 1.0)

            lines.append(
                f"| {baseline} | {metric} "
                f"| {mean_diff:.3f} | {ci_lo:.3f} | {ci_hi:.3f} "
                f"| {p_raw:.4f} | {p_adj:.4f} |"
            )

    lines += [
        "",
        "**Interpretation:** p_adj < 0.05 (Bonferroni-adjusted) indicates Diet-OS "
        "statistically outperforms the baseline on that metric.  \n",
        "Note: for ECE, lower is better; mean_diff < 0 is favourable for Diet-OS.  \n",
    ]

    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys as _sys

    parser = argparse.ArgumentParser(
        prog="python3 -m eval.report",
        description=(
            "DietResearchBench-Clinical results reporter.\n"
            "Loads per-prediction JSON artifacts written by eval.runner, "
            "reconstructs the results matrix, and renders summary.md + "
            "reliability_diagram.png."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--latest",
        metavar="RESULTS_ROOT",
        help=(
            "Path to the results root directory. The most recently modified "
            "timestamped subdirectory is selected automatically."
        ),
    )
    mode_group.add_argument(
        "--results-dir",
        metavar="DIR",
        help="Path to a specific timestamped results directory to render.",
    )

    parser.add_argument(
        "--cypher-runner",
        choices=["none", "source-attribution"],
        default="none",
        help="Provenance metric runner. 'source-attribution' uses the v1 "
             "source-id-prefix proxy; 'none' leaves provenance as '—'.",
    )

    args = parser.parse_args()

    # --- Resolve the target results directory ---
    if args.latest is not None:
        latest_root = Path(args.latest)
        if not latest_root.exists():
            parser.error(f"--latest path does not exist: {latest_root}")
        # Find the most recently modified subdirectory
        subdirs = sorted(
            (d for d in latest_root.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not subdirs:
            parser.error(
                f"No run subdirectories found under --latest path: {latest_root}"
            )
        results_dir = subdirs[0]
    else:
        results_dir = Path(args.results_dir)
        if not results_dir.exists():
            parser.error(f"--results-dir path does not exist: {results_dir}")

    # --- Load manifest to reconstruct scenario list ---
    manifests = sorted(results_dir.glob("manifest-*.json"))
    if not manifests:
        parser.error(
            f"No manifest-*.json found in results dir: {results_dir}\n"
            "Was this directory produced by eval.runner?"
        )

    manifest_data = json.loads(manifests[-1].read_text())
    scenario_ids: list[str] = manifest_data.get("scenario_ids", [])
    systems_in_run: list[str] = manifest_data.get("systems", [])

    # --- Load per-prediction JSONs ---
    from agents.models import ResearchSynthesis as _RS  # type: ignore[import-not-found]

    run_results: dict[str, list[_RS]] = {}
    for sys_name in systems_in_run:
        sys_dir = results_dir / sys_name
        per_system: list[_RS] = []
        for scen_id in scenario_ids:
            pred_path = sys_dir / f"{scen_id}.json"
            if pred_path.exists():
                per_system.append(_RS.model_validate_json(pred_path.read_text()))
            else:
                print(
                    f"WARNING: missing prediction {pred_path}",
                    file=_sys.stderr,
                )
        run_results[sys_name] = per_system

    # --- Reconstruct scenario stubs from manifest ---
    from eval.scenario import BenchmarkSet as _BS, GoldStandard as _GS, Scenario as _S  # type: ignore[import-not-found]

    # Try to discover benchmark file relative to the results directory
    # (expected layout: research-journal/shared/results/<run>/,
    #  benchmark at research-journal/shared/datasets/dietresearchbench_v1.json)
    _candidate_bench = results_dir.parents[1] / "datasets" / "dietresearchbench_v1.json"
    run_scenarios: list[_S] = []

    def _neutral_stub(scen_id: str) -> "_S":
        return _S(
            id=scen_id,
            category="herbal_single_symptom",
            research_question=scen_id,
            gold=_GS(
                expected_complexity="low",
                expected_panel_verdict="abstain",
                expected_evidence_tier="unknown",
                expected_min_chains=0,
                expected_defer=False,
                expected_red_flags=[],
                languages=["en"],
            ),
            rationale="reconstructed stub",
        )

    if _candidate_bench.exists():
        bench_data = json.loads(_candidate_bench.read_text())
        loaded_bench = _BS.model_validate(bench_data)
        scen_map = {s.id: s for s in loaded_bench.scenarios}
        for scen_id in scenario_ids:
            run_scenarios.append(scen_map.get(scen_id) or _neutral_stub(scen_id))
    else:
        print(
            f"WARNING: benchmark file not found at {_candidate_bench}; "
            "using neutral stubs for scenario gold standards.",
            file=_sys.stderr,
        )
        for scen_id in scenario_ids:
            run_scenarios.append(_neutral_stub(scen_id))

    # Ensure list lengths are consistent
    min_len = min((len(v) for v in run_results.values()), default=0)
    if min_len < len(run_scenarios):
        run_scenarios = run_scenarios[:min_len]

    if not run_results or not run_scenarios:
        print(
            "No results or scenarios to render. "
            "Ensure eval.runner completed successfully.",
            file=_sys.stderr,
        )
        _sys.exit(1)

    # --- Render ---
    print(f"Rendering report for: {results_dir}", file=_sys.stderr)

    cypher_runner = None
    if args.cypher_runner == "source-attribution":
        # Build the edge → source_id map from the loaded predictions
        edge_to_source: dict[tuple[str, str, str], str] = {}
        for sys_preds in run_results.values():
            for pred in sys_preds:
                for chain in pred.candidate_chains:
                    for e in chain.edges:
                        # KGEdge.source_id is str on the model; the or-fallback
                        # guards deserialized data where the field may be empty
                        # string from older runs. Empty source is rejected by
                        # the runner (no known-prefix match).
                        edge_to_source[(e.src, e.edge, e.tgt)] = e.source_id or ""
        cypher_runner = build_source_attribution_runner(edge_to_source)

    render_report(run_results, run_scenarios, out_dir=results_dir,
                  cypher_runner=cypher_runner)

    summary_path = results_dir / "summary.md"
    diagram_path = results_dir / "reliability_diagram.png"
    print(f"summary.md     -> {summary_path}")
    print(f"reliability    -> {diagram_path}")
    print(f"paired_tests   -> {results_dir / 'paired_tests.md'}")
