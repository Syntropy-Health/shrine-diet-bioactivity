"""Server-level tests — verify the 10 tools are registered with FastMCP and
that each tool's exposed schema matches the design memo.

These run without the MCP stdio runtime; they introspect ``server.list_tools()``
which FastMCP populates synchronously when a `@server.tool()`-decorated
function is defined at import time.
"""
from __future__ import annotations

import pytest

from kg_mcp.server import server


EXPECTED_TOOLS = {
    # Layer A
    "kg_query",
    # Layer B (6 role-priored traversals)
    "kg_diet_to_compounds",
    "kg_compound_to_targets",
    "kg_compound_to_diseases",
    "kg_herb_to_diseases",
    "kg_herb_to_symptoms",
    "kg_compound_to_symptoms",
    # Layer C (3 lookup primitives)
    "kg_hdi_check",
    "kg_bilingual_term",
    "kg_node_neighborhood",
}


@pytest.mark.asyncio
async def test_server_name_is_kg_mcp():
    assert server.name == "kg-mcp"


@pytest.mark.asyncio
async def test_all_ten_tools_registered():
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS, (
        f"missing: {EXPECTED_TOOLS - names}, extra: {names - EXPECTED_TOOLS}"
    )


@pytest.mark.asyncio
async def test_each_tool_has_a_description():
    tools = await server.list_tools()
    for t in tools:
        assert t.description, f"{t.name} has no description"


@pytest.mark.asyncio
async def test_kg_query_schema_constrains_mode():
    tools = await server.list_tools()
    kgq = next(t for t in tools if t.name == "kg_query")
    schema = kgq.inputSchema
    mode_spec = schema["properties"]["mode"]
    # FastMCP renders Literal[...] as {"enum": [...]}
    assert "enum" in mode_spec or "default" in mode_spec
    if "enum" in mode_spec:
        assert set(mode_spec["enum"]) == {"mix", "hybrid", "local", "global", "naive"}


@pytest.mark.asyncio
async def test_layer_b_tools_take_seed_and_top_k():
    tools = await server.list_tools()
    layer_b = {
        "kg_diet_to_compounds", "kg_compound_to_targets", "kg_compound_to_diseases",
        "kg_herb_to_diseases", "kg_herb_to_symptoms", "kg_compound_to_symptoms",
    }
    for t in tools:
        if t.name in layer_b:
            props = t.inputSchema["properties"]
            assert "seed" in props, f"{t.name} missing 'seed'"
            assert "top_k" in props, f"{t.name} missing 'top_k'"


@pytest.mark.asyncio
async def test_kg_hdi_check_takes_drug_and_herb():
    tools = await server.list_tools()
    hdi = next(t for t in tools if t.name == "kg_hdi_check")
    props = hdi.inputSchema["properties"]
    assert "drug" in props
    assert "herb" in props


@pytest.mark.asyncio
async def test_kg_node_neighborhood_takes_seed_depth_max_nodes():
    tools = await server.list_tools()
    nn = next(t for t in tools if t.name == "kg_node_neighborhood")
    props = nn.inputSchema["properties"]
    assert "seed" in props
    assert "max_depth" in props
    assert "max_nodes" in props
