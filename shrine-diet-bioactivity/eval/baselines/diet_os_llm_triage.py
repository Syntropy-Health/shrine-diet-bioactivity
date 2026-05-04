"""Diet-OS ablation cell — same panel + retrieval as `diet_os` but with
LLM-emitted Triage instead of gold-preset Triage.

This cell exists to address the C1 fairness concern (peer review on
v1 paper): the canonical `diet_os` baseline uses
`scenario.gold.expected_complexity` to construct the Triage object,
giving it gold-derived complexity that LLM-triage baselines do not have.
By comparing `diet_os` vs `diet_os_llm_triage` we report an explicit
ablation: does the architectural lift (KG-grounded retrieval bundle +
role-priored panel) survive when triage is also LLM-emitted?

Implementation: identical to `eval.baselines.diet_os.run` except no
`preset_question` / `preset_triage` are passed to `run_case_study`. The
runner then invokes `build_triage_agent()` and the triage LLM extracts
PICO + complexity from the scenario question text.

Caveat: Nemotron's malformed-JSON triage output (postmortem §9d) is
handled by `agents.triage._extract_json_obj`. Some scenarios will still
fail and surface as runner-error placeholders in the prediction —
this is the realistic, free-tier-LLM-driven panel behavior.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
from agents.run_case_study import run_case_study  # type: ignore[import-not-found]
from eval.scenario import Scenario  # type: ignore[import-not-found]


def run(scenario: Scenario) -> ResearchSynthesis:
    """Run diet_os without gold-preset triage.

    `run_case_study(spec, out, preset_question=None, preset_triage=None)`
    falls through to `build_triage_agent()` and uses the LLM to extract
    `ResearchQuestion` + `Triage` from the scenario question text.
    """
    spec = {
        "id": scenario.id,
        "research_question": scenario.research_question,
        "category": scenario.category,
        "version": scenario.version,
    }

    with tempfile.TemporaryDirectory(prefix="diet_os_llm_triage_eval_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        spec_path = tmp_path / f"{scenario.id}.json"
        spec_path.write_text(json.dumps(spec, indent=2))
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        synthesis = run_case_study(spec_path, out_dir)

    return synthesis
