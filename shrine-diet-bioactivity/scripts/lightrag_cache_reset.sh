#!/usr/bin/env bash
# Reset the local LightRAG NanoVectorDB cache and verify the configured
# embedder dimension matches what NanoVectorDB will create on next start.
#
# Why this exists (ADR 0001): NanoVectorDB stores `embedding_dim` in each
# vdb_*.json file and refuses to load when it disagrees with the configured
# embedder dim. Switching embedder models without resetting the cache yields
# a cryptic AssertionError during server startup. This script makes the
# reset explicit and idempotent.
#
# It also closes the dual-cache-path defect: WORKING_DIR is interpreted
# relative to cwd, so two parallel caches can exist
# (shrine-diet-bioactivity/rag_storage_local/ and
#  shrine-diet-bioactivity/lightrag/rag_storage_local/). Both are wiped here.
#
# Usage:
#   bash scripts/lightrag_cache_reset.sh             # wipe + report
#   FORCE=1 bash scripts/lightrag_cache_reset.sh     # wipe even if no .env
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Both candidate cache locations. Wipe is idempotent — non-existent dirs are no-ops.
CANDIDATES=(
  "$ROOT/rag_storage_local"
  "$ROOT/lightrag/rag_storage_local"
)

# ─── Pre-flight: capture state before wipe ─────────────────────────────────
echo "Pre-reset state:" >&2
for d in "${CANDIDATES[@]}"; do
  if [[ -d "$d" ]]; then
    size=$(du -sh "$d" 2>/dev/null | awk '{print $1}')
    files=$(find "$d" -type f 2>/dev/null | wc -l)
    echo "  ${d#"$ROOT/"}: ${size}, ${files} file(s)" >&2
  else
    echo "  ${d#"$ROOT/"}: absent" >&2
  fi
done

# ─── Inspect dim recorded in any existing vdb files ────────────────────────
echo "" >&2
echo "Dim in existing vdb caches (before wipe):" >&2
python3 - <<'PY' || true
import json, glob, os
roots = [
    os.path.expanduser("~/projects/SyntropyHealth/apps/shrine-diet-bioactivity/shrine-diet-bioactivity/rag_storage_local"),
    os.path.expanduser("~/projects/SyntropyHealth/apps/shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/rag_storage_local"),
]
for r in roots:
    for f in glob.glob(os.path.join(r, "**", "vdb_*.json"), recursive=True):
        try:
            d = json.load(open(f))
            print(f"  {f.replace(os.path.expanduser('~'), '~')}: dim={d.get('embedding_dim')} rows={len(d.get('data',[]))}")
        except Exception as e:
            print(f"  {f}: error {e}")
PY

# ─── Wipe ──────────────────────────────────────────────────────────────────
echo "" >&2
echo "Wiping..." >&2
for d in "${CANDIDATES[@]}"; do
  if [[ -d "$d" ]]; then
    rm -rf "$d"
    echo "  removed ${d#"$ROOT/"}" >&2
  fi
done

# ─── Verify configured embedding dim is sane ───────────────────────────────
# Source .env if present, then config_local.env (without override).
if [[ -f ./.env ]]; then
  set -a; . ./.env; set +a
elif [[ -z "${FORCE:-}" ]]; then
  echo "" >&2
  echo "WARNING: no .env found; skipping dim sanity check. Re-run with FORCE=1 to skip this notice." >&2
  exit 0
fi

if [[ -f ./lightrag/config_local.env ]]; then
  # config_local.env may interpolate ${OPENROUTER_API_KEY} from .env; this is fine.
  set -a; . ./lightrag/config_local.env; set +a
fi

if [[ -z "${EMBEDDING_DIM:-}" ]]; then
  echo "" >&2
  echo "WARNING: EMBEDDING_DIM not set in config; cannot verify." >&2
  exit 0
fi

echo "" >&2
echo "Configured EMBEDDING_DIM=${EMBEDDING_DIM} (model=${EMBEDDING_MODEL:-?})" >&2
echo "Cache reset complete. Next LightRAG start will create fresh vdb files at this dim." >&2
