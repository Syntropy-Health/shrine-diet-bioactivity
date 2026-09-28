"""
Scope-enforcement tests.

Two layers:

* **Unit** (always run) — Cypher-generation + ContextVar propagation
  against a fake async Neo4j driver. No network.
* **Integration** (``LIGHTRAG_RUN_INTEGRATION=true`` required) — real
  Neo4j; verifies that scope_filter actually hides cross-tenant data.

The integration path runs the same logic as ``canary_smoke_test.py``
but from within pytest so CI can assert exit status + artifact shape.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from scope_context import (
    DEFAULT_SCOPE,
    get_scope_filter,
    reset_scope_filter,
    set_scope_filter,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Fake async Neo4j driver — records every (cypher, params) tuple executed.
# ---------------------------------------------------------------------------


@dataclass
class _FakeRecord:
    data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


class _FakeAsyncResult:
    def __init__(self, records: list[_FakeRecord] | None = None) -> None:
        self._records = records or []

    async def fetch(self, n: int) -> list[_FakeRecord]:
        return self._records[:n]

    async def single(self) -> _FakeRecord | None:
        return self._records[0] if self._records else None

    async def consume(self) -> None:
        return None

    def __aiter__(self):
        async def gen():
            for r in self._records:
                yield r

        return gen()


class _FakeAsyncSession:
    def __init__(self, log: list[tuple[str, dict[str, Any]]]) -> None:
        self._log = log

    async def __aenter__(self) -> "_FakeAsyncSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def run(self, query: str, **params: Any) -> _FakeAsyncResult:
        self._log.append((query, params))
        return _FakeAsyncResult([])


class _FakeAsyncDriver:
    def __init__(self) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []

    def session(self, **_: Any) -> _FakeAsyncSession:
        return _FakeAsyncSession(self.log)


# ---------------------------------------------------------------------------
# Unit tests — verify every overridden method injects scope_filter.
# ---------------------------------------------------------------------------


def _make_scoped_storage() -> Any:
    """Build a ScopedNeo4JStorage without touching the real base __init__.

    We bypass ``Neo4JStorage.__init__`` (which expects real config) by
    constructing via ``__new__`` and hand-setting the attributes the
    overridden methods read.
    """
    from scoped_neo4j_storage import ScopedNeo4JStorage

    storage = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
    storage._driver = _FakeAsyncDriver()
    storage._DATABASE = "neo4j"
    storage.workspace = "unified_diet_kg"
    storage._workspace_label_cache = "unified_diet_kg"
    return storage


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.unit
def test_get_node_injects_scope_filter_with_default() -> None:
    storage = _make_scoped_storage()
    # Ensure the class can locate _get_workspace_label — patch it.
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_node("some-entity"))

    driver = storage._driver
    assert driver.log, "no Cypher was executed"
    query, params = driver.log[0]
    assert "WHERE n.scope IN $scope_filter" in query
    assert params["scope_filter"] == list(DEFAULT_SCOPE)


@pytest.mark.unit
def test_get_node_uses_contextvar_override() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        _run(storage.get_node("entity-x"))
    finally:
        reset_scope_filter(token)

    _query, params = storage._driver.log[-1]
    assert params["scope_filter"] == ["shared", "tenant:clinic-a"]


@pytest.mark.unit
def test_get_edge_filters_both_endpoints_and_relationship() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_edge("a", "b"))

    query, _ = storage._driver.log[0]
    assert "start.scope IN $scope_filter" in query
    assert "end.scope IN $scope_filter" in query
    assert "r.scope IN $scope_filter" in query


@pytest.mark.unit
def test_node_degree_filters_connected_nodes_and_relationships() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.node_degree("entity-x"))

    query, _ = storage._driver.log[0]
    assert "n.scope IN $scope_filter" in query
    assert "r.scope IN $scope_filter" in query
    assert "m.scope IN $scope_filter" in query


@pytest.mark.unit
def test_get_nodes_batch_injects_scope_filter() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_nodes_batch(["a", "b"]))

    query, params = storage._driver.log[0]
    assert "UNWIND $node_ids" in query
    assert "WHERE n.scope IN $scope_filter" in query
    assert params["scope_filter"] == list(DEFAULT_SCOPE)
    assert params["node_ids"] == ["a", "b"]


@pytest.mark.unit
def test_get_node_edges_filters_all_three() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_node_edges("entity-x"))

    query, _ = storage._driver.log[0]
    for predicate in (
        "n.scope IN $scope_filter",
        "m.scope IN $scope_filter",
        "r.scope IN $scope_filter",
    ):
        assert predicate in query


@pytest.mark.unit
def test_get_all_labels_applies_scope_filter() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_all_labels())

    query, _ = storage._driver.log[0]
    assert "n.scope IN $scope_filter" in query


@pytest.mark.unit
def test_context_var_does_not_leak_across_calls() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        _run(storage.get_node("a"))
    finally:
        reset_scope_filter(token)

    _run(storage.get_node("b"))

    _, first_params = storage._driver.log[0]
    _, second_params = storage._driver.log[1]
    assert first_params["scope_filter"] == ["shared", "tenant:clinic-a"]
    assert second_params["scope_filter"] == list(DEFAULT_SCOPE)


# ---------------------------------------------------------------------------
# Integration — real Neo4j, real scoped_server (gated).
# ---------------------------------------------------------------------------

_RUN_INTEGRATION = os.environ.get("LIGHTRAG_RUN_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.mark.integration
@pytest.mark.skipif(
    not _RUN_INTEGRATION,
    reason="requires LIGHTRAG_RUN_INTEGRATION=true + live Neo4j + scoped_server",
)
def test_cross_tenant_canary_isolation(tmp_path) -> None:  # noqa: ARG001
    """End-to-end canary: insert as tenant:canary-a, query as tenant:canary-b,
    assert the sentinel id does not appear in the response text.

    Mirrors canary_smoke_test.py with the same cleanup guarantee.
    """
    import canary_smoke_test as canary

    config = os.environ.get("SHRINE_CONFIG", "local")
    canary._load_config(config)
    workspace_label = canary._safe_label(
        os.environ.get("WORKSPACE", "unified_diet_kg")
    )
    sentinel_id = f"canary-sentinel-{uuid.uuid4().hex[:8]}"
    server_url = os.environ.get("LIGHTRAG_API_URL", "http://localhost:9621")

    canary._insert_sentinel(workspace_label, sentinel_id)
    try:
        response_b = canary._query_as_tenant(server_url, "canary-b", sentinel_id)
        assert sentinel_id not in response_b, (
            f"sentinel leaked across tenants: {response_b[:400]}"
        )
    finally:
        canary._delete_sentinel(workspace_label, sentinel_id)


# ---------------------------------------------------------------------------
# get_knowledge_graph override (shrine-diet #6): seed resolution within scope
# + scope-filtered subgraph. Upstream LightRAG 1.5.0 matches the start node
# on EXACT entity_id and its APOC BFS is workspace-scoped only — so without
# this override /graphs both misses 'curcumin' (case) AND can return tenant
# nodes/edges under scope_filter=shared.
# ---------------------------------------------------------------------------


class _ResolvingSession(_FakeAsyncSession):
    """Answers the seed-resolution query with a fixed entity_id (or nothing)."""

    def __init__(self, log, resolved: str | None) -> None:
        super().__init__(log)
        self._resolved = resolved

    async def run(self, query: str, **params: Any) -> _FakeAsyncResult:
        self._log.append((query, params))
        if self._resolved is None:
            return _FakeAsyncResult([])
        return _FakeAsyncResult([_FakeRecord({"entity_id": self._resolved})])


class _ResolvingDriver(_FakeAsyncDriver):
    def __init__(self, resolved: str | None) -> None:
        super().__init__()
        self._resolved = resolved

    def session(self, **_: Any) -> _ResolvingSession:
        return _ResolvingSession(self.log, self._resolved)


def _mixed_scope_graph():
    """1 shared seed, 2 shared, 3 tenant, 4 unscoped; edges of every kind."""
    from lightrag.types import KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode

    def n(nid: str, scope: str | None) -> KnowledgeGraphNode:
        props: dict[str, Any] = {"entity_id": f"E{nid}"}
        if scope is not None:
            props["scope"] = scope
        return KnowledgeGraphNode(id=nid, labels=[f"E{nid}"], properties=props)

    def e(eid: str, s: str, t: str, scope: str | None) -> KnowledgeGraphEdge:
        props: dict[str, Any] = {}
        if scope is not None:
            props["scope"] = scope
        return KnowledgeGraphEdge(id=eid, type="DIRECTED", source=s, target=t, properties=props)

    return KnowledgeGraph(
        nodes=[n("1", "shared"), n("2", "shared"), n("3", "tenant:clinic-a"), n("4", None)],
        edges=[
            e("a", "1", "2", "shared"),            # in scope both ends, in-scope edge -> KEEP
            e("b", "1", "3", "shared"),            # tenant endpoint under shared -> DROP
            e("c", "1", "4", "shared"),            # unscoped endpoint -> DROP (fail-closed)
            e("d", "1", "2", "tenant:clinic-a"),   # in-scope ends, tenant EDGE -> DROP under shared
            e("f", "1", "2", None),                # unscoped edge -> DROP (fail-closed)
        ],
        is_truncated=True,
    )


def _patch_parent_get_kg(monkeypatch, calls: list[dict[str, Any]], graph):
    from lightrag.kg.neo4j_impl import Neo4JStorage

    async def _fake(self, node_label, max_depth=3, max_nodes=1000):
        calls.append({"node_label": node_label, "max_depth": max_depth, "max_nodes": max_nodes})
        return graph

    monkeypatch.setattr(Neo4JStorage, "get_knowledge_graph", _fake)


@pytest.mark.unit
def test_get_knowledge_graph_resolves_seed_in_scope_then_filters(monkeypatch) -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"
    storage._driver = _ResolvingDriver("CURCUMIN")
    calls: list[dict[str, Any]] = []
    _patch_parent_get_kg(monkeypatch, calls, _mixed_scope_graph())

    out = _run(storage.get_knowledge_graph("curcumin", max_depth=1, max_nodes=20))

    # (1) the resolve query is scoped and case-insensitive
    query, params = storage._driver.log[0]
    assert "$scope_filter" in query and "toLower" in query
    assert params["scope_filter"] == list(DEFAULT_SCOPE)
    assert params["seed"] == "curcumin"
    # (2) upstream is called with the CANONICAL id, limits forwarded
    assert calls == [{"node_label": "CURCUMIN", "max_depth": 1, "max_nodes": 20}]
    # (3) under the default scope only shared nodes + one fully-shared edge survive
    assert sorted(n.id for n in out.nodes) == ["1", "2"]
    assert [e.id for e in out.edges] == ["a"]
    assert out.is_truncated is True  # upstream flag preserved


@pytest.mark.unit
def test_get_knowledge_graph_scope_filter_is_differential(monkeypatch) -> None:
    """Widening the scope must CHANGE the answer — proves the filter reads the
    variable rather than always returning the same subset."""
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"
    storage._driver = _ResolvingDriver("CURCUMIN")
    _patch_parent_get_kg(monkeypatch, [], _mixed_scope_graph())

    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        out = _run(storage.get_knowledge_graph("curcumin"))
    finally:
        reset_scope_filter(token)

    assert sorted(n.id for n in out.nodes) == ["1", "2", "3"]   # node 4 (unscoped) still out
    assert sorted(e.id for e in out.edges) == ["a", "b", "d"]  # c (unscoped end) + f (unscoped edge) out


@pytest.mark.unit
def test_get_knowledge_graph_unresolved_seed_returns_empty_without_delegating(monkeypatch) -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"
    storage._driver = _ResolvingDriver(None)
    calls: list[dict[str, Any]] = []
    _patch_parent_get_kg(monkeypatch, calls, _mixed_scope_graph())

    out = _run(storage.get_knowledge_graph("no-such-thing"))

    assert calls == [], "upstream BFS must not run for an unresolvable seed"
    assert out.nodes == [] and out.edges == [] and out.is_truncated is False


@pytest.mark.unit
def test_get_knowledge_graph_wildcard_skips_resolution_but_still_filters(monkeypatch) -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"
    storage._driver = _ResolvingDriver("SHOULD-NOT-BE-USED")
    calls: list[dict[str, Any]] = []
    _patch_parent_get_kg(monkeypatch, calls, _mixed_scope_graph())

    out = _run(storage.get_knowledge_graph("*"))

    assert storage._driver.log == [], "no resolve query for the wildcard"
    assert calls[0]["node_label"] == "*"
    assert sorted(n.id for n in out.nodes) == ["1", "2"]
