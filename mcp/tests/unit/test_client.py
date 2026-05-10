"""Unit tests for ScopedServerClient.

httpx is mocked at the AsyncClient level so tests don't hit a real server.
Verifies URL construction, scope_filter handling, graceful 404 fallback for
endpoints not yet on scoped_server.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from kg_mcp.client import ScopedServerClient

pytestmark = [pytest.mark.unit]


def _ok_response(payload: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    r.raise_for_status = MagicMock(return_value=None)
    return r


def _http_error_404(url: str = "http://localhost:9621/x") -> httpx.HTTPStatusError:
    req = httpx.Request("POST", url)
    resp = httpx.Response(404, request=req)
    return httpx.HTTPStatusError("404", request=req, response=resp)


@pytest.fixture
def client():
    c = ScopedServerClient(base_url="http://test:1234")
    c._client = MagicMock()
    c._client.aclose = AsyncMock()
    return c


# ─── base url + close ─────────────────────────────────────────────────────


def test_base_url_strips_trailing_slash():
    c = ScopedServerClient(base_url="http://x:9999/")
    assert c.base_url == "http://x:9999"


def test_base_url_uses_env_when_arg_missing(monkeypatch):
    monkeypatch.setenv("LIGHTRAG_URL", "http://from-env:1111/")
    c = ScopedServerClient()
    assert c.base_url == "http://from-env:1111"


@pytest.mark.asyncio
async def test_aclose_calls_inner_client(client):
    await client.aclose()
    client._client.aclose.assert_awaited_once()


# ─── /health ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_returns_json(client):
    client._client.get = AsyncMock(return_value=_ok_response({"status": "ok", "config": "local"}))
    out = await client.health()
    assert out == {"status": "ok", "config": "local"}
    client._client.get.assert_awaited_with("http://test:1234/health")


# ─── /query ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_posts_body_with_mode_and_top_k(client):
    client._client.post = AsyncMock(return_value=_ok_response({"response": "X"}))
    await client.query("hello", mode="hybrid", top_k=20)
    body = client._client.post.call_args.kwargs["json"]
    assert body == {"query": "hello", "mode": "hybrid", "top_k": 20}


@pytest.mark.asyncio
async def test_query_omits_scope_filter_when_none(client):
    """Server defaults to ['shared']; sending None lets the default apply."""
    client._client.post = AsyncMock(return_value=_ok_response({"response": ""}))
    await client.query("x")
    body = client._client.post.call_args.kwargs["json"]
    assert "scope_filter" not in body


@pytest.mark.asyncio
async def test_query_includes_explicit_scope_filter(client):
    client._client.post = AsyncMock(return_value=_ok_response({"response": ""}))
    await client.query("x", scope_filter=["shared", "tenant:alpha"])
    body = client._client.post.call_args.kwargs["json"]
    assert body["scope_filter"] == ["shared", "tenant:alpha"]


# ─── /graphs ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graphs_uses_query_params(client):
    client._client.get = AsyncMock(return_value=_ok_response({"nodes": [], "edges": []}))
    await client.graphs(label="Curcumin", max_depth=2, max_nodes=100)
    params = client._client.get.call_args.kwargs["params"]
    assert params["label"] == "Curcumin"
    assert params["max_depth"] == 2
    assert params["max_nodes"] == 100


@pytest.mark.asyncio
async def test_graphs_serializes_scope_filter_as_csv(client):
    client._client.get = AsyncMock(return_value=_ok_response({"nodes": [], "edges": []}))
    await client.graphs(label="X", scope_filter=["shared", "tenant:alpha"])
    params = client._client.get.call_args.kwargs["params"]
    assert params["scope_filter"] == "shared,tenant:alpha"


# ─── /traverse + 404 fallback ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_traverse_calls_traverse_endpoint_when_present(client):
    client._client.post = AsyncMock(return_value=_ok_response({"chains": [{"edges": []}]}))
    out = await client.traverse(
        start_label="Compound", edge_types=["TARGETS_PROTEIN"],
        seed="Curcumin", direction="outbound", depth=1, top_k=10,
    )
    body = client._client.post.call_args.kwargs["json"]
    assert body["start_label"] == "Compound"
    assert body["edge_types"] == ["TARGETS_PROTEIN"]
    assert body["seed"] == "Curcumin"
    assert out == {"chains": [{"edges": []}]}


@pytest.mark.asyncio
async def test_traverse_falls_back_to_graphs_on_404(client):
    """Until scoped_server gains /traverse, fall back to /graphs gracefully."""
    err = _http_error_404("http://test:1234/traverse")
    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = err
    bad_resp.status_code = 404
    bad_resp.json.return_value = {}

    ok_resp = _ok_response({"nodes": [{"id": 1}], "edges": []})

    client._client.post = AsyncMock(return_value=bad_resp)
    client._client.get = AsyncMock(return_value=ok_resp)

    out = await client.traverse(
        start_label="X", edge_types=["E"], seed="seed",
    )
    # /graphs was called as the fallback
    client._client.get.assert_awaited_once()
    assert out == {"nodes": [{"id": 1}], "edges": []}


@pytest.mark.asyncio
async def test_traverse_propagates_non_404_errors(client):
    req = httpx.Request("POST", "http://test:1234/traverse")
    resp = httpx.Response(500, request=req)
    err = httpx.HTTPStatusError("500", request=req, response=resp)
    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = err

    client._client.post = AsyncMock(return_value=bad_resp)

    with pytest.raises(httpx.HTTPStatusError):
        await client.traverse(start_label="X", edge_types=["E"], seed="s")


# ─── /hdi_check ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hdi_check_returns_payload_when_endpoint_exists(client):
    client._client.post = AsyncMock(return_value=_ok_response({
        "found": True, "severity": "moderate", "mechanism_class": "CYP450",
    }))
    out = await client.hdi_check("warfarin", "Ginkgo")
    body = client._client.post.call_args.kwargs["json"]
    assert body == {"drug": "warfarin", "herb": "Ginkgo"}
    assert out["found"] is True
    assert out["severity"] == "moderate"


@pytest.mark.asyncio
async def test_hdi_check_returns_empty_on_404(client):
    err = _http_error_404("http://test:1234/hdi_check")
    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = err
    bad_resp.status_code = 404
    client._client.post = AsyncMock(return_value=bad_resp)

    out = await client.hdi_check("warfarin", "Ginkgo")
    assert out == {"found": False}


# ─── /bilingual_term ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bilingual_term_passes_term_and_languages(client):
    client._client.post = AsyncMock(return_value=_ok_response({
        "english": "Coptis", "chinese": "黄连", "pinyin": "huang lian",
    }))
    out = await client.bilingual_term("黄连", ["en", "cn", "pinyin"])
    body = client._client.post.call_args.kwargs["json"]
    assert body == {"term": "黄连", "languages": ["en", "cn", "pinyin"]}
    assert out["chinese"] == "黄连"


@pytest.mark.asyncio
async def test_bilingual_term_returns_empty_on_404(client):
    err = _http_error_404("http://test:1234/bilingual_term")
    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = err
    bad_resp.status_code = 404
    client._client.post = AsyncMock(return_value=bad_resp)

    out = await client.bilingual_term("黄连", ["en"])
    assert out == {}
