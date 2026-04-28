"""Tests for eval/runner.py — F5 eval runner.

Covers:
  1. Per-prediction JSON persistence: out_dir/<sys>/<scen.id>.json
  2. Manifest file written once per run with expected fields.
  3. Unknown system name raises ValueError.
  4. Baseline failure writes a placeholder ResearchSynthesis with verdict=abstain.
  5. Returned results dict lists are in same order as input scenarios.

All baselines are mocked via unittest.mock.patch.dict on BASELINES. No real LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest

from agents.models import (  # type: ignore[import-not-found]
    ConfidenceComponents,
    PanelDeliberation,
    ResearchQuestion,
    ResearchSynthesis,
    RoleVerdict,
    Triage,
)
from eval.baselines import BASELINES  # type: ignore[import-not-found]
from eval.runner import run_eval  # type: ignore[import-not-found]
from eval.scenario import BenchmarkSet, GoldStandard, Scenario  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scenario(idx: int, category: str = "herbal_single_symptom") -> Scenario:
    return Scenario(
        id=f"test-scen-{idx:03d}",
        version="v1",
        category=category,  # type: ignore[arg-type]
        research_question=f"Research question {idx}",
        gold=GoldStandard(
            expected_complexity="low",
            expected_panel_verdict="prefer",
            expected_evidence_tier="clinical_trial",
            expected_min_chains=1,
            expected_defer=False,
            expected_red_flags=[],
            languages=["en"],
        ),
        rationale=f"Test rationale {idx}",
        source_citations=[],
    )


def _make_synthesis(scenario: Scenario, verdict: str = "prefer") -> ResearchSynthesis:
    """Build a minimal valid ResearchSynthesis for mocking."""
    return ResearchSynthesis(
        question=ResearchQuestion(text=scenario.research_question),
        triage=Triage(complexity="low", rationale="mock-run", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(
            verdicts=[
                RoleVerdict(
                    role="Dietitian",
                    verdict=verdict,  # type: ignore[arg-type]
                    support=["mock support"],
                    concerns=[],
                    notes="mock note",
                )
            ],
            dissent=[],
            moderator_summary="mock moderator",
        ),
        confidence=0.8,
        components=ConfidenceComponents(evidence_tier=0.8, hdi_risk=0.0, question_fit=0.8),
        defer_to_clinician=False,
    )


def _stub_baseline(verdict: str = "prefer") -> Callable[[Scenario], ResearchSynthesis]:
    """Return a callable baseline that always succeeds."""
    def _run(scenario: Scenario) -> ResearchSynthesis:
        return _make_synthesis(scenario, verdict)
    return _run


def _make_bench(scenarios: list[Scenario]) -> BenchmarkSet:
    return BenchmarkSet(
        name="DietResearchBench-Clinical",
        version="v1",
        scenarios=scenarios,
    )


# ---------------------------------------------------------------------------
# Test 1 — per-prediction JSON files written to out_dir/<sys>/<scen.id>.json
# ---------------------------------------------------------------------------

def test_run_eval_persists_per_prediction_json(tmp_path: Path) -> None:
    """run_eval must write out_dir/<system>/<scenario_id>.json for every (scenario, system) pair."""
    scenarios = [_make_scenario(i) for i in range(3)]
    bench = _make_bench(scenarios)

    mock_baselines = {
        "sys_a": _stub_baseline("prefer"),
        "sys_b": _stub_baseline("caution"),
    }

    with patch.dict(BASELINES, mock_baselines, clear=True):
        results = run_eval(bench, scenarios, out_dir=tmp_path, systems=["sys_a", "sys_b"])

    # Each system × scenario → one JSON file
    for sys_name in ("sys_a", "sys_b"):
        for scen in scenarios:
            expected_path = tmp_path / sys_name / f"{scen.id}.json"
            assert expected_path.exists(), f"Missing prediction file: {expected_path}"
            # Must parse as valid ResearchSynthesis
            rs = ResearchSynthesis.model_validate_json(expected_path.read_text())
            assert rs.question.text == scen.research_question

    # Results dict has both systems
    assert set(results.keys()) == {"sys_a", "sys_b"}
    # Each system list has one entry per scenario
    for sys_name in ("sys_a", "sys_b"):
        assert len(results[sys_name]) == len(scenarios)


# ---------------------------------------------------------------------------
# Test 2 — manifest JSON written once per run with expected fields
# ---------------------------------------------------------------------------

def test_run_eval_writes_manifest_with_timestamp(tmp_path: Path) -> None:
    """run_eval must write a manifest-<timestamp>.json with required fields."""
    scenarios = [_make_scenario(0), _make_scenario(1)]
    bench = _make_bench(scenarios)

    mock_baselines = {"sys_x": _stub_baseline()}

    with patch.dict(BASELINES, mock_baselines, clear=True):
        run_eval(bench, scenarios, out_dir=tmp_path, systems=["sys_x"])

    manifests = list(tmp_path.glob("manifest-*.json"))
    assert len(manifests) == 1, f"Expected 1 manifest, found {len(manifests)}: {manifests}"

    manifest = json.loads(manifests[0].read_text())

    # Required fields
    assert "benchmark_version" in manifest
    assert "scenario_count" in manifest
    assert "systems" in manifest
    assert "scenario_ids" in manifest
    assert "timestamp" in manifest

    # Values match what we passed
    assert manifest["benchmark_version"] == bench.version
    assert manifest["scenario_count"] == len(scenarios)
    assert manifest["systems"] == ["sys_x"]
    assert manifest["scenario_ids"] == [s.id for s in scenarios]

    # Timestamp must be a non-empty string in UTC ISO format (YYYYmmddTHHMMSSZ)
    ts = manifest["timestamp"]
    assert isinstance(ts, str) and len(ts) > 0
    assert ts.endswith("Z"), f"Timestamp must end with Z (UTC), got: {ts!r}"


# ---------------------------------------------------------------------------
# Test 3 — unknown system raises ValueError before any I/O
# ---------------------------------------------------------------------------

def test_run_eval_unknown_system_raises(tmp_path: Path) -> None:
    """Passing a system not in BASELINES must raise ValueError immediately."""
    scenarios = [_make_scenario(0)]
    bench = _make_bench(scenarios)

    mock_baselines = {"known_sys": _stub_baseline()}

    with patch.dict(BASELINES, mock_baselines, clear=True):
        with pytest.raises(ValueError, match="unknown system"):
            run_eval(bench, scenarios, out_dir=tmp_path, systems=["definitely_not_registered"])


# ---------------------------------------------------------------------------
# Test 4 — baseline failure writes placeholder with verdict=abstain
# ---------------------------------------------------------------------------

def test_run_eval_baseline_failure_writes_placeholder(tmp_path: Path) -> None:
    """When a baseline raises, runner writes a placeholder ResearchSynthesis
    with an empty verdicts list (abstain-equivalent) and confidence=0.0."""

    scenarios = [_make_scenario(0)]
    bench = _make_bench(scenarios)

    def _failing_baseline(scenario: Scenario) -> ResearchSynthesis:
        raise RuntimeError("Simulated LLM failure")

    mock_baselines = {"failing_sys": _failing_baseline}

    with patch.dict(BASELINES, mock_baselines, clear=True):
        results = run_eval(bench, scenarios, out_dir=tmp_path, systems=["failing_sys"])

    # run_eval must still return a result (one entry per scenario)
    assert len(results["failing_sys"]) == 1

    # Placeholder file must exist and parse
    placeholder_path = tmp_path / "failing_sys" / f"{scenarios[0].id}.json"
    assert placeholder_path.exists(), "Placeholder JSON not written"

    rs = ResearchSynthesis.model_validate_json(placeholder_path.read_text())

    # Placeholder properties: confidence=0.0 and no verdicts (abstain)
    assert rs.confidence == 0.0
    assert rs.panel.verdicts == []

    # Error text is surfaced in panel dissent
    assert any("Simulated LLM failure" in d for d in rs.panel.dissent), (
        f"Error message not in dissent: {rs.panel.dissent}"
    )


# ---------------------------------------------------------------------------
# Test 5 — returned results matrix is in same order as input scenarios
# ---------------------------------------------------------------------------

def test_run_eval_returns_results_matrix_in_scenario_order(tmp_path: Path) -> None:
    """Results[system] list must be in the same order as the input scenarios list."""
    n = 5
    # Create scenarios in a non-trivial id order
    scenarios = [_make_scenario(i) for i in [7, 2, 9, 1, 5]]
    bench = _make_bench(scenarios)

    call_order: list[str] = []

    def _ordered_baseline(scenario: Scenario) -> ResearchSynthesis:
        call_order.append(scenario.id)
        return _make_synthesis(scenario)

    mock_baselines = {"ordered_sys": _ordered_baseline}

    with patch.dict(BASELINES, mock_baselines, clear=True):
        results = run_eval(bench, scenarios, out_dir=tmp_path, systems=["ordered_sys"])

    assert "ordered_sys" in results
    result_list = results["ordered_sys"]

    # Length matches
    assert len(result_list) == len(scenarios)

    # Each result matches the corresponding scenario's question text
    for rs, scen in zip(result_list, scenarios):
        assert rs.question.text == scen.research_question, (
            f"Order mismatch: got {rs.question.text!r}, expected {scen.research_question!r}"
        )

    # Baseline was called in input order
    assert call_order == [s.id for s in scenarios]


# ---------------------------------------------------------------------------
# Test 6 — manifest is refreshed after EACH system completes
# ---------------------------------------------------------------------------

def test_run_eval_writes_manifest_after_each_system(tmp_path: Path) -> None:
    """Manifest must be written/refreshed after each system's inner loop
    completes, not only after the final system. Otherwise a kill mid-run
    leaves the dir un-renderable by eval/report.py.

    Contract: a single manifest-<timestamp>.json file at the run dir is
    overwritten N+1 times (once after each of N systems; an initial empty
    write before any system is optional). The systems list grows as each
    system finishes.
    """
    scenarios = [_make_scenario(0)]
    bench = _make_bench(scenarios)

    mock_baselines = {
        "sys_a": _stub_baseline("prefer"),
        "sys_b": _stub_baseline("caution"),
        "sys_c": _stub_baseline("reject"),
    }

    write_calls: list[list[str]] = []
    original_write = Path.write_text

    def _spy(self: Path, data: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name.startswith("manifest-") and self.suffix == ".json":
            try:
                payload = json.loads(data)
                write_calls.append(list(payload.get("systems", [])))
            except (ValueError, TypeError):
                pass
        return original_write(self, data, *args, **kwargs)

    with patch.dict(BASELINES, mock_baselines, clear=True), \
         patch.object(Path, "write_text", _spy):
        run_eval(
            bench, scenarios, out_dir=tmp_path,
            systems=["sys_a", "sys_b", "sys_c"],
        )

    assert len(write_calls) >= 3, (
        f"Manifest was written {len(write_calls)} time(s); expected at "
        f"least once per completed system (3). Calls: {write_calls}"
    )

    # Final write must list all three systems in input order.
    assert write_calls[-1] == ["sys_a", "sys_b", "sys_c"], (
        f"Final manifest must list all systems; got {write_calls[-1]!r}"
    )

    # The systems list must grow monotonically — earlier writes never
    # contain a system that later ones drop. (Captures the "snapshot of
    # progress so far" semantics.)
    seen_lengths = [len(c) for c in write_calls]
    assert seen_lengths == sorted(seen_lengths), (
        f"Manifest systems list shrank between writes: {write_calls}"
    )

    # End state: exactly one manifest file on disk.
    manifests = list(tmp_path.glob("manifest-*.json"))
    assert len(manifests) == 1, (
        f"Expected exactly 1 manifest file, found {len(manifests)}: {manifests}"
    )
