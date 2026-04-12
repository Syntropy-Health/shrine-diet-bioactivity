"""
Direct Neo4j ingestion — bypasses Graphiti LLM extraction.

Our data is already structured (herbs, compounds, targets, diseases with known
relationships). No LLM entity extraction needed. Uses embeddings only for
vector search indices on node names/descriptions.

This is faster, cheaper, and more reliable than Graphiti's LLM-based approach
for structured data. Graphiti's add_episode() is designed for unstructured text
where entities need to be discovered — our entities are already known.

Usage:
    python ingest_direct.py                # Ingest with defaults
    python ingest_direct.py --dry-run      # Show what would be ingested
    MAX_HERBS=500 python ingest_direct.py  # Larger subsample
"""

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import httpx
from neo4j import AsyncGraphDatabase

from config import (
    BATCH_SIZE,
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MAX_COMPOUNDS,
    MAX_HERBS,
    MAX_LINKS,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    SQLITE_DB_PATH,
)


async def get_embedding(client: httpx.AsyncClient, text: str) -> list[float]:
    """Get embedding from local LM Studio."""
    try:
        resp = await client.post(
            f"{EMBEDDING_BASE_URL}/embeddings",
            json={"model": EMBEDDING_MODEL, "input": text[:512]},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"  Embedding error: {e}")
        return [0.0] * EMBEDDING_DIM


def get_sqlite_connection() -> sqlite3.Connection:
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"ERROR: DB not found at {SQLITE_DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


async def create_schema(driver):
    """Create Neo4j constraints and indices."""
    async with driver.session() as s:
        # Constraints
        await s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (h:Herb) REQUIRE h.id IS UNIQUE")
        await s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Compound) REQUIRE c.id IS UNIQUE")
        await s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (t:Target) REQUIRE t.id IS UNIQUE")
        await s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:Disease) REQUIRE d.name IS UNIQUE")
        await s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:Symptom) REQUIRE s.id IS UNIQUE")

        # Vector indices for semantic search
        try:
            await s.run(f"""
                CREATE VECTOR INDEX herb_embedding IF NOT EXISTS
                FOR (h:Herb) ON (h.embedding)
                OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBEDDING_DIM}, `vector.similarity_function`: 'cosine'}}}}
            """)
            await s.run(f"""
                CREATE VECTOR INDEX compound_embedding IF NOT EXISTS
                FOR (c:Compound) ON (c.embedding)
                OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBEDDING_DIM}, `vector.similarity_function`: 'cosine'}}}}
            """)
        except Exception as e:
            print(f"  Vector index creation (may already exist): {e}")

        # Fulltext indices for keyword search
        try:
            await s.run("""
                CREATE FULLTEXT INDEX herb_search IF NOT EXISTS
                FOR (h:Herb) ON EACH [h.common_name, h.scientific_name]
            """)
            await s.run("""
                CREATE FULLTEXT INDEX compound_search IF NOT EXISTS
                FOR (c:Compound) ON EACH [c.name]
            """)
        except Exception as e:
            print(f"  Fulltext index creation (may already exist): {e}")

    print("  Schema and indices created")


async def ingest_herbs(driver, http_client, conn, limit):
    """Ingest herb nodes with embeddings."""
    cursor = conn.execute("""
        SELECT h.id, h.scientific_name, h.common_name, h.family,
               h.is_food_plant, h.is_edible,
               (SELECT COUNT(DISTINCT compound_id) FROM herb_compounds WHERE herb_id = h.id) as compound_count
        FROM herbs h ORDER BY compound_count DESC LIMIT ?
    """, (limit,))
    herbs = [dict(r) for r in cursor.fetchall()]
    print(f"  Ingesting {len(herbs)} herbs...")

    async with driver.session() as s:
        for i, herb in enumerate(herbs):
            text = f"{herb['common_name'] or ''} {herb['scientific_name']} {herb['family'] or ''}"
            embedding = await get_embedding(http_client, text.strip())

            await s.run("""
                MERGE (h:Herb {id: $id})
                SET h.scientific_name = $scientific_name,
                    h.common_name = $common_name,
                    h.family = $family,
                    h.is_food_plant = $is_food_plant,
                    h.is_edible = $is_edible,
                    h.compound_count = $compound_count,
                    h.embedding = $embedding,
                    h.source = 'duke'
            """, {
                **herb,
                "is_food_plant": bool(herb["is_food_plant"]),
                "is_edible": bool(herb["is_edible"]),
                "embedding": embedding,
            })

            if (i + 1) % 50 == 0:
                print(f"    {i + 1}/{len(herbs)} herbs")

    print(f"  Done: {len(herbs)} herbs")
    return len(herbs)


async def ingest_compounds(driver, http_client, conn, limit):
    """Ingest compound nodes with embeddings."""
    cursor = conn.execute("""
        SELECT c.id, c.name, c.compound_class, c.bioactivities,
               (SELECT COUNT(DISTINCT herb_id) FROM herb_compounds WHERE compound_id = c.id) as herb_count,
               (SELECT COUNT(DISTINCT food_name) FROM compound_foods WHERE compound_id = c.id) as food_count
        FROM compounds c ORDER BY herb_count DESC LIMIT ?
    """, (limit,))
    compounds = [dict(r) for r in cursor.fetchall()]
    print(f"  Ingesting {len(compounds)} compounds...")

    async with driver.session() as s:
        for i, cpd in enumerate(compounds):
            bioactivities = []
            try:
                bioactivities = json.loads(cpd.get("bioactivities", "[]") or "[]")
            except (json.JSONDecodeError, TypeError):
                pass

            text = f"{cpd['name']} {cpd['compound_class'] or ''} {' '.join(bioactivities[:5])}"
            embedding = await get_embedding(http_client, text.strip())

            await s.run("""
                MERGE (c:Compound {id: $id})
                SET c.name = $name,
                    c.compound_class = $compound_class,
                    c.bioactivities = $bioactivities,
                    c.herb_count = $herb_count,
                    c.food_count = $food_count,
                    c.embedding = $embedding,
                    c.source = 'duke+foodb'
            """, {
                "id": cpd["id"],
                "name": cpd["name"],
                "compound_class": cpd["compound_class"],
                "bioactivities": bioactivities,
                "herb_count": cpd["herb_count"],
                "food_count": cpd["food_count"],
                "embedding": embedding,
            })

            if (i + 1) % 50 == 0:
                print(f"    {i + 1}/{len(compounds)} compounds")

    print(f"  Done: {len(compounds)} compounds")
    return len(compounds)


async def ingest_targets(driver, conn):
    """Ingest target nodes (no embedding needed — small set)."""
    cursor = conn.execute("SELECT id, name, uniprot_id, gene_symbol FROM targets LIMIT 1000")
    targets = [dict(r) for r in cursor.fetchall()]
    print(f"  Ingesting {len(targets)} targets...")

    async with driver.session() as s:
        for t in targets:
            await s.run("""
                MERGE (t:Target {id: $id})
                SET t.name = $name, t.uniprot_id = $uniprot_id,
                    t.gene_symbol = $gene_symbol, t.source = 'cmaup'
            """, t)

    print(f"  Done: {len(targets)} targets")
    return len(targets)


async def ingest_symptoms(driver, conn):
    """Ingest symptom nodes."""
    cursor = conn.execute("SELECT id, name, symptom_type, description FROM symptoms")
    symptoms = [dict(r) for r in cursor.fetchall()]
    print(f"  Ingesting {len(symptoms)} symptoms...")

    async with driver.session() as s:
        for sym in symptoms:
            await s.run("""
                MERGE (s:Symptom {id: $id})
                SET s.name = $name, s.symptom_type = $symptom_type,
                    s.description = $description
            """, sym)

    print(f"  Done: {len(symptoms)} symptoms")
    return len(symptoms)


async def ingest_relationships(driver, conn, herb_ids, compound_ids, max_links):
    """Ingest edges: CONTAINS_COMPOUND, TARGETS_PROTEIN, ASSOCIATED_WITH_SYMPTOM."""
    stats = {"herb_compound": 0, "compound_target": 0, "herb_symptom": 0}

    # Herb → Compound
    if herb_ids:
        ph = ",".join("?" for _ in herb_ids)
        cursor = conn.execute(f"""
            SELECT hc.herb_id, hc.compound_id, hc.plant_part,
                   hc.concentration_high_ppm
            FROM herb_compounds hc
            WHERE hc.herb_id IN ({ph})
            ORDER BY hc.concentration_high_ppm DESC NULLS LAST
            LIMIT ?
        """, [*herb_ids, max_links])
        links = [dict(r) for r in cursor.fetchall()]
        print(f"  Ingesting {len(links)} herb→compound edges...")

        async with driver.session() as s:
            for link in links:
                await s.run("""
                    MATCH (h:Herb {id: $herb_id}), (c:Compound {id: $compound_id})
                    MERGE (h)-[r:CONTAINS_COMPOUND]->(c)
                    SET r.plant_part = $plant_part,
                        r.concentration_ppm = $concentration_high_ppm
                """, link)
                stats["herb_compound"] += 1

    # Compound → Target
    if compound_ids:
        ph = ",".join("?" for _ in compound_ids)
        cursor = conn.execute(f"""
            SELECT ct.compound_id, ct.target_id, ct.activity_value, ct.activity_type
            FROM compound_targets ct
            WHERE ct.compound_id IN ({ph})
            LIMIT ?
        """, [*compound_ids, max_links])
        links = [dict(r) for r in cursor.fetchall()]
        print(f"  Ingesting {len(links)} compound→target edges...")

        async with driver.session() as s:
            for link in links:
                await s.run("""
                    MATCH (c:Compound {id: $compound_id}), (t:Target {id: $target_id})
                    MERGE (c)-[r:TARGETS_PROTEIN]->(t)
                    SET r.activity_value = $activity_value,
                        r.activity_type = $activity_type
                """, link)
                stats["compound_target"] += 1

    # Herb → Symptom
    if herb_ids:
        ph_herb = ",".join("?" for _ in herb_ids)
        cursor = conn.execute(f"""
            SELECT hs.herb_id, hs.symptom_id
            FROM herb_symptoms hs
            WHERE hs.herb_id IN ({ph_herb})
            LIMIT ?
        """, [*herb_ids, max_links])
        links = [dict(r) for r in cursor.fetchall()]
        print(f"  Ingesting {len(links)} herb→symptom edges...")

        async with driver.session() as s:
            for link in links:
                await s.run("""
                    MATCH (h:Herb {id: $herb_id}), (s:Symptom {id: $symptom_id})
                    MERGE (h)-[:TREATS]->(s)
                """, link)
                stats["herb_symptom"] += 1

    print(f"  Done: {stats}")
    return stats


async def main():
    dry_run = "--dry-run" in sys.argv
    conn = get_sqlite_connection()

    # Count what we'll ingest
    herbs_count = conn.execute(f"SELECT COUNT(*) FROM (SELECT id FROM herbs ORDER BY (SELECT COUNT(*) FROM herb_compounds WHERE herb_id = herbs.id) DESC LIMIT {MAX_HERBS})").fetchone()[0]
    compounds_count = conn.execute(f"SELECT COUNT(*) FROM (SELECT id FROM compounds ORDER BY (SELECT COUNT(*) FROM herb_compounds WHERE compound_id = compounds.id) DESC LIMIT {MAX_COMPOUNDS})").fetchone()[0]
    targets_count = conn.execute("SELECT COUNT(*) FROM targets LIMIT 1000").fetchone()[0]
    symptoms_count = conn.execute("SELECT COUNT(*) FROM symptoms").fetchone()[0]

    print(f"\n=== Direct Neo4j Ingestion ===")
    print(f"  Herbs: {herbs_count}")
    print(f"  Compounds: {compounds_count}")
    print(f"  Targets: {min(targets_count, 1000)}")
    print(f"  Symptoms: {symptoms_count}")
    print(f"  Max link edges: {MAX_LINKS}")
    print(f"  Neo4j: {NEO4J_URI}")
    print(f"  Embeddings: {EMBEDDING_BASE_URL}")

    if dry_run:
        print("\n  DRY RUN — no changes made.")
        conn.close()
        return

    if not NEO4J_PASSWORD:
        print("ERROR: NEO4J_PASSWORD not set")
        sys.exit(1)

    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    http_client = httpx.AsyncClient()

    try:
        print("\n--- Creating schema ---")
        await create_schema(driver)

        print("\n--- Ingesting nodes ---")
        await ingest_herbs(driver, http_client, conn, MAX_HERBS)
        await ingest_compounds(driver, http_client, conn, MAX_COMPOUNDS)
        await ingest_targets(driver, conn)
        await ingest_symptoms(driver, conn)

        # Collect IDs for relationship ingestion
        herb_ids = [r[0] for r in conn.execute(f"SELECT id FROM herbs ORDER BY (SELECT COUNT(*) FROM herb_compounds WHERE herb_id = herbs.id) DESC LIMIT {MAX_HERBS}").fetchall()]
        compound_ids = [r[0] for r in conn.execute(f"SELECT id FROM compounds ORDER BY (SELECT COUNT(*) FROM herb_compounds WHERE compound_id = compounds.id) DESC LIMIT {MAX_COMPOUNDS}").fetchall()]

        print("\n--- Ingesting relationships ---")
        await ingest_relationships(driver, conn, herb_ids, compound_ids, MAX_LINKS)

        # Final stats
        async with driver.session() as s:
            result = await s.run("MATCH (n) RETURN COUNT(n) AS c")
            nodes = (await result.single())["c"]
            result = await s.run("MATCH ()-[r]->() RETURN COUNT(r) AS c")
            rels = (await result.single())["c"]
            print(f"\n=== Complete: {nodes} nodes, {rels} relationships ===")

    finally:
        await http_client.aclose()
        await driver.close()
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
