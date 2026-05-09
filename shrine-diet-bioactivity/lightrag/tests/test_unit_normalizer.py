"""Tests for compound_foods.content_unit normalization (Phase 5)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unit_normalizer import to_mg_per_gram  # noqa: E402


# ---- mg/100g family (dominant unit, ~67K rows in live DB) ---------------


def test_mg_per_100g_canonical():
    # 100 mg/100g = 1 mg/g
    assert to_mg_per_gram(100.0, "mg/100g") == 1.0


def test_mg_per_100g_with_internal_space():
    """KEGG and FooDB have inconsistent whitespace on this unit."""
    assert to_mg_per_gram(100.0, "mg/100 g") == 1.0
    assert to_mg_per_gram(100.0, "mg/100 g of dry matter") == 1.0
    assert to_mg_per_gram(100.0, "mg/100 g freshweight") == 1.0


def test_mg_per_100g_handles_decimal_value():
    assert to_mg_per_gram(2380.0, "mg/100g") == 23.8
    assert abs(to_mg_per_gram(0.5, "mg/100g") - 0.005) < 1e-9


def test_mg_per_100g_zero_value():
    assert to_mg_per_gram(0.0, "mg/100g") == 0.0


# ---- mg/kg --------------------------------------------------------------


def test_mg_per_kg():
    # 1000 mg/kg = 1 mg/g
    assert to_mg_per_gram(1000.0, "mg/kg") == 1.0
    assert to_mg_per_gram(2500.0, "mg/kg") == 2.5


# ---- unsupported units return None --------------------------------------


def test_uM_returns_none():
    """Molarity requires molecular weight to convert to mass; unsupported."""
    assert to_mg_per_gram(5.0, "uM") is None


def test_IU_returns_none():
    """International Units require per-substance constants; unsupported."""
    assert to_mg_per_gram(100.0, "IU") is None


def test_alpha_TE_returns_none():
    """α-Tocopherol equivalents need a vitamin-E factor table."""
    assert to_mg_per_gram(10.0, "α-TE") is None


def test_RE_NE_return_none():
    assert to_mg_per_gram(50.0, "RE") is None
    assert to_mg_per_gram(20.0, "NE") is None


def test_completely_unknown_unit_returns_none():
    assert to_mg_per_gram(1.0, "fake_unit_xyz") is None
    assert to_mg_per_gram(1.0, "") is None
    assert to_mg_per_gram(1.0, None) is None  # type: ignore[arg-type]


# ---- input validation ---------------------------------------------------


def test_negative_value_returns_none():
    """Defensive: negative mass per unit is nonsensical and should not be used."""
    assert to_mg_per_gram(-5.0, "mg/100g") is None


def test_none_value_returns_none():
    assert to_mg_per_gram(None, "mg/100g") is None  # type: ignore[arg-type]


# ---- monotonicity invariant ---------------------------------------------


def test_monotonic_in_value_for_supported_units():
    """For any supported unit, output should monotonically increase with input."""
    for unit in ("mg/100g", "mg/100 g", "mg/kg"):
        results = [to_mg_per_gram(v, unit) for v in (1, 10, 100, 1000)]
        assert all(
            a is not None and b is not None and a < b
            for a, b in zip(results, results[1:])
        ), f"Monotonicity broken for unit={unit}: {results}"
