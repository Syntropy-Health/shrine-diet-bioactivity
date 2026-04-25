# shrine-diet-bioactivity/agents/tests/test_calibrator.py
from agents.calibrator import compute_confidence  # type: ignore[import-not-found]
from agents.models import ConfidenceComponents


def test_confidence_increases_with_evidence_tier():
    low = compute_confidence(ConfidenceComponents(evidence_tier=0.2, hdi_risk=0.0, question_fit=0.5))
    high = compute_confidence(ConfidenceComponents(evidence_tier=0.9, hdi_risk=0.0, question_fit=0.5))
    assert high > low


def test_confidence_capped_by_hdi_risk():
    no_risk = compute_confidence(ConfidenceComponents(evidence_tier=0.9, hdi_risk=0.0, question_fit=0.9))
    severe  = compute_confidence(ConfidenceComponents(evidence_tier=0.9, hdi_risk=0.95, question_fit=0.9))
    assert severe < no_risk
    assert 0 <= severe <= 1


def test_confidence_bounds_satisfied():
    for et in (0.0, 0.5, 1.0):
        for hr in (0.0, 0.5, 1.0):
            for qf in (0.0, 0.5, 1.0):
                v = compute_confidence(ConfidenceComponents(evidence_tier=et, hdi_risk=hr, question_fit=qf))
                assert 0 <= v <= 1
