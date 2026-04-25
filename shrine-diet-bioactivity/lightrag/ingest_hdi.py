"""Ingest HDI-Safe 50 herb-drug interactions into LightRAG via ainsert_custom_kg.

Loads ``hdi_safe_50.json`` (path from data_sources.yaml), constructs a
custom-KG payload with Herb / Drug nodes and INTERACTS_WITH edges, and
writes them into the same LightRAG workspace as the unified ingest so
the Safety Reviewer can query them alongside the rest of the diet KG.

Run:
    python ingest_hdi.py            # writes to Aura
    python ingest_hdi.py --dry-run  # prints counts only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from config_loader import load_data_sources, load_ingest_params
from entity_schema import describe_interacts_with
from lightrag_init import init_lightrag

# Project root = shrine-diet-bioactivity/ (one level above this file's dir)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_hdi_path() -> Path:
    """Resolve hdi_safe_50.json path from data_sources.yaml."""
    cfg = load_data_sources()
    raw = Path(cfg.paths.hdi_safe_50)
    return raw if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()


def build_payload(hdis: list[dict[str, Any]], severity_weights: dict[str, float]) -> dict:
    """Build a LightRAG custom-KG payload from HDI-Safe 50 entries."""
    herbs: dict[str, dict] = {}
    drugs: dict[str, dict] = {}
    relationships: list[dict] = []

    for entry in hdis:
        latin = entry["herb"]["latin"]
        drug_name = entry["drug"]["name"]
        # entity_id naming stays consistent with ingest_unified (scientific name)
        # so HDI edges connect to existing Herb nodes when latin matches.
        herb_id = latin
        drug_id = f"Drug:{drug_name}"

        herbs[herb_id] = {
            "entity_name": herb_id,
            "entity_type": "Herb",
            "description": (
                f"{entry['herb']['name']} ({latin}) — herb with documented "
                f"drug interactions in NIH ODS / MSK About Herbs / LiverTox."
            ),
            "scope": "shared",
            "source_id": f"hdi-safe-50:{entry['id']}",
        }

        atc_part = (
            f" (ATC {entry['drug']['atc']})" if entry["drug"].get("atc") else ""
        )
        drugs[drug_id] = {
            "entity_name": drug_id,
            "entity_type": "Drug",
            "description": f"Drug {drug_name}{atc_part}",
            "scope": "shared",
            "source_id": f"hdi-safe-50:{entry['id']}",
        }

        weight = severity_weights.get(entry["severity"], 0.5)
        desc = describe_interacts_with(
            {
                "herb_name": entry["herb"]["name"],
                "drug_name": drug_name,
                "severity": entry["severity"],
                "mechanism_class": entry["mechanism_class"],
                "evidence_tier": entry["evidence_tier"],
            }
        )
        relationships.append(
            {
                "src_id": herb_id,
                "tgt_id": drug_id,
                "description": desc,
                "keywords": (
                    f"HDI {entry['mechanism_class']} {entry['severity']} "
                    f"herb-drug-interaction"
                ),
                "weight": weight,
                "scope": "shared",
                "source_id": f"hdi-safe-50:{entry['id']}",
                # Custom properties — LightRAG forwards via upsert_edge.
                # NOTE: not all backends persist non-standard fields; the
                # Neo4j backend does, see scoped_neo4j_storage.upsert_edge.
                "severity": entry["severity"],
                "mechanism_class": entry["mechanism_class"],
                "evidence_tier": entry["evidence_tier"],
            }
        )

    entities = list(herbs.values()) + list(drugs.values())
    # The payload chunk is required so source_id mapping resolves cleanly.
    chunk_content = (
        f"HDI-Safe 50 reference set — {len(relationships)} curated herb-drug "
        f"interactions across mechanism classes "
        f"({sorted({r['mechanism_class'] for r in relationships})})."
    )
    return {
        "chunks": [
            {
                "content": chunk_content,
                "source_id": "hdi-safe-50",
                "file_path": "research-journal/shared/hdi_safe_50.json",
            }
        ],
        "entities": [{**e, "source_id": "hdi-safe-50"} for e in entities],
        "relationships": [
            {**r, "source_id": "hdi-safe-50"} for r in relationships
        ],
    }


async def _ingest_async(payload: dict) -> None:
    rag, workspace = init_lightrag()
    print(f"  Workspace: {workspace}")
    await rag.initialize_storages()
    try:
        await rag.ainsert_custom_kg(payload)
    finally:
        await rag.finalize_storages()


def _label_drug_nodes_and_promote_edges(payload: dict) -> None:
    """Tag Drug/Herb nodes and promote HDI edges to :INTERACTS_WITH.

    LightRAG persists every edge as a generic ``:DIRECTED`` relationship
    in Neo4j. The Safety Reviewer queries by ``:INTERACTS_WITH``, so we
    create a typed copy of each HDI edge alongside the LightRAG-managed
    ``:DIRECTED`` edge (LightRAG keeps using the generic edge for its
    retrieval; the typed edge is what Cypher consumers query).
    """
    from neo4j import GraphDatabase  # local import to keep dry-run light

    from entity_schema import safe_label

    workspace = os.getenv("WORKSPACE", "unified_diet_kg")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    ws = safe_label(workspace)
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            # 1. Promote node labels for visual exploration / typed queries.
            for etype in ("Herb", "Drug"):
                et = safe_label(etype)
                result = s.run(
                    f"MATCH (n:`{ws}`) WHERE n.entity_type = $etype "
                    f"SET n:`{et}` RETURN COUNT(n) AS count",
                    etype=etype,
                ).single()
                print(f"  :{etype} → {result['count']} nodes")

            # 2. Create typed :INTERACTS_WITH edges in addition to the
            # LightRAG-managed :DIRECTED edges. We encode every edge by
            # (src, tgt) pair from the payload — this is idempotent
            # because we use MERGE.
            promoted = 0
            for rel in payload["relationships"]:
                s.run(
                    f"""
                    MATCH (h:`{ws}` {{entity_id: $src}})
                    MATCH (d:`{ws}` {{entity_id: $tgt}})
                    MERGE (h)-[r:INTERACTS_WITH]->(d)
                    SET r.description = $desc,
                        r.keywords = $keywords,
                        r.weight = $weight,
                        r.severity = $severity,
                        r.mechanism_class = $mech,
                        r.evidence_tier = $tier,
                        r.source_id = $source_id,
                        r.scope = 'shared'
                    """,
                    src=rel["src_id"],
                    tgt=rel["tgt_id"],
                    desc=rel["description"],
                    keywords=rel["keywords"],
                    weight=rel["weight"],
                    severity=rel["severity"],
                    mech=rel["mechanism_class"],
                    tier=rel["evidence_tier"],
                    source_id=rel["source_id"],
                )
                promoted += 1
            print(f"  :INTERACTS_WITH → {promoted} edges promoted")


def main(dry_run: bool = False) -> None:
    """Entrypoint — load env from .env + per-config env, then ingest."""
    # 1. Aura creds from gitignored .env at project root
    load_dotenv(PROJECT_ROOT / ".env")
    # 2. Embedding/storage knobs from config_local.env (override-safe)
    load_dotenv(Path(__file__).parent / "config_local.env", override=False)

    params = load_ingest_params()
    severity_weights = {
        "severe": params.hdi_severity_weights.severe,
        "moderate": params.hdi_severity_weights.moderate,
        "mild": params.hdi_severity_weights.mild,
    }

    hdi_path = _resolve_hdi_path()
    print(f"Loading HDI-Safe 50 from {hdi_path}")
    hdis = json.loads(hdi_path.read_text())
    print(f"  {len(hdis)} HDI entries loaded")

    payload = build_payload(hdis, severity_weights)
    print(
        f"  Payload: {len(payload['entities'])} entities, "
        f"{len(payload['relationships'])} relationships"
    )

    if dry_run:
        print("DRY RUN — no data written.")
        return

    asyncio.run(_ingest_async(payload))
    _label_drug_nodes_and_promote_edges(payload)
    print(f"✅ Ingested {len(payload['relationships'])} HDI edges into Aura")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
