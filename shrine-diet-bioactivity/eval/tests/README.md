# Eval test suite

## Markers (from project `pytest.ini`)

| Marker | Meaning |
|---|---|
| `unit` | Pure unit, no I/O, no network |
| `integration` | Real components (file system, multi-layer roundtrip) |
| `e2e` | Real network call to staged services |
| `live_llm` | Calls OpenRouter / Nemotron real-time |
| `live_llm_replay` | Cassette replay of LLM call |
| `aura` | Hits live Neo4j Aura |
| `slow` | Runtime > 30s |

## Layout

- `test_*.py` — unit tests for the eval harness (runner, report, metrics,
  baselines, scenario schema).
- `integration/` — Phase 3 & 4 of the coverage uplift plan:
  - `test_pipeline_e2e.py` — `diet_os.run()` against real OpenRouter + MCP
    gateway (`e2e + live_llm + slow`).
  - `test_benchmark_fixtures.py` — DietResearchBench v1 fixture sanity.
  - `test_results_artifact.py` — paper-grade per-prediction JSON validation.
  - `test_report_rerender.py` — `eval.report` re-render reproducibility
    (`integration + slow`).

## Running

```bash
# Unit tests (default)
python3 -m pytest -m unit -q

# Integration tests
python3 -m pytest -m integration -q
```

## Run modes

Marker lanes, per the integration-test coverage uplift plan
(`research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md`):

```bash
pytest -m "unit"                            # per-PR, fast, hermetic
pytest -m "integration and not slow"        # per-PR optional, real artifacts
pytest -m "e2e or live_llm or aura"         # nightly — live gateway / Aura / LLM
pytest -m "slow"                            # nightly — > 30s runtime
```

The `integration/` pipeline tests require `OPENROUTER_API_KEY` +
`MCP_API_KEY` in env; they skip cleanly when those are unset.

## Coverage ratio

`scripts/test_coverage_ratio.py` (repo root) reports the real-integration
vs unit ratio across all Python test lanes. Wired into
`.github/workflows/mcp-ci.yml` in `--mode warn` (report-only).

```bash
python3 scripts/test_coverage_ratio.py          # table + ratio
python3 scripts/test_coverage_ratio.py --json   # machine-readable
```

## Braintrust logging

The integration test `test_report_integrity.py` logs scenario_id and
result counts to Braintrust project `diet-os-eval` when
`BRAINTRUST_API_KEY` is set. Logging is a fail-soft no-op when:

- `BRAINTRUST_API_KEY` is unset, or
- the `braintrust` SDK is not installed, or
- any init/span call raises.

Tests never fail because of Braintrust.

Pull the key from Infisical:

- Project: `SyntropyHealth App` (id `589d1e3b-5798-48ea-97c0-2d58086a375b`)
- Path: `/BRAINTRUST_API_KEY`

Install the optional SDK with:

```bash
pip install -r ../../../requirements-test.txt   # from eval/tests/
# or, from the worktree root:
pip install -r requirements-test.txt
```

The wrapper lives at `_braintrust_logger.py` and exposes a single context
manager `bt_span(name, **inputs)` whose yielded object supports
`.log(**kwargs)` and `.end()`. See that file for usage examples.
