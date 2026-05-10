# shrine-diet-bioactivity/agents/tests/test_provenance.py
"""Round-trip validation and defer_to_clinician logic tests for provenance.py."""
import pytest

from agents.models import (  # type: ignore[import-not-found]
    ConfidenceComponents,
    KGEdge,
    KGResult,
    PanelDeliberation,
    ProvenanceChain,
    ResearchQuestion,
    ResearchSynthesis,
    RoleVerdict,
    Triage,
)
from agents.provenance import assemble_synthesis  # type: ignore[import-not-found]

pytestmark = [pytest.mark.unit]


def _minimal_kg() -> KGResult:
    edge = KGEdge(
        src="Zingiber officinale",
        edge="CONTAINS_COMPOUND",
        tgt="6-gingerol",
        source_id="duke:1.1",
        weight=0.85,
        evidence_tier="experimental",
    )
    return KGResult(
        chains=[ProvenanceChain(edges=[edge])],
        raw_subgraph_node_count=2,
        raw_subgraph_edge_count=1,
    )


def _base_inputs():
    rq = ResearchQuestion(text="What is the evidence for ginger in CIN?")
    triage = Triage(complexity="high", rationale="safety critical", red_flags=["pregnancy"])
    kg = _minimal_kg()
    components = ConfidenceComponents(evidence_tier=0.7, hdi_risk=0.5, question_fit=0.6)
    return rq, triage, kg, components


def test_safety_reviewer_reject_sets_defer_flag():
    rq, triage, kg, components = _base_inputs()
    safety_verdict = RoleVerdict(
        role="SafetyReviewer", verdict="reject",
        support=[], concerns=["severe CYP450 inhibition"], notes="HDI-001 applies",
    )
    panel = PanelDeliberation(verdicts=[safety_verdict], dissent=[], moderator_summary="Reject")
    synthesis = assemble_synthesis(rq, triage, kg, panel, components)
    assert synthesis.defer_to_clinician is True


def test_defer_to_clinician_caution_sets_defer_flag():
    rq, triage, kg, components = _base_inputs()
    defer_verdict = RoleVerdict(
        role="DeferToClinician", verdict="caution",
        support=[], concerns=["scope boundary"], notes="clinician review needed",
    )
    panel = PanelDeliberation(verdicts=[defer_verdict], dissent=[], moderator_summary="Caution")
    synthesis = assemble_synthesis(rq, triage, kg, panel, components)
    assert synthesis.defer_to_clinician is True


def test_defer_to_clinician_reject_sets_defer_flag():
    rq, triage, kg, components = _base_inputs()
    defer_verdict = RoleVerdict(
        role="DeferToClinician", verdict="reject",
        support=[], concerns=["patient question"], notes="strong defer",
    )
    panel = PanelDeliberation(verdicts=[defer_verdict], dissent=[], moderator_summary="Strong defer")
    synthesis = assemble_synthesis(rq, triage, kg, panel, components)
    assert synthesis.defer_to_clinician is True


def test_no_safety_issue_does_not_set_defer_flag():
    rq, triage, kg, _ = _base_inputs()
    diet_verdict = RoleVerdict(
        role="Dietitian", verdict="prefer",
        support=["well-supported"], concerns=[], notes="",
    )
    panel = PanelDeliberation(verdicts=[diet_verdict], dissent=[], moderator_summary="Prefer")
    components_ok = ConfidenceComponents(evidence_tier=0.8, hdi_risk=0.0, question_fit=0.9)
    synthesis = assemble_synthesis(rq, triage, kg, panel, components_ok)
    assert synthesis.defer_to_clinician is False


def test_assemble_synthesis_round_trip_model_validate():
    """ResearchSynthesis produced by assemble_synthesis must pass model_validate."""
    rq, triage, kg, components = _base_inputs()
    panel = PanelDeliberation(verdicts=[], dissent=[], moderator_summary="OK")
    synthesis = assemble_synthesis(rq, triage, kg, panel, components)
    validated = ResearchSynthesis.model_validate(synthesis.model_dump())
    assert validated.confidence == synthesis.confidence
    assert validated.defer_to_clinician == synthesis.defer_to_clinician
    assert len(validated.candidate_chains) == len(kg.chains)
