# shrine-diet-bioactivity/agents/provenance.py
"""Provenance-chain formatter — assembles the final ResearchSynthesis."""
from __future__ import annotations

from agents.models import (
    ConfidenceComponents, KGResult, PanelDeliberation,
    ResearchQuestion, ResearchSynthesis, Triage,
)
from agents.calibrator import compute_confidence


def assemble_synthesis(
    question: ResearchQuestion,
    triage: Triage,
    kg: KGResult,
    panel: PanelDeliberation,
    components: ConfidenceComponents,
) -> ResearchSynthesis:
    confidence = compute_confidence(components)
    safety_reject = any(v.role == "SafetyReviewer" and v.verdict == "reject" for v in panel.verdicts)
    defer_strong = any(v.role == "DeferToClinician" and v.verdict in {"caution", "reject"} for v in panel.verdicts)
    return ResearchSynthesis(
        question=question,
        triage=triage,
        candidate_chains=kg.chains,
        panel=panel,
        confidence=confidence,
        components=components,
        defer_to_clinician=safety_reject or defer_strong,
    )
