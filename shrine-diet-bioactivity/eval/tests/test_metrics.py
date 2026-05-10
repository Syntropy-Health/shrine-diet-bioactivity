"""Tests for eval/metrics.py — six headline metrics for DietResearchBench-Clinical.

Coverage target: 5+ tests per metric = 30+ total.

Test strategy:
  - Identity/perfect case  → exact expected value
  - Adversarial case       → value at extreme
  - Edge case              → empty list, single element, all-same-class
  - Boundary / NaN         → NaN returned when metric is undefined
  - Synthetic 5+-scenario  → known ground truth verified against hand calculation
"""
from __future__ import annotations

import math
from typing import Any

import pytest

from agents.models import (  # type: ignore[import-not-found]
    ConfidenceComponents,
    KGEdge,
    PanelDeliberation,
    ProvenanceChain,
    ResearchQuestion,
    ResearchSynthesis,
    RoleVerdict,
    Triage,
)
from eval.metrics import (  # type: ignore[import-not-found]
    bilingual_coverage,
    defer_accuracy,
    expected_calibration_error,
    hdi_safety_recall,
    provenance_faithfulness,
    verdict_agreement_kappa,
)
from eval.scenario import GoldStandard, Scenario  # type: ignore[import-not-found]

pytestmark = [pytest.mark.unit]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_pred(
    verdict: str = "prefer",
    confidence: float = 0.5,
    defer: bool = False,
    chains: list[ProvenanceChain] | None = None,
) -> ResearchSynthesis:
    """Construct a minimal ResearchSynthesis for testing."""
    return ResearchSynthesis(
        question=ResearchQuestion(text="test question"),
        triage=Triage(complexity="low", rationale="test", red_flags=[]),
        candidate_chains=chains or [],
        panel=PanelDeliberation(
            verdicts=[
                RoleVerdict(
                    role="Dietitian",
                    verdict=verdict,  # type: ignore[arg-type]
                    support=[],
                    concerns=[],
                    notes="",
                )
            ],
            dissent=[],
            moderator_summary="test",
        ),
        confidence=confidence,
        components=ConfidenceComponents(evidence_tier=0.5, hdi_risk=0.0, question_fit=0.5),
        defer_to_clinician=defer,
    )


def _mk_pred_no_verdict() -> ResearchSynthesis:
    """Prediction with empty panel — should produce majority verdict 'abstain'."""
    return ResearchSynthesis(
        question=ResearchQuestion(text="test question"),
        triage=Triage(complexity="low", rationale="test", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(verdicts=[], dissent=[], moderator_summary=""),
        confidence=0.0,
        components=ConfidenceComponents(evidence_tier=0.0, hdi_risk=0.0, question_fit=0.0),
        defer_to_clinician=False,
    )


def _mk_scen(
    verdict: str = "prefer",
    category: str = "herbal_single_symptom",
    hdi_severity: str = "none",
    expected_defer: bool = False,
    languages: list[str] | None = None,
) -> Scenario:
    """Construct a minimal Scenario for testing."""
    return Scenario(
        id="test-scenario",
        category=category,  # type: ignore[arg-type]
        research_question="Does test herb reduce test symptom?",
        gold=GoldStandard(
            expected_complexity="low",
            expected_panel_verdict=verdict,  # type: ignore[arg-type]
            expected_evidence_tier="clinical_trial",
            expected_min_chains=1,
            expected_defer=expected_defer,
            expected_red_flags=[],
            expected_hdi_severity=hdi_severity,  # type: ignore[arg-type]
            languages=languages or ["en"],
        ),
        rationale="test",
        source_citations=[],
    )


def _mk_chain(*edge_tuples: tuple[str, str, str]) -> ProvenanceChain:
    """Build a ProvenanceChain from (src, edge, tgt) tuples."""
    edges = [
        KGEdge(src=s, edge=e, tgt=t, source_id="test", weight=1.0, evidence_tier="unknown")
        for s, e, t in edge_tuples
    ]
    return ProvenanceChain(edges=edges)


# ---------------------------------------------------------------------------
# 1. verdict_agreement_kappa
# ---------------------------------------------------------------------------


class TestVerdictAgreementKappa:
    def test_perfect_agreement_binary(self):
        """Perfect agreement on two distinct labels → kappa = 1.0."""
        preds = [_mk_pred("prefer"), _mk_pred("reject")]
        scens = [_mk_scen("prefer"), _mk_scen("reject")]
        assert verdict_agreement_kappa(preds, scens) == pytest.approx(1.0)

    def test_perfect_agreement_all_same_label_returns_nan(self):
        """When all instances share one label, cohen_kappa_score returns NaN.

        This is the correct mathematical behavior: kappa's denominator
        (1 - P_e) is 0 when all predictions and all gold labels are identical,
        making the score undefined. The metric should propagate NaN rather than
        masking this degenerate input.
        """
        preds = [_mk_pred("caution")] * 4
        scens = [_mk_scen("caution")] * 4
        result = verdict_agreement_kappa(preds, scens)
        assert math.isnan(result)

    def test_complete_disagreement_returns_negative_or_zero(self):
        """Systematic reversal should produce kappa <= 0."""
        # prefer vs reject, caution vs abstain — maximally wrong
        preds = [_mk_pred("reject"), _mk_pred("prefer"), _mk_pred("abstain"), _mk_pred("caution")]
        scens = [_mk_scen("prefer"), _mk_scen("reject"), _mk_scen("caution"), _mk_scen("abstain")]
        kappa = verdict_agreement_kappa(preds, scens)
        assert kappa <= 0.0

    def test_empty_panel_counted_as_abstain(self):
        """A prediction with no verdicts must be counted as 'abstain'.

        When all preds and gold are 'abstain', the degenerate all-same-label
        case applies and kappa is NaN — but the important invariant to test
        is that empty panel maps to 'abstain', not some other label.
        We verify this by mixing with a 'prefer' prediction so kappa is defined.
        """
        preds = [_mk_pred_no_verdict(), _mk_pred("prefer")]
        scens = [_mk_scen("abstain"), _mk_scen("prefer")]
        # Both correct → kappa == 1.0
        assert verdict_agreement_kappa(preds, scens) == pytest.approx(1.0)

    def test_five_scenario_synthetic_known_kappa(self):
        """4-of-5 correct with known class distribution.

        preds:  prefer, prefer, reject, caution, abstain
        gold:   prefer, prefer, reject, caution, prefer

        Confusion matrix (gold=rows, pred=cols):
          prefer:  2 correct, 1 wrong (as abstain)
          reject:  1 correct
          caution: 1 correct
          abstain: 0
        Expected kappa > 0.6 (high agreement minus one error).
        """
        preds = [
            _mk_pred("prefer"),
            _mk_pred("prefer"),
            _mk_pred("reject"),
            _mk_pred("caution"),
            _mk_pred("abstain"),  # wrong — gold is "prefer"
        ]
        scens = [
            _mk_scen("prefer"),
            _mk_scen("prefer"),
            _mk_scen("reject"),
            _mk_scen("caution"),
            _mk_scen("prefer"),
        ]
        kappa = verdict_agreement_kappa(preds, scens)
        assert kappa > 0.6

    def test_all_four_labels_represented(self):
        """Kappa computed correctly across all 4 verdict labels."""
        preds = [_mk_pred("prefer"), _mk_pred("caution"), _mk_pred("reject"), _mk_pred("abstain")]
        scens = [_mk_scen("prefer"), _mk_scen("caution"), _mk_scen("reject"), _mk_scen("abstain")]
        assert verdict_agreement_kappa(preds, scens) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. expected_calibration_error
# ---------------------------------------------------------------------------


class TestExpectedCalibrationError:
    def test_perfect_calibration_returns_zero(self):
        """If every prediction is correct AND confidence == 1.0, ECE = 0."""
        preds = [_mk_pred("prefer", confidence=1.0)] * 5
        scens = [_mk_scen("prefer")] * 5
        assert expected_calibration_error(preds, scens) == pytest.approx(0.0)

    def test_worst_case_calibration(self):
        """Wrong prediction with confidence 1.0 → ECE = 1.0 (single bin, gap=1)."""
        preds = [_mk_pred("reject", confidence=1.0)]  # wrong — gold is prefer
        scens = [_mk_scen("prefer")]
        ece = expected_calibration_error(preds, scens)
        assert ece == pytest.approx(1.0)

    def test_empty_predictions_returns_zero(self):
        """No predictions → ECE defaults to 0.0 (no data, no error)."""
        assert expected_calibration_error([], []) == pytest.approx(0.0)

    def test_single_correct_mid_confidence(self):
        """1 correct prediction with confidence 0.5 → ECE = |1.0 - 0.5| = 0.5."""
        preds = [_mk_pred("prefer", confidence=0.5)]
        scens = [_mk_scen("prefer")]
        ece = expected_calibration_error(preds, scens)
        assert ece == pytest.approx(0.5)

    def test_10_pred_toy_set_hand_calculated(self):
        """10 predictions across two confidence levels — hand-calculated ECE.

        Setup:
          5 predictions at confidence=0.8: all correct (verdict=prefer, gold=prefer)
          5 predictions at confidence=0.2: all wrong  (verdict=reject, gold=prefer)

        With n_bins=10:
          Bin [0.2, 0.3): 5 items, mean_conf=0.2, accuracy=0.0, gap=0.2, weight=5/10=0.5
          Bin [0.8, 0.9): 5 items, mean_conf=0.8, accuracy=1.0, gap=0.2, weight=5/10=0.5

        ECE = 0.5 * 0.2 + 0.5 * 0.2 = 0.2
        """
        preds = (
            [_mk_pred("prefer", confidence=0.8)] * 5
            + [_mk_pred("reject", confidence=0.2)] * 5
        )
        scens = [_mk_scen("prefer")] * 10
        ece = expected_calibration_error(preds, scens, n_bins=10)
        assert ece == pytest.approx(0.2, abs=1e-6)

    def test_boundary_confidence_1_included_in_last_bin(self):
        """Confidence exactly 1.0 must land in the [0.9, 1.0] bin (not overflow)."""
        preds = [_mk_pred("prefer", confidence=1.0)] * 3
        scens = [_mk_scen("prefer")] * 3
        # All correct, conf=1.0, in last bin → ECE = 0
        assert expected_calibration_error(preds, scens) == pytest.approx(0.0)

    def test_mixed_correctness_within_single_bin(self):
        """Same confidence bin, half correct → gap = |0.5 - conf|."""
        # Both at confidence=0.9, one correct, one wrong
        preds = [_mk_pred("prefer", confidence=0.9), _mk_pred("reject", confidence=0.9)]
        scens = [_mk_scen("prefer"), _mk_scen("prefer")]
        ece = expected_calibration_error(preds, scens, n_bins=10)
        # mean_conf=0.9, accuracy=0.5, gap=0.4, weight=1.0
        assert ece == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# 3. hdi_safety_recall
# ---------------------------------------------------------------------------


class TestHdiSafetyRecall:
    def test_nan_when_no_severe_hdi_scenarios(self):
        """Returns NaN when no severe-HDI scenarios in eval set."""
        preds = [_mk_pred("prefer")]
        scens = [_mk_scen(category="multi_drug_hdi", hdi_severity="none")]
        result = hdi_safety_recall(preds, scens)
        assert math.isnan(result)

    def test_nan_on_empty_list(self):
        """Empty input → NaN (undefined)."""
        result = hdi_safety_recall([], [])
        assert math.isnan(result)

    def test_perfect_recall_via_reject_verdict(self):
        """100% recall when all severe-HDI cases flagged with 'reject'."""
        preds = [_mk_pred("reject")] * 3
        scens = [_mk_scen(category="multi_drug_hdi", hdi_severity="severe")] * 3
        assert hdi_safety_recall(preds, scens) == pytest.approx(1.0)

    def test_perfect_recall_via_defer_flag(self):
        """100% recall when all severe-HDI cases flagged via defer_to_clinician=True."""
        preds = [_mk_pred("prefer", defer=True)] * 3
        scens = [_mk_scen(category="multi_drug_hdi", hdi_severity="severe")] * 3
        assert hdi_safety_recall(preds, scens) == pytest.approx(1.0)

    def test_zero_recall(self):
        """0% recall when no severe-HDI case is flagged."""
        preds = [_mk_pred("prefer", defer=False)] * 4
        scens = [_mk_scen(category="multi_drug_hdi", hdi_severity="severe")] * 4
        assert hdi_safety_recall(preds, scens) == pytest.approx(0.0)

    def test_partial_recall(self):
        """2 of 4 flagged → recall = 0.5."""
        preds = [
            _mk_pred("reject"),         # flagged
            _mk_pred("prefer", defer=True),  # flagged
            _mk_pred("prefer"),         # missed
            _mk_pred("caution"),        # missed
        ]
        scens = [_mk_scen(category="multi_drug_hdi", hdi_severity="severe")] * 4
        assert hdi_safety_recall(preds, scens) == pytest.approx(0.5)

    def test_filters_only_severe_scenarios(self):
        """Non-severe scenarios should be excluded from the denominator."""
        preds = [
            _mk_pred("prefer"),   # severe → flagged: no
            _mk_pred("reject"),   # moderate → excluded
            _mk_pred("reject"),   # severe → flagged: yes
        ]
        scens = [
            _mk_scen(category="multi_drug_hdi", hdi_severity="severe"),
            _mk_scen(category="multi_drug_hdi", hdi_severity="moderate"),
            _mk_scen(category="multi_drug_hdi", hdi_severity="severe"),
        ]
        # 1 of 2 severe cases flagged → 0.5
        assert hdi_safety_recall(preds, scens) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 4. provenance_faithfulness
# ---------------------------------------------------------------------------


class TestProvenanceFaithfulness:
    def test_no_edges_returns_one(self):
        """No edges in predictions → perfect faithfulness (vacuous truth)."""
        preds = [_mk_pred("prefer")]  # no chains
        result = provenance_faithfulness(preds, cypher_runner=lambda s, e, t: True)
        assert result == pytest.approx(1.0)

    def test_all_edges_verified_returns_one(self):
        """All edges round-trip → 1.0."""
        chain = _mk_chain(("ginger", "treats", "nausea"))
        preds = [_mk_pred("prefer", chains=[chain])]
        result = provenance_faithfulness(preds, cypher_runner=lambda s, e, t: True)
        assert result == pytest.approx(1.0)

    def test_no_edges_verified_returns_zero(self):
        """No edges round-trip → 0.0."""
        chain = _mk_chain(("ginger", "treats", "nausea"))
        preds = [_mk_pred("prefer", chains=[chain])]
        result = provenance_faithfulness(preds, cypher_runner=lambda s, e, t: False)
        assert result == pytest.approx(0.0)

    def test_partial_faithfulness(self):
        """2 edges total, 1 verified → 0.5."""
        chain = _mk_chain(("ginger", "treats", "nausea"), ("ginger", "inhibits", "vomiting"))
        preds = [_mk_pred("prefer", chains=[chain])]
        calls: list[tuple[str, str, str]] = []

        def runner(s: str, e: str, t: str) -> bool:
            calls.append((s, e, t))
            return s == "ginger" and e == "treats"  # only first edge verified

        result = provenance_faithfulness(preds, cypher_runner=runner)
        assert result == pytest.approx(0.5)
        assert len(calls) == 2

    def test_multiple_predictions_edges_aggregated(self):
        """Edges from all predictions are counted together."""
        chain_a = _mk_chain(("a", "r", "b"))
        chain_b = _mk_chain(("c", "r", "d"), ("e", "r", "f"))
        preds = [
            _mk_pred("prefer", chains=[chain_a]),
            _mk_pred("prefer", chains=[chain_b]),
        ]
        # 3 total edges, only chain_a edge verified (src="a")
        result = provenance_faithfulness(
            preds,
            cypher_runner=lambda s, e, t: s == "a",
        )
        assert result == pytest.approx(1 / 3)

    def test_cypher_runner_called_with_correct_args(self):
        """Verify cypher_runner receives (src, edge, tgt) from KGEdge correctly."""
        chain = _mk_chain(("herb-x", "interacts_with", "drug-y"))
        preds = [_mk_pred("prefer", chains=[chain])]
        received: list[Any] = []

        def runner(s: str, e: str, t: str) -> bool:
            received.extend([s, e, t])
            return True

        provenance_faithfulness(preds, cypher_runner=runner)
        assert received == ["herb-x", "interacts_with", "drug-y"]


# ---------------------------------------------------------------------------
# 5. defer_accuracy
# ---------------------------------------------------------------------------


class TestDeferAccuracy:
    def test_perfect_accuracy(self):
        """All defer flags correct → 1.0."""
        preds = [_mk_pred(defer=False), _mk_pred(defer=True)]
        scens = [_mk_scen(expected_defer=False), _mk_scen(expected_defer=True)]
        assert defer_accuracy(preds, scens) == pytest.approx(1.0)

    def test_zero_accuracy(self):
        """All defer flags wrong → 0.0."""
        preds = [_mk_pred(defer=True), _mk_pred(defer=False)]
        scens = [_mk_scen(expected_defer=False), _mk_scen(expected_defer=True)]
        assert defer_accuracy(preds, scens) == pytest.approx(0.0)

    def test_empty_predictions_returns_nan(self):
        """Empty list → NaN (undefined)."""
        result = defer_accuracy([], [])
        assert math.isnan(result)

    def test_single_correct(self):
        """Single correct defer → 1.0."""
        assert defer_accuracy([_mk_pred(defer=True)], [_mk_scen(expected_defer=True)]) == pytest.approx(1.0)

    def test_single_incorrect(self):
        """Single incorrect defer → 0.0."""
        assert defer_accuracy([_mk_pred(defer=False)], [_mk_scen(expected_defer=True)]) == pytest.approx(0.0)

    def test_five_scenario_partial_accuracy(self):
        """3 of 5 correct → 0.6."""
        preds = [
            _mk_pred(defer=False),  # correct
            _mk_pred(defer=True),   # correct
            _mk_pred(defer=False),  # correct
            _mk_pred(defer=True),   # wrong (gold=False)
            _mk_pred(defer=False),  # wrong (gold=True)
        ]
        scens = [
            _mk_scen(expected_defer=False),
            _mk_scen(expected_defer=True),
            _mk_scen(expected_defer=False),
            _mk_scen(expected_defer=False),
            _mk_scen(expected_defer=True),
        ]
        assert defer_accuracy(preds, scens) == pytest.approx(0.6)

    def test_all_same_value_correct(self):
        """All non-defer, all gold non-defer → 1.0."""
        preds = [_mk_pred(defer=False)] * 6
        scens = [_mk_scen(expected_defer=False)] * 6
        assert defer_accuracy(preds, scens) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 6. bilingual_coverage
# ---------------------------------------------------------------------------


def _mk_cjk_chain() -> ProvenanceChain:
    """Chain with a CJK-named source entity."""
    return _mk_chain(("当归", "treats", "anemia"))


def _mk_latin_chain() -> ProvenanceChain:
    """Chain with only ASCII entities."""
    return _mk_chain(("ginger", "treats", "nausea"))


class TestBilingualCoverage:
    def test_nan_when_no_tcm_bilingual_scenarios(self):
        """Returns NaN when no tcm_bilingual scenarios in eval set."""
        preds = [_mk_pred("prefer")]
        scens = [_mk_scen(category="herbal_single_symptom")]
        result = bilingual_coverage(preds, scens)
        assert math.isnan(result)

    def test_nan_on_empty_list(self):
        """Empty input → NaN."""
        result = bilingual_coverage([], [])
        assert math.isnan(result)

    def test_full_coverage_with_cjk_in_src(self):
        """All TCM scenarios have CJK in src entity → 1.0."""
        preds = [_mk_pred("prefer", chains=[_mk_cjk_chain()])] * 3
        scens = [_mk_scen(category="tcm_bilingual")] * 3
        assert bilingual_coverage(preds, scens) == pytest.approx(1.0)

    def test_zero_coverage_latin_only(self):
        """All TCM scenarios have only ASCII chains → 0.0."""
        preds = [_mk_pred("prefer", chains=[_mk_latin_chain()])] * 3
        scens = [_mk_scen(category="tcm_bilingual")] * 3
        assert bilingual_coverage(preds, scens) == pytest.approx(0.0)

    def test_zero_coverage_empty_chains(self):
        """TCM scenarios with no chains at all → 0.0 (no CJK entity found)."""
        preds = [_mk_pred("prefer")] * 3  # no chains
        scens = [_mk_scen(category="tcm_bilingual")] * 3
        assert bilingual_coverage(preds, scens) == pytest.approx(0.0)

    def test_partial_coverage(self):
        """2 of 4 TCM predictions have CJK → 0.5."""
        preds = [
            _mk_pred("prefer", chains=[_mk_cjk_chain()]),
            _mk_pred("prefer", chains=[_mk_cjk_chain()]),
            _mk_pred("prefer", chains=[_mk_latin_chain()]),
            _mk_pred("prefer"),  # no chains
        ]
        scens = [_mk_scen(category="tcm_bilingual")] * 4
        assert bilingual_coverage(preds, scens) == pytest.approx(0.5)

    def test_cjk_in_tgt_entity_counts(self):
        """CJK character in the target entity also qualifies."""
        chain = _mk_chain(("ginger", "used_for", "消化不良"))
        preds = [_mk_pred("prefer", chains=[chain])]
        scens = [_mk_scen(category="tcm_bilingual")]
        assert bilingual_coverage(preds, scens) == pytest.approx(1.0)

    def test_only_tcm_bilingual_category_counted(self):
        """Non-TCM scenarios are excluded from the denominator."""
        preds = [
            _mk_pred("prefer", chains=[_mk_cjk_chain()]),  # tcm → counted
            _mk_pred("prefer", chains=[_mk_cjk_chain()]),  # herbal → excluded
            _mk_pred("prefer"),                             # tcm → counted, no cjk
        ]
        scens = [
            _mk_scen(category="tcm_bilingual"),
            _mk_scen(category="herbal_single_symptom"),
            _mk_scen(category="tcm_bilingual"),
        ]
        # 1 of 2 tcm_bilingual predictions have CJK → 0.5
        assert bilingual_coverage(preds, scens) == pytest.approx(0.5)
