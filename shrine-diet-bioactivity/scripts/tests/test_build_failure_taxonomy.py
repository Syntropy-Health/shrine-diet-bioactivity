"""Unit tests for failure-mode classification logic."""
import sys
from pathlib import Path

import pytest

# Bootstrap so this test can import scripts/build_failure_taxonomy.py
_REPO = Path(__file__).resolve().parents[2]  # shrine-diet-bioactivity/
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.build_failure_taxonomy import _classify_failure  # type: ignore[import-not-found]

pytestmark = [pytest.mark.unit]


def _gold(verdict: str = "prefer") -> dict:
    return {"expected_panel_verdict": verdict}


def _pred(
    triage_rationale: str = "ok",
    chains: list | None = None,
    verdicts: list | None = None,
    confidence: float = 0.5,
) -> dict:
    return {
        "triage": {"rationale": triage_rationale},
        "candidate_chains": chains if chains is not None else [{"edges": [{}]}],
        "panel": {"verdicts": verdicts if verdicts is not None else []},
        "confidence": confidence,
    }


def test_classify_runner_error_triage_returns_json_validation_failure():
    pred = _pred(triage_rationale="runner-error: LightRAG unreachable")
    assert _classify_failure(pred, _gold("prefer")) == "json_validation_failure"


def test_classify_empty_chains_returns_retrieval_empty():
    pred = _pred(chains=[])
    assert _classify_failure(pred, _gold()) == "retrieval_empty"


def test_classify_panel_mis_vote_when_majority_diverges_from_gold():
    pred = _pred(
        verdicts=[{"verdict": "caution"}, {"verdict": "caution"}, {"verdict": "prefer"}],
    )
    assert _classify_failure(pred, _gold("prefer")) == "panel_mis_vote"


def test_classify_calibrator_under_confidence():
    pred = _pred(
        verdicts=[{"verdict": "prefer"}],
        confidence=0.05,
    )
    assert _classify_failure(pred, _gold("prefer")) == "calibrator_under_confidence"


def test_classify_returns_none_on_success():
    pred = _pred(
        verdicts=[{"verdict": "prefer"}],
        confidence=0.5,
    )
    assert _classify_failure(pred, _gold("prefer")) is None


def test_classify_handles_no_verdicts():
    """If panel produced no verdicts (empty list), pred_verdict is None and
    can't equal gold's expected verdict — classify as panel_mis_vote."""
    pred = _pred(verdicts=[], confidence=0.5)
    assert _classify_failure(pred, _gold("prefer")) == "panel_mis_vote"
