"""Phase 3 pipeline E2E tests — drive `diet_os.run(scenario)` against real
OpenRouter + real MCP gateway for 3 DietResearchBench-Clinical scenarios and
assert majority verdict matches gold.

Plan ref: research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md
Category B (pipeline end-to-end), tests #13/#14/#15.

Why these 3 scenarios (one per category):
  - case-hdi-001-sjw-sertraline  → multi_drug_hdi  (gold: reject, severe HDI)
  - case-tcm-002-huangqi-fatigue → tcm_bilingual   (gold: caution, moderate HDI)
  - case-nutrition-001-vitamin-d-deficiency → nutrition (gold: prefer, no HDI)

These three exercise complementary KG paths:
  - HDI → kg_hdi_check + serotonergic interaction chain
  - TCM-bilingual → kg_bilingual_term (黄芪 / huangqi / Astragalus membranaceus)
  - nutrition → kg_diet_to_compounds + kg_compound_to_targets

Cost / runtime envelope:
  - All tests skipped unless `OPENROUTER_API_KEY` AND `MCP_API_KEY` are in env
    (autouse `_require_live_env` fixture in conftest.py).
  - Default `addopts = ["-m", "not e2e"]` in mcp/pyproject.toml deselects
    them on every PR run.
  - Sequential execution; 3-second pre-test sleep keeps per-process LLM-call
    rate under the Nemotron free-tier 20 RPM limit even if test internals
    burst.
  - Each diet_os.run() invocation does ~5-10 LLM calls (panel deliberation
    + provenance assembly); expect 30-60s per test, ~3-5 min nightly total.
"""

from __future__ import annotations

import time

import pytest

from eval.baselines import diet_os  # type: ignore[import-not-found]
from eval.metrics import _majority_verdict  # type: ignore[import-not-found]
from eval.tests.integration._helpers import assert_confidence_consistent_with_verdict  # type: ignore[import-not-found]

pytestmark = [pytest.mark.e2e, pytest.mark.live_llm, pytest.mark.slow]


@pytest.fixture(autouse=True)
def _throttle_between_scenarios() -> None:
    """Sleep 3s before each test to keep per-process call rate under the
    free-tier Nemotron 20-RPM limit even when burst-starts overlap with the
    previous test's tail (pytest's default sequential mode does NOT add gaps
    between tests).

    9s total cost across the 3 tests is negligible against the ~3-5 min
    nightly runtime budget.
    """
    time.sleep(3)


def test_diet_os_hdi_scenario_e2e(scenario_by_id) -> None:
    """SJW + sertraline → 'reject' (severe serotonergic interaction).

    Verifies the full panel correctly identifies the HDI and outputs a
    low-confidence reject — confidence should be low BY DESIGN because the
    calibrator weighs (1 - hdi_risk)^0.3, and hdi_risk is high for severe
    interactions. A high-confidence reject would mean the calibrator inverted.
    """
    scenario = scenario_by_id("case-hdi-001-sjw-sertraline")
    assert scenario.gold.expected_panel_verdict == "reject", (
        "gold drift — Phase 3 test asserts against a fixed expected verdict"
    )

    synthesis = diet_os.run(scenario)

    majority = _majority_verdict(synthesis)
    assert majority == "reject", (
        f"HDI scenario: panel returned {majority!r}, expected 'reject' "
        f"(gold says severe serotonergic interaction). "
        f"per-role verdicts: {[v.verdict for v in synthesis.panel.verdicts]}"
    )
    assert_confidence_consistent_with_verdict("reject", synthesis.confidence)


def test_diet_os_tcm_bilingual_e2e(scenario_by_id) -> None:
    """黄芪 (huangqi / Astragalus membranaceus) + fatigue → 'caution'.

    Exercises the bilingual term resolution path. Gold expects a moderate
    HDI severity and a caution verdict (not full reject — Astragalus has a
    safety profile but interacts with several immunosuppressants).
    """
    scenario = scenario_by_id("case-tcm-002-huangqi-fatigue")
    assert scenario.gold.expected_panel_verdict == "caution", (
        "gold drift — Phase 3 test asserts against a fixed expected verdict"
    )
    assert "zh" in scenario.gold.languages, (
        "TCM bilingual scenario should declare zh in gold.languages"
    )

    synthesis = diet_os.run(scenario)

    majority = _majority_verdict(synthesis)
    assert majority == "caution", (
        f"TCM-bilingual scenario: panel returned {majority!r}, expected 'caution'. "
        f"per-role verdicts: {[v.verdict for v in synthesis.panel.verdicts]}"
    )
    assert_confidence_consistent_with_verdict("caution", synthesis.confidence)


def test_diet_os_nutrition_e2e(scenario_by_id) -> None:
    """Vitamin D deficiency → 'prefer' (clinical-trial-backed recommendation).

    No HDI risk → hdi_risk component is near 0 → confidence should be
    nontrivial. A 'prefer' verdict with confidence < 0.3 would indicate
    the evidence_tier component collapsed (calibrator may be ignoring
    upstream evidence signals).
    """
    scenario = scenario_by_id("case-nutrition-001-vitamin-d-deficiency")
    assert scenario.gold.expected_panel_verdict == "prefer", (
        "gold drift — Phase 3 test asserts against a fixed expected verdict"
    )
    assert scenario.gold.expected_hdi_severity == "none", (
        "nutrition scenario should have no HDI risk"
    )

    synthesis = diet_os.run(scenario)

    majority = _majority_verdict(synthesis)
    assert majority == "prefer", (
        f"Nutrition scenario: panel returned {majority!r}, expected 'prefer'. "
        f"per-role verdicts: {[v.verdict for v in synthesis.panel.verdicts]}"
    )
    assert_confidence_consistent_with_verdict("prefer", synthesis.confidence)
