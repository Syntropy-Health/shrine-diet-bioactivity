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

DB_PATH = (
    Path(__file__).parent.parent.parent / "data_local" / "herbal_botanicals.db"
)


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Audit §3 Gap 1: chemical_diseases table is empty in live DB despite "
        "the architecture promising ~3.8M CTD rows. Implementation tracked at "
        "audit §4.1 — load-ctd ingest script. Flip xfail off once implemented."
    ),
)
def test_chemical_diseases_has_meaningful_coverage(db_conn: sqlite3.Connection) -> None:
    """CTD chem→disease map should have ≥10K rows after ingest."""
    assert _table_exists(db_conn, "chemical_diseases")
    n = db_conn.execute("SELECT COUNT(*) FROM chemical_diseases").fetchone()[0]
    assert n >= 10_000, (
        f"chemical_diseases has {n} rows; CTD ingest never ran. "
        "See docs/KG_COMPLETENESS_AUDIT.md §3 Gap 1 + §4.1."
    )


# ---------------------------------------------------------------------------
# Gap 2 — symptom→disease map missing (audit §3 Gap 2 + §4.2)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Audit §3 Gap 2: symptom_disease_map table not yet built. "
        "Highest-leverage gap for use case A. Implementation spec at §4.2; "
        "schema + build pipeline + acceptance criteria defined. "
        "Flip xfail off once make build-symptom-disease-map exists."
    ),
)
def test_symptom_disease_map_table_exists(db_conn: sqlite3.Connection) -> None:
    assert _table_exists(db_conn, "symptom_disease_map"), (
        "symptom_disease_map table not present. See audit §4.2 for schema."
    )


@pytest.mark.xfail(strict=True, reason="depends on symptom_disease_map (audit §4.2)")
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


@pytest.mark.xfail(strict=True, reason="depends on symptom_disease_map (audit §4.2)")
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


@pytest.mark.xfail(strict=True, reason="depends on symptom_disease_map (audit §4.2)")
def test_match_score_in_valid_range(db_conn: sqlite3.Connection) -> None:
    bad = db_conn.execute(
        "SELECT COUNT(*) FROM symptom_disease_map "
        "WHERE match_score < 0.0 OR match_score > 1.0"
    ).fetchone()[0]
    assert bad == 0, f"{bad} rows have match_score outside [0,1]"


# ---------------------------------------------------------------------------
# Gap 3 — HERB 2.0 ↔ Duke resolution (audit §3 Gap 3)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Audit §3 Gap 3: herb_resolution_map table missing. HERB 2.0 herbs "
        "are siloed from Duke herb_compounds. Implementation spec at §4.3; "
        "depends on a herb-name normalization library."
    ),
)
def test_herb_resolution_covers_majority_of_duke_herbs(
    db_conn: sqlite3.Connection,
) -> None:
    n_duke = db_conn.execute("SELECT COUNT(*) FROM herbs").fetchone()[0]
    n_resolved = db_conn.execute(
        "SELECT COUNT(DISTINCT duke_id) FROM herb_resolution_map"
    ).fetchone()[0]
    # Audit §4.3 target: ≥75% (~1,782 of 2,376).
    assert n_resolved >= int(0.75 * n_duke), (
        f"{n_resolved}/{n_duke} Duke herbs resolved to HERB 2.0 (need ≥75%)."
    )
