"""Tests for ChEMBL bioactivity extractor."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from chembl_extractor import extract_bioactivities_for_inchikeys  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "chembl_subset.sqlite"


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(FIXTURE)


def test_extract_returns_curcumin_nfkb():
    rows = extract_bioactivities_for_inchikeys(
        _conn(),
        inchikeys=["VFLDPWHFBUODDF-FCXRPNKRSA-N"],
        min_pchembl=5.0,
        min_confidence=5,
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["chembl_compound_id"] == "CHEMBL116438"
    assert r["target_pref_name"] == "Nuclear factor NF-kappa-B p65"
    assert r["target_organism"] == "Homo sapiens"
    assert r["activity_type"] == "IC50"
    assert r["pchembl"] == 5.30
    assert r["assay_confidence"] == 8


def test_extract_filters_low_confidence_assays():
    rows = extract_bioactivities_for_inchikeys(
        _conn(),
        inchikeys=["RYYVLZVUVIJVGH-UHFFFAOYSA-N"],
        min_pchembl=5.0,
        min_confidence=5,
    )
    # Two activities exist for caffeine; the confidence=3 one must be dropped.
    assert len(rows) == 1
    assert rows[0]["assay_confidence"] == 9
    assert rows[0]["pchembl"] == 5.62


def test_extract_filters_low_pchembl():
    """Lowering confidence floor still drops the noisy pchembl=0.0 row."""
    rows = extract_bioactivities_for_inchikeys(
        _conn(),
        inchikeys=["RYYVLZVUVIJVGH-UHFFFAOYSA-N"],
        min_pchembl=5.0,
        min_confidence=1,
    )
    assert all(r["pchembl"] >= 5.0 for r in rows)


def test_extract_batches_inchikeys():
    """Must work cleanly when the IN-list crosses the batch threshold."""
    keys = [f"FAKE{i:040d}-X" for i in range(2500)]
    keys[0] = "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    rows = extract_bioactivities_for_inchikeys(_conn(), inchikeys=keys)
    chembl_ids = [r["chembl_compound_id"] for r in rows]
    assert "CHEMBL116438" in chembl_ids


def test_extract_empty_inchikey_list_returns_empty():
    assert extract_bioactivities_for_inchikeys(_conn(), inchikeys=[]) == []
