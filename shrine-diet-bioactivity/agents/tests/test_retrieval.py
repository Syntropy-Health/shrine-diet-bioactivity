"""Tests for agents.retrieval — deterministic pre-fetch orchestrator."""
from unittest.mock import patch

from agents.models import ResearchQuestion, Triage  # type: ignore[import-not-found]
from agents.retrieval import (  # type: ignore[import-not-found]
    KGRetrievalBundle, _looks_like_compound, render_bundle_for_prompt,
    retrieve_for_question,
)
from agents.tools.kg_tools import (  # type: ignore[import-not-found]
    BilingualTermOutput, HDICheckOutput, ProvenanceChain, ProvenanceEdge,
    TraversalOutput,
)


# ---------------------------------------------------------------------------
# heuristics
# ---------------------------------------------------------------------------

def test_looks_like_compound_uppercase_chemical():
    assert _looks_like_compound("CURCUMIN")
    assert _looks_like_compound("EPIGALLOCATECHIN-GALLATE")
    assert _looks_like_compound("BISDEMETHOXYCURCUMIN")


def test_looks_like_compound_chemical_suffix():
    assert _looks_like_compound("gingerol")
    assert _looks_like_compound("Curcumin")  # ends in "in"
    assert _looks_like_compound("acetate")


def test_looks_like_compound_rejects_herbs_and_sentences():
    assert not _looks_like_compound("Ginkgo biloba")     # space
    assert not _looks_like_compound("Curcuma longa")     # space
    assert not _looks_like_compound("Garlic")            # generic noun, no suffix
    assert not _looks_like_compound("")
    assert not _looks_like_compound("turmeric tea")


# ---------------------------------------------------------------------------
# retrieve_for_question — dispatch logic
# ---------------------------------------------------------------------------

def _empty_traversal() -> TraversalOutput:
    return TraversalOutput()


def _chain_traversal(src: str, tgt: str, rel: str = "TARGETS_PROTEIN") -> TraversalOutput:
    return TraversalOutput(
        chains=[ProvenanceChain(edges=[
            ProvenanceEdge(src_id=src, tgt_id=tgt, rel_type=rel, source_id="cmaup:1"),
        ])],
        seeds_resolved=[src],
        raw_subgraph_edge_count=1,
    )


def test_retrieve_dispatches_compound_path_when_intervention_looks_chemical():
    rq = ResearchQuestion(
        text="Does CURCUMIN modulate inflammation pathways?",
        intervention="CURCUMIN", outcome="inflammation modulation",
    )
    triage = Triage(complexity="moderate", rationale="t", red_flags=[])

    calls: list[str] = []

    def mk_compound_targets(seed: str, top_k: int = 20):  # noqa: ARG001
        calls.append("compound_to_targets")
        return _chain_traversal("CURCUMIN", "COX-2")

    def mk_compound_diseases(seed: str, top_k: int = 20):  # noqa: ARG001
        calls.append("compound_to_diseases")
        return _empty_traversal()

    def mk_compound_symptoms(seed: str, top_k: int = 20):  # noqa: ARG001
        calls.append("compound_to_symptoms")
        return _empty_traversal()

    with patch("agents.retrieval.kg_tools.kg_compound_to_targets", side_effect=mk_compound_targets), \
         patch("agents.retrieval.kg_tools.kg_compound_to_diseases", side_effect=mk_compound_diseases), \
         patch("agents.retrieval.kg_tools.kg_compound_to_symptoms", side_effect=mk_compound_symptoms), \
         patch("agents.retrieval.kg_tools.kg_herb_to_diseases") as p_hd, \
         patch("agents.retrieval.kg_tools.kg_herb_to_symptoms") as p_hs, \
         patch("agents.retrieval.kg_tools.kg_diet_to_compounds") as p_dc:
        bundle = retrieve_for_question(rq, triage)

    # compound branch fired
    assert "compound_to_targets" in calls
    assert "compound_to_diseases" in calls
    assert "compound_to_symptoms" in calls
    assert bundle.compound_to_targets is not None
    assert len(bundle.compound_to_targets.chains) == 1
    # herb-side tools NOT called
    p_hd.assert_not_called()
    p_hs.assert_not_called()
    p_dc.assert_not_called()


def test_retrieve_dispatches_herb_path_when_intervention_is_latin_name():
    rq = ResearchQuestion(
        text="Does Ginkgo biloba help cognition?",
        intervention="Ginkgo biloba", outcome="cognition",
    )
    triage = Triage(complexity="moderate", rationale="t", red_flags=[])

    with patch("agents.retrieval.kg_tools.kg_herb_to_diseases", return_value=_chain_traversal("Ginkgo biloba", "Dementia", "ASSOCIATED_WITH_DISEASE")), \
         patch("agents.retrieval.kg_tools.kg_herb_to_symptoms", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_diet_to_compounds", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_compound_to_targets") as p_ct:
        bundle = retrieve_for_question(rq, triage)

    assert bundle.herb_to_diseases is not None
    assert len(bundle.herb_to_diseases.chains) == 1
    assert bundle.compound_to_targets is None
    p_ct.assert_not_called()


def test_retrieve_calls_hdi_check_when_comparator_is_drug():
    rq = ResearchQuestion(
        text="Is Ginkgo biloba safe with warfarin?",
        intervention="Ginkgo biloba", comparator="Warfarin",
    )
    triage = Triage(complexity="high", rationale="t", red_flags=["anticoagulant_therapy"])

    hdi_hit = HDICheckOutput(
        found=True, severity="severe", mechanism_class="coagulation",
        evidence_tier="clinical", citations=["pmid:1"],
    )
    with patch("agents.retrieval.kg_tools.kg_herb_to_diseases", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_herb_to_symptoms", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_diet_to_compounds", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_hdi_check", return_value=hdi_hit) as p_hdi:
        bundle = retrieve_for_question(rq, triage)

    p_hdi.assert_called_once()
    assert bundle.hdi_check is not None
    assert bundle.hdi_check.found is True
    assert bundle.hdi_check.severity == "severe"


def test_retrieve_extracts_cn_token_for_bilingual_lookup():
    rq = ResearchQuestion(
        text="What does 黄连 (Huanglian) treat?",
        intervention="Coptidis Rhizoma",
    )
    bilingual = BilingualTermOutput(
        english="Coptidis Rhizoma", chinese="黄连", pinyin="Huanglian",
        confidence=1.0,
    )
    with patch("agents.retrieval.kg_tools.kg_herb_to_diseases", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_herb_to_symptoms", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_diet_to_compounds", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_bilingual_term", return_value=bilingual) as p_b:
        bundle = retrieve_for_question(rq, Triage(complexity="high", rationale="t", red_flags=[]))

    p_b.assert_called_once()
    args, _ = p_b.call_args
    # Either positional or keyword 'term' — accept both
    if args:
        assert args[0] == "黄连"
    assert bundle.bilingual is not None
    assert bundle.bilingual.chinese == "黄连"


def test_retrieve_surfaces_per_tool_errors_without_aborting():
    rq = ResearchQuestion(text="Does CURCUMIN target COX-2?", intervention="CURCUMIN")
    triage = Triage(complexity="moderate", rationale="t", red_flags=[])

    def boom(seed, top_k=20):  # noqa: ARG001
        raise RuntimeError("transient gateway down")

    with patch("agents.retrieval.kg_tools.kg_compound_to_targets", side_effect=boom), \
         patch("agents.retrieval.kg_tools.kg_compound_to_diseases", return_value=_empty_traversal()), \
         patch("agents.retrieval.kg_tools.kg_compound_to_symptoms", return_value=_empty_traversal()):
        bundle = retrieve_for_question(rq, triage)

    assert bundle.compound_to_targets is None
    assert "compound_to_targets" in bundle.errors
    assert "transient" in bundle.errors["compound_to_targets"]
    # Bundle still returned, other tools' results still present
    assert bundle.compound_to_diseases is not None


def test_retrieve_handles_empty_intervention():
    rq = ResearchQuestion(text="A vague question", intervention=None)
    triage = Triage(complexity="low", rationale="t", red_flags=[])
    bundle = retrieve_for_question(rq, triage)
    assert bundle.is_empty()
    assert "intervention" in bundle.errors


# ---------------------------------------------------------------------------
# render_bundle_for_prompt
# ---------------------------------------------------------------------------

def test_render_bundle_includes_chain_indices():
    bundle = KGRetrievalBundle(
        compound_to_targets=_chain_traversal("CURCUMIN", "COX-2"),
        seeds_used={"intervention": "CURCUMIN"},
    )
    rendered = render_bundle_for_prompt(bundle)
    assert "[chain #0]" in rendered
    assert "CURCUMIN" in rendered
    assert "COX-2" in rendered
    assert "TARGETS_PROTEIN" in rendered
    assert "intervention='CURCUMIN'" in rendered


def test_render_bundle_marks_hdi_severity():
    bundle = KGRetrievalBundle(hdi_check=HDICheckOutput(
        found=True, severity="severe", mechanism_class="CYP450",
        citations=["pmid:1"]),
    )
    rendered = render_bundle_for_prompt(bundle)
    assert "FOUND" in rendered
    assert "severe" in rendered
    assert "CYP450" in rendered


def test_render_bundle_handles_empty():
    bundle = KGRetrievalBundle()
    rendered = render_bundle_for_prompt(bundle)
    assert "empty" in rendered.lower()
