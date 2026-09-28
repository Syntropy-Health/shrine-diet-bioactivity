"""Shared Cypher for the scoped graph layer — a LEAF module (imports nothing local).

Why a leaf: ``scoped_server`` imports ``scoped_neo4j_storage``, so the storage
layer cannot import from the server without a cycle; both import from here.
One definition of the seed-matching rule keeps the typed ``/traverse`` routes
and ``ScopedNeo4JStorage.get_knowledge_graph`` from drifting (QG finding,
reviewer-design P2, shrine-diet #6).

Why the ``/graphs`` queries live here too: the query TEXT is the artifact that
reaches Neo4j, and the only test that can prove it behaves is one that runs it
against a real database. ``tests/test_graphs_scoped_cypher_aura.py`` does that
in the CI job that already holds Aura credentials — a job that installs only
``neo4j`` + ``pytest``, so nothing here may import ``lightrag``.

Every builder takes an already-escaped workspace label (callers pass
``Neo4JStorage._get_workspace_label()``, which escapes backticks) and returns a
query whose user-controlled values are ALL parameters (``$seed``, ``$frontier``,
``$ids``, ``$scope_filter``, ``$max_nodes``) — never interpolated.
"""
from __future__ import annotations


def seed_match_predicate(var: str, param: str = "seed") -> str:
    """Case-insensitive entity-resolution predicate for node variable ``var``
    against Cypher parameter ``$<param>``.

    Arms (Phase 0/2 entity resolution): ``entity_id``, ``common_name``, any
    element of ``aliases``, or an exact ``pubchem_cid`` literal. Callers wrap
    it in their own parentheses. This matches EVERY node satisfying an arm —
    ``/traverse`` fans out over all of them, while the neighborhood resolver
    picks ONE (see :func:`resolve_scan_query`); that one-vs-many choice is the
    caller's, not this predicate's.
    """
    return (
        f"    toLower({var}.entity_id) = toLower(${param}) "
        f"    OR toLower(coalesce({var}.common_name, '')) = toLower(${param}) "
        f"    OR any(_a IN coalesce({var}.aliases, []) WHERE toLower(_a) = toLower(${param})) "
        f"    OR ({var}.pubchem_cid IS NOT NULL AND toString({var}.pubchem_cid) = ${param}) "
    )


# ─── seed resolution (two steps, cheapest first) ──────────────────────────


def resolve_exact_query(ws: str) -> str:
    """Index-served exact ``entity_id`` lookup, in scope. Params: seed, scope_filter."""
    return (
        f"MATCH (n:`{ws}` {{entity_id: $seed}}) "
        f"WHERE n.scope IN $scope_filter "
        f"RETURN n.entity_id AS entity_id LIMIT 1"
    )


def resolve_scan_query(ws: str) -> str:
    """Predicate scan, in scope, picking ONE node: case-folded id matches rank
    before name / alias / CID matches, ties break on ``entity_id`` (Aura holds
    both ``Curcumin`` and ``CURCUMIN``) so the answer is deterministic.
    Params: seed, scope_filter."""
    return (
        f"MATCH (n:`{ws}`) "
        f"WHERE n.scope IN $scope_filter "
        f"  AND ("
        + seed_match_predicate("n")
        + f"  ) "
        f"RETURN n.entity_id AS entity_id "
        f"ORDER BY CASE WHEN toLower(n.entity_id) = toLower($seed) THEN 0 ELSE 1 END, "
        f"         n.entity_id "
        f"LIMIT 1"
    )


# ─── seeded neighbourhood: one hop per BFS level ──────────────────────────


def hop_query(ws: str) -> str:
    """All in-scope edges touching the frontier: the frontier node ``a``, the
    relationship ``r`` AND the neighbour ``b`` must each be in scope. ``here``
    names the frontier end; ``src``/``tgt`` carry the TRUE direction from
    ``startNode(r)``. Params: frontier, scope_filter."""
    return (
        f"MATCH (a:`{ws}`)-[r]-(b:`{ws}`) "
        f"WHERE a.entity_id IN $frontier "
        f"  AND a.scope IN $scope_filter "
        f"  AND r.scope IN $scope_filter "
        f"  AND b.scope IN $scope_filter "
        f"RETURN a.entity_id AS here, elementId(r) AS rid, type(r) AS rel_type, "
        f"       startNode(r).entity_id AS src, endNode(r).entity_id AS tgt, "
        f"       properties(r) AS props"
    )


def nodes_by_ids_query(ws: str) -> str:
    """Materialise admitted nodes, still scope-checked. Params: ids, scope_filter."""
    return (
        f"MATCH (n:`{ws}`) "
        f"WHERE n.entity_id IN $ids AND n.scope IN $scope_filter "
        f"RETURN n.entity_id AS entity_id, labels(n) AS labels, properties(n) AS props"
    )


# ─── '*' wildcard: top in-scope nodes by in-scope degree ─────────────────


def wildcard_count_query(ws: str) -> str:
    """Params: scope_filter."""
    return f"MATCH (n:`{ws}`) WHERE n.scope IN $scope_filter RETURN count(n) AS total"


def wildcard_top_query(ws: str) -> str:
    """Params: scope_filter, max_nodes."""
    return (
        f"MATCH (n:`{ws}`) WHERE n.scope IN $scope_filter "
        f"OPTIONAL MATCH (n)-[r]-(m:`{ws}`) "
        f"  WHERE r.scope IN $scope_filter AND m.scope IN $scope_filter "
        f"WITH n, count(r) AS degree "
        f"ORDER BY degree DESC, n.entity_id "
        f"LIMIT $max_nodes "
        f"RETURN n.entity_id AS entity_id, labels(n) AS labels, properties(n) AS props"
    )


def wildcard_edges_query(ws: str) -> str:
    """In-scope edges among the returned nodes. Params: ids, scope_filter."""
    return (
        f"MATCH (a:`{ws}`)-[r]->(b:`{ws}`) "
        f"WHERE a.entity_id IN $ids AND b.entity_id IN $ids "
        f"  AND a.scope IN $scope_filter AND r.scope IN $scope_filter AND b.scope IN $scope_filter "
        f"RETURN elementId(r) AS rid, type(r) AS rel_type, a.entity_id AS src, "
        f"       b.entity_id AS tgt, properties(r) AS props"
    )
