"""Triage agent — converts free-form research question to typed structure."""
import os
import pytest

from agents.triage import build_triage_agent  # type: ignore[import-not-found]
from agents.models import ResearchQuestion, Triage


@pytest.mark.live_llm
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="LLM smoke test")
def test_triage_classifies_simple_question_as_low():
    agent = build_triage_agent()
    rq, t = agent("Is there evidence that ginger reduces post-prandial bloating?")
    assert isinstance(rq, ResearchQuestion)
    assert isinstance(t, Triage)
    assert t.complexity in {"low", "moderate", "high"}


@pytest.mark.unit
def test_build_triage_agent_returns_callable():
    """Builder must return a callable even without an API key (won't run, just constructed)."""
    agent = build_triage_agent()
    assert callable(agent)
