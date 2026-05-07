"""Duke ↔ HERB 2.0 herb matcher (audit §4.3 / Gap 3).

Pure logic — no DB. Callers feed lists of dicts mirroring the live shapes
of `herbs` (Duke) and `herb2_herbs` (HERB 2.0); the matcher returns one
or more ``HerbMatch`` records per Duke herb across four tiers.

Why a matrix of matches instead of a single best?
  - A genus-level match may co-exist with a Latin-exact match for the
    SAME (duke_id, herb2_id) pair — keep both so callers can rank.
  - A Duke herb at the genus tier may map to multiple HERB 2.0 rows
    (every species of the same genus). Persisting the genus matches
    enables herb2_herb_disease evidence to flow through transitively
    even when the species don't line up exactly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class HerbMatch:
    duke_id: str
    herb2_id: str
    match_type: str  # 'latin_exact' | 'binomial' | 'common_name' | 'genus'
    match_score: float  # in [0.0, 1.0]


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def binomial_key(latin: Optional[str]) -> Optional[str]:
    """First two whitespace-separated tokens of a Latin name, lowercased.

    Trims subspecies / variety / authority annotations:
        "Achillea millefolium subsp. lanulosa" → "achillea millefolium"

    Returns None if the input has fewer than two tokens.
    """
    n = _norm(latin)
    if not n:
        return None
    parts = n.split()
    if len(parts) < 2:
        return None
    return f"{parts[0]} {parts[1]}"


def genus_key(latin: Optional[str]) -> Optional[str]:
    """First whitespace-separated token, lowercased."""
    n = _norm(latin)
    if not n:
        return None
    return n.split()[0]


def _alt_names(raw: Optional[str]) -> list[str]:
    """Parse Duke's alternate_names JSON field. Returns [] on any parse error."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(s) for s in parsed if s]


def match_herbs(*, duke: Iterable[dict], herb2: Iterable[dict]) -> list[HerbMatch]:
    """Resolve Duke herbs to HERB 2.0 herbs across four match tiers.

    Each tier emits its own record per (duke_id, herb2_id) pair — a single
    Duke herb may appear under multiple tiers for the same target.
    """
    duke_list = list(duke)
    herb2_list = list(herb2)

    # Pre-index HERB 2.0 by Latin / binomial / genus / name_en.
    h2_by_latin: dict[str, list[dict]] = {}
    h2_by_binomial: dict[str, list[dict]] = {}
    h2_by_genus: dict[str, list[dict]] = {}
    h2_by_name_en: dict[str, list[dict]] = {}

    for row in herb2_list:
        latin = row.get("latin")
        if latin:
            h2_by_latin.setdefault(_norm(latin), []).append(row)
            bk = binomial_key(latin)
            if bk:
                h2_by_binomial.setdefault(bk, []).append(row)
            gk = genus_key(latin)
            if gk:
                h2_by_genus.setdefault(gk, []).append(row)
        name_en = row.get("name_en")
        if name_en:
            h2_by_name_en.setdefault(_norm(name_en), []).append(row)

    out: list[HerbMatch] = []

    for d in duke_list:
        duke_id = str(d.get("id") or "")
        if not duke_id:
            continue
        sci = d.get("scientific_name") or ""
        common = d.get("common_name")
        alt = _alt_names(d.get("alternate_names"))

        # Tier 1 — Latin exact (case-insensitive).
        for h2 in h2_by_latin.get(_norm(sci), []):
            out.append(
                HerbMatch(
                    duke_id=duke_id,
                    herb2_id=h2["herb_id"],
                    match_type="latin_exact",
                    match_score=1.0,
                )
            )

        # Tier 2 — binomial (first two tokens of Latin).
        bk = binomial_key(sci)
        if bk:
            for h2 in h2_by_binomial.get(bk, []):
                out.append(
                    HerbMatch(
                        duke_id=duke_id,
                        herb2_id=h2["herb_id"],
                        match_type="binomial",
                        match_score=0.85,
                    )
                )

        # Tier 3 — common_name exact (Duke common_name OR alt_names vs HERB2 name_en).
        candidates = [common] + alt if common else alt
        seen_pairs: set[tuple[str, str]] = set()
        for c in candidates:
            for h2 in h2_by_name_en.get(_norm(c), []):
                pair = (duke_id, h2["herb_id"])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                out.append(
                    HerbMatch(
                        duke_id=duke_id,
                        herb2_id=h2["herb_id"],
                        match_type="common_name",
                        match_score=0.7,
                    )
                )

        # Tier 4 — genus (first token of Latin). Lower confidence; broad recall.
        gk = genus_key(sci)
        if gk:
            for h2 in h2_by_genus.get(gk, []):
                out.append(
                    HerbMatch(
                        duke_id=duke_id,
                        herb2_id=h2["herb_id"],
                        match_type="genus",
                        match_score=0.5,
                    )
                )

    return out
