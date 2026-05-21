"""Shared helpers for `eval/tests/integration/`. Plain module (not a
pytest-collected conftest) so the test files can import it without
relying on pytest's internal conftest collection mechanics.
"""

from __future__ import annotations

from eval.scenario import Verdict  # type: ignore[import-not-found]


def assert_confidence_consistent_with_verdict(
    verdict: Verdict, confidence: float
) -> None:
    """Verdict-direction-aware sanity bound on calibrator output.

    The calibrator (agents/calibrator.compute_confidence) is a deterministic
    weighted geometric mean of (evidence_tier, 1 - hdi_risk, question_fit).
    The result is "confidence the intervention is safe / recommended,"
    NOT "confidence the verdict is right." That asymmetry matters:

      - "prefer" verdict → high evidence + low HDI risk → confidence should be
        nontrivial (>= 0.3 with the current weights and any non-empty signal).
      - "reject" verdict → high HDI risk dominates the product → confidence
        should be low (<= 0.5); a "reject" with confidence 0.9 means the
        calibrator inverted.
      - "caution" / "abstain" → middle ground: confidence must be strictly
        positive. The calibrator is a weighted geometric mean — an exact 0.0
        means one component collapsed to 0 (a calibrator bug), which is
        never a correct output for a panel that reached a verdict.

    These bounds catch calibrator-direction regressions without false-failing
    correct-but-low-confidence outcomes (e.g., the SJW+sertraline case).
    """
    assert 0.0 <= confidence <= 1.0, f"confidence out of [0,1]: {confidence}"
    if verdict == "prefer":
        assert confidence >= 0.3, (
            f"prefer verdict but confidence={confidence:.3f} (expected >= 0.3); "
            "calibrator may be inverting evidence_tier weighting"
        )
    elif verdict == "reject":
        assert confidence <= 0.5, (
            f"reject verdict but confidence={confidence:.3f} (expected <= 0.5); "
            "calibrator may be ignoring hdi_risk signal"
        )
    else:  # caution / abstain
        assert confidence > 0.0, (
            f"{verdict} verdict but confidence is exactly 0.0 — the "
            "weighted-geometric-mean calibrator collapsed (a component hit 0)"
        )
