"""E2E acceptance for the tiered evidence read path — kg_compound_evidence
(shrine-diet #108).

evidence_tier + source_id live ONLY on the HAS_EVIDENCE / EVIDENCE_FOR_TARGET
edges (chain: Compound -HAS_EVIDENCE-> BioactivityEvidence -EVIDENCE_FOR_TARGET->
Target). The compound->target tools traverse untiered TARGETS_PROTEIN edges — so
before #108 the tier had NO wire read path (that is the #233(a) contradiction).
These tests exercise the new tool end-to-end through the deployed gateway and are
the #108 acceptance: a known-tiered seed must come back tiered, EMPTY -> FAIL.

Gating: skips cleanly unless KG_MCP_E2E_URL + KG_MCP_API_KEY are set (the
``mcp_call`` fixture handles the skip). Seed ``1,4-NAPHTHOQUINONE`` is a Compound
with a HAS_EVIDENCE edge verified in Aura (2026-09-14).
"""
from __future__ import annotations

import pytest

from ._helpers import _extract_chains, _is_error, _payload

pytestmark = [pytest.mark.e2e]

# A Compound with a HAS_EVIDENCE edge in the workspace (Aura, 2026-09-14).
KNOWN_TIERED_SEED = "1,4-NAPHTHOQUINONE"
EVIDENCE_REL_TYPES = {"HAS_EVIDENCE", "EVIDENCE_FOR_TARGET"}


def _edges(result: dict) -> list:
    return [e for c in _extract_chains(result) for e in (c.get("edges") or [])]


def test_kg_compound_evidence_returns_chains(mcp_call):
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 25})
    assert not _is_error(result["result"]), result
    assert len(_extract_chains(result)) >= 1, f"expected >=1 chain: {result}"


def test_kg_compound_evidence_not_error_for_known_seed(mcp_call):
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 5})
    assert not _is_error(result["result"]), f"tool errored: {result}"


def test_kg_compound_evidence_edges_carry_evidence_tier(mcp_call):
    # THE #108 acceptance: the tiered edges surface a non-empty tier on the wire.
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 25})
    edges = _edges(result)
    assert edges, f"no edges: {result}"
    tiered = [e for e in edges if (e.get("evidence_tier") or "") != ""]
    assert tiered, f"EMPTY -> FAIL: no edge carried evidence_tier: {edges[:3]}"


def test_kg_compound_evidence_tier_values_are_nonempty_strings(mcp_call):
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 25})
    for e in _edges(result):
        t = e.get("evidence_tier")
        if t not in (None, ""):
            assert isinstance(t, str) and t.strip(), f"malformed tier: {t!r}"


def test_kg_compound_evidence_edges_carry_source_id(mcp_call):
    # Provenance: a tiered row must also carry a citation.
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 25})
    edges = _edges(result)
    assert edges, f"no edges: {result}"
    assert any((e.get("source_id") or "") != "" for e in edges), f"no source_id: {edges[:3]}"


def test_kg_compound_evidence_is_depth_2_chain(mcp_call):
    # Compound -HAS_EVIDENCE-> BioactivityEvidence -EVIDENCE_FOR_TARGET-> Target.
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 25})
    chains = _extract_chains(result)
    assert chains, f"no chains: {result}"
    assert any(len(c.get("edges") or []) == 2 for c in chains), \
        f"expected a 2-edge chain: {chains[:2]}"


def test_kg_compound_evidence_rel_types_are_the_evidence_layer(mcp_call):
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 25})
    rels = {e.get("rel_type") for e in _edges(result) if e.get("rel_type")}
    assert rels, f"no rel_types: {result}"
    assert rels <= EVIDENCE_REL_TYPES, f"unexpected rel_types: {rels - EVIDENCE_REL_TYPES}"


def test_kg_compound_evidence_first_edge_is_has_evidence(mcp_call):
    result = mcp_call("kg_compound_evidence", {"seed": KNOWN_TIERED_SEED, "top_k": 25})
    for c in _extract_chains(result):
        edges = c.get("edges") or []
        if edges:
            assert edges[0].get("rel_type") == "HAS_EVIDENCE", edges[0]
            break


def test_kg_compound_evidence_unknown_seed_is_empty_not_error(mcp_call):
    # Honest empty: a nonsense seed returns 0 chains, not an error.
    result = mcp_call("kg_compound_evidence", {"seed": "__no_such_compound_zzz__", "top_k": 5})
    assert not _is_error(result["result"]), f"unknown seed errored: {result}"
    assert _extract_chains(result) == [], f"expected no chains: {result}"


def test_kg_compound_to_targets_path_is_untiered_contrast(mcp_call):
    # Documents #233(a) on the wire: the compound->target path traverses the
    # untiered TARGETS_PROTEIN edges — evidence_tier is empty there. This is why
    # a separate evidence tool is needed; if this path ever starts carrying a
    # tier, the assumption behind #108 has changed and the panel design must be
    # revisited.
    result = mcp_call("kg_compound_to_targets", {"seed": "curcumin", "top_k": 25})
    if _is_error(result["result"]) or not _extract_chains(result):
        pytest.skip("kg_compound_to_targets returned no data for the seed")
    edges = _edges(result)
    assert all((e.get("evidence_tier") or "") == "" for e in edges), \
        f"untiered path unexpectedly carried a tier: {[e.get('evidence_tier') for e in edges][:5]}"
