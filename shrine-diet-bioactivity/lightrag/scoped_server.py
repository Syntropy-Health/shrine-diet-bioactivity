"""
FastAPI wrapper around LightRAG that enforces per-request tenant
scoping via ``ScopedNeo4JStorage`` and emits an audit row per query.

Why this exists (see the multi-tenant-enforcement-bootstrap plan):
upstream LightRAG's ``POST /query`` has no ``scope_filter`` field; our
MCP layer sends one and the upstream binary silently drops it. This
wrapper accepts ``scope_filter`` in the request body, sets a
``contextvars.ContextVar`` that ``ScopedNeo4JStorage`` reads during
every Cypher execution, then delegates to LightRAG's ``aquery()``.

Boot::

    cd shrine-diet-bioactivity/lightrag
    uvicorn scoped_server:app --host 0.0.0.0 --port 9621

Or via ``make lightrag-server``.

Current surface is intentionally narrow — just ``POST /query`` +
``GET /health``. Graph-routes pass-throughs (``get-entity`` /
``get-neighbors`` / ``list-entity-types``) land with the Phase D
tool-catalog cutover.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from audit_log import AuditLog, AuditRow, default_audit_log
from scope_context import (
    reset_scope_filter,
    set_scope_filter,
    validate_scope,
)

SCRIPT_DIR = Path(__file__).parent
VALID_MODES = {"local", "global", "hybrid", "naive", "mix"}

logger = logging.getLogger("scoped_server")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_config() -> str:
    """Load config_<name>.env from lightrag/; return config name."""
    config_name = os.environ.get("SHRINE_CONFIG", "local")
    env_file = SCRIPT_DIR / f"config_{config_name}.env"
    if env_file.exists():
        load_dotenv(env_file, override=True)
    else:
        logger.warning(
            "config_%s.env not found at %s — relying on process env only",
            config_name,
            env_file,
        )
    return config_name


# ---------------------------------------------------------------------------
# LightRAG factory — registers ScopedNeo4JStorage and returns a booted rag
# ---------------------------------------------------------------------------


async def _build_scoped_rag() -> Any:
    """Instantiate LightRAG with ScopedNeo4JStorage as the graph backend."""
    from lightrag import LightRAG
    from lightrag.kg import STORAGES, STORAGE_IMPLEMENTATIONS

    # Register our subclasses in BOTH LightRAG registries:
    #   - STORAGES: dynamic resolver string → module path
    #   - STORAGE_IMPLEMENTATIONS: hardcoded compatibility list checked by
    #     verify_storage_implementation() during LightRAG.__post_init__
    # Recent LightRAG versions added the second registry; without this entry
    # __post_init__ raises ValueError("not compatible with <SLOT>_STORAGE").
    STORAGES["ScopedNeo4JStorage"] = "scoped_neo4j_storage"
    STORAGES["ScopedNeo4JVectorStorage"] = "scoped_neo4j_vector_storage"
    graph_impls = STORAGE_IMPLEMENTATIONS["GRAPH_STORAGE"]["implementations"]
    if "ScopedNeo4JStorage" not in graph_impls:
        graph_impls.append("ScopedNeo4JStorage")
    vector_impls = STORAGE_IMPLEMENTATIONS["VECTOR_STORAGE"]["implementations"]
    if "ScopedNeo4JVectorStorage" not in vector_impls:
        vector_impls.append("ScopedNeo4JVectorStorage")

    working_dir = os.environ.get("WORKING_DIR", str(SCRIPT_DIR / "rag_storage_local"))
    workspace = os.environ.get("WORKSPACE", "unified_diet_kg")

    # Import LLM and embedding bindings lazily so missing optional deps do
    # not break the server at import time.
    from lightrag.llm.ollama import ollama_model_complete, ollama_embed
    from lightrag.utils import EmbeddingFunc

    embedding_dim = int(os.environ.get("EMBEDDING_DIM", "1024"))
    embedding_model = os.environ.get("EMBEDDING_MODEL", "bge-m3:latest")
    llm_model = os.environ.get("LLM_MODEL", "qwen2.5-coder:7b")
    llm_host = os.environ.get("LLM_BINDING_HOST", "http://localhost:11434")

    async def _embed(texts: list[str]) -> Any:
        return await ollama_embed(
            texts,
            embed_model=embedding_model,
            host=llm_host,
        )

    rag = LightRAG(
        working_dir=working_dir,
        workspace=workspace,
        graph_storage="ScopedNeo4JStorage",
        llm_model_func=ollama_model_complete,
        llm_model_name=llm_model,
        llm_model_kwargs={"host": llm_host, "options": {"num_ctx": 32768}},
        embedding_func=EmbeddingFunc(
            embedding_dim=embedding_dim,
            max_token_size=8192,
            func=_embed,
        ),
    )
    await rag.initialize_storages()
    return rag


# ---------------------------------------------------------------------------
# Preflight — block startup if the graph still has scope IS NULL nodes
# ---------------------------------------------------------------------------


def _preflight_scope_check() -> None:
    """Verify ``bootstrap_scope.py`` has been run against this Neo4j.

    Raises at startup if legacy untagged rows remain — serving queries
    before the migration would let shared data leak into tenant-only
    results (or vice versa) because ScopedNeo4JStorage filters out rows
    with ``scope IS NULL``.
    """
    from bootstrap_scope import _safe_label, count_untagged
    from neo4j import GraphDatabase

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    workspace_label = _safe_label(os.environ.get("WORKSPACE", "unified_diet_kg"))

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        n, r = count_untagged(driver, workspace_label)
        if n or r:
            raise RuntimeError(
                f"Preflight failed: {n} nodes and {r} relationships in "
                f"workspace '{workspace_label}' have scope IS NULL. "
                "Run `make lightrag-bootstrap-scope` before serving."
            )
    logger.info("preflight: all nodes+relationships scoped ✓")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language query")
    mode: str = Field("hybrid", description="LightRAG retrieval mode")
    top_k: int = Field(60, ge=1, le=200)
    # scope_filter defaults to ['shared'] to match the codebase-wide
    # DEFAULT_SCOPE in scope_context.py and the project policy that
    # open-source datasets ingest under scope='shared'. Tenant-scoped
    # callers MUST still pass ['shared', 'tenant:<slug>'] explicitly —
    # the server cannot guess a tenant. Empty lists are rejected.
    scope_filter: list[str] = Field(
        default_factory=lambda: ["shared"],
        min_length=1,
        description="Defaults to ['shared']. Pass ['shared','tenant:<slug>'] for tenant-scoped reads.",
    )


class HealthResponse(BaseModel):
    status: str
    config: str


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


app = FastAPI(title="shrine-diet-bioactivity scoped LightRAG wrapper")
_rag: Any = None
_audit: AuditLog = default_audit_log()
_config_name: str = "unknown"


@app.on_event("startup")
async def _startup() -> None:
    global _rag, _config_name
    _config_name = _load_config()
    _preflight_scope_check()
    _rag = await _build_scoped_rag()
    logger.info("scoped_server booted (config=%s)", _config_name)


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _rag
    if _rag is not None:
        try:
            await _rag.finalize_storages()
        except Exception as e:  # noqa: BLE001 - best-effort cleanup
            logger.warning("finalize_storages failed: %s", e)
        _rag = None


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", config=_config_name)


# ---------------------------------------------------------------------------
# Typed-Cypher endpoints (POST /traverse, /hdi_check, /bilingual_term).
#
# These bypass LightRAG's NL synthesis and run direct Cypher against Aura,
# enforcing the scope filter on every node + edge. They power the MCP
# Layer-B/C tools per research-journal/plans/2026-04-29-mcp-gateway-design.md.
#
# Cypher safety: ALL label/edge-type names sent by the client are checked
# against an explicit allow-list before string-substitution. This is the
# same pattern bootstrap_scope.py and ingest_direct.py already use; never
# relax it.
# ---------------------------------------------------------------------------

# Allow-listed labels and edge types. Extending the KG schema means extending
# these lists too — keeps the Cypher dispatch surface explicit.
ALLOWED_LABELS: set[str] = {
    "Herb", "Compound", "Food", "Target", "Disease", "Symptom", "Drug",
    "Gene", "Pathway", "VectorEntity", "VectorRelationship", "VectorChunk",
}
ALLOWED_EDGE_TYPES: set[str] = {
    "TARGETS_PROTEIN", "ASSOCIATED_WITH_DISEASE", "TREATS_SYMPTOM",
    "FOUND_IN_FOOD", "CONTAINS_COMPOUND", "INTERACTS_WITH", "DIRECTED",
    "MODULATES_PATHWAY",
}


def _get_driver() -> Any:
    """Return the underlying neo4j driver from the booted LightRAG storage.

    The driver is owned by ScopedNeo4JStorage; we just borrow it for the
    typed endpoints. Tests monkeypatch this function to inject a fake.
    """
    if _rag is None:
        raise HTTPException(status_code=503, detail="LightRAG not initialized")
    storage = getattr(_rag, "chunk_entity_relation_graph", None)
    driver = getattr(storage, "_driver", None) if storage else None
    if driver is None:
        raise HTTPException(status_code=503, detail="Neo4j driver unavailable")
    return driver


def _safe_label(name: str) -> str:
    """Reject Cypher-injection attempts; assume the allow-list already passed."""
    if not name.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail=f"label/edge name not allowed: {name!r}")
    return name


def _build_traverse_cypher(
    *,
    workspace: str,
    start_label: str,
    edge_types: list[str],
    direction: str,
    depth: int,
) -> str:
    """Compose the typed Cypher for the requested traversal pattern.

    Two patterns supported:
      depth=1 with 1 edge type    — single-hop
      depth=2 with 2 edge types   — chain
    Anything else is rejected at the endpoint, not here.
    """
    ws = _safe_label(workspace)
    sl = _safe_label(start_label)

    if depth == 1:
        et = _safe_label(edge_types[0])
        if direction == "outbound":
            arrow = f"(start)-[r:`{et}`]->(tgt)"
        elif direction == "inbound":
            arrow = f"(start)<-[r:`{et}`]-(tgt)"
        else:  # bidirectional
            arrow = f"(start)-[r:`{et}`]-(tgt)"
        # Multi-label MATCH on (workspace, start_label) is faster than a
        # post-WHERE labels() check and clearer to reviewers reading the
        # Cypher. The allow-list at the endpoint guarantees `sl` is safe.
        return (
            f"MATCH (start:`{ws}`:`{sl}` {{entity_id: $seed}}) "
            f"WHERE start.scope IN $scope_filter "
            f"MATCH {arrow} "
            f"WHERE tgt:`{ws}` AND tgt.scope IN $scope_filter "
            f"  AND r.scope IN $scope_filter "
            f"RETURN start.entity_id AS src_id, tgt.entity_id AS tgt_id, "
            f"       type(r) AS rel_type, "
            f"       coalesce(r.description, '') AS description, "
            f"       coalesce(r.evidence_tier, '') AS evidence_tier, "
            f"       coalesce(r.source_id, '') AS source_id "
            f"LIMIT $top_k"
        )

    # depth == 2
    e1, e2 = _safe_label(edge_types[0]), _safe_label(edge_types[1])
    if direction == "outbound":
        chain = (
            f"(start)-[r1:`{e1}`]->(mid:`{ws}`)-[r2:`{e2}`]->(tgt:`{ws}`)"
        )
    elif direction == "inbound":
        chain = (
            f"(start)<-[r1:`{e1}`]-(mid:`{ws}`)<-[r2:`{e2}`]-(tgt:`{ws}`)"
        )
    else:  # bidirectional
        chain = (
            f"(start)-[r1:`{e1}`]-(mid:`{ws}`)-[r2:`{e2}`]-(tgt:`{ws}`)"
        )
    return (
        f"MATCH (start:`{ws}`:`{sl}` {{entity_id: $seed}}) "
        f"WHERE start.scope IN $scope_filter "
        f"MATCH {chain} "
        f"WHERE r1.scope IN $scope_filter AND r2.scope IN $scope_filter "
        f"  AND mid.scope IN $scope_filter AND tgt.scope IN $scope_filter "
        f"RETURN start.entity_id AS src_id, mid.entity_id AS mid_id, "
        f"       tgt.entity_id AS tgt_id, "
        f"       type(r1) AS rel_type_1, type(r2) AS rel_type_2, "
        f"       coalesce(r1.description, '') AS description_1, "
        f"       coalesce(r2.description, '') AS description_2, "
        f"       coalesce(r1.source_id, '') AS source_id_1, "
        f"       coalesce(r2.source_id, '') AS source_id_2 "
        f"LIMIT $top_k"
    )


# ─── Pydantic models for typed endpoints ──────────────────────────────────


class TraverseRequest(BaseModel):
    start_label: str = Field(..., min_length=1)
    edge_types: list[str] = Field(..., min_length=1, max_length=2)
    seed: str = Field(..., min_length=1)
    direction: Literal["outbound", "inbound", "bidirectional"] = "outbound"
    depth: int = Field(1, ge=1, le=2)
    top_k: int = Field(20, ge=1, le=200)
    scope_filter: list[str] = Field(default_factory=lambda: ["shared"], min_length=1)


class HDICheckRequest(BaseModel):
    drug: str = Field(..., min_length=1)
    herb: str = Field(..., min_length=1)
    scope_filter: list[str] = Field(default_factory=lambda: ["shared"], min_length=1)


class BilingualTermRequest(BaseModel):
    term: str = Field(..., min_length=1)
    scope_filter: list[str] = Field(default_factory=lambda: ["shared"], min_length=1)


# ─── POST /traverse ───────────────────────────────────────────────────────


@app.post("/traverse")
async def traverse(request: TraverseRequest) -> dict[str, Any]:
    # Allow-list check — prevents Cypher injection via label/edge name.
    if request.start_label not in ALLOWED_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"start_label must be one of {sorted(ALLOWED_LABELS)}",
        )
    for et in request.edge_types:
        if et not in ALLOWED_EDGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"edge_type {et!r} not allowed; expected one of {sorted(ALLOWED_EDGE_TYPES)}",
            )
    if request.depth == 2 and len(request.edge_types) != 2:
        raise HTTPException(
            status_code=400,
            detail="depth=2 requires exactly 2 edge_types (chain pattern)",
        )
    if request.depth == 1 and len(request.edge_types) != 1:
        raise HTTPException(
            status_code=400,
            detail="depth=1 requires exactly 1 edge_type",
        )

    try:
        [validate_scope(s) for s in request.scope_filter]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    workspace = os.environ.get("WORKSPACE", "unified_diet_kg")
    cypher = _build_traverse_cypher(
        workspace=workspace,
        start_label=request.start_label,
        edge_types=request.edge_types,
        direction=request.direction,
        depth=request.depth,
    )

    tenant_id = _extract_tenant_id(request.scope_filter)
    with _scoped_audit(
        tool="scoped_server./traverse",
        scope_filter=request.scope_filter,
        tenant_id=tenant_id,
        body=request.model_dump(),
    ) as row:
        driver = _get_driver()
        with driver.session() as s:
            result = s.run(
                cypher,
                seed=request.seed,
                scope_filter=request.scope_filter,
                top_k=request.top_k,
            )
            records = list(result)

        # Build chains response. depth=1 → single edge per chain;
        # depth=2 → two edges per chain.
        chains: list[dict[str, Any]] = []
        seeds_resolved: set[str] = set()
        for rec in records:
            if request.depth == 1:
                seeds_resolved.add(rec["src_id"])
                chains.append({"edges": [{
                    "src_id": rec["src_id"],
                    "tgt_id": rec["tgt_id"],
                    "rel_type": rec["rel_type"],
                    "description": rec["description"],
                    "evidence_tier": rec["evidence_tier"],
                    "source_id": rec["source_id"],
                }]})
            else:
                seeds_resolved.add(rec["src_id"])
                chains.append({"edges": [
                    {
                        "src_id": rec["src_id"],
                        "tgt_id": rec["mid_id"],
                        "rel_type": rec["rel_type_1"],
                        "description": rec["description_1"],
                        "evidence_tier": "",
                        "source_id": rec["source_id_1"],
                    },
                    {
                        "src_id": rec["mid_id"],
                        "tgt_id": rec["tgt_id"],
                        "rel_type": rec["rel_type_2"],
                        "description": rec["description_2"],
                        "evidence_tier": "",
                        "source_id": rec["source_id_2"],
                    },
                ]})
        row.result_count = len(chains)

        return {
            "chains": chains,
            "seeds_resolved": sorted(seeds_resolved),
            "raw_subgraph_node_count": 0,
            "raw_subgraph_edge_count": sum(len(c["edges"]) for c in chains),
        }


# ─── POST /hdi_check ──────────────────────────────────────────────────────


@app.post("/hdi_check")
async def hdi_check(request: HDICheckRequest) -> dict[str, Any]:
    try:
        [validate_scope(s) for s in request.scope_filter]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    workspace = _safe_label(os.environ.get("WORKSPACE", "unified_diet_kg"))
    # Match either direction of INTERACTS_WITH; case-insensitive on entity_id.
    cypher = (
        f"MATCH (a:`{workspace}`)-[r:INTERACTS_WITH]-(b:`{workspace}`) "
        f"WHERE a.scope IN $scope_filter AND b.scope IN $scope_filter "
        f"  AND r.scope IN $scope_filter "
        f"  AND ((toLower(a.entity_id) = toLower($drug) AND toLower(b.entity_id) = toLower($herb)) "
        f"    OR (toLower(b.entity_id) = toLower($drug) AND toLower(a.entity_id) = toLower($herb))) "
        f"RETURN coalesce(r.severity, '') AS severity, "
        f"       coalesce(r.mechanism_class, '') AS mechanism_class, "
        f"       coalesce(r.evidence_tier, '') AS evidence_tier, "
        f"       coalesce(r.source_id, '') AS source_id "
        f"LIMIT 1"
    )

    tenant_id = _extract_tenant_id(request.scope_filter)
    with _scoped_audit(
        tool="scoped_server./hdi_check",
        scope_filter=request.scope_filter,
        tenant_id=tenant_id,
        body={"drug": request.drug, "herb": request.herb},
    ) as row:
        driver = _get_driver()
        with driver.session() as s:
            result = s.run(
                cypher,
                drug=request.drug,
                herb=request.herb,
                scope_filter=request.scope_filter,
            )
            records = list(result)

    if not records:
        return {"found": False, "severity": None, "mechanism_class": None,
                "evidence_tier": None, "citations": []}
    rec = records[0]
    sev = rec["severity"] or None
    mech = rec["mechanism_class"] or None
    evid = rec["evidence_tier"] or None
    src = rec["source_id"]
    return {
        "found": True,
        "severity": sev,
        "mechanism_class": mech,
        "evidence_tier": evid,
        "citations": [src] if src else [],
    }


# ─── POST /bilingual_term ─────────────────────────────────────────────────


@app.post("/bilingual_term")
async def bilingual_term(request: BilingualTermRequest) -> dict[str, Any]:
    try:
        [validate_scope(s) for s in request.scope_filter]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    workspace = _safe_label(os.environ.get("WORKSPACE", "unified_diet_kg"))
    # Match the term against entity_id, chinese_name, or pinyin_name on Herb
    # nodes (case-insensitive). SymMap ingestion populates these properties
    # via extra_props in ingest_direct.py.
    cypher = (
        f"MATCH (h:`{workspace}`:Herb) "
        f"WHERE h.scope IN $scope_filter AND ("
        f"  toLower(h.entity_id) = toLower($term) "
        f"  OR toLower(coalesce(h.chinese_name, '')) = toLower($term) "
        f"  OR toLower(coalesce(h.pinyin_name, '')) = toLower($term)"
        f") "
        f"RETURN h.entity_id AS english, "
        f"       coalesce(h.chinese_name, h.name_cn, '') AS chinese, "
        f"       coalesce(h.pinyin_name, '') AS pinyin "
        f"LIMIT 1"
    )

    tenant_id = _extract_tenant_id(request.scope_filter)
    with _scoped_audit(
        tool="scoped_server./bilingual_term",
        scope_filter=request.scope_filter,
        tenant_id=tenant_id,
        body={"term": request.term},
    ) as row:
        driver = _get_driver()
        with driver.session() as s:
            result = s.run(
                cypher, term=request.term, scope_filter=request.scope_filter,
            )
            records = list(result)

    if not records:
        return {"english": None, "chinese": None, "pinyin": None,
                "source": "symmap", "confidence": 0.0}
    rec = records[0]
    return {
        "english": rec["english"] or None,
        "chinese": rec["chinese"] or None,
        "pinyin": rec["pinyin"] or None,
        "source": "symmap",
        "confidence": 1.0,  # exact match
    }


@app.post("/query")
async def query(request: QueryRequest) -> dict[str, Any]:
    if request.mode not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {sorted(VALID_MODES)}, got {request.mode!r}",
        )

    # Validate every scope value — fail closed on malformed input.
    try:
        [validate_scope(s) for s in request.scope_filter]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    tenant_id = _extract_tenant_id(request.scope_filter)

    with _audit.record(
        tool="scoped_server./query",
        scope_filter=request.scope_filter,
        tenant_id=tenant_id,
        query_body={
            "query": request.query,
            "mode": request.mode,
            "top_k": request.top_k,
        },
    ) as audit_row:
        from lightrag import QueryParam

        token = set_scope_filter(request.scope_filter)
        try:
            param = QueryParam(mode=request.mode, top_k=request.top_k)
            result = await _rag.aquery(request.query, param=param)
        finally:
            reset_scope_filter(token)

        text_result = result if isinstance(result, str) else str(result)
        audit_row.result_count = len(text_result)
        return {
            "response": text_result,
            "scope_filter": request.scope_filter,
        }


def _extract_tenant_id(scope_filter: list[str]) -> str | None:
    """Return the first 'tenant:<slug>' in the filter, or None."""
    for s in scope_filter:
        if s.startswith("tenant:"):
            return s[len("tenant:"):]
    return None


# ---------------------------------------------------------------------------
# Shared helpers for graph-route + ingest pass-throughs (Phase D1a)
# ---------------------------------------------------------------------------


def _parse_scope_filter_param(raw: str | None) -> list[str]:
    """Parse the ``scope_filter`` query-string value for GET routes.

    The value is a comma-separated list, e.g.
    ``scope_filter=shared,tenant:clinic-a``. Each element must pass
    :func:`validate_scope`. An empty or missing value is a 400 —
    fail-closed, never fall back to a permissive default on the wire.
    """
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="scope_filter query param required, e.g. ?scope_filter=shared,tenant:<slug>",
        )
    parts = [s.strip() for s in raw.split(",") if s.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="scope_filter cannot be empty")
    try:
        for s in parts:
            validate_scope(s)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return parts


def _require_tenant(scope_filter: list[str]) -> str:
    """Return the tenant slug or raise 400 — used by write routes."""
    tenant = _extract_tenant_id(scope_filter)
    if tenant is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "ingest routes require a 'tenant:<slug>' in scope_filter; "
                "shared writes go through the offline ETL (ingest_unified.py)"
            ),
        )
    return tenant


@contextmanager
def _scoped_audit(
    tool: str,
    scope_filter: list[str],
    tenant_id: str | None,
    body: object | None,
) -> Iterator[AuditRow]:
    """Compose scope-ContextVar set/reset with one audit row per request.

    The audit row is emitted via ``_audit.record`` on exit. Any exception
    inside the block is re-raised after the audit row has been marked
    ``status='error'`` and emitted.
    """
    token = set_scope_filter(scope_filter)
    try:
        with _audit.record(
            tool=tool,
            scope_filter=scope_filter,
            tenant_id=tenant_id,
            query_body=body,
        ) as row:
            yield row
    finally:
        reset_scope_filter(token)


# ---------------------------------------------------------------------------
# Custom KG ingest request model (strict pydantic — payload shape is
# validated at the edge; Cypher writes inherit the tenant scope).
# ---------------------------------------------------------------------------


class CustomKGEntity(BaseModel):
    entity_name: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    description: str = Field(default="")
    # scope is ignored on input — always rewritten to tenant:<id>
    scope: str | None = None
    source_id: str | None = None


class CustomKGRelationship(BaseModel):
    src_id: str = Field(..., min_length=1)
    tgt_id: str = Field(..., min_length=1)
    description: str = Field(default="")
    keywords: str = Field(default="")
    weight: float = 1.0
    scope: str | None = None
    source_id: str | None = None


class CustomKGPayload(BaseModel):
    entities: list[CustomKGEntity] = Field(default_factory=list)
    relationships: list[CustomKGRelationship] = Field(default_factory=list)


class IngestCustomKGRequest(BaseModel):
    scope_filter: list[str] = Field(..., min_length=1)
    custom_kg: CustomKGPayload
    source_label: str | None = None


# ---------------------------------------------------------------------------
# GET /graphs — subgraph by label
# ---------------------------------------------------------------------------


@app.get("/graphs")
async def get_graphs(
    label: str = Query(..., description="Entity label / entity_id to expand from"),
    max_depth: int = Query(3, ge=0, le=5),
    max_nodes: int = Query(1000, ge=1, le=10_000),
    scope_filter: str | None = Query(
        None, description="Comma-separated, e.g. 'shared,tenant:<slug>'"
    ),
) -> dict[str, Any]:
    scopes = _parse_scope_filter_param(scope_filter)
    tenant_id = _extract_tenant_id(scopes)

    with _scoped_audit(
        tool="scoped_server./graphs",
        scope_filter=scopes,
        tenant_id=tenant_id,
        body={"label": label, "max_depth": max_depth, "max_nodes": max_nodes},
    ) as row:
        result = await _rag.get_knowledge_graph(
            node_label=label,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        nodes = result.get("nodes", []) if isinstance(result, dict) else []
        row.result_count = len(nodes)
        return result if isinstance(result, dict) else {"raw": str(result)}


# ---------------------------------------------------------------------------
# GET /graph/label/popular — ontology shape in scope
# ---------------------------------------------------------------------------


@app.get("/graph/label/popular")
async def get_popular_labels(
    limit: int = Query(300, ge=1, le=1000),
    scope_filter: str | None = Query(None),
) -> list[str]:
    scopes = _parse_scope_filter_param(scope_filter)
    tenant_id = _extract_tenant_id(scopes)

    with _scoped_audit(
        tool="scoped_server./graph/label/popular",
        scope_filter=scopes,
        tenant_id=tenant_id,
        body={"limit": limit},
    ) as row:
        labels = await _rag.chunk_entity_relation_graph.get_popular_labels(limit)
        row.result_count = len(labels)
        return labels


# ---------------------------------------------------------------------------
# POST /documents/custom_kg — tenant-scoped write
# ---------------------------------------------------------------------------


@app.post("/documents/custom_kg")
async def ingest_custom_kg(request: IngestCustomKGRequest) -> dict[str, Any]:
    # Scope validation + tenant requirement happen first so a malformed
    # request does not emit an audit row under someone else's tenant.
    try:
        [validate_scope(s) for s in request.scope_filter]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    tenant_id = _require_tenant(request.scope_filter)
    tenant_scope = f"tenant:{tenant_id}"

    # Rewrite every entity / relationship scope to the tenant — the
    # client cannot inject into 'shared' by setting it on a single row.
    entities = [
        {**e.model_dump(exclude_none=True), "scope": tenant_scope}
        for e in request.custom_kg.entities
    ]
    relationships = [
        {**r.model_dump(exclude_none=True), "scope": tenant_scope}
        for r in request.custom_kg.relationships
    ]

    with _scoped_audit(
        tool="scoped_server./documents/custom_kg",
        scope_filter=request.scope_filter,
        tenant_id=tenant_id,
        body={
            "source_label": request.source_label,
            "entity_count": len(entities),
            "relationship_count": len(relationships),
        },
    ) as row:
        await _rag.ainsert_custom_kg(
            {"entities": entities, "relationships": relationships}
        )
        row.result_count = len(entities) + len(relationships)
        return {
            "ingested": {
                "entities": len(entities),
                "relationships": len(relationships),
            },
            "scope": tenant_scope,
        }
