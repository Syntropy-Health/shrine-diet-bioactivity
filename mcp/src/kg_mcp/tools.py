"""Pure async tool functions over the LightRAG KG.

Why split from server.py: testing MCP-decorated functions requires running
the MCP SDK, which couples tests to SDK version. These plain async functions
take an injected `client` and a Pydantic input → return a Pydantic output.
server.py registers these as MCP tools; tests exercise them directly.

Each function maps 1:1 to a tool in the design memo §3. Layer-B tools share
a body via _make_traversal — only (start_label, edge_types, direction, depth)
differ.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

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
    ProvenanceChain,
    ProvenanceEdge,
    TraversalInput,
    TraversalOutput,
)


# ─── Layer A — General Q&A ────────────────────────────────────────────────


async def kg_query(client: ScopedServerClient, args: KgQueryInput) -> KgQueryOutput:
    """Natural-language Q&A. Default fallback when no role-prior fits."""
    raw = await client.query(args.question, mode=args.mode, top_k=args.top_k)
    return KgQueryOutput(
        answer=raw.get("response", ""),
        references=list(raw.get("references", [])),
        scope_filter=list(raw.get("scope_filter", ["shared"])),
    )


# ─── Layer B — Role-priored traversals ────────────────────────────────────


def _coerce_chains(raw_chains: list[Any]) -> list[ProvenanceChain]:
    """Tolerate dict-shape and pre-typed chains from /traverse responses."""
    out: list[ProvenanceChain] = []
    for c in raw_chains or []:
        if isinstance(c, ProvenanceChain):
            out.append(c)
            continue
        edges_raw = c.get("edges", []) if isinstance(c, dict) else []
        edges = [ProvenanceEdge(**e) for e in edges_raw if isinstance(e, dict)]
        if edges:
            out.append(ProvenanceChain(edges=edges))
    return out


def _make_traversal(
    start_label: str,
    edge_types: list[str],
    direction: str,
    depth: int,
) -> Callable[[ScopedServerClient, TraversalInput], Awaitable[TraversalOutput]]:
    """Factory: every Layer-B tool shares this body; (label, edges, depth) vary."""

    async def _impl(client: ScopedServerClient, args: TraversalInput) -> TraversalOutput:
        raw = await client.traverse(
            start_label=start_label,
            edge_types=list(edge_types),
            seed=args.seed,
            direction=direction,
            depth=depth,
            top_k=args.top_k,
        )
        # /traverse returns chains; /graphs (fallback) returns nodes+edges.
        chains = _coerce_chains(raw.get("chains", []))
        nodes = raw.get("nodes") or []
        edges = raw.get("edges") or []
        return TraversalOutput(
            chains=chains,
            seeds_resolved=list(raw.get("seeds_resolved", [])),
            raw_subgraph_node_count=(
                len(nodes) if nodes else int(raw.get("raw_subgraph_node_count", 0))
            ),
            raw_subgraph_edge_count=(
                len(edges) if edges else int(raw.get("raw_subgraph_edge_count", 0))
            ),
        )

    return _impl


# Six named Layer-B tools — each is `_make_traversal(...)` with role-correct args.
# Defaults pinned for "continuous optimization" lever (memo §8.4): change here,
# every tool moves together.

kg_diet_to_compounds = _make_traversal(
    start_label="Food",
    edge_types=["FOUND_IN_FOOD", "CONTAINS_COMPOUND"],
    direction="bidirectional",
    depth=2,
)

kg_compound_to_targets = _make_traversal(
    start_label="Compound",
    edge_types=["TARGETS_PROTEIN"],
    direction="outbound",
    depth=1,
)

kg_compound_to_diseases = _make_traversal(
    start_label="Compound",
    edge_types=["TARGETS_PROTEIN", "ASSOCIATED_WITH_DISEASE"],
    direction="outbound",
    depth=2,
)

kg_herb_to_diseases = _make_traversal(
    start_label="Herb",
    edge_types=["ASSOCIATED_WITH_DISEASE"],
    direction="outbound",
    depth=1,
)

kg_herb_to_symptoms = _make_traversal(
    start_label="Herb",
    edge_types=["TREATS_SYMPTOM"],
    direction="outbound",
    depth=1,
)

kg_compound_to_symptoms = _make_traversal(
    start_label="Compound",
    edge_types=["CONTAINS_COMPOUND", "TREATS_SYMPTOM"],
    direction="bidirectional",
    depth=2,
)


# ─── Layer C — Lookup primitives ──────────────────────────────────────────


async def kg_hdi_check(client: ScopedServerClient, args: HDICheckInput) -> HDICheckOutput:
    """Direct lookup against HDI-Safe-50 panel."""
    raw = await client.hdi_check(args.drug, args.herb)
    return HDICheckOutput(
        found=bool(raw.get("found", False)),
        severity=raw.get("severity"),
        mechanism_class=raw.get("mechanism_class"),
        evidence_tier=raw.get("evidence_tier"),
        citations=list(raw.get("citations", [])),
    )


async def kg_bilingual_term(
    client: ScopedServerClient, args: BilingualTermInput
) -> BilingualTermOutput:
    """SymMap canonicalization. Term in any language → all three."""
    raw = await client.bilingual_term(args.term, list(args.languages))
    return BilingualTermOutput(
        english=raw.get("english"),
        chinese=raw.get("chinese"),
        pinyin=raw.get("pinyin"),
        source=str(raw.get("source", "symmap")),
        confidence=float(raw.get("confidence", 0.0)),
    )


async def kg_node_neighborhood(
    client: ScopedServerClient, args: NodeNeighborhoodInput
) -> NodeNeighborhoodOutput:
    """Generic bounded-depth subgraph dump. Last-resort fallback."""
    raw = await client.graphs(
        label=args.seed, max_depth=args.max_depth, max_nodes=args.max_nodes
    )
    return NodeNeighborhoodOutput(
        nodes=list(raw.get("nodes", [])),
        edges=list(raw.get("edges", [])),
    )


__all__ = [
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
]
