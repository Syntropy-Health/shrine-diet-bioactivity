"""Basic consumer-side integration smoke.

The minimum a downstream MCP client (Syntropy-Journals chat agent,
custom SDK loop, Claude Desktop) needs to know works before relying
on kg-mcp in a user flow. Three tests:

  1. /health responds 200 without auth — service is up.
  2. tools/list returns the 10 documented MCP tools — contract intact.
  3. One Layer-B traversal returns >= 1 chain with documented
     source-id prefix — the KG actually answers a real query.

Lift this file (and conftest.py) verbatim into a consumer repo and
only re-point the env-var names if you carry a different token type.
"""
from __future__ import annotations

import json
import os
import re

import httpx
import pytest


pytestmark = [pytest.mark.integration]


_SOURCE_PREFIX = re.compile(
    r"^(cmaup|duke|herb2|symmap|hdi-safe-50|opentcm|food):",
    re.IGNORECASE,
)

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


def test_gateway_health_returns_200():
    """Service-up probe — no auth, no MCP. Catches Railway/proxy outages
    before consumer code tries to authenticate."""
    url = os.environ.get("KG_MCP_E2E_URL")
    if not url:
        pytest.skip("KG_MCP_E2E_URL not set")
    r = httpx.get(f"{url}/health", timeout=10.0)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"


def test_tools_list_contract(mcp_call):
    """The gateway advertises all 10 documented tools — consumer code
    that hardcodes tool names won't silently break on a deploy."""
    url = os.environ["KG_MCP_E2E_URL"]
    key = os.environ["KG_MCP_API_KEY"]
    h = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{url}/mcp",
            headers=h,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "consumer-smoke", "version": "0.1"},
                },
            },
        )
        assert r.status_code == 200
        sid = r.headers["mcp-session-id"]
        h2 = {**h, "mcp-session-id": sid}
        c.post(
            f"{url}/mcp", headers=h2,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        r = c.post(
            f"{url}/mcp", headers=h2,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert r.status_code == 200
        # Streamable-HTTP returns SSE-or-JSON; tolerate both.
        body = None
        for line in r.text.splitlines():
            if line.startswith("data: "):
                body = json.loads(line[6:])
                break
        if body is None:
            body = r.json()
        tools = (body.get("result") or {}).get("tools", [])
        names = {t["name"] for t in tools}
    assert EXPECTED_TOOLS.issubset(names), f"missing tools: {EXPECTED_TOOLS - names}"


def test_herb_to_symptoms_returns_provenance_tagged_chain(mcp_call):
    """End-to-end consumer flow: call a Layer-B tool with a real seed,
    pull a chain out of the typed payload, validate the documented
    source-id prefix. This is what a Syntropy-Journals chat-agent call
    looks like under the hood — if this passes, the agent can ground
    its responses with provenance.

    Seed choice: ``Astragalus membranaceus`` has 38 TREATS_SYMPTOM
    edges in the current KG (verified via Cypher 2026-05-26) — a
    stable, populated path that doesn't depend on KG content not yet
    ingested (SYN-109 tracks broader content backfill).
    """
    result = mcp_call(
        "kg_herb_to_symptoms",
        {"seed": "Astragalus membranaceus", "top_k": 3},
    )
    assert "result" in result, f"no result envelope: {result}"
    envelope = result["result"]
    assert not envelope.get("isError"), f"tool returned error: {envelope}"
    payload = envelope.get("structuredContent") or envelope
    chains = payload.get("chains") or []
    assert len(chains) >= 1, f"expected >= 1 chain, got {chains}"
    # Provenance discipline: every edge's source_id matches the
    # documented prefix regex.
    for chain in chains:
        for edge in chain.get("edges", []):
            sid = edge.get("source_id", "")
            assert _SOURCE_PREFIX.match(sid), f"unknown source_id prefix: {sid!r}"
