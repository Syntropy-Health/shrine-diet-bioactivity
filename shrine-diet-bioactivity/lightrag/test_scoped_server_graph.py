"""
Unit tests for the Phase D1a scoped_server pass-throughs:

- ``GET /graphs`` — LightRAG subgraph by label, scope-filtered
- ``GET /graph/label/popular`` — popular labels in scope
- ``POST /documents/custom_kg`` — tenant-scoped custom KG ingest

The tests run against FastAPI's TestClient with a fake LightRAG that
records every method call plus the ``ContextVar`` scope value observed
at call time. Scope-filter injection at the Cypher layer is covered
separately by ``test_scope_enforcement.py``; these tests verify the
HTTP surface, scope validation, audit emission, and scope-forcing on
writes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scope_context import get_scope_filter


# ---------------------------------------------------------------------------
# Fake LightRAG — records calls + scope visible at each call
# ---------------------------------------------------------------------------


class _FakePopularLabels:
    def __init__(self, rag: "_FakeRag") -> None:
        self._rag = rag

    async def get_popular_labels(self, limit: int) -> list[str]:
        self._rag._scope_seen.append(get_scope_filter())
        self._rag.calls.append(("get_popular_labels", (limit,), {}))
        return ["Herb", "Compound", "Food"][:limit]


class _FakeRag:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._scope_seen: list[list[str]] = []
        self.chunk_entity_relation_graph = _FakePopularLabels(self)

    async def aquery(self, query: str, param: Any = None) -> str:
        self._scope_seen.append(get_scope_filter())
        self.calls.append(("aquery", (query,), {"param": param}))
        return f"fake response for: {query}"

    async def get_knowledge_graph(
        self,
        node_label: str,
        max_depth: int = 3,
        max_nodes: int = 1000,
    ) -> dict[str, Any]:
        self._scope_seen.append(get_scope_filter())
        self.calls.append(
            (
                "get_knowledge_graph",
                (node_label,),
                {"max_depth": max_depth, "max_nodes": max_nodes},
            )
        )
        return {"nodes": [], "edges": []}

    async def ainsert_custom_kg(self, custom_kg: dict[str, Any]) -> None:
        self._scope_seen.append(get_scope_filter())
        self.calls.append(("ainsert_custom_kg", (custom_kg,), {}))

    async def finalize_storages(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """TestClient with the real scoped_server app + fake rag + isolated audit DB."""
    import scoped_server as ss
    from audit_log import AuditLog

    fake_rag = _FakeRag()

    async def _fake_build() -> _FakeRag:
        return fake_rag

    monkeypatch.setattr(ss, "_preflight_scope_check", lambda: None)
    monkeypatch.setattr(ss, "_build_scoped_rag", _fake_build)
    monkeypatch.setattr(ss, "_audit", AuditLog(db_path=tmp_path / "audit.db"))

    with TestClient(ss.app) as c:
        c._fake_rag = fake_rag  # type: ignore[attr-defined]
        c._audit_db = tmp_path / "audit.db"  # type: ignore[attr-defined]
        yield c


def _audit_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM mcp_audit ORDER BY id ASC")
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# GET /graphs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_graphs_requires_scope_filter(client: TestClient) -> None:
    resp = client.get("/graphs", params={"label": "Ashwagandha"})
    assert resp.status_code == 400
    assert "scope" in resp.text.lower()


@pytest.mark.unit
def test_graphs_sets_contextvar_scope(client: TestClient) -> None:
    resp = client.get(
        "/graphs",
        params={
            "label": "Ashwagandha",
            "max_depth": 1,
            "max_nodes": 50,
            "scope_filter": "shared,tenant:clinic-a",
        },
    )
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    assert fake._scope_seen[-1] == ["shared", "tenant:clinic-a"]


@pytest.mark.unit
def test_graphs_forwards_label_and_limits(client: TestClient) -> None:
    resp = client.get(
        "/graphs",
        params={
            "label": "Turmeric",
            "max_depth": 2,
            "max_nodes": 100,
            "scope_filter": "shared",
        },
    )
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    (name, args, kwargs) = fake.calls[-1]
    assert name == "get_knowledge_graph"
    assert args == ("Turmeric",)
    assert kwargs == {"max_depth": 2, "max_nodes": 100}


@pytest.mark.unit
def test_graphs_rejects_malformed_scope(client: TestClient) -> None:
    resp = client.get(
        "/graphs",
        params={"label": "X", "scope_filter": "tenant:INVALID_CAPS"},
    )
    assert resp.status_code == 400


@pytest.mark.unit
def test_graphs_emits_audit_row(client: TestClient) -> None:
    resp = client.get(
        "/graphs",
        params={"label": "Curcumin", "scope_filter": "shared,tenant:clinic-a"},
    )
    assert resp.status_code == 200, resp.text
    rows = _audit_rows(client._audit_db)  # type: ignore[attr-defined]
    assert len(rows) == 1
    row = rows[0]
    assert row["tenant_id"] == "clinic-a"
    assert row["tool"] == "scoped_server./graphs"
    assert row["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /graph/label/popular
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_popular_labels_requires_scope_filter(client: TestClient) -> None:
    resp = client.get("/graph/label/popular")
    assert resp.status_code == 400


@pytest.mark.unit
def test_popular_labels_forwards_limit_and_scope(client: TestClient) -> None:
    resp = client.get(
        "/graph/label/popular",
        params={"limit": 50, "scope_filter": "shared"},
    )
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    assert fake.calls[-1] == ("get_popular_labels", (50,), {})
    assert fake._scope_seen[-1] == ["shared"]


@pytest.mark.unit
def test_popular_labels_emits_audit(client: TestClient) -> None:
    resp = client.get(
        "/graph/label/popular",
        params={"limit": 10, "scope_filter": "shared,tenant:canary-a"},
    )
    assert resp.status_code == 200, resp.text
    rows = _audit_rows(client._audit_db)  # type: ignore[attr-defined]
    assert len(rows) == 1
    assert rows[0]["tool"] == "scoped_server./graph/label/popular"
    assert rows[0]["tenant_id"] == "canary-a"


# ---------------------------------------------------------------------------
# POST /documents/custom_kg
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_custom_kg_requires_tenant_scope(client: TestClient) -> None:
    """A 'shared'-only scope_filter is a shared-write, not allowed via MCP.

    Shared data is populated by the offline ETL (``ingest_unified.py``).
    """
    resp = client.post(
        "/documents/custom_kg",
        json={
            "scope_filter": ["shared"],
            "custom_kg": {
                "entities": [
                    {
                        "entity_name": "X",
                        "entity_type": "Herb",
                        "description": "",
                    }
                ],
                "relationships": [],
            },
        },
    )
    assert resp.status_code == 400
    assert "tenant" in resp.text.lower()


@pytest.mark.unit
def test_custom_kg_forces_scope_on_every_entity(client: TestClient) -> None:
    resp = client.post(
        "/documents/custom_kg",
        json={
            "scope_filter": ["shared", "tenant:clinic-a"],
            "custom_kg": {
                "entities": [
                    {
                        "entity_name": "LocalHerb",
                        "entity_type": "Herb",
                        "description": "clinic-a supplier notes",
                    }
                ],
                "relationships": [
                    {
                        "src_id": "LocalHerb",
                        "tgt_id": "Inflammation",
                        "description": "reduces",
                        "keywords": "anti-inflammatory",
                        "weight": 1.0,
                    }
                ],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    (name, args, _kwargs) = fake.calls[-1]
    assert name == "ainsert_custom_kg"
    (payload,) = args
    assert all(e["scope"] == "tenant:clinic-a" for e in payload["entities"])
    assert all(r["scope"] == "tenant:clinic-a" for r in payload["relationships"])


@pytest.mark.unit
def test_custom_kg_overrides_client_supplied_shared_scope(client: TestClient) -> None:
    """Even if the client puts scope='shared' on an entity, the server rewrites
    it to ``tenant:<id>`` — a tenant context can never inject into shared.
    """
    resp = client.post(
        "/documents/custom_kg",
        json={
            "scope_filter": ["shared", "tenant:clinic-a"],
            "custom_kg": {
                "entities": [
                    {
                        "entity_name": "Sneaky",
                        "entity_type": "Herb",
                        "description": "",
                        "scope": "shared",
                    }
                ],
                "relationships": [],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    (_name, (payload,), _kwargs) = fake.calls[-1]
    assert payload["entities"][0]["scope"] == "tenant:clinic-a"


@pytest.mark.unit
def test_custom_kg_emits_audit_row(client: TestClient) -> None:
    resp = client.post(
        "/documents/custom_kg",
        json={
            "scope_filter": ["shared", "tenant:clinic-a"],
            "custom_kg": {
                "entities": [
                    {"entity_name": "X", "entity_type": "Herb", "description": ""}
                ],
                "relationships": [],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    rows = _audit_rows(client._audit_db)  # type: ignore[attr-defined]
    assert len(rows) == 1
    assert rows[0]["tool"] == "scoped_server./documents/custom_kg"
    assert rows[0]["tenant_id"] == "clinic-a"
    assert rows[0]["status"] == "ok"


@pytest.mark.unit
def test_custom_kg_validates_payload_shape(client: TestClient) -> None:
    resp = client.post(
        "/documents/custom_kg",
        json={
            "scope_filter": ["shared", "tenant:clinic-a"],
            "custom_kg": {"entities": [{"bad": "shape"}], "relationships": []},
        },
    )
    assert resp.status_code == 422  # FastAPI/pydantic validation error
