"""KG completeness gates — RED tests pinning the use-case A/D doneness criteria.

These tests are the regression surface for the gaps catalogued in
`docs/KG_COMPLETENESS_AUDIT.md`. Every test here is intentionally RED today;
each is marked ``xfail`` with a strict reason so:

  - Coverage of "what's broken" is visible in the test runner output.
  - When a gap is closed by a follow-up PR, the corresponding xfail test
    flips GREEN and pytest reports XPASS — surfaced as a hard failure
    (because of ``strict=True``) so the owner remembers to flip ``xfail``
    off once the work has landed.

This is TDD applied to the audit: the test goes in BEFORE the
implementation. When you implement, you delete the ``@pytest.mark.xfail``
line and watch it pass.

Live-DB gating: every test skips cleanly if the 5.5GB
``data_local/herbal_botanicals.db`` is absent (CI doesn't ship it).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

DB_PATH = Path(__file__).parent.parent.parent / "data_local" / "herbal_botanicals.db"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


@pytest.fixture(scope="module")
def db_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        pytest.skip(f"Live DB not present at {DB_PATH}; skipping completeness gates.")
    return sqlite3.connect(str(DB_PATH))


# ---------------------------------------------------------------------------
# Gap 1 — CTD chemical_diseases empty (audit §3 Gap 1)
# ---------------------------------------------------------------------------


def test_chemical_diseases_has_meaningful_coverage(db_conn: sqlite3.Connection) -> None:
    """CTD chem→disease map populated by load-ctd (audit §4.1).

    Audit floor is 10K rows. Live DB ingest produces ~900K unique
    (compound_id, disease_name) pairs after the PRIMARY KEY dedup.
    """
    assert _table_exists(db_conn, "chemical_diseases")
    n = db_conn.execute("SELECT COUNT(*) FROM chemical_diseases").fetchone()[0]
    assert n >= 10_000, (
        f"chemical_diseases has {n} rows. Run `make load-ctd` to populate."
    )


# ---------------------------------------------------------------------------
# Gap 2 — symptom→disease map missing (audit §3 Gap 2 + §4.2)
# ---------------------------------------------------------------------------


def test_symptom_disease_map_table_exists(db_conn: sqlite3.Connection) -> None:
    """Schema landed by phase2/symptom-disease-map (audit §4.2)."""
    assert _table_exists(db_conn, "symptom_disease_map"), (
        "symptom_disease_map table not present. See audit §4.2 for schema."
    )


def test_symptom_disease_map_covers_most_symptoms(db_conn: sqlite3.Connection) -> None:
    """≥40 of the 47 hand-curated symptoms must have ≥1 disease mapping."""
    n_symptoms = db_conn.execute("SELECT COUNT(*) FROM symptoms").fetchone()[0]
    assert n_symptoms >= 47  # sanity floor

    n_mapped = db_conn.execute(
        "SELECT COUNT(DISTINCT symptom_id) FROM symptom_disease_map"
    ).fetchone()[0]
    assert n_mapped >= 40, (
        f"Only {n_mapped}/{n_symptoms} symptoms have disease mappings. "
        "Audit §4.2 requires ≥40."
    )


def test_inflammation_diabetes_hypertension_have_mesh_ids(
    db_conn: sqlite3.Connection,
) -> None:
    """Three high-volume symptoms must resolve to a SymMap row with a MeSH ID.

    These three are picked because they have the richest target_diseases
    string-match coverage (Inflammation 2,885; Diabetes 9,286; Hypertension
    5,128) — if even these don't map cleanly, the build pipeline is broken.
    """
    rows = db_conn.execute(
        """
        SELECT s.name, COUNT(*) AS n_with_mesh
        FROM symptoms s
        JOIN symptom_disease_map sdm ON sdm.symptom_id = s.id
        WHERE s.name IN ('Inflammation', 'Diabetes', 'Hypertension')
          AND sdm.mesh_id IS NOT NULL
        GROUP BY s.name
        """
    ).fetchall()
    names_with_mesh = {r[0] for r in rows}
    expected = {"Inflammation", "Diabetes", "Hypertension"}
    missing = expected - names_with_mesh
    assert not missing, (
        f"These symptoms have no MeSH-anchored disease mapping: {sorted(missing)}. "
        "Audit §4.2 requires all three to resolve."
    )


def test_match_score_in_valid_range(db_conn: sqlite3.Connection) -> None:
    bad = db_conn.execute(
        "SELECT COUNT(*) FROM symptom_disease_map "
        "WHERE match_score < 0.0 OR match_score > 1.0"
    ).fetchone()[0]
    assert bad == 0, f"{bad} rows have match_score outside [0,1]"


def test_maps_to_disease_relationship_query_runs(db_conn: sqlite3.Connection) -> None:
    """MAPS_TO_DISEASE in entity_schema must query the symptom_disease_map cleanly."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from entity_schema import RELATIONSHIP_TYPES, describe_relationship

    assert "MAPS_TO_DISEASE" in RELATIONSHIP_TYPES
    spec = RELATIONSHIP_TYPES["MAPS_TO_DISEASE"]
    assert spec["src_type"] == "Symptom"
    assert spec["tgt_type"] == "Disease"

    # The query must execute against the populated map.
    rows = list(db_conn.execute(spec["query"]))
    assert len(rows) >= 40, (
        f"Expected ≥40 MAPS_TO_DISEASE edges (one per mapped symptom); got {len(rows)}"
    )

    cols = [d[0] for d in db_conn.execute(spec["query"]).description]
    sample = dict(zip(cols, rows[0]))
    desc, kw = describe_relationship("MAPS_TO_DISEASE", sample)
    assert sample["src_name"] in desc
    assert sample["tgt_name"] in desc
    assert "symptom" in kw and "disease" in kw


# ---------------------------------------------------------------------------
# Gap 3 — HERB 2.0 ↔ Duke resolution (audit §3 Gap 3)
# ---------------------------------------------------------------------------


def test_herb_resolution_covers_majority_of_duke_herbs(
    db_conn: sqlite3.Connection,
) -> None:
    """Audit §4.3 — Duke ↔ HERB 2.0 resolution.

    Multi-tier matcher (latin_exact / binomial / common_name / genus)
    populates herb_resolution_map. Live-DB result was 1,818/2,376 (76.5%).
    """
    n_duke = db_conn.execute("SELECT COUNT(*) FROM herbs").fetchone()[0]
    n_resolved = db_conn.execute(
        "SELECT COUNT(DISTINCT duke_id) FROM herb_resolution_map"
    ).fetchone()[0]
    # Audit §4.3 target: ≥75% (~1,782 of 2,376).
    assert n_resolved >= int(0.75 * n_duke), (
        f"{n_resolved}/{n_duke} Duke herbs resolved to HERB 2.0 (need ≥75%)."
    )
