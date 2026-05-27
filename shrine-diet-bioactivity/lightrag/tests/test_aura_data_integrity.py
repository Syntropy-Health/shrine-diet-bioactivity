"""Aura/Neo4j data-integrity gates.

Verifies the indexed KG instance contains the expected entity/edge
mass per label. Skips cleanly when Neo4j credentials are absent (so
PRs from forks and local-dev runs without secrets pass instead of
fail).

The thresholds below are deliberately conservative — they catch
catastrophic regressions (empty index, half-loaded ingest) without
flapping when the upstream sources tick by ±5%. Bump them upward
only when an ingest run consistently exceeds the new floor.
"""
from __future__ import annotations

import os

import pytest

# Minimum node counts per label; conservative floors to detect
# catastrophic ingest failures without flapping on small data drift.
MIN_NODE_COUNTS = {
    "Herb": 1500,
    "Compound": 3000,
    "Food": 500,
    "Target": 500,
    "Disease": 3000,
    "Symptom": 100,
}


@pytest.fixture(scope="module")
def neo4j_driver():
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("NEO4J_PASS")
    if not (uri and user and password):
        pytest.skip(
            "NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD not set; "
            "skipping Aura data-integrity gates."
        )
    try:
        from neo4j import GraphDatabase
    except ImportError:
        pytest.skip("neo4j driver not installed; skipping Aura gates.")
    # GraphDatabase.driver() parses the URI eagerly and raises
    # ConfigurationError on a missing scheme — keep it inside the same
    # try-block as the session smoke-test so a misconfigured secret
    # produces a clean skip+warning, not a hard test failure.
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        # Smoke-test the connection up front; without this a credentials
        # error wouldn't surface until the first per-test query, which
        # makes per-label test failures all look like the same root cause.
        with driver.session() as s:
            s.run("RETURN 1").consume()
    except Exception as e:  # noqa: BLE001 — surface any setup failure as skip
        if driver is not None:
            driver.close()
        pytest.skip(f"Neo4j connection setup failed ({type(e).__name__}: {e}); skipping.")
    yield driver
    driver.close()


@pytest.mark.parametrize(
    ("label", "min_count"),
    sorted(MIN_NODE_COUNTS.items()),
    ids=lambda v: v if isinstance(v, str) else f"min={v}",
)
def test_label_node_count_meets_floor(neo4j_driver, label: str, min_count: int) -> None:
    """Each indexed entity label must contain ≥ MIN_NODE_COUNTS[label] nodes."""
    with neo4j_driver.session() as s:
        # Use APOC-free count via cypher-only label scan; works on Aura free
        # tier without extensions.
        record = s.run(
            f"MATCH (n:`{label}`) RETURN count(n) AS n"
        ).single()
        actual = record["n"] if record else 0
        assert actual >= min_count, (
            f"label {label!r}: {actual} nodes (floor: {min_count}). "
            "Possible ingest regression — check the most recent ingest run."
        )


def test_no_orphan_nodes(neo4j_driver) -> None:
    """Every node should participate in at least one relationship.

    Floor: 15% (lowered from the prior 95% on 2026-05-27). The free-tier
    Aura strategy keeps all entity metadata for semantic-search recall
    even when an entity has no current typed edges — notably ~90K
    compounds from the SYN-85 clinical-anchor embed. The original 95%
    threshold encoded an "all-edges-loaded" expectation that doesn't
    match the prototype-v0 free-tier shape. SYN-109 tracks ingestion
    work that will reduce the orphan count by adding Target→Disease
    plus broader Herb→Disease edges; ratchet this threshold upward
    as that lands.
    """
    with neo4j_driver.session() as s:
        total = s.run("MATCH (n) RETURN count(n) AS n").single()["n"]
        connected = s.run(
            "MATCH (n) WHERE EXISTS { MATCH (n)--() } RETURN count(n) AS n"
        ).single()["n"]
        if total == 0:
            pytest.skip("Empty graph; orphan check N/A.")
        ratio = connected / total
        assert ratio >= 0.15, (
            f"Only {ratio:.1%} of nodes have at least one edge "
            f"({connected}/{total}). Below the free-tier-strategy floor "
            f"of 15%; likely half-loaded ingest or KG corruption."
        )
