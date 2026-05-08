"""Tests for disease canonicalization helpers (Phase 3 / spec §4.2)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from disease_canon import (  # noqa: E402
    canonical_id,
    parse_disease_id,
    slugify_disease_name,
)


# ---- parse_disease_id --------------------------------------------------


def test_parse_disease_id_strips_mesh_prefix():
    assert parse_disease_id("MESH:D018268") == ("mesh", "D018268")
    assert parse_disease_id("MESH:C123456") == ("mesh", "C123456")


def test_parse_disease_id_recognizes_omim_and_doid():
    assert parse_disease_id("OMIM:222100") == ("omim", "222100")
    assert parse_disease_id("DOID:14330") == ("doid", "14330")


def test_parse_disease_id_recognizes_umls_icd10_hpo():
    assert parse_disease_id("UMLS:C0011849") == ("umls", "C0011849")
    assert parse_disease_id("ICD10CM:E11") == ("icd10cm", "E11")
    assert parse_disease_id("HPO:0001392") == ("hpo", "0001392")


def test_parse_disease_id_returns_none_for_bare_string():
    assert parse_disease_id("Diabetes") == (None, None)
    assert parse_disease_id("") == (None, None)
    assert parse_disease_id(None) == (None, None)


def test_parse_disease_id_returns_none_for_unknown_prefix():
    assert parse_disease_id("MADEUP:42") == (None, None)


# ---- canonical_id ------------------------------------------------------


def test_canonical_id_prefers_mesh_then_umls_then_icd10():
    assert canonical_id(mesh="D003920", umls="C0011849", icd10="E11") == "mesh:D003920"
    assert canonical_id(mesh=None, umls="C0011849", icd10="E11") == "umls:C0011849"
    assert canonical_id(mesh=None, umls=None, icd10="E11") == "icd10cm:E11"


def test_canonical_id_falls_back_to_local_slug():
    assert (
        canonical_id(
            mesh=None, umls=None, icd10=None, preferred_name="Diabetes Mellitus"
        )
        == "local:diabetes-mellitus"
    )


def test_canonical_id_raises_when_nothing_to_anchor():
    import pytest

    with pytest.raises(ValueError):
        canonical_id(mesh=None, umls=None, icd10=None, preferred_name=None)


# ---- slugify_disease_name ---------------------------------------------


def test_slugify_lowercases_alphanums_and_dashes_separators():
    assert slugify_disease_name("Diabetes Mellitus") == "diabetes-mellitus"
    assert (
        slugify_disease_name("Alzheimer's Disease, Late Onset")
        == "alzheimer-s-disease-late-onset"
    )
    assert slugify_disease_name("Type-2 Diabetes (NIDDM)") == "type-2-diabetes-niddm"


def test_slugify_collapses_whitespace_and_strips_edges():
    assert slugify_disease_name("  Cancer   of   Lung  ") == "cancer-of-lung"
    assert slugify_disease_name("---foo---") == "foo"


def test_slugify_empty_returns_empty():
    assert slugify_disease_name("") == ""
