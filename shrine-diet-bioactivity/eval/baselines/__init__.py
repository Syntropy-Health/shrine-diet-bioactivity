"""Baseline registry for DietResearchBench-Clinical evaluation.

Each baseline implements the shared contract:
    run(scenario: Scenario) -> ResearchSynthesis

The BASELINES dict maps system name → run function for use by the eval runner.
"""
from typing import Callable

from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
from eval.scenario import Scenario  # type: ignore[import-not-found]

from eval.baselines.single_llm import run as _run_single_llm
from eval.baselines.single_llm_rag import run as _run_single_llm_rag
from eval.baselines.yang2025 import run as _run_yang2025
from eval.baselines.medagents import run as _run_medagents
from eval.baselines.mdagents import run as _run_mdagents
from eval.baselines.diet_os import run as _run_diet_os
from eval.baselines.diet_os_llm_triage import run as _run_diet_os_llm_triage

BASELINES: dict[str, Callable[[Scenario], ResearchSynthesis]] = {
    "single_llm": _run_single_llm,
    "single_llm_rag": _run_single_llm_rag,
    "yang2025": _run_yang2025,
    "medagents": _run_medagents,
    "mdagents": _run_mdagents,
    "diet_os": _run_diet_os,
    "diet_os_llm_triage": _run_diet_os_llm_triage,
}

__all__ = ["BASELINES"]
