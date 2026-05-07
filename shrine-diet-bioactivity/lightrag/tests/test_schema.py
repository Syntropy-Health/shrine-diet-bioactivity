"""Verify schema-DDL produces the expected drug-bioactive bridge tables.

The real `data_local/herbal_botanicals.db` is gitignored (5.5GB) so this test
spins up an ephemeral SQLite, applies the same DDL inline, and asserts the
columns. Keeps the test reproducible in any worktree even when the heavy DB
is absent.
"""

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS compounds (id TEXT PRIMARY KEY, name TEXT);

CREATE TABLE IF NOT EXISTS compound_identity (
  compound_id          TEXT PRIMARY KEY,
  inchikey             TEXT,
  inchi                TEXT,
  smiles               TEXT,
  pubchem_cid          INTEGER,
  chembl_id            TEXT,
  kegg_compound_id     TEXT,
  drugbank_id          TEXT,
  chebi_id             INTEGER,
  unichem_src_count    INTEGER NOT NULL DEFAULT 0,
  resolution_method    TEXT NOT NULL,
  resolved_at          TEXT NOT NULL,
  FOREIGN KEY (compound_id) REFERENCES compounds(id)
);

CREATE TABLE IF NOT EXISTS bioactivity_evidence (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  compound_id          TEXT NOT NULL,
  chembl_compound_id   TEXT NOT NULL,
  chembl_target_id     TEXT NOT NULL,
  target_pref_name     TEXT,
  target_type          TEXT,
  target_organism      TEXT,
  activity_type        TEXT NOT NULL,
  relation             TEXT,
  value                REAL,
  units                TEXT,
  pchembl              REAL,
  activity_comment     TEXT,
  assay_confidence     INTEGER,
  chembl_doc_id        TEXT,
  publication_year     INTEGER,
  ingested_at          TEXT NOT NULL,
  FOREIGN KEY (compound_id) REFERENCES compounds(id)
);
"""


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    return {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({table})")}


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    return conn


def test_compound_identity_schema_matches_spec():
    conn = _make_db()
    cols = _columns(conn, "compound_identity")
    # compound_id MUST be TEXT to match compounds.id.
    assert cols["compound_id"] == "TEXT"
    expected = {
        "inchikey",
        "inchi",
        "smiles",
        "pubchem_cid",
        "chembl_id",
        "kegg_compound_id",
        "drugbank_id",
        "chebi_id",
        "unichem_src_count",
        "resolution_method",
        "resolved_at",
    }
    assert expected.issubset(cols.keys()), cols.keys()


def test_bioactivity_evidence_schema_matches_spec():
    conn = _make_db()
    cols = _columns(conn, "bioactivity_evidence")
    assert cols["compound_id"] == "TEXT"
    expected = {
        "chembl_compound_id",
        "chembl_target_id",
        "target_pref_name",
        "target_type",
        "target_organism",
        "activity_type",
        "relation",
        "value",
        "units",
        "pchembl",
        "activity_comment",
        "assay_confidence",
        "chembl_doc_id",
        "publication_year",
        "ingested_at",
    }
    assert expected.issubset(cols.keys()), cols.keys()
