"""Phase-1 build-script hygiene gates (#42 #43 #44 #45).

Pure unit tests over source-level + smoke contracts. None of these need the
live KG DB or network.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
LIGHTRAG_DIR = SCRIPTS_DIR.parent / "lightrag"


# ─── Issue #42: distinct resolution_method for RDKit mismatches ────────────


def test_rdkit_mismatches_get_distinct_resolution_method():
    """When RDKit's recomputed InChIKey doesn't match PubChem's, the upserted
    row must carry a distinct ``resolution_method`` value (e.g.
    ``rdkit_mismatch``) so downstream consumers can filter or audit them.

    Before the fix, the mismatch counter incremented but ``method`` stayed
    at ``"pubchem_name"`` — silently mixing verified and unverified rows.
    """
    src = (SCRIPTS_DIR / "build_compound_identity.py").read_text()
    # The fix must assign the distinct method tag — substring match on the
    # rdkit_mismatches counter alone is not sufficient. Look for a string
    # literal "rdkit_mismatch" used as a method value (single, no trailing
    # 'es', so it's the method tag rather than the plural counter).
    assert '"rdkit_mismatch"' in src or "'rdkit_mismatch'" in src, (
        "build_compound_identity.py must assign "
        "resolution_method='rdkit_mismatch' when RDKit disagrees with "
        "PubChem (see #42). Only the counter variable name was found."
    )


# ─── Issue #43: UNIQUE constraint on compound_identity.inchikey ───────────


def test_compound_identity_inchikey_has_unique_index():
    """Schema must enforce one canonical compound_identity row per InChIKey.
    Two different compound names with the same chemistry should resolve to
    the same row, not two rows. Catches resolver bugs early (see #43)."""
    src = (SCRIPTS_DIR / "build-herbal-db.ts").read_text()
    # Look for a UNIQUE constraint specifically on compound_identity(inchikey)
    # — either as a CREATE UNIQUE INDEX or inline column qualifier. Other
    # tables (diseases_canonical) have unrelated UNIQUE indexes.
    import re as _re
    has_unique_idx = _re.search(
        r"CREATE\s+UNIQUE\s+INDEX[^;]*?compound_identity\s*\(\s*inchikey",
        src,
        _re.IGNORECASE | _re.DOTALL,
    )
    # Or an inline UNIQUE on the column.
    has_inline_unique = _re.search(
        r"inchikey\s+TEXT[^,]*?UNIQUE",
        src,
        _re.IGNORECASE,
    )
    assert has_unique_idx or has_inline_unique, (
        "build-herbal-db.ts must declare UNIQUE on "
        "compound_identity(inchikey) (#43). Found only a non-UNIQUE INDEX."
    )


# ─── Issue #44: atomic write for PubChem cache ───────────────────────────


def test_pubchem_cache_write_is_atomic():
    """``write_text`` on the target file is non-atomic — a kill mid-write
    leaves the cache half-flushed and unparseable. Use the tmp-file +
    ``replace`` pattern so the rename is the only operation observers see.
    (see #44)."""
    src = (LIGHTRAG_DIR / "identity_bridge.py").read_text()
    # Either ``os.replace(tmp, target)`` or ``tmp.replace(target)``.
    assert ".replace(" in src or "os.replace" in src, (
        "identity_bridge.py PubChem cache write is not atomic. "
        "Switch to write-then-replace (see #44)."
    )


# ─── Issue #45: smoke tests for build_compound_identity.main +
#               build_bioactivity_evidence.main


@pytest.mark.parametrize(
    "script",
    ["build_compound_identity.py", "build_bioactivity_evidence.py"],
)
def test_build_scripts_help_exits_zero(script: str) -> None:
    """``script.py --help`` must exit 0 — confirms the module imports cleanly
    and argparse is wired up. Cheap CI signal that the script entrypoint
    isn't broken (see #45)."""
    path = SCRIPTS_DIR / script
    if not path.exists():
        pytest.skip(f"script {script} missing — unrelated to this gate")
    proc = subprocess.run(
        [sys.executable, str(path), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"{script} --help exited {proc.returncode}; "
        f"stderr={proc.stderr[:400]}"
    )
    assert "usage:" in (proc.stdout + proc.stderr).lower()
