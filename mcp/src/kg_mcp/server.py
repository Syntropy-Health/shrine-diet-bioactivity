"""MCP server registering the 10 KG tools per the design memo.

The server speaks MCP stdio. Each tool is an async function that:
  1. Validates input via a Pydantic schema (failures bubble back as MCP errors).
  2. Calls scoped_server via the shared ScopedServerClient.
  3. Maps the HTTP response into the tool's output schema.

Layer A is wired end-to-end. Layers B and C call into ScopedServerClient.traverse /
hdi_check / bilingual_term, which gracefully degrade when those endpoints are
not yet on scoped_server (Task #12 follow-up).

Run:
    python -m kg_mcp.server

NOTE (2026-04-29 scaffold phase): the @server.tool() decorator below assumes
a recent MCP SDK API. Some MCP SDK versions use list_tools()/call_tool()
patterns instead. Before running, verify the installed `mcp` version and
adjust the registration pattern if needed. The schema and tool semantics
do not change — only the registration mechanics do.
"""
from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server

from .client import ScopedServerClient
from .schemas import (
    BilingualTermInput,
    BilingualTermOutput,
    HDICheckInput,
    HDICheckOutput,
    KgQueryInput,
    KgQueryOutput,
    NodeNeighborhoodInput,
    NodeNeighborhoodOutput,
    TraversalInput,
    TraversalOutput,
)

# Global client; closed at process shutdown via the stdio_server context manager.
_client: ScopedServerClient | None = None


def _get_client() -> ScopedServerClient:
    global _client
    if _client is None:
        _client = ScopedServerClient()
    return _client


server = Server("kg-mcp")


# ─── Layer A — General Q&A ────────────────────────────────────────────────


@server.tool()
async def kg_query(args: KgQueryInput) -> KgQueryOutput:
    """Natural-language question against the LightRAG KG.

    Default tool. Use this when no role-prior fits the question (open-ended
    exploration, unknown starting node type). For deterministic traversals
    (Compound→Target, Herb→Disease, etc.) prefer the Layer-B tools.
    """
    client = _get_client()
    raw = await client.query(args.question, mode=args.mode, top_k=args.top_k)
    return KgQueryOutput(
        answer=raw.get("response", ""),
        references=raw.get("references", []),
        scope_filter=raw.get("scope_filter", ["shared"]),
    )


# ─── Layer B — Role-priored traversals (deterministic) ────────────────────


def _make_traversal_tool(
    name: str,
    docstring: str,
    start_label: str,
    edge_types: list[str],
    direction: str,
    depth: int,
):
    """Factory: 6 traversal tools share a shape; only (label, edges, depth) differ."""

    @server.tool(name=name)
    async def _impl(args: TraversalInput) -> TraversalOutput:
        client = _get_client()
        raw = await client.traverse(
            start_label=start_label,
            edge_types=edge_types,
            seed=args.seed,
            direction=direction,
            depth=depth,
            top_k=args.top_k,
        )
        # Tolerate both /traverse and /graphs response shapes (graceful fallback).
        chains = raw.get("chains", [])
        nodes = raw.get("nodes", [])
        edges = raw.get("edges", [])
        return TraversalOutput(
            chains=chains,
            seeds_resolved=raw.get("seeds_resolved", []),
            raw_subgraph_node_count=len(nodes) if nodes else raw.get("raw_subgraph_node_count", 0),
            raw_subgraph_edge_count=len(edges) if edges else raw.get("raw_subgraph_edge_count", 0),
        )

    _impl.__doc__ = docstring
    return _impl


kg_diet_to_compounds = _make_traversal_tool(
    name="kg_diet_to_compounds",
    docstring=(
        "Food → bioactives. Seed with a Food name (e.g. 'Garlic'). "
        "Returns Compound chains via FOUND_IN_FOOD / CONTAINS_COMPOUND edges. "
        "Use when the dietitian agent needs to know what's in a food."
    ),
    start_label="Food",
    edge_types=["FOUND_IN_FOOD", "CONTAINS_COMPOUND"],
    direction="bidirectional",
    depth=2,
)

kg_compound_to_targets = _make_traversal_tool(
    name="kg_compound_to_targets",
    docstring=(
        "Compound → Target. Seed with a compound name (e.g. 'Curcumin'). "
        "Returns Target chains via TARGETS_PROTEIN. Pharmacologist's primary tool."
    ),
    start_label="Compound",
    edge_types=["TARGETS_PROTEIN"],
    direction="outbound",
    depth=1,
)

kg_compound_to_diseases = _make_traversal_tool(
    name="kg_compound_to_diseases",
    docstring=(
        "Compound → Target → Disease (depth-2 chain). Pharmacologist's provenance "
        "path for HDI Recall and disease-association claims."
    ),
    start_label="Compound",
    edge_types=["TARGETS_PROTEIN", "ASSOCIATED_WITH_DISEASE"],
    direction="outbound",
    depth=2,
)

kg_herb_to_diseases = _make_traversal_tool(
    name="kg_herb_to_diseases",
    docstring=(
        "Herb → Disease. Seed with a herb name (e.g. 'Astragalus membranaceus'). "
        "Backed by CMAUP plant-disease associations + HERB 2.0 evidence-tiered links."
    ),
    start_label="Herb",
    edge_types=["ASSOCIATED_WITH_DISEASE"],
    direction="outbound",
    depth=1,
)

kg_herb_to_symptoms = _make_traversal_tool(
    name="kg_herb_to_symptoms",
    docstring=(
        "Herb → Symptom. TCM and Dietitian. Seed with herb name; returns symptom "
        "associations via TREATS_SYMPTOM. Backed by Duke bioactivity + SymMap TCM."
    ),
    start_label="Herb",
    edge_types=["TREATS_SYMPTOM"],
    direction="outbound",
    depth=1,
)

kg_compound_to_symptoms = _make_traversal_tool(
    name="kg_compound_to_symptoms",
    docstring=(
        "Compound → Herb → Symptom (composite). When the dietitian asks "
        "'what symptom does this bioactive address?', the path goes through "
        "the herbs containing the compound."
    ),
    start_label="Compound",
    edge_types=["CONTAINS_COMPOUND", "TREATS_SYMPTOM"],
    direction="bidirectional",
    depth=2,
)


# ─── Layer C — Lookup primitives ──────────────────────────────────────────


@server.tool()
async def kg_hdi_check(args: HDICheckInput) -> HDICheckOutput:
    """Direct lookup against the curated HDI-Safe-50 panel.

    Safety reviewer's tool. Returns {severity, mechanism_class, evidence_tier}
    for known drug-herb interactions, or `found=False` otherwise. Deterministic;
    no LLM, no NL similarity.
    """
    client = _get_client()
    raw = await client.hdi_check(args.drug, args.herb)
    return HDICheckOutput(
        found=raw.get("found", False),
        severity=raw.get("severity"),
        mechanism_class=raw.get("mechanism_class"),
        evidence_tier=raw.get("evidence_tier"),
        citations=raw.get("citations", []),
    )


@server.tool()
async def kg_bilingual_term(args: BilingualTermInput) -> BilingualTermOutput:
    """SymMap bilingual canonicalization. Term in any of EN/CN/Pinyin → all three."""
    client = _get_client()
    raw = await client.bilingual_term(args.term, args.languages)
    return BilingualTermOutput(
        english=raw.get("english"),
        chinese=raw.get("chinese"),
        pinyin=raw.get("pinyin"),
        source=raw.get("source", "symmap"),
        confidence=float(raw.get("confidence", 0.0)),
    )


@server.tool()
async def kg_node_neighborhood(args: NodeNeighborhoodInput) -> NodeNeighborhoodOutput:
    """Generic bounded-depth subgraph expansion. Use when no role-prior tool fits."""
    client = _get_client()
    raw = await client.graphs(
        label=args.seed, max_depth=args.max_depth, max_nodes=args.max_nodes
    )
    return NodeNeighborhoodOutput(
        nodes=raw.get("nodes", []),
        edges=raw.get("edges", []),
    )


# ─── Entry point ──────────────────────────────────────────────────────────


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Console-script entry: `python -m kg_mcp.server` or `kg-mcp-server`."""
    try:
        asyncio.run(_run())
    finally:
        if _client is not None:
            asyncio.run(_client.aclose())


if __name__ == "__main__":
    main()
