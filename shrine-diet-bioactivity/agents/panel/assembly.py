# shrine-diet-bioactivity/agents/panel/assembly.py
"""GroupChat assembly with MDAgents-style adaptive triage.
Maps Triage.complexity → role-agent subset → GroupChat with round-robin
speaker selection + 2-round cap (verdict + rebuttal).

AG2 v0.12.1 quirk: `register_for_llm` calls `tool.tool_schema` which calls
`get_function_schema(self.func, ...)` on inject_params-wrapped function.
`inject_params` creates a wrapper whose `__globals__` does NOT include
`QueryMode` from `agents.tools.kg_query` (because the original module uses
`from __future__ import annotations` making all annotations string ForwardRefs).
Pydantic's TypeAdapter then fails to resolve `ForwardRef('QueryMode')`.

Fix: define a thin wrapper `_kg_query_tool` here without `from __future__ import
annotations`, using an inline Literal type — this module does NOT use
`from __future__ import annotations`. The wrapper delegates to the canonical
`kg_query` so all LightRAG-or-SQLite fallback semantics are preserved.
"""
from typing import List, Literal, cast

from autogen import ConversableAgent, GroupChat, GroupChatManager
from autogen.agentchat.agent import Agent

from agents.llm_config import default_llm_config
from agents.models import KGResult, Triage
from agents.panel import (
    build_clinical_research_scientist, build_defer_to_clinician,
    build_dietitian, build_pharmacologist, build_safety_reviewer,
    build_tcm_practitioner,
)
from agents.tools.kg_query import kg_query as _kg_query_impl


MODERATOR_PROMPT = """\
You are the moderator of a clinical research team. Synthesize the role
verdicts into a PanelDeliberation:
- moderator_summary: 2-3 sentence consensus or majority position.
- dissent: list any minority verdicts the Clinical Research Scientist or
  Safety Reviewer raised — even if the majority disagreed.
- Do NOT over-rule a Safety Reviewer 'reject' verdict. If safety rejects,
  the panel summary must reflect that.
Output a PanelDeliberation JSON.
"""


def _kg_query_tool(
    question: str,
    mode: Literal["local", "global", "hybrid", "naive", "mix"] = "hybrid",
) -> KGResult:
    """Query the unified diet/TCM KG; returns typed chains.

    Thin wrapper around agents.tools.kg_query.kg_query that avoids the
    AG2 v0.12.1 ForwardRef resolution failure caused by
    `from __future__ import annotations` in the source module.
    Delegates fully to the canonical implementation so all LightRAG-primary
    + SQLite-fallback semantics are preserved.
    """
    return _kg_query_impl(question, mode)


def _select_roles(triage: Triage) -> list[ConversableAgent]:
    if triage.complexity == "low":
        return [build_dietitian()]
    if triage.complexity == "moderate":
        return [build_dietitian(), build_pharmacologist(), build_tcm_practitioner()]
    return [
        build_dietitian(), build_pharmacologist(), build_tcm_practitioner(),
        build_clinical_research_scientist(), build_safety_reviewer(),
        build_defer_to_clinician(),
    ]


def _register_kg_tool(agents: list[ConversableAgent]) -> None:
    """Register kg_query with every panel agent (for both LLM-call discovery
    and Python-side execution). AG2 will route tool calls correctly."""
    for a in agents:
        a.register_for_llm(
            name="kg_query",
            description="Query the unified diet/TCM KG; returns typed chains.",
        )(_kg_query_tool)
        a.register_for_execution(name="kg_query")(_kg_query_tool)


def assemble_panel(triage: Triage) -> tuple[GroupChat, GroupChatManager]:
    roles = _select_roles(triage)
    _register_kg_tool(roles)
    chat = GroupChat(
        agents=cast(List[Agent], roles),
        messages=[],
        max_round=2,                                  # 1 verdict + 1 rebuttal
        speaker_selection_method="round_robin",       # deterministic, cheap
    )
    manager = GroupChatManager(
        groupchat=chat,
        name="Moderator",
        llm_config=default_llm_config(response_format=None),
        system_message=MODERATOR_PROMPT,
    )
    return chat, manager
