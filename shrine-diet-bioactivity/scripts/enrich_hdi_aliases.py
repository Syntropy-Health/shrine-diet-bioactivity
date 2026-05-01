"""Phase 0 — stamp common_name + aliases on HDI-Safe-50 Herb + Drug nodes.

Closes Blockers 1 + 4 from HANDOFF-blockers-to-engineering.md by giving the
/hdi_check endpoint enough alias coverage to resolve user-natural inputs
("Warfarin", "St. John's Wort") to the canonical Aura entity_ids
(``Drug:Warfarin``, ``Hypericum perforatum``).

Idempotent: re-running with the same source data is a SET-only no-op.
Reads aliases directly from research-journal/shared/hdi_safe_50.json — no
NCBI calls, no extra dependencies.

Run:
    python3 scripts/enrich_hdi_aliases.py
    python3 scripts/enrich_hdi_aliases.py --dry-run    # preview only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HDI_JSON = (
    PROJECT_ROOT.parent / "research-journal" / "shared" / "hdi_safe_50.json"
)


def _safe_label(s: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s)


def collect_aliases(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Read hdi_safe_50.json → {herb_id: {common_name, aliases}}, {drug_id: {aliases}}.

    Mirrors the entity_id convention from ingest_hdi.py:
      - Herb entity_id = entry["herb"]["latin"]
      - Drug entity_id = "Drug:" + entry["drug"]["name"]
    """
    raw = json.loads(path.read_text())
    herbs: dict[str, dict] = {}
    drugs: dict[str, dict] = {}
    for entry in raw:
        latin = entry["herb"]["latin"]
        common = entry["herb"]["name"]
        herbs[latin] = {
            "common_name": common,
            "aliases": sorted({common, latin}),
        }
        drug_name = entry["drug"]["name"]
        drug_id = f"Drug:{drug_name}"
        drugs.setdefault(drug_id, {"common_name": drug_name, "aliases": set()})
        drugs[drug_id]["aliases"].update({drug_name, drug_id})
    # Materialize drug aliases as sorted lists.
    return herbs, {k: {"common_name": v["common_name"], "aliases": sorted(v["aliases"])}
                   for k, v in drugs.items()}


def stamp(driver, workspace_label: str, table: dict[str, dict], label: str) -> int:
    """SET common_name + aliases on every node matched by entity_id.

    Returns the number of nodes actually touched (Aura's count(n) of matched
    nodes — useful for verifying the JSON entries align with the graph).
    """
    cypher = (
        f"UNWIND $rows AS row "
        f"MATCH (n:`{workspace_label}`:`{label}` {{entity_id: row.entity_id}}) "
        f"SET n.common_name = row.common_name, "
        f"    n.aliases = row.aliases "
        f"RETURN count(n) AS c"
    )
    rows = [
        {"entity_id": eid, "common_name": v["common_name"], "aliases": v["aliases"]}
        for eid, v in table.items()
    ]
    if not rows:
        return 0
    with driver.session() as s:
        rec = s.run(cypher, rows=rows).single()
        return int(rec["c"]) if rec else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the alias plan without writing")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    workspace = _safe_label(os.environ.get("WORKSPACE", "unified_diet_kg"))

    if not HDI_JSON.exists():
        print(f"ERROR: {HDI_JSON} not found", file=sys.stderr)
        return 1
    herbs, drugs = collect_aliases(HDI_JSON)
    print(f"HDI-Safe-50 source: {len(herbs)} herbs, {len(drugs)} drugs", file=sys.stderr)

    if args.dry_run:
        print("\n=== Herbs (Latin → common_name + aliases) ===", file=sys.stderr)
        for k, v in list(herbs.items())[:5]:
            print(f"  {k} → common={v['common_name']!r} aliases={v['aliases']}", file=sys.stderr)
        print(f"  ... ({len(herbs)} total)\n", file=sys.stderr)
        print("=== Drugs (Drug:Name → common_name + aliases) ===", file=sys.stderr)
        for k, v in list(drugs.items())[:5]:
            print(f"  {k} → common={v['common_name']!r} aliases={v['aliases']}", file=sys.stderr)
        print(f"  ... ({len(drugs)} total)", file=sys.stderr)
        return 0

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    print(f"Aura: {uri.split('//')[1].split('.')[0]} workspace={workspace}", file=sys.stderr)

    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        herb_n = stamp(driver, workspace, herbs, "Herb")
        drug_n = stamp(driver, workspace, drugs, "Drug")

    print(f"Stamped {herb_n}/{len(herbs)} Herb nodes", file=sys.stderr)
    print(f"Stamped {drug_n}/{len(drugs)} Drug nodes", file=sys.stderr)
    if herb_n < len(herbs):
        miss = len(herbs) - herb_n
        print(
            f"WARN: {miss} herb(s) in JSON did not match a Herb node in Aura — "
            "check entity_id alignment via ingest_hdi.py",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
