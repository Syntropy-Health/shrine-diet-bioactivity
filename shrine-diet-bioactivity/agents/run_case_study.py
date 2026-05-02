# shrine-diet-bioactivity/agents/run_case_study.py
"""End-to-end runner — load case spec, execute pipeline, save synthesis.

Usage (CLI):
    python run_case_study.py <spec_path> [<out_dir>]

Prints:  confidence=X.XXX defer=True/False
"""
from __future__ import annotations

# Bootstrap sys.path so this module works when invoked as
# `python3 -m agents.run_case_study` without a prior conftest.py
# (e.g. CLI, Makefile). When pytest runs, conftest.py has already done this.
import sys as _sys
from pathlib import Path as _Path
_REPO = _Path(__file__).resolve().parent.parent  # shrine-diet-bioactivity/
for _sub in ("", "lightrag", "agents"):
    _p = str(_REPO / _sub) if _sub else str(_REPO)
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
# Pyright thinks the for-loop body might not execute; ignore.
del _sys, _Path, _REPO  # type: ignore[name-defined]

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from autogen import ConversableAgent

from agents.calibrator import compute_confidence
from agents.models import (
    ConfidenceComponents,
    PanelDeliberation,
    ResearchQuestion,
    ResearchSynthesis,
    RoleVerdict,
    Triage,
)
from agents.panel.assembly import assemble_panel
from agents.provenance import assemble_synthesis
from agents.retrieval import (  # type: ignore[import-not-found]
    render_bundle_for_prompt, retrieve_for_question,
)
from agents.tools.kg_query import kg_query
from agents.triage import build_triage_agent


def run_case_study(spec_path: Path, out_dir: Path) -> ResearchSynthesis:
    """Load a case-study spec JSON, run the full pipeline, persist outputs.

    Stages:
      1. Triage  — build_triage_agent() classifies complexity + extracts PICO.
      2. KG      — kg_query() retrieves typed provenance chains.
      3. Panel   — assemble_panel() runs GroupChat deliberation.
      4. Calibrate + Synthesise — _derive_components() + assemble_synthesis().

    Persists to out_dir/<case-id>/<timestamp>-synthesis.json and
                 out_dir/<case-id>/<timestamp>-transcript.jsonl.
    """
    spec = json.loads(spec_path.read_text())
    triage_agent = build_triage_agent()

    # Stage 1: triage
    rq, triage = triage_agent(spec["research_question"])

    # Stage 2: KG retrieval — pre-fetched deterministic Layer-B/C dispatch.
    # Free-tier Nemotron does not reliably emit AG2 tool_calls (per
    # `e2-panel-mcp-wiring-results.md`), so the panel cannot decide what
    # to retrieve. We pre-fetch evidence based on the PICO components
    # extracted by triage and inject it into moderator_input.
    bundle = retrieve_for_question(rq, triage)
    kg = kg_query(spec["research_question"], mode="mix")  # Layer A fallback context

    # Stage 3: panel deliberation
    chat, manager = assemble_panel(triage)
    moderator_input = (
        f"Research question: {rq.model_dump_json()}\n"
        f"Triage: {triage.model_dump_json()}\n\n"
        f"{render_bundle_for_prompt(bundle)}\n"
        f"Layer-A NL retrieval (often empty on free-tier; supplementary): "
        f"{kg.model_dump_json()}\n\n"
        "Each role agent: emit a RoleVerdict reasoning over the Retrieval "
        "Bundle above. Cite chain indices in `cited_chains`. The moderator "
        "emits a PanelDeliberation summarizing the team."
    )
    manager.initiate_chat(cast(ConversableAgent, chat.agents[0]), message=moderator_input)
    panel = _extract_panel_deliberation(chat.messages)

    # Stage 4: calibration + synthesis
    components = _derive_components(rq, kg, panel)
    synthesis = assemble_synthesis(rq, triage, kg, panel, components)

    # Persist
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    case_dir = out_dir / spec["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / f"{timestamp}-synthesis.json").write_text(synthesis.model_dump_json(indent=2))
    (case_dir / f"{timestamp}-transcript.jsonl").write_text(
        "\n".join(json.dumps(m, default=str) for m in chat.messages)
    )
    return synthesis


def _extract_panel_deliberation(messages: list[dict[str, Any]]) -> PanelDeliberation:
    """Parse panel verdicts from AG2 chat history.

    The moderator emits a PanelDeliberation JSON in its final message;
    everything earlier is per-role.  Non-JSON and non-string content is
    silently skipped — this keeps the parser robust against AG2 tool-call
    messages (which carry dict content or None).
    """
    verdicts: list[RoleVerdict] = []
    moderator_summary = ""
    dissent: list[str] = []
    for m in messages:
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        try:
            obj = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        if "role" in obj and "verdict" in obj:
            verdicts.append(RoleVerdict.model_validate(obj))
        elif "moderator_summary" in obj:
            moderator_summary = obj["moderator_summary"]
            dissent = obj.get("dissent", [])
    return PanelDeliberation(verdicts=verdicts, dissent=dissent, moderator_summary=moderator_summary)


def _derive_components(
    rq: ResearchQuestion,
    kg: "Any",
    panel: PanelDeliberation,
) -> ConfidenceComponents:
    """Map raw KG + panel signals to ConfidenceComponents in [0, 1].

    evidence_tier: best (max) evidence-tier score across all KG edges.
    hdi_risk:      0.0 (prefer/abstain), 0.5 (caution), 1.0 (reject) from SafetyReviewer.
    question_fit:  fraction of actionable role agents that issued "prefer".
                   Excludes DeferToClinician and SafetyReviewer (non-actionable scope).
                   Defaults to 0.5 when no actionable agents voted.
    """
    tier_score: dict[str, float] = {
        "clinical_trial": 1.0,
        "pharmacokinetic_study": 0.85,
        "observational": 0.7,
        "case_report_series": 0.55,
        "case_report": 0.4,
        "experimental": 0.55,
        "in_vivo": 0.5,
        "in_vitro": 0.3,
        "traditional": 0.2,
        "unknown": 0.1,
    }
    tiers = [e.evidence_tier for c in kg.chains for e in c.edges]
    evidence_tier = max((tier_score.get(t, 0.1) for t in tiers), default=0.1)

    # HDI risk: presence of safety-reviewer "reject" → 1.0, "caution" → 0.5
    hdi = 0.0
    for v in panel.verdicts:
        if v.role == "SafetyReviewer":
            if v.verdict == "reject":
                hdi = 1.0
            elif v.verdict == "caution":
                hdi = 0.5

    # Question fit: fraction of actionable role agents that issued "prefer"
    # (excludes Defer/Safety which operate outside the evidence-quality axis)
    actionable = [v for v in panel.verdicts if v.role not in {"DeferToClinician", "SafetyReviewer"}]
    if not actionable:
        question_fit = 0.5
    else:
        question_fit = sum(1 for v in actionable if v.verdict == "prefer") / len(actionable)

    return ConfidenceComponents(
        evidence_tier=evidence_tier,
        hdi_risk=hdi,
        question_fit=question_fit,
    )


if __name__ == "__main__":
    import sys

    spec = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("research-journal/shared/case_study_runs")
    s = run_case_study(spec, out)
    print(f"confidence={s.confidence:.3f} defer={s.defer_to_clinician}")
