"""Typed contracts for the Subsystem H clinical research team.

Every AG2 ConversableAgent that emits structured output uses these models
via response_format=PydanticModel. The moderator consumes them; the
calibrator + provenance formatter assemble the final ResearchSynthesis.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ComplexityTier = Literal["low", "moderate", "high"]
Verdict = Literal["prefer", "caution", "reject", "abstain"]
EvidenceTier = Literal[
    "clinical_trial", "pharmacokinetic_study", "observational",
    "case_report_series", "case_report",
    "experimental", "in_vivo", "in_vitro",
    "traditional", "unknown",
]
RoleName = Literal[
    "Dietitian", "Pharmacologist", "TCMPractitioner",
    "ClinicalResearchScientist", "SafetyReviewer", "DeferToClinician",
]


class ResearchQuestion(BaseModel):
    text: str = Field(min_length=1)
    intervention: str | None = None      # e.g., "ginger" or "Zingiber officinale"
    outcome: str | None = None           # e.g., "chemotherapy-induced nausea"
    population: str | None = None        # e.g., "adult oncology patients on cisplatin"
    comparator: str | None = None        # e.g., "ondansetron"
    languages: list[str] = Field(default_factory=lambda: ["en"])  # e.g., ["en", "zh"]


class Triage(BaseModel):
    complexity: ComplexityTier
    rationale: str
    red_flags: list[str]                 # e.g., ["pregnancy", "anticoagulant_therapy"]
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list, max_length=3)


class KGEdge(BaseModel):
    src: str
    edge: str
    tgt: str
    source_id: str
    weight: float = Field(ge=0, le=1)
    evidence_tier: EvidenceTier = "unknown"


class ProvenanceChain(BaseModel):
    edges: list[KGEdge] = Field(min_length=1)


class KGResult(BaseModel):
    chains: list[ProvenanceChain]
    raw_subgraph_node_count: int = Field(ge=0)
    raw_subgraph_edge_count: int = Field(ge=0)
    query_mode: Literal["local", "global", "hybrid", "naive", "mix"] = "hybrid"


class RoleVerdict(BaseModel):
    role: RoleName
    verdict: Verdict
    support: list[str]                   # bullet points the role finds compelling
    concerns: list[str]                  # bullet points the role finds problematic
    notes: str                           # free-form qualitative note
    cited_chains: list[int] = Field(default_factory=list)  # indices into KGResult.chains


class PanelDeliberation(BaseModel):
    verdicts: list[RoleVerdict]
    dissent: list[str]                   # minority opinions surfaced explicitly
    moderator_summary: str


class ConfidenceComponents(BaseModel):
    evidence_tier: float = Field(ge=0, le=1)
    hdi_risk: float = Field(ge=0, le=1)
    question_fit: float = Field(ge=0, le=1)


class ResearchSynthesis(BaseModel):
    question: ResearchQuestion
    triage: Triage
    candidate_chains: list[ProvenanceChain]
    panel: PanelDeliberation
    confidence: float = Field(ge=0, le=1)
    components: ConfidenceComponents
    defer_to_clinician: bool
