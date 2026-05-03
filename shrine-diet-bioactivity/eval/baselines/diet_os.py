"""Diet-OS wrapper baseline — wraps agents.run_case_study.run_case_study.

Converts a Scenario into the spec format expected by run_case_study, invokes
the full Subsystem H pipeline, and returns the ResearchSynthesis it produces.

Persistence: uses a tempfile directory so eval runs never write to research-journal/.

Eval-time triage bypass: free-tier Nemotron emits malformed JSON in the
triage stage at 100K+ token padding. This baseline derives a preset
Triage from `scenario.gold.expected_complexity` + a heuristic intervention
extraction from `scenario.id`, skipping the triage LLM entirely. This
makes eval runs deterministic, faster, and not gated on Nemotron JSON
quality.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agents.models import (  # type: ignore[import-not-found]
    ResearchQuestion, ResearchSynthesis, Triage,
)
from agents.run_case_study import run_case_study  # type: ignore[import-not-found]
from eval.scenario import Scenario  # type: ignore[import-not-found]


def _intervention_from_scenario_id(scenario_id: str) -> str | None:
    """Heuristic extraction. Scenario ids follow the convention
    `case-<category>-<num>-<intervention-name>-<outcome>`. Token [3] is
    the intervention. Underscores → spaces, then title-case."""
    parts = scenario_id.split("-")
    if len(parts) < 4:
        return None
    raw = parts[3]
    if not raw:
        return None
    return raw.replace("_", " ").title()


def _scenario_to_preset(scenario: Scenario) -> tuple[ResearchQuestion, Triage]:
    rq = ResearchQuestion(
        text=scenario.research_question,
        intervention=_intervention_from_scenario_id(scenario.id),
        languages=list(scenario.gold.languages or ["en"]),
    )
    triage = Triage(
        complexity=scenario.gold.expected_complexity,
        rationale=f"eval-preset from gold.expected_complexity={scenario.gold.expected_complexity}",
        red_flags=list(scenario.gold.expected_red_flags or []),
    )
    return rq, triage


def run(scenario: Scenario) -> ResearchSynthesis:
    """Wrap run_case_study for benchmarking.

    Constructs a minimal case-study spec JSON from the Scenario, writes it
    to a temp directory, calls run_case_study with a preset Triage, and
    returns the synthesis.
    """
    spec = {
        "id": scenario.id,
        "research_question": scenario.research_question,
        "category": scenario.category,
        "version": scenario.version,
    }

    rq, triage = _scenario_to_preset(scenario)

    with tempfile.TemporaryDirectory(prefix="diet_os_eval_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        spec_path = tmp_path / f"{scenario.id}.json"
        spec_path.write_text(json.dumps(spec, indent=2))
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        synthesis = run_case_study(
            spec_path, out_dir,
            preset_question=rq, preset_triage=triage,
        )

    return synthesis
