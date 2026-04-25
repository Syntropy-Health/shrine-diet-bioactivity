"""Integration test: HDI-Safe 50 land in Aura via ainsert_custom_kg.

Gated by ``-m integration`` and requires NEO4J_* env (loaded from
shrine-diet-bioactivity/.env which is gitignored).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load .env from shrine-diet-bioactivity/ (one level above this file's directory)
load_dotenv(Path(__file__).parent.parent / ".env")


@pytest.mark.integration
def test_hdi_edges_land_in_aura() -> None:
    """Run the ingest, then assert ≥50 INTERACTS_WITH edges live in Aura."""
    from ingest_hdi import main as ingest_main

    ingest_main(dry_run=False)

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            n = s.run(
                "MATCH ()-[r:INTERACTS_WITH]->() RETURN count(r) AS c"
            ).single()["c"]
            assert n >= 50, f"expected ≥50 INTERACTS_WITH edges, got {n}"

            # Sample a handful of edges — verify required fields are persisted.
            sample = s.run(
                """
                MATCH (h)-[r:INTERACTS_WITH]->(d)
                RETURN h.entity_id AS herb,
                       d.entity_id AS drug,
                       r.description AS desc,
                       r.weight AS weight
                LIMIT 5
                """
            ).data()
            assert len(sample) > 0, "no INTERACTS_WITH edges sampled"
            for row in sample:
                assert row["herb"], "herb entity_id missing"
                assert row["drug"], "drug entity_id missing"
                assert row["desc"], "edge description missing"
                assert row["weight"] is not None, "edge weight missing"
