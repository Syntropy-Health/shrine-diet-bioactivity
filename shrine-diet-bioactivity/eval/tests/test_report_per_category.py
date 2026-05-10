"""Test for per-category breakdown rendering."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eval.report import render_category_breakdown  # type: ignore[import-not-found]

pytestmark = [pytest.mark.unit]


@pytest.fixture
def fake_predictions_and_scenarios():
    """Two systems × four scenarios across three categories."""
    from eval.scenario import Scenario, GoldStandard

    def _scenario(scen_id: str, category: str) -> Scenario:
        return Scenario(
            id=scen_id, category=category,  # type: ignore[arg-type]
            research_question=f"Q for {scen_id}",
            gold=GoldStandard(
                expected_complexity="low", expected_panel_verdict="prefer",
                expected_evidence_tier="clinical_trial", expected_min_chains=1,
                expected_defer=False, expected_red_flags=[], languages=["en"],
            ),
            rationale="t", source_citations=[],
        )

    scenarios = [
        _scenario("h1", "herbal_single_symptom"),
        _scenario("h2", "herbal_single_symptom"),
        _scenario("n1", "nutrition"),
        _scenario("t1", "tcm_bilingual"),
    ]
    fake_pred = lambda: MagicMock()
    results = {
        "diet_os": [fake_pred(), fake_pred(), fake_pred(), fake_pred()],
        "single_llm": [fake_pred(), fake_pred(), fake_pred(), fake_pred()],
    }
    return results, scenarios


def test_render_category_breakdown_creates_table_and_heatmap(
    tmp_path, fake_predictions_and_scenarios
):
    """render_category_breakdown writes a markdown table per category and
    a category × system heatmap PNG."""
    results, scenarios = fake_predictions_and_scenarios

    def fake_metric(preds, scens):
        return 0.5  # placeholder

    out_md, out_png = render_category_breakdown(
        results, scenarios, out_dir=tmp_path,
        metric_fn=fake_metric, metric_name="verdict_kappa",
    )

    assert Path(out_md).exists()
    text = Path(out_md).read_text()
    assert "herbal_single_symptom" in text
    assert "nutrition" in text
    assert "tcm_bilingual" in text
    assert "diet_os" in text
    assert "single_llm" in text


def test_render_category_breakdown_handles_empty_category(tmp_path):
    """Empty results dict yields a stub markdown but doesn't crash."""
    out_md, _ = render_category_breakdown(
        {}, [], out_dir=tmp_path,
        metric_fn=lambda _p, _s: 0.0, metric_name="verdict_kappa",
    )
    assert Path(out_md).exists()
