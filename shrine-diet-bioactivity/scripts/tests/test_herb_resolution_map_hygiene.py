"""Source + behavior gates on build_herb_resolution_map.py (#56 #58)."""
from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "build_herb_resolution_map.py"


# ---- Issue #56: don't silently swallow FK violations --------------------


def test_inserts_distinguish_fk_violation_from_duplicate():
    """``INSERT OR IGNORE`` swallows both duplicate-PK AND FK-violation
    errors silently. The resolver's intent is to dedup duplicates, not to
    hide referential-integrity bugs. The file must not use
    ``INSERT OR IGNORE`` against ``herb_resolution_map`` — switch to a
    try/except that distinguishes the two cases.
    """
    src = SCRIPT.read_text()
    # The bug shape: an INSERT OR IGNORE statement targeting the table.
    assert "INSERT OR IGNORE INTO herb_resolution_map" not in src, (
        "Use try/except IntegrityError (or distinct INSERT semantics) so "
        "FK violations are surfaced, not silently dropped (#56)."
    )


# ---- Issue #58: DDL must be transactional ------------------------------


def test_ddl_application_is_transactional():
    """``conn.executescript(DDL)`` auto-commits any open transaction and
    runs the DDL with autocommit semantics — partial failures leave
    half-created tables. Wrap DDL execution so a mid-script failure rolls
    back (#58)."""
    src = SCRIPT.read_text()
    # The fix should replace bare ``conn.executescript(DDL)`` with either:
    #   - a ``with conn:`` block, or
    #   - explicit BEGIN/COMMIT around per-statement executes.
    # Either way the bare top-level executescript call is gone.
    assert "conn.executescript(DDL)" not in src, (
        "DDL application must be transactional (#58). Wrap in `with conn:` "
        "or run statements individually inside a BEGIN/COMMIT block."
    )
