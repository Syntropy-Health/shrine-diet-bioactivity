"""Capture the current scope tagging state of the Aura KG.

Why: scope='shared' is the policy contract for open-source data. This
script provides an audit-quality snapshot a paper reviewer (or future
ingestion job) can use to verify the contract is intact.

The snapshot is keyed on (scope, source_prefix) so we can spot:
  - any scope IS NULL leakage (re-run bootstrap_scope.py if found)
  - any unexpected tenant scope on what should be open-source
  - per-source counts to support deduplication on future ingestion

Run:
    python scripts/capture_scope_state.py
    python scripts/capture_scope_state.py --out /tmp/scope-state.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_LABEL = os.environ.get("WORKSPACE", "unified_diet_kg")


def query(session, cypher: str) -> list[dict]:
    return [dict(r) for r in session.run(cypher)]


def render_table(rows: list[dict], cols: list[str], title: str) -> str:
    lines = [f"## {title}", ""]
    if not rows:
        lines.append("_no rows_")
        lines.append("")
        return "\n".join(lines)
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for r in rows:
        cells = [str(r.get(c, "")) for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def collect(session, ws: str) -> dict:
    """Run all the snapshot queries; return {section_name: rows}."""
    return {
        # All rel queries use directed `-[r]->` so each relationship is counted
        # once. Undirected `-[r]-` traverses each rel from both endpoints, doubling.
        "untagged": query(
            session,
            f"MATCH (n:`{ws}`) WHERE n.scope IS NULL RETURN count(n) AS untagged_nodes "
            "UNION ALL "
            f"MATCH (:`{ws}`)-[r]->(:`{ws}`) WHERE r.scope IS NULL RETURN count(r) AS untagged_nodes",
        ),
        "node_scope_dist": query(
            session,
            f"MATCH (n:`{ws}`) RETURN coalesce(n.scope, '<NULL>') AS scope, "
            "count(n) AS nodes ORDER BY nodes DESC",
        ),
        "rel_scope_dist": query(
            session,
            f"MATCH (:`{ws}`)-[r]->(:`{ws}`) RETURN coalesce(r.scope, '<NULL>') AS scope, "
            "count(r) AS rels ORDER BY rels DESC",
        ),
        "node_source_x_scope": query(
            session,
            f"MATCH (n:`{ws}`) "
            "WITH coalesce(n.scope, '<NULL>') AS scope, "
            "     split(coalesce(n.source_id, 'unknown:_'), ':')[0] AS source_prefix "
            "RETURN scope, source_prefix, count(*) AS nodes "
            "ORDER BY scope, nodes DESC",
        ),
        "rel_type_x_scope": query(
            session,
            f"MATCH (:`{ws}`)-[r]->(:`{ws}`) "
            "WITH coalesce(r.scope, '<NULL>') AS scope, type(r) AS rel_type "
            "RETURN scope, rel_type, count(*) AS rels "
            "ORDER BY scope, rels DESC",
        ),
        "indexes": query(
            session,
            "SHOW INDEXES YIELD name, entityType, type, labelsOrTypes, properties, state "
            "WHERE name STARTS WITH 'shared_diet_kg' "
            "RETURN name, entityType, type, labelsOrTypes, properties, state ORDER BY name",
        ),
    }


def render(snapshot: dict, ws: str) -> str:
    ts = datetime.now(timezone.utc).isoformat()

    untagged_nodes = snapshot["untagged"][0]["untagged_nodes"] if snapshot["untagged"] else 0
    untagged_rels = snapshot["untagged"][1]["untagged_nodes"] if len(snapshot["untagged"]) > 1 else 0

    parts = [
        "# Scope State Snapshot",
        "",
        f"_Generated {ts}_  ",
        f"_Workspace: `{ws}`_  ",
        "",
        "**Policy:** open-source data ingests under `scope='shared'`. ",
        "Tenant-scoped data uses `scope='tenant:<slug>'`. The scoped LightRAG ",
        "server enforces these scopes on every read. This snapshot is the ",
        "audit baseline — any deviation from the policy that this report can ",
        "see (NULL scopes, unexpected tenant tags) is a defect.",
        "",
        "## Health check",
        "",
        f"- Untagged nodes (scope IS NULL): **{untagged_nodes}** _(must be 0)_",
        f"- Untagged relationships (scope IS NULL): **{untagged_rels}** _(must be 0)_",
        f"- Bootstrap status: {'✅ clean' if untagged_nodes == 0 and untagged_rels == 0 else '❌ run bootstrap_scope.py'}",
        "",
        render_table(snapshot["node_scope_dist"], ["scope", "nodes"], "Node count by scope"),
        render_table(snapshot["rel_scope_dist"], ["scope", "rels"], "Relationship count by scope"),
        render_table(
            snapshot["node_source_x_scope"],
            ["scope", "source_prefix", "nodes"],
            "Nodes — scope × source prefix",
        ),
        render_table(
            snapshot["rel_type_x_scope"],
            ["scope", "rel_type", "rels"],
            "Relationships — scope × type",
        ),
        render_table(
            snapshot["indexes"],
            ["name", "entityType", "labelsOrTypes", "properties", "state"],
            "Scope indexes",
        ),
        "## Idempotency contract",
        "",
        "Future ingestion must:",
        "1. Set `scope='shared'` (or `tenant:<slug>`) on every node and edge it writes.",
        "2. Use `MERGE` (not `CREATE`) on `(entity_id)` for nodes and `(src, tgt, rel_type)` for edges.",
        "3. Re-running the same job over the same input must not increase counts in this snapshot.",
        "",
        "If a new dataset is being added: append a row to `data/manifest.yaml` ",
        "with the source slug, expected entity/edge counts, and primary join key. ",
        "Then run a fresh snapshot and diff against the prior one — only the ",
        "expected source-prefix counts should grow.",
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT.parent / "research-journal" / "shared" / "scope-state-snapshot.md"),
        help="Output Markdown path.",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    ws = os.environ.get("WORKSPACE", "unified_diet_kg")

    print(f"Querying {uri.split('//')[1].split('.')[0] if '//' in uri else uri} workspace={ws}", file=sys.stderr)
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            snap = collect(s, ws)

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(snap, ws))
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
