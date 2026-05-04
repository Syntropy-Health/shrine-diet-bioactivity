"""Eval runner — loops (scenarios × systems), persists per-prediction artifacts,
returns a results matrix that the report module renders."""
from __future__ import annotations

# Bootstrap sys.path so this module works when invoked directly as
# `python3 -m eval.runner` without a prior conftest.py (e.g. CLI, Makefile).
# When pytest runs, conftest.py has already done this — the inserts are no-ops.
import sys as _sys
from pathlib import Path as _Path
_REPO = _Path(__file__).resolve().parent.parent  # shrine-diet-bioactivity/
for _sub in ("", "lightrag", "agents"):
    _p = str(_REPO / _sub) if _sub else str(_REPO)
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
del _sys, _Path, _REPO, _sub, _p  # keep namespace clean

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
from eval.baselines import BASELINES
from eval.scenario import BenchmarkSet, Scenario

log = logging.getLogger(__name__)


def run_eval(
    bench: BenchmarkSet,
    scenarios: list[Scenario],
    out_dir: Path,
    systems: list[str] | None = None,
) -> dict[str, list[ResearchSynthesis]]:
    """Run all scenarios against all selected baseline systems.
    Persists each prediction to out_dir/<system>/<scenario_id>.json.
    Returns {system_name: [ResearchSynthesis, ...] in the same order as scenarios}."""
    sysnames = systems or list(BASELINES.keys())
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[ResearchSynthesis]] = {}
    for sysname in sysnames:
        if sysname not in BASELINES:
            raise ValueError(f"unknown system {sysname!r}; available: {list(BASELINES.keys())}")
        fn = BASELINES[sysname]
        sys_out = out_dir / sysname
        sys_out.mkdir(parents=True, exist_ok=True)
        per_system: list[ResearchSynthesis] = []
        for s in scenarios:
            log.info("running %s on %s", sysname, s.id)
            try:
                rs = fn(s)
            except Exception as e:
                log.warning("system %s failed on %s: %s", sysname, s.id, e)
                # Emit a placeholder ResearchSynthesis with abstain to keep matrix shape.
                rs = _placeholder(s, error=str(e))
            (sys_out / f"{s.id}.json").write_text(rs.model_dump_json(indent=2))
            per_system.append(rs)
        results[sysname] = per_system
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"manifest-{timestamp}.json").write_text(json.dumps({
        "benchmark_version": bench.version,
        "scenario_count": len(scenarios),
        "systems": sysnames,
        "scenario_ids": [s.id for s in scenarios],
        "timestamp": timestamp,
    }, indent=2))
    return results


def _placeholder(scenario: Scenario, error: str) -> ResearchSynthesis:
    """Stand-in synthesis when a system errors — abstain + zero confidence."""
    from agents.models import (
        ConfidenceComponents, PanelDeliberation, ResearchQuestion, Triage,
    )
    return ResearchSynthesis(
        question=ResearchQuestion(text=scenario.research_question),
        triage=Triage(complexity="low", rationale=f"runner-error: {error[:200]}", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(verdicts=[], dissent=[error[:200]], moderator_summary="error"),
        confidence=0.0,
        components=ConfidenceComponents(evidence_tier=0.0, hdi_risk=0.0, question_fit=0.0),
        defer_to_clinician=False,
    )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys as _sys

    parser = argparse.ArgumentParser(
        prog="python3 -m eval.runner",
        description=(
            "DietResearchBench-Clinical evaluation runner.\n"
            "Loads a BenchmarkSet, selects scenarios for the requested split, "
            "runs each baseline system, and persists per-prediction JSON artifacts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bench",
        required=True,
        metavar="PATH",
        help="Path to dietresearchbench_v1.json (BenchmarkSet JSON).",
    )
    parser.add_argument(
        "--splits",
        required=True,
        metavar="PATH",
        help="Path to splits_seed42.json (splits manifest).",
    )
    parser.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help="Output directory for this run (created if absent). "
             "Recommended: results/<timestamp>/",
    )
    parser.add_argument(
        "--systems",
        metavar="SYSTEMS",
        default=None,
        help="Optional comma-separated list of system names to run "
             "(e.g. diet_os,medagents). Defaults to all registered baselines.",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "test", "all"],
        default="test",
        help="Which split to evaluate (train|val|test|all). Default: test. "
             "Use 'all' for the full 40 scenarios (paper-grade matrix).",
    )

    args = parser.parse_args()

    # --- Validate inputs before doing any work ---
    bench_path = Path(args.bench)
    if not bench_path.exists():
        parser.error(f"--bench path does not exist: {bench_path}")

    splits_path = Path(args.splits)
    if not splits_path.exists():
        parser.error(f"--splits path does not exist: {splits_path}")

    # --- Load benchmark ---
    try:
        bench_data = json.loads(bench_path.read_text())
        bench = BenchmarkSet.model_validate(bench_data)
    except Exception as exc:
        parser.error(f"Failed to load --bench file: {exc}")

    # --- Load splits manifest and filter scenarios ---
    split_ids: list[str] = []
    try:
        splits_data = json.loads(splits_path.read_text())
        if args.split == "all":
            split_ids = (
                splits_data.get("train_ids", [])
                + splits_data.get("val_ids", [])
                + splits_data.get("test_ids", [])
            )
        else:
            split_ids = splits_data[f"{args.split}_ids"]
    except Exception as exc:
        parser.error(f"Failed to read --splits file: {exc}")

    split_id_set = set(split_ids)
    scenarios = [s for s in bench.scenarios if s.id in split_id_set]

    if not scenarios:
        print(
            f"WARNING: No scenarios found for split '{args.split}' in the benchmark. "
            "Check that --splits was generated from the same --bench file.",
            file=_sys.stderr,
        )

    # --- Resolve optional --systems flag ---
    systems_list: list[str] | None = None
    if args.systems:
        systems_list = [s.strip() for s in args.systems.split(",") if s.strip()]

    out_dir = Path(args.out)

    # --- Run ---
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(
        f"Running eval: split={args.split!r} scenarios={len(scenarios)} "
        f"systems={systems_list or 'all'} out={out_dir}",
        file=_sys.stderr,
    )

    try:
        results = run_eval(bench, scenarios, out_dir=out_dir, systems=systems_list)
    except ValueError as exc:
        parser.error(str(exc))

    # --- Summary line ---
    total_preds = sum(len(v) for v in results.values())
    print(
        f"Done. {len(results)} system(s), {len(scenarios)} scenario(s), "
        f"{total_preds} total predictions. Results in: {out_dir}"
    )
