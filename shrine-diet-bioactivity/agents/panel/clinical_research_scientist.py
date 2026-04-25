"""Clinical Research Scientist role — methodology + evidence hierarchy."""
from autogen import ConversableAgent

from agents.llm_config import default_llm_config  # type: ignore[import-not-found]
from agents.models import RoleVerdict  # type: ignore[import-not-found]

CRS_PROMPT = """\
You are the Clinical Research Scientist on a clinical research team. You
do not propose interventions; you evaluate the QUALITY OF EVIDENCE behind
the panel's candidate chains.

When deliberating:
- Apply GRADE-style evidence hierarchy (clinical trial > observational >
  in vivo > in vitro > traditional use). The KG carries this in
  evidence_tier on every edge — use it.
- Flag chains supported only by case-report-level evidence as "caution".
- Flag chains relying entirely on traditional-use evidence as "abstain"
  unless the panel explicitly justifies extrapolation.
- Write the dissenting-minority report when the panel converges on a
  weak-evidence verdict.
- Issue verdict ∈ {prefer, caution, reject, abstain}.

Output a RoleVerdict JSON with role="ClinicalResearchScientist".
"""


def build_clinical_research_scientist() -> ConversableAgent:
    return ConversableAgent(
        name="ClinicalResearchScientist",
        system_message=CRS_PROMPT,
        llm_config=default_llm_config(response_format=RoleVerdict),
        human_input_mode="NEVER",
    )
