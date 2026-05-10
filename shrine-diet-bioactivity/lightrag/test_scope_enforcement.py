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
