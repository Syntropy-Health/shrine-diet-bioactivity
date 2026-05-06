"""MCP server registering the 10 KG tools per the design memo.

Thin wrapper: each MCP tool dispatches to a pure async function in
``tools.py``. The pure functions take an injected ``ScopedServerClient``
and a Pydantic input model. This split keeps the test surface clean —
unit tests exercise the tools without booting the MCP SDK.

Run:
    python -m kg_mcp.server               # stdio transport (the default)
    kg-mcp-server                          # console-script entry
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import analytics
from . import tools as t
from .client import ScopedServerClient
from .schemas import (
    BilingualTermInput,
    BilingualTermOutput,
    HDICheckInput,
    HDICheckOutput,
    KgQueryInput,
    KgQueryOutput,
    NodeNeighborhoodInput,
    NodeNeighborhoodOutput,
    TraversalInput,
    TraversalOutput,
)

# ─── Lifespan: build/close the HTTP client once ──────────────────────────


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncIterator[ScopedServerClient]:
    client = ScopedServerClient()
    try:
        yield client
    finally:
        await client.aclose()


# Build TransportSecuritySettings from env BEFORE FastMCP construction.
# Mutating server.settings.transport_security after the fact does NOT propagate
# to the streamable_http_app's middleware (it captures the settings at
# app-construction time). So we read env here and pass via kwargs.
def _build_transport_security() -> TransportSecuritySettings:
    if os.environ.get("MCP_DISABLE_DNS_REBINDING_PROTECTION", "").lower() in ("1", "true", "yes"):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    extra_hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    extra_origins = [o.strip() for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    base_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    base_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=base_hosts + extra_hosts,
        allowed_origins=base_origins + extra_origins,
    )


server = FastMCP(
    "kg-mcp",
    lifespan=_lifespan,
    transport_security=_build_transport_security(),
)


def _client() -> ScopedServerClient:
    """Resolve the lifespan-bound client at tool-invocation time."""
    return server.get_context().request_context.lifespan_context  # type: ignore[no-any-return]


# ─── HTTP custom routes (only used in streamable-http / sse transports) ────


@server.custom_route("/health", methods=["GET"])
async def _http_health(_request):
    """Public health endpoint Railway polls. Probes the upstream scoped_server too,
    so a green /health here means the whole MCP→scoped_server→Aura path is reachable.
    """
    from starlette.responses import JSONResponse

    try:
        client = ScopedServerClient()
        try:
            up = await client.health()
        finally:
            await client.aclose()
        return JSONResponse({
            "status": "ok",
            "mcp": "ok",
            "scoped_server": up,
        })
    except Exception as e:  # noqa: BLE001 - health endpoint must always respond
        return JSONResponse(
            {"status": "degraded", "mcp": "ok", "scoped_server_error": str(e)},
            status_code=503,
        )


# ─── Layer A — General Q&A ────────────────────────────────────────────────


@server.tool()
async def kg_query(
    question: str,
    mode: Literal["mix", "hybrid", "local", "global", "naive"] = "mix",
    top_k: int = 40,
) -> KgQueryOutput:
    """Natural-language question over the LightRAG KG. Default fallback when no role-prior fits.

    Use this for open-ended exploration. For deterministic traversals
    (Compound→Target, Herb→Disease, etc.) prefer the typed Layer-B tools —
    they cite explicit edge types in their result chains, which is what
    the publication's provenance metric measures.
    """
    return await t.kg_query(_client(), KgQueryInput(question=question, mode=mode, top_k=top_k))


# ─── Layer B — Role-priored deterministic traversals ─────────────────────


@server.tool()
async def kg_diet_to_compounds(seed: str, top_k: int = 20) -> TraversalOutput:
    """Food → bioactives. Seed with a Food name (e.g. 'Garlic'). Used by the Dietitian role."""
    return await t.kg_diet_to_compounds(_client(), TraversalInput(seed=seed, top_k=top_k))


@server.tool()
async def kg_compound_to_targets(seed: str, top_k: int = 20) -> TraversalOutput:
    """Compound → Target. Seed with a compound name (e.g. 'Curcumin'). Pharmacologist's primary tool."""
    return await t.kg_compound_to_targets(_client(), TraversalInput(seed=seed, top_k=top_k))


@server.tool()
async def kg_compound_to_diseases(seed: str, top_k: int = 20) -> TraversalOutput:
    """Compound → Target → Disease (depth-2 chain). Provenance path for HDI Recall claims."""
    return await t.kg_compound_to_diseases(_client(), TraversalInput(seed=seed, top_k=top_k))


@server.tool()
async def kg_herb_to_diseases(seed: str, top_k: int = 20) -> TraversalOutput:
    """Herb → Disease. Backed by CMAUP plant-disease + HERB 2.0 evidence-tiered links."""
    return await t.kg_herb_to_diseases(_client(), TraversalInput(seed=seed, top_k=top_k))


@server.tool()
async def kg_herb_to_symptoms(seed: str, top_k: int = 20) -> TraversalOutput:
    """Herb → Symptom. TCM and Dietitian. Backed by Duke bioactivity + SymMap TCM."""
    return await t.kg_herb_to_symptoms(_client(), TraversalInput(seed=seed, top_k=top_k))


@server.tool()
async def kg_compound_to_symptoms(seed: str, top_k: int = 20) -> TraversalOutput:
    """Compound → Herb → Symptom (composite). Path for compound-mechanism→clinical-symptom queries."""
    return await t.kg_compound_to_symptoms(_client(), TraversalInput(seed=seed, top_k=top_k))


# ─── Layer C — Lookup primitives ──────────────────────────────────────────


@server.tool()
async def kg_hdi_check(drug: str, herb: str) -> HDICheckOutput:
    """Direct lookup against HDI-Safe-50 panel. Returns severity/mechanism/evidence_tier or `found=False`."""
    return await t.kg_hdi_check(_client(), HDICheckInput(drug=drug, herb=herb))


@server.tool()
async def kg_bilingual_term(term: str) -> BilingualTermOutput:
    """SymMap bilingual canonicalization. Term in any of EN/CN/Pinyin → all three."""
    return await t.kg_bilingual_term(_client(), BilingualTermInput(term=term))


@server.tool()
async def kg_node_neighborhood(
    seed: str, max_depth: int = 2, max_nodes: int = 200
) -> NodeNeighborhoodOutput:
    """Generic bounded-depth subgraph dump. Use only when a role-priored tool doesn't fit."""
    return await t.kg_node_neighborhood(
        _client(), NodeNeighborhoodInput(seed=seed, max_depth=max_depth, max_nodes=max_nodes)
    )


# ─── Entry point ──────────────────────────────────────────────────────────


def main() -> None:
    """Console-script entry: `python -m kg_mcp.server` or `kg-mcp-server`.

    Transport selection (env-driven):
      MCP_TRANSPORT=stdio           local agent spawns this as a subprocess (default)
      MCP_TRANSPORT=streamable-http Railway-deployed; agent connects over HTTP
    HTTP transport extras:
      MCP_HOST=0.0.0.0
      MCP_PORT=8080
    """
    from typing import cast

    transport_env = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport_env not in ("stdio", "sse", "streamable-http"):
        raise SystemExit(
            f"MCP_TRANSPORT={transport_env!r} invalid; expected one of "
            "stdio | sse | streamable-http"
        )
    transport = cast(Literal["stdio", "sse", "streamable-http"], transport_env)

    analytics.capture(
        analytics.SERVER_DISTINCT_ID,
        "mcp_server_started",
        {"transport": transport},
    )

    if transport == "stdio":
        server.run()
        return

    # FastMCP HTTP transports honor `host`/`port` set on the FastMCP instance
    # via settings. Set them right before run() so env-driven config applies.
    server.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")
    server.settings.port = int(os.environ.get("MCP_PORT", "8080"))

    # transport_security was already configured at FastMCP construction
    # (see _build_transport_security above) — no post-hoc mutation needed.

    # Auth layer: wrap FastMCP's HTTP app with Bearer-token middleware.
    # /health stays public (Railway healthcheck); /mcp* requires either
    # MCP_API_KEY or a Clerk JWT with email in MCP_ADMIN_EMAILS.
    # Set MCP_AUTH_DISABLED=true to bypass — local dev only.
    auth_disabled = os.environ.get("MCP_AUTH_DISABLED", "").lower() in ("1", "true", "yes")
    if auth_disabled:
        server.run(transport=transport)
        return

    import uvicorn
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Mount

    from .auth import AuthMiddleware

    if transport == "streamable-http":
        inner_app = server.streamable_http_app()
    elif transport == "sse":
        inner_app = server.sse_app()
    else:
        server.run(transport=transport)
        return

    # Wrap with an OUTER Starlette app so the middleware runs before any
    # routing in the inner FastMCP app. Calling app.add_middleware() on the
    # inner app after it's been built is silently ignored when the app's
    # middleware stack has already been finalized — caught by an e2e test
    # that saw 200 instead of 401 from /mcp without bearer.
    #
    # CRITICAL: forward the inner app's lifespan to the outer. FastMCP's
    # StreamableHTTP session manager initializes its task_group inside the
    # inner app's lifespan; without forwarding, every /mcp request errors
    # with "Task group is not initialized. Make sure to use run()".
    guarded_app = Starlette(
        routes=[Mount("/", app=inner_app)],
        middleware=[Middleware(AuthMiddleware)],
        lifespan=inner_app.router.lifespan_context,
    )

    uvicorn.run(
        guarded_app,
        host=server.settings.host,
        port=server.settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
