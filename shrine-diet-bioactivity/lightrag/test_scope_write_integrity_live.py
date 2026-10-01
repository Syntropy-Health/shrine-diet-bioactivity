"""Write-path scope integrity on a REAL Neo4j (shrine-diet #113).

MEASURED defect (2026-10-01, local Neo4j 5.26, lightrag-hku 1.5.0): upstream
``LightRAG.ainsert_custom_kg`` rebuilds every node/edge dict WITHOUT the
payload's ``scope`` and writes through ``upsert_nodes_batch`` /
``upsert_edges_batch`` (``MERGE {entity_id} SET n += props``), which
``ScopedNeo4JStorage`` did not override. A tenant payload therefore

* OVERWROTE the shared ``CURCUMIN`` node's description with tenant text
  (visible to every shared reader), and
* created tenant nodes/edges with ``scope = NULL`` — rows the boot preflight
  refuses, i.e. the #103 crash-loop class, reachable from ANY custom-KG ingest
  (the shared typed ingest scripts included).

This file drives the real upstream ``ainsert_custom_kg`` through the real
``ScopedNeo4JStorage`` against a real database, because a fake driver cannot
show what Neo4j's MERGE does to an existing row.

SAFETY: runs only when ``SCOPED_WRITE_TEST_NEO4J_URI`` is set AND points at a
loopback host. It writes and deletes data; it must never touch Aura. Each test
uses its own random workspace label and removes it afterwards.

RUN (the in-place ``lightrag/`` dir shadows the installed package under pytest,
#106): from a symlink harness dir not named ``lightrag``::

    SCOPED_WRITE_TEST_NEO4J_URI=bolt://127.0.0.1:17687 \\
    SCOPED_WRITE_TEST_NEO4J_PASSWORD=... python -m pytest test_scope_write_integrity_live.py
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from urllib.parse import urlparse

import pytest

URI = os.environ.get("SCOPED_WRITE_TEST_NEO4J_URI", "")
USER = os.environ.get("SCOPED_WRITE_TEST_NEO4J_USERNAME", "neo4j")
PASSWORD = os.environ.get("SCOPED_WRITE_TEST_NEO4J_PASSWORD", "")

if not URI:
    pytest.skip("SCOPED_WRITE_TEST_NEO4J_URI not set — live write-integrity arm skipped", allow_module_level=True)
if urlparse(URI).hostname not in {"127.0.0.1", "localhost", "::1"}:
    pytest.fail(f"refusing to run destructive write tests against non-loopback {urlparse(URI).hostname!r}", pytrace=False)

import numpy as np  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

import scoped_neo4j_storage  # noqa: E402,F401  (registers ScopedNeo4JStorage)
from lightrag import LightRAG  # noqa: E402
from lightrag.utils import EmbeddingFunc  # noqa: E402
from scope_context import reset_write_scope, set_write_scope  # noqa: E402
from scoped_neo4j_storage import ScopeConflictError  # noqa: E402

TENANT = "tenant:clinic-a"


def _cypher(query: str, **params):
    with GraphDatabase.driver(URI, auth=(USER, PASSWORD)) as d, d.session() as s:
        return [r.data() for r in s.run(query, **params)]


async def _embed(texts):
    return np.zeros((len(texts), 8), dtype=np.float32)


async def _llm(*_a, **_k):
    return ""


@pytest.fixture()
def ws():
    os.environ.update(NEO4J_URI=URI, NEO4J_USERNAME=USER, NEO4J_PASSWORD=PASSWORD, NEO4J_DATABASE="neo4j")
    label = f"t113_{uuid.uuid4().hex[:10]}"
    _cypher(f"CREATE (:`{label}` {{entity_id:'CURCUMIN', description:'shared-desc', scope:'shared', entity_type:'Compound'}})")
    _cypher(f"CREATE (:`{label}` {{entity_id:'NFKB1', description:'shared-target', scope:'shared', entity_type:'Target'}})")
    _cypher(f"MATCH (a:`{label}` {{entity_id:'CURCUMIN'}}), (b:`{label}` {{entity_id:'NFKB1'}}) "
            f"CREATE (a)-[:DIRECTED {{scope:'shared', description:'shared-edge'}}]->(b)")
    yield label
    _cypher(f"MATCH (n:`{label}`) DETACH DELETE n")


def _ingest(label: str, payload: dict, scope: str | None):
    async def run():
        rag = LightRAG(working_dir=tempfile.mkdtemp(), workspace=label, graph_storage="ScopedNeo4JStorage",
                       embedding_func=EmbeddingFunc(embedding_dim=8, max_token_size=512, func=_embed),
                       llm_model_func=_llm)
        await rag.initialize_storages()
        try:
            from lightrag.kg.shared_storage import initialize_pipeline_status
            await initialize_pipeline_status()
        except Exception:
            pass
        token = set_write_scope(scope) if scope else None
        try:
            await rag.ainsert_custom_kg(payload)
        finally:
            if token is not None:
                reset_write_scope(token)
            await rag.finalize_storages()
    asyncio.run(run())


def _nodes(label):
    return {r["id"]: r for r in _cypher(f"MATCH (n:`{label}`) RETURN n.entity_id AS id, n.scope AS scope, n.description AS description")}


def _edges(label):
    return _cypher(f"MATCH (a:`{label}`)-[r]->(b:`{label}`) RETURN a.entity_id AS a, b.entity_id AS b, r.scope AS scope, r.description AS description ORDER BY a, b")


def _payload(entities, relationships=()):
    return {"chunks": [{"content": "c", "source_id": "c1"}],
            "entities": [{"entity_type": "X", "source_id": "c1", **e} for e in entities],
            "relationships": [{"keywords": "k", "weight": 1.0, "source_id": "c1", **r} for r in relationships]}


def test_tenant_redefining_a_shared_entity_is_refused_and_writes_nothing(ws) -> None:
    with pytest.raises(ScopeConflictError):
        _ingest(ws, _payload([{"entity_name": "CURCUMIN", "description": "TENANT-PRIVATE-NOTE"},
                              {"entity_name": "TENANT-ONLY", "description": "tenant row"}]), TENANT)
    nodes = _nodes(ws)
    assert nodes["CURCUMIN"]["description"] == "shared-desc" and nodes["CURCUMIN"]["scope"] == "shared"
    assert "TENANT-ONLY" not in nodes, "the whole node batch must roll back, not half-apply"


def test_tenant_rows_are_born_tenant_scoped_and_shared_rows_untouched(ws) -> None:
    _ingest(ws, _payload([{"entity_name": "TENANT-ONLY", "description": "tenant row"}],
                         [{"src_id": "TENANT-ONLY", "tgt_id": "CURCUMIN", "description": "tenant link"}]), TENANT)
    nodes = _nodes(ws)
    assert nodes["TENANT-ONLY"]["scope"] == TENANT
    assert nodes["CURCUMIN"] == {"id": "CURCUMIN", "scope": "shared", "description": "shared-desc"}
    link = [e for e in _edges(ws) if "TENANT-ONLY" in (e["a"], e["b"])]
    assert len(link) == 1 and link[0]["scope"] == TENANT


def test_shared_custom_kg_ingest_never_creates_unscoped_rows(ws) -> None:
    """The batch path with NO write scope set (the typed ingest scripts) must
    stamp 'shared' — otherwise the next boot preflight refuses the graph (#103)."""
    _ingest(ws, _payload([{"entity_name": "QUERCETIN", "description": "q"}],
                         [{"src_id": "QUERCETIN", "tgt_id": "NFKB1", "description": "q-link"}]), None)
    assert _nodes(ws)["QUERCETIN"]["scope"] == "shared"
    assert _cypher(f"MATCH (n:`{ws}`) WHERE n.scope IS NULL RETURN count(n) AS c")[0]["c"] == 0
    assert _cypher(f"MATCH (:`{ws}`)-[r]-(:`{ws}`) WHERE r.scope IS NULL RETURN count(r) AS c")[0]["c"] == 0


def test_tenant_edge_over_an_existing_shared_edge_is_refused(ws) -> None:
    """Upstream MERGEs ONE undirected DIRECTED relationship per pair, so a tenant
    edge between two shared nodes that are already linked would overwrite the
    shared edge's properties."""
    with pytest.raises(ScopeConflictError):
        _ingest(ws, _payload([], [{"src_id": "CURCUMIN", "tgt_id": "NFKB1", "description": "TENANT-EDGE-NOTE"}]), TENANT)
    shared = [e for e in _edges(ws) if (e["a"], e["b"]) == ("CURCUMIN", "NFKB1")]
    assert shared == [{"a": "CURCUMIN", "b": "NFKB1", "scope": "shared", "description": "shared-edge"}]


# ─── QG round 2 (code / security / test reviewers) ─────────────────────────


def test_existing_unscoped_node_is_refused_not_overwritten(ws) -> None:
    """A legacy row with NO scope must count as a different scope (fail-closed),
    not slip past ``NULL <> 'tenant:x'`` (which is NULL, i.e. not true)."""
    _cypher(f"CREATE (:`{ws}` {{entity_id:'LEGACY', description:'legacy-desc'}})")
    with pytest.raises(ScopeConflictError):
        _ingest(ws, _payload([{"entity_name": "LEGACY", "description": "TENANT-NOTE"}]), TENANT)
    row = _nodes(ws)["LEGACY"]
    assert row["description"] == "legacy-desc" and row["scope"] is None


def test_existing_unscoped_edge_is_refused_not_overwritten(ws) -> None:
    _cypher(f"CREATE (a:`{ws}` {{entity_id:'L1', scope:'shared'}})-[:DIRECTED {{description:'legacy-edge'}}]->(b:`{ws}` {{entity_id:'L2', scope:'shared'}})")
    with pytest.raises(ScopeConflictError):
        _ingest(ws, _payload([], [{"src_id": "L1", "tgt_id": "L2", "description": "TENANT-EDGE"}]), TENANT)
    edge = [e for e in _edges(ws) if (e["a"], e["b"]) == ("L1", "L2")]
    assert edge == [{"a": "L1", "b": "L2", "scope": None, "description": "legacy-edge"}]


def test_reversed_direction_tenant_edge_over_a_shared_edge_is_refused(ws) -> None:
    """Upstream MERGEs the pair UNDIRECTED, so NFKB1->CURCUMIN lands on the
    existing CURCUMIN->NFKB1 edge; the guard must look both ways."""
    with pytest.raises(ScopeConflictError):
        _ingest(ws, _payload([], [{"src_id": "NFKB1", "tgt_id": "CURCUMIN", "description": "TENANT-REVERSED"}]), TENANT)
    edges = _cypher(f"MATCH (:`{ws}`)-[r]-(:`{ws}`) RETURN DISTINCT r.scope AS scope, r.description AS description")
    assert edges == [{"scope": "shared", "description": "shared-edge"}]


def test_tenant_cannot_hang_an_edge_on_another_tenants_node(ws) -> None:
    _cypher(f"CREATE (:`{ws}` {{entity_id:'B-PRIVATE', description:'b-only', scope:'tenant:clinic-b'}})")
    with pytest.raises(ScopeConflictError):
        _ingest(ws, _payload([{"entity_name": "A-NOTE", "description": "a"}],
                             [{"src_id": "A-NOTE", "tgt_id": "B-PRIVATE", "description": "a->b"}]), TENANT)
    attached = _cypher(f"MATCH (:`{ws}` {{entity_id:'B-PRIVATE'}})-[r]-() RETURN count(r) AS c")[0]["c"]
    assert attached == 0
    assert _nodes(ws)["B-PRIVATE"]["scope"] == "tenant:clinic-b"


def test_shared_ingest_over_an_existing_tenant_node_is_refused(ws) -> None:
    _cypher(f"CREATE (:`{ws}` {{entity_id:'T-NOTE', description:'tenant-text', scope:'{TENANT}'}})")
    with pytest.raises(ScopeConflictError):
        _ingest(ws, _payload([{"entity_name": "T-NOTE", "description": "shared-text"}]), None)
    assert _nodes(ws)["T-NOTE"] == {"id": "T-NOTE", "scope": TENANT, "description": "tenant-text"}


def test_tenant_re_ingesting_its_own_entity_is_allowed(ws) -> None:
    """No false refusals: same scope -> normal MERGE update."""
    _ingest(ws, _payload([{"entity_name": "MINE", "description": "v1"}]), TENANT)
    _ingest(ws, _payload([{"entity_name": "MINE", "description": "v2"}]), TENANT)
    assert _nodes(ws)["MINE"] == {"id": "MINE", "scope": TENANT, "description": "v2"}


def test_one_long_lived_instance_stamps_each_ingest_with_its_own_scope(ws) -> None:
    """Production shape: ONE LightRAG instance serving successive requests. A
    worker that captured the context at init would stamp every write the same."""
    async def run():
        rag = LightRAG(working_dir=tempfile.mkdtemp(), workspace=ws, graph_storage="ScopedNeo4JStorage",
                       embedding_func=EmbeddingFunc(embedding_dim=8, max_token_size=512, func=_embed),
                       llm_model_func=_llm)
        await rag.initialize_storages()
        try:
            for name, scope in (("ROW-A", "tenant:clinic-a"), ("ROW-B", "tenant:clinic-b"), ("ROW-S", None)):
                token = set_write_scope(scope) if scope else None
                try:
                    await rag.ainsert_custom_kg(_payload([{"entity_name": name, "description": name}]))
                finally:
                    if token is not None:
                        reset_write_scope(token)
        finally:
            await rag.finalize_storages()
    asyncio.run(run())
    nodes = _nodes(ws)
    assert (nodes["ROW-A"]["scope"], nodes["ROW-B"]["scope"], nodes["ROW-S"]["scope"]) == \
        ("tenant:clinic-a", "tenant:clinic-b", "shared")


def test_preflight_counts_every_conflict_and_writes_nothing(ws) -> None:
    """The route's request-level guard: entity redefinition + a link over an
    existing shared edge + an endpoint in another tenant = 3, nothing written."""
    _cypher(f"CREATE (:`{ws}` {{entity_id:'B-PRIVATE', scope:'tenant:clinic-b'}})")
    before = _cypher(f"MATCH (n:`{ws}`) OPTIONAL MATCH (n)-[r]-() RETURN count(DISTINCT n) AS n, count(DISTINCT r) AS r")

    async def run():
        rag = LightRAG(working_dir=tempfile.mkdtemp(), workspace=ws, graph_storage="ScopedNeo4JStorage",
                       embedding_func=EmbeddingFunc(embedding_dim=8, max_token_size=512, func=_embed),
                       llm_model_func=_llm)
        await rag.initialize_storages()
        try:
            graph = rag.chunk_entity_relation_graph
            bad = await graph.preflight_custom_kg(
                ["CURCUMIN", "NEW-A"], [("NFKB1", "CURCUMIN"), ("NEW-A", "B-PRIVATE")], TENANT)
            ok = await graph.preflight_custom_kg(["NEW-A"], [("NEW-A", "CURCUMIN")], TENANT)
            return bad, ok
        finally:
            await rag.finalize_storages()
    bad, ok = asyncio.run(run())
    assert (bad, ok) == (3, 0)
    after = _cypher(f"MATCH (n:`{ws}`) OPTIONAL MATCH (n)-[r]-() RETURN count(DISTINCT n) AS n, count(DISTINCT r) AS r")
    assert after == before


def test_concurrent_writers_of_one_new_id_cannot_both_win_under_a_uniqueness_constraint(ws) -> None:
    """The guard->write race (code reviewer, measured 29/30 duplicates before):
    with the conditional write and a uniqueness constraint, exactly ONE scope
    ends up owning the id and the other writer is refused."""
    cname = f"uniq_{ws}"
    _cypher(f"CREATE CONSTRAINT {cname} IF NOT EXISTS FOR (n:`{ws}`) REQUIRE n.entity_id IS UNIQUE")
    try:
        async def run():
            rag = LightRAG(working_dir=tempfile.mkdtemp(), workspace=ws, graph_storage="ScopedNeo4JStorage",
                           embedding_func=EmbeddingFunc(embedding_dim=8, max_token_size=512, func=_embed),
                           llm_model_func=_llm)
            await rag.initialize_storages()
            graph = rag.chunk_entity_relation_graph

            async def write(scope):
                token = set_write_scope(scope)
                try:
                    await graph.upsert_nodes_batch([("RACE", {"entity_id": "RACE", "description": scope})])
                    return "ok"
                except ScopeConflictError:
                    return "refused"
                except Exception as e:  # constraint violation surfaced by the driver
                    return f"error:{type(e).__name__}"
                finally:
                    reset_write_scope(token)
            try:
                outcomes = []
                for _ in range(10):
                    _cypher(f"MATCH (n:`{ws}` {{entity_id:'RACE'}}) DETACH DELETE n")
                    outcomes.append(await asyncio.gather(write(TENANT), write("shared")))
                    rows = _cypher(f"MATCH (n:`{ws}` {{entity_id:'RACE'}}) RETURN n.scope AS scope, n.description AS description")
                    assert len(rows) == 1, rows
                    assert rows[0]["scope"] == rows[0]["description"], rows   # props only from the owning scope
                return outcomes
            finally:
                await rag.finalize_storages()
        outcomes = asyncio.run(run())
        # Exactly one writer wins each round; the other is refused (or rejected
        # by the constraint). Two "ok"s would mean the loser's MERGE matched the
        # winner's committed node and overwrote it — the #113 defect via a race.
        for pair in outcomes:
            assert pair.count("ok") == 1, outcomes
    finally:
        _cypher(f"DROP CONSTRAINT {cname} IF EXISTS")


# ─── each remaining layer pinned on its own (so no layer hides behind another) ─


def _graph_call(label: str, scope: str | None, fn):
    async def run():
        rag = LightRAG(working_dir=tempfile.mkdtemp(), workspace=label, graph_storage="ScopedNeo4JStorage",
                       embedding_func=EmbeddingFunc(embedding_dim=8, max_token_size=512, func=_embed),
                       llm_model_func=_llm)
        await rag.initialize_storages()
        token = set_write_scope(scope) if scope else None
        try:
            return await fn(rag.chunk_entity_relation_graph)
        finally:
            if token is not None:
                reset_write_scope(token)
            await rag.finalize_storages()
    return asyncio.run(run())


def test_edge_endpoint_guard_alone_refuses_a_cross_tenant_edge(ws) -> None:
    """Direct storage call — no ainsert_custom_kg, no existence check in front.
    Without the endpoint guard the undirected MERGE would CREATE this edge."""
    _cypher(f"CREATE (:`{ws}` {{entity_id:'A-OWN', scope:'{TENANT}'}})")
    _cypher(f"CREATE (:`{ws}` {{entity_id:'B-PRIVATE', scope:'tenant:clinic-b'}})")
    with pytest.raises(ScopeConflictError):
        _graph_call(ws, TENANT, lambda g: g.upsert_edges_batch([("A-OWN", "B-PRIVATE", {"description": "x"})]))
    with pytest.raises(ScopeConflictError):  # and a SHARED edge may not reference a tenant node
        _graph_call(ws, None, lambda g: g.upsert_edges_batch([("CURCUMIN", "A-OWN", {"description": "y"})]))
    assert _cypher(f"MATCH (:`{ws}` {{entity_id:'B-PRIVATE'}})-[r]-() RETURN count(r) AS c")[0]["c"] == 0
    assert _cypher(f"MATCH (:`{ws}` {{entity_id:'A-OWN'}})-[r]-() RETURN count(r) AS c")[0]["c"] == 0


def test_existence_check_is_scoped_to_the_writer(ws) -> None:
    _cypher(f"CREATE (:`{ws}` {{entity_id:'MINE', scope:'{TENANT}'}})")
    _cypher(f"CREATE (:`{ws}` {{entity_id:'THEIRS', scope:'tenant:clinic-b'}})")
    ids = ["CURCUMIN", "MINE", "THEIRS", "ABSENT"]
    assert _graph_call(ws, TENANT, lambda g: g.has_nodes_batch(ids)) == {"CURCUMIN", "MINE"}
    assert _graph_call(ws, None, lambda g: g.has_nodes_batch(ids)) == {"CURCUMIN"}
