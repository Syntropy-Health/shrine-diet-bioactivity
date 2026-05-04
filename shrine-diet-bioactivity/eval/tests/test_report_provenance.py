"""Test for the source-attribution-based cypher_runner factory."""
import pytest


KNOWN_PREFIXES = ("cmaup:", "duke:", "herb2:", "symmap:", "hdi-safe-50:")


def test_source_attribution_runner_accepts_known_kg_prefix():
    """Edges whose source_id starts with a known KG dataset prefix
    are trusted as KG-faithful (the bundle pulled them from the live KG)."""
    from eval.report import build_source_attribution_runner  # type: ignore[import-not-found]

    chains_with_sources = {
        ("Curcuma longa", "CONTAINS_COMPOUND", "CURCUMIN"): "duke:contains_compound",
        ("CURCUMIN", "TARGETS_PROTEIN", "COX-2"): "cmaup:compound_target",
        ("Ginger", "FOUND_IN_FOOD", "GINGEROL"): "duke:found_in_food",
    }
    runner = build_source_attribution_runner(chains_with_sources)

    assert runner("Curcuma longa", "CONTAINS_COMPOUND", "CURCUMIN") is True
    assert runner("CURCUMIN", "TARGETS_PROTEIN", "COX-2") is True


def test_source_attribution_runner_rejects_unknown_source():
    """Edges with unknown or empty source_id are rejected — these are
    LLM-emitted or hallucinated edges, not KG-faithful."""
    from eval.report import build_source_attribution_runner

    chains_with_sources = {
        ("X", "BOGUS", "Y"): "llm:hallucinated",
        ("A", "MADE_UP", "B"): "",
    }
    runner = build_source_attribution_runner(chains_with_sources)

    assert runner("X", "BOGUS", "Y") is False
    assert runner("A", "MADE_UP", "B") is False


def test_source_attribution_runner_rejects_unmapped_edge():
    """Edges not present in the precomputed map are rejected (defensive)."""
    from eval.report import build_source_attribution_runner

    runner = build_source_attribution_runner({})
    assert runner("any", "edge", "missing") is False


def test_source_attribution_runner_accepts_all_known_prefixes():
    """All five canonical KG dataset prefixes are accepted."""
    from eval.report import build_source_attribution_runner

    chains = {
        ("a", "REL", "b"): "cmaup:plant_disease",
        ("c", "REL", "d"): "duke:found_in_food",
        ("e", "REL", "f"): "herb2:herb_disease",
        ("g", "REL", "h"): "symmap:tcm_symptom",
        ("i", "REL", "j"): "hdi-safe-50:cyp450",
    }
    runner = build_source_attribution_runner(chains)
    for src, edge, tgt in chains:
        assert runner(src, edge, tgt) is True, f"{src} {edge} {tgt} should be accepted"


@pytest.mark.parametrize("bad_prefix", ["mcp:something", "openai:hallucinated", "unknown:"])
def test_source_attribution_runner_rejects_non_canonical_prefix(bad_prefix):
    from eval.report import build_source_attribution_runner

    chains = {("a", "REL", "b"): bad_prefix}
    runner = build_source_attribution_runner(chains)
    assert runner("a", "REL", "b") is False
