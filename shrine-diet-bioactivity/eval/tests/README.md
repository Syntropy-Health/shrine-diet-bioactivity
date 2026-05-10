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

## Running

```bash
# Unit tests (default)
python3 -m pytest -m unit -q

# Integration tests
python3 -m pytest -m integration -q
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
