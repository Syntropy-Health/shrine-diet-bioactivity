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
        r.raise_for_status()
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
        r.raise_for_status()
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
        r.raise_for_status()
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
            r.raise_for_status()
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
            r.raise_for_status()
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
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {}
            raise
