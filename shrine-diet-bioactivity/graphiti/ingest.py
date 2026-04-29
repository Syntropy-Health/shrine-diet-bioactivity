"""
Ingest herbal_botanicals.db entities into Graphiti KG via Neo4j.

Reads herbs, compounds, targets, and their relationships from SQLite,
then creates Graphiti episodes for each entity batch. Graphiti handles
entity extraction, deduplication, and vector indexing automatically.

Usage:
    python ingest.py                    # Ingest with default limits
    MAX_HERBS=2376 python ingest.py     # Ingest all herbs
    python ingest.py --dry-run          # Show what would be ingested

Prerequisites:
    1. LM Studio running with embedding + chat models loaded
    2. Neo4j accessible (Railway or local Docker)
    3. pip install -r requirements.txt
    4. cp .env.example .env && edit .env with Neo4j password
"""

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

from config import (
    BATCH_SIZE,
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MAX_COMPOUNDS,
    MAX_HERBS,
    MAX_LINKS,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    SQLITE_DB_PATH,
    validate_config,
)


def get_sqlite_connection() -> sqlite3.Connection:
    """Connect to the herbal_botanicals SQLite database."""
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"ERROR: SQLite database not found at {SQLITE_DB_PATH}")
        print("Run: cd .. && npm run convert-data && npm run migrate-kg")
        sys.exit(1)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_herbs(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """Fetch herbs with compound counts."""
    cursor = conn.execute(
        """
        SELECT h.id, h.scientific_name, h.common_name, h.family, h.genus,
               h.species, h.usage_type, h.is_food_plant, h.is_edible,
               (SELECT COUNT(DISTINCT compound_id) FROM herb_compounds WHERE herb_id = h.id) as compound_count
        FROM herbs h
        ORDER BY compound_count DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def fetch_compounds(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """Fetch top compounds by herb association count."""
    cursor = conn.execute(
        """
        SELECT c.id, c.name, c.name_normalized, c.cas_number, c.compound_class,
               c.bioactivities,
               (SELECT COUNT(DISTINCT herb_id) FROM herb_compounds WHERE compound_id = c.id) as herb_count,
               (SELECT COUNT(DISTINCT food_name) FROM compound_foods WHERE compound_id = c.id) as food_count
        FROM compounds c
        ORDER BY herb_count DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = []
    for row in cursor.fetchall():
        d = dict(row)
        try:
            d["bioactivities"] = json.loads(d.get("bioactivities", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["bioactivities"] = []
        rows.append(d)
    return rows


def fetch_herb_compound_links(conn: sqlite3.Connection, herb_ids: list[str]) -> list[dict]:
    """Fetch herb-compound relationships for given herbs."""
    if not herb_ids:
        return []
    placeholders = ",".join("?" for _ in herb_ids)
    cursor = conn.execute(
        f"""
        SELECT hc.herb_id, h.common_name as herb_name, h.scientific_name,
               hc.compound_id, c.name as compound_name, hc.plant_part,
               hc.concentration_low_ppm, hc.concentration_high_ppm
        FROM herb_compounds hc
        JOIN herbs h ON hc.herb_id = h.id
        JOIN compounds c ON hc.compound_id = c.id
        WHERE hc.herb_id IN ({placeholders})
        ORDER BY hc.herb_id, hc.concentration_high_ppm DESC NULLS LAST
        """,
        herb_ids,
    )
    return [dict(row) for row in cursor.fetchall()]


def fetch_compound_targets(conn: sqlite3.Connection, compound_ids: list[str]) -> list[dict]:
    """Fetch compound-target relationships."""
    if not compound_ids:
        return []
    placeholders = ",".join("?" for _ in compound_ids)
    cursor = conn.execute(
        f"""
        SELECT ct.compound_id, c.name as compound_name,
               ct.target_id, t.name as target_name,
               ct.activity_value, ct.activity_type
        FROM compound_targets ct
        JOIN compounds c ON ct.compound_id = c.id
        JOIN targets t ON ct.target_id = t.id
        WHERE ct.compound_id IN ({placeholders})
        """,
        compound_ids,
    )
    return [dict(row) for row in cursor.fetchall()]


async def ingest_to_graphiti(dry_run: bool = False) -> None:
    """Main ingestion pipeline."""
    # Validate config
    warnings = validate_config()
    for w in warnings:
        print(f"WARNING: {w}")
    if not NEO4J_PASSWORD and not dry_run:
        print("ERROR: NEO4J_PASSWORD not set. Copy .env.example to .env and set it.")
        sys.exit(1)

    conn = get_sqlite_connection()

    # Fetch data
    print(f"\n=== Fetching data from SQLite ===")
    herbs = fetch_herbs(conn, MAX_HERBS)
    print(f"  Herbs: {len(herbs)}")

    compounds = fetch_compounds(conn, MAX_COMPOUNDS)
    print(f"  Compounds: {len(compounds)}")

    herb_ids = [h["id"] for h in herbs]
    herb_compound_links = fetch_herb_compound_links(conn, herb_ids)[:MAX_LINKS]
    print(f"  Herb-compound links: {len(herb_compound_links)} (capped at {MAX_LINKS})")

    compound_ids = [c["id"] for c in compounds]
    compound_target_links = fetch_compound_targets(conn, compound_ids)[:MAX_LINKS]
    print(f"  Compound-target links: {len(compound_target_links)} (capped at {MAX_LINKS})")

    conn.close()

    if dry_run:
        print("\n=== DRY RUN — would ingest: ===")
        print(f"  {len(herbs)} herb episodes")
        print(f"  {len(compounds)} compound episodes")
        print(f"  {len(herb_compound_links)} herb-compound link episodes")
        print(f"  {len(compound_target_links)} compound-target link episodes")
        print(f"  Total episodes: {len(herbs) + len(compounds) + len(herb_compound_links) + len(compound_target_links)}")
        return

    # Import Graphiti (deferred to avoid import errors during dry run)
    from graphiti_core import Graphiti
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.nodes import EpisodeType

    from local_llm_client import LocalLLMClient

    # Configure embedder (local LM Studio)
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            base_url=EMBEDDING_BASE_URL,
            api_key=EMBEDDING_API_KEY,
            embedding_model=EMBEDDING_MODEL,
            embedding_dim=EMBEDDING_DIM,
        )
    )

    # Configure LLM client (local — uses chat.completions, not responses.parse)
    llm_client = LocalLLMClient(
        config=LLMConfig(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL or None,
        )
    )

    # Connect to Graphiti
    print(f"\n=== Connecting to Graphiti ===")
    print(f"  Neo4j: {NEO4J_URI}")
    print(f"  LLM: {LLM_BASE_URL}")
    print(f"  Embeddings: {EMBEDDING_BASE_URL}")
    graphiti = Graphiti(
        NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
        embedder=embedder,
        llm_client=llm_client,
    )
    await graphiti.build_indices_and_constraints()
    print("  Connected and indices built")

    now = datetime.now(timezone.utc)

    # Ingest herbs
    print(f"\n=== Ingesting {len(herbs)} herbs ===")
    for i in range(0, len(herbs), BATCH_SIZE):
        batch = herbs[i : i + BATCH_SIZE]
        for herb in batch:
            await graphiti.add_episode(
                name=f"herb_{herb['id']}",
                episode_body=json.dumps(
                    {
                        "entity_type": "Herb",
                        "id": herb["id"],
                        "scientific_name": herb["scientific_name"],
                        "common_name": herb["common_name"],
                        "family": herb["family"],
                        "is_food_plant": bool(herb["is_food_plant"]),
                        "is_edible": bool(herb["is_edible"]),
                        "compound_count": herb["compound_count"],
                    }
                ),
                source=EpisodeType.json,
                source_description="Dr. Duke's Phytochemical Database — herb entity",
                reference_time=now,
            )
        print(f"  Ingested herbs {i + 1}-{min(i + len(batch), len(herbs))}")

    # Ingest compounds
    print(f"\n=== Ingesting {len(compounds)} compounds ===")
    for i in range(0, len(compounds), BATCH_SIZE):
        batch = compounds[i : i + BATCH_SIZE]
        for compound in batch:
            await graphiti.add_episode(
                name=f"compound_{compound['id']}",
                episode_body=json.dumps(
                    {
                        "entity_type": "Compound",
                        "id": compound["id"],
                        "name": compound["name"],
                        "compound_class": compound["compound_class"],
                        "bioactivities": compound["bioactivities"],
                        "herb_count": compound["herb_count"],
                        "food_count": compound["food_count"],
                    }
                ),
                source=EpisodeType.json,
                source_description="Dr. Duke's Phytochemical Database — compound entity",
                reference_time=now,
            )
        print(f"  Ingested compounds {i + 1}-{min(i + len(batch), len(compounds))}")

    # Ingest herb-compound relationships
    print(f"\n=== Ingesting {len(herb_compound_links)} herb-compound links ===")
    for i in range(0, len(herb_compound_links), BATCH_SIZE):
        batch = herb_compound_links[i : i + BATCH_SIZE]
        for link in batch:
            await graphiti.add_episode(
                name=f"hc_{link['herb_id']}_{link['compound_id']}",
                episode_body=json.dumps(
                    {
                        "relationship": "CONTAINS_COMPOUND",
                        "herb": link["herb_name"] or link["scientific_name"],
                        "compound": link["compound_name"],
                        "plant_part": link["plant_part"],
                        "concentration_ppm": link["concentration_high_ppm"],
                    }
                ),
                source=EpisodeType.json,
                source_description="Dr. Duke's — herb contains compound relationship",
                reference_time=now,
            )
        print(f"  Ingested links {i + 1}-{min(i + len(batch), len(herb_compound_links))}")

    # Ingest compound-target relationships
    if compound_target_links:
        print(f"\n=== Ingesting {len(compound_target_links)} compound-target links ===")
        for i in range(0, len(compound_target_links), BATCH_SIZE):
            batch = compound_target_links[i : i + BATCH_SIZE]
            for link in batch:
                await graphiti.add_episode(
                    name=f"ct_{link['compound_id']}_{link['target_id']}",
                    episode_body=json.dumps(
                        {
                            "relationship": "TARGETS_PROTEIN",
                            "compound": link["compound_name"],
                            "target": link["target_name"],
                            "activity_value": link["activity_value"],
                            "activity_type": link["activity_type"],
                        }
                    ),
                    source=EpisodeType.json,
                    source_description="CMAUP — compound targets protein relationship",
                    reference_time=now,
                )
            print(f"  Ingested target links {i + 1}-{min(i + len(batch), len(compound_target_links))}")

    await graphiti.close()
    print("\n=== Ingestion complete ===")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(ingest_to_graphiti(dry_run=dry_run))
