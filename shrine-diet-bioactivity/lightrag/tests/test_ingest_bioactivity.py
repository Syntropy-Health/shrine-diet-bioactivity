"""End-to-end check that bioactivity_evidence flows through extract_entities."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_schema import (  # noqa: E402
    DESCRIPTION_GENERATORS,
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
)


def _make_populated_db(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE compounds (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE targets (id TEXT PRIMARY KEY, name TEXT, uniprot_id TEXT,
                               gene_symbol TEXT, druggability_status TEXT);
        CREATE TABLE bioactivity_evidence (
          id INTEGER PRIMARY KEY,
          compound_id TEXT,
          chembl_compound_id TEXT,
          chembl_target_id TEXT,
          target_pref_name TEXT,
          target_type TEXT,
          target_organism TEXT,
          activity_type TEXT,
          relation TEXT,
          value REAL,
          units TEXT,
          pchembl REAL,
          assay_confidence INTEGER,
          chembl_doc_id TEXT,
          publication_year INTEGER
        );
        INSERT INTO compounds VALUES ('curcumin', 'Curcumin');
        INSERT INTO targets VALUES ('NPT1', 'Nuclear factor NF-kappa-B p65',
                                    'Q04206', 'RELA', 'Druggable');
        INSERT INTO bioactivity_evidence VALUES (
          1, 'curcumin', 'CHEMBL116438', 'CHEMBL1741221',
          'Nuclear factor NF-kappa-B p65', 'SINGLE PROTEIN', 'Homo sapiens',
          'IC50', '=', 5000.0, 'nM', 5.3, 8, 'CHEMBL1129589', 2018
        );
        """
    )
    conn.commit()
    return conn


def test_bioactivity_query_runs_against_real_schema(tmp_path):
    conn = _make_populated_db(tmp_path)
    et = ENTITY_TYPES["BioactivityEvidence"]
    rows = list(conn.execute(et["query"]))
    assert len(rows) == 1


def test_description_generator_renders_real_row(tmp_path):
    conn = _make_populated_db(tmp_path)
    cur = conn.execute(ENTITY_TYPES["BioactivityEvidence"]["query"])
    cols = [d[0] for d in cur.description]
    row = dict(zip(cols, cur.fetchone()))
    desc = DESCRIPTION_GENERATORS["BioactivityEvidence"](row)
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "IC50" in desc
    assert "CHEMBL116438" in desc


def test_has_evidence_relationship_query_joins_compounds(tmp_path):
    conn = _make_populated_db(tmp_path)
    spec = RELATIONSHIP_TYPES["HAS_EVIDENCE"]
    rows = list(conn.execute(spec["query"]))
    assert len(rows) == 1
    cols = [d[0] for d in conn.execute(spec["query"]).description]
    row = dict(zip(cols, rows[0]))
    assert row["src_name"] == "Curcumin"  # joined from compounds.name
    assert row["activity_type"] == "IC50"


def test_evidence_for_target_relationship_falls_back_when_target_missing(tmp_path):
    conn = _make_populated_db(tmp_path)
    spec = RELATIONSHIP_TYPES["EVIDENCE_FOR_TARGET"]
    rows = list(conn.execute(spec["query"]))
    assert len(rows) == 1
    cols = [d[0] for d in conn.execute(spec["query"]).description]
    row = dict(zip(cols, rows[0]))
    # COALESCE(t.name, be.target_pref_name) should resolve to the matching
    # targets.name when present.
    assert row["tgt_name"] == "Nuclear factor NF-kappa-B p65"
    assert row["confidence_score"] == 8
    assert row["year"] == 2018


def test_evidence_for_target_uses_pref_name_when_no_target_row(tmp_path):
    """When targets table is empty, the join must fall back to bioactivity_evidence.target_pref_name."""
    conn = _make_populated_db(tmp_path)
    conn.execute("DELETE FROM targets")
    conn.commit()
    spec = RELATIONSHIP_TYPES["EVIDENCE_FOR_TARGET"]
    rows = list(conn.execute(spec["query"]))
    cols = [d[0] for d in conn.execute(spec["query"]).description]
    row = dict(zip(cols, rows[0]))
    assert row["tgt_name"] == "Nuclear factor NF-kappa-B p65"
