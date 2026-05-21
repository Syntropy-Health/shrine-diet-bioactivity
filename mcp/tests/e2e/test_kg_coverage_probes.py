"""Phase 5 — KG coverage probes (Category E).

Plan ref: research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md
tests #19-25.

Seven probes asserting that key entities resolve through the live MCP
gateway against the indexed `unified_diet_kg` Aura workspace. Where Phase 2
(`test_tool_roundtrips.py`) checks that each tool returns a well-shaped
response, these probes check that specific, real entities are actually
PRESENT in the graph — they catch upstream-KG drift (a re-ingest that
silently drops Curcumin, a bilingual alias that stops resolving, an HDI
panel that loses coverage).

Skipped without `KG_MCP_E2E_URL` + `KG_MCP_API_KEY` (gated by conftest
fixtures). Marked `e2e + aura`.

Assertion discipline: probes assert on STRUCTURED payload fields (node /
edge / chain / seeds_resolved COUNTS, the `english` field of a bilingual
result), never on substring search of the JSON dump. A JSON dump contains
schema field names (`"nodes"`, `"edges"`, ...) unconditionally — so
`"edge" in json_text` is true even for a zero-edge response and would
make a drift-detection probe unable to detect drift. Schemas:
`mcp/src/kg_mcp/schemas.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._braintrust_logger import bt_span

pytestmark = [pytest.mark.e2e, pytest.mark.aura]

# research-journal/shared/hdi_safe_50.json — 50 curated herb-drug pairs.
# test file: mcp/tests/e2e/test_kg_coverage_probes.py → parents[3] = repo root
_HDI_SAFE_50_PATH = (
    Path(__file__).resolve().parents[3]
    / "research-journal"
    / "shared"
    / "hdi_safe_50.json"
)


def _is_error(result: dict) -> bool:
    """True if the JSON-RPC envelope carries an error."""
    return "error" in result and result.get("error") is not None


def _payload(result: dict) -> dict:
    """The tool result payload (the structured tool output)."""
    payload = result.get("result", {})
    return payload if isinstance(payload, dict) else {}


# ─── Probe 19: Curcumin → Compound node ──────────────────────────────────


def test_curcumin_resolves_to_compound_node(mcp_call):
    """'Curcumin' resolves to >= 1 node in its 1-hop neighborhood, and at
    least one resolved node carries a compound-identity marker."""
    inputs = {"seed": "Curcumin", "max_depth": 1, "max_nodes": 20}
    with bt_span(
        "test_curcumin_resolves_to_compound_node",
        tool="kg_node_neighborhood",
        **inputs,
    ) as span:
        result = mcp_call("kg_node_neighborhood", inputs)
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        nodes = _payload(result).get("nodes", [])
        span.log(output={"node_count": len(nodes)})
        # Hard check: a re-ingest that drops Curcumin yields 0 nodes.
        assert len(nodes) >= 1, (
            f"Curcumin resolved to 0 nodes — not present in the KG"
        )
        # Identity check on the node DICTS (not the full payload, so the
        # schema's `"edges"`/`"nodes"` keys can't leak into the match).
        node_blob = json.dumps(nodes).lower()
        assert any(
            k in node_blob for k in ("curcumin", "compound", "chebi", "inchikey")
        ), f"Curcumin nodes carry no compound-identity marker: {node_blob[:300]}"


# ─── Probe 20: Type 2 diabetes → Disease node ────────────────────────────


def test_t2d_resolves_to_disease_node(mcp_call):
    """'Type 2 diabetes' resolves to >= 1 node, with a disease-identity
    marker on the resolved nodes."""
    inputs = {"seed": "Type 2 diabetes", "max_depth": 1, "max_nodes": 20}
    with bt_span(
        "test_t2d_resolves_to_disease_node",
        tool="kg_node_neighborhood",
        **inputs,
    ) as span:
        result = mcp_call("kg_node_neighborhood", inputs)
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        nodes = _payload(result).get("nodes", [])
        span.log(output={"node_count": len(nodes)})
        assert len(nodes) >= 1, (
            "Type 2 diabetes resolved to 0 nodes — not present in the KG"
        )
        node_blob = json.dumps(nodes).lower()
        assert any(
            k in node_blob for k in ("diabetes", "disease", "t2d")
        ), f"T2D nodes carry no disease-identity marker: {node_blob[:300]}"


# ─── Probe 21: Mediterranean diet resolvable ─────────────────────────────


def test_mediterranean_diet_resolvable(mcp_call):
    """'Mediterranean diet' is a resolvable dietary pattern — the diet→
    compounds traversal resolves the seed (seeds_resolved is non-empty)."""
    inputs = {"seed": "Mediterranean diet", "top_k": 5}
    with bt_span(
        "test_mediterranean_diet_resolvable",
        tool="kg_diet_to_compounds",
        **inputs,
    ) as span:
        result = mcp_call("kg_diet_to_compounds", inputs)
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        payload = _payload(result)
        seeds_resolved = payload.get("seeds_resolved", [])
        chains = payload.get("chains", [])
        node_count = payload.get("raw_subgraph_node_count", 0)
        span.log(
            output={
                "seeds_resolved": len(seeds_resolved),
                "chains": len(chains),
                "raw_subgraph_node_count": node_count,
            }
        )
        # A resolved diet seed lands in seeds_resolved; an unresolved
        # free-text seed leaves it empty. Fall back to subgraph evidence.
        assert seeds_resolved or chains or node_count >= 1, (
            "Mediterranean diet did not resolve — seeds_resolved empty, "
            f"no chains, subgraph node count {node_count}"
        )


# ─── Probe 22: St John's Wort bilingual aliasing ─────────────────────────


def test_sjw_bilingual_aliasing(mcp_call):
    """'St John's Wort' resolves through the bilingual-term resolver to a
    non-empty canonical `english` name."""
    inputs = {"term": "St John's Wort"}
    with bt_span(
        "test_sjw_bilingual_aliasing", tool="kg_bilingual_term", **inputs
    ) as span:
        result = mcp_call("kg_bilingual_term", inputs)
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        payload = _payload(result)
        english = (payload.get("english") or "").strip()
        span.log(output={"english": english, "source": payload.get("source")})
        assert english, (
            f"St John's Wort did not resolve to a canonical english name; "
            f"payload={payload}"
        )


# ─── Probe 23: Astragalus trilingual aliasing ────────────────────────────


def test_huangqi_trilingual_aliasing(mcp_call):
    """'Astragalus membranaceus' / '黄芪' / 'huangqi' resolve to the SAME
    canonical entity — the bilingual resolver's `english` field is
    identical across all three surface forms.

    This is the actual aliasing property: three independent lookups must
    converge on one entity, not merely each echo their own input.
    """
    surface_forms = ["Astragalus membranaceus", "黄芪", "huangqi"]
    canonical: dict[str, str] = {}
    for term in surface_forms:
        with bt_span(
            "test_huangqi_trilingual_aliasing",
            tool="kg_bilingual_term",
            term=term,
        ) as span:
            result = mcp_call("kg_bilingual_term", {"term": term})
            assert not _is_error(result), (
                f"gateway error for {term!r}: {result.get('error')}"
            )
            payload = _payload(result)
            english = (payload.get("english") or "").strip().lower()
            span.log(output={"term": term, "english": english})
            assert english, (
                f"surface form {term!r} resolved to an empty english name; "
                f"payload={payload}"
            )
            canonical[term] = english

    distinct = set(canonical.values())
    assert len(distinct) == 1, (
        "trilingual surface forms resolved to DIFFERENT canonical entities — "
        f"aliasing is broken: {canonical}"
    )


# ─── Probe 24: HDI-Safe-50 panel coverage ────────────────────────────────


@pytest.mark.slow
def test_hdi_safe_50_panel_coverage(mcp_call):
    """At least 45 of the 50 curated HDI-Safe-50 herb-drug pairs are
    queryable via kg_hdi_check without a gateway error."""
    if not _HDI_SAFE_50_PATH.is_file():
        pytest.skip(f"HDI-Safe-50 fixture not present: {_HDI_SAFE_50_PATH}")

    panel = json.loads(_HDI_SAFE_50_PATH.read_text(encoding="utf-8"))
    assert len(panel) == 50, f"expected 50 HDI pairs, got {len(panel)}"

    queryable = 0
    failures: list[str] = []
    for entry in panel:
        herb = entry["herb"]["name"]
        drug = entry["drug"]["name"]
        try:
            result = mcp_call("kg_hdi_check", {"herb": herb, "drug": drug})
        except Exception as exc:  # noqa: BLE001 — any transport failure = not queryable
            failures.append(f"{entry['id']} ({herb} x {drug}): {exc}")
            continue
        if _is_error(result):
            failures.append(
                f"{entry['id']} ({herb} x {drug}): {result.get('error')}"
            )
            continue
        queryable += 1

    with bt_span("test_hdi_safe_50_panel_coverage", tool="kg_hdi_check") as span:
        span.log(output={"queryable": queryable, "total": len(panel)})

    assert queryable >= 45, (
        f"only {queryable}/50 HDI-Safe-50 pairs were queryable "
        f"(need >= 45). First failures:\n  " + "\n  ".join(failures[:10])
    )


# ─── Probe 25: Herb node edge-density sanity ─────────────────────────────


def test_herb_node_has_edges(mcp_call):
    """A known Herb node returns at least one EDGE — a herb with zero edges
    indicates a broken or partial ingest.

    Asserts on len(edges), not substring presence of the literal key
    `"edges"` (which a NodeNeighborhoodOutput carries even when empty).
    """
    inputs = {"seed": "Astragalus membranaceus", "max_depth": 1, "max_nodes": 25}
    with bt_span(
        "test_herb_node_has_edges", tool="kg_node_neighborhood", **inputs
    ) as span:
        result = mcp_call("kg_node_neighborhood", inputs)
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        payload = _payload(result)
        node_count = len(payload.get("nodes", []))
        edge_count = len(payload.get("edges", []))
        span.log(output={"node_count": node_count, "edge_count": edge_count})
        assert edge_count >= 1, (
            "Astragalus herb node returned 0 edges — possible partial "
            f"ingest (node_count={node_count})"
        )
