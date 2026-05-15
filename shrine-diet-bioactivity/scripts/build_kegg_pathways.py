"""Ingest KEGG pathway overlay into herbal_botanicals.db (Phase 4 / spec §5.2).

Pulls 3 KEGG REST endpoints (pathway list, compound↔pathway, pathway↔gene),
resolves KEGG gene IDs to HUGO symbols (so they join targets.gene_symbol),
and writes 3 SQLite tables in a single idempotent transaction.

License: KEGG is academic-use-only. Commercial deployments need a license.
This script is the only entry point that fetches KEGG data — drop the
target from CI and the rest of the build pipeline still works.

Usage:
  python scripts/build_kegg_pathways.py --db data_local/herbal_botanicals.db \\
      --cache-dir data_local/kegg_cache
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from kegg_client import KeggClient  # noqa: E402


def _build_argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "Build KEGG pathway overlay").split("\n\n")[0]
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data_local/kegg_cache"),
        help="Directory for KEGG REST response cache (default: data_local/kegg_cache)",
    )
    ap.add_argument(
        "--organism",
        default="hsa",
        help="KEGG organism code (default: hsa = Homo sapiens)",
    )
    return ap


def main() -> int:
    args = _build_argparser().parse_args()
    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    client = KeggClient(cache_dir=args.cache_dir)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"Fetching KEGG pathway list for organism={args.organism}...")
    pathways = client.list_pathways(organism=args.organism)
    print(f"  {len(pathways)} pathways")

    print("Fetching pathway↔compound links...")
    cpd_links_raw = client.list_compound_pathway_links(organism=args.organism)
    # Filter to pathways that exist in our kegg_pathways set. KEGG's compound
    # links live in the organism-agnostic 'map' namespace and we translate
    # 'map00010 → hsa00010' — but some reference pathways have no organism-
    # specific counterpart, and inserting those would violate the FK to
    # kegg_pathways(id). Drop them at the source instead of letting SQLite
    # reject the whole batch.
    valid_pathway_ids = {p["id"] for p in pathways}
    cpd_links = [(pid, cpd) for pid, cpd in cpd_links_raw if pid in valid_pathway_ids]
    n_dropped = len(cpd_links_raw) - len(cpd_links)
    print(
        f"  {len(cpd_links)} compound-pathway links "
        f"({n_dropped} dropped — pathway not in {args.organism})"
    )

    print("Fetching pathway↔gene links...")
    gene_links = client.list_pathway_gene_links(organism=args.organism)
    print(f"  {len(gene_links)} pathway-gene links")

    # Distinct kegg_gene_ids → batch-resolve to HUGO symbols.
    kegg_gene_ids = sorted({gid for _, gid in gene_links})
    print(f"Resolving {len(kegg_gene_ids)} distinct KEGG gene IDs to HUGO symbols...")
    aliases = client.resolve_gene_symbols(kegg_gene_ids)
    print(
        f"  resolved {len(aliases)} ({len(aliases) / max(len(kegg_gene_ids), 1):.1%})"
    )

    # Write all three tables in one atomic transaction.
    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            cur = conn.cursor()

            # Idempotent rebuild — DELETE then INSERT in a single transaction.
            # Order matters: child tables FIRST so FK enforcement allows deletion
            # of pathways without orphans.
            cur.execute("DELETE FROM kegg_compound_pathways")
            cur.execute("DELETE FROM kegg_pathway_genes")
            cur.execute("DELETE FROM kegg_pathways")

            cur.executemany(
                "INSERT INTO kegg_pathways "
                "(id, name, organism, category, ingested_at) "
                "VALUES (?, ?, ?, NULL, ?)",
                [(p["id"], p["name"], p["organism"], now_iso) for p in pathways],
            )

            cur.executemany(
                "INSERT OR IGNORE INTO kegg_compound_pathways "
                "(kegg_compound_id, kegg_pathway_id, ingested_at) "
                "VALUES (?, ?, ?)",
                [(cpd, pid, now_iso) for pid, cpd in cpd_links],
            )

            cur.executemany(
                "INSERT OR IGNORE INTO kegg_pathway_genes "
                "(kegg_pathway_id, kegg_gene_id, gene_symbol, ingested_at) "
                "VALUES (?, ?, ?, ?)",
                [(pid, gid, aliases.get(gid), now_iso) for pid, gid in gene_links],
            )
    finally:
        conn.close()

    # Stats — fresh connection inside try/finally per code-review pattern.
    conn = sqlite3.connect(str(args.db))
    try:
        n_p = conn.execute("SELECT COUNT(*) FROM kegg_pathways").fetchone()[0]
        n_cp = conn.execute("SELECT COUNT(*) FROM kegg_compound_pathways").fetchone()[0]
        n_pg = conn.execute("SELECT COUNT(*) FROM kegg_pathway_genes").fetchone()[0]
        n_pg_resolved = conn.execute(
            "SELECT COUNT(*) FROM kegg_pathway_genes WHERE gene_symbol IS NOT NULL"
        ).fetchone()[0]
        n_join = conn.execute(
            "SELECT COUNT(*) FROM kegg_pathway_genes kpg "
            "JOIN targets t ON t.gene_symbol = kpg.gene_symbol"
        ).fetchone()[0]
    finally:
        conn.close()

    print("\nLoaded:")
    print(f"  kegg_pathways:           {n_p}")
    print(f"  kegg_compound_pathways:  {n_cp}")
    print(f"  kegg_pathway_genes:      {n_pg} ({n_pg_resolved} HUGO-resolved)")
    print(f"  pathway-target joins:    {n_join}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
