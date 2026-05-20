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

Response-shape note: the gateway's exact payload schema is verified
against the live deployment; assertions here are intentionally tolerant
of shape (substring / key presence on the JSON-serialized payload), the
same convention `test_tool_roundtrips.py` uses.
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


def _payload_text(result: dict) -> str:
    """Lower-cased JSON dump of the tool result payload, for tolerant
    substring assertions (mirrors test_tool_roundtrips.py)."""
    return json.dumps(result.get("result", {})).lower()


def _is_error(result: dict) -> bool:
    """True if the JSON-RPC envelope carries an error."""
    return "error" in result and result.get("error") is not None


# ─── Probe 19: Curcumin → Compound node ──────────────────────────────────


def test_curcumin_resolves_to_compound_node(mcp_call):
    """'Curcumin' resolves to a Compound node carrying a chemical identity
    (CHEBI / InChIKey / compound type marker)."""
    inputs = {"seed": "Curcumin", "max_depth": 1, "max_nodes": 20}
    with bt_span(
        "test_curcumin_resolves_to_compound_node",
        tool="kg_node_neighborhood",
        **inputs,
    ) as span:
        result = mcp_call("kg_node_neighborhood", inputs)
        text = _payload_text(result)
        span.log(output={"payload_text_excerpt": text[:300]})
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        # verify against live gateway: a Compound node should surface either
        # a type marker or a chemical-identity property.
        assert any(
            k in text for k in ("compound", "chebi", "inchikey", "curcumin")
        ), f"Curcumin did not resolve to a compound-shaped node: {text[:300]}"


# ─── Probe 20: Type 2 diabetes → Disease node ────────────────────────────


def test_t2d_resolves_to_disease_node(mcp_call):
    """'Type 2 diabetes' resolves to a Disease node."""
    inputs = {"seed": "Type 2 diabetes", "max_depth": 1, "max_nodes": 20}
    with bt_span(
        "test_t2d_resolves_to_disease_node",
        tool="kg_node_neighborhood",
        **inputs,
    ) as span:
        result = mcp_call("kg_node_neighborhood", inputs)
        text = _payload_text(result)
        span.log(output={"payload_text_excerpt": text[:300]})
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        assert any(
            k in text for k in ("disease", "diabetes", "t2d")
        ), f"Type 2 diabetes did not resolve to a disease node: {text[:300]}"


# ─── Probe 21: Mediterranean diet resolvable ─────────────────────────────


def test_mediterranean_diet_resolvable(mcp_call):
    """'Mediterranean diet' is a resolvable dietary pattern — diet→compounds
    traversal returns a non-trivial result."""
    inputs = {"seed": "Mediterranean diet", "top_k": 5}
    with bt_span(
        "test_mediterranean_diet_resolvable",
        tool="kg_diet_to_compounds",
        **inputs,
    ) as span:
        result = mcp_call("kg_diet_to_compounds", inputs)
        text = _payload_text(result)
        span.log(output={"payload_text_excerpt": text[:300]})
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        # A resolved diet pattern returns compounds/chains; an unresolved
        # seed returns an empty/zero-result payload.
        assert any(
            k in text for k in ("compound", "chain", "entity_id", "mediterranean")
        ), f"Mediterranean diet did not resolve: {text[:300]}"


# ─── Probe 22: St John's Wort bilingual aliasing ─────────────────────────


def test_sjw_bilingual_aliasing(mcp_call):
    """'St John's Wort' resolves to its Herb node (Hypericum perforatum)
    via the bilingual-term resolver."""
    inputs = {"term": "St John's Wort"}
    with bt_span(
        "test_sjw_bilingual_aliasing", tool="kg_bilingual_term", **inputs
    ) as span:
        result = mcp_call("kg_bilingual_term", inputs)
        text = _payload_text(result)
        span.log(output={"payload_text_excerpt": text[:300]})
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        assert any(
            k in text for k in ("hypericum", "st john", "st. john", "perforatum")
        ), f"St John's Wort did not resolve to its herb node: {text[:300]}"


# ─── Probe 23: Astragalus trilingual aliasing ────────────────────────────


def test_huangqi_trilingual_aliasing(mcp_call):
    """'Astragalus membranaceus' / '黄芪' / 'huangqi' all resolve, and each
    response references the shared canonical entity (Astragalus)."""
    surface_forms = ["Astragalus membranaceus", "黄芪", "huangqi"]
    resolved: dict[str, str] = {}
    for term in surface_forms:
        inputs = {"term": term}
        with bt_span(
            "test_huangqi_trilingual_aliasing",
            tool="kg_bilingual_term",
            term=term,
        ) as span:
            result = mcp_call("kg_bilingual_term", inputs)
            text = _payload_text(result)
            span.log(output={"term": term, "payload_text_excerpt": text[:300]})
            assert not _is_error(result), (
                f"gateway error for {term!r}: {result.get('error')}"
            )
            resolved[term] = text

    # All three surface forms should resolve to the same canonical herb —
    # use 'astragalus' / 'huangqi' as the shared-identity proxy.
    for term, text in resolved.items():
        assert any(k in text for k in ("astragalus", "huangqi", "黄芪")), (
            f"surface form {term!r} did not resolve to the shared "
            f"Astragalus entity: {text[:300]}"
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
        inputs = {"herb": herb, "drug": drug}
        try:
            result = mcp_call("kg_hdi_check", inputs)
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
    """A known Herb node returns at least one edge — a herb with zero edges
    indicates a broken or partial ingest."""
    inputs = {"seed": "Astragalus membranaceus", "max_depth": 1, "max_nodes": 25}
    with bt_span(
        "test_herb_node_has_edges", tool="kg_node_neighborhood", **inputs
    ) as span:
        result = mcp_call("kg_node_neighborhood", inputs)
        payload = result.get("result", {})
        text = json.dumps(payload).lower()
        span.log(output={"payload_text_excerpt": text[:300]})
        assert not _is_error(result), f"gateway error: {result.get('error')}"
        # verify against live gateway: the neighborhood payload should carry
        # at least one edge/relationship for a herb that is genuinely indexed.
        assert any(k in text for k in ("edge", "interacts", "contains", "rel")), (
            f"Astragalus herb node returned no edges — possible partial "
            f"ingest: {text[:300]}"
        )
