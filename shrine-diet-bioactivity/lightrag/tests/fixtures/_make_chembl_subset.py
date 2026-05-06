"""Generate a tiny ChEMBL-shaped SQLite fixture for tests.

Run once; the resulting `chembl_subset.sqlite` is committed to git (~50 KB).
"""
import sqlite3
from pathlib import Path

OUT = Path(__file__).parent / "chembl_subset.sqlite"
OUT.unlink(missing_ok=True)

conn = sqlite3.connect(OUT)
conn.executescript("""
CREATE TABLE compound_structures (
    molregno INTEGER PRIMARY KEY,
    standard_inchi_key TEXT
);
CREATE TABLE molecule_dictionary (
    molregno INTEGER PRIMARY KEY,
    chembl_id TEXT
);
CREATE TABLE target_dictionary (
    tid INTEGER PRIMARY KEY,
    chembl_id TEXT,
    pref_name TEXT,
    target_type TEXT,
    organism TEXT
);
CREATE TABLE assays (
    assay_id INTEGER PRIMARY KEY,
    tid INTEGER,
    confidence_score INTEGER
);
CREATE TABLE docs (
    doc_id INTEGER PRIMARY KEY,
    chembl_id TEXT,
    year INTEGER
);
CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY,
    molregno INTEGER,
    assay_id INTEGER,
    doc_id INTEGER,
    standard_type TEXT,
    standard_relation TEXT,
    standard_value REAL,
    standard_units TEXT,
    pchembl_value REAL,
    activity_comment TEXT
);

-- Curcumin (CHEMBL116438) inhibits NF-kB
INSERT INTO compound_structures VALUES (1, 'VFLDPWHFBUODDF-FCXRPNKRSA-N');
INSERT INTO molecule_dictionary VALUES (1, 'CHEMBL116438');
INSERT INTO target_dictionary VALUES (100, 'CHEMBL1741221', 'Nuclear factor NF-kappa-B p65', 'SINGLE PROTEIN', 'Homo sapiens');
INSERT INTO assays VALUES (1000, 100, 8);
INSERT INTO docs VALUES (5000, 'CHEMBL1129589', 2018);
INSERT INTO activities VALUES (10000, 1, 1000, 5000, 'IC50', '=', 5000.0, 'nM', 5.30, NULL);

-- Caffeine (CHEMBL113) on adenosine A2A receptor
INSERT INTO compound_structures VALUES (2, 'RYYVLZVUVIJVGH-UHFFFAOYSA-N');
INSERT INTO molecule_dictionary VALUES (2, 'CHEMBL113');
INSERT INTO target_dictionary VALUES (200, 'CHEMBL251', 'Adenosine A2a receptor', 'SINGLE PROTEIN', 'Homo sapiens');
INSERT INTO assays VALUES (2000, 200, 9);
INSERT INTO docs VALUES (5001, 'CHEMBL1100001', 2019);
INSERT INTO activities VALUES (10001, 2, 2000, 5001, 'Ki', '=', 2400.0, 'nM', 5.62, NULL);

-- Low-confidence noisy row that must be filtered out
INSERT INTO assays VALUES (3000, 200, 3);
INSERT INTO activities VALUES (10002, 2, 3000, 5001, 'IC50', '=', 1e9, 'nM', 0.0, 'noisy');
""")
conn.commit()
conn.close()
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
