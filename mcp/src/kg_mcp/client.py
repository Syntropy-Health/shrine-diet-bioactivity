"""Async HTTP client for scoped_server. Thin — no business logic.

Why a separate client: keeps tool implementations focused on schema mapping
without each one re-deriving auth, base URL, scope_filter handling, or audit
correlation IDs.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_SCOPED_SERVER_URL = "http://localhost:9621"
DEFAULT_TIMEOUT_SECONDS = 60.0
_DETAIL_MAX_CHARS = 200


def _upstream_detail(r: httpx.Response) -> str:
    """Human detail for an error: scoped_server's own JSON ``detail`` (its
    HTTPException strings), else the bare HTTP reason phrase. NEVER the raw
    body — a proxy HTML page or a stack-trace body would re-open the leak this
    helper exists to close."""
    try:
        body = r.json()
    except Exception:  # noqa: BLE001 - non-JSON upstream bodies (proxy HTML etc.)
        body = None
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])[:_DETAIL_MAX_CHARS]
    reason = getattr(r, "reason_phrase", "")
    return reason if isinstance(reason, str) else ""


def _check(r: httpx.Response) -> None:
    """``raise_for_status`` with a SANITISED message.

    httpx's default message embeds the full request URL, which for this client
    is the INTERNAL scoped_server address (e.g. ``http://127.0.0.1:9621/graphs?…``).
    FastMCP forwards ``str(exc)`` to consumers verbatim, so that leaked the
    upstream host/port to every MCP client (shrine-diet #6). Re-raise the same
    exception TYPE (callers branch on ``exc.response.status_code`` for the 404
    fallbacks) carrying only status + route path + upstream ``detail``.
    """
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        path = exc.request.url.path
        msg = f"scoped_server returned {r.status_code} for {path}"
        detail = _upstream_detail(r)
        if detail:
            msg = f"{msg}: {detail}"
        raise httpx.HTTPStatusError(msg, request=exc.request, response=exc.response) from None


class ScopedServerClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = (base_url or os.environ.get("LIGHTRAG_URL", DEFAULT_SCOPED_SERVER_URL)).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        r = await self._client.get(f"{self.base_url}/health")
        _check(r)
        return r.json()

    async def query(
        self,
        question: str,
        mode: str = "mix",
        top_k: int = 40,
        scope_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        body = {"query": question, "mode": mode, "top_k": top_k}
        if scope_filter is not None:
            body["scope_filter"] = scope_filter
        r = await self._client.post(f"{self.base_url}/query", json=body)
        _check(r)
        return r.json()

    async def graphs(
        self,
        label: str,
        max_depth: int = 2,
        max_nodes: int = 200,
        scope_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "label": label,
            "max_depth": max_depth,
            "max_nodes": max_nodes,
        }
        if scope_filter is not None:
            params["scope_filter"] = ",".join(scope_filter)
        r = await self._client.get(f"{self.base_url}/graphs", params=params)
        _check(r)
        return r.json()

    async def traverse(
        self,
        start_label: str,
        edge_types: list[str],
        seed: str,
        direction: str = "outbound",
        depth: int = 1,
        top_k: int = 20,
        scope_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        """Layer-B typed traversal. Requires scoped_server to expose POST /traverse.

        Falls back to /graphs if /traverse is not yet implemented (so Layer-B
        tools degrade gracefully in the scaffold phase).
        """
        body = {
            "start_label": start_label,
            "edge_types": edge_types,
            "seed": seed,
            "direction": direction,
            "depth": depth,
            "top_k": top_k,
        }
        if scope_filter is not None:
            body["scope_filter"] = scope_filter
        try:
            r = await self._client.post(f"{self.base_url}/traverse", json=body)
            _check(r)
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # /traverse not yet on scoped_server — fall back to /graphs
                return await self.graphs(
                    label=seed, max_depth=depth, max_nodes=top_k * 5, scope_filter=scope_filter
                )
            raise

    async def hdi_check(self, drug: str, herb: str) -> dict[str, Any]:
        """POST /hdi_check (to be added on scoped_server). Falls back to empty result."""
        try:
            r = await self._client.post(
                f"{self.base_url}/hdi_check", json={"drug": drug, "herb": herb}
            )
            _check(r)
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"found": False}
            raise

    async def bilingual_term(self, term: str, languages: list[str]) -> dict[str, Any]:
        """POST /bilingual_term (to be added on scoped_server). Falls back to empty result."""
        try:
            r = await self._client.post(
                f"{self.base_url}/bilingual_term",
                json={"term": term, "languages": languages},
            )
            _check(r)
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {}
            raise
