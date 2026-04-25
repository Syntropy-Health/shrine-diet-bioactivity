"""Tests for eval/report.py — results reporter (Task F6).

Six tests covering:
1. bootstrap_ci returns a valid interval that brackets the mean.
2. render_report writes summary.md with all 6 systems and 6 metrics.
3. render_report writes a non-trivial reliability_diagram.png (> 1 KB).
4. render_report writes paired_tests.md with Bonferroni + 5 baseline rows.
5. render_report returns a JSON-serialisable dict.
6. render_report gracefully handles NaN metrics (shows "—" in markdown).
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from agents.models import (  # type: ignore[import-not-found]
    ConfidenceComponents,
    PanelDeliberation,
    ResearchQuestion,
    ResearchSynthesis,
    RoleVerdict,
    Triage,
)
from eval.report import bootstrap_ci, render_report  # type: ignore[import-not-found]
from eval.scenario import GoldStandard, Scenario  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_SYSTEMS = ["diet_os", "single_llm", "single_llm_rag", "yang2025", "medagents", "mdagents"]


def _mk_synthesis(
    verdict: str = "prefer",
    confidence: float = 0.7,
    defer: bool = False,
) -> ResearchSynthesis:
    return ResearchSynthesis(
        question=ResearchQuestion(text="Does herb X treat condition Y?"),
        triage=Triage(complexity="low", rationale="test", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(
            verdicts=[
                RoleVerdict(
                    role="Dietitian",
                    verdict=verdict,  # type: ignore[arg-type]
                    support=[],
                    concerns=[],
                    notes="",
                )
            ],
            dissent=[],
            moderator_summary="",
        ),
        confidence=confidence,
        components=ConfidenceComponents(evidence_tier=0.5, hdi_risk=0.0, question_fit=0.5),
        defer_to_clinician=defer,
    )


def _mk_scenario(
    verdict: str = "prefer",
    category: str = "herbal_single_symptom",
    hdi_severity: str = "none",
    expected_defer: bool = False,
) -> Scenario:
    return Scenario(
        id="scen-test",
        category=category,  # type: ignore[arg-type]
        research_question="Does herb X treat condition Y?",
        gold=GoldStandard(
            expected_complexity="low",
            expected_panel_verdict=verdict,  # type: ignore[arg-type]
            expected_evidence_tier="clinical_trial",
            expected_min_chains=1,
            expected_defer=expected_defer,
            expected_red_flags=[],
            expected_hdi_severity=hdi_severity,  # type: ignore[arg-type]
            languages=["en"],
        ),
        rationale="test",
        source_citations=[],
    )


def _make_results_and_scenarios(
    n: int = 5,
    verdict: str = "prefer",
) -> tuple[dict[str, list[ResearchSynthesis]], list[Scenario]]:
    """Build a minimal results dict (all 6 systems) + matching scenarios list."""
    scenarios = [_mk_scenario(verdict=verdict) for _ in range(n)]
    results: dict[str, list[ResearchSynthesis]] = {
        sys: [_mk_synthesis(verdict=verdict) for _ in range(n)]
        for sys in _SYSTEMS
    }
    return results, scenarios


# ---------------------------------------------------------------------------
# Test 1 — bootstrap_ci returns a valid interval bracketing the mean
# ---------------------------------------------------------------------------


class TestBootstrapCi:
    def test_ci_brackets_mean_for_synthetic_data(self):
        """CI must satisfy lo <= mean <= hi for a well-behaved distribution."""
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        lo, hi = bootstrap_ci(values, n_iter=1000, seed=42)
        mean_val = sum(values) / len(values)
        assert lo <= mean_val <= hi, f"CI [{lo:.4f}, {hi:.4f}] does not bracket mean {mean_val:.4f}"

    def test_ci_lo_less_than_hi(self):
        """Lower bound must always be less than upper bound."""
        values = [float(i) / 100 for i in range(1, 101)]
        lo, hi = bootstrap_ci(values, n_iter=500, seed=0)
        assert lo < hi

    def test_ci_constant_distribution_collapses_to_point(self):
        """All identical values → CI is essentially a point interval."""
        values = [0.5] * 20
        lo, hi = bootstrap_ci(values, n_iter=200, seed=7)
        assert lo == pytest.approx(0.5, abs=1e-9)
        assert hi == pytest.approx(0.5, abs=1e-9)

    def test_ci_respects_alpha(self):
        """Wider alpha=0.10 (90% CI) should be narrower than alpha=0.02 (98% CI)."""
        values = list(range(100))
        lo90, hi90 = bootstrap_ci([v / 100 for v in values], n_iter=1000, seed=42, alpha=0.10)
        lo98, hi98 = bootstrap_ci([v / 100 for v in values], n_iter=1000, seed=42, alpha=0.02)
        # 90% CI is contained within 98% CI
        assert lo98 <= lo90
        assert hi90 <= hi98

    def test_ci_seed_deterministic(self):
        """Same seed must produce identical CI."""
        values = [0.1, 0.3, 0.5, 0.7, 0.9]
        r1 = bootstrap_ci(values, n_iter=500, seed=123)
        r2 = bootstrap_ci(values, n_iter=500, seed=123)
        assert r1 == r2


# ---------------------------------------------------------------------------
# Test 2 — render_report writes summary.md with 6 systems × 6 metrics
# ---------------------------------------------------------------------------


class TestRenderReportSummaryMd:
    def test_summary_md_exists_and_contains_all_systems_and_metrics(self):
        results, scenarios = _make_results_and_scenarios(n=6)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            render_report(results, scenarios, out_dir, n_bootstrap=100, seed=42)
            summary = out_dir / "summary.md"
            assert summary.exists(), "summary.md was not written"
            content = summary.read_text()
            # All 6 system names must appear
            for sys in _SYSTEMS:
                assert sys in content, f"system '{sys}' missing from summary.md"
            # All 6 metric names must appear
            for metric in [
                "verdict_kappa",
                "ece",
                "hdi_recall",
                "provenance",
                "defer_acc",
                "bilingual",
            ]:
                assert metric in content, f"metric '{metric}' missing from summary.md"

    def test_summary_md_is_markdown_table(self):
        """summary.md must contain pipe characters (Markdown table syntax)."""
        results, scenarios = _make_results_and_scenarios(n=4)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            render_report(results, scenarios, out_dir, n_bootstrap=50, seed=42)
            content = (out_dir / "summary.md").read_text()
            assert "|" in content, "summary.md does not appear to be a Markdown table"


# ---------------------------------------------------------------------------
# Test 3 — render_report writes reliability_diagram.png > 1 KB
# ---------------------------------------------------------------------------


class TestReliabilityDiagram:
    def test_png_file_exists_and_is_nontrivial(self):
        """PNG must exist and be larger than 1 KB (a real matplotlib render)."""
        results, scenarios = _make_results_and_scenarios(n=6)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            render_report(results, scenarios, out_dir, n_bootstrap=50, seed=42)
            png = out_dir / "reliability_diagram.png"
            assert png.exists(), "reliability_diagram.png was not written"
            assert png.stat().st_size > 1024, (
                f"reliability_diagram.png is only {png.stat().st_size} bytes — "
                "expected a real matplotlib render > 1 KB"
            )


# ---------------------------------------------------------------------------
# Test 4 — render_report writes paired_tests.md with Bonferroni + 5 baselines
# ---------------------------------------------------------------------------


class TestPairedTestsMd:
    def test_paired_tests_md_contains_bonferroni_and_five_baseline_rows(self):
        results, scenarios = _make_results_and_scenarios(n=6, verdict="prefer")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            render_report(results, scenarios, out_dir, n_bootstrap=100, seed=42)
            pt = out_dir / "paired_tests.md"
            assert pt.exists(), "paired_tests.md was not written"
            content = pt.read_text()
            # Must mention Bonferroni adjustment
            assert "Bonferroni" in content, "paired_tests.md missing Bonferroni mention"
            # Must have a row for each of the 5 non-diet_os baselines
            baselines = ["single_llm", "single_llm_rag", "yang2025", "medagents", "mdagents"]
            for bl in baselines:
                assert bl in content, f"baseline '{bl}' missing from paired_tests.md"

    def test_paired_tests_md_has_pipe_table(self):
        """paired_tests.md must be a Markdown pipe table."""
        results, scenarios = _make_results_and_scenarios(n=4)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            render_report(results, scenarios, out_dir, n_bootstrap=50, seed=42)
            content = (out_dir / "paired_tests.md").read_text()
            assert "|" in content


# ---------------------------------------------------------------------------
# Test 5 — render_report returns a JSON-serialisable dict
# ---------------------------------------------------------------------------


class TestReturnValueIsJsonSerializable:
    def test_return_value_serializes_via_json_dumps(self):
        results, scenarios = _make_results_and_scenarios(n=5)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            ret = render_report(results, scenarios, out_dir, n_bootstrap=50, seed=42)
            # Must not raise
            serialized = json.dumps(ret)
            parsed = json.loads(serialized)
            # Outer keys are metric names
            assert isinstance(parsed, dict)
            assert len(parsed) > 0
            # Inner keys are system names
            for metric_data in parsed.values():
                assert isinstance(metric_data, dict)
                for sys_data in metric_data.values():
                    # Each cell has mean, ci_lo, ci_hi (or None for NaN)
                    assert "mean" in sys_data
                    assert "ci_lo" in sys_data
                    assert "ci_hi" in sys_data

    def test_return_value_contains_all_metrics(self):
        """Return dict must have keys for all 6 metrics."""
        results, scenarios = _make_results_and_scenarios(n=5)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            ret = render_report(results, scenarios, out_dir, n_bootstrap=50, seed=42)
        expected_metrics = {
            "verdict_kappa",
            "ece",
            "hdi_recall",
            "provenance",
            "defer_acc",
            "bilingual",
        }
        assert expected_metrics.issubset(set(ret.keys())), (
            f"Missing metrics in return dict: {expected_metrics - set(ret.keys())}"
        )


# ---------------------------------------------------------------------------
# Test 6 — render_report handles NaN metrics gracefully (shows "—" in markdown)
# ---------------------------------------------------------------------------


class TestNanMetricGracefulHandling:
    def test_nan_metric_shows_dash_in_summary_md(self):
        """When a metric returns NaN (e.g., no severe-HDI or no tcm_bilingual
        scenarios), summary.md must render '—' in the affected cells rather than
        'nan' or raising an exception."""
        # Use only herbal_single_symptom scenarios with none hdi_severity.
        # This forces hdi_recall and bilingual_coverage to return NaN.
        n = 4
        scenarios = [_mk_scenario(category="herbal_single_symptom", hdi_severity="none") for _ in range(n)]
        results: dict[str, list[ResearchSynthesis]] = {
            sys: [_mk_synthesis() for _ in range(n)]
            for sys in _SYSTEMS
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            render_report(results, scenarios, out_dir, n_bootstrap=50, seed=42)
            content = (out_dir / "summary.md").read_text()
            # "—" must appear at least once (for hdi_recall and bilingual cells)
            assert "—" in content, (
                "summary.md should show '—' for undefined metrics, but none found"
            )
            # Must NOT contain numeric 'nan' as a standalone token.
            # (Note: "Provenance" legitimately contains "nan" as a substring,
            # so we check for word-boundary patterns: ' nan', '|nan', or
            # lines that contain only 'nan' as a cell value.)
            import re as _re
            bare_nan = _re.compile(r"(?<![A-Za-z])nan(?![A-Za-z])", _re.IGNORECASE)
            assert not bare_nan.search(content), (
                "summary.md contains bare numeric 'nan' token — "
                "NaN metrics must be rendered as '—'"
            )

    def test_per_system_json_contains_nan_for_undefined_metrics(self):
        """per_system/<sys>/per_metric.json must mark undefined metrics as null."""
        n = 3
        scenarios = [_mk_scenario(category="herbal_single_symptom", hdi_severity="none") for _ in range(n)]
        results: dict[str, list[ResearchSynthesis]] = {
            sys: [_mk_synthesis() for _ in range(n)]
            for sys in _SYSTEMS
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            render_report(results, scenarios, out_dir, n_bootstrap=50, seed=42)
            # Check diet_os per_metric.json
            pm_path = out_dir / "per_system" / "diet_os" / "per_metric.json"
            assert pm_path.exists(), "per_system/diet_os/per_metric.json not written"
            pm = json.loads(pm_path.read_text())
            # hdi_recall should be null (JSON null for Python None)
            assert pm.get("hdi_recall", "MISSING") is None, (
                f"hdi_recall should be null in per_metric.json, got {pm.get('hdi_recall')}"
            )
