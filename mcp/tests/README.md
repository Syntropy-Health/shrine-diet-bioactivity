# MCP gateway tests

## Layout

- `unit/` — pure unit tests, no I/O. Run by default.
- `e2e/` — gateway roundtrip tests against the live MCP gateway. Deselected
  by default via `addopts = ["-m", "not e2e"]` in `pyproject.toml`.

## Running

```bash
# Unit tests (default)
python3 -m pytest -m unit -q

# E2E tests against the live gateway
KG_MCP_E2E_URL=https://kg-mcp-test.up.railway.app \
KG_MCP_API_KEY=<bearer-token> \
python3 -m pytest -m e2e -q
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
