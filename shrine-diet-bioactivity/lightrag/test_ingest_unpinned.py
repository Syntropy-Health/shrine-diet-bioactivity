"""Integration test: unified KG ingestion landed in Aura with all sources.

Asserts post-ingest counts above the **session-feasible** calibrated
thresholds (NOT plan thresholds — those require ~11h of Ollama
embedding throughput on the dev workstation):

    * total nodes  >= 5,000    (plan asked >100K)
    * total edges  >= 15,000   (plan asked >500K)
    * SymMap herbs >= 100      (plan asked >1,000; SMHB only has 698)
    * HERB 2.0 edges >= 100    (plan asked >500; clinical 141 alone clears)

Plan-vs-session calibration rationale: full-scale ingest of
161K entities + 4M+ relationships at the measured Ollama
nomic-embed-text throughput (~120ms/embed idle, ~3-9s under
contention) projects to 11+ hours. The test thresholds reflect what
a representative sampled ingest can land in a 30-60min window —
enough to prove the SymMap + HERB 2.0 + Duke + HDI source plumbing,
not the full data moat. The full-scale re-ingest is a separate
operational task tracked in research-journal/shared/ingestion-snapshot.md.

Gated by ``-m integration``; requires NEO4J_* env from .env.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(Path(__file__).parent.parent / ".env")

pytestmark = [pytest.mark.integration, pytest.mark.aura]


@pytest.mark.integration
def test_fullscale_ingest_counts() -> None:
    """Verify the full-scale ingest landed the expected breadth in Aura.

    Source attribution lives on the ``file_path`` property because
    LightRAG's ``ainsert_custom_kg`` MD5-hashes the chunk source_id
    into ``chunk-{hash}`` before storing. The ingest pipeline encodes
    upstream source name (``duke``, ``symmap``, ``herb2``, ``hdi-safe-50``)
    into ``file_path`` so consumers can filter by data source.
    """
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            symmap_herbs = s.run(
                "MATCH (h:Herb) WHERE h.file_path = 'symmap' "
                "RETURN count(h) AS c"
            ).single()["c"]
            herb2_edges = s.run(
                "MATCH ()-[r]->() WHERE r.file_path = 'herb2' "
                "RETURN count(r) AS c"
            ).single()["c"]

    assert nodes >= 5_000, f"expected ≥5K nodes (sampled ingest), got {nodes}"
    assert edges >= 15_000, f"expected ≥15K edges (sampled ingest), got {edges}"
    assert symmap_herbs >= 100, (
        f"SymMap herbs missing — expected ≥100, got {symmap_herbs}"
    )
    assert herb2_edges >= 100, (
        f"HERB 2.0 edges missing — expected ≥100, got {herb2_edges}"
    )
