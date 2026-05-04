"""Render the §6.5 ablation paired test: diet_os vs diet_os_llm_triage.

This complements eval.report's main paired-tests table (which compares each
of the 5 baselines to diet_os under a 20-cell Bonferroni family). The
ablation test answers a planned, single-cell question:

    "Does deterministic gold-triage substitute account for diet_os's lift?"

so it is intentionally NOT rolled into the multiple-testing family.

Usage:
    python3 -m scripts.render_ablation_test \
        --results-dir <combined_results_dir>

Writes <results_dir>/ablation_test.md.
"""
from __future__ import annotations

import argparse
import json
import sys as _sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in _sys.path:
    _sys.path.insert(0, str(_REPO))

from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
from eval.report import _paired_bootstrap_pvalue, _per_scenario_metric  # type: ignore[import-not-found]
from eval.scenario import BenchmarkSet, Scenario  # type: ignore[import-not-found]

_METRICS = ["verdict_kappa", "ece", "hdi_recall", "defer_acc"]


def _load_predictions(sys_dir: Path, scenario_ids: list[str]) -> list[ResearchSynthesis]:
    out: list[ResearchSynthesis] = []
    for sid in scenario_ids:
        path = sys_dir / f"{sid}.json"
        if not path.exists():
            print(f"WARNING: missing {path}", file=_sys.stderr)
            continue
        out.append(ResearchSynthesis.model_validate_json(path.read_text()))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--n-iter", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    manifests = sorted(results_dir.glob("manifest-*.json"))
    if not manifests:
        raise SystemExit(f"No manifest in {results_dir}")
    manifest = json.loads(manifests[-1].read_text())
    scenario_ids: list[str] = manifest["scenario_ids"]

    bench_path = results_dir.parents[1] / "datasets" / "dietresearchbench_v1.json"
    bench = BenchmarkSet.model_validate_json(bench_path.read_text())
    scenarios_by_id: dict[str, Scenario] = {s.id: s for s in bench.scenarios}
    scenarios: list[Scenario] = [scenarios_by_id[sid] for sid in scenario_ids]

    diet_os = _load_predictions(results_dir / "diet_os", scenario_ids)
    diet_os_llm = _load_predictions(results_dir / "diet_os_llm_triage", scenario_ids)

    if len(diet_os) != len(diet_os_llm) or len(diet_os) != len(scenarios):
        raise SystemExit(
            f"Length mismatch: diet_os={len(diet_os)} llm={len(diet_os_llm)} scen={len(scenarios)}"
        )

    rows: list[dict] = []
    for metric in _METRICS:
        d_scores = _per_scenario_metric(metric, diet_os, scenarios, cypher_runner=None)
        l_scores = _per_scenario_metric(metric, diet_os_llm, scenarios, cypher_runner=None)
        # Filter NaNs (e.g., hdi_recall is only defined on severe-HDI scenarios)
        paired = [(d, l) for d, l in zip(d_scores, l_scores) if d == d and l == l]
        if not paired:
            rows.append({
                "metric": metric, "n": 0, "mean_diff": float("nan"),
                "ci_lo": float("nan"), "ci_hi": float("nan"), "p_value": float("nan"),
            })
            continue
        d_paired = [p[0] for p in paired]
        l_paired = [p[1] for p in paired]
        mean_diff, ci_lo, ci_hi, p_val = _paired_bootstrap_pvalue(
            d_paired, l_paired, n_iter=args.n_iter, seed=args.seed
        )
        rows.append({
            "metric": metric, "n": len(paired), "mean_diff": mean_diff,
            "ci_lo": ci_lo, "ci_hi": ci_hi, "p_value": p_val,
        })

    lines: list[str] = []
    lines.append("# DietResearchBench-Clinical — Triage Ablation Paired Test\n")
    lines.append("Comparison: **diet_os** (deterministic gold-triage substitute) vs. ")
    lines.append("**diet_os_llm_triage** (free-tier Nemotron triage; identical retrieval + panel).\n")
    lines.append("Null hypothesis: diet_os performs no better than diet_os_llm_triage (mean_diff ≤ 0).\n")
    lines.append(
        f"Bootstrap iterations: B = {args.n_iter}; "
        "p-value via Davison-Hinkley (k+1)/(B+1) convention. "
        "**No Bonferroni correction** — this is a single planned-comparison ablation, "
        "not part of the 20-cell baseline family in `paired_tests.md`.\n"
    )
    lines.append("| Metric | n | mean_diff | CI_lo | CI_hi | p_value |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        lines.append(
            f"| {r['metric']} | {r['n']} | "
            f"{r['mean_diff']:.3f} | {r['ci_lo']:.3f} | {r['ci_hi']:.3f} | "
            f"{r['p_value']:.5f} |"
        )
    lines.append(
        "\n**Sign convention**: for verdict_kappa, hdi_recall, defer_acc, higher is better and "
        "positive mean_diff = diet_os − diet_os_llm_triage is favourable. For ECE, lower is "
        "better and positive mean_diff is *adverse* (worse calibration for diet_os).\n"
    )
    lines.append(
        "**Surrogate disclosure**: paired κ test resamples per-scenario verdict-correctness "
        "(not the κ statistic itself); see §6.2.\n"
    )

    out_path = results_dir / "ablation_test.md"
    out_path.write_text("\n".join(lines))
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
