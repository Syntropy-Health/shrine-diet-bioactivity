"""Unit tests for the symptom→SymMap matcher.

Pure logic tests — no DB. The matcher is fed lists of dictionaries that
mirror the SymMap table shapes, so we can exhaustively cover the four-tier
matching strategy (exact / token-overlap / substring / fallback) without
needing the 5.5GB live DB.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make lightrag/ importable when pytest runs from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from symptom_matcher import (  # noqa: E402
    MatchResult,
    match_symptom,
    token_jaccard,
)


# Fixture data — slimmed slices of the real SymMap shape.
# Modern symptoms have name + mesh_id + umls_id + icd10cm_id + symmap_id.
# TCM symptoms have name_en + symmap_id + umls_id (no MeSH).
MODERN = [
    {
        "symmap_id": "SMMS0001",
        "name": "Inflammation",
        "mesh_id": "D007249",
        "umls_id": "C0021368",
        "icd10cm_id": None,
    },
    {
        "symmap_id": "SMMS0002",
        "name": "Diabetes Mellitus",
        "mesh_id": "D003920",
        "umls_id": "C0011849",
        "icd10cm_id": "E11",
    },
    {
        "symmap_id": "SMMS0003",
        "name": "Essential Hypertension",
        "mesh_id": "C562386",
        "umls_id": "C0085580",
        "icd10cm_id": "I10",
    },
    {
        "symmap_id": "SMMS0004",
        "name": "Bronchial Asthma",
        "mesh_id": "D001249",
        "umls_id": None,
        "icd10cm_id": None,
    },
    {
        "symmap_id": "SMMS0005",
        "name": "Pain",
        "mesh_id": "D010146",
        "umls_id": "C0030193",
        "icd10cm_id": None,
    },
    {
        "symmap_id": "SMMS0006",
        "name": "Acute Heart Disease",
        "mesh_id": "D006331",
        "umls_id": None,
        "icd10cm_id": None,
    },
]

TCM = [
    {"symmap_id": "SMTS0001", "name_en": "Heat-Toxin Inflammation"},
    {"symmap_id": "SMTS0002", "name_en": "Yang Deficiency"},
]

DISEASES = [
    "Cancer of the lung",
    "Hair loss alopecia",
    "Bile insufficiency syndrome",
    "Chronic stress disorder",
]


# ---------------------------------------------------------------------------
# Tier 1 — exact case-insensitive match (preferred)
# ---------------------------------------------------------------------------


def test_exact_match_on_modern_symptom_returns_full_xrefs():
    result = match_symptom("Inflammation", modern=MODERN, tcm=TCM, diseases=DISEASES)
    assert result is not None
    assert isinstance(result, MatchResult)
    assert result.source == "symmap_modern"
    assert result.match_score == 1.0
    assert result.symmap_id == "SMMS0001"
    assert result.mesh_id == "D007249"
    assert result.umls_id == "C0021368"


def test_exact_match_is_case_insensitive():
    result = match_symptom("PAIN", modern=MODERN, tcm=TCM, diseases=DISEASES)
    assert result is not None
    assert result.symmap_id == "SMMS0005"
    assert result.match_score == 1.0


# ---------------------------------------------------------------------------
# Tier 2 — token Jaccard (when exact fails, but symptom shares enough tokens)
# ---------------------------------------------------------------------------


def test_token_jaccard_basic():
    assert token_jaccard("inflammation", "inflammation") == 1.0
    assert token_jaccard("heart disease", "heart disease") == 1.0
    # 1 shared token of 2 unique → 1/3 = ~0.333
    assert abs(token_jaccard("heart disease", "lung disease") - 1 / 3) < 0.01


def test_token_jaccard_returns_zero_for_disjoint_strings():
    assert token_jaccard("foo", "bar") == 0.0


# ---------------------------------------------------------------------------
# Tier 3 — substring containment (Diabetes → "Diabetes Mellitus", etc.)
# ---------------------------------------------------------------------------


def test_substring_match_diabetes_finds_diabetes_mellitus():
    """Audit acceptance: Diabetes must resolve to a MeSH-anchored row."""
    result = match_symptom("Diabetes", modern=MODERN, tcm=TCM, diseases=DISEASES)
    assert result is not None
    assert result.symmap_id == "SMMS0002"
    assert result.mesh_id == "D003920"
    assert result.source == "symmap_modern"
    # Substring is below 1.0 to reflect partial match.
    assert 0.5 <= result.match_score < 1.0


def test_substring_match_hypertension_finds_essential_hypertension():
    """Audit acceptance: Hypertension must resolve to a MeSH-anchored row."""
    result = match_symptom("Hypertension", modern=MODERN, tcm=TCM, diseases=DISEASES)
    assert result is not None
    assert result.symmap_id == "SMMS0003"
    assert result.mesh_id == "C562386"


def test_substring_prefers_better_token_overlap_over_random_substring():
    """Heart disease should pick 'Acute Heart Disease' (jaccard high) — not a
    random shorter symmap row that happens to contain 'heart'."""
    result = match_symptom("Heart Disease", modern=MODERN, tcm=TCM, diseases=DISEASES)
    assert result is not None
    assert result.symmap_id == "SMMS0006"


def test_substring_tier_prefers_row_with_mesh_id_when_tied():
    """When multiple rows substring-match with equal token overlap, prefer
    the one with a non-NULL mesh_id (downstream-joinable formal ID).

    Real-world case: 'Hypertension' substring-matches both 'Essential
    Hypertension' (MeSH=C562386) and 'Rebound Hypertension' (MeSH=NULL).
    Without this tie-breaker, the picker is order-dependent.
    """
    modern_dual = [
        {
            "symmap_id": "SMMS_RB",
            "name": "Rebound Hypertension",
            "mesh_id": None,
            "umls_id": None,
            "icd10cm_id": None,
        },
        {
            "symmap_id": "SMMS_ESS",
            "name": "Essential Hypertension",
            "mesh_id": "C562386",
            "umls_id": "C0085580",
            "icd10cm_id": "I10",
        },
    ]
    result = match_symptom("Hypertension", modern=modern_dual, tcm=[], diseases=[])
    assert result is not None
    assert result.symmap_id == "SMMS_ESS", (
        f"Expected MeSH-anchored Essential Hypertension; got "
        f"{result.symmap_id} ({result.disease_name}) with mesh_id={result.mesh_id}"
    )
    assert result.mesh_id == "C562386"


# ---------------------------------------------------------------------------
# Tier 4 — fallback to target_diseases substring search
# ---------------------------------------------------------------------------


def test_fallback_to_diseases_when_no_symmap_match():
    """Bile insufficiency has no SymMap row in our fixture but appears in diseases."""
    result = match_symptom(
        "Bile insufficiency", modern=MODERN, tcm=TCM, diseases=DISEASES
    )
    assert result is not None
    assert result.source == "string_match"
    # Fallback rows have NO formal IDs.
    assert result.mesh_id is None
    assert result.umls_id is None
    assert result.symmap_id is None
    # Lower score than SymMap matches.
    assert result.match_score < 0.7


def test_returns_none_when_nothing_matches_anywhere():
    result = match_symptom(
        "Totally unknown symptom xyz", modern=MODERN, tcm=TCM, diseases=DISEASES
    )
    assert result is None


# ---------------------------------------------------------------------------
# Score range invariant — used by audit gate test
# ---------------------------------------------------------------------------


def test_content_token_tier_catches_memory_decline():
    """Memory decline → 'Memory Loss Or Impairment' via content-token (tier 3.5).

    Neither Jaccard (≥0.5) nor substring containment hit; only the
    content-token tier rescues this. Audit acceptance: this should resolve
    to a SymMap row with a MeSH ID.
    """
    modern_with_memory = MODERN + [
        {
            "symmap_id": "SMMS0099",
            "name": "Memory Loss Or Impairment",
            "mesh_id": "D008569",
            "umls_id": None,
            "icd10cm_id": None,
        }
    ]
    result = match_symptom(
        "Memory decline", modern=modern_with_memory, tcm=TCM, diseases=DISEASES
    )
    assert result is not None
    assert result.symmap_id == "SMMS0099"
    assert result.mesh_id == "D008569"
    assert result.match_score == 0.4


def test_content_token_tier_skips_stopword_only_overlap():
    """'Low libido' should match 'Libido Decreased' on 'libido', not on 'low'."""
    modern_with_libido = MODERN + [
        {
            "symmap_id": "SMMS0100",
            "name": "Libido Decreased",
            "mesh_id": "D007989",
            "umls_id": None,
            "icd10cm_id": None,
        },
        # A row that ONLY shares the stopword 'low' — must not be picked.
        {
            "symmap_id": "SMMS0101",
            "name": "Low Birth Weight",
            "mesh_id": "D008106",
            "umls_id": None,
            "icd10cm_id": None,
        },
    ]
    result = match_symptom(
        "Low libido", modern=modern_with_libido, tcm=TCM, diseases=DISEASES
    )
    assert result is not None
    assert result.symmap_id == "SMMS0100", (
        f"Expected SMMS0100 (Libido Decreased) but got {result.symmap_id} "
        f"({result.disease_name}). Stopword 'low' should NOT anchor a match."
    )


def test_match_score_always_in_unit_interval():
    """Audit gate: match_score must always be in [0, 1]."""
    queries = [
        "Inflammation",
        "Diabetes",
        "Hypertension",
        "Pain",
        "Heart Disease",
        "Bile insufficiency",
        "Hair loss",
        "Cancer",
    ]
    for q in queries:
        r = match_symptom(q, modern=MODERN, tcm=TCM, diseases=DISEASES)
        if r is not None:
            assert 0.0 <= r.match_score <= 1.0, (
                f"match_score for {q!r} = {r.match_score} outside [0,1]"
            )
