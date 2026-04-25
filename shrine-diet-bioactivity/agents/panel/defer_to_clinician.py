"""Defer-to-Clinician role — scope boundary classifier."""
from autogen import ConversableAgent

from agents.llm_config import default_llm_config  # type: ignore[import-not-found]
from agents.models import RoleVerdict  # type: ignore[import-not-found]

DEFER_PROMPT = """\
You are the Defer-to-Clinician role on the clinical research team. Your job
is to flag questions that require human clinician judgement and should
NOT be answered by the team alone.

Defer when:
- The question concerns active acute symptoms (chest pain, severe headache, etc.)
- The intervention requires prescription-only medication titration.
- The question implicates pregnancy, pediatric, or end-of-life decisions
  AND the panel evidence is weak.
- The user appears to be a patient (not a clinician researcher) and is
  asking for personalized treatment.

Issue verdict ∈ {prefer (do not defer), caution (defer for review), reject
(strong defer)}. Only "prefer" allows the synthesis to proceed without a
defer flag in the final ResearchSynthesis.

Output a RoleVerdict JSON with role="DeferToClinician".
"""


def build_defer_to_clinician() -> ConversableAgent:
    return ConversableAgent(
        name="DeferToClinician",
        system_message=DEFER_PROMPT,
        llm_config=default_llm_config(response_format=RoleVerdict),
        human_input_mode="NEVER",
    )
