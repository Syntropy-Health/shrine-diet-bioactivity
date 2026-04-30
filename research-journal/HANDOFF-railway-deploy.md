# Handoff — Railway deployment for the KG MCP service

_Drafted 2026-04-30. Companion to `HANDOFF-research-via-mcp.md`._

The deployment infrastructure is in place. Two paths to actually launch the service to Railway test environment.

## What's already in place

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build, Python 3.11-slim, non-root user, healthcheck on `$PORT/health`. Combines scoped_server (internal :9621) + MCP gateway (FastMCP streamable-http on `$PORT`). |
| `.dockerignore` | Excludes data_local/ (5.2 GB), data/ (1.4 GB), node_modules/, mcp-opennutrition/, graphiti/, research-journal/, tests, etc. Effective build context: ~5 MB. |
| `railway.toml` | Builder=DOCKERFILE, healthcheck `/health`, ON_FAILURE restart with 3 retries. |
| `scripts/start_combined.sh` | Supervisor: starts scoped_server in background, waits for /health, then execs MCP gateway in foreground. SIGTERM cleanup. |
| `.github/workflows/deploy-mcp.yml` | Branch→env mapping (`main`→prod, `test`→test, `dev-*`→test), pre-deploy MCP unit tests (39 tests), Docker build smoke, deploy via Railway CLI, post-deploy health check, rollback on failure. PR-promotion guard (PRs to main must come from `test`). |
| Railway service `kg-mcp` | Created in `syntropy` / `test`, id `a4546378-91b0-4447-96b3-354e632d1fb1`. Env vars set: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENROUTER_API_KEY`, `WORKSPACE=unified_diet_kg`, `MCP_TRANSPORT=streamable-http`, `MCP_HOST=0.0.0.0`, `SHRINE_CONFIG=local`. |

## How to trigger the deploy

### Option A — push to a `dev-*` branch (fastest, recommended)

```
cd apps/shrine-diet-bioactivity
git checkout -b dev-mcp-deploy
git add Dockerfile .dockerignore railway.toml scripts/start_combined.sh \
        .github/workflows/deploy-mcp.yml mcp/
git commit -m "feat(mcp): railway deployment scaffold + 10-tool gateway"
git push origin dev-mcp-deploy
```

The workflow's branch trigger maps `dev-*` → test. CI runs MCP unit tests (89% coverage), Docker smoke, then `railway up`.

GitHub Actions environment `test` must have:
- `RAILWAY_TOKEN` (already in Infisical SyntropyHealth App / prod / `RAILWAY_TOKEN` — copy to GitHub environment secret)

### Option B — manual `railway up` from a non-WSL environment

```
export RAILWAY_TOKEN=<from Infisical SyntropyHealth App / prod / RAILWAY_TOKEN>
cd apps/shrine-diet-bioactivity
railway up --service kg-mcp --environment test --ci --detach
```

**Note:** local attempts from WSL2 hit `BadRecordMac` TLS errors (likely MTU/networking artifact specific to WSL2). On stable networks (CI runners, Linux native, macOS), this works. If you must use WSL2, try lowering MTU: `sudo ip link set dev eth0 mtu 1280`.

### Option C — Railway dashboard manual deploy

1. Open Railway dashboard → `syntropy` project → `test` env → `kg-mcp` service
2. Settings → Source → connect to GitHub repo `Syntropy-Health/<this-repo>`, branch `test` (or another)
3. Trigger a redeploy from the deployments page

## Verifying the deploy

```
RAILWAY_TOKEN=<...> railway status --json | jq '.environments.edges[] | select(.node.name == "test") | .node.serviceInstances.edges[] | select(.node.serviceName == "kg-mcp") | {status: .node.latestDeployment.status, domain: .node.serviceDomains[0].domain}'
```

Healthy state:
```json
{"status": "SUCCESS", "domain": "kg-mcp-test.up.railway.app"}
```

Then:
```
curl -fsS https://<domain>/health
curl -fsS -X POST https://<domain>/mcp -H 'Content-Type: application/json' -d '{...mcp init handshake...}'
```

## Architecture (deployed shape)

```
Railway container (kg-mcp, syntropy/test)
├── scoped_server.py       (uvicorn, 127.0.0.1:9621, internal only)
│   └── reads/writes Aura
└── kg_mcp.server          (FastMCP streamable-http, 0.0.0.0:$PORT, public)
    └── HTTP-calls scoped_server@127.0.0.1:9621
```

External agents connect to `https://<railway-domain>/mcp`. Transport: streamable-http MCP.

## Failure modes + remediation

| Symptom | Likely cause | Fix |
|---|---|---|
| `BadRecordMac` on local `railway up` | WSL2 MTU mismatch | Use Option A (CI) or lower local MTU |
| Build fails on `pip install` | LightRAG dep version drift | Pin specific versions in `lightrag/requirements.txt` |
| Health check fails after deploy | scoped_server can't connect to Aura | Verify `NEO4J_*` env vars on Railway service; check Aura instance not paused |
| MCP `/health` returns 404 | FastMCP transport not exposing `/health` | Add explicit FastMCP health route in `server.py` (currently uses healthcheck on inner uvicorn — review) |
| 429s on first queries | OpenRouter chat rate limit | Expected at 20 RPM free tier; pace caller or upgrade |

## What still needs to happen for production-grade

These are not blockers for `test`; track for production rollout.

1. **Add `RAILWAY_TOKEN` to GitHub environment secrets** for both `test` and `prod` environments.
2. **Health endpoint** — confirm FastMCP's streamable-http transport actually exposes `/health` matching what `railway.toml` polls. If not, add a manual route.
3. **Rate-limit-aware MCP client** — reuse the `_embed_with_retry` exponential backoff pattern in `kg_mcp.client` for downstream LLM calls.
4. **Two-service split** — for prod, separate `kg-scoped-server` and `kg-mcp` services with internal Railway DNS. Cleaner blast radius.
5. **Monitoring** — wire scoped_server's `audit/mcp_audit.db` to ship to a real metrics backend (PostHog or similar) for the continuous-optimization lever per design memo §8.4.
