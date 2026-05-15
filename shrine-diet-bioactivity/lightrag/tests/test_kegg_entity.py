"""Verify Phase 4 KEGG additions to entity_schema against the live DB."""

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
        pytest.skip("live DB absent; skipping Phase 4 entity tests")
    return sqlite3.connect(str(DB_PATH))


# ---- Pathway entity ------------------------------------------------------


def test_pathway_entity_query_runs(db_conn):
    rows = list(db_conn.execute(ENTITY_TYPES["Pathway"]["query"]))
    assert len(rows) >= 300, f"expected ≥300 pathways, got {len(rows)}"


def test_describe_pathway_renders_kegg_id():
    desc = DESCRIPTION_GENERATORS["Pathway"](
        {
            "id": "hsa01100",
            "name": "Metabolic pathways",
            "organism": "hsa",
            "category": None,
            "source": "kegg",
        }
    )
    assert "Metabolic pathways" in desc
    assert "KEGG ID: hsa01100" in desc
    assert "organism: hsa" in desc


# ---- PATHWAY_INCLUDES_TARGET ---------------------------------------------


def test_pathway_includes_target_query_returns_rows(db_conn):
    spec = RELATIONSHIP_TYPES["PATHWAY_INCLUDES_TARGET"]
    rows = list(db_conn.execute(spec["query"] + " LIMIT 100"))
    assert len(rows) > 0, "no pathway-target joins — KEGG ingest may have failed"


def test_pathway_includes_target_describe_renders_gene(db_conn):
    spec = RELATIONSHIP_TYPES["PATHWAY_INCLUDES_TARGET"]
    cur = db_conn.execute(spec["query"] + " LIMIT 1")
    cols = [d[0] for d in cur.description]
    sample = cur.fetchone()
    if sample is None:
        pytest.skip("no PATHWAY_INCLUDES_TARGET rows")
    row = dict(zip(cols, sample))
    desc, kw = describe_relationship("PATHWAY_INCLUDES_TARGET", row)
    assert row["src_name"] in desc
    assert row["tgt_name"] in desc
    if row.get("gene_symbol"):
        assert row["gene_symbol"] in desc
    assert "pathway" in kw and "gene" in kw


# ---- COMPOUND_IN_PATHWAY (lazy — empty until Phase 1 ingest) -------------


def test_compound_in_pathway_query_runs_even_if_empty(db_conn):
    """Returns 0 rows until compound_identity is populated by Phase 1.
    The query must still execute cleanly — the spec-defined laziness is
    the whole point of decoupling Phase 1 and Phase 4."""
    spec = RELATIONSHIP_TYPES["COMPOUND_IN_PATHWAY"]
    # Just confirm it runs without error; row count is environment-dependent.
    rows = list(db_conn.execute(spec["query"] + " LIMIT 5"))
    assert isinstance(rows, list)


def test_compound_in_pathway_describe_renders_kegg_id():
    """Pure-logic description test; doesn't depend on live data."""
    desc, kw = describe_relationship(
        "COMPOUND_IN_PATHWAY",
        {
            "src_name": "Curcumin",
            "tgt_name": "NF-kappa B signaling pathway",
            "pathway_id": "hsa04064",
        },
    )
    assert "Curcumin" in desc
    assert "NF-kappa B signaling pathway" in desc
    assert "hsa04064" in desc
    assert "compound" in kw and "pathway" in kw
