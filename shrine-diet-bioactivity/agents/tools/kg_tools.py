"""Typed Python wrappers for the 10 staged-MCP-gateway tools.

Each wrapper accepts primitive args (str, int) and returns a Pydantic
model that mirrors the MCP tool's output schema. The wrapper layer
adds:
  - Per-entity-type seed normalization (compound → UPPERCASE etc.) per
    `research-journal/shared/staged-mcp-probe.md`.
  - Single retry-on-MCPError for transient transport failures.
  - Friendly defaults — agents pass top_k=20 by default.

Usage from a panel agent (registered via AG2 register_for_llm):

    from agents.tools.kg_tools import (
        kg_compound_to_targets, kg_hdi_check, kg_bilingual_term,
    )

    result = kg_compound_to_targets(seed="curcumin", top_k=10)
    # → TraversalOutput(chains=[...], seeds_resolved=['CURCUMIN'], ...)

The 10 tools:
  Layer A — kg_query
  Layer B — kg_diet_to_compounds, kg_compound_to_targets,
            kg_compound_to_diseases, kg_herb_to_diseases,
            kg_herb_to_symptoms, kg_compound_to_symptoms
  Layer C — kg_hdi_check, kg_bilingual_term, kg_node_neighborhood
"""
# NOTE: this module deliberately does NOT use `from __future__ import annotations`.
# AG2's register_for_llm inspects function signatures via inject_params; with
# stringified annotations the inspection fails to resolve generic parameter
# types (TypeAdapter on ForwardRef). Plain Python 3.10 PEP-604 unions
# (`X | None`) work natively without the future import.

import logging
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agents.tools.mcp_client import MCPError, default_client

_log = logging.getLogger(__name__)


# ---- MCP-shape output models (mirror tools/list inputSchema) --------------
#
# Renamed from ProvenanceEdge/ProvenanceChain to MCPEdge/MCPChain per code
# review I1 — eliminates the name-shadowing risk with `agents.models`'s
# `ProvenanceChain` (which is the local synthesis-layer model with different
# field names: src/edge/tgt/weight vs MCP's src_id/tgt_id/rel_type).

class MCPEdge(BaseModel):
    src_id: str
    tgt_id: str
    rel_type: str
    description: str | None = None
    evidence_tier: str | None = None
    source_id: str | None = None


class MCPChain(BaseModel):
    edges: list[MCPEdge]


# Back-compat aliases — kept for one minor version so any in-flight code
# importing the old names still works. Remove after the next release.
ProvenanceEdge = MCPEdge
ProvenanceChain = MCPChain


class TraversalOutput(BaseModel):
    chains: list[MCPChain] = Field(default_factory=list)
    seeds_resolved: list[str] = Field(default_factory=list)
    raw_subgraph_node_count: int = 0
    raw_subgraph_edge_count: int = 0


class KgQueryOutput(BaseModel):
    answer: str = ""
    references: list[str] = Field(default_factory=list)
    scope_filter: list[str] = Field(default_factory=list)


class HDICheckOutput(BaseModel):
    found: bool
    severity: Literal["mild", "moderate", "severe"] | None = None
    mechanism_class: Literal[
        "CYP450", "P-gp", "PD-antagonism", "coagulation", "serotonergic"
    ] | None = None
    evidence_tier: str | None = None
    citations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_severity_when_found(self) -> "HDICheckOutput":
        if self.found and self.severity is None:
            raise ValueError(
                "HDICheckOutput: severity must be set when found=True "
                "(Safety Reviewer cannot consume a found-but-undefined hit)"
            )
        return self


class BilingualTermOutput(BaseModel):
    english: str | None = None
    chinese: str | None = None
    pinyin: str | None = None
    source: str = "symmap"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NodeNeighborhoodOutput(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


# ---- seed normalization ----------------------------------------------------

EntityType = Literal["compound", "herb", "food", "term"]


def normalize_seed(entity_type: EntityType, value: str) -> str:
    """Normalize a free-text seed to the canonical form the staged KG expects.

    Per `staged-mcp-probe.md`:
      - compounds: UPPERCASE (CURCUMIN, QUERCETIN, ...)
      - herbs:    Latin title-case (Ginkgo biloba, Curcuma longa)
      - foods:    common title-case (Garlic, Ginger)
      - terms (bilingual lookup): pass through — the tool accepts any of
        EN/CN/Pinyin
    """
    v = (value or "").strip()
    if not v:
        return v
    if entity_type == "compound":
        return v.upper()
    if entity_type in ("herb", "food"):
        # Title-case but preserve embedded hyphens and Latin spp. spelling.
        # `Ginkgo biloba` vs `Ginkgo Biloba`: title() lowers the second word's
        # tail correctly. For multi-word herbs we accept exactly what the
        # caller gave if it already looks title-cased.
        return v.title() if v.islower() or v.isupper() else v
    return v


# ---- Layer A ---------------------------------------------------------------

def kg_query(
    question: str,
    mode: Literal["mix", "hybrid", "local", "global", "naive"] = "mix",
    top_k: int = 40,
) -> KgQueryOutput:
    """Natural-language question over the LightRAG KG (Layer A fallback).

    Note: per probe results 2026-05-01, this tool currently returns
    `answer="None"` or `"[no-context]"` on most queries. Prefer the
    Layer-B typed traversals when the question fits a known motif.
    """
    raw = _call("kg_query", {"question": question, "mode": mode, "top_k": top_k})
    return KgQueryOutput.model_validate(raw)


# ---- Layer B (typed traversals) -------------------------------------------

def kg_diet_to_compounds(seed: str, top_k: int = 20) -> TraversalOutput:
    """Food → bioactive compounds. Dietitian's primary tool.

    Seed: food name (e.g. "Garlic", "Ginger"). Auto-normalized to title-case.
    """
    raw = _call(
        "kg_diet_to_compounds",
        {"seed": normalize_seed("food", seed), "top_k": top_k},
    )
    return TraversalOutput.model_validate(raw)


def kg_compound_to_targets(seed: str, top_k: int = 20) -> TraversalOutput:
    """Compound → protein targets. Pharmacologist's primary tool.

    Seed: compound name (e.g. "Curcumin"). Auto-normalized to UPPERCASE.
    """
    raw = _call(
        "kg_compound_to_targets",
        {"seed": normalize_seed("compound", seed), "top_k": top_k},
    )
    return TraversalOutput.model_validate(raw)


def kg_compound_to_diseases(seed: str, top_k: int = 20) -> TraversalOutput:
    """Compound → Target → Disease (depth-2 chain). Provenance for HDI claims.

    Note: per probe 2026-05-01, this chain currently returns 0 chains
    even when single-hop kg_compound_to_targets succeeds — Compound→Target
    join layer issue, tracked as a follow-up to Task #10. Use with caution.
    """
    raw = _call(
        "kg_compound_to_diseases",
        {"seed": normalize_seed("compound", seed), "top_k": top_k},
    )
    return TraversalOutput.model_validate(raw)


def kg_herb_to_diseases(seed: str, top_k: int = 20) -> TraversalOutput:
    """Herb → Disease. Backed by CMAUP plant-disease + HERB 2.0 evidence.

    Seed: herb name in Latin scientific form (e.g. "Ginkgo biloba",
    "Curcuma longa") OR common form. Normalization is light-touch.
    """
    raw = _call(
        "kg_herb_to_diseases",
        {"seed": normalize_seed("herb", seed), "top_k": top_k},
    )
    return TraversalOutput.model_validate(raw)


def kg_herb_to_symptoms(seed: str, top_k: int = 20) -> TraversalOutput:
    """Herb → Symptom. TCM and Dietitian. Duke bioactivity + SymMap TCM."""
    raw = _call(
        "kg_herb_to_symptoms",
        {"seed": normalize_seed("herb", seed), "top_k": top_k},
    )
    return TraversalOutput.model_validate(raw)


def kg_compound_to_symptoms(seed: str, top_k: int = 20) -> TraversalOutput:
    """Compound → Herb → Symptom (composite). Mechanism→clinical-symptom path.

    Note: TREATS_SYMPTOM semantics on the compound side are loose
    (per probe 2026-05-01 — GINGEROL → 'Liver damage', etc.). Document
    the relation as 'associated with' rather than 'treats' in the paper
    Methods if this tool is the source.
    """
    raw = _call(
        "kg_compound_to_symptoms",
        {"seed": normalize_seed("compound", seed), "top_k": top_k},
    )
    return TraversalOutput.model_validate(raw)


# ---- Layer C (lookup primitives) ------------------------------------------

def kg_hdi_check(drug: str, herb: str) -> HDICheckOutput:
    """HDI-Safe-50 lookup. Safety Reviewer's primary tool.

    Returns severity + mechanism + citations or `found=False`. Accepts
    both Latin and common name forms for `herb`.
    """
    raw = _call("kg_hdi_check", {"drug": drug, "herb": herb})
    return HDICheckOutput.model_validate(raw)


def kg_bilingual_term(term: str) -> BilingualTermOutput:
    """SymMap bilingual canonicalization for TCM herb terms.

    Note: per probe 2026-05-01, syndrome-level TCM concepts (阴虚, 阳虚)
    are NOT in SymMap and return all-null. Works for herb canonical names
    (黄连 → Coptidis Rhizoma / Huanglian).
    """
    raw = _call("kg_bilingual_term", {"term": term})
    return BilingualTermOutput.model_validate(raw)


def kg_node_neighborhood(
    seed: str,
    max_depth: int = 2,
    max_nodes: int = 200,
) -> NodeNeighborhoodOutput:
    """Generic bounded-depth subgraph dump.

    Note: per probe 2026-05-01, the staged backend rejects label-style
    seeds with HTTP 400. Avoid in panel wiring; prefer Layer-B traversals.
    Kept here for completeness / future debug use.
    """
    raw = _call(
        "kg_node_neighborhood",
        {"seed": seed, "max_depth": max_depth, "max_nodes": max_nodes},
    )
    return NodeNeighborhoodOutput.model_validate(raw)


# ---- internals -------------------------------------------------------------

def _call(name: str, arguments: dict) -> dict:
    """Single-retry wrapper around the MCP client default singleton.

    Logs the first attempt's error before retrying so paper-grade eval
    debugging can distinguish transient timeouts from permanent failures.
    """
    client = default_client()
    try:
        return client.call_tool(name, arguments)
    except MCPError as first_exc:
        _log.warning(
            "kg_tools._call(%r) first attempt failed, retrying once: %s",
            name, first_exc,
        )
        return client.call_tool(name, arguments)
