"""Compound concentration unit normalization (Phase 5 / spec §4.2 Stage 1).

Pure logic. Converts a (value, unit) pair from `compound_foods.content_unit`
into mg per gram of food, returning None for unsupported units. Unit
distribution observed in the live DB:

  mg/100g, mg/100 g, mg/100 g of dry matter, mg/100 g freshweight  → ~67K rows
  mg/kg                                                              → ~100 rows
  uM, IU, α-TE, RE, NE                                               → ~3K rows (no MW; unsupported)

Rule for unsupported: return None so the caller can emit a per-row warning.
We never silently use a row we can't normalize — the diet score must reflect
real exposure, not arbitrary numeric guesses.
"""

from __future__ import annotations

from typing import Optional

# Map of canonical content_unit string → mg-per-gram conversion factor.
#   value × factor = mg per gram of food
_FACTORS: dict[str, float] = {
    # mg / 100g family — value is mg per 100g, divide by 100 → mg/g.
    "mg/100g": 0.01,
    "mg/100 g": 0.01,
    "mg/100 g of dry matter": 0.01,
    "mg/100 g freshweight": 0.01,
    # mg / kg — value is mg per 1000g, divide by 1000 → mg/g.
    "mg/kg": 0.001,
}


def to_mg_per_gram(value: Optional[float], unit: Optional[str]) -> Optional[float]:
    """Convert a compound concentration to mg per gram of food.

    Returns None when:
      - value is None or negative
      - unit is None, empty, or not in the supported set

    The supported set covers ~99% of `compound_foods` rows in the live DB.
    Unsupported units (uM, IU, α-TE, RE, NE) require per-substance constants
    we don't have; callers should treat None as "skip + warn", not "error".
    """
    if value is None or value < 0:
        return None
    if not unit:
        return None
    factor = _FACTORS.get(unit)
    if factor is None:
        return None
    return value * factor
