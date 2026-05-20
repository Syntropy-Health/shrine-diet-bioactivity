"""Phase 4 — paper-grade results-artifact validation (Category D).

Plan ref: research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md
test #18 — test_paper_grade_results_artifacts_valid.

Parametrized over the 240 per-prediction JSONs in the paper-grade results
directory (6 systems x 40 scenarios). Local-only — reads committed
artifacts, no network, marked `integration`.

Each prediction JSON is a serialized ResearchSynthesis. The eval reporting
pipeline (eval.report) depends on a fixed set of fields; a prediction that
deserializes but is missing a field would produce a confusing report-time
crash. This test makes that STRUCTURAL contract explicit.

Note: the plan named the required fields "verdict, confidence,
mechanism_chain, sources". The actual ResearchSynthesis schema uses
`panel.verdicts[*].verdict`, top-level `confidence`, `candidate_chains`
(the mechanism evidence), and `candidate_chains[*].edges[*].source_id`
(the provenance / sources). This test asserts against the real schema.

Empty panels are VALID and expected: 45 of the 240 paper-grade
predictions are rate-limit (HTTP 429) error cases from the original eval
run — `panel.verdicts == []`, `panel.moderator_summary == "error"`, the
429 body captured in `panel.dissent`. These are structurally-valid
ResearchSynthesis objects (`_majority_verdict` falls back to "abstain"),
so this test validates structure, not panel completeness.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

# Paper-grade run: 6 systems x 40 scenarios. The final-7sys directory is a
# multi-source re-render with no per-prediction JSONs of its own, so this
# canonical single-source run is used instead.
_PAPER_GRADE_DIR = (
    Path(__file__).resolve().parents[4]
    / "research-journal"
    / "shared"
    / "results"
    / "20260504T042540Z"
)

_VALID_VERDICTS = frozenset({"prefer", "caution", "reject", "abstain"})


def _prediction_files() -> list[Path]:
    """Per-prediction JSONs live at <dir>/<system>/<case-id>.json. Excludes
    the per_system/<sys>/per_metric.json aggregates and the run manifest."""
    if not _PAPER_GRADE_DIR.is_dir():
        return []
    return sorted(
        p
        for p in _PAPER_GRADE_DIR.glob("*/*.json")
        if p.name != "per_metric.json" and not p.name.startswith("manifest")
    )


_PRED_FILES = _prediction_files()


@pytest.mark.skipif(
    not _PRED_FILES, reason=f"paper-grade results dir not present: {_PAPER_GRADE_DIR}"
)
@pytest.mark.parametrize(
    "pred_path", _PRED_FILES, ids=lambda p: f"{p.parent.name}/{p.stem}"
)
def test_paper_grade_results_artifacts_valid(pred_path: Path) -> None:
    """Every per-prediction JSON carries the fields eval.report consumes."""
    data = json.loads(pred_path.read_text(encoding="utf-8"))
    label = f"{pred_path.parent.name}/{pred_path.name}"

    # --- required top-level fields ------------------------------------
    for field in (
        "question",
        "triage",
        "panel",
        "confidence",
        "components",
        "candidate_chains",
        "defer_to_clinician",
    ):
        assert field in data, f"{label}: missing top-level field {field!r}"

    # --- confidence in [0, 1] -----------------------------------------
    conf = data["confidence"]
    assert isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0, (
        f"{label}: confidence {conf!r} out of [0, 1]"
    )

    # --- panel structure: verdicts/dissent are lists, moderator_summary
    #     a str. verdicts MAY be empty (rate-limit error predictions);
    #     each verdict that IS present must carry a known label.
    panel = data["panel"]
    assert isinstance(panel.get("verdicts"), list), (
        f"{label}: panel.verdicts is not a list"
    )
    assert isinstance(panel.get("dissent"), list), (
        f"{label}: panel.dissent is not a list"
    )
    assert isinstance(panel.get("moderator_summary"), str), (
        f"{label}: panel.moderator_summary is not a str"
    )
    for rv in panel["verdicts"]:
        assert rv.get("verdict") in _VALID_VERDICTS, (
            f"{label}: role {rv.get('role')!r} has bad verdict "
            f"{rv.get('verdict')!r}"
        )

    # --- defer flag is a real boolean ---------------------------------
    assert isinstance(data["defer_to_clinician"], bool), (
        f"{label}: defer_to_clinician is "
        f"{type(data['defer_to_clinician']).__name__}, expected bool"
    )

    # --- mechanism evidence: candidate_chains is a list; any edge that
    #     is present must carry a source_id (provenance). Baseline systems
    #     and error predictions legitimately produce zero chains.
    chains = data["candidate_chains"]
    assert isinstance(chains, list), f"{label}: candidate_chains is not a list"
    for chain in chains:
        for edge in chain.get("edges", []):
            assert "source_id" in edge, (
                f"{label}: a candidate_chains edge is missing source_id"
            )
