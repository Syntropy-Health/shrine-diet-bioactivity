"""Enrich Food nodes in Aura with `nutrition_100g` property from SQLite bridge.

The `enrich-nutrition.ts` flow populates `compound_foods.nutrition_100g` (the
edge layer). The dietitian agent queries Food NODES, so we lift the per-food
nutrient profile (one JSON blob per food name) onto the Food node properties.

Idempotent: uses Cypher SET; re-running with the same source data is a no-op.
Honors the scope='shared' policy by matching only Food nodes already in scope.

Run:
    python3 scripts/enrich_food_nodes.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = PROJECT_ROOT / "data_local" / "herbal_botanicals.db"


def collect_food_nutrition(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {food_name: nutrition_100g_json}.

    Multiple compound_foods rows can share the same food_name; we take any
    non-null nutrition payload (they're identical per food, sourced from the
    bridge). Falls back gracefully if the column doesn't exist.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(compound_foods)")}
    if "nutrition_100g" not in cols:
        print("compound_foods.nutrition_100g column missing — run enrich-nutrition first", file=sys.stderr)
        return {}

    by_food: dict[str, str] = {}
    cur = conn.execute(
        "SELECT food_name, nutrition_100g FROM compound_foods "
        "WHERE nutrition_100g IS NOT NULL AND nutrition_100g != '' "
        "GROUP BY food_name"
    )
    for food_name, nutrition_json in cur:
        if food_name and nutrition_json:
            by_food[str(food_name)] = str(nutrition_json)
    return by_food


def enrich_aura(driver, workspace: str, by_food: dict[str, str]) -> tuple[int, int]:
    """Apply nutrition_100g to Food nodes; return (matched, missed) counts."""
    matched = 0
    missed = 0
    safe_ws = "".join(c if c.isalnum() or c == "_" else "_" for c in workspace)

    # Batch updates — UNWIND a list of {entity_id, payload} dicts.
    # Only matches Food nodes in workspace + shared scope.
    rows = [{"entity_id": k, "payload": v} for k, v in by_food.items()]
    BATCH = 500
    with driver.session() as s:
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            result = s.run(
                f"UNWIND $rows AS row "
                f"MATCH (f:`{safe_ws}`:Food {{entity_id: row.entity_id}}) "
                f"WHERE f.scope = 'shared' "
                f"SET f.nutrition_100g = row.payload "
                f"RETURN count(f) AS c",
                rows=batch,
            ).single()
            if result is not None:
                matched += int(result["c"])

    missed = len(rows) - matched
    return matched, missed


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    workspace = os.environ.get("WORKSPACE", "unified_diet_kg")

    print(f"Reading nutrition payloads from {SQLITE_DB}", file=sys.stderr)
    conn = sqlite3.connect(str(SQLITE_DB))
    by_food = collect_food_nutrition(conn)
    conn.close()
    print(f"Found {len(by_food)} foods with nutrition_100g", file=sys.stderr)

    if not by_food:
        print("Nothing to enrich.", file=sys.stderr)
        return 0

    print(f"Enriching Food nodes in {uri.split('//')[1].split('.')[0]} workspace={workspace}", file=sys.stderr)
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        matched, missed = enrich_aura(driver, workspace, by_food)

    print(f"  enriched: {matched}", file=sys.stderr)
    print(f"  missed (food in SQLite but not in Aura): {missed}", file=sys.stderr)

    # Sanity: report sample for verification
    if matched > 0:
        with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
            with driver.session() as s:
                rec = s.run(
                    "MATCH (f:Food) WHERE f.nutrition_100g IS NOT NULL "
                    "RETURN f.entity_id AS name, f.nutrition_100g AS payload LIMIT 1"
                ).single()
                if rec:
                    payload = rec["payload"]
                    try:
                        keys = list(json.loads(payload).keys())[:5]
                    except (TypeError, ValueError):
                        keys = []
                    print(f"  sample: {rec['name']} → {len(payload)} chars, keys[:5]={keys}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
