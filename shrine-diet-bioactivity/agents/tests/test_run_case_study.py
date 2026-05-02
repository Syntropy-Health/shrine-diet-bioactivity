# shrine-diet-bioactivity/agents/tests/test_run_case_study.py
"""Tests for the end-to-end case-study runner (Task H7).

Mocks all LLM calls so no API keys are required.  Three tests:
  1. Unit — _extract_panel_deliberation parses a synthetic message list.
  2. Unit — _derive_components maps kg/panel signals to ConfidenceComponents.
  3. Integration — full run_case_study flow with mocked Triage + KG + GroupChat.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from agents.run_case_study import (  # type: ignore[import-not-found]
    _derive_components,
    _extract_panel_deliberation,
    run_case_study,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kg_result(evidence_tier: str = "clinical_trial") -> KGResult:
    edge = KGEdge(
        src="Zingiber officinale",
        edge="CONTAINS_COMPOUND",
        tgt="6-gingerol",
        source_id="duke:1",
        weight=0.9,
        evidence_tier=evidence_tier,  # type: ignore[arg-type]
    )
    chain = ProvenanceChain(edges=[edge])
    return KGResult(chains=[chain], raw_subgraph_node_count=2, raw_subgraph_edge_count=1)


def _make_panel(safety_verdict: str = "prefer", actionable_prefer: int = 2, actionable_total: int = 2) -> PanelDeliberation:
    verdicts: list[RoleVerdict] = []
    # safety reviewer
    verdicts.append(RoleVerdict(
        role="SafetyReviewer",
        verdict=safety_verdict,  # type: ignore[arg-type]
        support=["no known interactions"],
        concerns=[],
        notes="",
    ))
    # actionable role agents
    for i in range(actionable_total):
        v = "prefer" if i < actionable_prefer else "caution"
        verdicts.append(RoleVerdict(
            role="Dietitian",
            verdict=v,  # type: ignore[arg-type]
            support=["adequate nutrition evidence"],
            concerns=[],
            notes="",
        ))
    return PanelDeliberation(verdicts=verdicts, dissent=[], moderator_summary="consensus reached")


# ---------------------------------------------------------------------------
# Test 1 — Unit: _extract_panel_deliberation
# ---------------------------------------------------------------------------

def test_extract_panel_deliberation_parses_role_verdicts_and_summary():
    """_extract_panel_deliberation must parse RoleVerdict + PanelDeliberation
    objects from a synthetic AG2 chat message list."""
    role_verdict_dict = {
        "role": "Dietitian",
        "verdict": "prefer",
        "support": ["ginger reduces nausea"],
        "concerns": [],
        "notes": "Well-supported by RCTs",
        "cited_chains": [0],
    }
    moderator_dict = {
        "moderator_summary": "Panel consensus: ginger has strong evidence for CINV.",
        "dissent": ["CRS noted only 3 RCTs meet GRADE A"],
        "verdicts": [],
    }
    messages = [
        {"role": "assistant", "name": "Dietitian", "content": json.dumps(role_verdict_dict)},
        {"role": "assistant", "name": "Moderator", "content": json.dumps(moderator_dict)},
        # Message without JSON — should be silently skipped
        {"role": "user", "content": "Please deliberate on the question."},
        # Non-string content — should be silently skipped
        {"role": "assistant", "content": None},
    ]

    result = _extract_panel_deliberation(messages)

    assert isinstance(result, PanelDeliberation)
    assert len(result.verdicts) == 1
    assert result.verdicts[0].role == "Dietitian"
    assert result.verdicts[0].verdict == "prefer"
    assert result.moderator_summary == "Panel consensus: ginger has strong evidence for CINV."
    assert "CRS noted only 3 RCTs meet GRADE A" in result.dissent


def test_extract_panel_deliberation_empty_messages_returns_empty_panel():
    """With no messages, _extract_panel_deliberation must return a valid
    PanelDeliberation with empty verdicts and blank summary."""
    result = _extract_panel_deliberation([])
    assert isinstance(result, PanelDeliberation)
    assert result.verdicts == []
    assert result.moderator_summary == ""
    assert result.dissent == []


# ---------------------------------------------------------------------------
# Test 2 — Unit: _derive_components
# ---------------------------------------------------------------------------

def test_derive_components_clinical_trial_tier_gives_high_evidence():
    """clinical_trial evidence tier must map to score 1.0."""
    kg = _make_kg_result("clinical_trial")
    panel = _make_panel(safety_verdict="prefer", actionable_prefer=2, actionable_total=2)
    rq = ResearchQuestion(text="test question")

    components = _derive_components(rq, kg, panel)

    assert isinstance(components, ConfidenceComponents)
    assert components.evidence_tier == 1.0
    assert components.hdi_risk == 0.0
    assert components.question_fit == 1.0  # 2/2 preferred


def test_derive_components_safety_reject_gives_full_hdi_risk():
    """Safety Reviewer 'reject' verdict must set hdi_risk=1.0."""
    kg = _make_kg_result("experimental")
    panel = _make_panel(safety_verdict="reject", actionable_prefer=0, actionable_total=1)
    rq = ResearchQuestion(text="test question")

    components = _derive_components(rq, kg, panel)

    assert components.hdi_risk == 1.0
    assert components.evidence_tier == 0.55  # experimental tier score


def test_derive_components_safety_caution_gives_half_hdi_risk():
    """Safety Reviewer 'caution' verdict must set hdi_risk=0.5."""
    kg = _make_kg_result("observational")
    panel = _make_panel(safety_verdict="caution", actionable_prefer=1, actionable_total=2)
    rq = ResearchQuestion(text="test question")

    components = _derive_components(rq, kg, panel)

    assert components.hdi_risk == 0.5
    assert components.evidence_tier == 0.7  # observational tier score
    assert components.question_fit == pytest.approx(0.5)  # 1/2


def test_derive_components_empty_chains_defaults_to_lowest_tier():
    """When kg has no chains, evidence_tier must default to 0.1 (unknown)."""
    kg = KGResult(chains=[], raw_subgraph_node_count=0, raw_subgraph_edge_count=0)
    panel = PanelDeliberation(verdicts=[], dissent=[], moderator_summary="")
    rq = ResearchQuestion(text="test question")

    components = _derive_components(rq, kg, panel)

    assert components.evidence_tier == 0.1
    assert components.hdi_risk == 0.0
    assert components.question_fit == 0.5  # no actionable roles → default 0.5


# ---------------------------------------------------------------------------
# Test 3 — Integration: run_case_study end-to-end with mocks
# ---------------------------------------------------------------------------

@patch("agents.run_case_study.build_triage_agent")
@patch("agents.run_case_study.kg_query")
@patch("agents.run_case_study.assemble_panel")
def test_run_case_study_e2e(mock_assemble, mock_kg, mock_triage, tmp_path):
    """Full run_case_study pipeline with all LLM calls mocked.

    Asserts:
    - Output synthesis JSON file is created in the correct location.
    - The file parses as a valid ResearchSynthesis.
    - Confidence is a float in [0, 1].
    - defer_to_clinician is a bool.
    """
    # --- Arrange: case spec file ---
    spec = {
        "id": "case-01-ginger-cin",
        "version": "v1",
        "research_question": "Synthesize the evidence for ginger in CINV.",
    }
    spec_path = tmp_path / "case_01.json"
    spec_path.write_text(json.dumps(spec))

    # --- Arrange: mock triage agent ---
    fake_rq = ResearchQuestion(
        text="Synthesize the evidence for ginger in CINV.",
        intervention="ginger",
        outcome="chemotherapy-induced nausea",
    )
    fake_triage = Triage(complexity="low", rationale="single intervention", red_flags=[])
    mock_triage_callable = MagicMock(return_value=(fake_rq, fake_triage))
    mock_triage.return_value = mock_triage_callable

    # --- Arrange: mock KG query ---
    fake_kg = _make_kg_result("clinical_trial")
    mock_kg.return_value = fake_kg

    # --- Arrange: mock GroupChat with synthetic messages (role verdict + moderator summary) ---
    role_verdict_dict = {
        "role": "Dietitian",
        "verdict": "prefer",
        "support": ["strong RCT evidence"],
        "concerns": [],
        "notes": "Two phase-III RCTs",
        "cited_chains": [0],
    }
    moderator_dict = {
        "moderator_summary": "Panel prefers ginger for CINV — strong RCT basis.",
        "dissent": [],
        "verdicts": [],
    }
    synthetic_messages = [
        {"role": "assistant", "name": "Dietitian", "content": json.dumps(role_verdict_dict)},
        {"role": "assistant", "name": "Moderator", "content": json.dumps(moderator_dict)},
    ]

    fake_chat = MagicMock()
    fake_chat.messages = synthetic_messages
    fake_chat.agents = [MagicMock(name="Dietitian")]

    fake_manager = MagicMock()
    fake_manager.initiate_chat = MagicMock(return_value=None)

    mock_assemble.return_value = (fake_chat, fake_manager)

    # --- Act ---
    out_dir = tmp_path / "runs"
    synthesis = run_case_study(spec_path, out_dir)

    # --- Assert: return value ---
    assert isinstance(synthesis, ResearchSynthesis)
    assert 0.0 <= synthesis.confidence <= 1.0
    assert isinstance(synthesis.defer_to_clinician, bool)
    assert synthesis.question.text == fake_rq.text

    # --- Assert: output file created ---
    case_dir = out_dir / spec["id"]
    assert case_dir.is_dir(), "case output directory must be created"
    synthesis_files = list(case_dir.glob("*-synthesis.json"))
    assert len(synthesis_files) == 1, "exactly one synthesis JSON must be written"
    transcript_files = list(case_dir.glob("*-transcript.jsonl"))
    assert len(transcript_files) == 1, "exactly one transcript JSONL must be written"

    # --- Assert: output file is valid ResearchSynthesis ---
    loaded = ResearchSynthesis.model_validate_json(synthesis_files[0].read_text())
    assert loaded.confidence == synthesis.confidence
    assert loaded.defer_to_clinician == synthesis.defer_to_clinician

    # --- Assert: mocks called correctly ---
    mock_triage.assert_called_once()
    mock_triage_callable.assert_called_once_with(spec["research_question"])
    # Mode flipped from "hybrid" to "mix" when retrieval moved to the
    # pre-fetched bundle (Option A) — Layer A is now supplementary.
    mock_kg.assert_called_once_with(spec["research_question"], mode="mix")
    mock_assemble.assert_called_once()
    fake_manager.initiate_chat.assert_called_once()


@patch("agents.run_case_study.build_triage_agent")
@patch("agents.run_case_study.kg_query")
@patch("agents.run_case_study.assemble_panel")
def test_run_case_study_safety_reject_sets_defer(mock_assemble, mock_kg, mock_triage, tmp_path):
    """When SafetyReviewer issues 'reject', defer_to_clinician must be True."""
    spec = {
        "id": "case-02-sjw-sertraline-hdi",
        "version": "v1",
        "research_question": "Evaluate SJW + sertraline interaction.",
    }
    spec_path = tmp_path / "case_02.json"
    spec_path.write_text(json.dumps(spec))

    fake_rq = ResearchQuestion(text=spec["research_question"], intervention="St. John's Wort")
    fake_triage = Triage(complexity="high", rationale="serotonin risk", red_flags=["serotonergic_interaction"])
    mock_triage.return_value = MagicMock(return_value=(fake_rq, fake_triage))
    mock_kg.return_value = _make_kg_result("clinical_trial")

    safety_reject_dict = {
        "role": "SafetyReviewer",
        "verdict": "reject",
        "support": [],
        "concerns": ["serotonin syndrome risk"],
        "notes": "HDI-Safe 50 HDI-001",
        "cited_chains": [],
    }
    moderator_dict = {
        "moderator_summary": "Safety reviewer rejected: serotonin syndrome.",
        "dissent": [],
        "verdicts": [],
    }
    fake_chat = MagicMock()
    fake_chat.messages = [
        {"role": "assistant", "name": "SafetyReviewer", "content": json.dumps(safety_reject_dict)},
        {"role": "assistant", "name": "Moderator", "content": json.dumps(moderator_dict)},
    ]
    fake_chat.agents = [MagicMock(name="SafetyReviewer")]
    fake_manager = MagicMock()
    mock_assemble.return_value = (fake_chat, fake_manager)

    synthesis = run_case_study(spec_path, tmp_path / "runs")

    assert synthesis.defer_to_clinician is True
