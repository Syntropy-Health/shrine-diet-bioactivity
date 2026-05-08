"""Build the canonical disease registry (Phase 3 / spec §4.3).

Reads disease names + formal IDs from:
  - target_diseases.disease_name        (CMAUP — bare names, no formal IDs)
  - symmap_modern_symptoms              (mesh_id, umls_id, icd10cm_id, hpo_id)
  - chemical_diseases (disease_name, disease_id='MESH:Dxxxxxx')
  - herb2_herb_disease.disease_label    (HERB 2.0 — bare names; disease_id is internal)

Writes to diseases_canonical (one canonical row per real-world disease) and
disease_name_aliases (every observed disease string, joined back to canonical).

Idempotent — UPSERT semantics keyed on the formal-ID priority chain
(MeSH → UMLS → ICD-10 → local slug). Safe to re-run after each source-data refresh.

Usage:
  python scripts/build_disease_canonical.py --db data_local/herbal_botanicals.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from disease_canon import canonical_id, parse_disease_id  # noqa: E402


def _build_argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "Build disease canonical").split("\n\n")[0]
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--db", type=Path, required=True)
    return ap


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _upsert_canonical(
    conn: sqlite3.Connection,
    *,
    preferred_name: str,
    mesh: str | None,
    umls: str | None,
    icd10: str | None,
    hpo: str | None,
    source_origin: str,
    now_iso: str,
) -> str | None:
    """Insert (or fetch existing) the canonical row by formal-ID priority.

    Returns the canonical id, or None if we have nothing anchorable.
    """
    if mesh:
        row = conn.execute(
            "SELECT id FROM diseases_canonical WHERE mesh_id=?", (mesh,)
        ).fetchone()
        if row:
            return row[0]
    if umls:
        row = conn.execute(
            "SELECT id FROM diseases_canonical WHERE umls_id=?", (umls,)
        ).fetchone()
        if row:
            return row[0]

    if not (mesh or umls or icd10 or preferred_name):
        return None

    cid = canonical_id(mesh=mesh, umls=umls, icd10=icd10, preferred_name=preferred_name)
    # Fall back: existence check by primary key for local slugs (multiple
    # bare-name diseases may collide under the same slug; first writer wins).
    row = conn.execute(
        "SELECT id FROM diseases_canonical WHERE id=?", (cid,)
    ).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO diseases_canonical "
        "(id, preferred_name, mesh_id, umls_id, icd10cm_id, hpo_id, source_origin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, preferred_name, mesh, umls, icd10, hpo, source_origin, now_iso),
    )
    return cid


def _add_alias(
    conn: sqlite3.Connection, *, disease_id: str, alias: str, source: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO disease_name_aliases "
        "(disease_id, alias, source) VALUES (?, ?, ?)",
        (disease_id, alias, source),
    )


def _ingest_symmap(conn: sqlite3.Connection, now_iso: str) -> tuple[int, int]:
    """SymMap is the cleanest source — formal IDs are populated."""
    if not _table_exists(conn, "symmap_modern_symptoms"):
        return (0, 0)
    rows = conn.execute(
        "SELECT name, mesh_id, umls_id, icd10cm_id, hpo_id "
        "FROM symmap_modern_symptoms WHERE name IS NOT NULL"
    ).fetchall()
    n_canonical = 0
    n_aliases = 0
    for name, mesh, umls, icd10, hpo in rows:
        cid = _upsert_canonical(
            conn,
            preferred_name=name,
            mesh=mesh,
            umls=umls,
            icd10=icd10,
            hpo=hpo,
            source_origin="symmap",
            now_iso=now_iso,
        )
        if cid:
            _add_alias(conn, disease_id=cid, alias=name, source="symmap")
            n_canonical += 1
            n_aliases += 1
    return (n_canonical, n_aliases)


def _ingest_ctd(conn: sqlite3.Connection, now_iso: str) -> tuple[int, int]:
    """CTD's disease_id is 'MESH:Dxxxxxx' — strip prefix, anchor on MeSH."""
    if not _table_exists(conn, "chemical_diseases"):
        return (0, 0)
    rows = conn.execute(
        "SELECT DISTINCT disease_name, disease_id FROM chemical_diseases "
        "WHERE disease_name IS NOT NULL"
    ).fetchall()
    n_canonical = 0
    n_aliases = 0
    for name, raw_id in rows:
        prefix, value = parse_disease_id(raw_id or "")
        mesh = value if prefix == "mesh" else None
        cid = _upsert_canonical(
            conn,
            preferred_name=name,
            mesh=mesh,
            umls=None,
            icd10=None,
            hpo=None,
            source_origin="ctd",
            now_iso=now_iso,
        )
        if cid:
            _add_alias(conn, disease_id=cid, alias=name, source="ctd")
            n_canonical += 1
            n_aliases += 1
    return (n_canonical, n_aliases)


def _ingest_target_diseases(conn: sqlite3.Connection, now_iso: str) -> tuple[int, int]:
    """CMAUP target_diseases — bare names, no formal IDs.

    Resolve via existing alias first (so 'Diabetes Mellitus' from CMAUP joins
    the SymMap-anchored canonical row); otherwise create local-slug canonical.
    """
    if not _table_exists(conn, "target_diseases"):
        return (0, 0)
    rows = conn.execute(
        "SELECT DISTINCT disease_name FROM target_diseases "
        "WHERE disease_name IS NOT NULL"
    ).fetchall()
    n_canonical = 0
    n_aliases = 0
    for (name,) in rows:
        existing = conn.execute(
            "SELECT disease_id FROM disease_name_aliases "
            "WHERE lower(alias) = lower(?) LIMIT 1",
            (name,),
        ).fetchone()
        if existing:
            cid = existing[0]
        else:
            cid = _upsert_canonical(
                conn,
                preferred_name=name,
                mesh=None,
                umls=None,
                icd10=None,
                hpo=None,
                source_origin="target_diseases",
                now_iso=now_iso,
            )
            if cid:
                n_canonical += 1
        if cid:
            _add_alias(conn, disease_id=cid, alias=name, source="target_diseases")
            n_aliases += 1
    return (n_canonical, n_aliases)


def _ingest_herb2(conn: sqlite3.Connection, now_iso: str) -> tuple[int, int]:
    """HERB 2.0 herb_disease — column is disease_label (NOT 'disease' as
    the un-hardened spec said). Bare names; resolve via alias when possible.
    """
    if not _table_exists(conn, "herb2_herb_disease"):
        return (0, 0)
    rows = conn.execute(
        "SELECT DISTINCT disease_label FROM herb2_herb_disease "
        "WHERE disease_label IS NOT NULL"
    ).fetchall()
    n_canonical = 0
    n_aliases = 0
    for (name,) in rows:
        existing = conn.execute(
            "SELECT disease_id FROM disease_name_aliases "
            "WHERE lower(alias) = lower(?) LIMIT 1",
            (name,),
        ).fetchone()
        if existing:
            cid = existing[0]
        else:
            cid = _upsert_canonical(
                conn,
                preferred_name=name,
                mesh=None,
                umls=None,
                icd10=None,
                hpo=None,
                source_origin="herb2",
                now_iso=now_iso,
            )
            if cid:
                n_canonical += 1
        if cid:
            _add_alias(conn, disease_id=cid, alias=name, source="herb2")
            n_aliases += 1
    return (n_canonical, n_aliases)


def main() -> int:
    args = _build_argparser().parse_args()
    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys = ON")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    counts = {
        "symmap": (0, 0),
        "ctd": (0, 0),
        "target_diseases": (0, 0),
        "herb2": (0, 0),
    }

    try:
        with conn:
            # Order matters: SymMap first (MeSH anchors), then CTD (also MeSH),
            # then bare-name sources that resolve via alias lookup.
            counts["symmap"] = _ingest_symmap(conn, now_iso)
            counts["ctd"] = _ingest_ctd(conn, now_iso)
            counts["target_diseases"] = _ingest_target_diseases(conn, now_iso)
            counts["herb2"] = _ingest_herb2(conn, now_iso)
    finally:
        conn.close()

    # Stats run on a fresh connection inside try/finally (per code-review §23).
    conn = sqlite3.connect(str(args.db))
    try:
        total_canonical = conn.execute(
            "SELECT COUNT(*) FROM diseases_canonical"
        ).fetchone()[0]
        n_with_mesh = conn.execute(
            "SELECT COUNT(*) FROM diseases_canonical WHERE mesh_id IS NOT NULL"
        ).fetchone()[0]
        n_with_umls = conn.execute(
            "SELECT COUNT(*) FROM diseases_canonical WHERE umls_id IS NOT NULL"
        ).fetchone()[0]
        total_aliases = conn.execute(
            "SELECT COUNT(*) FROM disease_name_aliases"
        ).fetchone()[0]
    finally:
        conn.close()

    print(f"\nCanonical diseases: {total_canonical}")
    print(f"  with MeSH id: {n_with_mesh}")
    print(f"  with UMLS id: {n_with_umls}")
    print(f"Aliases: {total_aliases}")
    print("Per-source contribution (canonical, aliases):")
    for src, (n_can, n_ali) in counts.items():
        print(f"  {src}: +{n_can} canonical, +{n_ali} aliases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
