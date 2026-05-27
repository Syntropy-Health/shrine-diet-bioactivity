"""Tests for _openai_compat_embed — the OpenRouter-compatible embed call.

lightrag's bundled openai_embed hardcodes ``encoding_format="base64"``,
which OpenRouter rejects (returns ``{"error": ...}`` with no ``data``),
producing a downstream ``'NoneType' object is not iterable``. The ingest
script replaces it with ``_openai_compat_embed`` — a direct call that
uses float encoding and passes base_url / api_key explicitly.

These tests pin that contract so the base64 regression cannot return:
  - the request payload must NOT carry ``encoding_format``
  - missing ``data`` must raise a clear error, not crash downstream
  - results must come back in input order regardless of response order

Usage:
    python -m pytest test_ingest_embed.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np
import pytest

from ingest_unified import _openai_compat_embed

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# httpx mock plumbing
# ---------------------------------------------------------------------------


def _mock_httpx(response_body: dict, *, raise_status: Exception | None = None):
    """Build a patch target for httpx.AsyncClient.

    Returns a MagicMock suitable for ``patch("httpx.AsyncClient", ...)``.
    The client is used as ``async with httpx.AsyncClient(...) as client``.
    """
    resp = MagicMock()
    resp.json.return_value = response_body
    if raise_status is not None:
        resp.raise_for_status = MagicMock(side_effect=raise_status)
    else:
        resp.raise_for_status = MagicMock(return_value=None)

    client = MagicMock()
    client.post = AsyncMock(return_value=resp)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock(return_value=ctx)
    # expose the inner post mock so tests can assert on the request
    factory._post = client.post
    return factory


def _embedding_response(vectors: list[list[float]]) -> dict:
    """OpenAI-shaped embeddings response, items in input order (index == position)."""
    data = [
        {"object": "embedding", "index": i, "embedding": vec}
        for i, vec in enumerate(vectors)
    ]
    return {"object": "list", "data": data, "model": "test-model"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_returns_float32_array_of_right_shape():
    factory = _mock_httpx(_embedding_response([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]))
    with patch("httpx.AsyncClient", factory):
        out = asyncio.run(
            _openai_compat_embed(
                ["a", "b"], model="m", base_url="https://x/api/v1",
                api_key="k", embedding_dim=3,
            )
        )
    assert isinstance(out, np.ndarray)
    assert out.shape == (2, 3)
    assert out.dtype == np.float32


def test_request_payload_has_no_encoding_format():
    """The base64 regression guard — encoding_format must never be sent."""
    factory = _mock_httpx(_embedding_response([[1.0, 2.0]]))
    with patch("httpx.AsyncClient", factory):
        asyncio.run(
            _openai_compat_embed(
                ["only"], model="nv-embed", base_url="https://openrouter.ai/api/v1",
                api_key="k", embedding_dim=2,
            )
        )
    sent = factory._post.await_args.kwargs["json"]
    assert "encoding_format" not in sent, "encoding_format=base64 is the OpenRouter-incompatible bug"
    assert sent["model"] == "nv-embed"
    assert sent["input"] == ["only"]
    assert sent["dimensions"] == 2


def test_results_sorted_by_response_index():
    """Round-trip proof: output row i must hold the embedding the provider
    tagged index=i, regardless of the order items appear in the response list.

    The contract: input "x"→index 0→[1.0], "y"→1→[2.0], "z"→2→[3.0]. The
    response lists them scrambled; the function must re-sort to input order.
    """
    body = {"data": [
        {"index": 2, "embedding": [3.0]},   # belongs to input "z"
        {"index": 0, "embedding": [1.0]},   # belongs to input "x"
        {"index": 1, "embedding": [2.0]},   # belongs to input "y"
    ]}
    factory = _mock_httpx(body)
    with patch("httpx.AsyncClient", factory):
        out = asyncio.run(
            _openai_compat_embed(
                ["x", "y", "z"], model="m", base_url="https://x/v1",
                api_key="k", embedding_dim=1,
            )
        )
    # Scrambled list order + explicit index → output reconstructed in input order.
    assert out.flatten().tolist() == [1.0, 2.0, 3.0]


def test_missing_index_field_raises():
    """An item without `index` must fail loudly — a default sort key would
    silently misalign embeddings with their source texts."""
    body = {"data": [
        {"embedding": [1.0]},               # no `index`
        {"index": 1, "embedding": [2.0]},
    ]}
    factory = _mock_httpx(body)
    with patch("httpx.AsyncClient", factory):
        with pytest.raises(RuntimeError, match="index"):
            asyncio.run(
                _openai_compat_embed(
                    ["a", "b"], model="m", base_url="https://x/v1",
                    api_key="k", embedding_dim=1,
                )
            )


def test_base_url_trailing_slash_is_stripped():
    factory = _mock_httpx(_embedding_response([[1.0]]))
    with patch("httpx.AsyncClient", factory):
        asyncio.run(
            _openai_compat_embed(
                ["a"], model="m", base_url="https://x/api/v1/",
                api_key="k", embedding_dim=1,
            )
        )
    url = factory._post.await_args.args[0]
    assert url == "https://x/api/v1/embeddings"


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


def test_authorization_header_present_with_api_key():
    factory = _mock_httpx(_embedding_response([[1.0]]))
    with patch("httpx.AsyncClient", factory):
        asyncio.run(
            _openai_compat_embed(
                ["a"], model="m", base_url="https://x/v1",
                api_key="secret-token", embedding_dim=1,
            )
        )
    headers = factory._post.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret-token"


def test_authorization_header_omitted_when_api_key_none():
    factory = _mock_httpx(_embedding_response([[1.0]]))
    with patch("httpx.AsyncClient", factory):
        asyncio.run(
            _openai_compat_embed(
                ["a"], model="m", base_url="https://x/v1",
                api_key=None, embedding_dim=1,
            )
        )
    headers = factory._post.await_args.kwargs["headers"]
    assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_data_raises_runtime_error():
    """OpenRouter rejects bad params with {"error": ...} and no data —
    must raise a clear error, not 'NoneType is not iterable' downstream."""
    factory = _mock_httpx({"error": {"message": "unsupported encoding_format"}})
    with patch("httpx.AsyncClient", factory):
        with pytest.raises(RuntimeError, match="no data|error"):
            asyncio.run(
                _openai_compat_embed(
                    ["a"], model="m", base_url="https://x/v1",
                    api_key="k", embedding_dim=1,
                )
            )


def test_data_not_a_list_raises_runtime_error():
    factory = _mock_httpx({"data": None})
    with patch("httpx.AsyncClient", factory):
        with pytest.raises(RuntimeError):
            asyncio.run(
                _openai_compat_embed(
                    ["a"], model="m", base_url="https://x/v1",
                    api_key="k", embedding_dim=1,
                )
            )


def test_http_error_propagates():
    """A non-transient 4xx from the endpoint must not be swallowed."""
    factory = _mock_httpx({}, raise_status=RuntimeError("boom"))
    with patch("httpx.AsyncClient", factory):
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(
                _openai_compat_embed(
                    ["a"], model="m", base_url="https://x/v1",
                    api_key="k", embedding_dim=1,
                )
            )


# ---------------------------------------------------------------------------
# Transient-failure retry
# ---------------------------------------------------------------------------


def _mock_httpx_sequence(items: list):
    """httpx.AsyncClient factory whose .post yields `items` across calls.

    Each item is either a response body dict (HTTP 200) or an Exception
    instance to raise. The retry loop creates a fresh client per attempt,
    but the post mock is shared, so side_effect advances per attempt.
    """
    side_effects = []
    for it in items:
        if isinstance(it, Exception):
            side_effects.append(it)
        else:
            resp = MagicMock()
            resp.json.return_value = it
            resp.raise_for_status = MagicMock(return_value=None)
            side_effects.append(resp)

    client = MagicMock()
    client.post = AsyncMock(side_effect=side_effects)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=ctx)
    factory._post = client.post
    return factory


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://x/v1/embeddings")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"HTTP {code}", request=req, response=resp)


def test_retries_transient_520_body_then_succeeds():
    """OpenRouter's 200-with-{'code':520} body is transient → retry, then win."""
    factory = _mock_httpx_sequence([
        {"message": "HTTP 520: error code: 520", "code": 520},  # transient
        _embedding_response([[1.0, 2.0]]),                       # recovered
    ])
    with patch("httpx.AsyncClient", factory), patch("asyncio.sleep", new=AsyncMock()):
        out = asyncio.run(
            _openai_compat_embed(
                ["a"], model="m", base_url="https://x/v1",
                api_key="k", embedding_dim=2, max_retries=4,
            )
        )
    assert out.shape == (1, 2)
    assert factory._post.await_count == 2


def test_retries_transient_http_503_then_succeeds():
    factory = _mock_httpx_sequence([
        _http_status_error(503),               # transient gateway error
        _embedding_response([[9.0]]),          # recovered
    ])
    with patch("httpx.AsyncClient", factory), patch("asyncio.sleep", new=AsyncMock()):
        out = asyncio.run(
            _openai_compat_embed(
                ["a"], model="m", base_url="https://x/v1",
                api_key="k", embedding_dim=1, max_retries=4,
            )
        )
    assert out.flatten().tolist() == [9.0]
    assert factory._post.await_count == 2


def test_permanent_http_400_not_retried():
    """A 400 is a client error — retrying is pointless; fail on first attempt."""
    factory = _mock_httpx_sequence([
        _http_status_error(400),
        _embedding_response([[1.0]]),  # never reached
    ])
    with patch("httpx.AsyncClient", factory), patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(
                _openai_compat_embed(
                    ["a"], model="m", base_url="https://x/v1",
                    api_key="k", embedding_dim=1, max_retries=4,
                )
            )
    assert factory._post.await_count == 1, "400 must not be retried"


def test_retries_exhausted_raises():
    """Persistent transient failure → raise after max_retries attempts."""
    factory = _mock_httpx_sequence([
        {"message": "HTTP 520", "code": 520},
        {"message": "HTTP 520", "code": 520},
        {"message": "HTTP 520", "code": 520},
    ])
    with patch("httpx.AsyncClient", factory), patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="after 3 attempts|no data"):
            asyncio.run(
                _openai_compat_embed(
                    ["a"], model="m", base_url="https://x/v1",
                    api_key="k", embedding_dim=1, max_retries=3,
                )
            )
    assert factory._post.await_count == 3


def test_network_error_is_retried():
    """httpx.RequestError (timeout / connection reset) is transient."""
    factory = _mock_httpx_sequence([
        httpx.ConnectError("connection reset"),
        _embedding_response([[5.0]]),
    ])
    with patch("httpx.AsyncClient", factory), patch("asyncio.sleep", new=AsyncMock()):
        out = asyncio.run(
            _openai_compat_embed(
                ["a"], model="m", base_url="https://x/v1",
                api_key="k", embedding_dim=1, max_retries=4,
            )
        )
    assert out.flatten().tolist() == [5.0]
    assert factory._post.await_count == 2
