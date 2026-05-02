# shrine-diet-bioactivity/agents/tests/test_assembly.py
import pytest
from autogen import ConversableAgent, GroupChat, GroupChatManager

from agents.panel.assembly import assemble_panel  # type: ignore[import-not-found]
from agents.models import Triage


def test_assemble_panel_low_complexity_returns_solo():
    triage = Triage(complexity="low", rationale="single intervention", red_flags=[])
    chat, manager = assemble_panel(triage)
    assert isinstance(chat, GroupChat)
    assert isinstance(manager, GroupChatManager)
    assert len(chat.agents) == 1  # solo Dietitian


def test_assemble_panel_moderate_returns_three_role_team():
    triage = Triage(complexity="moderate", rationale="multi-drug", red_flags=["polypharmacy_3plus"])
    chat, manager = assemble_panel(triage)
    role_names = sorted(a.name for a in chat.agents)
    assert role_names == sorted(["Dietitian", "Pharmacologist", "TCMPractitioner"])


def test_assemble_panel_high_returns_full_six():
    triage = Triage(complexity="high", rationale="pregnancy + weak-evidence", red_flags=["pregnancy"])
    chat, manager = assemble_panel(triage)
    assert len(chat.agents) == 6
    # max_round = N agents — one verdict per role under pre-fetched
    # retrieval architecture (per e2-panel-mcp-wiring-results.md Option A).
    assert chat.max_round == len(chat.agents)
