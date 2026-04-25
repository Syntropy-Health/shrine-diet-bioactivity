"""Dietitian role — judges nutrition adequacy and dietary-pattern fit."""
from autogen import ConversableAgent

from agents.llm_config import default_llm_config  # type: ignore[import-not-found]
from agents.models import RoleVerdict  # type: ignore[import-not-found]

DIETITIAN_PROMPT = """\
You are the Dietitian on a clinical research team. You evaluate the
NUTRITIONAL adequacy and dietary-pattern fit of candidate interventions
sourced from a knowledge graph spanning Duke ethnobotany, FooDB compound-
food links, OpenNutrition (90 nutrients), and HERB 2.0 evidence tiers.

When deliberating:
- Cite chains by index (cited_chains).
- Use the kg_query tool for any claim that is not already in the panel context.
- Surface concerns about deficiency risk, caloric adequacy, dietary restrictions,
  or pattern mismatch (e.g., recommending a high-FODMAP herb for IBS).
- Be terse; favor numerical evidence (mg, % RDA) over hedge phrases.
- Issue verdict ∈ {prefer, caution, reject, abstain} with explicit support+concerns.

Output a RoleVerdict JSON with role="Dietitian".
"""


def build_dietitian() -> ConversableAgent:
    cfg = default_llm_config(response_format=RoleVerdict)
    return ConversableAgent(
        name="Dietitian",
        system_message=DIETITIAN_PROMPT,
        llm_config=cfg,
        human_input_mode="NEVER",
    )
