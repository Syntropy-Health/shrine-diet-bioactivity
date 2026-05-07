"""Populate compound_identity for active compounds in herbal_botanicals.db.

Phase 1 pipeline (post-harden):
  1. Pick active subset: compounds in herb_compounds ∪ compound_targets
     (avoid wasting API calls on unused compounds)
  2. PubChem PUG-REST: name → CID + InChIKey + SMILES (cached on disk)
  3. RDKit verify: recompute InChIKey from returned SMILES; flag mismatches
  4. UniChem cross-refs: InChIKey → ChEMBL/KEGG/ChEBI/DrugBank IDs

Usage:
  # Smoke (fixture UniChem, no PubChem network):
  python scripts/build_compound_identity.py \\
      --db data_local/herbal_botanicals.db \\
      --unichem-tsv lightrag/tests/fixtures/unichem_subset.tsv \\
      --pubchem-cache /tmp/pc_smoke.json \\
      --no-pubchem --limit 50

  # Real run on active subset (~25K compounds):
  python scripts/build_compound_identity.py \\
      --db data_local/herbal_botanicals.db \\
      --unichem-tsv data/unichem_src1_22_2_6_7.tsv \\
      --pubchem-cache data_local/pubchem_name_cache.json
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root: project_root/scripts/build_compound_identity.py
# imports lightrag/identity_bridge.py via the inserted path.
sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from identity_bridge import (  # noqa: E402
    compute_inchikey,
    load_unichem_mapping,
    resolve_compound_by_name,
)

# Compounds appearing in any structural relationship — herb attribution or
# target binding. Skips orphan compounds (no herb, no target) so Phase 1 stays
# bounded. Use --include-orphans for full backfill.
ACTIVE_SUBSET_SQL = """
SELECT DISTINCT c.id, c.name
FROM compounds c
WHERE c.id IN (SELECT compound_id FROM herb_compounds)
   OR c.id IN (SELECT compound_id FROM compound_targets)
ORDER BY c.id
"""

UPSERT_SQL = """
INSERT OR REPLACE INTO compound_identity
  (compound_id, inchikey, inchi, smiles, pubchem_cid, chembl_id,
   kegg_compound_id, drugbank_id, chebi_id,
   unichem_src_count, resolution_method, resolved_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _build_argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "Build compound_identity").split("\n\n")[0]
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--unichem-tsv", type=Path, required=True)
    ap.add_argument("--pubchem-cache", type=Path, required=True)
    ap.add_argument(
        "--no-pubchem",
        action="store_true",
        help="skip online PubChem fallback (smoke mode)",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--include-orphans",
        action="store_true",
        help="resolve all compounds, not just the active subset",
    )
    return ap


def main() -> int:
    args = _build_argparser().parse_args()

    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2
    if not args.unichem_tsv.exists():
        print(f"ERROR: UniChem TSV not found: {args.unichem_tsv}", file=sys.stderr)
        return 2

    print(f"Loading UniChem mapping from {args.unichem_tsv} ...")
    unichem = load_unichem_mapping(args.unichem_tsv)
    print(f"  {len(unichem)} InChIKeys mapped")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if args.include_orphans:
        query = "SELECT id, name FROM compounds"
    else:
        query = ACTIVE_SUBSET_SQL
    if args.limit:
        query += f" LIMIT {args.limit}"

    rows = list(cur.execute(query))
    total = len(rows)
    print(f"Resolving {total} compound names ...")

    resolved_pubchem = 0
    resolved_rdkit_verified = 0
    matched_unichem = 0
    rdkit_mismatches = 0
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started = time.time()

    for idx, row in enumerate(rows):
        compound_id = row["id"]
        name = row["name"]
        inchikey: str | None = None
        inchi: str | None = None
        smiles: str | None = None
        cid: int | None = None
        method: str | None = None

        if name and not args.no_pubchem:
            pubchem = resolve_compound_by_name(name, cache_path=args.pubchem_cache)
            if pubchem:
                inchikey = pubchem.inchikey
                cid = pubchem.cid
                smiles = pubchem.smiles
                method = "pubchem_name"
                resolved_pubchem += 1
                if smiles:
                    rdkit_id = compute_inchikey(smiles)
                    if rdkit_id and rdkit_id.inchikey == inchikey:
                        resolved_rdkit_verified += 1
                        inchi = rdkit_id.inchi
                    elif rdkit_id and rdkit_id.inchikey != inchikey:
                        rdkit_mismatches += 1

        xrefs = unichem.get(inchikey, {}) if inchikey else {}
        if xrefs:
            matched_unichem += 1
            cid = cid or xrefs.get("pubchem_cid")

        if not (inchikey or xrefs):
            continue

        cur.execute(
            UPSERT_SQL,
            (
                compound_id,
                inchikey,
                inchi,
                smiles,
                cid,
                xrefs.get("chembl_id"),
                xrefs.get("kegg_compound_id"),
                xrefs.get("drugbank_id"),
                xrefs.get("chebi_id"),
                xrefs.get("unichem_src_count", 0),
                method or "unknown",
                now_iso,
            ),
        )

        if (idx + 1) % 500 == 0:
            conn.commit()
            elapsed = time.time() - started
            rate = (idx + 1) / elapsed if elapsed else 0
            eta_min = ((total - idx - 1) / rate / 60) if rate else 0
            print(
                f"  [{idx + 1}/{total}] resolved_pubchem={resolved_pubchem} "
                f"matched_unichem={matched_unichem} "
                f"rate={rate:.1f}/s eta={eta_min:.1f}min"
            )

    conn.commit()
    conn.close()

    coverage = matched_unichem / total if total else 0.0
    print(
        f"\nResolved via PubChem: {resolved_pubchem} "
        f"(RDKit-verified: {resolved_rdkit_verified}, "
        f"mismatches: {rdkit_mismatches})"
    )
    print(f"UniChem cross-refs matched: {matched_unichem}/{total} ({coverage:.1%})")
    if total and coverage < 0.50:
        print(
            "WARNING: cross-ref coverage below 50% — see runbook stub "
            "harden-plan/scope/full-94k-name-resolution-deferred."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
