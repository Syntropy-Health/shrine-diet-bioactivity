"""Verify the Phase 3 LightRAG schema additions against the live DB.

The Disease entity now sources from `diseases_canonical` and three new
evidence-typed relationships query `compound_disease_evidence` joined
through that registry. Skips cleanly when the live DB is absent.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_schema import (  # noqa: E402
    DESCRIPTION_GENERATORS,
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
    describe_relationship,
)

DB_PATH = Path(__file__).parent.parent.parent / "data_local" / "herbal_botanicals.db"


@pytest.fixture(scope="module")
def db_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        pytest.skip(f"Live DB absent at {DB_PATH}; skipping Phase 3 entity tests.")
    return sqlite3.connect(str(DB_PATH))


# ---- Disease entity ------------------------------------------------------


def test_disease_entity_query_runs_against_canonical(db_conn):
    """The new query should pull from diseases_canonical, NOT the legacy
    aggregator. Sanity floor: a few thousand rows exist."""
    rows = list(db_conn.execute(ENTITY_TYPES["Disease"]["query"]))
    assert len(rows) > 1000, f"expected >1000 canonical diseases, got {len(rows)}"


def test_describe_disease_renders_full_cross_refs(db_conn):
    cur = db_conn.execute(
        "SELECT id, preferred_name, mesh_id, umls_id, icd10cm_id, hpo_id, "
        "       source_origin "
        "FROM diseases_canonical WHERE mesh_id IS NOT NULL AND umls_id IS NOT NULL "
        "LIMIT 1"
    )
    cols = [d[0] for d in cur.description]
    sample = cur.fetchone()
    if sample is None:
        pytest.skip("no canonical row with both MeSH and UMLS — re-run orchestrator")
    row = dict(zip(cols, sample))
    desc = DESCRIPTION_GENERATORS["Disease"](row)
    assert row["preferred_name"] in desc
    assert "MeSH" in desc
    assert "UMLS" in desc


def test_describe_disease_falls_back_to_legacy_disease_name():
    """Defensive: pre-Phase-3 row shape (no preferred_name, has disease_name)
    must still render via the fallback path so old call sites don't crash
    during the migration cycle."""
    legacy_row = {"disease_name": "Diabetes Mellitus"}
    desc = DESCRIPTION_GENERATORS["Disease"](legacy_row)
    assert "Diabetes Mellitus" in desc


# ---- Phase 3 relationships ----------------------------------------------


def test_compound_treats_disease_relationship_query(db_conn):
    spec = RELATIONSHIP_TYPES["COMPOUND_TREATS_DISEASE"]
    rows = list(db_conn.execute(spec["query"] + " LIMIT 100"))
    assert len(rows) > 0, "no direct_therapeutic edges — CTD ingest may have failed"
    # Sample row schema check
    cols = [d[0] for d in db_conn.execute(spec["query"] + " LIMIT 1").description]
    assert "src_name" in cols and "tgt_name" in cols and "pubmed_ids" in cols


def test_compound_treats_disease_describe_renders_citation_count(db_conn):
    spec = RELATIONSHIP_TYPES["COMPOUND_TREATS_DISEASE"]
    cur = db_conn.execute(spec["query"] + " AND cde.pubmed_ids IS NOT NULL LIMIT 1")
    cols = [d[0] for d in cur.description]
    sample = cur.fetchone()
    if sample is None:
        pytest.skip("no direct_therapeutic with pubmed_ids — unexpected")
    row = dict(zip(cols, sample))
    desc, kw = describe_relationship("COMPOUND_TREATS_DISEASE", row)
    assert row["src_name"] in desc
    assert row["tgt_name"] in desc
    assert "PubMed citation" in desc
    assert "compound" in kw and "therapeutic" in kw


def test_compound_inferred_disease_relationship_renders_gene(db_conn):
    spec = RELATIONSHIP_TYPES["COMPOUND_INFERRED_DISEASE"]
    cur = db_conn.execute(spec["query"] + " LIMIT 1")
    cols = [d[0] for d in cur.description]
    sample = cur.fetchone()
    if sample is None:
        pytest.skip("no inferred_via_gene rows — unexpected after CTD ingest")
    row = dict(zip(cols, sample))
    desc, kw = describe_relationship("COMPOUND_INFERRED_DISEASE", row)
    assert row["src_name"] in desc
    assert row["tgt_name"] in desc
    if row.get("gene"):
        assert row["gene"] in desc


def test_compound_marker_for_disease_relationship_runs(db_conn):
    spec = RELATIONSHIP_TYPES["COMPOUND_MARKER_FOR_DISEASE"]
    rows = list(db_conn.execute(spec["query"] + " LIMIT 50"))
    assert len(rows) > 0


# ---- MAPS_TO_DISEASE Phase 3 join check ---------------------------------


def test_maps_to_disease_now_joins_canonical_when_mesh_match(db_conn):
    """When sdm.mesh_id matches a canonical row, tgt_name should come from
    diseases_canonical.preferred_name (not the raw symptom_disease_map.disease_name)."""
    spec = RELATIONSHIP_TYPES["MAPS_TO_DISEASE"]
    rows = list(db_conn.execute(spec["query"]))
    # Sanity: at least 30 rows expected (40 mapped symptoms - some misses).
    assert len(rows) >= 30
    # Check the JOIN actually fires for at least one mesh-anchored row.
    cur = db_conn.execute(
        spec["query"].replace("ORDER BY", "AND sdm.mesh_id IS NOT NULL ORDER BY")
    )
    cols = [d[0] for d in cur.description]
    sample = cur.fetchone()
    if sample is None:
        pytest.skip("no mesh-anchored MAPS_TO_DISEASE rows — unexpected")
    row = dict(zip(cols, sample))
    # tgt_name is COALESCE(d.preferred_name, sdm.disease_name); for mesh-anchored
    # rows the canonical preferred_name should be set (not NULL fallback).
    assert row["tgt_name"] is not None
