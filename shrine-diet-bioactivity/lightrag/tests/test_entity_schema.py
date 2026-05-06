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
    desc = gen({
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
    })
    assert "IC50" in desc
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "Homo sapiens" in desc
    assert "CHEMBL1129589" in desc
    assert "pChEMBL 5.3" in desc


def test_describe_bioactivity_evidence_handles_missing_fields():
    """Should not crash when target_pref_name / organism are None."""
    gen = DESCRIPTION_GENERATORS["BioactivityEvidence"]
    desc = gen({
        "id": 2,
        "chembl_compound_id": "CHEMBL?",
        "chembl_target_id": "CHEMBL?",
        "activity_type": "Ki",
        "value": None, "units": "", "relation": None,
        "target_pref_name": None, "target_organism": None,
        "assay_confidence": None, "publication_year": None,
        "chembl_doc_id": None, "pchembl": None,
    })
    assert "BioactivityEvidence" in desc
    # Falls back to chembl_target_id when target_pref_name is None.
    assert "CHEMBL?" in desc


def test_has_evidence_relationship_described():
    desc, kw = describe_relationship("HAS_EVIDENCE", {
        "src_name": "Curcumin",
        "tgt_name": "BioactivityEvidence#1",
        "pchembl": 5.3,
        "activity_type": "IC50",
    })
    assert "Curcumin" in desc
    assert "IC50" in desc
    assert "pChEMBL 5.3" in desc
    assert "BioactivityEvidence#1" in desc


def test_evidence_for_target_relationship_described():
    desc, kw = describe_relationship("EVIDENCE_FOR_TARGET", {
        "src_name": "BioactivityEvidence#1",
        "tgt_name": "Nuclear factor NF-kappa-B p65",
        "confidence_score": 8,
        "year": 2018,
    })
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "assay confidence 8" in desc
    assert "year 2018" in desc
