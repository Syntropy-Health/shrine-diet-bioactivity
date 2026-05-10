import pytest
from autogen import ConversableAgent

from agents.panel import (  # type: ignore[import-not-found]
    build_dietitian, build_pharmacologist, build_tcm_practitioner,
    build_clinical_research_scientist, build_safety_reviewer, build_defer_to_clinician,
)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("builder, expected_role", [
    (build_dietitian, "Dietitian"),
    (build_pharmacologist, "Pharmacologist"),
    (build_tcm_practitioner, "TCMPractitioner"),
    (build_clinical_research_scientist, "ClinicalResearchScientist"),
    (build_safety_reviewer, "SafetyReviewer"),
    (build_defer_to_clinician, "DeferToClinician"),
])
def test_role_builder_returns_conversable_agent(builder, expected_role):
    agent = builder()
    assert isinstance(agent, ConversableAgent)
    assert expected_role in agent.system_message
    # All roles share the kg_query tool (after assembly registers it)
    # Tool registration happens during GroupChat assembly (Task H5).
