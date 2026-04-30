"""Pydantic input/output models for the 10 MCP tools.

Per design memo §5. Inputs are tight (1–2 fields per tool) so the agent can
populate them confidently; outputs carry structured chains the agent can cite.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ─── Layer A — General Q&A ────────────────────────────────────────────────


class KgQueryInput(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language question over the KG")
    mode: Literal["mix", "hybrid", "local", "global", "naive"] = "mix"
    top_k: int = Field(40, ge=1, le=200)


class KgQueryOutput(BaseModel):
    answer: str
    references: list[str] = Field(default_factory=list, description="entity_ids cited in answer")
    scope_filter: list[str] = Field(default_factory=lambda: ["shared"])


# ─── Layer B — Role-priored traversals (shared shape) ─────────────────────


class TraversalInput(BaseModel):
    """Single typed input shared by every Layer-B tool.

    `seed` is either an entity_id (preferred — deterministic) or a free-text
    string the gateway resolves to the closest entity by vector match.
    """

    seed: str = Field(..., min_length=1)
    top_k: int = Field(20, ge=1, le=200)


class ProvenanceEdge(BaseModel):
    src_id: str
    tgt_id: str
    rel_type: str
    description: str | None = None
    evidence_tier: str | None = None
    source_id: str | None = None


class ProvenanceChain(BaseModel):
    edges: list[ProvenanceEdge]


class TraversalOutput(BaseModel):
    chains: list[ProvenanceChain] = Field(default_factory=list)
    seeds_resolved: list[str] = Field(default_factory=list)
    raw_subgraph_node_count: int = 0
    raw_subgraph_edge_count: int = 0


# ─── Layer C — Lookup primitives ──────────────────────────────────────────


class HDICheckInput(BaseModel):
    drug: str = Field(..., min_length=1)
    herb: str = Field(..., min_length=1)


class HDICheckOutput(BaseModel):
    found: bool
    severity: Literal["mild", "moderate", "severe"] | None = None
    mechanism_class: Literal[
        "CYP450", "P-gp", "PD-antagonism", "coagulation", "serotonergic"
    ] | None = None
    evidence_tier: str | None = None
    citations: list[str] = Field(default_factory=list)


class BilingualTermInput(BaseModel):
    term: str = Field(..., min_length=1)
    languages: list[Literal["en", "cn", "pinyin"]] = Field(
        default_factory=lambda: ["en", "cn", "pinyin"]
    )


class BilingualTermOutput(BaseModel):
    english: str | None = None
    chinese: str | None = None
    pinyin: str | None = None
    source: str = "symmap"
    confidence: float = 0.0


class NodeNeighborhoodInput(BaseModel):
    seed: str = Field(..., min_length=1)
    max_depth: int = Field(2, ge=0, le=5)
    max_nodes: int = Field(200, ge=1, le=2000)


class NodeNeighborhoodOutput(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
