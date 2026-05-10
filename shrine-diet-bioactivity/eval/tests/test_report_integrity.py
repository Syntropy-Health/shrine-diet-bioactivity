"""Regression tests for eval.report manifest → scenario resolution integrity.

Closes issue #16: silent synthetic-gold fabrication when a manifest
``scenario_id`` is not found in the benchmark dataset is a latent
integrity risk. PEP 661 / SRE convention is fail-loud-by-default with
explicit opt-in for permissive mode.

These tests are written FIRST (TDD RED phase). They target a public
function ``load_run_scenarios(results_dir, *, allow_stubs=False) ->
list[Scenario]`` that B-GREEN will extract from the
``if __name__ == '__main__':`` block in ``eval/report.py``. Until B-GREEN
lands, tests 1 and 2 are expected to FAIL (either because the function
does not yet exist, or because the silent-stub behavior is still in
place). Test 3 is a regression guard for the all-found case (paper-1 v1
condition: 40/40 manifest ∩ benchmark match).

Post-B-GREEN contract:
    load_run_scenarios(results_dir, *, allow_stubs=False)
        Reads ``results_dir/manifest-*.json`` for ``scenario_ids`` and
        resolves each id against the benchmark dataset
        ``results_dir.parents[1] / 'datasets' /
        'dietresearchbench_v1.json'``.
        - Default (allow_stubs=False): raises RuntimeError if any
          scenario_id is not present in the benchmark.
        - allow_stubs=True: missing ids fall back to a synthetic neutral
          gold stub with expected_panel_verdict='abstain'.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Importing eval.report itself must not fail; the tested symbol may not
# yet exist (B-RED: ImportError → AttributeError below is the failure
# mode that makes test 2 RED).
import eval.report as _report  # type: ignore[import-not-found]
from eval.scenario import (  # type: ignore[import-not-found]
    BenchmarkSet,
    GoldStandard,
    Scenario,
)

from ._braintrust_logger import bt_span

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Paper-1 v1 benchmark cardinality (research-journal/shared/datasets/
# dietresearchbench_v1.json). Used by the all-found regression test (test 3)
# to assert the production-data shape.
_PAPER_1_V1_SCENARIO_COUNT = 40


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_manifest(
    results_dir: Path,
    scenario_ids: list[str],
    *,
    timestamp: str = "20260505T000000Z",
    systems: list[str] | None = None,
    benchmark_version: str = "v1",
) -> Path:
    """Write a manifest-<ts>.json mirroring the eval.runner schema.

    Note:
        When ``systems`` is omitted (or ``None``), the manifest's ``systems``
        list is empty. Tests using this fixture in that mode therefore exercise
        only the scenario-resolution code path of ``load_run_scenarios`` —
        i.e. the manifest ``scenario_ids`` -> benchmark lookup. If future
        extensions of ``load_run_scenarios`` also load per-system predictions
        from disk, those code paths will need fixtures that pass
        ``systems=[...]`` *and* pre-populate per-system JSON dirs alongside
        the manifest.
    """
    manifest_path = results_dir / f"manifest-{timestamp}.json"
    manifest_path.write_text(
        json.dumps(
            {
                "benchmark_version": benchmark_version,
                "scenario_count": len(scenario_ids),
                "systems": systems or [],
                "scenario_ids": scenario_ids,
                "timestamp": timestamp,
            },
            indent=2,
        )
    )
    return manifest_path


def _mk_scenario(scen_id: str) -> Scenario:
    return Scenario(
        id=scen_id,
        category="herbal_single_symptom",
        research_question=f"question for {scen_id}",
        gold=GoldStandard(
            expected_complexity="low",
            expected_panel_verdict="prefer",
            expected_evidence_tier="clinical_trial",
            expected_min_chains=1,
            expected_defer=False,
            expected_red_flags=[],
            languages=["en"],
        ),
        rationale="fixture",
    )


def _write_benchmark(
    datasets_dir: Path,
    scenarios: list[Scenario],
) -> Path:
    """Write a dietresearchbench_v1.json at the expected sibling path."""
    datasets_dir.mkdir(parents=True, exist_ok=True)
    bench = BenchmarkSet(scenarios=scenarios)
    bench_path = datasets_dir / "dietresearchbench_v1.json"
    bench_path.write_text(bench.model_dump_json(indent=2))
    return bench_path


def _make_results_layout(
    tmp_path: Path,
    *,
    benchmark_scenarios: list[Scenario],
    manifest_scenario_ids: list[str],
) -> Path:
    """Build the results-dir layout report.py expects:

        tmp_path/
          results/
            run-1/                    <- results_dir (returned)
              manifest-<ts>.json
          datasets/
            dietresearchbench_v1.json

    report.py looks up benchmark via
    ``results_dir.parents[1] / 'datasets' / 'dietresearchbench_v1.json'``.
    """
    root = tmp_path
    results_dir = root / "results" / "run-1"
    results_dir.mkdir(parents=True, exist_ok=True)
    datasets_dir = root / "datasets"
    _write_benchmark(datasets_dir, benchmark_scenarios)
    _write_manifest(results_dir, manifest_scenario_ids)
    return results_dir


# ---------------------------------------------------------------------------
# Test 1 — missing scenario_id → RuntimeError (default fail-loud)
# ---------------------------------------------------------------------------


def test_missing_scenario_id_fails_render(tmp_path: Path) -> None:
    """A scenario_id present in the manifest but absent from the benchmark
    must raise RuntimeError by default. The error must name the offending
    id and explain that synthetic gold is being refused.

    RED: the current code silently fabricates a neutral stub via the
    inline ``_neutral_stub`` helper, so no exception is raised.
    """
    with bt_span(
        "test_missing_scenario_id_fails_render",
        scenario_id="not-in-benchmark-xyz",
        benchmark_size=1,
    ) as span:
        benchmark = [_mk_scenario("real-scen-001")]
        results_dir = _make_results_layout(
            tmp_path,
            benchmark_scenarios=benchmark,
            manifest_scenario_ids=["not-in-benchmark-xyz"],
        )

        load_fn = getattr(_report, "load_run_scenarios", None)
        assert load_fn is not None, (
            "eval.report.load_run_scenarios does not exist yet — B-GREEN "
            "must extract the manifest→scenario resolution logic into a "
            "public function before this test can pass."
        )

        with pytest.raises(RuntimeError) as excinfo:
            load_fn(results_dir)

        msg = str(excinfo.value)
        span.log(output={"raised": "RuntimeError", "message_excerpt": msg[:300]})
        assert "not in benchmark" in msg, (
            f"RuntimeError message should mention 'not in benchmark'; got: {msg!r}"
        )
        assert "not-in-benchmark-xyz" in msg, (
            f"RuntimeError message should name the offending scenario_id "
            f"'not-in-benchmark-xyz'; got: {msg!r}"
        )


# ---------------------------------------------------------------------------
# Test 2 — allow_stubs=True preserves prior lenient behavior
# ---------------------------------------------------------------------------


def test_missing_scenario_id_allowed_with_flag(tmp_path: Path) -> None:
    """With ``allow_stubs=True``, missing scenario_ids must fall back to a
    synthetic neutral gold stub (expected_panel_verdict='abstain'),
    matching the prior lenient behavior.

    RED: the function does not yet accept an ``allow_stubs`` kwarg.
    """
    with bt_span(
        "test_missing_scenario_id_allowed_with_flag",
        scenario_id="not-in-benchmark-xyz",
        allow_stubs=True,
    ) as span:
        benchmark = [_mk_scenario("real-scen-001")]
        results_dir = _make_results_layout(
            tmp_path,
            benchmark_scenarios=benchmark,
            manifest_scenario_ids=["not-in-benchmark-xyz"],
        )

        load_fn = getattr(_report, "load_run_scenarios", None)
        assert load_fn is not None, (
            "eval.report.load_run_scenarios does not exist yet — B-GREEN "
            "must extract the manifest→scenario resolution logic into a "
            "public function before this test can pass."
        )

        # Must not raise when allow_stubs=True
        scenarios = load_fn(results_dir, allow_stubs=True)

        span.log(
            output={
                "scenario_count": len(scenarios) if isinstance(scenarios, list) else None,
                "stub_id": scenarios[0].id if scenarios else None,
                "stub_verdict": (
                    scenarios[0].gold.expected_panel_verdict if scenarios else None
                ),
            }
        )

        assert isinstance(scenarios, list)
        assert len(scenarios) == 1, (
            f"Expected 1 scenario (the manifest has 1 id); got {len(scenarios)}"
        )
        stub = scenarios[0]
        assert stub.id == "not-in-benchmark-xyz", (
            f"Stub id should preserve the manifest scenario_id; got {stub.id!r}"
        )
        assert stub.gold.expected_panel_verdict == "abstain", (
            "Synthetic neutral gold must default to expected_panel_verdict="
            f"'abstain'; got {stub.gold.expected_panel_verdict!r}"
        )


# ---------------------------------------------------------------------------
# Test 3 — full benchmark render (40/40 match) is unaffected
# ---------------------------------------------------------------------------


def test_full_benchmark_render_unaffected(tmp_path: Path) -> None:
    """Regression guard for the paper-1 v1 condition: when every
    manifest scenario_id is present in the benchmark, default-mode
    resolution must succeed and return real Scenario objects (no stubs).

    Uses the real ``research-journal/shared/datasets/dietresearchbench_v1.json``
    (40 scenarios) when available so this test doubles as an
    end-to-end fixture for the production data shape.
    """
    with bt_span(
        "test_full_benchmark_render_unaffected",
        expected_scenario_count=_PAPER_1_V1_SCENARIO_COUNT,
    ) as span:
        # Locate the real benchmark file. Worktree layout:
        #   <worktree>/shrine-diet-bioactivity/eval/tests/test_report_integrity.py
        #   <worktree>/research-journal/shared/datasets/dietresearchbench_v1.json
        here = Path(__file__).resolve()
        repo_root = here.parents[2]  # shrine-diet-bioactivity/
        worktree_root = repo_root.parent  # worktree containing research-journal/
        real_bench = (
            worktree_root
            / "research-journal"
            / "shared"
            / "datasets"
            / "dietresearchbench_v1.json"
        )

        if not real_bench.exists():
            span.log(output={"skipped": True, "reason": "benchmark_file_missing"})
            pytest.skip(
                f"Real benchmark not found at {real_bench}; "
                "this test only validates the production-data path. "
                "Run from the lightrag-test-debt worktree where "
                "research-journal/shared/datasets/ is present."
            )
        # Only reached when the real benchmark file exists — no synthetic fallback.
        bench_data = json.loads(real_bench.read_text())
        bench_set = BenchmarkSet.model_validate(bench_data)
        benchmark_scenarios = list(bench_set.scenarios)

        manifest_scenario_ids = [s.id for s in benchmark_scenarios]
        assert len(manifest_scenario_ids) == _PAPER_1_V1_SCENARIO_COUNT, (
            f"Test 3 expects a {_PAPER_1_V1_SCENARIO_COUNT}-scenario benchmark "
            f"to mirror the paper-1 v1 condition; got "
            f"{len(manifest_scenario_ids)} scenarios"
        )

        results_dir = _make_results_layout(
            tmp_path,
            benchmark_scenarios=benchmark_scenarios,
            manifest_scenario_ids=manifest_scenario_ids,
        )

        load_fn = getattr(_report, "load_run_scenarios", None)
        assert load_fn is not None, (
            "eval.report.load_run_scenarios does not exist yet — B-GREEN "
            "must extract the manifest→scenario resolution logic into a "
            "public function before this test can pass."
        )

        # Default args, no allow_stubs — should succeed because every id matches.
        run_scenarios = load_fn(results_dir)

        stub_count = sum(
            1 for s in run_scenarios if getattr(s, "rationale", "") == "reconstructed stub"
        )
        span.log(
            output={
                "scenario_count": len(run_scenarios),
                "stub_count": stub_count,
            }
        )

        assert len(run_scenarios) == _PAPER_1_V1_SCENARIO_COUNT, (
            f"Expected {_PAPER_1_V1_SCENARIO_COUNT} run scenarios; "
            f"got {len(run_scenarios)}"
        )
        bench_id_set = {s.id for s in benchmark_scenarios}
        for s in run_scenarios:
            assert isinstance(s, Scenario)
            assert s.id in bench_id_set, (
                f"Scenario {s.id!r} not in benchmark — render path returned a "
                "stub even though every manifest id should have matched a real "
                "benchmark scenario."
            )
            # Real benchmark scenarios carry a non-default rationale; the
            # synthetic stub uses 'reconstructed stub'. This is a coarse but
            # robust 'not a stub' check.
            assert s.rationale != "reconstructed stub", (
                f"Scenario {s.id!r} appears to be a synthetic stub "
                "(rationale=='reconstructed stub') — the all-found path must "
                "return real Scenario objects."
            )
