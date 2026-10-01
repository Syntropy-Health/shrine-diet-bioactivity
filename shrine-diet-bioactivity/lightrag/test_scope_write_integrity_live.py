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
