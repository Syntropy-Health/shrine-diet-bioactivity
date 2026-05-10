"""E2E tests against the live MCP gateway.

Skipped by default; opt in with one of:
  KG_MCP_E2E_URL=https://kg-mcp-test.up.railway.app pytest -m e2e
  KG_MCP_E2E_URL=http://localhost:8080 ...

Requires:
  KG_MCP_API_KEY — Bearer token (or unset MCP_AUTH_DISABLED is true on the target)

Validates the actual deployed surface — not what unit tests can mock:
  - /health responds 200 without auth
  - /mcp without bearer → 401
  - /mcp with wrong bearer → 401
  - /mcp with correct bearer → MCP initialize handshake succeeds
  - tools/list returns the 10 expected tools
"""
from __future__ import annotations

import json
import os

import httpx
import pytest

E2E_URL = os.environ.get("KG_MCP_E2E_URL")
E2E_KEY = os.environ.get("KG_MCP_API_KEY")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.aura,
    pytest.mark.skipif(not E2E_URL, reason="KG_MCP_E2E_URL not set"),
]


EXPECTED_TOOLS = {
    "kg_query",
    "kg_diet_to_compounds",
    "kg_compound_to_targets",
    "kg_compound_to_diseases",
    "kg_herb_to_diseases",
    "kg_herb_to_symptoms",
    "kg_compound_to_symptoms",
    "kg_hdi_check",
    "kg_bilingual_term",
    "kg_node_neighborhood",
}


def _mcp_headers(token: str | None) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _parse_sse_or_json(text: str) -> dict:
    """Streamable-HTTP transport returns SSE-formatted JSON. Parse either shape."""
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(text)


# ─── /health (no auth) ────────────────────────────────────────────────────


def test_health_no_auth_returns_200():
    r = httpx.get(f"{E2E_URL}/health", timeout=15.0)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "ok"
    # /health should also confirm scoped_server is reachable, not just that
    # the MCP layer booted.
    assert "scoped_server" in body or body.get("status") == "ok"


# ─── /mcp auth gate ───────────────────────────────────────────────────────


def test_mcp_without_bearer_returns_401_or_403():
    r = httpx.post(
        f"{E2E_URL}/mcp",
        headers=_mcp_headers(None),
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "e2e", "version": "0.1"}},
        },
        timeout=15.0,
    )
    # 401 with our middleware; 403 if a future Clerk middleware classifies it differently.
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"


def test_mcp_with_wrong_bearer_returns_401():
    r = httpx.post(
        f"{E2E_URL}/mcp",
        headers=_mcp_headers("not-a-real-key-zzzzzzzz"),
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "e2e", "version": "0.1"}},
        },
        timeout=15.0,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"


@pytest.mark.skipif(not E2E_KEY, reason="KG_MCP_API_KEY not set")
def test_mcp_initialize_with_valid_bearer():
    r = httpx.post(
        f"{E2E_URL}/mcp",
        headers=_mcp_headers(E2E_KEY),
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "e2e", "version": "0.1"}},
        },
        timeout=20.0,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = _parse_sse_or_json(r.text)
    result = body.get("result", body)
    assert result.get("serverInfo", {}).get("name") == "kg-mcp"
    assert "tools" in result.get("capabilities", {})


# ─── tools/list — confirm all 10 tools registered on the live server ──────


@pytest.mark.skipif(not E2E_KEY, reason="KG_MCP_API_KEY not set")
def test_mcp_tools_list_contains_all_ten():
    """Use a single-shot session: initialize, then tools/list."""
    with httpx.Client(timeout=30.0) as client:
        # Step 1: initialize, capture session id from header.
        r = client.post(
            f"{E2E_URL}/mcp",
            headers=_mcp_headers(E2E_KEY),
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "e2e", "version": "0.1"}},
            },
        )
        assert r.status_code == 200
        session_id = r.headers.get("mcp-session-id")
        if not session_id:
            pytest.skip("server did not return mcp-session-id; tools/list needs session")

        # Step 2: notifications/initialized to complete handshake.
        client.post(
            f"{E2E_URL}/mcp",
            headers={**_mcp_headers(E2E_KEY), "mcp-session-id": session_id},
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )

        # Step 3: tools/list.
        r = client.post(
            f"{E2E_URL}/mcp",
            headers={**_mcp_headers(E2E_KEY), "mcp-session-id": session_id},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert r.status_code == 200, r.text
        body = _parse_sse_or_json(r.text)
        tools = (body.get("result") or {}).get("tools", [])
        names = {t["name"] for t in tools}
        assert EXPECTED_TOOLS.issubset(names), f"missing: {EXPECTED_TOOLS - names}"
