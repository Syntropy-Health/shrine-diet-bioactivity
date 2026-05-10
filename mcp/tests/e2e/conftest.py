"""Shared fixtures for ``mcp/tests/e2e/``.

Provides:
  - ``gateway_url`` — base URL of the deployed MCP gateway (e.g. ``https://kg-mcp-test.up.railway.app``)
  - ``gateway_key`` — bearer token from ``KG_MCP_API_KEY``
  - ``gateway_health_ok`` — fail-soft session-scoped probe of ``/health``
  - ``mcp_call`` — callable that performs the MCP streamable-HTTP handshake
    (``initialize`` → ``notifications/initialized`` → ``tools/call``) and
    returns the parsed JSON-RPC envelope.

All fixtures gate on ``KG_MCP_E2E_URL`` and ``KG_MCP_API_KEY``; tests that
depend on them are skipped when the env vars are unset, matching the
behaviour of ``test_live_endpoints.py``.

The transport layer (SSE-or-JSON parsing, header construction) mirrors
``test_live_endpoints.py`` exactly so both test modules behave identically
against the live gateway.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

import httpx
import pytest

E2E_URL = os.environ.get("KG_MCP_E2E_URL")
E2E_KEY = os.environ.get("KG_MCP_API_KEY")


def _mcp_headers(token: str | None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _parse_sse_or_json(text: str) -> dict:
    """Streamable-HTTP transport returns SSE-formatted JSON. Parse either shape."""
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(text)


@pytest.fixture(scope="session")
def gateway_url() -> str:
    """Base URL of the deployed gateway (no trailing ``/mcp``)."""
    if not E2E_URL:
        pytest.skip("KG_MCP_E2E_URL not set")
    return E2E_URL  # type: ignore[return-value]


@pytest.fixture(scope="session")
def gateway_key() -> str:
    if not E2E_KEY:
        pytest.skip("KG_MCP_API_KEY not set")
    return E2E_KEY  # type: ignore[return-value]


@pytest.fixture(scope="session")
def gateway_health_ok(gateway_url: str) -> bool:
    """Probe ``/health`` once per session; skip-on-down so a flaky gateway
    doesn't fail an entire test run with hard errors."""
    try:
        r = httpx.get(f"{gateway_url}/health", timeout=10.0)
    except Exception as exc:  # noqa: BLE001 — broad on purpose; any failure is "down"
        pytest.skip(f"Gateway unreachable: {exc}")
    if r.status_code != 200:
        pytest.skip(f"Gateway /health returned {r.status_code}: {r.text}")
    return True


@pytest.fixture
def mcp_call(
    gateway_url: str,
    gateway_key: str,
    gateway_health_ok: bool,  # noqa: ARG001 — health gate is a side effect
) -> Callable[..., dict[str, Any]]:
    """Return a callable that invokes ``tools/call`` on the live gateway.

    Performs the full streamable-HTTP handshake on each invocation:
      1. ``initialize`` (captures ``mcp-session-id`` header)
      2. ``notifications/initialized`` (completes handshake)
      3. ``tools/call`` (returns parsed JSON-RPC envelope)

    Each call uses a fresh session — fine for E2E since handshake cost is
    negligible compared to KG query cost, and session isolation prevents
    cross-test state leakage.
    """

    def _call(tool_name: str, args: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        with httpx.Client(timeout=timeout) as client:
            # Step 1: initialize.
            r = client.post(
                f"{gateway_url}/mcp",
                headers=_mcp_headers(gateway_key),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest-e2e", "version": "0.1"},
                    },
                },
            )
            assert r.status_code == 200, f"initialize failed: {r.status_code} {r.text}"
            session_id = r.headers.get("mcp-session-id")
            if not session_id:
                pytest.skip("server did not return mcp-session-id; tools/call needs session")

            session_headers = {**_mcp_headers(gateway_key), "mcp-session-id": session_id}

            # Step 2: notifications/initialized.
            r2 = client.post(
                f"{gateway_url}/mcp",
                headers=session_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )
            # Per MCP spec, notifications return 204; 200 also acceptable.
            assert r2.status_code in (200, 202, 204), (
                f"notifications/initialized failed: {r2.status_code} {r2.text[:200]}"
            )

            # Step 3: tools/call.
            r = client.post(
                f"{gateway_url}/mcp",
                headers=session_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                },
            )
            assert r.status_code == 200, f"tools/call {tool_name!r} failed: {r.status_code} {r.text}"
            return _parse_sse_or_json(r.text)

    return _call
