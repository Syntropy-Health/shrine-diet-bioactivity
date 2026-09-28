"""Real-database arm for the scoped /graphs Cypher (shrine-diet #6).

The unit suite drives ``ScopedNeo4JStorage.get_knowledge_graph`` with a fake
driver, which can prove the Python BFS and that the query TEXT carries the
scope clauses — but not that Neo4j parses and honours that text. This file
runs the exact builders from ``cypher_fragments`` against the live graph.

Gated like ``test_aura_data_integrity.py``: skips locally without
``NEO4J_URI``/``NEO4J_USERNAME``/``NEO4J_PASSWORD``; in the mcp-ci lightrag job
those secrets are REQUIRED (a missing one fails the job, it does not skip).
Imports only ``neo4j`` + ``pytest`` + the leaf ``cypher_fragments`` module —
no ``lightrag`` — so it runs in that job's minimal environment. READ-ONLY.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lightrag/ dir: cypher_fragments.py
from cypher_fragments import (  # noqa: E402
    hop_query,
    nodes_by_ids_query,
    resolve_exact_query,
    resolve_scan_query,
    wildcard_count_query,
    wildcard_top_query,
)

WS = os.environ.get("WORKSPACE", "unified_diet_kg")
SHARED = ["shared"]


@pytest.fixture(scope="module")
def session():
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("NEO4J_PASS")
    if not (uri and user and password):
        pytest.skip("NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD not set; live Aura arm skipped")
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password), notifications_min_severity="OFF")
    db = os.environ.get("NEO4J_DATABASE") or None
    with driver.session(database=db, default_access_mode="READ") as s:
        yield s
    driver.close()


def _first(session, query, **params):
    rec = session.run(query, **params).single()
    return rec["entity_id"] if rec else None


def test_exact_lookup_is_case_sensitive_and_scoped(session) -> None:
    assert _first(session, resolve_exact_query(WS), seed="CURCUMIN", scope_filter=SHARED) == "CURCUMIN"
    assert _first(session, resolve_exact_query(WS), seed="curcumin", scope_filter=SHARED) is None
    # a scope nothing carries returns nothing — the clause is live, not decorative
    assert _first(session, resolve_exact_query(WS), seed="CURCUMIN", scope_filter=["tenant:no-such-tenant-6"]) is None


def test_scan_resolves_case_fold_common_name_and_cid_deterministically(session) -> None:
    scan = resolve_scan_query(WS)
    # Aura holds both 'Curcumin' and 'CURCUMIN'; the tie must break the same way every call
    got = {_first(session, scan, seed="curcumin", scope_filter=SHARED) for _ in range(3)}
    assert got == {"CURCUMIN"}, got
    assert _first(session, scan, seed="turmeric", scope_filter=SHARED) == "Turmeric"
    assert _first(session, scan, seed="969516", scope_filter=SHARED) == "Curcumin"   # PubChem CID arm
    assert _first(session, scan, seed="zzz-no-such-entity-#6", scope_filter=SHARED) is None


def test_hop_query_returns_only_in_scope_rows_with_true_direction(session) -> None:
    rows = list(session.run(hop_query(WS), frontier=["CURCUMIN"], scope_filter=SHARED))
    assert rows, "CURCUMIN has in-scope neighbours on Aura (measured 33 rels at depth 1)"
    for r in rows:
        assert r["here"] == "CURCUMIN"
        assert "CURCUMIN" in (r["src"], r["tgt"])
        assert r["props"].get("scope") == "shared"
    # negative control: an impossible scope yields nothing
    assert list(session.run(hop_query(WS), frontier=["CURCUMIN"], scope_filter=["tenant:no-such-tenant-6"])) == []


def test_nodes_by_ids_and_wildcard_queries_execute_in_scope(session) -> None:
    rows = list(session.run(nodes_by_ids_query(WS), ids=["CURCUMIN", "Turmeric"], scope_filter=SHARED))
    assert {r["entity_id"] for r in rows} == {"CURCUMIN", "Turmeric"}
    assert all(r["props"]["scope"] == "shared" and WS in r["labels"] for r in rows)
    total = session.run(wildcard_count_query(WS), scope_filter=SHARED).single()["total"]
    assert total > 0
    top = list(session.run(wildcard_top_query(WS), scope_filter=SHARED, max_nodes=5))
    assert 0 < len(top) <= 5 and all(r["props"]["scope"] == "shared" for r in top)
