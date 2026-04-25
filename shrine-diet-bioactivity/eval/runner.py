"""Eval runner — loops (scenarios × systems), persists per-prediction artifacts,
returns a results matrix that the report module renders."""
from __future__ import annotations

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
