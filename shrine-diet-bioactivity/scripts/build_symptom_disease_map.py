"""Build the materialized symptom→disease map (audit §4.2).

Reads:
  - symptoms                   (47 hand-curated symptoms)
  - symmap_modern_symptoms     (1,148 clinical symptoms with MeSH/UMLS/ICD)
  - symmap_tcm_symptoms        (2,285 TCM symptoms via name_en)
  - target_diseases            (795K rows, 2,976 distinct disease names)

Writes:
  - symptom_disease_map (idempotent rebuild — DELETE then INSERT in a
    single transaction so a partial run leaves the prior contents intact).

Usage:
  python scripts/build_symptom_disease_map.py \\
      --db data_local/herbal_botanicals.db \\
      [--max-fallbacks-per-symptom 5]   # cap target_diseases fallbacks
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from symptom_matcher import match_symptom  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS symptom_disease_map (
    symptom_id     TEXT NOT NULL,
    disease_name   TEXT NOT NULL,
    source         TEXT NOT NULL,
    symmap_id      TEXT,
    mesh_id        TEXT,
    umls_id        TEXT,
    icd10cm_id     TEXT,
    match_score    REAL NOT NULL,
    PRIMARY KEY (symptom_id, disease_name, source),
    FOREIGN KEY (symptom_id) REFERENCES symptoms(id)
);
CREATE INDEX IF NOT EXISTS idx_sdm_symptom    ON symptom_disease_map(symptom_id);
CREATE INDEX IF NOT EXISTS idx_sdm_mesh       ON symptom_disease_map(mesh_id);
CREATE INDEX IF NOT EXISTS idx_sdm_score      ON symptom_disease_map(match_score);
"""


def _build_argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "Build symptom_disease_map").split("\n\n")[0]
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument(
        "--max-fallbacks-per-symptom",
        type=int,
        default=5,
        help=(
            "When tier-4 (target_diseases substring) is the only match, "
            "cap how many disease rows to record per symptom (default: 5)."
        ),
    )
    return ap


def _load_modern(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT symmap_id, name, mesh_id, umls_id, icd10cm_id "
        "FROM symmap_modern_symptoms WHERE name IS NOT NULL"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_tcm(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT symmap_id, name_en FROM symmap_tcm_symptoms WHERE name_en IS NOT NULL"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_distinct_diseases(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        "SELECT DISTINCT disease_name FROM target_diseases "
        "WHERE disease_name IS NOT NULL"
    )
    return [row[0] for row in cur.fetchall()]


def main() -> int:
    args = _build_argparser().parse_args()
    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)

    print("Loading SymMap + target_diseases ...")
    modern = _load_modern(conn)
    tcm = _load_tcm(conn)
    diseases = _load_distinct_diseases(conn)
    print(
        f"  {len(modern)} modern symptoms, {len(tcm)} TCM symptoms, "
        f"{len(diseases)} distinct disease names"
    )

    symptoms = [
        {"id": row["id"], "name": row["name"]}
        for row in conn.execute("SELECT id, name FROM symptoms ORDER BY id")
    ]
    print(f"  {len(symptoms)} symptoms to map")

    insert_sql = """
        INSERT OR IGNORE INTO symptom_disease_map
          (symptom_id, disease_name, source, symmap_id, mesh_id,
           umls_id, icd10cm_id, match_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """

    inserted = 0
    matched_symptoms = 0
    matched_with_mesh = 0
    fallback_only = 0

    try:
        with conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM symptom_disease_map")
            for s in symptoms:
                # Primary best match.
                best = match_symptom(
                    s["name"], modern=modern, tcm=tcm, diseases=diseases
                )
                if best is None:
                    continue
                cur.execute(
                    insert_sql,
                    (
                        s["id"],
                        best.disease_name,
                        best.source,
                        best.symmap_id,
                        best.mesh_id,
                        best.umls_id,
                        best.icd10cm_id,
                        best.match_score,
                    ),
                )
                inserted += 1
                matched_symptoms += 1
                if best.mesh_id is not None:
                    matched_with_mesh += 1
                if best.source == "string_match":
                    fallback_only += 1

                # Tier-4 expansion: if the primary match is a fallback, also
                # add a few more target_diseases substring matches so the
                # symptom has more recall in downstream queries. Capped per
                # symptom to avoid blowup on common terms (e.g. Cancer).
                if best.source == "string_match":
                    extras = 0
                    sname = s["name"].lower()
                    for d in diseases:
                        if extras >= args.max_fallbacks_per_symptom - 1:
                            break
                        dn = d.lower()
                        if d == best.disease_name:
                            continue
                        if sname in dn or dn in sname:
                            cur.execute(
                                insert_sql,
                                (
                                    s["id"],
                                    d,
                                    "string_match",
                                    None,
                                    None,
                                    None,
                                    None,
                                    0.3,
                                ),
                            )
                            inserted += 1
                            extras += 1

    finally:
        conn.close()

    print(f"\nInserted {inserted} rows for {matched_symptoms}/{len(symptoms)} symptoms")
    print(f"  with MeSH IDs:    {matched_with_mesh}")
    print(f"  fallback (string) only: {fallback_only}")
    if matched_symptoms < 40:
        print(
            "WARNING: fewer than 40/47 symptoms mapped — audit §4.2 acceptance "
            "criterion not met. Inspect symmap_modern_symptoms.name overlap."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
