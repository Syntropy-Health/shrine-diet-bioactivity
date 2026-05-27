"""Modal cloud runner for the LightRAG KG ingestion.

Why a cloud runner: the local WSL2 → Aura TLS path drops mid-write
(SSLV3_ALERT_BAD_RECORD_MAC) and runs out of memory on multi-hour
ingests. Modal provides a clean network path to Aura and stable
container resources.

Setup (one-time):
    # Save the Infisical machine-identity token as a Modal Secret.
    # The function uses this to fetch the actual Aura + OpenRouter
    # credentials from Infisical at runtime, so secrets never live on
    # disk anywhere in the runner image.
    modal secret create kg-mcp-infisical \\
        INFISICAL_TOKEN=ak-gs3IFfLQcx7Eyo0toi36wQ

    # Upload the herbal_botanicals.db (≈ 6.3 GB) to the Modal volume.
    # Runs once; subsequent ingestion invocations reuse the volume.
    modal volume create kg-mcp-data
    modal volume put kg-mcp-data \\
        shrine-diet-bioactivity/data_local/herbal_botanicals.db \\
        /data/herbal_botanicals.db

Run:
    modal run scripts/modal_ingest_runner.py::ingest

Idempotent — re-runs MERGE into Aura, filling whatever's missing.
"""
from __future__ import annotations

import os
import subprocess
import sys

import modal

# ─── Modal app + image ────────────────────────────────────────────────────

APP_NAME = "kg-mcp-ingest"

# Image: Python + the runtime deps the ingest needs. lightrag-hku is the
# upstream LightRAG package — must match the local-dev pin.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "lightrag-hku>=1.4",
        "neo4j>=5.26",
        "numpy>=1.26",
        "httpx>=0.27",
        "python-dotenv>=1.0",
        "nano-vectordb>=0.0.4",
    )
    # The lightrag/ source dir holds the custom storages + ingest script.
    # Mount it from the repo so we don't have to bake a per-commit image.
    .add_local_dir(
        local_path=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "lightrag",
        ),
        remote_path="/app/lightrag",
    )
)

app = modal.App(APP_NAME, image=image)

# Persistent volume holding the SQLite source DB. The ingest reads it
# heavily but never modifies it — so the volume is read-mostly.
data_volume = modal.Volume.from_name("kg-mcp-data", create_if_missing=True)

# Secret containing the Infisical machine-identity token. Fetched
# secrets (Aura, OpenRouter) are loaded into env at function start.
infisical_secret = modal.Secret.from_name("kg-mcp-infisical")


# ─── Infisical fetch helper ───────────────────────────────────────────────


INFISICAL_WORKSPACE = "687cab01-ccc1-4789-99a9-1214bd268f2b"
INFISICAL_ENV = "prod"
INFISICAL_PATH = "/research/shrine-diet-bioactivity"
REQUIRED_KEYS = (
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "OPENROUTER_API_KEY",
)


def _load_secrets_into_env(token: str) -> None:
    """Fetch the canonical Aura + OpenRouter creds from Infisical and
    push them into os.environ for the ingestion subprocess.
    """
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.get(
        "https://app.infisical.com/api/v3/secrets/raw",
        params={
            "workspaceId": INFISICAL_WORKSPACE,
            "environment": INFISICAL_ENV,
            "secretPath": INFISICAL_PATH,
        },
        headers=headers,
        timeout=30.0,
    )
    r.raise_for_status()
    secrets = {s["secretKey"]: s["secretValue"] for s in r.json().get("secrets", [])}

    missing = [k for k in REQUIRED_KEYS if k not in secrets and k != "NEO4J_DATABASE"]
    if missing:
        raise RuntimeError(f"Infisical missing required keys: {missing}")

    for k in REQUIRED_KEYS:
        if k in secrets:
            os.environ[k] = secrets[k]
    # Length-only debug — never echo the secret value
    print(
        "secrets loaded:",
        {k: f"len={len(os.environ.get(k, ''))}" for k in REQUIRED_KEYS},
    )


# ─── The ingest function ──────────────────────────────────────────────────


@app.function(
    image=image,
    secrets=[infisical_secret],
    volumes={"/data": data_volume},
    timeout=60 * 60 * 4,  # 4 hours — generous; idempotent so safe to re-run
    cpu=2.0,
    memory=8192,  # 8 GB — local v6 hit OOM around 3 GB
)
def ingest(
    only_relationships: str = (
        "CONTAINS_COMPOUND,FOUND_IN_FOOD,TREATS_SYMPTOM,ASSOCIATED_WITH_DISEASE,"
        "TARGETS_PROTEIN,COMPOUND_TREATS_DISEASE,COMPOUND_MARKER_FOR_DISEASE,"
        "PATHWAY_INCLUDES_TARGET,MAPS_TO_DISEASE"
    ),
    max_relationships: int = 50_000,
    batch_size: int = 2000,
) -> dict:
    """Run ingest_unified.py against the Aura instance referenced in
    Infisical, restricted to the MCP-relevant edge types. Returns a
    summary of the final Aura node/edge counts.
    """
    token = os.environ.get("INFISICAL_TOKEN")
    if not token:
        raise RuntimeError("INFISICAL_TOKEN not present — check Modal Secret")
    _load_secrets_into_env(token)

    # Vectors stay in NanoVectorDB locally (in the container's ephemeral FS)
    # — the Aura Free instance cannot hold them.
    os.environ["LIGHTRAG_VECTOR_STORAGE"] = "NanoVectorDBStorage"

    # The ingest expects the SQLite at ../data_local/ relative to the
    # lightrag/ dir. We mount the volume at /data — symlink the file in.
    os.makedirs("/app/data_local", exist_ok=True)
    src = "/data/herbal_botanicals.db"
    dst = "/app/data_local/herbal_botanicals.db"
    if not os.path.exists(dst):
        os.symlink(src, dst)

    cmd = [
        sys.executable, "-u", "ingest_unified.py",
        "--config", "local",
        "--batch-size", str(batch_size),
        "--max-relationships", str(max_relationships),
        "--only-relationships", only_relationships,
    ]
    print("running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd="/app/lightrag", check=False)
    print(f"ingest exit code: {proc.returncode}", flush=True)

    # Final Aura snapshot
    from neo4j import GraphDatabase
    with GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    ) as drv:
        with drv.session() as s:
            nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            by_rel = {
                r["t"]: r["c"]
                for r in s.run(
                    "MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c"
                )
            }
    return {
        "exit_code": proc.returncode,
        "aura_nodes": nodes,
        "aura_rels": rels,
        "edges_by_type": by_rel,
    }


@app.local_entrypoint()
def main(
    only_relationships: str = (
        "CONTAINS_COMPOUND,FOUND_IN_FOOD,TREATS_SYMPTOM,ASSOCIATED_WITH_DISEASE,"
        "TARGETS_PROTEIN,COMPOUND_TREATS_DISEASE,COMPOUND_MARKER_FOR_DISEASE,"
        "PATHWAY_INCLUDES_TARGET,MAPS_TO_DISEASE"
    ),
    max_relationships: int = 50_000,
    batch_size: int = 2000,
):
    out = ingest.remote(
        only_relationships=only_relationships,
        max_relationships=max_relationships,
        batch_size=batch_size,
    )
    print("RESULT:", out)
