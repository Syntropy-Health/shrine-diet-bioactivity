"""Ingest CMAUP plant→disease associations as Herb→Disease edges in Aura.

Why this exists (Task #10): the SQLite `target_diseases` table holds 765,266
CMAUP rows where `target_id` is `plant:<Plant_ID>` (NPO*) — *not* a target ID
despite the column name. The existing `extract_duke_relationships()` query
joins on `targets.id` (NPT* CMAUP target IDs) which has zero overlap, so
zero edges land.

This script does the proper ingestion:

1. Reads `data/cmaup-plants.txt` → builds Plant_ID → name lookup (7,865 plants)
2. MERGEs every CMAUP plant as a Herb node in Aura, keyed on scientific_name
   (or Plant_Name when Species_Name is "NA"). New Herb nodes get
   `source_id='cmaup:plant'`, existing herbs (Duke or SymMap) keep their
   identity — MERGE is idempotent.
3. For each `target_diseases` row WHERE source='cmaup': resolves Plant_ID →
   herb entity_id and MERGEs ASSOCIATED_WITH_DISEASE edge.

Coverage estimate (computed at run time):
- ~987 CMAUP plants overlap by name with existing 2,376 Duke herbs → upserts
- ~6,878 CMAUP plants are new → new Herb nodes
- ~765K Herb→Disease edges land

Skips drug:PMID* rows (TTD literature refs) — they need a separate ingestion
path (drug entity catalogue) and are out of scope here.

Run:
    python3 scripts/ingest_cmaup_plant_diseases.py
"""
from __future__ import annotations

import csv
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = PROJECT_ROOT / "data_local" / "herbal_botanicals.db"
CMAUP_PLANTS_TSV = PROJECT_ROOT / "data" / "cmaup-plants.txt"
SCOPE = "shared"
WORKSPACE = os.environ.get("WORKSPACE", "unified_diet_kg")
BATCH = 500


def safe_label(label: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in label)


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def load_cmaup_plants() -> dict[str, dict]:
    """Plant_ID → {scientific_name, plant_name, family, genus, species}."""
    plants: dict[str, dict] = {}
    with open(CMAUP_PLANTS_TSV) as f:
        rdr = csv.DictReader(f, delimiter="\t")
        for row in rdr:
            pid = row["Plant_ID"].strip()
            if not pid:
                continue
            species = row.get("Species_Name", "").strip()
            plant_name = row.get("Plant_Name", "").strip()
            # Choose the best canonical name:
            #   - Species_Name when present and not "NA"
            #   - Plant_Name otherwise (it's typically a more verbose form)
            scientific = species if species and species.upper() != "NA" else plant_name
            plants[pid] = {
                "scientific_name": scientific,
                "plant_name": plant_name,
                "family": row.get("Family_Name", "").strip(),
                "genus": row.get("Genus_Name", "").strip(),
                "species": species if species.upper() != "NA" else "",
            }
    return plants


def read_plant_diseases(conn: sqlite3.Connection) -> list[dict]:
    """Pull rows from target_diseases where target_id is plant: prefixed."""
    rows = []
    cur = conn.execute(
        "SELECT target_id, disease_name, evidence_layer "
        "FROM target_diseases "
        "WHERE source = 'cmaup' AND substr(target_id, 1, 6) = 'plant:'"
    )
    for tid, disease, evidence in cur:
        plant_id = tid[len("plant:") :]
        if not plant_id or not disease:
            continue
        rows.append({
            "plant_id": plant_id,
            "disease": disease.strip(),
            "evidence_layer": evidence or "",
        })
    return rows


def upsert_herbs(driver, plants: dict[str, dict]) -> dict[str, str]:
    """MERGE Herb nodes for every CMAUP plant; return {Plant_ID: entity_id}."""
    ws = safe_label(WORKSPACE)
    plant_to_entity: dict[str, str] = {}

    rows = []
    for pid, info in plants.items():
        entity_id = info["scientific_name"]
        if not entity_id:
            continue
        plant_to_entity[pid] = entity_id
        rows.append({
            "entity_id": entity_id,
            "entity_type": "Herb",
            "description": (
                f"{info['scientific_name']}"
                + (f" — {info['plant_name']}" if info['plant_name'] and info['plant_name'] != info['scientific_name'] else "")
                + (f". Family: {info['family']}" if info['family'] else "")
                + (f". Genus: {info['genus']}" if info['genus'] else "")
            ),
            "scope": SCOPE,
            "file_path": "cmaup-plants",
            "source_id": "cmaup:plant",
            "cmaup_plant_id": pid,
            "family": info["family"],
            "genus": info["genus"],
            "species": info["species"],
        })

    print(f"Upserting {len(rows)} CMAUP plant Herb nodes...", file=sys.stderr)
    with driver.session() as s:
        for batch in chunked(rows, BATCH):
            s.run(
                f"UNWIND $rows AS row "
                f"MERGE (n:`{ws}` {{entity_id: row.entity_id}}) "
                f"SET n += row, n:Herb",
                rows=batch,
            ).consume()
    return plant_to_entity


def upsert_plant_diseases(
    driver,
    plant_disease_rows: list[dict],
    plant_to_entity: dict[str, str],
) -> tuple[int, int]:
    """MERGE ASSOCIATED_WITH_DISEASE edges; return (written, skipped_orphan)."""
    ws = safe_label(WORKSPACE)
    rows = []
    skipped = 0
    for r in plant_disease_rows:
        herb_eid = plant_to_entity.get(r["plant_id"])
        if not herb_eid:
            skipped += 1
            continue
        rows.append({
            "src_id": herb_eid,
            "tgt_id": r["disease"],
            "description": (
                f"CMAUP plant-disease association"
                + (f" (evidence: {r['evidence_layer']})" if r['evidence_layer'] else "")
            ),
            "keywords": "cmaup,plant_disease",
            "weight": 1.0,
            "file_path": "cmaup-plants",
            "source_id": "cmaup:plant_disease",
            "evidence_tier": r["evidence_layer"] or "",
            "scope": SCOPE,
        })

    # Diseases referenced may not exist as nodes yet — MERGE them first as Disease.
    distinct_diseases = list({r["tgt_id"] for r in rows})
    print(f"Upserting {len(distinct_diseases)} Disease nodes (idempotent)...", file=sys.stderr)
    with driver.session() as s:
        for batch in chunked(distinct_diseases, BATCH):
            s.run(
                f"UNWIND $names AS n "
                f"MERGE (d:`{ws}` {{entity_id: n}}) "
                f"ON CREATE SET d.entity_type = 'Disease', d.scope = '{SCOPE}', "
                f"              d.source_id = 'cmaup:plant_disease', "
                f"              d.description = 'Disease: ' + n, "
                f"              d.file_path = 'cmaup-plants', d:Disease "
                f"ON MATCH SET d:Disease, d.scope = coalesce(d.scope, '{SCOPE}')",
                names=batch,
            ).consume()

    print(f"Upserting {len(rows)} ASSOCIATED_WITH_DISEASE edges...", file=sys.stderr)
    written = 0
    with driver.session() as s:
        for batch in chunked(rows, BATCH):
            result = s.run(
                f"UNWIND $rows AS row "
                f"MATCH (h:`{ws}` {{entity_id: row.src_id}}) "
                f"MATCH (d:`{ws}` {{entity_id: row.tgt_id}}) "
                f"MERGE (h)-[r:ASSOCIATED_WITH_DISEASE]->(d) "
                f"SET r.description = row.description, "
                f"    r.keywords = row.keywords, "
                f"    r.weight = row.weight, "
                f"    r.file_path = row.file_path, "
                f"    r.source_id = row.source_id, "
                f"    r.evidence_tier = row.evidence_tier, "
                f"    r.scope = row.scope "
                f"RETURN count(r) AS c",
                rows=batch,
            ).single()
            if result is not None:
                written += int(result["c"])
    return written, skipped


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]

    print(f"Loading CMAUP plants from {CMAUP_PLANTS_TSV}", file=sys.stderr)
    plants = load_cmaup_plants()
    print(f"  {len(plants)} plants", file=sys.stderr)

    print(f"Reading plant-disease rows from {SQLITE_DB}", file=sys.stderr)
    conn = sqlite3.connect(str(SQLITE_DB))
    pd_rows = read_plant_diseases(conn)
    conn.close()
    print(f"  {len(pd_rows)} plant-disease rows", file=sys.stderr)

    if not plants or not pd_rows:
        print("Nothing to ingest.", file=sys.stderr)
        return 0

    print(f"Aura: {uri.split('//')[1].split('.')[0]} workspace={WORKSPACE} scope={SCOPE}", file=sys.stderr)
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        plant_to_entity = upsert_herbs(driver, plants)
        print(f"  resolved {len(plant_to_entity)} plant_id → entity_id mappings", file=sys.stderr)
        written, skipped = upsert_plant_diseases(driver, pd_rows, plant_to_entity)

    print(f"\nResult: {written:,} ASSOCIATED_WITH_DISEASE edges written, "
          f"{skipped:,} orphan rows skipped (plant_id missing scientific_name)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
