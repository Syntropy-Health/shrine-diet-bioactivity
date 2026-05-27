"""Unit tests for the Duke ↔ HERB 2.0 herb matcher (audit §4.3 / Gap 3).

Pure logic — no DB. The matcher is fed lists of dicts mirroring the live
shapes of `herbs` (Duke) and `herb2_herbs` (HERB 2.0), and returns one or
more ``HerbMatch`` records per Duke herb across four tiers:

  Tier 1 — latin_exact     score 1.0
  Tier 2 — binomial        score 0.85  (first two tokens match: Genus species)
  Tier 3 — common_name     score 0.7   (Duke common_name == HERB2 name_en)
  Tier 4 — genus           score 0.5   (first token only)

A Duke herb may produce multiple matches across tiers — the resolver keeps
all of them so callers can rank or filter.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from herb_matcher import (  # noqa: E402
    HerbMatch,
    binomial_key,
    genus_key,
    match_herbs,
)


# --- fixture data ----------------------------------------------------------

DUKE = [
    {  # exact Latin hit + binomial + genus all match the same herb2 row
        "id": "d-okra",
        "scientific_name": "Abelmoschus esculentus",
        "common_name": "Okra",
        "alternate_names": json.dumps(["Okra", "Lady's Finger"]),
    },
    {  # subspecies — binomial trims off subsp.
        "id": "d-yarrow",
        "scientific_name": "Achillea millefolium subsp. lanulosa",
        "common_name": "Yarrow",
        "alternate_names": json.dumps(["Yarrow", "Milfoil"]),
    },
    {  # only a common-name match
        "id": "d-foxglove",
        "scientific_name": "Foxgloveus garbageus",  # nonsense Latin
        "common_name": "Foxglove",
        "alternate_names": json.dumps(["Foxglove"]),
    },
    {  # only genus matches
        "id": "d-orphan-genus",
        "scientific_name": "Erythrina suspiciosa",
        "common_name": "Suspicious Coral Tree",
        "alternate_names": "[]",
    },
    {  # nothing matches
        "id": "d-unknown",
        "scientific_name": "Plantarum mysteriosum",
        "common_name": "Mystery Plant",
        "alternate_names": "[]",
    },
]

HERB2 = [
    {"herb_id": "H-OKRA", "name_en": "Okra", "latin": "Abelmoschus esculentus"},
    {
        "herb_id": "H-YARROW",
        "name_en": "Common Yarrow",
        "latin": "Achillea millefolium",
    },
    {"herb_id": "H-FOXGLOVE", "name_en": "Foxglove", "latin": "Digitalis purpurea"},
    {"herb_id": "H-CORAL", "name_en": "Coral Tree", "latin": "Erythrina abyssinica"},
    {
        "herb_id": "H-NULL",
        "name_en": "Mystery",
        "latin": None,
    },  # null latin — must skip
]


# --- key extraction helpers ------------------------------------------------


def test_binomial_key_strips_subspecies():
    assert (
        binomial_key("Achillea millefolium subsp. lanulosa") == "achillea millefolium"
    )
    assert binomial_key("Abelmoschus esculentus") == "abelmoschus esculentus"


def test_binomial_key_handles_single_token_or_empty():
    assert binomial_key("Achillea") is None
    assert binomial_key("") is None
    assert binomial_key(None) is None


def test_genus_key_first_token_lowercase():
    assert genus_key("Achillea millefolium") == "achillea"
    assert genus_key("ABELMOSCHUS esculentus") == "abelmoschus"
    assert genus_key("") is None


# --- matching tiers --------------------------------------------------------


def test_match_herbs_tier1_latin_exact_returns_score_1():
    matches = match_herbs(duke=DUKE[:1], herb2=HERB2)
    okra = [m for m in matches if m.duke_id == "d-okra"]
    latin_exact = [m for m in okra if m.match_type == "latin_exact"]
    assert len(latin_exact) == 1
    assert latin_exact[0].herb2_id == "H-OKRA"
    assert latin_exact[0].match_score == 1.0


def test_match_herbs_tier2_binomial_for_subspecies_yarrow():
    """Achillea millefolium subsp. lanulosa → matches Achillea millefolium via binomial."""
    matches = match_herbs(duke=[DUKE[1]], herb2=HERB2)
    yarrow = [m for m in matches if m.duke_id == "d-yarrow"]
    bin_matches = [m for m in yarrow if m.match_type == "binomial"]
    assert any(m.herb2_id == "H-YARROW" for m in bin_matches)
    bin_match = next(m for m in bin_matches if m.herb2_id == "H-YARROW")
    assert bin_match.match_score == 0.85


def test_match_herbs_tier3_common_name():
    """Foxglove has nonsense Latin but Duke common_name == HERB2 name_en."""
    matches = match_herbs(duke=[DUKE[2]], herb2=HERB2)
    fg = [
        m
        for m in matches
        if m.duke_id == "d-foxglove" and m.match_type == "common_name"
    ]
    assert len(fg) == 1
    assert fg[0].herb2_id == "H-FOXGLOVE"
    assert fg[0].match_score == 0.7


def test_match_herbs_tier4_genus_only():
    """Erythrina suspiciosa shares only genus with Erythrina abyssinica."""
    matches = match_herbs(duke=[DUKE[3]], herb2=HERB2)
    coral = [m for m in matches if m.duke_id == "d-orphan-genus"]
    assert any(
        m.match_type == "genus" and m.herb2_id == "H-CORAL" and m.match_score == 0.5
        for m in coral
    )


def test_match_herbs_no_match_returns_no_rows():
    matches = match_herbs(duke=[DUKE[4]], herb2=HERB2)
    assert [m for m in matches if m.duke_id == "d-unknown"] == []


# --- multi-tier records for one Duke herb ---------------------------------


def test_okra_emits_all_three_tiers_simultaneously():
    """Abelmoschus esculentus / Okra hits Latin-exact, binomial, common-name,
    and genus on H-OKRA — record all four."""
    matches = match_herbs(duke=[DUKE[0]], herb2=HERB2)
    okra_to_h_okra = [
        m for m in matches if m.duke_id == "d-okra" and m.herb2_id == "H-OKRA"
    ]
    types = {m.match_type for m in okra_to_h_okra}
    assert {"latin_exact", "binomial", "common_name", "genus"}.issubset(types)


def test_higher_tier_wins_when_consumer_dedupes():
    """Tests that the consumer pattern of 'pick max score per (duke_id, herb2_id)'
    yields tier-1 (1.0) for okra over the same row's tier-4 (0.5)."""
    matches = match_herbs(duke=[DUKE[0]], herb2=HERB2)
    by_pair: dict[tuple[str, str], float] = {}
    for m in matches:
        key = (m.duke_id, m.herb2_id)
        by_pair[key] = max(by_pair.get(key, 0.0), m.match_score)
    assert by_pair[("d-okra", "H-OKRA")] == 1.0


# --- invariants ------------------------------------------------------------


def test_match_score_in_unit_interval():
    matches = match_herbs(duke=DUKE, herb2=HERB2)
    for m in matches:
        assert 0.0 <= m.match_score <= 1.0, f"{m} out of range"


def test_match_returns_dataclass_records():
    matches = match_herbs(duke=DUKE[:1], herb2=HERB2)
    assert all(isinstance(m, HerbMatch) for m in matches)


def test_null_latin_in_herb2_is_skipped():
    """herb2 row with NULL latin must not crash the matcher."""
    matches = match_herbs(duke=DUKE, herb2=HERB2)
    # H-NULL has latin=None and a generic name_en; common_name "Mystery Plant"
    # contains "Mystery" but exact-match only on common_name. Let me not assert on
    # whether it matches — just that it doesn't crash.
    # Defensive assertion: no match record points at H-NULL via latin-derived tiers.
    bad = [
        m
        for m in matches
        if m.herb2_id == "H-NULL"
        and m.match_type in {"latin_exact", "binomial", "genus"}
    ]
    assert bad == [], (
        f"Should not derive Latin-tier matches from null-latin herb2: {bad}"
    )


# ---- Issue #57: Tier 1/2/4 must dedup the same way Tier 3 does ----------


def test_no_duplicate_match_records_across_tiers():
    """``seen_pairs`` should keep distinct (duke_id, herb2_id, match_type)
    triples; same (duke, herb2) appearing twice in the same tier is a
    matcher bug. Tier 3 had the guard; Tiers 1/2/4 must follow (#57).
    """
    duke = [{
        "id": "D-X",
        "scientific_name": "Astragalus membranaceus",
        "common_name": "milk-vetch",
        "alternate_names": "milk-vetch",
    }]
    # Two herb2 rows with the same herb_id + latin (known mode in the
    # source data when multiple regional accessions list one botanical).
    herb2 = [
        {"herb_id": "H-X", "name_en": "milk-vetch", "latin": "Astragalus membranaceus"},
        {"herb_id": "H-X", "name_en": "milk-vetch", "latin": "Astragalus membranaceus"},
    ]
    matches = match_herbs(duke=duke, herb2=herb2)
    seen = set()
    dupes = []
    for m in matches:
        key = (m.duke_id, m.herb2_id, m.match_type)
        if key in seen:
            dupes.append(m)
        seen.add(key)
    assert dupes == [], (
        f"Duplicate (duke_id, herb2_id, match_type) records: {dupes} "
        "(see #57 — Tier 1/2/4 need the same seen_pairs guard as Tier 3)."
    )


# ---- Issue #24[7]: per-Duke genus cap -----------------------------------


def test_match_herbs_caps_genus_tier_per_duke_herb():
    """For widespread genera (Astragalus ~3K species, Carex ~2K, Senecio
    ~1.25K), each Duke herb can produce hundreds of genus-tier rows. The
    matcher accepts an optional ``max_genus_matches_per_duke_herb`` (#24[7])
    that caps Tier-4 records per Duke herb without affecting Tiers 1-3.
    """
    duke = [{"id": "D-A", "scientific_name": "Astragalus membranaceus"}]
    herb2 = [
        {"herb_id": f"H-{i}", "name_en": f"sp{i}", "latin": f"Astragalus sp{i}"}
        for i in range(120)
    ]
    matches = match_herbs(
        duke=duke, herb2=herb2, max_genus_matches_per_duke_herb=50
    )
    genus_count = sum(1 for m in matches if m.match_type == "genus")
    assert genus_count <= 50, (
        f"genus cap not enforced: produced {genus_count} > 50 (#24[7])"
    )


# ---- Issue #24[8]: hybrid mark in binomial_key -------------------------


def test_binomial_key_drops_hybrid_mark():
    """``Mentha × piperita`` → binomial key ``mentha piperita`` (drop the
    botanical hybrid mark ``×``). Before the fix the key was ``mentha ×``
    which never matched Duke's plain binomials (#24[8])."""
    assert binomial_key("Mentha × piperita") == "mentha piperita"
    assert binomial_key("Citrus × paradisi") == "citrus paradisi"


def test_binomial_key_drops_authority_apostrophe():
    """Tokens beginning with ``'`` are authority markers (e.g.
    ``'Lavendula 'Hidcote''``) and should be dropped (#24[8])."""
    # Multi-token authority: 'Hidcote' is a cultivar tag.
    assert binomial_key("Lavandula 'Hidcote' angustifolia") == "lavandula angustifolia"
