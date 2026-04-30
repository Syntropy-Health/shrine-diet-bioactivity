"""Unit tests for the 10 pure tool functions in kg_mcp.tools.

Tools are decoupled from MCP SDK registration so we can test their logic
directly. Each test injects a mocked ScopedServerClient and verifies the
tool's input → schema mapping plus the fixed (start_label, edge_types,
direction, depth) on Layer-B tools.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kg_mcp.schemas import (
    BilingualTermInput,
    HDICheckInput,
    KgQueryInput,
    NodeNeighborhoodInput,
    TraversalInput,
)
from kg_mcp.tools import (
    kg_bilingual_term,
    kg_compound_to_diseases,
    kg_compound_to_symptoms,
    kg_compound_to_targets,
    kg_diet_to_compounds,
    kg_hdi_check,
    kg_herb_to_diseases,
    kg_herb_to_symptoms,
    kg_node_neighborhood,
    kg_query,
)


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.query = AsyncMock()
    c.traverse = AsyncMock()
    c.graphs = AsyncMock()
    c.hdi_check = AsyncMock()
    c.bilingual_term = AsyncMock()
    return c


# ─── Layer A — kg_query ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kg_query_maps_response_to_output(fake_client):
    fake_client.query.return_value = {
        "response": "Ginger reduces nausea.",
        "references": ["Ginger", "Zingiber officinale"],
        "scope_filter": ["shared"],
    }
    out = await kg_query(fake_client, KgQueryInput(question="does ginger help?"))
    assert out.answer == "Ginger reduces nausea."
    assert out.references == ["Ginger", "Zingiber officinale"]
    assert out.scope_filter == ["shared"]


@pytest.mark.asyncio
async def test_kg_query_passes_mode_and_top_k(fake_client):
    fake_client.query.return_value = {"response": ""}
    await kg_query(fake_client, KgQueryInput(question="x", mode="local", top_k=5))
    fake_client.query.assert_awaited_once_with("x", mode="local", top_k=5)


@pytest.mark.asyncio
async def test_kg_query_defaults_mode_to_mix(fake_client):
    fake_client.query.return_value = {"response": ""}
    await kg_query(fake_client, KgQueryInput(question="x"))
    assert fake_client.query.await_args.kwargs["mode"] == "mix"


# ─── Layer B — traversals ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kg_compound_to_targets_uses_correct_label_and_edge(fake_client):
    fake_client.traverse.return_value = {"chains": [], "nodes": [], "edges": []}
    await kg_compound_to_targets(fake_client, TraversalInput(seed="Curcumin"))
    kwargs = fake_client.traverse.await_args.kwargs
    assert kwargs["start_label"] == "Compound"
    assert kwargs["edge_types"] == ["TARGETS_PROTEIN"]
    assert kwargs["direction"] == "outbound"
    assert kwargs["depth"] == 1
    assert kwargs["seed"] == "Curcumin"


@pytest.mark.asyncio
async def test_kg_compound_to_diseases_is_depth_2_chain(fake_client):
    fake_client.traverse.return_value = {"chains": []}
    await kg_compound_to_diseases(fake_client, TraversalInput(seed="Aspirin"))
    kwargs = fake_client.traverse.await_args.kwargs
    assert kwargs["edge_types"] == ["TARGETS_PROTEIN", "ASSOCIATED_WITH_DISEASE"]
    assert kwargs["depth"] == 2


@pytest.mark.asyncio
async def test_kg_diet_to_compounds_starts_from_food(fake_client):
    fake_client.traverse.return_value = {"chains": []}
    await kg_diet_to_compounds(fake_client, TraversalInput(seed="Garlic"))
    kwargs = fake_client.traverse.await_args.kwargs
    assert kwargs["start_label"] == "Food"
    assert "FOUND_IN_FOOD" in kwargs["edge_types"]
    assert "CONTAINS_COMPOUND" in kwargs["edge_types"]


@pytest.mark.asyncio
async def test_kg_herb_to_diseases_starts_from_herb(fake_client):
    fake_client.traverse.return_value = {"chains": []}
    await kg_herb_to_diseases(fake_client, TraversalInput(seed="Astragalus"))
    kwargs = fake_client.traverse.await_args.kwargs
    assert kwargs["start_label"] == "Herb"
    assert kwargs["edge_types"] == ["ASSOCIATED_WITH_DISEASE"]


@pytest.mark.asyncio
async def test_kg_herb_to_symptoms_uses_treats_symptom(fake_client):
    fake_client.traverse.return_value = {"chains": []}
    await kg_herb_to_symptoms(fake_client, TraversalInput(seed="Ginger"))
    kwargs = fake_client.traverse.await_args.kwargs
    assert kwargs["start_label"] == "Herb"
    assert kwargs["edge_types"] == ["TREATS_SYMPTOM"]


@pytest.mark.asyncio
async def test_kg_compound_to_symptoms_is_composite(fake_client):
    fake_client.traverse.return_value = {"chains": []}
    await kg_compound_to_symptoms(fake_client, TraversalInput(seed="Curcumin"))
    kwargs = fake_client.traverse.await_args.kwargs
    assert kwargs["edge_types"] == ["CONTAINS_COMPOUND", "TREATS_SYMPTOM"]
    assert kwargs["depth"] == 2


@pytest.mark.asyncio
async def test_traversal_coerces_chains_response_shape(fake_client):
    fake_client.traverse.return_value = {
        "chains": [
            {"edges": [{"src_id": "A", "tgt_id": "B", "rel_type": "X"}]},
            {"edges": []},  # empty chain — filtered
        ],
        "seeds_resolved": ["A"],
    }
    out = await kg_compound_to_targets(fake_client, TraversalInput(seed="A"))
    assert len(out.chains) == 1
    assert out.chains[0].edges[0].src_id == "A"
    assert out.seeds_resolved == ["A"]


@pytest.mark.asyncio
async def test_traversal_falls_back_to_node_count_from_graphs_shape(fake_client):
    """When /traverse falls back to /graphs, response has nodes/edges, not chains."""
    fake_client.traverse.return_value = {
        "nodes": [{"id": 1}, {"id": 2}],
        "edges": [{"src": 1, "tgt": 2}],
    }
    out = await kg_compound_to_targets(fake_client, TraversalInput(seed="X"))
    assert out.raw_subgraph_node_count == 2
    assert out.raw_subgraph_edge_count == 1
    assert out.chains == []


# ─── Layer C — lookup primitives ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_kg_hdi_check_passes_through(fake_client):
    fake_client.hdi_check.return_value = {
        "found": True,
        "severity": "moderate",
        "mechanism_class": "CYP450",
        "evidence_tier": "clinical",
        "citations": ["hdi-safe-50:warfarin-ginkgo"],
    }
    out = await kg_hdi_check(
        fake_client, HDICheckInput(drug="warfarin", herb="Ginkgo"),
    )
    assert out.found is True
    assert out.severity == "moderate"
    assert out.mechanism_class == "CYP450"
    assert out.citations == ["hdi-safe-50:warfarin-ginkgo"]


@pytest.mark.asyncio
async def test_kg_hdi_check_returns_not_found_when_endpoint_empty(fake_client):
    fake_client.hdi_check.return_value = {"found": False}
    out = await kg_hdi_check(
        fake_client, HDICheckInput(drug="x", herb="y"),
    )
    assert out.found is False
    assert out.severity is None


@pytest.mark.asyncio
async def test_kg_bilingual_term_passes_through(fake_client):
    fake_client.bilingual_term.return_value = {
        "english": "Coptis chinensis",
        "chinese": "黄连",
        "pinyin": "huang lian",
        "source": "symmap",
        "confidence": 0.92,
    }
    out = await kg_bilingual_term(fake_client, BilingualTermInput(term="黄连"))
    assert out.chinese == "黄连"
    assert out.english == "Coptis chinensis"
    assert out.pinyin == "huang lian"
    assert out.confidence == 0.92


@pytest.mark.asyncio
async def test_kg_bilingual_term_handles_empty(fake_client):
    fake_client.bilingual_term.return_value = {}
    out = await kg_bilingual_term(fake_client, BilingualTermInput(term="unknown"))
    assert out.english is None
    assert out.chinese is None
    assert out.pinyin is None


@pytest.mark.asyncio
async def test_kg_node_neighborhood_calls_graphs(fake_client):
    fake_client.graphs.return_value = {
        "nodes": [{"id": "Curcumin"}],
        "edges": [{"src": "Curcumin", "tgt": "X"}],
    }
    out = await kg_node_neighborhood(
        fake_client, NodeNeighborhoodInput(seed="Curcumin", max_depth=3, max_nodes=50),
    )
    fake_client.graphs.assert_awaited_once_with(
        label="Curcumin", max_depth=3, max_nodes=50,
    )
    assert len(out.nodes) == 1
    assert len(out.edges) == 1
