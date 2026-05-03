"""Pre-fetched KG retrieval orchestrator.

The panel cannot rely on free-tier Nemotron to invoke tools (smoke ran 2
panel rounds, panel produced valid RoleVerdict JSONs that *claimed* tool
use in their notes but emitted zero AG2 tool_calls — see
`research-journal/shared/e2-panel-mcp-wiring-results.md`).

This module pre-fetches a deterministic KG retrieval bundle from the
PICO components extracted by triage. The bundle is injected into the
moderator_input as structured JSON; panel agents reason over the
pre-fetched chains and cite them by index in `cited_chains`.

Tool selection logic:
  - Always: kg_compound_to_targets and kg_diet_to_compounds + kg_herb_to_*
    on the intervention seed (resilient — any subset can return empty).
  - If `comparator` looks like a drug AND `intervention` looks like a herb:
    kg_hdi_check.
  - If question contains CN characters or `tcm` keyword: kg_bilingual_term.

Per-tool failures are caught and surfaced in `errors` so a single broken
tool doesn't abort the bundle.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

from agents.models import (  # type: ignore[import-not-found]
    KGEdge, KGResult, ResearchQuestion, Triage,
)
from agents.models import ProvenanceChain as _LocalProvenanceChain  # type: ignore[import-not-found]
from agents.tools import kg_tools  # type: ignore[import-not-found]

# Local KGEdge.evidence_tier is a Literal — MCP may return any string. Coerce.
_LOCAL_EVIDENCE_TIERS = {
    "clinical_trial", "pharmacokinetic_study", "observational",
    "case_report_series", "case_report",
    "experimental", "in_vivo", "in_vitro",
    "traditional", "unknown",
}


class KGRetrievalBundle(BaseModel):
    """Pre-fetched KG context injected into the moderator input.

    Each Optional[X] field carries the typed result of one MCP tool call,
    or None if that tool wasn't applicable / returned empty / errored.
    `errors` records per-tool failure messages so reviewers can audit.
    """
    # Layer-B traversals (compound-side)
    compound_to_targets: kg_tools.TraversalOutput | None = None
    compound_to_symptoms: kg_tools.TraversalOutput | None = None
    compound_to_diseases: kg_tools.TraversalOutput | None = None

    # Layer-B traversals (herb / food side)
    herb_to_diseases: kg_tools.TraversalOutput | None = None
    herb_to_symptoms: kg_tools.TraversalOutput | None = None
    diet_to_compounds: kg_tools.TraversalOutput | None = None

    # Layer-C lookups
    hdi_check: kg_tools.HDICheckOutput | None = None
    bilingual: kg_tools.BilingualTermOutput | None = None

    # Telemetry
    seeds_used: dict[str, str] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)

    def total_chains(self) -> int:
        return sum(
            len(getattr(self, f).chains)
            for f in ("compound_to_targets", "compound_to_symptoms",
                      "compound_to_diseases", "herb_to_diseases",
                      "herb_to_symptoms", "diet_to_compounds")
            if getattr(self, f) is not None
        )

    def is_empty(self) -> bool:
        return self.total_chains() == 0 and self.hdi_check is None and self.bilingual is None


# Compound-name heuristic: strings like "CURCUMIN", "EPIGALLOCATECHIN-GALLATE",
# or with chemical suffixes -OL/-IDE/-ATE/-INE in uppercase.
_COMPOUND_RE = re.compile(r"^[A-Z][A-Z0-9\-,]+[A-Z0-9]$")
_CN_CHAR_RE = re.compile(r"[一-鿿]")


def _looks_like_compound(s: str) -> bool:
    """Heuristic: chemical name in upper/title case with no spaces, OR a
    title-case word that ends in -in/-ol/-one/-ide/-ate (curcumin, gingerol).
    Matches before falling back to herb interpretation."""
    s = (s or "").strip()
    if not s:
        return False
    if " " in s:
        return False
    if _COMPOUND_RE.match(s):
        return True
    lower_suffixes = ("ol", "ic acid", "ide", "ate", "in", "ine", "one")
    return s.lower().endswith(lower_suffixes)


def _has_cn(text: str) -> bool:
    return bool(_CN_CHAR_RE.search(text))


def _extract_cn_token(text: str) -> str | None:
    m = _CN_CHAR_RE.search(text)
    if not m:
        return None
    # Grab the maximal contiguous run of CN characters around the match.
    start = m.start()
    end = m.end()
    while start > 0 and _CN_CHAR_RE.match(text[start - 1]):
        start -= 1
    while end < len(text) and _CN_CHAR_RE.match(text[end]):
        end += 1
    return text[start:end]


def _safe_call(name: str, fn, *args, **kwargs) -> tuple[Any, str | None]:
    """Call fn(*args, **kwargs) returning (result_or_none, error_message_or_none).

    Per code review I3: also logs the failure at WARNING so server-side
    operators see partial-bundle issues even if the caller doesn't inspect
    bundle.errors. Preserves the project rule "Log detailed context server-side".
    """
    try:
        out = fn(*args, **kwargs)
        return out, None
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        _log.warning("retrieval._safe_call(%r) failed: %s", name, msg)
        return None, msg[:300]


def retrieve_for_question(
    rq: ResearchQuestion,
    triage: Triage | None = None,  # noqa: ARG001 — reserved for triage-driven branching
    top_k: int = 10,
) -> KGRetrievalBundle:
    """Dispatch deterministic Layer-B/C tool calls per PICO components.

    Returns a populated KGRetrievalBundle. Per-tool errors are captured
    in bundle.errors rather than raised — the bundle is always returned.
    """
    bundle = KGRetrievalBundle()

    intervention = (rq.intervention or "").strip()
    comparator = (rq.comparator or "").strip()
    full_text = " ".join(filter(None, [
        rq.text, rq.intervention, rq.outcome, rq.population, rq.comparator,
    ]))

    if not intervention:
        bundle.errors["intervention"] = "no intervention extracted by triage; bundle stays empty"
        return bundle

    bundle.seeds_used["intervention"] = intervention
    if comparator:
        bundle.seeds_used["comparator"] = comparator

    # --- compound vs herb branch --------------------------------------------
    if _looks_like_compound(intervention):
        # Compound path: targets + diseases + symptoms (all auto-uppercased).
        ct, err = _safe_call("compound_to_targets",
                             kg_tools.kg_compound_to_targets, intervention, top_k=top_k)
        bundle.compound_to_targets = ct
        if err: bundle.errors["compound_to_targets"] = err

        cd, err = _safe_call("compound_to_diseases",
                             kg_tools.kg_compound_to_diseases, intervention, top_k=top_k)
        bundle.compound_to_diseases = cd
        if err: bundle.errors["compound_to_diseases"] = err

        cs, err = _safe_call("compound_to_symptoms",
                             kg_tools.kg_compound_to_symptoms, intervention, top_k=top_k)
        bundle.compound_to_symptoms = cs
        if err: bundle.errors["compound_to_symptoms"] = err
    else:
        # Herb / food path: try herb-side first, then food-side as fallback.
        hd, err = _safe_call("herb_to_diseases",
                             kg_tools.kg_herb_to_diseases, intervention, top_k=top_k)
        bundle.herb_to_diseases = hd
        if err: bundle.errors["herb_to_diseases"] = err

        hs, err = _safe_call("herb_to_symptoms",
                             kg_tools.kg_herb_to_symptoms, intervention, top_k=top_k)
        bundle.herb_to_symptoms = hs
        if err: bundle.errors["herb_to_symptoms"] = err

        dc, err = _safe_call("diet_to_compounds",
                             kg_tools.kg_diet_to_compounds, intervention, top_k=top_k)
        bundle.diet_to_compounds = dc
        if err: bundle.errors["diet_to_compounds"] = err

    # --- HDI check ---------------------------------------------------------
    if comparator and intervention:
        hdi, err = _safe_call("hdi_check",
                              kg_tools.kg_hdi_check, comparator, intervention)
        bundle.hdi_check = hdi
        if err: bundle.errors["hdi_check"] = err

    # --- bilingual lookup --------------------------------------------------
    cn_tok = _extract_cn_token(full_text)
    if cn_tok:
        bundle.seeds_used["bilingual_cn"] = cn_tok
        b, err = _safe_call("bilingual", kg_tools.kg_bilingual_term, cn_tok)
        bundle.bilingual = b
        if err: bundle.errors["bilingual"] = err
    elif "tcm" in full_text.lower() or any(
        rq.languages and "zh" in lang for lang in (rq.languages or [])
    ):
        # Try the intervention name itself as a bilingual seed (for Latin name → CN/Pinyin)
        bundle.seeds_used["bilingual_intervention"] = intervention
        b, err = _safe_call("bilingual", kg_tools.kg_bilingual_term, intervention)
        bundle.bilingual = b
        if err: bundle.errors["bilingual"] = err

    return bundle


def flatten_bundle_to_kg_result(bundle: KGRetrievalBundle) -> KGResult:
    """Convert MCP-shape chains in the bundle into the local KGResult shape
    so eval/metrics.py can read them via synthesis.candidate_chains.

    Field mapping (the rename in I1 keeps these layers visually distinct):
      MCP MCPEdge.src_id   → local KGEdge.src
      MCP MCPEdge.tgt_id   → local KGEdge.tgt
      MCP MCPEdge.rel_type → local KGEdge.edge
      MCP MCPEdge.source_id, evidence_tier → preserved
      weight is set to 1.0 (MCP schema has no weight field)

    Empty traversals are skipped (local ProvenanceChain enforces min_length=1).
    """
    chains: list[_LocalProvenanceChain] = []
    total_edges = 0
    for field in (
        "compound_to_targets", "compound_to_symptoms", "compound_to_diseases",
        "herb_to_diseases", "herb_to_symptoms", "diet_to_compounds",
    ):
        result = getattr(bundle, field)
        if result is None:
            continue
        for ch in result.chains:
            if not ch.edges:
                continue
            local_edges = [
                KGEdge(
                    src=e.src_id,
                    edge=e.rel_type,
                    tgt=e.tgt_id,
                    source_id=e.source_id or f"mcp:{field}",
                    weight=1.0,
                    evidence_tier=(
                        e.evidence_tier  # type: ignore[arg-type]
                        if e.evidence_tier in _LOCAL_EVIDENCE_TIERS
                        else "unknown"
                    ),
                )
                for e in ch.edges
            ]
            chains.append(_LocalProvenanceChain(edges=local_edges))
            total_edges += len(local_edges)
    return KGResult(
        chains=chains,
        raw_subgraph_node_count=0,
        raw_subgraph_edge_count=total_edges,
        query_mode="hybrid",
    )


def render_bundle_for_prompt(bundle: KGRetrievalBundle) -> str:
    """Serialize the bundle into a panel-friendly markdown block.

    Used by run_case_study to inject the pre-fetched evidence into the
    moderator_input. Roles cite chains by their index across the
    concatenated chains list.
    """
    if bundle.is_empty() and not bundle.errors:
        return "## KG Retrieval Bundle\n\n_(empty — no chains retrieved)_\n"

    lines = ["## KG Retrieval Bundle (pre-fetched)"]
    if bundle.seeds_used:
        seeds = ", ".join(f"{k}={v!r}" for k, v in bundle.seeds_used.items())
        lines.append(f"_Seeds: {seeds}_")

    chain_idx = 0
    for field in (
        "compound_to_targets", "compound_to_symptoms", "compound_to_diseases",
        "herb_to_diseases", "herb_to_symptoms", "diet_to_compounds",
    ):
        result = getattr(bundle, field)
        if result is None or not result.chains:
            continue
        lines.append(f"\n### {field} ({len(result.chains)} chains)")
        for ch in result.chains[:5]:  # cap rendered chains for prompt budget
            edges_str = " → ".join(
                f"{e.src_id} -[{e.rel_type}]-> {e.tgt_id}" for e in ch.edges
            )
            sources = sorted({e.source_id for e in ch.edges if e.source_id})
            lines.append(f"  [chain #{chain_idx}] {edges_str}  _(sources: {','.join(sources) or 'none'})_")
            chain_idx += 1

    if bundle.hdi_check is not None:
        h = bundle.hdi_check
        if h.found:
            lines.append(
                f"\n### kg_hdi_check\n  ⚠️ FOUND: severity={h.severity!r}, "
                f"mechanism={h.mechanism_class!r}, citations={h.citations}"
            )
        else:
            lines.append("\n### kg_hdi_check\n  found=False (no entry in HDI-Safe-50 panel)")

    if bundle.bilingual is not None:
        b = bundle.bilingual
        lines.append(
            f"\n### kg_bilingual_term\n  english={b.english!r}, chinese={b.chinese!r}, "
            f"pinyin={b.pinyin!r}, source={b.source}, confidence={b.confidence}"
        )

    if bundle.errors:
        lines.append("\n### Per-tool errors (non-fatal)")
        for tool, msg in bundle.errors.items():
            lines.append(f"  - {tool}: {msg}")

    return "\n".join(lines) + "\n"
