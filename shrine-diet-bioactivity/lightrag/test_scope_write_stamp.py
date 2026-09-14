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


def _capture_parent():
    """Patch the parent Neo4JStorage writes with async stubs that record the
    data dict they receive. Returns (captured, restore)."""
    captured: dict[str, object] = {}

    async def _node_stub(self, node_id, node_data):  # noqa: ANN001
        captured["node_id"] = node_id
        captured["node_data"] = node_data

    async def _edge_stub(self, src, tgt, edge_data):  # noqa: ANN001
        captured["src"] = src
        captured["tgt"] = tgt
        captured["edge_data"] = edge_data

    orig_node = Neo4JStorage.upsert_node
    orig_edge = Neo4JStorage.upsert_edge
    Neo4JStorage.upsert_node = _node_stub  # type: ignore[assignment]
    Neo4JStorage.upsert_edge = _edge_stub  # type: ignore[assignment]

    def restore():
        Neo4JStorage.upsert_node = orig_node  # type: ignore[assignment]
        Neo4JStorage.upsert_edge = orig_edge  # type: ignore[assignment]

    return captured, restore


def test_upsert_edge_stamps_default_scope():
    captured, restore = _capture_parent()
    try:
        store = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
        payload = {"description": "curcumin -> PTGS2", "weight": "1.0"}
        asyncio.run(store.upsert_edge("curcumin", "PTGS2", payload))
        got = captured["edge_data"]
        assert got.get("scope") == WRITE_SCOPE_DEFAULT == "shared", got
        # caller's dict must not be mutated
        assert "scope" not in payload, "override mutated the caller's dict"
    finally:
        restore()


def test_upsert_edge_respects_explicit_tenant_scope():
    captured, restore = _capture_parent()
    try:
        store = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
        asyncio.run(store.upsert_edge("a", "b", {"scope": "tenant:clinic-a"}))
        assert captured["edge_data"].get("scope") == "tenant:clinic-a", captured["edge_data"]
    finally:
        restore()


def test_upsert_node_stamps_default_scope():
    captured, restore = _capture_parent()
    try:
        store = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
        asyncio.run(store.upsert_node("curcumin", {"entity_type": "Compound"}))
        assert captured["node_data"].get("scope") == "shared", captured["node_data"]
    finally:
        restore()


def test_empty_scope_string_falls_back_to_shared():
    # a falsy scope on the payload (e.g. "") must not leave the row unscoped
    captured, restore = _capture_parent()
    try:
        store = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
        asyncio.run(store.upsert_edge("a", "b", {"scope": ""}))
        assert captured["edge_data"].get("scope") == "shared", captured["edge_data"]
    finally:
        restore()


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
