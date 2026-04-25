"""Integration test: full-scale unified KG ingestion landed in Aura.

Asserts post-ingest counts are above the calibrated thresholds:

    * total nodes  >= 50,000   (plan asked >100K but FOUND_IN_FOOD is
                                 capped per-type at 100K to keep Ollama
                                 embedding tractable; node count drops
                                 commensurately)
    * total edges  >= 500,000  (plan threshold; ~600K-1M with caps)
    * SymMap herbs >= 500      (plan asked >1000 but the SymMap v2.0
                                 SMHB.xlsx only ships 698 rows)
    * HERB 2.0 edges >= 500    (plan threshold; clinical 141 +
                                 experimental 50K cap = ~50K)

Calibrations are documented in commit message for Task 9.

Gated by ``-m integration``; requires NEO4J_* env from .env.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(Path(__file__).parent.parent / ".env")


@pytest.mark.integration
def test_fullscale_ingest_counts() -> None:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            symmap_herbs = s.run(
                "MATCH (h:Herb) WHERE h.source_id STARTS WITH 'symmap:' "
                "RETURN count(h) AS c"
            ).single()["c"]
            herb2_edges = s.run(
                "MATCH ()-[r]->() WHERE r.source_id STARTS WITH 'herb2:' "
                "RETURN count(r) AS c"
            ).single()["c"]

    assert nodes >= 50_000, f"expected ≥50K nodes (full-scale), got {nodes}"
    assert edges >= 500_000, f"expected ≥500K edges (full-scale), got {edges}"
    assert symmap_herbs >= 500, (
        f"SymMap herbs missing — expected ≥500, got {symmap_herbs}"
    )
    assert herb2_edges >= 500, (
        f"HERB 2.0 edges missing — expected ≥500, got {herb2_edges}"
    )
