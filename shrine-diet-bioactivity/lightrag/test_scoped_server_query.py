"""Unit tests for POST /query — verifies scope_filter default-to-shared behavior.

The default-to-shared policy aligns with:
  - scope_context.DEFAULT_SCOPE = ('shared',)
  - Project policy: open-source data ingests under scope='shared'

Tenant-scoped clients still pass scope_filter explicitly; the server cannot
guess a tenant.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


# Reuse the fake rag + fixture pattern from test_scoped_server_graph.py.
class _FakeRag:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._scope_seen: list[list[str]] = []

    async def aquery(self, query: str, param: Any = None) -> str:
        from scope_context import get_scope_filter

        self._scope_seen.append(get_scope_filter())
        self.calls.append(("aquery", (query,), {"param": param}))
        return f"fake response for: {query}"

    async def finalize_storages(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
        yield c


@pytest.mark.unit
def test_query_defaults_to_shared_scope_when_omitted(client: TestClient) -> None:
    """No scope_filter in body → server applies ['shared']."""
    resp = client.post("/query", json={"query": "What treats nausea?"})
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    assert fake._scope_seen[-1] == ["shared"]


@pytest.mark.unit
def test_query_accepts_explicit_shared_scope(client: TestClient) -> None:
    resp = client.post(
        "/query",
        json={"query": "X", "scope_filter": ["shared"]},
    )
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    assert fake._scope_seen[-1] == ["shared"]


@pytest.mark.unit
def test_query_accepts_tenant_scope(client: TestClient) -> None:
    resp = client.post(
        "/query",
        json={"query": "X", "scope_filter": ["shared", "tenant:clinic-a"]},
    )
    assert resp.status_code == 200, resp.text
    fake = client._fake_rag  # type: ignore[attr-defined]
    assert fake._scope_seen[-1] == ["shared", "tenant:clinic-a"]


@pytest.mark.unit
def test_query_rejects_empty_scope_filter_list(client: TestClient) -> None:
    """Empty list is malformed even though field is now defaulted."""
    resp = client.post(
        "/query",
        json={"query": "X", "scope_filter": []},
    )
    assert resp.status_code == 422  # pydantic min_length=1 rejection


@pytest.mark.unit
def test_query_rejects_malformed_scope(client: TestClient) -> None:
    resp = client.post(
        "/query",
        json={"query": "X", "scope_filter": ["tenant:INVALID_CAPS"]},
    )
    assert resp.status_code == 400


@pytest.mark.unit
def test_query_response_carries_scope_filter_back(client: TestClient) -> None:
    """Sanity: caller can verify which scope the server actually applied."""
    resp = client.post("/query", json={"query": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("scope_filter") == ["shared"]
