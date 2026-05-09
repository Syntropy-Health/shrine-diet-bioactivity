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
# Gap 1 — CTD chemical_diseases empty (audit §3 Gap 1; Phase 3 supersedes)
# ---------------------------------------------------------------------------


def test_chemical_diseases_has_meaningful_coverage(db_conn: sqlite3.Connection) -> None:
    """Legacy gate kept for the migration cycle (spec §4.5).

    chemical_diseases stays populated alongside compound_disease_evidence
    until the legacy table is dropped (planned: ≥1 stable production cycle
    after Phase 3 lands). After drop, this test gets removed; the new
    gate test_compound_disease_evidence_has_meaningful_coverage takes over.
    """
    assert _table_exists(db_conn, "chemical_diseases")
    n = db_conn.execute("SELECT COUNT(*) FROM chemical_diseases").fetchone()[0]
    assert n >= 10_000, (
        f"chemical_diseases has {n} rows. Run `make load-ctd` to populate."
    )


# ---------------------------------------------------------------------------
# Phase 3 — disease canonicalization gates (spec §8 DoD)
# ---------------------------------------------------------------------------


def test_diseases_canonical_table_populated(db_conn: sqlite3.Connection) -> None:
    """Canonical disease registry should have thousands of entries unifying
    SymMap + CTD + target_diseases + HERB 2.0."""
    assert _table_exists(db_conn, "diseases_canonical")
    n = db_conn.execute("SELECT COUNT(*) FROM diseases_canonical").fetchone()[0]
    assert n >= 5_000, (
        f"diseases_canonical has {n} rows. Run `make build-disease-canonical`."
    )


def test_compound_disease_evidence_has_meaningful_coverage(
    db_conn: sqlite3.Connection,
) -> None:
    """Phase 3 supersedes Gap 1 — CTD evidence in canonicalized form.

    Live-DB ingest produces ~2.9M rows (vs the legacy chemical_diseases'
    934K) because the new schema also captures inferred-via-gene rows
    that the legacy filter dropped. Floor of 800K is conservative.
    """
    assert _table_exists(db_conn, "compound_disease_evidence")
    n = db_conn.execute(
        "SELECT COUNT(*) FROM compound_disease_evidence"
    ).fetchone()[0]
    assert n >= 800_000, (
        f"compound_disease_evidence has {n} rows; expected ≥800K. "
        "Run build-disease-canonical && load-ctd."
    )


def test_compound_disease_evidence_evidence_types_balanced(
    db_conn: sqlite3.Connection,
) -> None:
    """All three evidence types must appear, and the schema CHECK must hold."""
    rows = dict(
        db_conn.execute(
            "SELECT evidence_type, COUNT(*) FROM compound_disease_evidence "
            "GROUP BY evidence_type"
        ).fetchall()
    )
    assert "direct_therapeutic" in rows and rows["direct_therapeutic"] > 1_000
    assert "direct_marker" in rows and rows["direct_marker"] > 1_000
    assert "inferred_via_gene" in rows and rows["inferred_via_gene"] > 1_000


def test_compound_disease_evidence_preserves_pubmed_citations(
    db_conn: sqlite3.Connection,
) -> None:
    """≥40% of CDE rows should carry at least one PubMed ID — that's the
    primary use-case-A 'citation-graded recommendation' signal."""
    total = db_conn.execute(
        "SELECT COUNT(*) FROM compound_disease_evidence"
    ).fetchone()[0]
    with_cites = db_conn.execute(
        "SELECT COUNT(*) FROM compound_disease_evidence "
        "WHERE pubmed_ids IS NOT NULL AND pubmed_ids != ''"
    ).fetchone()[0]
    assert total > 0
    fraction = with_cites / total
    assert fraction >= 0.40, (
        f"Only {fraction:.1%} of CDE rows carry pubmed_ids; expected ≥40%."
    )


def test_disease_canonicalization_unifies_sources(
    db_conn: sqlite3.Connection,
) -> None:
    """Every disease string from the four sources should have ≥1 alias row."""
    sources = ["target_diseases", "ctd", "symmap", "herb2"]
    counts = {
        s: db_conn.execute(
            "SELECT COUNT(*) FROM disease_name_aliases WHERE source=?", (s,)
        ).fetchone()[0]
        for s in sources
    }
    assert counts["target_diseases"] > 0, "CMAUP target_diseases not aliased"
    assert counts["ctd"] > 0, "CTD not aliased"
    assert counts["symmap"] > 0, "SymMap not aliased"
    assert counts["herb2"] > 0, "HERB 2.0 not aliased"


def test_disease_canonical_mesh_uniqueness(
    db_conn: sqlite3.Connection,
) -> None:
    """No two canonical rows share the same mesh_id (UNIQUE index enforces)."""
    dups = db_conn.execute(
        "SELECT mesh_id, COUNT(*) FROM diseases_canonical "
        "WHERE mesh_id IS NOT NULL GROUP BY mesh_id HAVING COUNT(*) > 1"
    ).fetchall()
    assert dups == [], f"Duplicate mesh_ids found: {dups}"


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


# ---------------------------------------------------------------------------
# Phase 4 — KEGG pathway overlay (spec 2026-05-08-kegg-pathway-overlay-design)
# ---------------------------------------------------------------------------


def test_kegg_pathways_table_populated(db_conn: sqlite3.Connection) -> None:
    """Live-DB ingest produces ~370 hsa pathways (KEGG baseline)."""
    assert _table_exists(db_conn, "kegg_pathways")
    n = db_conn.execute("SELECT COUNT(*) FROM kegg_pathways").fetchone()[0]
    assert n >= 300, (
        f"kegg_pathways has {n} rows; expected ≥300. Run `make build-kegg-pathways`."
    )


def test_kegg_pathway_gene_resolution_coverage(
    db_conn: sqlite3.Connection,
) -> None:
    """≥80% of KEGG genes should resolve to HUGO symbols (live-DB hits 100%)."""
    total = db_conn.execute("SELECT COUNT(*) FROM kegg_pathway_genes").fetchone()[0]
    with_symbol = db_conn.execute(
        "SELECT COUNT(*) FROM kegg_pathway_genes WHERE gene_symbol IS NOT NULL"
    ).fetchone()[0]
    assert total > 0
    coverage = with_symbol / total
    assert coverage >= 0.80, (
        f"only {coverage:.1%} of KEGG genes have HUGO symbols; expected ≥80%"
    )


def test_pathway_includes_target_join_works_at_scale(
    db_conn: sqlite3.Connection,
) -> None:
    """Closes Phase 4 — pathway↔target join via gene_symbol resolves
    at meaningful scale (≥400 joins on live DB today)."""
    n = db_conn.execute(
        "SELECT COUNT(*) FROM kegg_pathway_genes kpg "
        "JOIN targets t ON t.gene_symbol = kpg.gene_symbol"
    ).fetchone()[0]
    assert n >= 400, (
        f"only {n} pathway-target joins; expected ≥400. "
        "Indicates KEGG ingest or targets table is incomplete."
    )


def test_kegg_compound_pathway_covers_meaningful_set(
    db_conn: sqlite3.Connection,
) -> None:
    """Spec §6: ≥5,000 compound-pathway links. Live DB hits 10,556."""
    n = db_conn.execute(
        "SELECT COUNT(*) FROM kegg_compound_pathways"
    ).fetchone()[0]
    assert n >= 5_000, (
        f"only {n} compound-pathway links; expected ≥5,000."
    )


# ---------------------------------------------------------------------------
# Phase 5 — diet scoring (spec 2026-05-08-diet-scoring-design)
# ---------------------------------------------------------------------------


def test_diet_scoring_end_to_end(db_conn: sqlite3.Connection) -> None:
    """Closes use-case-D doneness §5.4 — aggregate scoring function works
    end-to-end against the live KG, returning ranked targets + diseases
    + pathways with evidence-typed breakdowns and PubMed citation totals.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from diet_scorer import score_diet

    diet = [("Turmeric", 5), ("Ginger", 10), ("Broccoli", 100)]
    result = score_diet(diet, conn=db_conn)

    assert len(result["exposures"]) > 0, "expected ≥1 compound exposure"
    assert len(result["targets"]) > 0, "expected ≥1 ranked target"
    assert len(result["diseases"]) > 0, "expected ≥1 ranked disease"

    # Top-ranked disease should carry an evidence breakdown with all four keys.
    top = result["diseases"][0]
    breakdown = top["evidence_breakdown"]
    assert {"direct_therapeutic", "direct_marker",
            "inferred_via_gene", "pubmed_total"}.issubset(breakdown.keys())
    # PubMed citation count is non-negative and an int.
    assert isinstance(breakdown["pubmed_total"], int)
    assert breakdown["pubmed_total"] >= 0

    # Disclaimer field must be present (research-only flag).
    assert "research-aid" in result["disclaimer"].lower()
