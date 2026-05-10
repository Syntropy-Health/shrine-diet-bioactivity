"""Coverage for the analytics-instrumented error paths in kg_mcp.tools.

The happy paths are exercised by ``test_tools.py``.  These tests verify that
when the underlying client raises, each tool:

  1. emits a ``kg_tool_error`` event with ``tool_name`` + ``error_type``;
  2. calls ``capture_exception`` on the analytics layer;
  3. re-raises the original exception (does not swallow).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kg_mcp import analytics, tools
from kg_mcp.schemas import (
    BilingualTermInput,
    HDICheckInput,
    KgQueryInput,
    NodeNeighborhoodInput,
    ProvenanceChain,
    ProvenanceEdge,
    TraversalInput,
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


@pytest.fixture
def captured(monkeypatch):
    """Replace analytics.capture / capture_exception with spies."""
    capture_spy = MagicMock()
    capture_exc_spy = MagicMock()
    monkeypatch.setattr(analytics, "capture", capture_spy)
    monkeypatch.setattr(analytics, "capture_exception", capture_exc_spy)
    return capture_spy, capture_exc_spy


# ─── kg_query error path (lines 57-60) ────────────────────────────────────


@pytest.mark.asyncio
async def test_kg_query_error_path_records_and_reraises(fake_client, captured):
    capture_spy, capture_exc_spy = captured
    fake_client.query.side_effect = RuntimeError("upstream-down")
    with pytest.raises(RuntimeError, match="upstream-down"):
        await tools.kg_query(fake_client, KgQueryInput(question="x"))
    # First call: kg_tool_error event with metadata.
    assert capture_spy.call_count == 1
    args, kwargs = capture_spy.call_args
    assert args[1] == "kg_tool_error"
    assert args[2]["tool_name"] == "kg_query"
    assert args[2]["error_type"] == "RuntimeError"
    capture_exc_spy.assert_called_once()


# ─── _make_traversal error path (lines 126-129) ───────────────────────────


@pytest.mark.asyncio
async def test_traversal_error_path_records_and_reraises(fake_client, captured):
    capture_spy, capture_exc_spy = captured
    fake_client.traverse.side_effect = ValueError("bad-seed")
    with pytest.raises(ValueError, match="bad-seed"):
        await tools.kg_compound_to_targets(
            fake_client, TraversalInput(seed="missing"),
        )
    assert capture_spy.call_count == 1
    args, _ = capture_spy.call_args
    assert args[1] == "kg_tool_error"
    assert args[2]["tool_name"] == "kg_traversal_compound"
    assert args[2]["error_type"] == "ValueError"
    capture_exc_spy.assert_called_once()


# ─── kg_hdi_check error path (lines 206-209) ──────────────────────────────


@pytest.mark.asyncio
async def test_kg_hdi_check_error_path_records_and_reraises(fake_client, captured):
    capture_spy, capture_exc_spy = captured
    fake_client.hdi_check.side_effect = TimeoutError("slow")
    with pytest.raises(TimeoutError):
        await tools.kg_hdi_check(
            fake_client, HDICheckInput(drug="warfarin", herb="ginkgo"),
        )
    args, _ = capture_spy.call_args
    assert args[2]["tool_name"] == "kg_hdi_check"
    assert args[2]["error_type"] == "TimeoutError"
    capture_exc_spy.assert_called_once()


# ─── kg_bilingual_term error path (lines 237-240) ─────────────────────────


@pytest.mark.asyncio
async def test_kg_bilingual_term_error_path_records_and_reraises(
    fake_client, captured,
):
    capture_spy, capture_exc_spy = captured
    fake_client.bilingual_term.side_effect = KeyError("missing-lang")
    with pytest.raises(KeyError):
        await tools.kg_bilingual_term(
            fake_client, BilingualTermInput(term="黄连"),
        )
    args, _ = capture_spy.call_args
    assert args[2]["tool_name"] == "kg_bilingual_term"
    assert args[2]["error_type"] == "KeyError"
    capture_exc_spy.assert_called_once()


# ─── kg_node_neighborhood error path (lines 266-269) ──────────────────────


@pytest.mark.asyncio
async def test_kg_node_neighborhood_error_path_records_and_reraises(
    fake_client, captured,
):
    capture_spy, capture_exc_spy = captured
    fake_client.graphs.side_effect = ConnectionError("net-out")
    with pytest.raises(ConnectionError):
        await tools.kg_node_neighborhood(
            fake_client,
            NodeNeighborhoodInput(seed="Curcumin", max_depth=2, max_nodes=10),
        )
    args, _ = capture_spy.call_args
    assert args[2]["tool_name"] == "kg_node_neighborhood"
    assert args[2]["error_type"] == "ConnectionError"
    capture_exc_spy.assert_called_once()


# ─── _coerce_chains pre-typed branch (lines 70-72) ────────────────────────


@pytest.mark.asyncio
async def test_traversal_accepts_pre_typed_chain_objects(fake_client):
    """A ProvenanceChain in the upstream payload is forwarded as-is."""
    pre_typed = ProvenanceChain(
        edges=[ProvenanceEdge(src_id="A", tgt_id="B", rel_type="X")],
    )
    fake_client.traverse.return_value = {"chains": [pre_typed]}
    out = await tools.kg_compound_to_targets(
        fake_client, TraversalInput(seed="A"),
    )
    assert len(out.chains) == 1
    assert out.chains[0].edges[0].src_id == "A"
