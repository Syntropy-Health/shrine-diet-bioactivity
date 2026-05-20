"""Shared fixtures + env-gating for `eval/tests/integration/` — Phases 3 & 4
of the integration-test coverage uplift plan
(`research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md`).

Two kinds of test live here:

  - Phase 3 (`test_pipeline_e2e.py`) — drives `diet_os.run(scenario)` against
    real OpenRouter (OPENROUTER_API_KEY) + real MCP gateway (MCP_API_KEY).
    Marked `[e2e, live_llm, slow]`.
  - Phase 4 (`test_report_rerender.py`, `test_benchmark_fixtures.py`,
    `test_results_artifact.py`) — local-only: re-render committed results +
    validate committed fixtures/artifacts. Marked `[integration]`
    (+ `slow` for the re-render). No network.

The `_require_live_env` autouse fixture is MARKER-AWARE: it only enforces
credential presence on tests carrying `e2e` or `live_llm`. Phase 4 local
tests run without credentials.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from eval.scenario import BenchmarkSet, Scenario  # type: ignore[import-not-found]

# Resolve the benchmark JSON path from this file's location:
#   __file__:  shrine-diet-bioactivity/eval/tests/integration/conftest.py
#   parents[4]: <repo root>
BENCH_PATH = (
    Path(__file__).resolve().parents[4]
    / "research-journal"
    / "shared"
    / "datasets"
    / "dietresearchbench_v1.json"
)


@pytest.fixture(scope="session")
def benchmark() -> BenchmarkSet:
    """Load DietResearchBench v1 once per session."""
    data = json.loads(BENCH_PATH.read_text(encoding="utf-8"))
    return BenchmarkSet.model_validate(data)


@pytest.fixture(scope="session")
def scenario_by_id(benchmark: BenchmarkSet):
    """Return a lookup callable: id -> Scenario."""
    index = {s.id: s for s in benchmark.scenarios}

    def _lookup(scenario_id: str) -> Scenario:
        if scenario_id not in index:
            pytest.fail(
                f"scenario id {scenario_id!r} not found in {BENCH_PATH.name}; "
                f"available ids start with: {sorted(index)[:3]}..."
            )
        return index[scenario_id]

    return _lookup


@pytest.fixture(autouse=True)
def _require_live_env(request: pytest.FixtureRequest) -> None:
    """Skip live tests (carrying `e2e` or `live_llm`) unless both live-env
    credentials are present.

    Marker-aware: Phase 4 local tests (`integration`-only) are exempt — they
    read committed artifacts and need no network. Phase 3 pipeline tests
    (`e2e + live_llm`) require credentials.

    For live tests this gives two layers of safety against accidental cost:
      1. Default `-m "not e2e"` (mcp/pyproject.toml addopts) deselects them.
      2. This fixture skips them even if explicitly selected without creds.
    """
    needs_live = any(
        request.node.get_closest_marker(m) for m in ("e2e", "live_llm")
    )
    if not needs_live:
        return
    missing = [
        var for var in ("OPENROUTER_API_KEY", "MCP_API_KEY") if not os.environ.get(var)
    ]
    if missing:
        pytest.skip(
            f"pipeline e2e requires {', '.join(missing)} — set in env to run"
        )


# Verdict-direction-aware confidence assertion helper lives in
# `_helpers.py` so test files can import it directly without depending on
# pytest's conftest collection mechanics.
