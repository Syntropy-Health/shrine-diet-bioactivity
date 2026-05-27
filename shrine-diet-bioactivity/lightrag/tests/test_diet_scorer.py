"""Pure-logic tests for diet_scorer (Phase 5 / spec §4.2)."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from diet_scorer import (  # noqa: E402
    EVIDENCE_WEIGHTS,
    aggregate_exposures,
    citation_factor,
    score_diseases,
    score_pathways,
    score_targets,
)


# ---- citation_factor ----------------------------------------------------


def test_citation_factor_zero_citations_is_one():
    assert citation_factor(0) == 1.0


def test_citation_factor_grows_logarithmically():
    """Within the cap range, factor follows 1 + log10(1 + n)."""
    f5 = citation_factor(5)
    f20 = citation_factor(20)
    assert f20 > f5
    # 1 + log10(21) ≈ 2.322 (well below the 3.0 cap)
    assert abs(f20 - (1 + math.log10(21))) < 1e-6


def test_citation_factor_capped_at_3():
    """Heavy-citation diseases (e.g., Cancer with 5K+ rows) shouldn't dominate."""
    assert citation_factor(10_000) == 3.0
    assert citation_factor(1_000_000) == 3.0


def test_citation_factor_negative_is_one():
    assert citation_factor(-5) == 1.0


# ---- aggregate_exposures (Stage 1) --------------------------------------


def test_aggregate_exposures_simple_single_food():
    """5g of Turmeric × (curcumin at 14400 mg/100g = 144 mg/g) = 720 mg curcumin."""
    diet = [("Turmeric", 5)]
    rows = [
        # (food_name, compound_id, content_value, content_unit)
        ("Turmeric", "curcumin", 14400.0, "mg/100g"),
        ("Turmeric", "turmerone", 200.0, "mg/100g"),
    ]
    result = aggregate_exposures(diet, rows)
    assert result["exposures"]["curcumin"] == pytest.approx(720.0)
    assert result["exposures"]["turmerone"] == pytest.approx(10.0)
    assert result["warnings"] == []


def test_aggregate_exposures_aggregates_across_foods_for_same_compound():
    """A compound found in two foods accumulates exposure across both."""
    diet = [("Turmeric", 5), ("Curry", 100)]
    rows = [
        ("Turmeric", "curcumin", 14400.0, "mg/100g"),  # 720 mg
        ("Curry", "curcumin", 200.0, "mg/100g"),  # 200 mg
    ]
    result = aggregate_exposures(diet, rows)
    assert result["exposures"]["curcumin"] == pytest.approx(920.0)


def test_aggregate_exposures_skips_unsupported_unit_with_warning():
    diet = [("Spinach", 100)]
    rows = [
        ("Spinach", "lutein", 12.0, "mg/100g"),  # 12 mg
        ("Spinach", "vit_e", 2.0, "α-TE"),  # unsupported
    ]
    result = aggregate_exposures(diet, rows)
    assert result["exposures"]["lutein"] == pytest.approx(12.0)
    assert "vit_e" not in result["exposures"]
    assert any("α-TE" in w for w in result["warnings"])


def test_aggregate_exposures_warns_on_food_not_in_db():
    diet = [("Turmeric", 5), ("UnknownFood", 100)]
    rows = [("Turmeric", "curcumin", 14400.0, "mg/100g")]
    result = aggregate_exposures(diet, rows)
    assert "curcumin" in result["exposures"]
    assert any("UnknownFood" in w for w in result["warnings"])


def test_aggregate_exposures_rejects_negative_grams():
    diet = [("Turmeric", -5)]
    rows = [("Turmeric", "curcumin", 14400.0, "mg/100g")]
    with pytest.raises(ValueError, match="negative"):
        aggregate_exposures(diet, rows)


def test_aggregate_exposures_dedups_duplicate_foods():
    """Two entries for the same food should sum (not silently overwrite)."""
    diet = [("Turmeric", 5), ("Turmeric", 3)]
    rows = [("Turmeric", "curcumin", 14400.0, "mg/100g")]
    result = aggregate_exposures(diet, rows)
    # 8g total × 144 mg/g = 1152
    assert result["exposures"]["curcumin"] == pytest.approx(1152.0)


def test_aggregate_exposures_empty_diet_returns_empty():
    result = aggregate_exposures([], [])
    assert result["exposures"] == {}
    assert result["warnings"] == []


# ---- score_targets (Stage 2 / 3) ----------------------------------------


def test_score_targets_aggregates_per_target():
    exposures = {"curcumin": 720.0, "gingerol": 50.0}
    target_rows = [
        # (compound_id, target_id, target_name)
        ("curcumin", "T1", "NF-kappa-B p65"),
        ("gingerol", "T1", "NF-kappa-B p65"),
        ("curcumin", "T2", "COX-2"),
    ]
    out = score_targets(exposures, target_rows)
    nfkb = next(r for r in out if r["target"] == "NF-kappa-B p65")
    cox2 = next(r for r in out if r["target"] == "COX-2")
    # NF-kB: (720 + 50) × 1.0 weight = 770
    assert nfkb["score"] == pytest.approx(770.0)
    # COX-2: 720 × 1.0
    assert cox2["score"] == pytest.approx(720.0)
    assert nfkb["evidence_count"] == 2
    assert cox2["evidence_count"] == 1


def test_score_targets_top_compounds_ranked():
    exposures = {"curcumin": 720.0, "gingerol": 50.0}
    target_rows = [
        ("curcumin", "T1", "NF-kappa-B p65"),
        ("gingerol", "T1", "NF-kappa-B p65"),
    ]
    out = score_targets(exposures, target_rows)
    nfkb = out[0]
    # Top contributor first: curcumin (720) > gingerol (50)
    assert nfkb["top_compounds"][0] == "curcumin"


def test_score_targets_orders_by_score_descending():
    exposures = {"a": 100.0, "b": 50.0}
    target_rows = [
        ("a", "T1", "Low"),
        ("b", "T2", "High"),
        ("a", "T2", "High"),
    ]
    out = score_targets(exposures, target_rows)
    # T2 = 100+50 = 150, T1 = 100
    assert out[0]["target"] == "High"
    assert out[1]["target"] == "Low"


def test_score_targets_skips_compounds_not_in_exposures():
    exposures = {"curcumin": 100.0}
    target_rows = [("curcumin", "T1", "Hit"), ("missing", "T2", "Skip")]
    out = score_targets(exposures, target_rows)
    assert {r["target"] for r in out} == {"Hit"}


# ---- score_diseases ------------------------------------------------------


def test_score_diseases_breakdown_per_evidence_type():
    exposures = {"curcumin": 100.0}
    cde_rows = [
        # (compound_id, disease_id, disease_name, evidence_type, pubmed_ids)
        ("curcumin", "D1", "Inflammation", "direct_therapeutic", "111|222"),
        ("curcumin", "D1", "Inflammation", "inferred_via_gene", None),
        ("curcumin", "D2", "Cancer", "direct_marker", "999"),
    ]
    out = score_diseases(exposures, cde_rows)
    infl = next(r for r in out if r["disease"] == "Inflammation")
    # direct_therapeutic (0.9 weight) + inferred (0.5) for the same disease.
    # citation factor for D1: 1 + log10(1+2) ≈ 1.477 from the 2-citation row;
    # the inferred row has 0 citations → factor 1.0
    assert infl["evidence_breakdown"]["direct_therapeutic"] == 1
    assert infl["evidence_breakdown"]["inferred_via_gene"] == 1
    assert infl["evidence_breakdown"]["pubmed_total"] == 2


def test_score_diseases_uses_evidence_weights():
    """A direct_therapeutic row should outweigh an inferred_via_gene row at
    same exposure + same citations."""
    exposures = {"x": 100.0}
    rows_direct = [("x", "D1", "Foo", "direct_therapeutic", None)]
    rows_inferred = [("x", "D1", "Foo", "inferred_via_gene", None)]
    score_direct = score_diseases(exposures, rows_direct)[0]["score"]
    score_inferred = score_diseases(exposures, rows_inferred)[0]["score"]
    assert score_direct > score_inferred


def test_score_diseases_citation_factor_boosts_score():
    exposures = {"x": 100.0}
    rows_zero = [("x", "D1", "Foo", "direct_therapeutic", None)]
    rows_many = [("x", "D1", "Foo", "direct_therapeutic", "1|2|3|4|5|6|7|8|9|10")]
    s_zero = score_diseases(exposures, rows_zero)[0]["score"]
    s_many = score_diseases(exposures, rows_many)[0]["score"]
    assert s_many > s_zero


# ---- score_pathways -----------------------------------------------------


def test_score_pathways_rolls_up_target_scores_via_membership():
    """Pathways aggregate the scores of their member targets."""
    target_scores = [
        {"target_id": "T1", "target": "NFKB", "score": 100.0},
        {"target_id": "T2", "target": "COX2", "score": 50.0},
    ]
    kpg_rows = [
        # (kegg_pathway_id, pathway_name, gene_symbol→target join already done)
        ("hsa04064", "NF-kappa B signaling", "T1"),
        ("hsa04064", "NF-kappa B signaling", "T2"),
        ("hsa04668", "TNF signaling", "T1"),
    ]
    out = score_pathways(target_scores, kpg_rows)
    nfkb_path = next(r for r in out if r["kegg_id"] == "hsa04064")
    tnf_path = next(r for r in out if r["kegg_id"] == "hsa04668")
    # Pathway scores apply PATHWAY_MEMBERSHIP_WEIGHT (0.60) per ADR 0010 §4.2:
    #   NFκB:  (100 + 50)  × 0.60 =  90.0
    #   TNF:   100         × 0.60 =  60.0
    assert nfkb_path["score"] == pytest.approx(90.0)
    assert nfkb_path["n_targets_hit"] == 2
    assert tnf_path["score"] == pytest.approx(60.0)


def test_score_pathways_with_no_target_scores_returns_empty():
    out = score_pathways([], [])
    assert out == []


# ---- evidence weights are constants (single tuning point) ---------------


def test_evidence_weights_documented():
    """The weights are public constants — change them in one place only."""
    assert "direct_therapeutic" in EVIDENCE_WEIGHTS
    assert "direct_marker" in EVIDENCE_WEIGHTS
    assert "inferred_via_gene" in EVIDENCE_WEIGHTS
    # Direct therapeutic should be the highest disease-layer weight.
    assert EVIDENCE_WEIGHTS["direct_therapeutic"] > EVIDENCE_WEIGHTS["direct_marker"]
    assert EVIDENCE_WEIGHTS["direct_marker"] > EVIDENCE_WEIGHTS["inferred_via_gene"]
    # All disease-layer weights below 1.0 (target binding is the gold).
    for k in ("direct_therapeutic", "direct_marker", "inferred_via_gene"):
        assert 0.0 < EVIDENCE_WEIGHTS[k] < 1.0


# ---- Issue #64: target_id_via_gene contract ----------------------------


def test_score_pathways_target_id_via_gene_is_target_id_not_gene_symbol():
    """``kpg_rows`` third element MUST be a ``targets.id`` value, not a
    gene_symbol. The upstream SQL joins ``kegg_pathway_genes`` ↔ ``targets``
    via gene_symbol, but the column passed to ``score_pathways`` is the
    resolved target_id. Passing a gene_symbol silently misses the score
    lookup (regression guard for #64).
    """
    target_scores = [{"target_id": "T1", "target": "NFKB1", "score": 100.0}]
    # Pass the *gene symbol* (NFKB1) where target_id (T1) is expected.
    kpg_rows = [("hsa04064", "NF-kB", "NFKB1")]
    out = score_pathways(target_scores, kpg_rows)
    assert out == [], (
        "score_pathways looked up gene_symbol as if it were target_id — "
        "the docstring contract is broken (#64)."
    )
