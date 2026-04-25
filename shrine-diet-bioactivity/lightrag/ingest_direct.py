"""Direct-Cypher ingest fallback — bypasses LightRAG embeddings.

Use this when Ollama embedding throughput would otherwise blow the
session window. Writes the same entity / relationship payload to
Aura as ``ingest_unified.py`` would, but skips the embedding step
entirely and uses parametrized batched MERGE Cypher for ~50x speedup.

Trade-off: vector retrieval (semantic-search MCP tool) won't surface
the directly-ingested entities until a later embedding pass runs.
Graph queries (the Safety Reviewer path) work immediately.

Run:
    python ingest_direct.py --max-extra-per-table 1000 --herb2-cap 500 \\
        --duke-rel-cap 5000
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

from entity_schema import (
    DESCRIPTION_GENERATORS,
    ENTITY_TYPES,
    QUERY_BUILDERS,
    RELATIONSHIP_TYPES,
    describe_relationship,
    safe_label,
)
from extra_sources import (
    EXTRA_ENTITY_ADAPTERS,
    extract_extra_entities,
    extract_herb2_relationships,
)

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / ".." / "data_local" / "herbal_botanicals.db"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def extract_duke_entities(
    conn: sqlite3.Connection,
    entity_type: str,
    max_count: int | None,
    file_path_label: str = "duke",
) -> list[dict]:
    """Mirror of ingest_unified.extract_entities, simpler."""
    spec = ENTITY_TYPES[entity_type]
    if spec.get("source_table") is None and "query_builder" not in spec:
        return []
    if spec["source_table"] and not _table_exists(conn, spec["source_table"]):
        return []
    query = spec.get("query")
    if query is None and "query_builder" in spec:
        query = QUERY_BUILDERS[spec["query_builder"]](conn)
    if query is None:
        return []
    if max_count and max_count > 0:
        query = f"{query} LIMIT {max_count}"

    cur = conn.execute(query)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    describe = DESCRIPTION_GENERATORS[entity_type]
    entities: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        name = str(row.get(spec["name_field"], "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entities.append(
            {
                "entity_id": name,
                "entity_type": entity_type,
                "description": describe(row),
                "file_path": file_path_label,
                "source_id": f"duke:{entity_type.lower()}",
            }
        )
    return entities


def extract_duke_relationships(
    conn: sqlite3.Connection,
    rel_type: str,
    max_count: int | None,
    file_path_label: str = "duke",
) -> list[dict]:
    spec = RELATIONSHIP_TYPES[rel_type]
    if spec.get("source_table") is None:
        return []
    if not _table_exists(conn, spec["source_table"]):
        return []
    q = spec["query"]
    if max_count and max_count > 0:
        q = f"{q} LIMIT {max_count}"
    cur = conn.execute(q)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    rels: list[dict] = []
    for row in rows:
        src = str(row.get("src_name", "")).strip()
        tgt = str(row.get("tgt_name", "")).strip()
        if not src or not tgt:
            continue
        desc, keywords = describe_relationship(rel_type, row)
        rels.append(
            {
                "src_id": src,
                "tgt_id": tgt,
                "rel_type": rel_type,
                "description": desc,
                "keywords": keywords,
                "weight": 1.0,
                "file_path": file_path_label,
                "source_id": f"duke:{rel_type.lower()}",
            }
        )
    return rels


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def upsert_entities(session, entities: list[dict], workspace: str) -> int:
    """Batch MERGE entities with workspace + entity_type labels."""
    ws = safe_label(workspace)
    total = 0
    for batch in chunked(entities, 500):
        # Group by entity_type so we can SET the right label per batch.
        by_type: dict[str, list[dict]] = {}
        for e in batch:
            by_type.setdefault(e["entity_type"], []).append(e)
        for etype, group in by_type.items():
            et = safe_label(etype)
            cypher = (
                f"UNWIND $rows AS row "
                f"MERGE (n:`{ws}` {{entity_id: row.entity_id}}) "
                f"SET n += row, n:`{et}`"
            )
            result = session.run(cypher, rows=group)
            result.consume()
            total += len(group)
    return total


def upsert_relationships(session, rels: list[dict], workspace: str) -> int:
    """Batch MERGE relationships keyed by (src, tgt, rel_type).

    Uses APOC apoc.merge.relationship for dynamic edge type. Falls back
    to a plain :RELATES if APOC isn't available (Aura includes APOC).
    """
    ws = safe_label(workspace)
    total = 0
    for batch in chunked(rels, 500):
        # Group by rel_type so we get typed edges (INTERACTS_WITH,
        # ASSOCIATED_WITH_DISEASE, etc.) without needing APOC.
        by_type: dict[str, list[dict]] = {}
        for r in batch:
            by_type.setdefault(r["rel_type"], []).append(r)
        for rel_type, group in by_type.items():
            rt = safe_label(rel_type)
            cypher = (
                f"UNWIND $rows AS row "
                f"MATCH (s:`{ws}` {{entity_id: row.src_id}}) "
                f"MATCH (t:`{ws}` {{entity_id: row.tgt_id}}) "
                f"MERGE (s)-[r:`{rt}`]->(t) "
                f"SET r.description = row.description, "
                f"    r.keywords = row.keywords, "
                f"    r.weight = row.weight, "
                f"    r.file_path = row.file_path, "
                f"    r.source_id = row.source_id, "
                f"    r.evidence_tier = row.evidence_tier"
            )
            result = session.run(cypher, rows=group)
            result.consume()
            total += len(group)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-duke-herbs", type=int, default=2000)
    parser.add_argument("--max-duke-compounds", type=int, default=3000)
    parser.add_argument("--max-duke-foods", type=int, default=500)
    parser.add_argument("--max-extra-per-table", type=int, default=1000)
    parser.add_argument("--duke-rel-cap", type=int, default=10000)
    parser.add_argument("--herb2-cap", type=int, default=2000)
    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR.parent / ".env")
    load_dotenv(SCRIPT_DIR / "config_local.env", override=False)

    workspace = os.getenv("WORKSPACE", "unified_diet_kg")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]

    conn = sqlite3.connect(str(DB_PATH))
    print(f"Connected to {DB_PATH}")
    print(f"Workspace: {workspace}, Aura: {uri.split('//')[1].split('.')[0]}")

    # --- Extract ---
    print("\nExtracting Duke entities...")
    duke_entities: list[dict] = []
    duke_limits = {
        "Herb": args.max_duke_herbs,
        "Compound": args.max_duke_compounds,
        "Food": args.max_duke_foods,
        "Target": None,
        "Disease": None,
        "Symptom": None,
    }
    for et in ("Herb", "Compound", "Food", "Target", "Disease", "Symptom"):
        ents = extract_duke_entities(conn, et, duke_limits.get(et))
        duke_entities.extend(ents)
        print(f"  {et}: {len(ents)}")

    print("\nExtracting Duke relationships...")
    duke_rels: list[dict] = []
    for rt in (
        "CONTAINS_COMPOUND",
        "FOUND_IN_FOOD",
        "TARGETS_PROTEIN",
        "ASSOCIATED_WITH_DISEASE",
        "TREATS_SYMPTOM",
    ):
        rels = extract_duke_relationships(conn, rt, args.duke_rel_cap)
        duke_rels.extend(rels)
        print(f"  {rt}: {len(rels)}")

    print("\nExtracting SymMap + HERB 2.0 entities...")
    extra_entities: list[dict] = []
    seen_names = {e["entity_id"] for e in duke_entities}
    for adapter in EXTRA_ENTITY_ADAPTERS:
        rows = extract_extra_entities(
            conn, adapter, max_count=args.max_extra_per_table
        )
        # extract_extra_entities returns entity_name + extra_props (e.g.
        # chinese_name, pinyin_name, name_cn, etc). Carry them through
        # so bilingual coverage on Herb nodes is queryable.
        adapted = []
        for r in rows:
            if r["entity_name"] in seen_names:
                continue
            seen_names.add(r["entity_name"])
            ent = {
                "entity_id": r["entity_name"],
                "entity_type": r["entity_type"],
                "description": r["description"],
                "file_path": adapter["source"],
                "source_id": r["source_id"],
            }
            # Pull through extra_props (chinese_name, pinyin_name, ...).
            for prop in adapter.get("extra_props", ()):
                if r.get(prop) is not None:
                    ent[prop] = r[prop]
            adapted.append(ent)
        extra_entities.extend(adapted)
        print(f"  {adapter['source']}/{adapter['table']}: {len(adapted)} new (after dedupe)")

    print("\nExtracting HERB 2.0 herb→disease edges...")
    herb2_raw = extract_herb2_relationships(conn, experimental_cap=args.herb2_cap)
    herb2_rels = [
        {
            "src_id": r["src_id"],
            "tgt_id": r["tgt_id"],
            "rel_type": "ASSOCIATED_WITH_DISEASE",
            "description": r["description"],
            "keywords": r["keywords"],
            "weight": r["weight"],
            "file_path": "herb2",
            "source_id": "herb2:herb_disease",
            "evidence_tier": r.get("evidence_tier", ""),
        }
        for r in herb2_raw
    ]
    print(f"  ASSOCIATED_WITH_DISEASE (herb2): {len(herb2_rels)}")

    # Add evidence_tier='' to all duke_rels for cypher uniformity.
    for r in duke_rels:
        r.setdefault("evidence_tier", "")

    conn.close()

    all_entities = duke_entities + extra_entities
    all_rels = duke_rels + herb2_rels

    # Edges referring to entities not in our extracted set will be
    # created with empty UNKNOWN nodes — filter them out instead.
    entity_ids = {e["entity_id"] for e in all_entities}
    valid_rels = [r for r in all_rels if r["src_id"] in entity_ids and r["tgt_id"] in entity_ids]
    dropped = len(all_rels) - len(valid_rels)
    print(f"\nTotal: {len(all_entities):,} entities, {len(valid_rels):,} edges (dropped {dropped:,} orphans)")

    # --- Upsert ---
    print("\nWriting to Aura...")
    start = time.time()
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as session:
            n_ent = upsert_entities(session, all_entities, workspace)
            print(f"  ✅ {n_ent:,} entities upserted in {time.time() - start:.1f}s")
            t1 = time.time()
            n_rel = upsert_relationships(session, valid_rels, workspace)
            print(f"  ✅ {n_rel:,} relationships upserted in {time.time() - t1:.1f}s")

    print(f"\nTotal time: {time.time() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
