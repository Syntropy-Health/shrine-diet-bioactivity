"""Agentic E2E — minimal Anthropic SDK tool-use loop against live kg-mcp.

Goal: prove an LLM agent, given only the gateway URL + bearer token,
can successfully ground a clinical-style question on the live KG. Locks
the "functional prototype readiness" criterion the migration is in
service of (Phase 5 of the plan).

Loop is intentionally tiny — one tool registered (``kg_query``), one
back-and-forth, then we assert the agent's reply cites at least one
provenance source_id matching the documented prefix regex.

Gating: three env vars must all be present, or the test skips cleanly:

  * ``KG_MCP_E2E_URL``      — gateway base URL, e.g. ``https://kg-mcp-test.up.railway.app``
  * ``KG_MCP_API_KEY``      — bearer token enforced on /mcp
  * ``ANTHROPIC_API_KEY``   — for the SDK loop

Why not AG2: AG2 is heavyweight (multi-agent orchestration). For a single
tool-use loop, the bare Anthropic SDK is one file and avoids pulling AG2
into the kg-mcp test path. Per architectural choice in /plan discussion.
"""
from __future__ import annotations

import json
import os
import re

import httpx
import pytest


pytestmark = [pytest.mark.e2e]


_SOURCE_PREFIX = re.compile(
    r"\b(duke|cmaup|herb2|symmap|hdi-safe-50|opentcm|food):[A-Za-z0-9_\-]+",
    re.IGNORECASE,
)


def _env_or_skip(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} not set; agentic E2E skipped.")
    return value


# ---------------------------------------------------------------------------
# Minimal kg-mcp client — initialise, call one tool, return the typed payload
# ---------------------------------------------------------------------------


def _mcp_call(url: str, key: str, tool: str, arguments: dict) -> dict:
    """Invoke a single MCP tool via streamable-HTTP. Returns the typed
    structuredContent payload (or the envelope dict on isError)."""
    h = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with httpx.Client(timeout=60.0) as c:
        # initialize
        r = c.post(
            f"{url}/mcp",
            headers=h,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agentic-e2e", "version": "0.1"},
                },
            },
        )
        r.raise_for_status()
        sid = r.headers["mcp-session-id"]
        h2 = {**h, "mcp-session-id": sid}
        c.post(
            f"{url}/mcp",
            headers=h2,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        # tools/call
        r = c.post(
            f"{url}/mcp",
            headers=h2,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        r.raise_for_status()
        body = None
        for line in r.text.splitlines():
            if line.startswith("data: "):
                body = json.loads(line[6:])
                break
        if body is None:
            body = r.json()
        envelope = body.get("result", {}) or {}
        return envelope.get("structuredContent") or envelope


# ---------------------------------------------------------------------------
# The actual agentic loop
# ---------------------------------------------------------------------------


def test_agent_uses_kg_query_and_cites_provenance():
    """One-turn agentic loop: the model picks ``kg_query``, gets a real
    payload, and produces a final reply that cites ≥ 1 provenance
    source_id matching the documented prefix regex.

    A skip-clean PRO TIP: pre-fund OpenRouter / Anthropic in CI with a
    tiny budget; the loop costs < $0.005 per run.
    """
    url = _env_or_skip("KG_MCP_E2E_URL")
    key = _env_or_skip("KG_MCP_API_KEY")
    anthropic_key = _env_or_skip("ANTHROPIC_API_KEY")

    try:
        from anthropic import Anthropic
    except ImportError:
        pytest.skip("anthropic SDK not installed in this test env.")

    client = Anthropic(api_key=anthropic_key)
    tools = [
        {
            "name": "kg_query",
            "description": (
                "Search the Syntropy clinical knowledge graph for "
                "compounds, herbs, foods, targets, diseases, and symptoms. "
                "Returns ranked entities with provenance source_ids."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural-language question about diet/herbs/compounds.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["local", "global", "hybrid", "naive", "mix"],
                        "default": "local",
                    },
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["question"],
            },
        }
    ]
    user_msg = (
        "What compounds in Astragalus membranaceus help with immune "
        "function? Use the kg_query tool, then summarize the top finding "
        "and include the source_id of at least one supporting edge."
    )

    # Turn 1 — model decides whether to call the tool.
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        tools=tools,
        messages=[{"role": "user", "content": user_msg}],
    )

    tool_use = next(
        (c for c in resp.content if getattr(c, "type", "") == "tool_use"),
        None,
    )
    assert tool_use is not None, (
        f"Model didn't call kg_query. stop_reason={resp.stop_reason} "
        f"content={[c.type for c in resp.content]}"
    )
    assert tool_use.name == "kg_query"

    # Execute the tool against the live gateway.
    tool_result = _mcp_call(url, key, "kg_query", dict(tool_use.input))

    # Turn 2 — feed the tool result back; model summarises.
    final = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        tools=tools,
        messages=[
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": resp.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(tool_result)[:8000],
                    }
                ],
            },
        ],
    )
    final_text = "\n".join(
        c.text for c in final.content if getattr(c, "type", "") == "text"
    )
    assert final_text.strip(), f"empty final reply; got {final.content!r}"

    # Provenance discipline: the reply must include at least one
    # source_id matching the documented prefix regex. This is a strong
    # signal that the agent actually used the KG payload (rather than
    # hallucinating around it).
    assert _SOURCE_PREFIX.search(final_text), (
        "Agent reply lacks a documented source_id prefix — provenance "
        f"discipline failed.\n--- reply ---\n{final_text[:800]}"
    )
