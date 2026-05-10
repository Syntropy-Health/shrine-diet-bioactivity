"""Scenario + GoldStandard schema tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.scenario import BenchmarkSet, GoldStandard, Scenario  # type: ignore[import-not-found]

pytestmark = [pytest.mark.unit]

BENCH_PATH = (
    Path(__file__).resolve().parents[3]
    / "research-journal"
    / "shared"
    / "datasets"
    / "dietresearchbench_v1.json"
)


def test_gold_standard_validates_complexity_enum():
    with pytest.raises(ValidationError):
        GoldStandard(
            expected_complexity="trivial",  # type: ignore[arg-type]
            expected_panel_verdict="prefer",
            expected_evidence_tier="clinical_trial",
            expected_min_chains=1,
            expected_defer=False,
            expected_red_flags=[],
            languages=["en"],
        )


def test_scenario_round_trip():
    s = Scenario(
        id="case-test-001",
        version="v1",
        category="herbal_single_symptom",
        research_question="Does ginger reduce nausea?",
        gold=GoldStandard(
            expected_complexity="low",
            expected_panel_verdict="prefer",
            expected_evidence_tier="clinical_trial",
            expected_min_chains=1,
            expected_defer=False,
            expected_red_flags=[],
            languages=["en"],
        ),
        rationale="Multiple RCTs support ginger for CINV.",
        source_citations=["Ryan 2012 PMID:21818642"],
    )
    raw = s.model_dump_json()
    s2 = Scenario.model_validate_json(raw)
    assert s2.id == s.id


def test_benchmark_v1_loads_and_validates():
    """v1 benchmark on disk must parse cleanly with at least 40 scenarios."""
    data = json.loads(BENCH_PATH.read_text())
    bench = BenchmarkSet.model_validate(data)
    assert len(bench.scenarios) >= 40
    counts: dict[str, int] = {}
    for s in bench.scenarios:
        counts[s.category] = counts.get(s.category, 0) + 1
    for cat in ("herbal_single_symptom", "nutrition", "multi_drug_hdi", "tcm_bilingual"):
        assert counts.get(cat, 0) >= 8, f"{cat} only has {counts.get(cat, 0)} scenarios"


def test_benchmark_v1_languages_include_zh_in_tcm_category():
    data = json.loads(BENCH_PATH.read_text())
    bench = BenchmarkSet.model_validate(data)
    tcm = [s for s in bench.scenarios if s.category == "tcm_bilingual"]
    assert any("zh" in s.gold.languages for s in tcm), "tcm_bilingual scenarios must include zh"
