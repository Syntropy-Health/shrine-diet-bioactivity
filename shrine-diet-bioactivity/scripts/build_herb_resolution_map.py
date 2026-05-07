"""Build the Duke ↔ HERB 2.0 herb resolution map (audit §4.3 / Gap 3).

Reads:
  - herbs                (2,376 Duke herbs with scientific_name, common_name, alternate_names)
  - herb2_herbs          (7,263 HERB 2.0 herbs with name_en + latin)

Writes:
  - herb_resolution_map  (DDL guarded with CREATE TABLE IF NOT EXISTS)

Idempotent: DELETE then INSERT inside a single transaction. Safe to re-run.

Usage:
  python scripts/build_herb_resolution_map.py --db data_local/herbal_botanicals.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from herb_matcher import match_herbs  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS herb_resolution_map (
    duke_id      TEXT NOT NULL,
    herb2_id     TEXT NOT NULL,
    match_type   TEXT NOT NULL,
    match_score  REAL NOT NULL,
    PRIMARY KEY (duke_id, herb2_id, match_type),
    FOREIGN KEY (duke_id)  REFERENCES herbs(id),
    FOREIGN KEY (herb2_id) REFERENCES herb2_herbs(herb_id)
);
CREATE INDEX IF NOT EXISTS idx_hrm_duke   ON herb_resolution_map(duke_id);
CREATE INDEX IF NOT EXISTS idx_hrm_herb2  ON herb_resolution_map(herb2_id);
CREATE INDEX IF NOT EXISTS idx_hrm_score  ON herb_resolution_map(match_score);
"""


def _build_argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "Build herb_resolution_map").split("\n\n")[0]
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--db", type=Path, required=True)
    return ap


def _load_duke(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT id, scientific_name, common_name, alternate_names FROM herbs"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _load_herb2(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT herb_id, name_en, latin FROM herb2_herbs WHERE latin IS NOT NULL"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main() -> int:
    args = _build_argparser().parse_args()
    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    # SQLite disables FK enforcement by default; turn it on so the
    # FOREIGN KEY clauses in herb_resolution_map's DDL actually validate
    # at insert time. Per code review: without this the FK clauses are
    # documentation-only.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)

    print("Loading herbs ...")
    duke = _load_duke(conn)
    herb2 = _load_herb2(conn)
    print(f"  {len(duke)} Duke herbs, {len(herb2)} HERB 2.0 herbs (with Latin)")

    print("Computing matches ...")
    matches = match_herbs(duke=duke, herb2=herb2)
    print(f"  {len(matches)} match records across all tiers")

    insert_sql = """
        INSERT OR IGNORE INTO herb_resolution_map
          (duke_id, herb2_id, match_type, match_score)
        VALUES (?, ?, ?, ?)
    """

    inserted = 0
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM herb_resolution_map")
            for m in matches:
                cur.execute(
                    insert_sql,
                    (m.duke_id, m.herb2_id, m.match_type, m.match_score),
                )
                inserted += 1
    finally:
        conn.close()

    # Re-open to compute coverage stats. try/finally guarantees the
    # connection closes even if a stats query throws (e.g., concurrent
    # schema change between the load and the report).
    conn = sqlite3.connect(str(args.db))
    try:
        n_duke = conn.execute("SELECT COUNT(*) FROM herbs").fetchone()[0]
        n_resolved = conn.execute(
            "SELECT COUNT(DISTINCT duke_id) FROM herb_resolution_map"
        ).fetchone()[0]
        by_tier = dict(
            conn.execute(
                "SELECT match_type, COUNT(DISTINCT duke_id) "
                "FROM herb_resolution_map GROUP BY match_type"
            ).fetchall()
        )
    finally:
        conn.close()

    coverage = n_resolved / n_duke if n_duke else 0.0
    print(f"\nInserted {inserted} match rows")
    print(f"  Duke herbs with ≥1 match: {n_resolved}/{n_duke} ({coverage:.1%})")
    print("  By tier (distinct Duke herbs reaching each):")
    for tier, n in by_tier.items():
        print(f"    {tier}: {n}")
    if coverage < 0.75:
        print(
            "WARNING: coverage below 75% — audit §4.3 acceptance not met. "
            "Inspect herbs.scientific_name normalization."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
