#!/usr/bin/env bash
# Resolve a Railway service's public domain.
#
# Reads `railway status --json` output on stdin. If the JSON contains a
# `service.serviceDomains[0].domain` field, prints it. Otherwise falls back
# to the documented Railway pattern `${SERVICE}-${ENV}.up.railway.app`.
#
# Why a fallback: Railway CLI output shape has drifted across versions, and
# fresh services briefly report an empty serviceDomains array between
# deploy and DNS propagation. Without the fallback, a healthy live service
# gets reported as a failed CI deploy. The fallback is the URL that
# Railway itself assigns; if it doesn't answer, the downstream /health
# probe will catch that.
#
# Usage:
#   railway status --service "$SERVICE" --environment "$ENV" --json \
#     | scripts/ci/resolve_railway_domain.sh "$SERVICE" "$ENV"
#
# Always exits 0. Always prints exactly one line to stdout.

set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <service> <env>" >&2
  exit 2
fi

SERVICE="$1"
ENV_NAME="$2"

# Slurp stdin; tolerate empty/garbage input.
INPUT="$(cat || true)"

DOMAIN="$(
  printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read() or '{}')
except Exception:
    d = {}
svc = d.get('service') if isinstance(d, dict) else None
domains = (svc or {}).get('serviceDomains') if isinstance(svc, dict) else None
if isinstance(domains, list) and domains:
    first = domains[0]
    print(first.get('domain', '') if isinstance(first, dict) else '')
else:
    print('')
" 2>/dev/null || true
)"

if [ -z "$DOMAIN" ]; then
  DOMAIN="${SERVICE}-${ENV_NAME}.up.railway.app"
fi

echo "$DOMAIN"
