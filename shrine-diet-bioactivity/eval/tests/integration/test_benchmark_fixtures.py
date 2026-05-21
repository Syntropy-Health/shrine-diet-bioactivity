"""Phase 4 — benchmark fixture sanity (Category D).

Plan ref: research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md
test #17 — test_dietresearchbench_v1_fixtures_well_formed.

Parametrized over all 40 DietResearchBench-Clinical v1 scenarios. Local-only
(reads the committed benchmark JSON) — no network, no LLM, marked
`integration`.

Guards against silent benchmark corruption: a scenario landing without a
gold record, without a resolvable source citation, or with an out-of-enum
category would otherwise only surface as a confusing eval-runtime failure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from eval.scenario import BenchmarkSet  # type: ignore[import-not-found]

pytestmark = [pytest.mark.integration]

_BENCH_PATH = (
    Path(__file__).resolve().parents[4]
    / "research-journal"
    / "shared"
    / "datasets"
    / "dietresearchbench_v1.json"
)

# The benchmark cites a deliberately diverse source base — PubMed PMIDs,
# DOIs, URLs, NCBI Bookshelf (LiverTox), MSK "About Herbs", internal
# HDI-panel IDs, and classical TCM texts (本草纲目 etc.). Rather than
# whitelist that whole taxonomy, this test guards the realistic failure
# mode: a scenario shipping with EMPTY or PLACEHOLDER citations.
_PLACEHOLDER = re.compile(
    r"\b(TODO|TBD|FIXME|XXX|citation needed|placeholder|stub)\b", re.IGNORECASE
)
_HAS_LETTER = re.compile(r"[A-Za-z一-鿿]")  # Latin or CJK
_MIN_CITATION_LEN = 8

_VALID_VERDICTS = frozenset({"prefer", "caution", "reject", "abstain"})
_VALID_COMPLEXITY = frozenset({"low", "moderate", "high"})
_VALID_CATEGORIES = frozenset(
    {"herbal_single_symptom", "nutrition", "multi_drug_hdi", "tcm_bilingual"}
)


def _load_scenarios() -> list:
    """Load + validate the benchmark at collection time. A malformed JSON or
    schema-invalid scenario fails fast here rather than mid-parametrization."""
    data = json.loads(_BENCH_PATH.read_text(encoding="utf-8"))
    return BenchmarkSet.model_validate(data).scenarios


@pytest.mark.parametrize("scenario", _load_scenarios(), ids=lambda s: s.id)
def test_dietresearchbench_v1_fixtures_well_formed(scenario) -> None:
    """Each benchmark scenario has a complete gold record + resolvable
    citations."""
    # --- gold present and within enums --------------------------------
    assert scenario.gold is not None, f"{scenario.id}: missing gold"
    assert scenario.gold.expected_panel_verdict in _VALID_VERDICTS, (
        f"{scenario.id}: bad verdict {scenario.gold.expected_panel_verdict!r}"
    )
    assert scenario.gold.expected_complexity in _VALID_COMPLEXITY, (
        f"{scenario.id}: bad complexity {scenario.gold.expected_complexity!r}"
    )
    assert scenario.gold.expected_min_chains >= 0, (
        f"{scenario.id}: negative expected_min_chains"
    )

    # --- category enum -------------------------------------------------
    assert scenario.category in _VALID_CATEGORIES, (
        f"{scenario.id}: bad category {scenario.category!r}"
    )

    # --- research question is non-trivial ------------------------------
    assert scenario.research_question.strip(), (
        f"{scenario.id}: empty research_question"
    )

    # --- >= 1 substantive source citation ------------------------------
    assert len(scenario.source_citations) >= 1, (
        f"{scenario.id}: no source_citations"
    )
    for cite in scenario.source_citations:
        text = cite.strip()
        assert len(text) >= _MIN_CITATION_LEN, (
            f"{scenario.id}: citation {cite!r} is too short to be substantive"
        )
        assert _HAS_LETTER.search(text), (
            f"{scenario.id}: citation {cite!r} has no alphabetic content"
        )
        assert not _PLACEHOLDER.search(text), (
            f"{scenario.id}: citation {cite!r} looks like a placeholder/stub"
        )
