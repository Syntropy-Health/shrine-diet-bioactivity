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
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from audit_log import AuditLog, default_audit_log
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
    from lightrag.kg import STORAGES

    # Register our subclass so LightRAG's string-based resolver can find it.
    # The entry value is the absolute module path (``scoped_neo4j_storage``
    # must be importable from cwd — the Makefile enforces cd lightrag).
    STORAGES["ScopedNeo4JStorage"] = "scoped_neo4j_storage"

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
    scope_filter: list[str] = Field(
        ...,
        min_length=1,
        description="Required: ['shared'] or ['shared','tenant:<slug>']",
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
