"""Tests for BioactivityEvidence entity + HAS_EVIDENCE/EVIDENCE_FOR_TARGET edges."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_schema import (  # noqa: E402
    DESCRIPTION_GENERATORS,
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
    describe_relationship,
)


def test_bioactivity_evidence_entity_registered():
    assert "BioactivityEvidence" in ENTITY_TYPES
    et = ENTITY_TYPES["BioactivityEvidence"]
    assert et["source_table"] == "bioactivity_evidence"
    assert et["id_field"] == "id"
    assert "BioactivityEvidence" in DESCRIPTION_GENERATORS


def test_bioactivity_relationship_types_registered():
    assert "HAS_EVIDENCE" in RELATIONSHIP_TYPES
    has_ev = RELATIONSHIP_TYPES["HAS_EVIDENCE"]
    assert has_ev["src_type"] == "Compound"
    assert has_ev["tgt_type"] == "BioactivityEvidence"

    assert "EVIDENCE_FOR_TARGET" in RELATIONSHIP_TYPES
    ev_for = RELATIONSHIP_TYPES["EVIDENCE_FOR_TARGET"]
    assert ev_for["src_type"] == "BioactivityEvidence"
    assert ev_for["tgt_type"] == "Target"


def test_describe_bioactivity_evidence_renders_full_text():
    gen = DESCRIPTION_GENERATORS["BioactivityEvidence"]
    desc = gen(
        {
            "id": 1,
            "compound_id": "curcumin",
            "chembl_compound_id": "CHEMBL116438",
            "chembl_target_id": "CHEMBL1741221",
            "target_pref_name": "Nuclear factor NF-kappa-B p65",
            "target_organism": "Homo sapiens",
            "activity_type": "IC50",
            "relation": "=",
            "value": 5000.0,
            "units": "nM",
            "pchembl": 5.3,
            "assay_confidence": 8,
            "chembl_doc_id": "CHEMBL1129589",
            "publication_year": 2018,
        }
    )
    assert "IC50" in desc
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "Homo sapiens" in desc
    assert "CHEMBL1129589" in desc
    assert "pChEMBL 5.3" in desc


def test_describe_bioactivity_evidence_handles_missing_fields():
    """Should not crash when target_pref_name / organism are None."""
    gen = DESCRIPTION_GENERATORS["BioactivityEvidence"]
    desc = gen(
        {
            "id": 2,
            "chembl_compound_id": "CHEMBL?",
            "chembl_target_id": "CHEMBL?",
            "activity_type": "Ki",
            "value": None,
            "units": "",
            "relation": None,
            "target_pref_name": None,
            "target_organism": None,
            "assay_confidence": None,
            "publication_year": None,
            "chembl_doc_id": None,
            "pchembl": None,
        }
    )
    assert "BioactivityEvidence" in desc
    # Falls back to chembl_target_id when target_pref_name is None.
    assert "CHEMBL?" in desc


def test_has_evidence_relationship_described():
    desc, kw = describe_relationship(
        "HAS_EVIDENCE",
        {
            "src_name": "Curcumin",
            "tgt_name": "BioactivityEvidence#1",
            "pchembl": 5.3,
            "activity_type": "IC50",
        },
    )
    assert "Curcumin" in desc
    assert "IC50" in desc
    assert "pChEMBL 5.3" in desc
    assert "BioactivityEvidence#1" in desc


def test_evidence_for_target_relationship_described():
    desc, kw = describe_relationship(
        "EVIDENCE_FOR_TARGET",
        {
            "src_name": "BioactivityEvidence#1",
            "tgt_name": "Nuclear factor NF-kappa-B p65",
            "confidence_score": 8,
            "year": 2018,
        },
    )
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "assay confidence 8" in desc
    assert "year 2018" in desc


# ---- Issue #50: MAPS_TO_DISEASE must drop low-confidence string-match rows


def test_maps_to_disease_query_filters_low_score_tier4_rows():
    """The Phase-2 symptom→disease bridge built tier-4 string-match rows at
    match_score=0.3. Promoting those into LightRAG via MAPS_TO_DISEASE
    pollutes the recommendation graph with noise. The relationship query
    must filter to ``match_score >= 0.5`` so tier-4 hits stay out (see #50).
    """
    from entity_schema import RELATIONSHIP_TYPES  # noqa: E402

    q = RELATIONSHIP_TYPES["MAPS_TO_DISEASE"]["query"]
    assert "match_score >= 0.5" in q, (
        "MAPS_TO_DISEASE query does not filter on match_score — "
        "tier-4 (0.3) string-match rows leak into the KG (see #50)."
    )


# ---- Issue #62: COMPOUND_IN_PATHWAY zero-row warning


def test_compound_in_pathway_warns_on_zero_rows(tmp_path, capsys):
    """When COMPOUND_IN_PATHWAY's join yields 0 rows (Phase 1 compound_identity
    not yet populated), extract_duke_relationships must emit a visible
    warning so the operator notices the missing pathway edges (see #62)."""
    import sqlite3
    import sys
    from pathlib import Path as _P

    sys.path.insert(0, str(_P(__file__).parent.parent))
    from ingest_direct import extract_duke_relationships  # noqa: E402

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE kegg_compound_pathways (
            kegg_compound_id TEXT,
            kegg_pathway_id TEXT
        );
        CREATE TABLE compound_identity (
            compound_id INTEGER,
            kegg_compound_id TEXT
        );
        CREATE TABLE compounds (
            id INTEGER PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE kegg_pathways (
            id TEXT PRIMARY KEY,
            name TEXT
        );
        """
    )

    rels = extract_duke_relationships(
        conn, "COMPOUND_IN_PATHWAY", max_count=None
    )
    assert rels == [], "expected zero rows in the empty fixture"

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "COMPOUND_IN_PATHWAY" in combined and (
        "0 rows" in combined or "no rows" in combined or "empty" in combined.lower()
    ), (
        "Expected an operator-visible warning when COMPOUND_IN_PATHWAY "
        f"returns 0 rows. Captured: out={captured.out!r} err={captured.err!r}"
    )
