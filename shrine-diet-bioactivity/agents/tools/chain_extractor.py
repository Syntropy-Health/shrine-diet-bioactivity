# shrine-diet-bioactivity/agents/tools/chain_extractor.py
"""SQLite-backed fallback chain extraction.
Implements the deterministic herb->compound->target->symptom traversal
used both as a LightRAG fallback and during prototyping before Aura ingest."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from agents.models import KGEdge, KGResult, ProvenanceChain
from config_loader import load_data_sources  # type: ignore[import-not-found]

QueryMode = Literal["local", "global", "hybrid", "naive", "mix"]


def _connect() -> sqlite3.Connection:
    cfg = load_data_sources()
    # config_loader resolves relative paths from the shrine-diet-bioactivity root.
    # At runtime the CWD may differ, so resolve relative to the config file's parent.
    db_path_str = cfg.paths.sqlite_db
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        # Resolve relative to the shrine-diet-bioactivity package root
        # (one level up from agents/, which is one level up from tools/)
        _pkg_root = Path(__file__).resolve().parents[2]
        db_path = _pkg_root / db_path_str
    return sqlite3.connect(db_path)


def extract_chains_from_sqlite(question: str, mode: QueryMode = "hybrid", k: int = 10) -> KGResult:
    """Deterministic fallback: tokenize question, find matching herbs/symptoms,
    traverse herb->compound->target->symptom chains. Returns top-k by edge weight."""
    tokens = [t.lower() for t in question.split() if len(t) > 2]
    if not tokens:
        return KGResult(chains=[], raw_subgraph_node_count=0, raw_subgraph_edge_count=0, query_mode=mode)

    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        # Anchor herbs by scientific_name OR common_name to handle colloquial terms
        # (e.g., "ginger" matches common_name "Ginger" -> Zingiber officinale)
        like_sci = " OR ".join(["LOWER(scientific_name) LIKE ?"] * len(tokens))
        like_cmn = " OR ".join(["LOWER(common_name) LIKE ?"] * len(tokens))
        params = [f"%{t}%" for t in tokens]
        herb_rows = conn.execute(
            f"SELECT id, scientific_name FROM herbs WHERE ({like_sci}) OR ({like_cmn}) LIMIT 5",
            params + params,
        ).fetchall()

        chains: list[ProvenanceChain] = []
        node_set: set[str] = set()
        edge_count = 0
        for h in herb_rows:
            cmpd_rows = conn.execute(
                "SELECT c.id, c.name FROM herb_compounds hc "
                "JOIN compounds c ON hc.compound_id = c.id "
                "WHERE hc.herb_id = ? LIMIT 3",
                (h["id"],),
            ).fetchall()
            for c in cmpd_rows:
                edges = [KGEdge(
                    src=h["scientific_name"], edge="CONTAINS_COMPOUND",
                    tgt=c["name"], source_id=f"duke:{h['id']}.{c['id']}",
                    weight=0.85, evidence_tier="traditional",
                )]
                node_set.add(h["scientific_name"])
                node_set.add(c["name"])
                edge_count += 1

                tgt_rows = conn.execute(
                    "SELECT t.name FROM compound_targets ct "
                    "JOIN targets t ON ct.target_id = t.id "
                    "WHERE ct.compound_id = ? LIMIT 2",
                    (c["id"],),
                ).fetchall()
                for tgt in tgt_rows:
                    edges.append(KGEdge(
                        src=c["name"], edge="TARGETS_PROTEIN",
                        tgt=tgt["name"], source_id=f"cmaup:{c['id']}",
                        weight=0.7, evidence_tier="experimental",
                    ))
                    node_set.add(tgt["name"])
                    edge_count += 1

                chains.append(ProvenanceChain(edges=edges))
                if len(chains) >= k:
                    break
            if len(chains) >= k:
                break

        return KGResult(
            chains=chains[:k],
            raw_subgraph_node_count=len(node_set),
            raw_subgraph_edge_count=edge_count,
            query_mode=mode,
        )
    finally:
        conn.close()
