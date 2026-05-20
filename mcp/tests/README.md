# MCP gateway tests

## Layout

- `unit/` — pure unit tests, no I/O. Run by default.
- `e2e/` — gateway tests against the live MCP gateway. Deselected by
  default via `addopts = ["-m", "not e2e"]` in `pyproject.toml`.
  - `test_live_endpoints.py` — auth + handshake.
  - `test_tool_roundtrips.py` — one roundtrip per tool (Phase 2).
  - `test_kg_coverage_probes.py` — entity-resolution probes against the
    indexed Aura KG (Phase 5): Curcumin/T2D/Mediterranean-diet resolution,
    bilingual aliasing, HDI-Safe-50 panel coverage, herb edge density.

## Running

```bash
# Unit tests (default)
python3 -m pytest -m unit -q

# E2E tests against the live gateway
KG_MCP_E2E_URL=https://kg-mcp-test.up.railway.app \
KG_MCP_API_KEY=<bearer-token> \
python3 -m pytest -m e2e -q
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

## Coverage ratio

`scripts/test_coverage_ratio.py` (repo root) reports the real-integration
vs unit ratio across all Python test lanes. The `test-coverage-ratio` job
in `.github/workflows/mcp-ci.yml` runs it in `--mode warn` (report-only;
never fails the build).

```bash
python3 scripts/test_coverage_ratio.py          # table + ratio
python3 scripts/test_coverage_ratio.py --json   # machine-readable
```

## Braintrust logging

Integration tests in `tests/e2e/test_tool_roundtrips.py` log inputs and
outputs to Braintrust project `diet-os-eval` when `BRAINTRUST_API_KEY` is
set. Logging is a fail-soft no-op when:

- `BRAINTRUST_API_KEY` is unset, or
- the `braintrust` SDK is not installed, or
- any init/span call raises.

Tests never fail because of Braintrust.

Pull the key from Infisical:

- Project: `SyntropyHealth App` (id `589d1e3b-5798-48ea-97c0-2d58086a375b`)
- Path: `/BRAINTRUST_API_KEY`

Install the optional SDK with:

```bash
pip install -e '.[test]'
```

The wrapper lives at `tests/e2e/_braintrust_logger.py` and exposes a single
context manager `bt_span(name, **inputs)` whose yielded object supports
`.log(**kwargs)` and `.end()`. See that file for usage examples.

## Markers

| Marker | Meaning |
|---|---|
| `unit` | Pure unit, no I/O, no network |
| `integration` | Real components (file system, multi-layer roundtrip) |
| `e2e` | Real network call to staged services |
| `aura` | Hits live Neo4j Aura |
| `slow` | Runtime > 30s |
