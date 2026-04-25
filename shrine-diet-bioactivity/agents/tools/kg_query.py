# shrine-diet-bioactivity/agents/tools/kg_query.py
"""KG-query tool registered with AG2. Tries LightRAG /query first;
falls back to direct SQLite reads when LightRAG is unreachable.
Returns a typed KGResult Pydantic model so panel agents can reason
over structured chains rather than free-form text."""
from __future__ import annotations

import os
from typing import Literal

import requests

from agents.models import KGEdge, KGResult, ProvenanceChain
from agents.tools.chain_extractor import extract_chains_from_sqlite

QueryMode = Literal["local", "global", "hybrid", "naive", "mix"]
_VALID_MODES = {"local", "global", "hybrid", "naive", "mix"}


class KGQueryError(RuntimeError):
    pass


def _lightrag_query(question: str, mode: QueryMode) -> dict:
    base = os.environ.get("LIGHTRAG_BASE_URL", "http://localhost:9621")
    try:
        r = requests.post(f"{base}/query", json={"query": question, "mode": mode}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        raise KGQueryError(f"LightRAG unreachable: {e}") from e
    data = r.json()
    return {
        "chains": data.get("chains", []),
        "node_count": data.get("node_count", 0),
        "edge_count": data.get("edge_count", 0),
    }


def kg_query(question: str, mode: QueryMode = "hybrid") -> KGResult:
    """Query the unified diet KG; return typed chains.
    Tries LightRAG first; on failure, falls back to deterministic SQLite traversal."""
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; valid: {sorted(_VALID_MODES)}")
    try:
        raw = _lightrag_query(question, mode)
        chains = [ProvenanceChain(edges=[KGEdge(**e) for e in c["edges"]]) for c in raw["chains"]]
        return KGResult(
            chains=chains,
            raw_subgraph_node_count=raw["node_count"],
            raw_subgraph_edge_count=raw["edge_count"],
            query_mode=mode,
        )
    except KGQueryError:
        return extract_chains_from_sqlite(question, mode)
