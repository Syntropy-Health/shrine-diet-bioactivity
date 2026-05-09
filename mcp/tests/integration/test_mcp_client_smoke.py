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
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

# NOTE: ``server._mcp_server`` is a private attribute of FastMCP. There is no
# public API for in-memory wiring in the current SDK (mcp~=1.0). If FastMCP
# renames this attribute in a future release, the fixture below will break
# loudly — pin ``mcp`` upper bound in pyproject.toml when that happens.
from kg_mcp.server import server


# ---------------------------------------------------------------------------
# Mock fixture: real FastMCP server + real ClientSession + mocked KG backend
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _connected_session_with_mock_backend(backend_responses: dict[str, Any]):
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
    """Layer A — researcher asks 'does ginger help with nausea?'

    Verifies: client args → MCP transport → FastMCP handler → mocked KG →
    transport → client deserialization. Both seeded strings must round-trip.
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
        assert "gingerols" in payload
        assert "Zingiber officinale" in payload
        fake_client.query.assert_awaited_once()


# Layer-B traversals share a fixed mock shape and a uniform call contract:
# every tool fixes start_label + edge_types + direction + depth at registration,
# and exposes only `seed` + `top_k` to the caller. One parametrized body covers
# all six tools — adding a new Layer-B tool is a one-line addition here.
LAYER_B_TRAVERSALS = [
    pytest.param(
        "kg_diet_to_compounds", "Garlic", "Food",
        ("Garlic", "Allicin", "FOUND_IN_FOOD"), "Allicin",
        id="diet_to_compounds-garlic",
    ),
    pytest.param(
        "kg_compound_to_targets", "Curcumin", "Compound",
        ("Curcumin", "NF-kappa-B p65", "TARGETS_PROTEIN"), "NF-kappa-B",
        id="compound_to_targets-curcumin",
    ),
    pytest.param(
        "kg_compound_to_diseases", "Curcumin", "Compound",
        ("Curcumin", "Hepatocellular Carcinoma", "ASSOCIATED_WITH_DISEASE"),
        "Hepatocellular",
        id="compound_to_diseases-curcumin",
    ),
    pytest.param(
        "kg_herb_to_diseases", "Ginger", "Herb",
        ("Ginger", "Nausea", "ASSOCIATED_WITH_DISEASE"), "Nausea",
        id="herb_to_diseases-ginger",
    ),
    pytest.param(
        "kg_herb_to_symptoms", "Ginger", "Herb",
        ("Ginger", "Vomiting", "TREATS_SYMPTOM"), "Vomiting",
        id="herb_to_symptoms-ginger",
    ),
    pytest.param(
        "kg_compound_to_symptoms", "Allicin", "Compound",
        ("Allicin", "Hypertension", "TREATS_SYMPTOM"), "Hypertension",
        id="compound_to_symptoms-allicin",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "seed", "expected_start_label", "edge_triple", "expected_in_payload"),
    LAYER_B_TRAVERSALS,
)
async def test_layer_b_traversal_round_trip(
    tool_name: str,
    seed: str,
    expected_start_label: str,
    edge_triple: tuple[str, str, str],
    expected_in_payload: str,
):
    """Each Layer-B tool: real-world seed → mocked traverse → response payload.

    Asserts uniformly: result deserializes, payload contains the expected
    target name, and the role-prior (start_label) was applied correctly.
    """
    src_id, tgt_id, rel_type = edge_triple
    async with _connected_session_with_mock_backend(
        {
            "traverse": {
                "chains": [
                    {
                        "edges": [
                            {"src_id": src_id, "tgt_id": tgt_id, "rel_type": rel_type}
                        ],
                    }
                ],
                "seeds_resolved": [seed],
            }
        }
    ) as (session, fake_client):
        result = await session.call_tool(
            tool_name, {"seed": seed, "top_k": 5}
        )
        assert not result.isError, _content_payload(result)
        assert expected_in_payload in _content_payload(result)

        kwargs = fake_client.traverse.call_args.kwargs
        assert kwargs["start_label"] == expected_start_label
        assert kwargs["seed"] == seed
        assert kwargs["top_k"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("found", "severity", "mechanism", "tier", "must_contain"),
    [
        pytest.param(
            True, "moderate", "coagulation", "case-report",
            ["moderate", "coagulation"],
            id="found-warfarin-garlic",
        ),
        pytest.param(
            False, None, None, None, ["false"],
            id="not-found-obscure-pair",
        ),
    ],
)
async def test_real_world_hdi_check(
    found: bool,
    severity: str | None,
    mechanism: str | None,
    tier: str | None,
    must_contain: list[str],
):
    """Layer C — HDI-Safe-50 lookup, both panel-hit and panel-miss cases."""
    async with _connected_session_with_mock_backend(
        {
            "hdi_check": {
                "found": found,
                "severity": severity,
                "mechanism_class": mechanism,
                "evidence_tier": tier,
            }
        }
    ) as (session, fake_client):
        result = await session.call_tool(
            "kg_hdi_check", {"drug": "warfarin", "herb": "garlic"}
        )
        assert not result.isError, _content_payload(result)
        payload = _content_payload(result).lower()
        for needle in must_contain:
            assert needle.lower() in payload
        fake_client.hdi_check.assert_awaited_with("warfarin", "garlic")


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
        payload = _content_payload(result)
        assert "Insomnia" in payload
        assert "Shi Mian" in payload
        fake_client.bilingual_term.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_world_node_neighborhood_fallback():
    """Layer C — generic bounded-depth subgraph dump (last-resort fallback)."""
    async with _connected_session_with_mock_backend(
        {
            "graphs": {
                "nodes": [{"id": "Curcumin", "label": "Compound"}],
                "edges": [],
            }
        }
    ) as (session, fake_client):
        result = await session.call_tool(
            "kg_node_neighborhood",
            {"seed": "Curcumin", "max_depth": 1, "max_nodes": 10},
        )
        assert not result.isError, _content_payload(result)
        assert "Curcumin" in _content_payload(result)
        fake_client.graphs.assert_awaited_once()


# ---------------------------------------------------------------------------
# Negative-path tests — input validation flows through MCP transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_unknown_tool_returns_error():
    """An unknown tool name must surface as an error, not silent success.

    FastMCP's low-level handler returns isError=True with a message in
    content rather than raising. We assert only the contract — not the
    specific wording, which would couple to SDK internals.
    """
    async with _connected_session_with_mock_backend({}) as (session, _):
        result = await session.call_tool("nonexistent_tool_xyz", {})
        assert result.isError, "unknown tool must produce isError=True"


@pytest.mark.asyncio
async def test_kg_query_missing_required_arg_validation_error():
    """Pydantic schema requires 'question'; missing it should error cleanly."""
    async with _connected_session_with_mock_backend({}) as (session, _):
        result = await session.call_tool("kg_query", {})
        # FastMCP returns isError=True with the validation message in content
        # rather than raising. Either form is acceptable; we assert the
        # call doesn't silently succeed.
        assert result.isError or "question" in _content_payload(result).lower()
