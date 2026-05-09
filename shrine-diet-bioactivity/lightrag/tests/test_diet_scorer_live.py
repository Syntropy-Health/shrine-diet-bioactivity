"""Live-DB integration tests for diet_scorer (Phase 5 spec §5 DoD)."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from diet_scorer import score_diet  # noqa: E402

DB_PATH = Path(__file__).parent.parent.parent / "data_local" / "herbal_botanicals.db"


@pytest.fixture(scope="module")
def db_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        pytest.skip("live DB absent; skipping diet-scoring live tests")
    return sqlite3.connect(str(DB_PATH))


def test_score_diet_three_food_sample_returns_nonempty(db_conn):
    """Spec §5 DoD: a 3-food diet should return non-empty exposures + targets + diseases."""
    diet = [("Turmeric", 5), ("Ginger", 10), ("Broccoli", 100)]
    result = score_diet(diet, conn=db_conn)
    assert isinstance(result["exposures"], dict)
    assert len(result["exposures"]) > 0, "expected ≥1 compound exposure"
    assert isinstance(result["targets"], list)
    assert len(result["targets"]) > 0, "expected ≥1 ranked target"
    assert isinstance(result["diseases"], list)
    assert len(result["diseases"]) > 0, "expected ≥1 ranked disease"
    assert "disclaimer" in result


def test_score_diet_disease_has_mesh_anchored_entry(db_conn):
    """At least one ranked disease should be MeSH-anchored (disease_id starts with 'mesh:')."""
    diet = [("Turmeric", 5), ("Ginger", 10)]
    result = score_diet(diet, conn=db_conn)
    mesh_diseases = [
        d for d in result["diseases"] if d["disease_id"].startswith("mesh:")
    ]
    assert len(mesh_diseases) > 0, (
        f"no MeSH-anchored diseases in top {len(result['diseases'])}: "
        f"{[d['disease_id'] for d in result['diseases']][:5]}"
    )


def test_score_diet_target_has_top_compounds(db_conn):
    """Target output should include top contributing compounds."""
    diet = [("Turmeric", 5), ("Ginger", 10), ("Broccoli", 100)]
    result = score_diet(diet, conn=db_conn)
    if not result["targets"]:
        pytest.skip("no targets to inspect")
    top_target = result["targets"][0]
    assert "top_compounds" in top_target
    assert len(top_target["top_compounds"]) > 0


def test_score_diet_warnings_for_unknown_food(db_conn):
    """An unknown food should produce a warning, not crash the scoring."""
    diet = [("Turmeric", 5), ("UnknownFakeFoodXYZ", 100)]
    result = score_diet(diet, conn=db_conn)
    assert any("UnknownFakeFoodXYZ" in w for w in result["warnings"])
    # Turmeric still produces exposures despite the unknown sibling.
    assert len(result["exposures"]) > 0


def test_score_diet_empty_diet_is_well_formed(db_conn):
    result = score_diet([], conn=db_conn)
    assert result["exposures"] == {}
    assert result["targets"] == []
    assert result["diseases"] == []
    assert result["pathways"] == []
    assert result["warnings"] == []
    assert "disclaimer" in result


def test_score_diet_disease_breakdown_has_pubmed_total(db_conn):
    """Each disease should report PubMed citation count (for explainability)."""
    diet = [("Turmeric", 5), ("Ginger", 10), ("Broccoli", 100)]
    result = score_diet(diet, conn=db_conn)
    if not result["diseases"]:
        pytest.skip("no diseases scored")
    breakdown = result["diseases"][0]["evidence_breakdown"]
    assert "pubmed_total" in breakdown
    assert isinstance(breakdown["pubmed_total"], int)


def test_score_diet_pathway_rollup_works_when_targets_exist(db_conn):
    """Pathway scores require both target hits AND KEGG pathway-target joins."""
    diet = [("Turmeric", 5), ("Ginger", 10), ("Broccoli", 100)]
    result = score_diet(diet, conn=db_conn)
    # Pathways may legitimately be empty if none of our hit targets are in KEGG;
    # just assert the field exists and has the right shape.
    assert isinstance(result["pathways"], list)
    if result["pathways"]:
        assert "kegg_id" in result["pathways"][0]
        assert "n_targets_hit" in result["pathways"][0]
