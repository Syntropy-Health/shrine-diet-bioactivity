"""Write-time scope-stamp tests for ScopedNeo4JStorage (shrine-diet #103).

Two arms, per the durability directive:

* **RED arm** — a node/edge ingested through the REAL write path
  (``ScopedNeo4JStorage.upsert_node`` / ``upsert_edge``) must arrive at the
  parent Neo4JStorage carrying a ``scope``. Before the write-stamp override
  this failed: LightRAG's semantic ingest wrote ``DIRECTED`` edges with no
  scope, which the boot preflight then refused (35,092 unscoped edges,
  container crash-loop). Removing the override in ``scoped_neo4j_storage.py``
  turns these red again.
* **Preflight control** — ``scoped_server._preflight_scope_check`` must STILL
  raise when an unscoped row exists, so nobody "fixes" a future regression by
  loosening the fail-closed preflight instead of the writer.

RUN: this imports ``lightrag.kg`` / ``lightrag.base``, which the local
``lightrag/`` dir shadows under *pytest collection* (same reason
``test_scoped_neo4j_vector_storage.py`` is harness-run). So run it as a direct
script from this directory:

    /tmp/lrenv/bin/python test_scope_write_stamp.py     # or: make lightrag-test-scope-write

Exits non-zero on any failure. Under pytest it skips at module level rather
than hard-erroring on the shadow.
"""
from __future__ import annotations

import asyncio
import os
import sys

# --- shadow-safe import: prime the INSTALLED lightrag before the local modules.
# Running as a plain script from this dir, `import lightrag` resolves to the
# installed lightrag-hku (site-packages precedes cwd for the package name),
# while the local top-level modules (scope_context, scoped_neo4j_storage) import
# from cwd. Under pytest the parent dir shadows `lightrag`, so we skip cleanly.
try:
    import lightrag.kg.neo4j_impl  # noqa: F401  (prime installed package)
    from lightrag.kg.neo4j_impl import Neo4JStorage
    import scoped_neo4j_storage
    from scoped_neo4j_storage import ScopedNeo4JStorage, WRITE_SCOPE_DEFAULT
    _IMPORT_OK = True
    _IMPORT_ERR = ""
except Exception as e:  # pragma: no cover - exercised only under the pytest shadow
    _IMPORT_OK = False
    _IMPORT_ERR = repr(e)

if "pytest" in sys.modules and not _IMPORT_OK:  # graceful skip, never a collection error
    import pytest  # type: ignore
    pytest.skip(f"lightrag dir-shadow under pytest; run via direct harness ({_IMPORT_ERR})",
                allow_module_level=True)


class _RecordingTx:
    """Records every (query, rows) a write transaction runs; returns no rows,
    so the #113 conflict guard always passes and the write proceeds."""

    def __init__(self, log):
        self.log = log

    async def run(self, query, **params):  # noqa: ANN001
        self.log.append((query, params.get("rows")))

        class _R:
            def __aiter__(self):
                async def gen():
                    if False:
                        yield None
                return gen()

            async def consume(self):
                return None

        return _R()


class _RecordingSession:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def execute_write(self, fn):  # noqa: ANN001
        return await fn(_RecordingTx(self.log))


class _RecordingDriver:
    def __init__(self):
        self.log = []

    def session(self, **_):
        return _RecordingSession(self.log)


def _store():
    """A ScopedNeo4JStorage whose writes land in a recording driver. Since #113
    the subclass no longer delegates to the parent's single-row writes (they
    route through its own guarded batch path), so the rows are captured at the
    DRIVER — what the database would actually receive."""
    store = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
    store._driver = _RecordingDriver()
    store._DATABASE = "neo4j"
    store.workspace = "unified_diet_kg"
    store._get_workspace_label = lambda: "unified_diet_kg"
    return store


def _written_rows(store):
    """Rows passed to the MERGE (write) statement — the guard runs first."""
    writes = [rows for q, rows in store._driver.log if "MERGE" in q]
    assert writes, f"no MERGE was executed: {store._driver.log!r}"
    return writes[-1]


def test_upsert_edge_stamps_default_scope():
    store = _store()
    payload = {"description": "curcumin -> PTGS2", "weight": "1.0"}
    asyncio.run(store.upsert_edge("curcumin", "PTGS2", payload))
    got = _written_rows(store)[0]["props"]
    assert got.get("scope") == WRITE_SCOPE_DEFAULT == "shared", got
    # caller's dict must not be mutated
    assert "scope" not in payload, "override mutated the caller's dict"


def test_upsert_edge_respects_explicit_tenant_scope():
    store = _store()
    asyncio.run(store.upsert_edge("a", "b", {"scope": "tenant:clinic-a"}))
    assert _written_rows(store)[0]["props"].get("scope") == "tenant:clinic-a"


def test_upsert_node_stamps_default_scope():
    store = _store()
    asyncio.run(store.upsert_node("curcumin", {"entity_id": "curcumin", "entity_type": "Compound"}))
    assert _written_rows(store)[0]["props"].get("scope") == "shared"


def test_empty_scope_string_falls_back_to_shared():
    # a falsy scope on the payload (e.g. "") must not leave the row unscoped
    store = _store()
    asyncio.run(store.upsert_edge("a", "b", {"scope": ""}))
    assert _written_rows(store)[0]["props"].get("scope") == "shared"


def test_batch_writes_are_stamped_and_guarded_before_the_merge():
    """#113: the BATCH entry points (what ainsert_custom_kg calls) stamp scope
    and run the conflict guard in the same transaction, BEFORE the MERGE."""
    from scope_context import reset_write_scope, set_write_scope

    store = _store()
    token = set_write_scope("tenant:clinic-a")
    try:
        asyncio.run(store.upsert_nodes_batch([("n1", {"entity_id": "n1"}), ("n2", {"entity_id": "n2"})]))
        asyncio.run(store.upsert_edges_batch([("n1", "n2", {"description": "d"})]))
    finally:
        reset_write_scope(token)
    queries = [q for q, _ in store._driver.log]
    assert len(queries) == 4, queries                         # guard + write, twice
    assert "<> row.props.scope" in queries[0] and "MERGE" not in queries[0]
    assert "MERGE" in queries[1] and "MERGE" in queries[3]
    for _q, rows in store._driver.log:
        assert all(r["props"]["scope"] == "tenant:clinic-a" for r in rows)


def test_invalid_write_scope_is_refused_before_any_query():
    store = _store()
    try:
        asyncio.run(store.upsert_node("x", {"entity_id": "x", "scope": "tenant:NOT VALID"}))
    except ValueError:
        pass
    else:
        raise AssertionError("an invalid scope string must be refused")
    assert store._driver.log == [], "nothing may reach the driver"


def test_preflight_still_refuses_unscoped_rows():
    """Preflight CONTROL: the fail-closed check must keep raising on unscoped
    rows (so the write-stamp fix is not 'completed' by loosening the preflight)."""
    import scoped_server
    import bootstrap_scope
    import neo4j

    class _FakeDriver:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def close(self):
            pass

    orig_driver = neo4j.GraphDatabase.driver
    orig_count = bootstrap_scope.count_untagged
    os.environ.setdefault("NEO4J_URI", "bolt://x")
    os.environ.setdefault("NEO4J_USERNAME", "u")
    os.environ.setdefault("NEO4J_PASSWORD", "p")
    neo4j.GraphDatabase.driver = lambda *a, **k: _FakeDriver()  # type: ignore[assignment]
    try:
        # unscoped rows present -> MUST raise
        bootstrap_scope.count_untagged = lambda drv, label: (0, 5)  # type: ignore[assignment]
        raised = False
        try:
            scoped_server._preflight_scope_check()
        except RuntimeError as e:
            raised = "scope IS NULL" in str(e)
        assert raised, "preflight did NOT refuse unscoped rows — fail-closed control lost"

        # zero unscoped -> MUST pass (no raise)
        bootstrap_scope.count_untagged = lambda drv, label: (0, 0)  # type: ignore[assignment]
        scoped_server._preflight_scope_check()  # should not raise
    finally:
        neo4j.GraphDatabase.driver = orig_driver  # type: ignore[assignment]
        bootstrap_scope.count_untagged = orig_count  # type: ignore[assignment]


def _main() -> int:
    if not _IMPORT_OK:
        print(f"FAIL: import error (run from the lightrag/ dir with lrenv): {_IMPORT_ERR}")
        return 1
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
