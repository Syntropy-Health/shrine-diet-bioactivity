"""
Tenant-scoped Neo4j storage for LightRAG.

Subclasses ``lightrag.kg.neo4j_impl.Neo4JStorage`` and overrides every
read method to inject ``WHERE <n>.scope IN $scope_filter`` (plus
matching predicates on edge / endpoint scope). Writes are **not**
filtered — tenant ingestion must be able to insert new tenant-scoped
nodes and edges.

Scope filter comes from :mod:`scope_context` (a ``ContextVar`` set by
``scoped_server.py`` per request). Default is ``("shared",)`` — missing
context falls back to the public KG.

Register via LightRAG constructor::

    from lightrag import LightRAG
    from scoped_neo4j_storage import ScopedNeo4JStorage

    rag = LightRAG(graph_storage="ScopedNeo4JStorage", ...)

Or by directly passing the class if your LightRAG version supports it.

Filter semantics (for every read):

- Node reads: ``n.scope IN $scope_filter``
- Edge reads: ``start.scope IN $scope_filter``
    ``AND end.scope IN $scope_filter``
    ``AND r.scope IN $scope_filter``
- Node-degree / node-edges: connected nodes *and* relationships filtered

Writes (``upsert_node``, ``upsert_edge``, ``delete_*``) are inherited
unchanged — the tenant ingestion API is responsible for stamping
``scope="tenant:<id>"`` on the payload it submits.
"""

from __future__ import annotations

from typing import Any

from lightrag.kg.neo4j_impl import READ_RETRY, Neo4JStorage
from lightrag.types import KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode
from lightrag.utils import logger

from cypher_fragments import (
    hop_query,
    nodes_by_ids_query,
    resolve_exact_query,
    resolve_scan_query,
    wildcard_count_query,
    wildcard_edges_query,
    wildcard_top_query,
)
from scope_context import DEFAULT_SCOPE, get_scope_filter

# The scope stamped on writes that arrive WITHOUT an explicit scope. Open-corpus
# ingest (LightRAG semantic extraction) has no tenant, so it is shared — matching
# scope_context.DEFAULT_SCOPE and the 'shared' vector nodes ScopedNeo4JVectorStorage
# writes. Single source of truth so the two paths cannot drift.
WRITE_SCOPE_DEFAULT: str = DEFAULT_SCOPE[0]


class ScopedNeo4JStorage(Neo4JStorage):
    """Neo4JStorage with WHERE-clause tenant filtering on all reads; the
    subgraph explorer (``get_knowledge_graph``) is a scoped BFS built here, not
    a filter over upstream's."""

    # ------------------------------------------------------------------
    # Writes — stamp scope at WRITE time.
    #
    # The parent Neo4JStorage writes node_data/edge_data verbatim, and this
    # subclass filters only READS — so LightRAG's semantic ingest wrote
    # ``DIRECTED`` edges with no ``scope`` property, which the scoped_server
    # boot preflight then refuses (shrine-diet #103: 35,092 unscoped DIRECTED
    # edges crash-looped the container). A one-time bootstrap backfills legacy
    # rows; THIS is the durable fix — every edge/node is BORN scoped.
    #
    # Respect an explicit ``scope`` already on the payload (tenant ingestion
    # sets ``scope='tenant:<id>'``); otherwise default to 'shared'. A new dict
    # is built so the caller's dict is never mutated. This does NOT touch the
    # preflight — that fail-closed control stays exactly as-is.
    # ------------------------------------------------------------------
    async def upsert_node(self, node_id: str, node_data: dict[str, str]) -> None:
        scoped = {**node_data, "scope": (node_data.get("scope") or WRITE_SCOPE_DEFAULT)}
        await super().upsert_node(node_id, scoped)

    async def upsert_edge(
        self, source_node_id: str, target_node_id: str, edge_data: dict[str, str]
    ) -> None:
        scoped = {**edge_data, "scope": (edge_data.get("scope") or WRITE_SCOPE_DEFAULT)}
        await super().upsert_edge(source_node_id, target_node_id, scoped)

    # ------------------------------------------------------------------
    # Node reads
    # ------------------------------------------------------------------

    @READ_RETRY
    async def get_node(self, node_id: str) -> dict[str, str] | None:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            try:
                query = (
                    f"MATCH (n:`{workspace_label}` {{entity_id: $entity_id}}) "
                    f"WHERE n.scope IN $scope_filter "
                    f"RETURN n"
                )
                result = await session.run(
                    query, entity_id=node_id, scope_filter=scopes
                )
                try:
                    records = await result.fetch(2)
                    if len(records) > 1:
                        logger.warning(
                            f"[{self.workspace}] Multiple nodes with label "
                            f"'{node_id}'. Using first."
                        )
                    if not records:
                        return None
                    node_dict = dict(records[0]["n"])
                    if "labels" in node_dict:
                        node_dict["labels"] = [
                            label
                            for label in node_dict["labels"]
                            if label != workspace_label
                        ]
                    return node_dict
                finally:
                    await result.consume()
            except Exception as e:
                logger.error(
                    f"[{self.workspace}] Error getting node '{node_id}': {e}"
                )
                raise

    @READ_RETRY
    async def get_nodes_batch(
        self, node_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $node_ids AS id
            MATCH (n:`{workspace_label}` {{entity_id: id}})
            WHERE n.scope IN $scope_filter
            RETURN n.entity_id AS entity_id, n
            """
            result = await session.run(
                query, node_ids=node_ids, scope_filter=scopes
            )
            nodes: dict[str, dict[str, Any]] = {}
            async for record in result:
                entity_id = record["entity_id"]
                node_dict = dict(record["n"])
                if "labels" in node_dict:
                    node_dict["labels"] = [
                        label
                        for label in node_dict["labels"]
                        if label != workspace_label
                    ]
                nodes[entity_id] = node_dict
            await result.consume()
            return nodes

    @READ_RETRY
    async def node_degree(self, node_id: str) -> int:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            try:
                query = f"""
                MATCH (n:`{workspace_label}` {{entity_id: $entity_id}})
                WHERE n.scope IN $scope_filter
                OPTIONAL MATCH (n)-[r]-(m)
                WHERE r.scope IN $scope_filter
                  AND m.scope IN $scope_filter
                RETURN COUNT(r) AS degree
                """
                result = await session.run(
                    query, entity_id=node_id, scope_filter=scopes
                )
                try:
                    record = await result.single()
                    if not record:
                        return 0
                    return int(record["degree"])
                finally:
                    await result.consume()
            except Exception as e:
                logger.error(
                    f"[{self.workspace}] Error getting degree for '{node_id}': {e}"
                )
                raise

    @READ_RETRY
    async def node_degrees_batch(self, node_ids: list[str]) -> dict[str, int]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $node_ids AS id
            MATCH (n:`{workspace_label}` {{entity_id: id}})
            WHERE n.scope IN $scope_filter
            OPTIONAL MATCH (n)-[r]-(m)
            WHERE r.scope IN $scope_filter AND m.scope IN $scope_filter
            RETURN n.entity_id AS entity_id, COUNT(r) AS degree
            """
            result = await session.run(
                query, node_ids=node_ids, scope_filter=scopes
            )
            degrees: dict[str, int] = {}
            async for record in result:
                degrees[record["entity_id"]] = int(record["degree"])
            await result.consume()
            for nid in node_ids:
                degrees.setdefault(nid, 0)
            return degrees

    # ------------------------------------------------------------------
    # Edge reads
    # ------------------------------------------------------------------

    @READ_RETRY
    async def get_edge(
        self, source_node_id: str, target_node_id: str
    ) -> dict[str, str] | None:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        try:
            async with self._driver.session(
                database=self._DATABASE, default_access_mode="READ"
            ) as session:
                query = f"""
                MATCH (start:`{workspace_label}` {{entity_id: $src}})
                      -[r]-
                      (end:`{workspace_label}` {{entity_id: $tgt}})
                WHERE start.scope IN $scope_filter
                  AND end.scope IN $scope_filter
                  AND r.scope IN $scope_filter
                RETURN properties(r) AS edge_properties
                """
                result = await session.run(
                    query,
                    src=source_node_id,
                    tgt=target_node_id,
                    scope_filter=scopes,
                )
                try:
                    records = await result.fetch(2)
                    if len(records) > 1:
                        logger.warning(
                            f"[{self.workspace}] Multiple edges "
                            f"'{source_node_id}' → '{target_node_id}'. Using first."
                        )
                    if not records:
                        return None
                    edge_result = dict(records[0]["edge_properties"])
                    defaults = {
                        "weight": 1.0,
                        "source_id": None,
                        "description": None,
                        "keywords": None,
                    }
                    for k, v in defaults.items():
                        edge_result.setdefault(k, v)
                    return edge_result
                finally:
                    await result.consume()
        except Exception as e:
            logger.error(
                f"[{self.workspace}] Error getting edge "
                f"'{source_node_id}' → '{target_node_id}': {e}"
            )
            raise

    @READ_RETRY
    async def get_edges_batch(
        self, pairs: list[dict[str, str]]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $pairs AS pair
            MATCH (start:`{workspace_label}` {{entity_id: pair.src}})
                  -[r]-
                  (end:`{workspace_label}` {{entity_id: pair.tgt}})
            WHERE start.scope IN $scope_filter
              AND end.scope IN $scope_filter
              AND r.scope IN $scope_filter
            RETURN pair.src AS src, pair.tgt AS tgt,
                   properties(r) AS edge_properties
            """
            payload = [{"src": p["src"], "tgt": p["tgt"]} for p in pairs]
            result = await session.run(
                query, pairs=payload, scope_filter=scopes
            )
            edges: dict[tuple[str, str], dict[str, Any]] = {}
            async for record in result:
                edges[(record["src"], record["tgt"])] = dict(
                    record["edge_properties"]
                )
            await result.consume()
            return edges

    @READ_RETRY
    async def get_node_edges(
        self, source_node_id: str
    ) -> list[tuple[str, str]] | None:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            MATCH (n:`{workspace_label}` {{entity_id: $entity_id}})
                  -[r]-
                  (m:`{workspace_label}`)
            WHERE n.scope IN $scope_filter
              AND m.scope IN $scope_filter
              AND r.scope IN $scope_filter
            RETURN n.entity_id AS src, m.entity_id AS tgt
            """
            result = await session.run(
                query, entity_id=source_node_id, scope_filter=scopes
            )
            edges: list[tuple[str, str]] = []
            async for record in result:
                edges.append((record["src"], record["tgt"]))
            await result.consume()
            return edges if edges else None

    @READ_RETRY
    async def get_nodes_edges_batch(
        self, node_ids: list[str]
    ) -> dict[str, list[tuple[str, str]]]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $node_ids AS id
            MATCH (n:`{workspace_label}` {{entity_id: id}})
                  -[r]-
                  (m:`{workspace_label}`)
            WHERE n.scope IN $scope_filter
              AND m.scope IN $scope_filter
              AND r.scope IN $scope_filter
            RETURN id AS src_id, m.entity_id AS tgt_id
            """
            result = await session.run(
                query, node_ids=node_ids, scope_filter=scopes
            )
            out: dict[str, list[tuple[str, str]]] = {nid: [] for nid in node_ids}
            async for record in result:
                out[record["src_id"]].append(
                    (record["src_id"], record["tgt_id"])
                )
            await result.consume()
            return out

    # ------------------------------------------------------------------
    # Label enumeration
    # ------------------------------------------------------------------

    @READ_RETRY
    async def get_all_labels(self) -> list[str]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            MATCH (n:`{workspace_label}`)
            WHERE n.scope IN $scope_filter
            RETURN DISTINCT n.entity_id AS entity_id
            ORDER BY entity_id
            """
            result = await session.run(query, scope_filter=scopes)
            labels: list[str] = []
            async for record in result:
                if record["entity_id"]:
                    labels.append(record["entity_id"])
            await result.consume()
            return labels


    # ------------------------------------------------------------------
    # Subgraph explorer — GET /graphs passthrough (shrine-diet #6).
    #
    # Upstream ``Neo4JStorage.get_knowledge_graph`` (lightrag-hku 1.5.0) is
    # NOT called. It (1) matches the start node on EXACT ``entity_id`` —
    # "curcumin" misses "CURCUMIN", names/aliases/CIDs never match — and
    # (2) runs an APOC BFS filtered on the WORKSPACE label only, so it walks
    # THROUGH tenant nodes: a post-filter can drop them but cannot undo that
    # the walk reached shared nodes via tenant paths (an inference channel),
    # spent ``max_depth``/``max_nodes`` on tenant hops, and computed
    # ``is_truncated`` over tenant nodes (a counting oracle). QG findings
    # reviewer-code / -security / -design, all P2, one root cause.
    #
    # So the traversal itself is scoped: a per-level BFS whose every hop
    # requires ``a.scope``, ``r.scope`` AND ``b.scope`` in the caller's scope
    # filter (query text in ``cypher_fragments``, proven against Aura by
    # ``tests/test_graphs_scoped_cypher_aura.py``). Every returned node is the
    # seed or reached from it over in-scope edges; the node budget counts only
    # in-scope nodes; ``is_truncated`` means "in-scope neighbours were left
    # out". Node ids are ``entity_id`` (what every other tool keys on).
    # ------------------------------------------------------------------
    async def get_knowledge_graph(
        self,
        node_label: str,
        max_depth: int = 3,
        max_nodes: int = 1000,
    ) -> KnowledgeGraph:
        scopes = get_scope_filter()
        if node_label == "*":
            return await self._scoped_wildcard(max_nodes, scopes)
        resolved = await self._resolve_seed_in_scope(node_label, scopes)
        if resolved is None:
            logger.info(
                f"[{self.workspace}] get_knowledge_graph: seed {node_label!r} "
                f"resolves to no node in scope {scopes} — returning empty graph"
            )
            return KnowledgeGraph()
        return await self._scoped_subgraph(resolved, max_depth, max_nodes, scopes)

    async def _resolve_seed_in_scope(self, seed: str, scopes: list[str]) -> str | None:
        """Map a user-supplied seed to ONE canonical ``entity_id`` within scope:
        an index-served exact lookup first, the Phase-0/2 predicate scan only on
        a miss. ``/traverse`` uses the same predicate but fans out over EVERY
        match; a neighborhood has one centre, so this picks one (see
        ``cypher_fragments.resolve_scan_query`` for the ordering)."""
        workspace_label = self._get_workspace_label()
        for query in (resolve_exact_query(workspace_label), resolve_scan_query(workspace_label)):
            entity_id = await self._first_entity_id(query, seed=seed, scope_filter=scopes)
            if entity_id:
                return entity_id
        return None

    async def _first_entity_id(self, query: str, **params: Any) -> str | None:
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            result = await session.run(query, **params)
            try:
                records = await result.fetch(1)
            finally:
                await result.consume()
        if not records:
            return None
        value = records[0]["entity_id"]
        return str(value) if value else None

    async def _scoped_subgraph(
        self, seed_id: str, max_depth: int, max_nodes: int, scopes: list[str]
    ) -> KnowledgeGraph:
        """Breadth-first expansion from ``seed_id`` over IN-SCOPE hops only.

        One round-trip per level (``max_depth`` <= 5 at the endpoint). Edges
        are keyed by ``elementId(r)`` so an undirected match seen from both
        ends counts once; direction comes from ``startNode(r)``, never from
        traversal order. A node beyond the budget is not admitted and neither
        is the edge that reached it, so the result is a connected, in-scope,
        budget-honest subgraph and ``is_truncated`` reports only in-scope loss.
        """
        workspace_label = self._get_workspace_label()
        query = hop_query(workspace_label)
        visited: set[str] = {seed_id}
        order: list[str] = [seed_id]
        edges: dict[str, KnowledgeGraphEdge] = {}
        truncated = False
        frontier: list[str] = [seed_id]
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            for _level in range(max_depth):
                if not frontier:
                    break
                result = await session.run(query, frontier=frontier, scope_filter=scopes)
                next_frontier: list[str] = []
                async for rec in result:
                    here, src, tgt = str(rec["here"]), str(rec["src"]), str(rec["tgt"])
                    other = tgt if src == here else src
                    if other not in visited:
                        if len(visited) >= max_nodes:
                            truncated = True
                            continue  # neither the node nor its edge is admitted
                        visited.add(other)
                        order.append(other)
                        next_frontier.append(other)
                    rid = str(rec["rid"])
                    if rid not in edges:
                        edges[rid] = KnowledgeGraphEdge(
                            id=rid,
                            type=rec["rel_type"],
                            source=src,
                            target=tgt,
                            properties=dict(rec["props"] or {}),
                        )
                await result.consume()
                frontier = next_frontier
            nodes = await self._nodes_by_entity_id(session, order, scopes, workspace_label)
        present = {n.id for n in nodes}
        kept_edges = [e for e in edges.values() if e.source in present and e.target in present]
        return KnowledgeGraph(nodes=nodes, edges=kept_edges, is_truncated=truncated)

    async def _nodes_by_entity_id(
        self, session: Any, ids: list[str], scopes: list[str], workspace_label: str
    ) -> list[KnowledgeGraphNode]:
        """Materialise nodes in ``ids`` order; ``labels`` drop the workspace tag."""
        if not ids:
            return []
        result = await session.run(nodes_by_ids_query(workspace_label), ids=ids, scope_filter=scopes)
        by_id: dict[str, KnowledgeGraphNode] = {}
        async for rec in result:
            eid = str(rec["entity_id"])
            by_id[eid] = KnowledgeGraphNode(
                id=eid,
                labels=[lb for lb in (rec["labels"] or []) if lb != workspace_label],
                properties=dict(rec["props"] or {}),
            )
        await result.consume()
        return [by_id[i] for i in ids if i in by_id]

    async def _scoped_wildcard(self, max_nodes: int, scopes: list[str]) -> KnowledgeGraph:
        """``label='*'``: the ``max_nodes`` highest-degree IN-SCOPE nodes (degree
        over in-scope edges to in-scope neighbours) plus the in-scope edges among
        them. ``is_truncated`` compares against the in-scope node count, never
        the workspace total (upstream ranked and counted across every tenant)."""
        workspace_label = self._get_workspace_label()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            result = await session.run(wildcard_count_query(workspace_label), scope_filter=scopes)
            rec = await result.single()
            total = int(rec["total"]) if rec else 0
            await result.consume()
            result = await session.run(
                wildcard_top_query(workspace_label), scope_filter=scopes, max_nodes=max_nodes
            )
            nodes: list[KnowledgeGraphNode] = []
            async for r in result:
                nodes.append(
                    KnowledgeGraphNode(
                        id=str(r["entity_id"]),
                        labels=[lb for lb in (r["labels"] or []) if lb != workspace_label],
                        properties=dict(r["props"] or {}),
                    )
                )
            await result.consume()
            ids = [n.id for n in nodes]
            edges: list[KnowledgeGraphEdge] = []
            if ids:
                result = await session.run(
                    wildcard_edges_query(workspace_label), ids=ids, scope_filter=scopes
                )
                async for r in result:
                    edges.append(
                        KnowledgeGraphEdge(
                            id=str(r["rid"]), type=r["rel_type"], source=str(r["src"]),
                            target=str(r["tgt"]), properties=dict(r["props"] or {}),
                        )
                    )
                await result.consume()
        return KnowledgeGraph(nodes=nodes, edges=edges, is_truncated=total > len(nodes))

# ---------------------------------------------------------------------------
# Register with upstream LightRAG's storage-compatibility whitelist and the
# STORAGES import-path map.
#
# LightRAG uses two separate dicts:
#   1. ``STORAGE_IMPLEMENTATIONS`` — verify_storage_implementation() check
#   2. ``STORAGES`` — _get_storage_class() dynamic-import resolution
#
# Both must know about our class for LightRAG(graph_storage=
# "ScopedNeo4JStorage") to succeed without touching the submodule.
# ---------------------------------------------------------------------------
try:
    from lightrag.kg import (  # type: ignore[import]
        STORAGE_IMPLEMENTATIONS as _STORAGE_IMPLEMENTATIONS,
        STORAGES as _STORAGES,
    )

    # 1. Compatibility whitelist
    _graph = _STORAGE_IMPLEMENTATIONS.get("GRAPH_STORAGE", {})
    _impls = _graph.get("implementations")
    if isinstance(_impls, list) and "ScopedNeo4JStorage" not in _impls:
        _impls.append("ScopedNeo4JStorage")

    # 2. Import-path map
    if "ScopedNeo4JStorage" not in _STORAGES:
        _STORAGES["ScopedNeo4JStorage"] = "scoped_neo4j_storage"
except (ImportError, KeyError, AttributeError):
    # Upstream LightRAG not importable or dict shape changed — tolerate silently.
    pass
