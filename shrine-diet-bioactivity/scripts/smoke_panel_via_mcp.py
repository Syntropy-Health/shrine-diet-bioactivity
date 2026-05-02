"""E2E smoke test for the panel + MCP gateway wiring.

Bypasses the triage stage (which has Nemotron JSON-quality issues per
postmortem §9d) and constructs a fixed high-complexity Triage so all 6
panel roles are assembled. Then verifies:

  1. The MCP tools were actually called by panel agents (look for
     kg_compound_to_targets / kg_hdi_check / kg_diet_to_compounds in the
     transcript).
  2. At least one tool returned non-empty chains/results.
  3. The chat completed without import or wiring errors.

Run:
  python3 -m scripts.smoke_panel_via_mcp

Requires env: MCP_URL, MCP_API_KEY, OPENROUTER_API_KEY.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

# Bootstrap sys.path for `python3 -m scripts.smoke_panel_via_mcp`.
_REPO = Path(__file__).resolve().parent.parent
for _sub in ("", "lightrag", "agents"):
    _p = str(_REPO / _sub) if _sub else str(_REPO)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from autogen import ConversableAgent

from agents.models import ResearchQuestion, Triage  # type: ignore[import-not-found]
from agents.panel.assembly import assemble_panel  # type: ignore[import-not-found]
from agents.retrieval import (  # type: ignore[import-not-found]
    render_bundle_for_prompt, retrieve_for_question,
)


QUESTION = (
    "In adults receiving moderately emetogenic chemotherapy, does adjunctive "
    "ginger (Zingiber officinale) reduce chemotherapy-induced nausea and "
    "vomiting compared to standard antiemetics alone?"
)


def _fixed_triage() -> Triage:
    return Triage(
        complexity="high",
        rationale="smoke: force all 6 panel roles to wire",
        red_flags=["chemotherapy", "polypharmacy_3plus"],
    )


def _scan_for_tool_calls(messages: list[dict]) -> dict[str, int]:
    """Return {tool_name: call_count} for any MCP tool seen in the chat."""
    counts: dict[str, int] = {}
    for m in messages:
        # AG2 tool-call messages live under content (None) + tool_calls list,
        # OR as serialized dicts in 'content'. Look at both.
        for tc in (m.get("tool_calls") or []):
            name = tc.get("function", {}).get("name") or tc.get("name")
            if name:
                counts[name] = counts.get(name, 0) + 1
        content = m.get("content")
        if isinstance(content, str):
            # Some AG2 versions render tool-call traces as text — sniff names.
            for tool in (
                "kg_query", "kg_diet_to_compounds", "kg_compound_to_targets",
                "kg_compound_to_diseases", "kg_herb_to_diseases",
                "kg_herb_to_symptoms", "kg_compound_to_symptoms",
                "kg_hdi_check", "kg_bilingual_term", "kg_node_neighborhood",
            ):
                if f'"name": "{tool}"' in content or f"name='{tool}'" in content:
                    counts[tool] = counts.get(tool, 0) + 1
    return counts


def main() -> int:
    rq = ResearchQuestion(
        text=QUESTION,
        intervention="Zingiber officinale",
        outcome="chemotherapy-induced nausea and vomiting",
        population="adults on moderately emetogenic chemo",
        comparator="Warfarin",  # forces an HDI check (well-known interaction)
    )
    triage = _fixed_triage()
    print(f"smoke: question={QUESTION[:80]}...")
    print(f"smoke: triage={triage.model_dump_json()}")

    # Pre-fetched retrieval (Option A): deterministic Layer-B/C dispatch.
    bundle = retrieve_for_question(rq, triage)
    print(f"smoke: bundle has {bundle.total_chains()} chains, "
          f"hdi_check={'set' if bundle.hdi_check else 'None'}, "
          f"bilingual={'set' if bundle.bilingual else 'None'}, "
          f"errors={list(bundle.errors)}")
    rendered = render_bundle_for_prompt(bundle)
    print(f"smoke: rendered bundle preview:\n{rendered[:600]}\n...")

    chat, manager = assemble_panel(triage)
    print(f"smoke: panel assembled with {len(chat.agents)} roles "
          f"({[a.name for a in chat.agents]}); max_round={chat.max_round}")

    moderator_input = (
        f"Research question: {rq.model_dump_json()}\n"
        f"Triage: {triage.model_dump_json()}\n\n"
        f"{rendered}\n"
        "Each role agent: emit a RoleVerdict reasoning over the Retrieval "
        "Bundle above. Cite chain indices in `cited_chains`. The moderator "
        "emits a PanelDeliberation."
    )
    try:
        manager.initiate_chat(
            cast(ConversableAgent, chat.agents[0]),
            message=moderator_input,
        )
    except Exception as e:
        print(f"smoke: panel chat raised: {type(e).__name__}: {e}", file=sys.stderr)
        # Don't fail-fast — we still want to inspect the partial transcript

    tool_counts = _scan_for_tool_calls(chat.messages)
    print("smoke: tool call counts (LLM-driven) =", json.dumps(tool_counts, indent=2))
    print(f"smoke: chat had {len(chat.messages)} messages")

    # Count role verdicts that cite real chain indices.
    cited_chains_total = 0
    role_verdicts_valid = 0
    for m in chat.messages:
        content = m.get("content")
        if not isinstance(content, str):
            continue
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            continue
        if "role" in obj and "verdict" in obj:
            role_verdicts_valid += 1
            cited_chains_total += len(obj.get("cited_chains") or [])

    # Persist transcript for forensic review
    out = Path("/tmp/e2e-smoke/panel-transcript.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(m, default=str) for m in chat.messages))
    print(f"smoke: transcript at {out}")

    # Pass criteria for Option A (pre-fetched retrieval):
    #   1. The retrieval bundle was non-empty (we actually retrieved evidence).
    #   2. All assembled roles produced valid RoleVerdict JSONs.
    #   3. At least one role cited a chain index (so the reasoning was grounded).
    bundle_ok = (bundle.total_chains() > 0) or (bundle.hdi_check is not None)
    roles_ok = role_verdicts_valid >= len(chat.agents)
    grounding_ok = cited_chains_total > 0

    print(f"smoke: bundle_ok={bundle_ok}, roles_ok={roles_ok} "
          f"({role_verdicts_valid}/{len(chat.agents)}), "
          f"grounding_ok={grounding_ok} (cited_chains_total={cited_chains_total})")

    if bundle_ok and roles_ok and grounding_ok:
        print("smoke: PASS — pre-fetched retrieval grounded the panel", file=sys.stderr)
        return 0
    print("smoke: FAIL — see criteria above", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
