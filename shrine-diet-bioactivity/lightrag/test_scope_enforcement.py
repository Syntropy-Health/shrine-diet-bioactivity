"""
Scope-enforcement tests.

Two layers:

* **Unit** (always run) — Cypher-generation + ContextVar propagation
  against a fake async Neo4j driver. No network.
* **Integration** (``LIGHTRAG_RUN_INTEGRATION=true`` required) — real
  Neo4j; verifies that scope_filter actually hides cross-tenant data.

The integration path runs the same logic as ``canary_smoke_test.py``
but from within pytest so CI can assert exit status + artifact shape.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from scope_context import (
    DEFAULT_SCOPE,
    get_scope_filter,
    reset_scope_filter,
    set_scope_filter,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Fake async Neo4j driver — records every (cypher, params) tuple executed.
# ---------------------------------------------------------------------------


@dataclass
class _FakeRecord:
    data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


class _FakeAsyncResult:
    def __init__(self, records: list[_FakeRecord] | None = None) -> None:
        self._records = records or []

    async def fetch(self, n: int) -> list[_FakeRecord]:
        return self._records[:n]

    async def single(self) -> _FakeRecord | None:
        return self._records[0] if self._records else None

    async def consume(self) -> None:
        return None

    def __aiter__(self):
        async def gen():
            for r in self._records:
                yield r

        return gen()


class _FakeAsyncSession:
    def __init__(self, log: list[tuple[str, dict[str, Any]]]) -> None:
        self._log = log

    async def __aenter__(self) -> "_FakeAsyncSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def run(self, query: str, **params: Any) -> _FakeAsyncResult:
        self._log.append((query, params))
        return _FakeAsyncResult([])


class _FakeAsyncDriver:
    def __init__(self) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []

    def session(self, **_: Any) -> _FakeAsyncSession:
        return _FakeAsyncSession(self.log)


# ---------------------------------------------------------------------------
# Unit tests — verify every overridden method injects scope_filter.
# ---------------------------------------------------------------------------


def _make_scoped_storage() -> Any:
    """Build a ScopedNeo4JStorage without touching the real base __init__.

    We bypass ``Neo4JStorage.__init__`` (which expects real config) by
    constructing via ``__new__`` and hand-setting the attributes the
    overridden methods read.
    """
    from scoped_neo4j_storage import ScopedNeo4JStorage

    storage = ScopedNeo4JStorage.__new__(ScopedNeo4JStorage)
    storage._driver = _FakeAsyncDriver()
    storage._DATABASE = "neo4j"
    storage.workspace = "unified_diet_kg"
    storage._workspace_label_cache = "unified_diet_kg"
    return storage


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.unit
def test_get_node_injects_scope_filter_with_default() -> None:
    storage = _make_scoped_storage()
    # Ensure the class can locate _get_workspace_label — patch it.
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_node("some-entity"))

    driver = storage._driver
    assert driver.log, "no Cypher was executed"
    query, params = driver.log[0]
    assert "WHERE n.scope IN $scope_filter" in query
    assert params["scope_filter"] == list(DEFAULT_SCOPE)


@pytest.mark.unit
def test_get_node_uses_contextvar_override() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        _run(storage.get_node("entity-x"))
    finally:
        reset_scope_filter(token)

    _query, params = storage._driver.log[-1]
    assert params["scope_filter"] == ["shared", "tenant:clinic-a"]


@pytest.mark.unit
def test_get_edge_filters_both_endpoints_and_relationship() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_edge("a", "b"))

    query, _ = storage._driver.log[0]
    assert "start.scope IN $scope_filter" in query
    assert "end.scope IN $scope_filter" in query
    assert "r.scope IN $scope_filter" in query


@pytest.mark.unit
def test_node_degree_filters_connected_nodes_and_relationships() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.node_degree("entity-x"))

    query, _ = storage._driver.log[0]
    assert "n.scope IN $scope_filter" in query
    assert "r.scope IN $scope_filter" in query
    assert "m.scope IN $scope_filter" in query


@pytest.mark.unit
def test_get_nodes_batch_injects_scope_filter() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_nodes_batch(["a", "b"]))

    query, params = storage._driver.log[0]
    assert "UNWIND $node_ids" in query
    assert "WHERE n.scope IN $scope_filter" in query
    assert params["scope_filter"] == list(DEFAULT_SCOPE)
    assert params["node_ids"] == ["a", "b"]


@pytest.mark.unit
def test_get_node_edges_filters_all_three() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_node_edges("entity-x"))

    query, _ = storage._driver.log[0]
    for predicate in (
        "n.scope IN $scope_filter",
        "m.scope IN $scope_filter",
        "r.scope IN $scope_filter",
    ):
        assert predicate in query


@pytest.mark.unit
def test_get_all_labels_applies_scope_filter() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    _run(storage.get_all_labels())

    query, _ = storage._driver.log[0]
    assert "n.scope IN $scope_filter" in query


@pytest.mark.unit
def test_context_var_does_not_leak_across_calls() -> None:
    storage = _make_scoped_storage()
    storage._get_workspace_label = lambda: "unified_diet_kg"

    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        _run(storage.get_node("a"))
    finally:
        reset_scope_filter(token)

    _run(storage.get_node("b"))

    _, first_params = storage._driver.log[0]
    _, second_params = storage._driver.log[1]
    assert first_params["scope_filter"] == ["shared", "tenant:clinic-a"]
    assert second_params["scope_filter"] == list(DEFAULT_SCOPE)


# ---------------------------------------------------------------------------
# Integration — real Neo4j, real scoped_server (gated).
# ---------------------------------------------------------------------------

_RUN_INTEGRATION = os.environ.get("LIGHTRAG_RUN_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.mark.integration
@pytest.mark.skipif(
    not _RUN_INTEGRATION,
    reason="requires LIGHTRAG_RUN_INTEGRATION=true + live Neo4j + scoped_server",
)
def test_cross_tenant_canary_isolation(tmp_path) -> None:  # noqa: ARG001
    """End-to-end canary: insert as tenant:canary-a, query as tenant:canary-b,
    assert the sentinel id does not appear in the response text.

    Mirrors canary_smoke_test.py with the same cleanup guarantee.
    """
    import canary_smoke_test as canary

    config = os.environ.get("SHRINE_CONFIG", "local")
    canary._load_config(config)
    workspace_label = canary._safe_label(
        os.environ.get("WORKSPACE", "unified_diet_kg")
    )
    sentinel_id = f"canary-sentinel-{uuid.uuid4().hex[:8]}"
    server_url = os.environ.get("LIGHTRAG_API_URL", "http://localhost:9621")

    canary._insert_sentinel(workspace_label, sentinel_id)
    try:
        response_b = canary._query_as_tenant(server_url, "canary-b", sentinel_id)
        assert sentinel_id not in response_b, (
            f"sentinel leaked across tenants: {response_b[:400]}"
        )
    finally:
        canary._delete_sentinel(workspace_label, sentinel_id)


# ---------------------------------------------------------------------------
# get_knowledge_graph (shrine-diet #6): a SCOPED BFS built in the storage layer.
#
# The fake below is a tiny Cypher emulator keyed on the CLAUSES of the real
# query text (from cypher_fragments): a scope condition is only applied when
# its clause is present in the query the code sent. So deleting a clause from
# production Cypher changes what the fake returns — the suite is a mutation
# detector for the query text, not a mirror of it. What the fake cannot show
# (that Neo4j parses and honours the text) is covered by
# tests/test_graphs_scoped_cypher_aura.py against the real database.
# ---------------------------------------------------------------------------

WS = "unified_diet_kg"


def _lc(x):
    return str(x).lower()


class _GraphFakeSession:
    def __init__(self, graph: "_GraphFake") -> None:
        self.g = graph

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def _in_scope(self, node_id: str, scopes) -> bool:
        node = self.g.nodes.get(node_id)
        return node is not None and node.get("scope") in set(scopes)

    async def run(self, query: str, **params: Any) -> _FakeAsyncResult:
        self.g.log.append((query, params))
        sf = params.get("scope_filter", [])
        rows: list[dict[str, Any]] = []
        # Clause detection reads the WHERE part only — never RETURN/ORDER BY —
        # and a tautology anywhere disqualifies the query. (Scorer finding on
        # QG round 2: keyed on the whole text, `... OR true` and a case-sensitive
        # predicate both slipped past because the tokens survived elsewhere.)
        lowered = query.lower()
        if " or true" in lowered or " or 1=1" in lowered or "where true" in lowered:
            raise AssertionError(f"tautological scope clause in query: {query[:120]}")
        where = query.split(" RETURN ")[0]
        if "{entity_id: $seed}" in query:                                   # resolve_exact
            seed = params["seed"]
            if seed in self.g.nodes and ("n.scope IN $scope_filter" not in where or self._in_scope(seed, sf)):
                rows = [{"entity_id": seed}]
        elif "ORDER BY CASE WHEN toLower(n.entity_id)" in query:            # resolve_scan
            seed = params["seed"]
            cands = []
            for nid, n in self.g.nodes.items():
                pr = n.get("props", {})
                hit = (
                    ("toLower(n.entity_id) = toLower($seed)" in where and _lc(nid) == _lc(seed))
                    or ("n.entity_id = $seed" in where and nid == seed)          # a case-SENSITIVE mutant matches less
                    or ("coalesce(n.common_name" in where and _lc(pr.get("common_name", "")) == _lc(seed))
                    or ("n.aliases" in where and _lc(seed) in [_lc(a) for a in pr.get("aliases", [])])
                    or ("n.pubchem_cid" in where and pr.get("pubchem_cid") is not None and str(pr["pubchem_cid"]) == seed)
                )
                if hit and ("n.scope IN $scope_filter" not in where or self._in_scope(nid, sf)):
                    cands.append(nid)
            cands.sort(key=lambda i: (0 if _lc(i) == _lc(seed) else 1, i))
            rows = [{"entity_id": cands[0]}] if cands else []
        elif "AS here" in query:                                            # hop_query
            frontier = set(params["frontier"])
            for e in self.g.edges:
                for here in (e["src"], e["tgt"]):
                    if here not in frontier:
                        continue
                    other = e["tgt"] if here == e["src"] else e["src"]
                    if "a.scope IN $scope_filter" in where and not self._in_scope(here, sf):
                        continue
                    if "r.scope IN $scope_filter" in where and e.get("scope") not in set(sf):
                        continue
                    if "b.scope IN $scope_filter" in where and not self._in_scope(other, sf):
                        continue
                    props = {"scope": e["scope"]} if e.get("scope") is not None else {}
                    rows.append({"here": here, "rid": e["rid"], "rel_type": e["type"],
                                 "src": e["src"], "tgt": e["tgt"], "props": props})
        elif "labels(n) AS labels" in query and "n.entity_id IN $ids" in query:  # nodes_by_ids
            for nid in params["ids"]:
                n = self.g.nodes.get(nid)
                if n is None:
                    continue
                if "n.scope IN $scope_filter" in where and not self._in_scope(nid, sf):
                    continue
                rows.append({"entity_id": nid, "labels": [WS] + n.get("labels", []), "props": self.g.props_of(nid)})
        elif "count(n) AS total" in query:                                  # wildcard_count
            rows = [{"total": sum(1 for nid in self.g.nodes if self._in_scope(nid, sf))}]
        elif "AS degree" in query:                                          # wildcard_top
            scored = []
            for nid in self.g.nodes:
                if not self._in_scope(nid, sf):
                    continue
                deg = sum(
                    1 for e in self.g.edges
                    if nid in (e["src"], e["tgt"]) and e.get("scope") in set(sf)
                    and self._in_scope(e["tgt"] if nid == e["src"] else e["src"], sf)
                )
                scored.append((-deg, nid))
            scored.sort()
            for _d, nid in scored[: params["max_nodes"]]:
                rows.append({"entity_id": nid, "labels": [WS] + self.g.nodes[nid].get("labels", []), "props": self.g.props_of(nid)})
        elif "a.entity_id IN $ids AND b.entity_id IN $ids" in query:        # wildcard_edges
            ids = set(params["ids"])
            for e in self.g.edges:
                if e["src"] in ids and e["tgt"] in ids and e.get("scope") in set(sf) \
                        and self._in_scope(e["src"], sf) and self._in_scope(e["tgt"], sf):
                    rows.append({"rid": e["rid"], "rel_type": e["type"], "src": e["src"], "tgt": e["tgt"], "props": {"scope": e["scope"]}})
        else:
            raise AssertionError(f"fake got an unrecognised query: {query[:80]}")
        return _FakeAsyncResult([_FakeRecord(r) for r in rows])


class _GraphFake:
    """In-memory graph. nodes: id -> {scope, labels, props}; edges: dicts."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.log: list[tuple[str, dict[str, Any]]] = []

    def node(self, nid: str, scope: str | None, **props: Any) -> "_GraphFake":
        self.nodes[nid] = {"scope": scope, "labels": ["Compound"], "props": props}
        return self

    def edge(self, rid: str, src: str, tgt: str, scope: str | None, typ: str = "DIRECTED") -> "_GraphFake":
        self.edges.append({"rid": rid, "src": src, "tgt": tgt, "scope": scope, "type": typ})
        return self

    def props_of(self, nid: str) -> dict[str, Any]:
        n = self.nodes[nid]
        out = {"entity_id": nid, **n.get("props", {})}
        if n.get("scope") is not None:
            out["scope"] = n["scope"]
        return out

    def session(self, **_: Any) -> _GraphFakeSession:
        return _GraphFakeSession(self)

    def queries(self, marker: str) -> list[tuple[str, dict[str, Any]]]:
        return [(q, p) for q, p in self.log if marker in q]


def _fixture_graph() -> _GraphFake:
    g = _GraphFake()
    (g.node("CURCUMIN", "shared", pubchem_cid=969516, common_name="Turmeric extract")
      .node("Curcumin", "shared")                       # case homonym, exists on Aura too
      .node("NFKB1", "shared")
      .node("TWO-HOPS", "shared")
      .node("INBOUND-SRC", "shared")
      .node("CLINIC-A-NOTE", "tenant:clinic-a")
      .node("SHARED-BEHIND-TENANT", "shared")
      .node("SHARED-VIA-TENANT-EDGE", "shared")
      .node("UNSCOPED", None)
      .node("TENANT-ONLY-SEED", "tenant:clinic-a")
      .node("QUERCETIN", "shared", aliases=["quercetol"]))
    (g.edge("e1", "CURCUMIN", "NFKB1", "shared")
      .edge("e2", "CURCUMIN", "CLINIC-A-NOTE", "shared")             # in-scope edge to a TENANT node
      .edge("e3", "CLINIC-A-NOTE", "SHARED-BEHIND-TENANT", "shared") # shared node only via tenant
      .edge("e4", "CURCUMIN", "SHARED-VIA-TENANT-EDGE", "tenant:clinic-a")  # shared node via TENANT edge
      .edge("e5", "CURCUMIN", "UNSCOPED", "shared")                  # neighbour with NO scope
      .edge("e6", "INBOUND-SRC", "CURCUMIN", "shared")               # inbound: direction must survive
      .edge("e7", "NFKB1", "TWO-HOPS", "shared")
      .edge("e8", "CURCUMIN", "Curcumin", "shared"))
    return g


def _storage_over(g: _GraphFake):
    storage = _make_scoped_storage()
    storage._driver = g
    storage._get_workspace_label = lambda: WS
    return storage


def _ids(graph) -> list[str]:
    return sorted(n.id for n in graph.nodes)


def _eids(graph) -> list[str]:
    return sorted(e.id for e in graph.edges)


@pytest.mark.unit
def test_registration_with_lightrag_survives_import() -> None:
    """QG P0 (reviewer-test): an earlier edit silently deleted the registration
    block and every test stayed green. Pin it."""
    import scoped_neo4j_storage  # noqa: F401  (import performs the registration)
    import lightrag.kg as kg

    assert kg.STORAGES.get("ScopedNeo4JStorage") == "scoped_neo4j_storage"
    assert "ScopedNeo4JStorage" in kg.STORAGE_IMPLEMENTATIONS["GRAPH_STORAGE"]["implementations"]


@pytest.mark.unit
def test_resolve_exact_id_uses_only_the_indexed_lookup() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    out = _run(st.get_knowledge_graph("CURCUMIN", max_depth=0))
    assert [n.id for n in out.nodes] == ["CURCUMIN"]
    assert len(g.queries("{entity_id: $seed}")) == 1
    assert g.queries("ORDER BY CASE WHEN toLower(n.entity_id)") == [], "no scan on an exact hit"
    q, params = g.queries("{entity_id: $seed}")[0]
    assert params["seed"] == "CURCUMIN" and params["scope_filter"] == list(DEFAULT_SCOPE)
    assert "CURCUMIN" not in q, "seed must be a parameter, never interpolated"


@pytest.mark.unit
def test_resolve_case_fold_is_deterministic_and_exact_wins() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    assert _run(st._resolve_seed_in_scope("curcumin", ["shared"])) == "CURCUMIN"   # tie -> entity_id order
    assert _run(st._resolve_seed_in_scope("Curcumin", ["shared"])) == "Curcumin"   # exact beats case-fold
    assert _run(st._resolve_seed_in_scope("CURCUMIN", ["shared"])) == "CURCUMIN"


@pytest.mark.unit
def test_resolve_via_common_name_alias_and_pubchem_cid() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    assert _run(st._resolve_seed_in_scope("turmeric EXTRACT", ["shared"])) == "CURCUMIN"
    assert _run(st._resolve_seed_in_scope("Quercetol", ["shared"])) == "QUERCETIN"
    assert _run(st._resolve_seed_in_scope("969516", ["shared"])) == "CURCUMIN"


@pytest.mark.unit
def test_tenant_only_seed_is_invisible_under_shared_and_runs_no_traversal() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    out = _run(st.get_knowledge_graph("TENANT-ONLY-SEED"))
    assert out.nodes == [] and out.edges == [] and out.is_truncated is False
    assert g.queries("AS here") == [], "no hop query for an unresolvable seed"
    # the same seed IS visible to its own tenant — proves the resolve step reads the scope
    g2 = _fixture_graph(); st2 = _storage_over(g2)
    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        out2 = _run(st2.get_knowledge_graph("tenant-only-seed", max_depth=0))
    finally:
        reset_scope_filter(token)
    assert [n.id for n in out2.nodes] == ["TENANT-ONLY-SEED"]
    assert g2.queries("ORDER BY CASE")[0][1]["scope_filter"] == ["shared", "tenant:clinic-a"]


@pytest.mark.unit
def test_bfs_under_shared_never_walks_through_tenant_or_unscoped_rows() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    out = _run(st.get_knowledge_graph("curcumin", max_depth=2, max_nodes=50))
    assert _ids(out) == ["CURCUMIN", "Curcumin", "INBOUND-SRC", "NFKB1", "TWO-HOPS"]
    assert _eids(out) == ["e1", "e6", "e7", "e8"]
    # direction is the relationship's, not the traversal's
    e6 = next(e for e in out.edges if e.id == "e6")
    assert (e6.source, e6.target) == ("INBOUND-SRC", "CURCUMIN")
    # the hop Cypher carries all three scope conditions and parameterises the frontier
    hop_q, hop_p = g.queries("AS here")[0]
    for clause in ("a.scope IN $scope_filter", "r.scope IN $scope_filter", "b.scope IN $scope_filter"):
        assert clause in hop_q
    assert hop_p["frontier"] == ["CURCUMIN"] and "CURCUMIN" not in hop_q
    assert out.is_truncated is False
    # ids are entity_ids, labels drop the workspace tag, scope rides in properties
    seed = next(n for n in out.nodes if n.id == "CURCUMIN")
    assert WS not in seed.labels and seed.properties["scope"] == "shared"


@pytest.mark.unit
def test_bfs_scope_is_differential() -> None:
    """Widening the scope must CHANGE the answer: tenant node, shared-behind-tenant
    node and the tenant-EDGE neighbour all appear; the unscoped node never does."""
    g = _fixture_graph(); st = _storage_over(g)
    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        out = _run(st.get_knowledge_graph("curcumin", max_depth=2, max_nodes=50))
    finally:
        reset_scope_filter(token)
    assert _ids(out) == ["CLINIC-A-NOTE", "CURCUMIN", "Curcumin", "INBOUND-SRC", "NFKB1",
                         "SHARED-BEHIND-TENANT", "SHARED-VIA-TENANT-EDGE", "TWO-HOPS"]
    assert _eids(out) == ["e1", "e2", "e3", "e4", "e6", "e7", "e8"]
    # every query in the chain carried the WIDE scope (QG finding: resolve vs traverse scope split)
    for _q, params in g.log:
        assert params["scope_filter"] == ["shared", "tenant:clinic-a"]


@pytest.mark.unit
def test_bfs_depth_counts_in_scope_hops_only() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    d0 = _run(st.get_knowledge_graph("CURCUMIN", max_depth=0))
    assert _ids(d0) == ["CURCUMIN"] and d0.edges == [] and g.queries("AS here") == []
    d1 = _run(st.get_knowledge_graph("CURCUMIN", max_depth=1))
    assert "TWO-HOPS" not in _ids(d1) and "NFKB1" in _ids(d1)
    d2 = _run(st.get_knowledge_graph("CURCUMIN", max_depth=2))
    assert "TWO-HOPS" in _ids(d2)


@pytest.mark.unit
def test_bfs_node_budget_counts_in_scope_nodes_and_flags_truncation() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    out = _run(st.get_knowledge_graph("CURCUMIN", max_depth=2, max_nodes=2))
    assert len(out.nodes) == 2 and out.nodes[0].id == "CURCUMIN"
    assert out.is_truncated is True
    present = {n.id for n in out.nodes}
    assert all(e.source in present and e.target in present for e in out.edges)
    # exactly fitting budget -> not truncated
    full = _run(st.get_knowledge_graph("CURCUMIN", max_depth=2, max_nodes=5))
    assert len(full.nodes) == 5 and full.is_truncated is False


@pytest.mark.unit
def test_wildcard_is_computed_in_scope() -> None:
    g = _fixture_graph(); st = _storage_over(g)
    out = _run(st.get_knowledge_graph("*", max_nodes=3))
    ids = _ids(out)
    assert "CLINIC-A-NOTE" not in ids and "UNSCOPED" not in ids and "TENANT-ONLY-SEED" not in ids
    assert len(ids) == 3 and "CURCUMIN" in ids          # highest in-scope degree
    assert out.is_truncated is True                       # 8 shared nodes > 3
    assert g.queries("{entity_id: $seed}") == [], "no seed resolution for the wildcard"
    present = set(ids)
    assert all(e.source in present and e.target in present for e in out.edges)
    everything = _run(st.get_knowledge_graph("*", max_nodes=100))
    assert everything.is_truncated is False and len(everything.nodes) == 8


@pytest.mark.unit
def test_empty_string_entity_id_from_resolver_is_treated_as_unresolved() -> None:
    class _Blank(_GraphFake):
        def session(self, **_):
            outer = self
            class S(_GraphFakeSession):
                async def run(self, query, **params):
                    outer.log.append((query, params))
                    if "AS here" in query:
                        raise AssertionError("traversal must not start from an empty id")
                    return _FakeAsyncResult([_FakeRecord({"entity_id": ""})])
            return S(self)
    st = _storage_over(_Blank())
    out = _run(st.get_knowledge_graph("anything"))
    assert out.nodes == [] and out.edges == []
