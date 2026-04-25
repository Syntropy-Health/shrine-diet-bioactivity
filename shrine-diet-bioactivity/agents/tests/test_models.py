"""Tests for typed contracts shared by all agents."""
import pytest
from pydantic import ValidationError

from agents.models import (  # type: ignore[import-not-found]
    ResearchQuestion,
    Triage,
    KGResult,
    ProvenanceChain,
    RoleVerdict,
    PanelDeliberation,
    ConfidenceComponents,
    ResearchSynthesis,
)


def test_research_question_minimal():
    q = ResearchQuestion(text="What is the evidence for ginger in CIN?")
    assert q.text.startswith("What is the evidence")
    assert q.intervention is None
    assert q.outcome is None


def test_triage_complexity_enum():
    t = Triage(complexity="moderate", rationale="multi-drug context", red_flags=[])
    assert t.complexity == "moderate"
    with pytest.raises(ValidationError):
        Triage(complexity="trivial", rationale="x", red_flags=[])


def test_provenance_chain_min_one_edge():
    with pytest.raises(ValidationError):
        ProvenanceChain(edges=[])
    pc = ProvenanceChain(edges=[{
        "src": "Zingiber officinale", "edge": "CONTAINS_COMPOUND",
        "tgt": "6-gingerol", "source_id": "duke:1234",
        "weight": 0.9, "evidence_tier": "experimental"
    }])
    assert len(pc.edges) == 1


def test_role_verdict_enum():
    v = RoleVerdict(role="Dietitian", verdict="prefer", support=[], concerns=[], notes="")
    assert v.verdict == "prefer"
    with pytest.raises(ValidationError):
        RoleVerdict(role="Dietitian", verdict="approve", support=[], concerns=[], notes="")


def test_confidence_components_bounds():
    c = ConfidenceComponents(evidence_tier=0.8, hdi_risk=0.1, question_fit=0.9)
    assert 0 <= c.evidence_tier <= 1
    with pytest.raises(ValidationError):
        ConfidenceComponents(evidence_tier=1.5, hdi_risk=0.1, question_fit=0.9)


def test_research_synthesis_complete():
    rs = ResearchSynthesis(
        question=ResearchQuestion(text="x"),
        triage=Triage(complexity="low", rationale="y", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(verdicts=[], dissent=[], moderator_summary="z"),
        confidence=0.5,
        components=ConfidenceComponents(evidence_tier=0.5, hdi_risk=0.0, question_fit=0.5),
        defer_to_clinician=False,
    )
    assert rs.confidence == 0.5
