"""
Bootstrap migration: tag every pre-existing Neo4j node and relationship
with ``scope='shared'`` and create scope property indexes.

Run this **once** against a Neo4j instance that was populated before
multi-tenant scoping existed. After this script runs, every read
through ``ScopedNeo4JStorage`` with ``scope_filter=['shared', ...]``
will return the legacy shared data plus whatever tenant-scoped data
has been ingested on top.

The script is idempotent — running it twice is a no-op aside from
counts printed. A preflight in ``scoped_server.py`` rejects reads
until this script has left zero ``scope IS NULL`` nodes behind.

Usage:
    python bootstrap_scope.py --config local --dry-run
    python bootstrap_scope.py --config local
    python bootstrap_scope.py --config production

Exits non-zero on any Neo4j error or when the post-migration sanity
check finds residual NULL-scope rows.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

SCRIPT_DIR = Path(__file__).parent
SHARED_SCOPE = "shared"
NODE_SCOPE_INDEX = "shared_diet_kg_node_scope"
EDGE_SCOPE_INDEX = "shared_diet_kg_edge_scope"


def _load_config(config_name: str) -> None:
    """Load config_<name>.env from lightrag/."""
    env_file = SCRIPT_DIR / f"config_{config_name}.env"
    if not env_file.exists():
        raise FileNotFoundError(f"Config file not found: {env_file}")
    load_dotenv(env_file, override=True)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} not set — check config_*.env"
        )
    return value


def _safe_label(label: str) -> str:
    """Match LightRAG's Neo4j workspace-label sanitisation."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in label)


def count_untagged(driver, workspace_label: str) -> tuple[int, int]:
    """Return (untagged_nodes, untagged_relationships)."""
    with driver.session() as session:
        node_count = session.run(
            f"MATCH (n:`{workspace_label}`) "
            "WHERE n.scope IS NULL RETURN count(n) AS c"
        ).single()["c"]
        rel_count = session.run(
            f"MATCH (n:`{workspace_label}`)-[r]-() "
            "WHERE r.scope IS NULL RETURN count(r) AS c"
        ).single()["c"]
    return int(node_count), int(rel_count)


def tag_shared(driver, workspace_label: str) -> tuple[int, int]:
    """Tag untagged nodes and relationships with scope='shared'.

    Returns (tagged_nodes, tagged_relationships).
    """
    with driver.session() as session:
        node_result = session.run(
            f"MATCH (n:`{workspace_label}`) "
            "WHERE n.scope IS NULL "
            "SET n.scope = $scope "
            "RETURN count(n) AS c",
            scope=SHARED_SCOPE,
        ).single()
        rel_result = session.run(
            f"MATCH (:`{workspace_label}`)-[r]-(:`{workspace_label}`) "
            "WHERE r.scope IS NULL "
            "SET r.scope = $scope "
            "RETURN count(r) AS c",
            scope=SHARED_SCOPE,
        ).single()
    return int(node_result["c"]), int(rel_result["c"])


def create_indexes(driver, workspace_label: str) -> None:
    """Create property indexes on node.scope and relationship scope.

    Uses ``IF NOT EXISTS`` so repeated runs are safe.
    """
    with driver.session() as session:
        session.run(
            f"CREATE INDEX {NODE_SCOPE_INDEX} IF NOT EXISTS "
            f"FOR (n:`{workspace_label}`) ON (n.scope)"
        ).consume()
        session.run(
            f"CREATE INDEX {EDGE_SCOPE_INDEX} IF NOT EXISTS "
            "FOR ()-[r]-() ON (r.scope)"
        ).consume()


def verify_clean(driver, workspace_label: str) -> None:
    """Post-migration check: no untagged rows remain. Raises on failure."""
    n, r = count_untagged(driver, workspace_label)
    if n or r:
        raise RuntimeError(
            f"Bootstrap incomplete: {n} nodes and {r} relationships still "
            "have scope IS NULL. Investigate and re-run."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--config",
        default="local",
        choices=["local", "production"],
        help="Which config_<name>.env to load from lightrag/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report untagged counts only — no writes, no index creation",
    )
    args = parser.parse_args()

    _load_config(args.config)
    uri = _require_env("NEO4J_URI")
    user = _require_env("NEO4J_USERNAME")
    password = _require_env("NEO4J_PASSWORD")
    workspace = os.environ.get("WORKSPACE", "unified_diet_kg")
    workspace_label = _safe_label(workspace)

    print(f"[bootstrap-scope] config={args.config}")
    print(f"[bootstrap-scope] workspace={workspace} (label={workspace_label})")
    print(f"[bootstrap-scope] neo4j={uri}")

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        n_before, r_before = count_untagged(driver, workspace_label)
        print(
            f"[bootstrap-scope] BEFORE: "
            f"{n_before} untagged nodes, {r_before} untagged relationships"
        )

        if args.dry_run:
            print("[bootstrap-scope] DRY RUN — no writes")
            return 0

        tagged_n, tagged_r = tag_shared(driver, workspace_label)
        print(
            f"[bootstrap-scope] TAGGED: "
            f"{tagged_n} nodes, {tagged_r} relationships set scope='{SHARED_SCOPE}'"
        )

        create_indexes(driver, workspace_label)
        print(
            f"[bootstrap-scope] INDEXES: "
            f"{NODE_SCOPE_INDEX} + {EDGE_SCOPE_INDEX} ensured"
        )

        verify_clean(driver, workspace_label)
        print("[bootstrap-scope] VERIFY: no untagged rows remain ✓")

    return 0


if __name__ == "__main__":
    sys.exit(main())
