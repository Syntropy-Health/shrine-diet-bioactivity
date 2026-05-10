"""Stratified split tests."""
from __future__ import annotations

import pytest

from eval.scenario import BenchmarkSet, GoldStandard, Scenario  # type: ignore[import-not-found]
from eval.splits import (  # type: ignore[import-not-found]
    check_no_entity_leakage,
    primary_entity,
    stratified_split,
)

pytestmark = [pytest.mark.unit]


def _mini_bench() -> BenchmarkSet:
    scenarios: list[Scenario] = []
    for cat in ("herbal_single_symptom", "nutrition", "multi_drug_hdi", "tcm_bilingual"):
        for cx in ("low", "moderate", "high"):
            for i in range(5):  # 5 per stratum * 12 strata = 60 (yields non-empty test)
                scenarios.append(
                    Scenario(
                        id=f"{cat}-{cx}-{i}",
                        category=cat,  # type: ignore[arg-type]
                        research_question=f"{cat} {cx} {i}",
                        gold=GoldStandard(
                            expected_complexity=cx,  # type: ignore[arg-type]
                            expected_panel_verdict="prefer",
                            expected_evidence_tier="clinical_trial",
                            expected_min_chains=1,
                            expected_defer=False,
                            expected_red_flags=[],
                            languages=["en"] if cat != "tcm_bilingual" else ["en", "zh"],
                        ),
                        rationale="test",
                        source_citations=[],
                    )
                )
    return BenchmarkSet(scenarios=scenarios)


def test_stratified_split_proportions():
    bench = _mini_bench()
    train, val, test = stratified_split(bench, ratios=(0.6, 0.2, 0.2), seed=42)
    assert len(train) + len(val) + len(test) == len(bench.scenarios)

    def cat_cx(s: Scenario) -> str:
        return f"{s.category}|{s.gold.expected_complexity}"

    for stratum in {cat_cx(s) for s in bench.scenarios}:
        assert any(cat_cx(s) == stratum for s in train), f"train missing stratum {stratum}"


def test_split_is_deterministic_with_seed():
    bench = _mini_bench()
    a = stratified_split(bench, ratios=(0.6, 0.2, 0.2), seed=42)
    b = stratified_split(bench, ratios=(0.6, 0.2, 0.2), seed=42)
    assert [s.id for s in a[0]] == [s.id for s in b[0]]


def test_primary_entity_extracts_herb():
    s = Scenario(
        id="x",
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
        rationale="x",
        source_citations=[],
    )
    assert primary_entity(s) == "ginger"  # tokenized + lowercased


def test_check_no_entity_leakage_raises_when_overlap():
    bench = _mini_bench()
    train, _val, test = stratified_split(bench, ratios=(0.6, 0.2, 0.2), seed=42)
    # All synthetic scenarios collapse to a small set of category-token entities
    # ("herbal", "nutrition", "multi", "tcm") -> overlap is guaranteed.
    with pytest.raises(ValueError, match="leakage"):
        check_no_entity_leakage(train, test)
