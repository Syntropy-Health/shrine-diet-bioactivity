"""
Knowledge Graph Metrics — Inspect and report on the LightRAG/Neo4j KG state.

Generates a markdown report with entity/relationship breakdowns, data quality
flags, and ingestion session history. Reports are saved to data/kg-reports/.

Usage:
    python kg_metrics.py --config local                    # Print to stdout
    python kg_metrics.py --config local --save             # Save to data/kg-reports/
    python kg_metrics.py --config local --save --json      # Also save JSON metrics
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
REPORTS_DIR = SCRIPT_DIR / ".." / "data" / "kg-reports"


def get_neo4j_metrics(uri: str, user: str, password: str) -> dict:
    """Query Neo4j for comprehensive KG metrics."""
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password))
    session = driver.session()

    metrics: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "neo4j_uri": uri,
        "entities": {},
        "relationships": {},
        "data_quality": {},
        "totals": {},
    }

    # Entity counts by type
    for r in session.run(
        "MATCH (n) RETURN n.entity_type AS type, COUNT(n) AS count ORDER BY count DESC"
    ):
        entity_type = r["type"] or "UNKNOWN"
        metrics["entities"][entity_type] = r["count"]

    # Relationship counts by type
    for r in session.run(
        "MATCH ()-[r]->() RETURN type(r) AS type, COUNT(r) AS count ORDER BY count DESC"
    ):
        metrics["relationships"][r["type"]] = r["count"]

    # Totals
    metrics["totals"]["nodes"] = session.run(
        "MATCH (n) RETURN COUNT(n) AS c"
    ).single()["c"]
    metrics["totals"]["edges"] = session.run(
        "MATCH ()-[r]->() RETURN COUNT(r) AS c"
    ).single()["c"]

    # Workspace labels
    workspaces = []
    for r in session.run(
        "MATCH (n) RETURN DISTINCT [l IN labels(n) WHERE NOT l IN ['Entity','Episodic','Community']][0] AS ws"
    ):
        if r["ws"]:
            workspaces.append(r["ws"])
    metrics["workspaces"] = sorted(set(workspaces))

    # Data quality checks
    unknown_count = metrics["entities"].get("UNKNOWN", 0)
    metrics["data_quality"]["unknown_type_nodes"] = unknown_count

    # Check for empty descriptions
    empty_desc = session.run(
        "MATCH (n) WHERE n.description IS NULL OR n.description = '' OR n.description = 'UNKNOWN' "
        "RETURN COUNT(n) AS c"
    ).single()["c"]
    metrics["data_quality"]["empty_descriptions"] = empty_desc

    # Check for orphan nodes (no relationships)
    orphans = session.run(
        "MATCH (n) WHERE NOT (n)--() RETURN COUNT(n) AS c"
    ).single()["c"]
    metrics["data_quality"]["orphan_nodes"] = orphans

    # Sample entities per type (for quick sanity check)
    samples = {}
    for entity_type in list(metrics["entities"].keys())[:6]:
        r = session.run(
            f'MATCH (n {{entity_type: "{entity_type}"}}) '
            "RETURN n.entity_id AS id, n.description AS desc LIMIT 2"
        )
        samples[entity_type] = [
            {"id": rec["id"], "desc": str(rec["desc"] or "")[:120]}
            for rec in r
        ]
    metrics["samples"] = samples

    session.close()
    driver.close()
    return metrics


def format_markdown(metrics: dict) -> str:
    """Format metrics as a markdown report."""
    lines = [
        f"# KG Metrics Report",
        f"",
        f"**Generated:** {metrics['timestamp']}",
        f"**Neo4j:** `{metrics['neo4j_uri']}`",
        f"**Workspaces:** {', '.join(metrics['workspaces']) or '(none)'}",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total nodes | {metrics['totals']['nodes']:,} |",
        f"| Total edges | {metrics['totals']['edges']:,} |",
        f"",
        f"## Entities by Type",
        f"",
        f"| Entity Type | Count | % |",
        f"|-------------|-------|---|",
    ]

    total_nodes = metrics["totals"]["nodes"] or 1
    for etype, count in sorted(
        metrics["entities"].items(), key=lambda x: x[1], reverse=True
    ):
        pct = count / total_nodes * 100
        lines.append(f"| {etype} | {count:,} | {pct:.1f}% |")

    lines.extend([
        f"",
        f"## Relationships by Type",
        f"",
        f"| Relationship Type | Count |",
        f"|-------------------|-------|",
    ])
    for rtype, count in sorted(
        metrics["relationships"].items(), key=lambda x: x[1], reverse=True
    ):
        lines.append(f"| {rtype} | {count:,} |")

    lines.extend([
        f"",
        f"## Data Quality",
        f"",
        f"| Check | Count | Status |",
        f"|-------|-------|--------|",
    ])
    dq = metrics["data_quality"]
    for check, count in dq.items():
        status = "OK" if count == 0 else f"WARN ({count:,})"
        lines.append(f"| {check} | {count:,} | {status} |")

    lines.extend([
        f"",
        f"## Sample Entities",
        f"",
    ])
    for etype, samples in metrics.get("samples", {}).items():
        lines.append(f"### {etype}")
        for s in samples:
            lines.append(f"- **{s['id']}**: {s['desc']}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="KG metrics and reporting")
    parser.add_argument("--config", choices=["local", "production"], default="local")
    parser.add_argument("--save", action="store_true", help="Save report to data/kg-reports/")
    parser.add_argument("--json", action="store_true", help="Also save raw JSON metrics")
    args = parser.parse_args()

    config_path = SCRIPT_DIR / f"config_{args.config}.env"
    load_dotenv(config_path, override=True)

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    print(f"Connecting to {uri}...", file=sys.stderr)
    metrics = get_neo4j_metrics(uri, user, password)
    report = format_markdown(metrics)

    # Always print to stdout
    print(report)

    if args.save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        md_path = REPORTS_DIR / f"kg-metrics-{ts}.md"
        md_path.write_text(report)
        print(f"\nReport saved to {md_path}", file=sys.stderr)

        if args.json:
            json_path = REPORTS_DIR / f"kg-metrics-{ts}.json"
            json_path.write_text(json.dumps(metrics, indent=2))
            print(f"JSON saved to {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
