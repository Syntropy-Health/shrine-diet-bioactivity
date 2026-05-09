"""MCP client SDK smoke tests — exercise the full transport surface.

These tests use the **canonical Python MCP client SDK** (via
``create_connected_server_and_client_session`` from ``mcp.shared.memory``)
to drive the actual ``kg-mcp`` FastMCP server in-process.

Why this exists alongside the existing unit + e2e tests:

  - ``test_tools.py`` covers tool *logic* with a mocked client → fast, but
    bypasses MCP wire serialization and Pydantic schema enforcement.
  - ``test_live_endpoints.py`` covers the *deployed* HTTP surface using raw
    httpx → proves the wire format works, but doesn't exercise the
    canonical MCP client handshake (initialize → notifications/initialized
    → call_tool → result deserialization).
  - This file fills the gap: a real ``ClientSession`` connected in-memory
    to the real FastMCP server, with the **backend KG mocked** so each
    test is hermetic and CI-safe (no Neo4j, no LightRAG, no network).

The "real-world simple task" smoke tests verify that, end-to-end:
  1. The MCP client can list all 10 tools from the running server.
  2. Each Layer-A / Layer-B / Layer-C tool round-trips a representative
     real-world query (e.g. "what compounds are in garlic?",
     "does warfarin interact with garlic?") through the full FastMCP
     pipeline, with results deserialized correctly on the client side.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from kg_mcp.server import server


# ---------------------------------------------------------------------------
# Mock fixture: real FastMCP server + real ClientSession + mocked KG backend
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _connected_session_with_mock_backend(backend_responses: dict):
    """Spin up an in-memory MCP client/server pair with mocked ScopedServer.

    Args:
      backend_responses: maps method name (e.g. 'query', 'traverse',
        'hdi_check') to the canned response the mocked client should return.
    """
    fake_client = AsyncMock()
    fake_client.health = AsyncMock(return_value={"status": "ok"})
    for method, response in backend_responses.items():
        setattr(fake_client, method, AsyncMock(return_value=response))
    fake_client.aclose = AsyncMock()

    # Patch the real ScopedServerClient construction inside the server's
    # lifespan so the in-memory MCP server uses our mock instead of trying
    # to talk to a real LightRAG instance.
    with patch(
        "kg_mcp.server.ScopedServerClient", return_value=fake_client
    ):
        async with create_connected_server_and_client_session(
            server._mcp_server
        ) as session:
            await session.initialize()
            yield session, fake_client


def _content_payload(call_tool_result) -> str:
    """Extract the text payload from a CallToolResult.

    FastMCP wraps tool returns into TextContent blocks; when the tool
    returns a Pydantic model, FastMCP serializes its model_dump_json()
    into the first content block.
    """
    assert call_tool_result.content, "tool returned no content"
    return call_tool_result.content[0].text


# ---------------------------------------------------------------------------
# tools/list — tool catalog round-trips through MCP transport
# ---------------------------------------------------------------------------


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


@pytest.mark.asyncio
async def test_client_lists_all_ten_tools_via_mcp_protocol():
    """Real ClientSession → real FastMCP server → all 10 tools come back."""
    async with _connected_session_with_mock_backend({}) as (session, _):
        result = await session.list_tools()
        names = {t.name for t in result.tools}
        assert names == EXPECTED_TOOLS, (
            f"missing: {EXPECTED_TOOLS - names}, extra: {names - EXPECTED_TOOLS}"
        )


@pytest.mark.asyncio
async def test_each_tool_has_input_schema_and_description():
    """Every registered tool must expose a JSON-schema input + a description."""
    async with _connected_session_with_mock_backend({}) as (session, _):
        result = await session.list_tools()
        for tool in result.tools:
            assert tool.description, f"{tool.name} has no description"
            assert tool.inputSchema is not None, f"{tool.name} has no inputSchema"
            assert tool.inputSchema.get("type") == "object", (
                f"{tool.name} inputSchema is not an object"
            )


# ---------------------------------------------------------------------------
# Real-world simple-task smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_world_kg_query_natural_language_question():
    """Simulate a researcher asking 'does ginger help with nausea?'

    Tests Layer A (kg_query) end-to-end: client serializes args → MCP
    transport → FastMCP routes to handler → tool calls mocked KG → result
    flows back through transport → client deserializes.
    """
    async with _connected_session_with_mock_backend(
        {
            "query": {
                "response": "Ginger contains gingerols which reduce nausea.",
                "references": ["Ginger", "Zingiber officinale"],
                "scope_filter": ["shared"],
            }
        }
    ) as (session, fake_client):
        result = await session.call_tool(
            "kg_query",
            {"question": "Does ginger help with nausea?"},
        )
        assert not result.isError, _content_payload(result)
        payload = _content_payload(result)
        # Pydantic model is serialized as JSON-shaped text.
        assert "gingerols" in payload or "Ginger" in payload
        # Verify the tool actually called through to the (mocked) backend.
        fake_client.query.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_world_diet_to_compounds_for_garlic():
    """A Dietitian asks 'what bioactives are in garlic?'

    Exercises Layer B's deterministic Food→Compound traversal.
    """
    async with _connected_session_with_mock_backend(
        {
            "traverse": {
                "chains": [
                    {
                        "edges": [
                            {
                                "src_id": "Garlic",
                                "tgt_id": "Allicin",
                                "rel_type": "FOUND_IN_FOOD",
                            }
                        ],
                    }
                ],
                "seeds_resolved": ["Garlic"],
            }
        }
    ) as (session, fake_client):
        result = await session.call_tool(
            "kg_diet_to_compounds",
            {"seed": "Garlic", "top_k": 5},
        )
        assert not result.isError, _content_payload(result)
        payload = _content_payload(result)
        assert "Allicin" in payload
        # Layer B fixes start_label/edge_types/direction/depth; only seed +
        # top_k vary per call. Verify the role-prior was applied correctly.
        call = fake_client.traverse.call_args
        assert call is not None
        kwargs = call.kwargs
        assert kwargs.get("start_label") == "Food"
        assert kwargs.get("seed") == "Garlic"
        assert kwargs.get("top_k") == 5


@pytest.mark.asyncio
async def test_real_world_compound_to_targets_for_curcumin():
    """A Pharmacologist asks 'what proteins does curcumin bind?'

    Layer B Compound→Target traversal — the gene-symbol-anchored chain.
    """
    async with _connected_session_with_mock_backend(
        {
            "traverse": {
                "chains": [
                    {
                        "edges": [
                            {
                                "src_id": "Curcumin",
                                "tgt_id": "NF-kappa-B p65",
                                "rel_type": "TARGETS_PROTEIN",
                            }
                        ],
                    }
                ],
                "seeds_resolved": ["Curcumin"],
            }
        }
    ) as (session, _):
        result = await session.call_tool(
            "kg_compound_to_targets",
            {"seed": "Curcumin"},
        )
        assert not result.isError, _content_payload(result)
        assert "NF-kappa-B" in _content_payload(result)


@pytest.mark.asyncio
async def test_real_world_hdi_check_warfarin_garlic():
    """A safety review asks 'does warfarin interact with garlic?'

    Layer C lookup primitive — direct query against the HDI-Safe-50 panel.
    """
    async with _connected_session_with_mock_backend(
        {
            "hdi_check": {
                "found": True,
                "severity": "moderate",
                "mechanism_class": "coagulation",
                "evidence_tier": "case-report",
            }
        }
    ) as (session, fake_client):
        result = await session.call_tool(
            "kg_hdi_check",
            {"drug": "warfarin", "herb": "garlic"},
        )
        assert not result.isError, _content_payload(result)
        payload = _content_payload(result)
        assert "moderate" in payload
        assert "coagulation" in payload
        fake_client.hdi_check.assert_awaited_with("warfarin", "garlic")


@pytest.mark.asyncio
async def test_real_world_hdi_check_no_match_returns_found_false():
    """Lookup with no panel hit should return found=False, not error."""
    async with _connected_session_with_mock_backend(
        {"hdi_check": {"found": False, "drug": "obscuredrug", "herb": "obscureherb"}}
    ) as (session, _):
        result = await session.call_tool(
            "kg_hdi_check",
            {"drug": "obscuredrug", "herb": "obscureherb"},
        )
        assert not result.isError, _content_payload(result)
        assert "false" in _content_payload(result).lower()


@pytest.mark.asyncio
async def test_real_world_bilingual_term_canonicalization():
    """Layer C — SymMap canonicalization of a Chinese symptom name."""
    async with _connected_session_with_mock_backend(
        {
            "bilingual_term": {
                "term_in": "失眠",
                "english": "Insomnia",
                "chinese": "失眠",
                "pinyin": "Shi Mian",
                "matched": True,
            }
        }
    ) as (session, fake_client):
        result = await session.call_tool(
            "kg_bilingual_term",
            {"term": "失眠"},
        )
        assert not result.isError, _content_payload(result)
        assert "Insomnia" in _content_payload(result)
        assert "Shi Mian" in _content_payload(result)
        fake_client.bilingual_term.assert_awaited_once()


# ---------------------------------------------------------------------------
# Negative-path tests — input validation flows through MCP transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_unknown_tool_returns_error():
    """An unknown tool name should surface a graceful error, not crash.

    FastMCP's low-level handler logs a warning and returns isError=True with
    the failure message in content; it does not raise. Either contract is
    acceptable — the invariant we care about is "the call doesn't silently
    succeed."
    """
    async with _connected_session_with_mock_backend({}) as (session, _):
        result = await session.call_tool("nonexistent_tool_xyz", {})
        assert result.isError, "unknown tool must produce isError=True"
        assert "nonexistent_tool_xyz" in _content_payload(result)


@pytest.mark.asyncio
async def test_kg_query_missing_required_arg_validation_error():
    """Pydantic schema requires 'question'; missing it should error cleanly."""
    async with _connected_session_with_mock_backend({}) as (session, _):
        result = await session.call_tool("kg_query", {})
        # FastMCP returns isError=True with the validation message in content
        # rather than raising. Either form is acceptable; we assert the
        # call doesn't silently succeed.
        assert result.isError or "question" in _content_payload(result).lower()
