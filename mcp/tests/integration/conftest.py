"""Fixtures for the consumer-side basic integration suite.

This conftest is intentionally a copy-paste-friendly snapshot of the
``mcp/tests/e2e/conftest.py`` fixtures. A consumer (e.g. the
Syntropy-Journals backend) can lift this file verbatim into their own
test tree and only re-point the env-var names to whatever they use.

Gated on ``KG_MCP_E2E_URL`` and ``KG_MCP_API_KEY`` — tests that
depend on the ``mcp_call`` fixture are skipped when either env var is
unset (so `pytest -m integration` in CI without those secrets doesn't
fail; it just records skips).
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

import httpx
import pytest


GATEWAY_URL = os.environ.get("KG_MCP_E2E_URL")
GATEWAY_KEY = os.environ.get("KG_MCP_API_KEY")


def _mcp_headers(token: str | None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _parse_sse_or_json(text: str) -> dict:
    """Streamable-HTTP returns SSE or JSON depending on the transport."""
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(text)


@pytest.fixture
def mcp_call() -> Callable[..., dict[str, Any]]:
    """Three-step MCP streamable-HTTP handshake reduced to one callable.

    Returns ``call(tool_name, args) -> jsonrpc_envelope``. Reuses the
    same shape as ``mcp/tests/e2e/conftest.py::mcp_call`` so probes
    can be copied between dirs.
    """
    if not GATEWAY_URL:
        pytest.skip("KG_MCP_E2E_URL not set")
    if not GATEWAY_KEY:
        pytest.skip("KG_MCP_API_KEY not set")

    def _call(tool_name: str, args: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(
                f"{GATEWAY_URL}/mcp",
                headers=_mcp_headers(GATEWAY_KEY),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "integration-smoke", "version": "0.1"},
                    },
                },
            )
            assert r.status_code == 200, f"initialize: {r.status_code} {r.text}"
            sid = r.headers.get("mcp-session-id")
            assert sid, "gateway did not return mcp-session-id"
            h2 = {**_mcp_headers(GATEWAY_KEY), "mcp-session-id": sid}
            c.post(
                f"{GATEWAY_URL}/mcp",
                headers=h2,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )
            r = c.post(
                f"{GATEWAY_URL}/mcp",
                headers=h2,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                },
            )
            assert r.status_code == 200, f"tools/call {tool_name!r}: {r.status_code} {r.text}"
            return _parse_sse_or_json(r.text)

    return _call
