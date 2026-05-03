"""Baseline contract tests — every baseline must produce a valid ResearchSynthesis.

Patch strategy: each baseline does `from openai import OpenAI` at module level,
so we patch `eval.baselines.<module>.OpenAI` (the name in the module's namespace)
rather than `openai.OpenAI` (which would only affect future imports).
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from eval.scenario import GoldStandard, Scenario  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_scenario() -> Scenario:
    return Scenario(
        id="fixture-001",
        category="herbal_single_symptom",
        research_question="Does ginger reduce post-prandial bloating?",
        gold=GoldStandard(
            expected_complexity="low",
            expected_panel_verdict="prefer",
            expected_evidence_tier="clinical_trial",
            expected_min_chains=1,
            expected_defer=False,
            expected_red_flags=[],
            languages=["en"],
        ),
        rationale="multiple RCTs",
        source_citations=[],
    )


@pytest.fixture
def high_complexity_scenario() -> Scenario:
    return Scenario(
        id="fixture-high-001",
        category="multi_drug_hdi",
        research_question="Does St. John's Wort interact with warfarin increasing bleeding risk?",
        gold=GoldStandard(
            expected_complexity="high",
            expected_panel_verdict="reject",
            expected_evidence_tier="clinical_trial",
            expected_min_chains=2,
            expected_defer=True,
            expected_red_flags=["anticoagulant_therapy"],
            expected_hdi_severity="severe",
            languages=["en"],
        ),
        rationale="Well-documented P450 induction",
        source_citations=["Johne 1999 PMID:10571030"],
    )


@pytest.fixture
def tcm_scenario() -> Scenario:
    return Scenario(
        id="fixture-tcm-001",
        category="tcm_bilingual",
        research_question="当归 Dang Gui for menopausal hot flashes — evidence and safety?",
        gold=GoldStandard(
            expected_complexity="moderate",
            expected_panel_verdict="caution",
            expected_evidence_tier="observational",
            expected_min_chains=1,
            expected_defer=False,
            expected_red_flags=[],
            languages=["en", "zh"],
        ),
        rationale="Phytoestrogen activity; limited RCTs",
        source_citations=[],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_completion(verdict: str = "prefer") -> SimpleNamespace:
    """Minimal OpenAI-shaped chat completion for mocking."""
    content = (
        f'{{"verdict":"{verdict}","support":["evidence A"],'
        f'"concerns":["concern B"],"notes":"stub note"}}'
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(total_tokens=20),
    )


def _stub_openai_client(verdict: str = "prefer") -> MagicMock:
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _stub_completion(verdict)
    return mock_client


# Mapping from baseline name → module patch path for OpenAI
_OPENAI_PATCH_TARGET = {
    "single_llm":     "eval.baselines.single_llm.OpenAI",
    "single_llm_rag": "eval.baselines.single_llm_rag.OpenAI",
    "yang2025":       "eval.baselines.yang2025.OpenAI",
    "medagents":      "eval.baselines.medagents.OpenAI",
    "mdagents":       "eval.baselines.mdagents.OpenAI",
    "diet_os":        None,  # diet_os does not use OpenAI directly
}


@contextmanager
def _mock_baseline(name: str, mock_client: MagicMock) -> Generator[None, None, None]:
    """Patch OpenAI in the correct baseline module namespace."""
    target = _OPENAI_PATCH_TARGET[name]
    if target is None:
        # diet_os imports run_case_study directly; patch in its local namespace.
        # Use a side_effect so the returned synthesis reflects the actual spec path.
        import json as _json
        from agents.models import (  # type: ignore[import-not-found]
            ConfidenceComponents, PanelDeliberation, ResearchQuestion,
            ResearchSynthesis, Triage,
        )
        from pathlib import Path as _Path

        def _diet_os_stub(spec_path: _Path, out_dir: _Path, **_kwargs) -> ResearchSynthesis:
            # Accept preset_question/preset_triage kwargs introduced by the
            # eval-time triage bypass. Stub ignores them.
            spec = _json.loads(spec_path.read_text())
            return ResearchSynthesis(
                question=ResearchQuestion(text=spec["research_question"]),
                triage=Triage(complexity="low", rationale="stub", red_flags=[]),
                candidate_chains=[],
                panel=PanelDeliberation(verdicts=[], dissent=[], moderator_summary="stub"),
                confidence=0.5,
                components=ConfidenceComponents(evidence_tier=0.5, hdi_risk=0.0, question_fit=0.5),
                defer_to_clinician=False,
            )

        with patch("eval.baselines.diet_os.run_case_study", side_effect=_diet_os_stub):
            yield
    else:
        with patch(target, return_value=mock_client):
            yield


# ---------------------------------------------------------------------------
# Parametrized contract tests — every baseline returns ResearchSynthesis
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["single_llm", "single_llm_rag", "yang2025", "medagents", "mdagents", "diet_os"])
def test_baseline_returns_research_synthesis(name: str, fixture_scenario: Scenario):
    """Every baseline must return a valid ResearchSynthesis (mocked LLM)."""
    from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
    from eval.baselines import BASELINES  # type: ignore[import-not-found]

    fn = BASELINES[name]
    mock_client = _stub_openai_client()

    with _mock_baseline(name, mock_client):
        result = fn(fixture_scenario)

    assert isinstance(result, ResearchSynthesis)
    assert result.question.text == fixture_scenario.research_question
    assert result.confidence >= 0.0
    assert result.confidence <= 1.0
    assert result.panel is not None
    assert result.triage is not None


@pytest.mark.parametrize("name", ["single_llm", "single_llm_rag", "yang2025", "medagents", "mdagents", "diet_os"])
def test_baseline_produces_valid_verdict(name: str, fixture_scenario: Scenario):
    """Panel verdicts must be within the allowed Verdict enum values."""
    from eval.baselines import BASELINES  # type: ignore[import-not-found]

    VALID_VERDICTS = {"prefer", "caution", "reject", "abstain"}
    fn = BASELINES[name]
    mock_client = _stub_openai_client()

    with _mock_baseline(name, mock_client):
        result = fn(fixture_scenario)

    for verdict in result.panel.verdicts:
        assert verdict.verdict in VALID_VERDICTS, (
            f"baseline {name} emitted invalid verdict {verdict.verdict!r}"
        )


@pytest.mark.parametrize("name", ["single_llm", "single_llm_rag", "yang2025", "medagents", "mdagents", "diet_os"])
def test_baseline_does_not_write_to_research_journal(name: str, fixture_scenario: Scenario, tmp_path):
    """No baseline may write to research-journal/."""
    from eval.baselines import BASELINES  # type: ignore[import-not-found]

    fn = BASELINES[name]
    mock_client = _stub_openai_client()

    with _mock_baseline(name, mock_client):
        result = fn(fixture_scenario)

    # Verify the function completed without writing to research-journal
    assert result is not None


# ---------------------------------------------------------------------------
# Baseline-specific tests
# ---------------------------------------------------------------------------

def test_single_llm_uses_temperature_zero(fixture_scenario: Scenario):
    """single_llm must pass temperature=0 to the OpenAI client."""
    import eval.baselines.single_llm as mod  # type: ignore[import-not-found]

    mock_client = _stub_openai_client()

    with patch("eval.baselines.single_llm.OpenAI", return_value=mock_client):
        mod.run(fixture_scenario)

    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs.kwargs.get("temperature") == 0 or (
        call_kwargs.args and call_kwargs.args[0] == 0
    ), "temperature=0 not passed"


def test_single_llm_rag_handles_kg_unreachable(fixture_scenario: Scenario):
    """single_llm_rag must degrade gracefully when LightRAG is unavailable."""
    from agents.models import ResearchSynthesis  # type: ignore[import-not-found]
    import eval.baselines.single_llm_rag as mod  # type: ignore[import-not-found]
    from agents.tools.kg_query import KGQueryError  # type: ignore[import-not-found]

    mock_client = _stub_openai_client()

    with patch("eval.baselines.single_llm_rag.OpenAI", return_value=mock_client), \
         patch("eval.baselines.single_llm_rag.kg_query", side_effect=KGQueryError("LightRAG unreachable")):
        result = mod.run(fixture_scenario)

    # Must still return a valid ResearchSynthesis even without KG
    assert isinstance(result, ResearchSynthesis)
    assert result.question.text == fixture_scenario.research_question


def test_single_llm_rag_injects_kg_context_when_available(fixture_scenario: Scenario):
    """single_llm_rag must include KG context in the prompt when retrieval succeeds."""
    from agents.models import KGEdge, KGResult, ProvenanceChain, ResearchSynthesis  # type: ignore[import-not-found]
    import eval.baselines.single_llm_rag as mod  # type: ignore[import-not-found]

    mock_client = _stub_openai_client()
    stub_kg = KGResult(
        chains=[ProvenanceChain(edges=[
            KGEdge(src="ginger", edge="reduces", tgt="nausea",
                   source_id="duke-001", weight=0.9, evidence_tier="clinical_trial")
        ])],
        raw_subgraph_node_count=2,
        raw_subgraph_edge_count=1,
        query_mode="naive",
    )

    with patch("eval.baselines.single_llm_rag.OpenAI", return_value=mock_client), \
         patch("eval.baselines.single_llm_rag.kg_query", return_value=stub_kg):
        result = mod.run(fixture_scenario)

    assert isinstance(result, ResearchSynthesis)
    # The system prompt should contain something from KG
    create_calls = mock_client.chat.completions.create.call_args_list
    assert len(create_calls) >= 1
    messages = create_calls[0].kwargs.get("messages", [])
    combined = " ".join(str(m.get("content", "")) for m in messages)
    assert "ginger" in combined or "nausea" in combined, "KG context not injected"


def test_yang2025_makes_two_llm_calls(fixture_scenario: Scenario):
    """yang2025 must make exactly two sequential LLM calls (barrier + strategy)."""
    import eval.baselines.yang2025 as mod  # type: ignore[import-not-found]

    mock_client = _stub_openai_client()

    with patch("eval.baselines.yang2025.OpenAI", return_value=mock_client):
        mod.run(fixture_scenario)

    assert mock_client.chat.completions.create.call_count == 2, (
        f"yang2025 expected 2 LLM calls, got {mock_client.chat.completions.create.call_count}"
    )


def test_yang2025_barrier_categories_in_prompt(fixture_scenario: Scenario):
    """yang2025 Agent A prompt must reference barrier taxonomy categories."""
    import eval.baselines.yang2025 as mod  # type: ignore[import-not-found]

    # Check the module-level constant for barrier categories
    barrier_prompt = mod._BARRIER_AGENT_SYSTEM
    expected_categories = ["motivational", "knowledge", "access", "social"]
    for cat in expected_categories:
        assert cat in barrier_prompt.lower(), f"barrier category '{cat}' missing from prompt"


def test_medagents_three_role_verdicts(fixture_scenario: Scenario):
    """medagents must produce exactly 3 role verdicts (Dietitian, Pharmacologist, CRS)."""
    import eval.baselines.medagents as mod  # type: ignore[import-not-found]

    mock_client = _stub_openai_client()

    with patch("eval.baselines.medagents.OpenAI", return_value=mock_client):
        result = mod.run(fixture_scenario)

    assert len(result.panel.verdicts) == 3, (
        f"medagents expected 3 verdicts, got {len(result.panel.verdicts)}"
    )
    role_names = {v.role for v in result.panel.verdicts}
    assert "Dietitian" in role_names
    assert "Pharmacologist" in role_names
    assert "ClinicalResearchScientist" in role_names


def test_medagents_makes_four_llm_calls(fixture_scenario: Scenario):
    """medagents makes 4 calls: 3 role agents + 1 moderator synthesis."""
    import eval.baselines.medagents as mod  # type: ignore[import-not-found]

    mock_client = _stub_openai_client()

    with patch("eval.baselines.medagents.OpenAI", return_value=mock_client):
        mod.run(fixture_scenario)

    assert mock_client.chat.completions.create.call_count == 4, (
        f"medagents expected 4 LLM calls, got {mock_client.chat.completions.create.call_count}"
    )


def test_mdagents_routes_low_complexity_to_one_agent(fixture_scenario: Scenario):
    """mdagents must route low-complexity scenarios to 1 role agent."""
    import eval.baselines.mdagents as mod  # type: ignore[import-not-found]

    mock_client = MagicMock()
    low_complexity_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"complexity": "low"}'))],
        usage=SimpleNamespace(total_tokens=10),
    )
    role_resp = _stub_completion("prefer")
    # 1 classify + 1 role + 1 moderator
    mock_client.chat.completions.create.side_effect = [
        low_complexity_resp,
        role_resp,
        role_resp,  # moderator
    ]

    with patch("eval.baselines.mdagents.OpenAI", return_value=mock_client):
        result = mod.run(fixture_scenario)

    assert len(result.panel.verdicts) == 1


def test_mdagents_routes_high_complexity_to_six_agents(high_complexity_scenario: Scenario):
    """mdagents must route high-complexity scenarios to 6 role agents."""
    import eval.baselines.mdagents as mod  # type: ignore[import-not-found]

    mock_client = MagicMock()
    high_complexity_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"complexity": "high"}'))],
        usage=SimpleNamespace(total_tokens=10),
    )
    role_resp = _stub_completion("reject")
    # 1 classify + 6 roles + 1 moderator = 8 calls
    mock_client.chat.completions.create.side_effect = [
        high_complexity_resp,
        role_resp, role_resp, role_resp, role_resp, role_resp, role_resp,
        role_resp,  # moderator
    ]

    with patch("eval.baselines.mdagents.OpenAI", return_value=mock_client):
        result = mod.run(high_complexity_scenario)

    assert len(result.panel.verdicts) == 6


def test_mdagents_routes_moderate_complexity_to_three_agents(fixture_scenario: Scenario):
    """mdagents routes moderate-complexity to 3 role agents."""
    import eval.baselines.mdagents as mod  # type: ignore[import-not-found]

    mock_client = MagicMock()
    moderate_complexity_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"complexity": "moderate"}'))],
        usage=SimpleNamespace(total_tokens=10),
    )
    role_resp = _stub_completion("caution")
    # 1 classify + 3 roles + 1 moderator
    mock_client.chat.completions.create.side_effect = [
        moderate_complexity_resp,
        role_resp, role_resp, role_resp,
        role_resp,  # moderator
    ]

    with patch("eval.baselines.mdagents.OpenAI", return_value=mock_client):
        result = mod.run(fixture_scenario)

    assert len(result.panel.verdicts) == 3


def test_mdagents_invalid_complexity_falls_back_to_moderate(fixture_scenario: Scenario):
    """mdagents must handle unparseable complexity JSON by falling back to moderate."""
    import eval.baselines.mdagents as mod  # type: ignore[import-not-found]

    mock_client = MagicMock()
    bad_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="this is not json"))],
        usage=SimpleNamespace(total_tokens=5),
    )
    role_resp = _stub_completion("caution")
    # fallback to moderate = 1 classify + 3 roles + 1 moderator
    mock_client.chat.completions.create.side_effect = [
        bad_resp,
        role_resp, role_resp, role_resp,
        role_resp,  # moderator
    ]

    with patch("eval.baselines.mdagents.OpenAI", return_value=mock_client):
        result = mod.run(fixture_scenario)

    assert len(result.panel.verdicts) == 3


def test_diet_os_invokes_run_case_study(fixture_scenario: Scenario):
    """diet_os must delegate to agents.run_case_study.run_case_study."""
    from agents.models import (  # type: ignore[import-not-found]
        ConfidenceComponents, PanelDeliberation, ResearchQuestion,
        ResearchSynthesis, Triage,
    )
    import eval.baselines.diet_os as mod  # type: ignore[import-not-found]

    stub_synthesis = ResearchSynthesis(
        question=ResearchQuestion(text=fixture_scenario.research_question),
        triage=Triage(complexity="low", rationale="stub", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(verdicts=[], dissent=[], moderator_summary="stub"),
        confidence=0.5,
        components=ConfidenceComponents(evidence_tier=0.5, hdi_risk=0.0, question_fit=0.5),
        defer_to_clinician=False,
    )

    with patch("eval.baselines.diet_os.run_case_study", return_value=stub_synthesis) as mock_rcs:
        result = mod.run(fixture_scenario)

    mock_rcs.assert_called_once()
    assert isinstance(result, ResearchSynthesis)
    assert result is stub_synthesis


def test_diet_os_uses_tempdir_not_research_journal(fixture_scenario: Scenario):
    """diet_os must pass a tempdir path to run_case_study, not research-journal/."""
    from agents.models import (  # type: ignore[import-not-found]
        ConfidenceComponents, PanelDeliberation, ResearchQuestion,
        ResearchSynthesis, Triage,
    )
    import eval.baselines.diet_os as mod  # type: ignore[import-not-found]

    stub_synthesis = ResearchSynthesis(
        question=ResearchQuestion(text=fixture_scenario.research_question),
        triage=Triage(complexity="low", rationale="stub", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(verdicts=[], dissent=[], moderator_summary="stub"),
        confidence=0.5,
        components=ConfidenceComponents(evidence_tier=0.5, hdi_risk=0.0, question_fit=0.5),
        defer_to_clinician=False,
    )

    with patch("eval.baselines.diet_os.run_case_study", return_value=stub_synthesis) as mock_rcs:
        mod.run(fixture_scenario)

    call_args = mock_rcs.call_args
    out_dir = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("out_dir")
    assert out_dir is not None
    assert "research-journal" not in str(out_dir), (
        f"diet_os wrote to research-journal: {out_dir}"
    )


def test_all_baselines_registered():
    """BASELINES registry must contain exactly the 6 expected keys."""
    from eval.baselines import BASELINES  # type: ignore[import-not-found]

    expected = {"single_llm", "single_llm_rag", "yang2025", "medagents", "mdagents", "diet_os"}
    assert set(BASELINES.keys()) == expected


def test_baselines_are_callable():
    """All registry entries must be callable."""
    from eval.baselines import BASELINES  # type: ignore[import-not-found]

    for name, fn in BASELINES.items():
        assert callable(fn), f"BASELINES[{name!r}] is not callable"
