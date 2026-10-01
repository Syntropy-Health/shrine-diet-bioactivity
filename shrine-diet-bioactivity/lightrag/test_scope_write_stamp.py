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


class _Result:
    def __init__(self, record):
        self._record = record

    async def single(self):
        return self._record

    async def consume(self):
        return None


class _RecordingTx:
    """Records every (query, rows) a write transaction runs. Guard queries
    report ``conflicts`` (default 0); the write reports ``applied``/``seen``
    (default: every row applied). Both are settable to drive the refusal
    branches offline (QG test reviewer: the old recorder could never conflict)."""

    def __init__(self, log, conflicts=0, unapplied=0):
        self.log, self.conflicts, self.unapplied = log, conflicts, unapplied

    async def run(self, query, **params):  # noqa: ANN001
        rows = params.get("rows")
        self.log.append((query, rows))
        if "AS conflicts" in query:
            return _Result({"conflicts": self.conflicts})
        n = len(rows or [])
        return _Result({"applied": n - self.unapplied, "seen": n})


class _RecordingSession:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def execute_write(self, fn):  # noqa: ANN001
        return await fn(_RecordingTx(self.driver.log, self.driver.conflicts, self.driver.unapplied))


class _RecordingDriver:
    def __init__(self, conflicts=0, unapplied=0):
        self.log = []
        self.conflicts, self.unapplied = conflicts, unapplied

    def session(self, **_):
        return _RecordingSession(self)


def _store(**driver_kw):
    """A ScopedNeo4JStorage whose writes land in a recording driver. Since #113
    the subclass routes every write through its own guarded batch path, so the
    rows are captured at the DRIVER — what the database would actually receive."""
    store = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
    store._driver = _RecordingDriver(**driver_kw)
    store._DATABASE = "neo4j"
    store.workspace = "unified_diet_kg"
    store._get_workspace_label = lambda: "unified_diet_kg"
    return store


def _written_rows(store):
    writes = [rows for q, rows in store._driver.log if "MERGE" in q]
    assert writes, f"no MERGE was executed: {store._driver.log!r}"
    return writes[-1]


def _raises_conflict(coro) -> bool:
    from scoped_neo4j_storage import ScopeConflictError

    try:
        asyncio.run(coro)
    except ScopeConflictError:
        return True
    return False


def test_upsert_edge_stamps_default_scope():
    store = _store()
    payload = {"description": "curcumin -> PTGS2", "weight": "1.0"}
    asyncio.run(store.upsert_edge("curcumin", "PTGS2", payload))
    got = _written_rows(store)[0]["props"]
    assert got.get("scope") == WRITE_SCOPE_DEFAULT == "shared", got
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
    store = _store()
    asyncio.run(store.upsert_edge("a", "b", {"scope": ""}))
    assert _written_rows(store)[0]["props"].get("scope") == "shared"


def test_context_write_scope_stamps_both_single_row_entry_points():
    """The single-row methods (operate.py semantic ingest) must go through the
    same stamped, conditional batch write as ainsert_custom_kg."""
    from scope_context import reset_write_scope, set_write_scope

    store = _store()
    token = set_write_scope("tenant:clinic-a")
    try:
        asyncio.run(store.upsert_node("n1", {"entity_id": "n1"}))
        asyncio.run(store.upsert_edge("n1", "n2", {"description": "d"}))
    finally:
        reset_write_scope(token)
    merges = [(q, rows) for q, rows in store._driver.log if "MERGE" in q]
    assert len(merges) == 2
    assert all("ON CREATE SET" in q and "applied" in q for q, _ in merges), "write must be the conditional MERGE"
    assert all(r["props"]["scope"] == "tenant:clinic-a" for _, rows in merges for r in rows)
    edge_idx = next(i for i, (q, _) in enumerate(store._driver.log) if "-[r:DIRECTED]-" in q)
    assert "AS conflicts" in store._driver.log[edge_idx - 1][0], "edge endpoint guard must run before the edge MERGE"


def test_endpoint_guard_conflict_refuses_before_any_merge():
    store = _store(conflicts=1)
    assert _raises_conflict(store.upsert_edges_batch([("a", "b", {})]))
    assert not [q for q, _ in store._driver.log if "MERGE" in q], "nothing may be merged after a guard refusal"


def test_unapplied_rows_in_the_conditional_write_raise():
    """The in-write check: a row whose stored scope differs is not applied, and
    the transaction must raise (rolling back) rather than report success."""
    assert _raises_conflict(_store(unapplied=1).upsert_nodes_batch([("x", {"entity_id": "x"})]))
    assert _raises_conflict(_store(unapplied=1).upsert_edges_batch([("a", "b", {})]))


def test_mixed_scopes_for_one_row_inside_a_batch_are_refused_before_the_database():
    store = _store()
    assert _raises_conflict(store.upsert_nodes_batch([
        ("D", {"entity_id": "D", "scope": "tenant:clinic-a"}), ("D", {"entity_id": "D", "scope": "shared"})]))
    assert _raises_conflict(store.upsert_edges_batch([
        ("A", "B", {"scope": "tenant:clinic-a"}), ("B", "A", {"scope": "shared"})]))
    assert store._driver.log == [], "the batch must be refused before any query"
    # same id, SAME scope twice is fine (last-wins on properties, as upstream)
    asyncio.run(_store().upsert_nodes_batch([("D", {"entity_id": "D"}), ("D", {"entity_id": "D"})]))


def test_conflict_message_carries_counts_never_identifiers():
    from scoped_neo4j_storage import ScopeConflictError

    err = ScopeConflictError("node", 2)
    assert str(err) == "refusing write: 2 node row(s) conflict with an existing row in another scope"
    assert (err.kind, err.count) == ("node", 2)


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
