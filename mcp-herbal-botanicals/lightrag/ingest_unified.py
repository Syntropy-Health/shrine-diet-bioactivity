"""
Unified Diet Knowledge Graph — LightRAG Ingestion Script.

Extracts entities and relationships from the unified herbal_botanicals.db
SQLite database and loads them into LightRAG via ainsert_custom_kg(),
bypassing LLM extraction entirely (zero API cost for structured data).

Entity types: Herb, Compound, Food, Target, Disease, Symptom
Relationship types: CONTAINS_COMPOUND, FOUND_IN_FOOD, TARGETS_PROTEIN,
                     ASSOCIATED_WITH_DISEASE, TREATS_SYMPTOM

Usage:
    python ingest_unified.py --config local --dry-run
    python ingest_unified.py --config local --batch-size 500
    python ingest_unified.py --config production --batch-size 200
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

from entity_schema import (
    DESCRIPTION_GENERATORS,
    ENTITY_TYPES,
    QUERY_BUILDERS,
    RELATIONSHIP_TYPES,
    describe_relationship,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / ".." / "data_local" / "herbal_botanicals.db"


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists in the SQLite database."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def fetch_all(conn: sqlite3.Connection, query: str, limit: int | None = None) -> list[dict]:
    """Fetch all rows as dicts, with optional limit."""
    if limit is not None:
        query = f"{query} LIMIT {limit}"
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(query)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.row_factory = None
    return rows


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------


def extract_entities(
    conn: sqlite3.Connection,
    entity_type: str,
    max_count: int | None = None,
) -> list[dict]:
    """Extract entities of a given type from SQLite as LightRAG entity dicts."""
    spec = ENTITY_TYPES[entity_type]
    describe = DESCRIPTION_GENERATORS[entity_type]

    # Check source table exists (Disease is aggregated, has no single table)
    if spec["source_table"] and not table_exists(conn, spec["source_table"]):
        print(f"  ⚠ Table '{spec['source_table']}' not found, skipping {entity_type}")
        return []

    # Resolve query — may be static string or dynamic builder
    query = spec.get("query")
    if query is None and "query_builder" in spec:
        builder_name = spec["query_builder"]
        query = QUERY_BUILDERS[builder_name](conn)
    if query is None:
        print(f"  ⚠ No query for {entity_type}, skipping")
        return []

    rows = fetch_all(conn, query, limit=max_count)
    entities = []
    seen_names: set[str] = set()

    for row in rows:
        name_field = spec["name_field"]
        entity_name = str(row.get(name_field, "")).strip()
        if not entity_name or entity_name in seen_names:
            continue
        seen_names.add(entity_name)

        description = describe(row)
        entities.append({
            "entity_name": entity_name,
            "entity_type": entity_type,
            "description": description,
            "source_id": f"sqlite-{entity_type.lower()}",
        })

    return entities


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------


def extract_relationships(
    conn: sqlite3.Connection,
    rel_type: str,
    max_count: int | None = None,
) -> list[dict]:
    """Extract relationships of a given type from SQLite as LightRAG edge dicts."""
    spec = RELATIONSHIP_TYPES[rel_type]

    if not table_exists(conn, spec["source_table"]):
        print(f"  ⚠ Table '{spec['source_table']}' not found, skipping {rel_type}")
        return []

    rows = fetch_all(conn, spec["query"], limit=max_count)
    relationships = []

    for row in rows:
        src = str(row.get("src_name", "")).strip()
        tgt = str(row.get("tgt_name", "")).strip()
        if not src or not tgt:
            continue

        description, keywords = describe_relationship(rel_type, row)
        relationships.append({
            "src_id": src,
            "tgt_id": tgt,
            "description": description,
            "keywords": keywords,
            "weight": 1.0,
            "source_id": f"sqlite-{rel_type.lower()}",
        })

    return relationships


# ---------------------------------------------------------------------------
# Batch ingestion
# ---------------------------------------------------------------------------


async def ingest_batch(
    rag,
    entities: list[dict],
    relationships: list[dict],
    batch_label: str,
) -> None:
    """Insert a batch of entities and relationships into LightRAG."""
    # Build a synthetic chunk as the source document
    source_id = f"batch-{batch_label}"
    entity_names = [e["entity_name"] for e in entities[:20]]
    chunk_content = (
        f"Batch '{batch_label}' containing {len(entities)} entities "
        f"and {len(relationships)} relationships. "
        f"Sample entities: {', '.join(entity_names)}"
    )

    custom_kg = {
        "chunks": [
            {
                "content": chunk_content,
                "source_id": source_id,
                "file_path": str(DB_PATH),
            }
        ],
        "entities": [
            {**e, "source_id": source_id} for e in entities
        ],
        "relationships": [
            {**r, "source_id": source_id} for r in relationships
        ],
    }

    await rag.ainsert_custom_kg(custom_kg)


def batch_items(items: list, batch_size: int) -> list[list]:
    """Split a list into batches."""
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest unified diet KG into LightRAG")
    parser.add_argument(
        "--config",
        choices=["local", "production"],
        default="local",
        help="Config profile (default: local)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing")
    parser.add_argument("--max-herbs", type=int, default=None, help="Max herbs to ingest")
    parser.add_argument("--max-compounds", type=int, default=None, help="Max compounds to ingest")
    parser.add_argument("--max-foods", type=int, default=None, help="Max foods to ingest")
    parser.add_argument("--max-relationships", type=int, default=None, help="Max relationships per type")
    parser.add_argument("--batch-size", type=int, default=500, help="Entities per batch (default: 500)")
    args = parser.parse_args()

    # Load config
    config_path = SCRIPT_DIR / f"config_{args.config}.env"
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return
    load_dotenv(config_path, override=True)

    # Check DB
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run: cd mcp-herbal-botanicals && make setup")
        return

    conn = sqlite3.connect(str(DB_PATH))
    print(f"Connected to {DB_PATH}")
    print(f"Config: {args.config}")
    print(f"Dry run: {args.dry_run}")
    print()

    # --- Extract entities ---
    limits = {
        "Herb": args.max_herbs,
        "Compound": args.max_compounds,
        "Food": args.max_foods,
        "Target": None,
        "Disease": None,
        "Symptom": None,
    }

    all_entities: dict[str, list[dict]] = {}
    total_entities = 0
    for entity_type in ENTITY_TYPES:
        print(f"Extracting {entity_type} entities...")
        entities = extract_entities(conn, entity_type, max_count=limits.get(entity_type))
        all_entities[entity_type] = entities
        total_entities += len(entities)
        print(f"  → {len(entities)} {entity_type} entities")

    # --- Extract relationships ---
    all_relationships: dict[str, list[dict]] = {}
    total_relationships = 0
    for rel_type in RELATIONSHIP_TYPES:
        print(f"Extracting {rel_type} relationships...")
        rels = extract_relationships(conn, rel_type, max_count=args.max_relationships)
        all_relationships[rel_type] = rels
        total_relationships += len(rels)
        print(f"  → {len(rels)} {rel_type} edges")

    conn.close()

    # --- Summary ---
    print(f"\n{'=' * 50}")
    print(f"Total entities:       {total_entities}")
    print(f"Total relationships:  {total_relationships}")
    print(f"Batch size:           {args.batch_size}")
    print(f"{'=' * 50}\n")

    if args.dry_run:
        print("DRY RUN — no data written to LightRAG/Neo4j")
        print("\nEntity breakdown:")
        for et, entities in all_entities.items():
            print(f"  {et:15s}: {len(entities):>8,}")
        print("\nRelationship breakdown:")
        for rt, rels in all_relationships.items():
            print(f"  {rt:30s}: {len(rels):>8,}")
        return

    # --- Initialize LightRAG ---
    print("Initializing LightRAG...")
    from functools import partial
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    embedding_binding = os.getenv("EMBEDDING_BINDING", "ollama")
    embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:latest")
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "768"))
    embedding_host = os.getenv("EMBEDDING_BINDING_HOST", "http://localhost:11434")

    if embedding_binding == "ollama":
        from lightrag.llm.ollama import ollama_embed, ollama_model_complete
        llm_func = ollama_model_complete
        embed_func = EmbeddingFunc(
            embedding_dim=embedding_dim,
            max_token_size=8192,
            func=partial(
                ollama_embed.func,
                embed_model=embedding_model,
                host=embedding_host,
            ),
        )
    else:
        from lightrag.llm.openai import gpt_4o_mini_complete, openai_embed
        llm_func = gpt_4o_mini_complete
        embed_func = EmbeddingFunc(
            embedding_dim=embedding_dim,
            max_token_size=8192,
            func=partial(
                openai_embed.func,
                model=embedding_model,
            ),
        )

    working_dir = os.getenv("WORKING_DIR", "./rag_storage_local")
    os.makedirs(working_dir, exist_ok=True)

    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_func,
        embedding_func=embed_func,
    )
    await rag.initialize_storages()
    print("LightRAG initialized\n")

    # --- Ingest entities in batches ---
    start_time = time.time()

    # Flatten all entities and ingest
    flat_entities = []
    for entities in all_entities.values():
        flat_entities.extend(entities)

    flat_relationships = []
    for rels in all_relationships.values():
        flat_relationships.extend(rels)

    entity_batches = batch_items(flat_entities, args.batch_size)
    rel_batches = batch_items(flat_relationships, args.batch_size)

    # Ingest entities first (nodes must exist before edges)
    for i, batch in enumerate(entity_batches):
        label = f"entities-{i + 1:03d}"
        print(f"  Ingesting {label} ({len(batch)} entities)...")
        await ingest_batch(rag, batch, [], label)

    # Then ingest relationships
    for i, batch in enumerate(rel_batches):
        label = f"relationships-{i + 1:03d}"
        print(f"  Ingesting {label} ({len(batch)} edges)...")
        await ingest_batch(rag, [], batch, label)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 50}")
    print(f"Ingestion complete in {elapsed:.1f}s")
    print(f"  Entities:       {total_entities:,}")
    print(f"  Relationships:  {total_relationships:,}")
    print(f"  Entity batches: {len(entity_batches)}")
    print(f"  Rel batches:    {len(rel_batches)}")
    print(f"{'=' * 50}")

    await rag.finalize_storages()


if __name__ == "__main__":
    asyncio.run(main())
