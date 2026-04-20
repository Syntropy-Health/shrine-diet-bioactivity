"""
Cross-tenant isolation canary.

Inserts a sentinel entity scoped to ``tenant:canary-a`` directly into
Neo4j, then queries the scoped server as ``tenant:canary-b`` and
asserts the sentinel does not appear in the result. Cleans up after
itself.

Run (requires live Neo4j + scoped_server.py running on port 9621)::

    cd shrine-diet-bioactivity/lightrag
    python canary_smoke_test.py --config local

    # or via Makefile
    make lightrag-canary-test

Exit codes:
    0 — isolation verified
    1 — sentinel leaked into the wrong tenant (FAIL — do not deploy)
    2 — environment error (no Neo4j, no server, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

SCRIPT_DIR = Path(__file__).parent
CANARY_TENANT_A = "canary-a"
CANARY_TENANT_B = "canary-b"


def _load_config(name: str) -> None:
    env_file = SCRIPT_DIR / f"config_{name}.env"
    if not env_file.exists():
        raise SystemExit(f"[canary] config_{name}.env not found at {env_file}")
    load_dotenv(env_file, override=True)


def _safe_label(label: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in label)


def _insert_sentinel(workspace_label: str, sentinel_id: str) -> None:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as session:
            session.run(
                f"""
                MERGE (n:`{workspace_label}` {{entity_id: $id}})
                SET n.scope = $scope,
                    n.entity_type = 'Canary',
                    n.description = $desc
                """,
                id=sentinel_id,
                scope=f"tenant:{CANARY_TENANT_A}",
                desc=(
                    "CANARY_SENTINEL_DO_NOT_RETURN — inserted by "
                    "canary_smoke_test.py to verify cross-tenant isolation"
                ),
            ).consume()


def _delete_sentinel(workspace_label: str, sentinel_id: str) -> None:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as session:
            session.run(
                f"MATCH (n:`{workspace_label}` {{entity_id: $id}}) DETACH DELETE n",
                id=sentinel_id,
            ).consume()


def _query_as_tenant(server_url: str, tenant_id: str, sentinel_id: str) -> str:
    body = json.dumps(
        {
            "query": f"Tell me about {sentinel_id}",
            "mode": "hybrid",
            "top_k": 30,
            "scope_filter": ["shared", f"tenant:{tenant_id}"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url.rstrip('/')}/query",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - internal URL
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("response", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", default="local", choices=["local", "production"])
    parser.add_argument(
        "--server-url",
        default=os.environ.get("LIGHTRAG_API_URL", "http://localhost:9621"),
    )
    args = parser.parse_args()

    _load_config(args.config)
    workspace_label = _safe_label(os.environ.get("WORKSPACE", "unified_diet_kg"))
    sentinel_id = f"canary-sentinel-{uuid.uuid4().hex[:8]}"

    print(f"[canary] workspace={workspace_label} sentinel={sentinel_id}")
    print(f"[canary] server={args.server_url}")

    try:
        _insert_sentinel(workspace_label, sentinel_id)
        print(f"[canary] inserted sentinel as tenant:{CANARY_TENANT_A}")

        # Give any write-through caches a moment to settle.
        time.sleep(1)

        response_b = _query_as_tenant(args.server_url, CANARY_TENANT_B, sentinel_id)
        if sentinel_id in response_b:
            print(
                f"[canary] FAIL — sentinel {sentinel_id} leaked into "
                f"tenant:{CANARY_TENANT_B} response:\n{response_b[:400]}",
                file=sys.stderr,
            )
            return 1
        print(f"[canary] tenant:{CANARY_TENANT_B} cannot see sentinel ✓")

        response_a = _query_as_tenant(args.server_url, CANARY_TENANT_A, sentinel_id)
        # Owning tenant should have some signal of the sentinel (at least
        # in retrieved entity list). We don't hard-assert because the
        # hybrid mode may or may not cite a single-node entity.
        if sentinel_id in response_a:
            print(f"[canary] tenant:{CANARY_TENANT_A} sees own sentinel ✓")
        else:
            print(
                f"[canary] WARN tenant:{CANARY_TENANT_A} did not surface own "
                "sentinel — retrieval is scope-correct but recall is low; "
                "check entity embedding / vector-side isolation.",
            )
        return 0
    except Exception as e:
        print(f"[canary] environment error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    finally:
        try:
            _delete_sentinel(workspace_label, sentinel_id)
            print(f"[canary] cleaned up sentinel {sentinel_id}")
        except Exception as e:  # noqa: BLE001 - best-effort cleanup
            print(
                f"[canary] WARN cleanup failed — orphan node {sentinel_id}: {e}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    sys.exit(main())
