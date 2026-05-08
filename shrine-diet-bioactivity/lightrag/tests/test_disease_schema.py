"""Schema invariant tests for the Phase 3 disease canonicalization tables.

Spins up an in-memory SQLite, applies the same DDL we add to
build-herbal-db.ts, and asserts the constraint behavior:

  - UNIQUE on mesh_id and umls_id (cross-source dedup)
  - CHECK on compound_disease_evidence.evidence_type ↔ inference fields
  - FK on disease_name_aliases.disease_id

Runs CI-safe — no live DB needed.
"""

import sqlite3

import pytest

DDL = """
CREATE TABLE compounds (id TEXT PRIMARY KEY, name TEXT);

CREATE TABLE diseases_canonical (
  id              TEXT PRIMARY KEY,
  preferred_name  TEXT NOT NULL,
  mesh_id         TEXT,
  umls_id         TEXT,
  icd10cm_id      TEXT,
  hpo_id          TEXT,
  source_origin   TEXT NOT NULL,
  created_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_dc_unique_mesh ON diseases_canonical(mesh_id) WHERE mesh_id IS NOT NULL;
CREATE UNIQUE INDEX idx_dc_unique_umls ON diseases_canonical(umls_id) WHERE umls_id IS NOT NULL;

CREATE TABLE disease_name_aliases (
  disease_id  TEXT NOT NULL,
  alias       TEXT NOT NULL,
  source      TEXT NOT NULL,
  PRIMARY KEY (disease_id, alias, source),
  FOREIGN KEY (disease_id) REFERENCES diseases_canonical(id)
);

CREATE TABLE compound_disease_evidence (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  compound_id            TEXT NOT NULL,
  disease_id             TEXT NOT NULL,
  evidence_type          TEXT NOT NULL,
  inference_gene_symbol  TEXT,
  inference_score        REAL,
  pubmed_ids             TEXT,
  source                 TEXT NOT NULL DEFAULT 'ctd',
  ingested_at            TEXT NOT NULL,
  FOREIGN KEY (compound_id) REFERENCES compounds(id),
  FOREIGN KEY (disease_id)  REFERENCES diseases_canonical(id),
  CHECK (
    (evidence_type IN ('direct_therapeutic', 'direct_marker')
       AND inference_gene_symbol IS NULL AND inference_score IS NULL)
    OR
    (evidence_type = 'inferred_via_gene' AND inference_score IS NOT NULL)
  )
);
"""


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    return conn


# ---- diseases_canonical ----------------------------------------------------


def test_unique_mesh_constraint_blocks_duplicate_mesh():
    conn = _make_db()
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('mesh:D003920','Diabetes','D003920',NULL,NULL,NULL,'ctd','now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO diseases_canonical VALUES "
            "('mesh:D003920-DUP','Diabetes 2','D003920',NULL,NULL,NULL,'symmap','now')"
        )


def test_unique_umls_constraint_blocks_duplicate_umls():
    conn = _make_db()
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('umls:C0011849','Diabetes',NULL,'C0011849',NULL,NULL,'ctd','now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO diseases_canonical VALUES "
            "('umls:C0011849-DUP','Diabetes',NULL,'C0011849',NULL,NULL,'symmap','now')"
        )


def test_null_mesh_and_umls_allows_multiple_rows():
    """Both UNIQUE indexes are partial (WHERE col IS NOT NULL) — local-slug
    rows with no formal IDs MUST coexist."""
    conn = _make_db()
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('local:foo','Foo Disease',NULL,NULL,NULL,NULL,'symmap','now')"
    )
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('local:bar','Bar Disease',NULL,NULL,NULL,NULL,'target_diseases','now')"
    )


# ---- compound_disease_evidence CHECK constraints --------------------------


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('mesh:D003920','Diabetes','D003920',NULL,NULL,NULL,'ctd','now')"
    )
    conn.execute("INSERT INTO compounds VALUES ('curcumin','Curcumin')")


def test_check_blocks_inferred_with_no_score():
    conn = _make_db()
    _seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO compound_disease_evidence "
            "(compound_id, disease_id, evidence_type, inference_gene_symbol, "
            " inference_score, pubmed_ids, ingested_at) "
            "VALUES ('curcumin','mesh:D003920','inferred_via_gene','MYC',NULL,NULL,'now')"
        )


def test_check_blocks_direct_with_score():
    conn = _make_db()
    _seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO compound_disease_evidence "
            "(compound_id, disease_id, evidence_type, inference_score, ingested_at) "
            "VALUES ('curcumin','mesh:D003920','direct_therapeutic',5.0,'now')"
        )


def test_check_blocks_unknown_evidence_type():
    conn = _make_db()
    _seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO compound_disease_evidence "
            "(compound_id, disease_id, evidence_type, ingested_at) "
            "VALUES ('curcumin','mesh:D003920','speculative','now')"
        )


def test_valid_direct_therapeutic_inserts_cleanly():
    conn = _make_db()
    _seed(conn)
    conn.execute(
        "INSERT INTO compound_disease_evidence "
        "(compound_id, disease_id, evidence_type, pubmed_ids, ingested_at) "
        "VALUES ('curcumin','mesh:D003920','direct_therapeutic','12345|67890','now')"
    )
    n = conn.execute("SELECT COUNT(*) FROM compound_disease_evidence").fetchone()[0]
    assert n == 1


def test_valid_inferred_via_gene_inserts_cleanly():
    conn = _make_db()
    _seed(conn)
    conn.execute(
        "INSERT INTO compound_disease_evidence "
        "(compound_id, disease_id, evidence_type, inference_gene_symbol, "
        " inference_score, ingested_at) "
        "VALUES ('curcumin','mesh:D003920','inferred_via_gene','MYC',4.31,'now')"
    )
    n = conn.execute("SELECT COUNT(*) FROM compound_disease_evidence").fetchone()[0]
    assert n == 1


# ---- FK on disease_name_aliases ------------------------------------------


def test_alias_fk_blocks_orphan():
    conn = _make_db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO disease_name_aliases VALUES "
            "('mesh:DOES-NOT-EXIST','Bogus','ctd')"
        )


def test_alias_pk_dedups_same_disease_alias_source():
    conn = _make_db()
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('mesh:D003920','Diabetes','D003920',NULL,NULL,NULL,'ctd','now')"
    )
    conn.execute(
        "INSERT INTO disease_name_aliases VALUES ('mesh:D003920','Diabetes','ctd')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO disease_name_aliases VALUES ('mesh:D003920','Diabetes','ctd')"
        )
    # Same alias under different source is OK.
    conn.execute(
        "INSERT INTO disease_name_aliases VALUES ('mesh:D003920','Diabetes','symmap')"
    )
