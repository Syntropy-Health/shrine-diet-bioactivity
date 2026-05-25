# `kg-mcp` — KG MCP Gateway

Production MCP server over the unified diet ⇄ food ⇄ compound ⇄ symptom ⇄ disease knowledge graph in Neo4j Aura. Speaks the [Model Context Protocol](https://modelcontextprotocol.io) so any MCP-compatible client (Claude Desktop, agent SDKs, custom clients) can query the KG with deterministic, scope-filtered Cypher behind 10 typed tools.

## Live deployment

| | |
|---|---|
| **URL** | `https://kg-mcp-test.up.railway.app` |
| **MCP endpoint** | `POST /mcp` (streamable-HTTP transport) |
| **Health (no auth)** | `GET /health` |
| **MCP server name / version** | `kg-mcp` / per `mcp` SDK |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  AURA NEO4J (sole data layer; durable)                  │
│  166K+ nodes, 5M+ edges                                 │
│  scope='shared' on every node and edge                  │
│  Native vector + per-relationship-type indexes          │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ neo4j+s://
                          │
┌─────────────────────────────────────────────────────────┐
│  RAILWAY (stateless compute; restartable)               │
│  ┌──────────────────────────────────────────────┐       │
│  │ scoped_server  (FastAPI, internal :9621)     │       │
│  │   /query /traverse /hdi_check                │       │
│  │   /bilingual_term /graphs                    │       │
│  └──────────────────────────────────────────────┘       │
│  ┌──────────────────────────────────────────────┐       │
│  │ kg-mcp gateway (FastMCP HTTP, public /mcp)   │       │
│  │   10 typed tools + auth middleware           │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

The Railway container is restartable; it holds zero data. All state is in Aura. NCBI enrichment writes flow through the scoped server back to Aura.

## Authentication

Every `/mcp*` request requires `Authorization: Bearer <token>`. `/health` is the only public path (Railway healthcheck reaches it without a token).

> **Direction:** internal API key issuance is moving to [Unkey](https://unkey.com) — see [#10](https://github.com/Syntropy-Health/shrine-open-diet/issues/10). The two paths below are interim; the static-key path is **deprecated** and will be removed once Unkey wiring lands.

### Canonical — Syntropy-Journals admin token (recommended)

Issue a long-lived admin token from the Syntropy-Journals Clerk-integrated token registry (`reflex_clerk_api`), then export it locally:

```bash
# In the Syntropy-Journals repo
APP_ENV=dev uv run python scripts/issue_admin_token.py \
  --name "kg-mcp-admin" --expires 30
# → prints: TOKEN: sj_<id>_<secret>

# In your shell — never commit this value
export ADMIN_API_TOKEN=sj_<id>_<secret>
```

Token format is `sj_<id>_<secret>` — id-prefixed bearer with a 30-day default expiry. Issuance procedure: [`apps/Syntropy-Journals/scripts/issue_admin_token.py`](../../Syntropy-Journals/scripts/issue_admin_token.py).

> **In-flight:** the kg-mcp gateway does **not yet validate `sj_*` tokens directly** — that requires a cross-service validator (Unkey, or an HTTP `/api/auth/validate-token` endpoint exposed by Syntropy-Journals). Tracked in [#10](https://github.com/Syntropy-Health/shrine-open-diet/issues/10). Until that ships, `sj_*` tokens are accepted only by Syntropy-Journals endpoints, not kg-mcp's.

### Canonical — Clerk admin sign-in (currently working for kg-mcp)

For browser/IDE clients that use the user's Clerk session JWT directly:

- Token verified against Clerk JWKS at `clerk.syntropyhealth.bio`
- Token's `email` claim must be in `MCP_ADMIN_EMAILS` (comma-separated allow-list)
- Currently allow-listed: `mymm.psu@gmail.com`

This path is live today.

### Deprecated — static `MCP_API_KEY` (CI smoke / dev only)

Kept until the Unkey migration completes; do not use for new integrations.

- Stored in Infisical → `SyntropyHealth App` / `prod` / `MCP_API_KEY`
- Constant-time compared with the server-side env var
- Will be removed once [#10](https://github.com/Syntropy-Health/shrine-open-diet/issues/10) lands

Full auth contract + rotation procedure: [`mcp-auth-contract.md`](../../../.claude/projects/-home-mo-projects-SyntropyHealth/memory/mcp-auth-contract.md) (admin-only memory doc).

## Quick smoke

```bash
# Pick one of:
#   export ADMIN_API_TOKEN=sj_<id>_<secret>     # Syntropy-Journals admin token (preferred — once #10 lands)
#   export ADMIN_API_TOKEN=<clerk-session-jwt>  # Clerk admin sign-in (live today)
#   export ADMIN_API_TOKEN=$(infisical secrets get MCP_API_KEY ... --plain)  # deprecated CI-only path

# 1. Health (no auth)
curl -fsS https://kg-mcp-test.up.railway.app/health

# 2. MCP initialize handshake
curl -fsS -X POST https://kg-mcp-test.up.railway.app/mcp \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"smoke","version":"0.1"}}}'
```

A complete Python smoke that initializes a session and calls each tool: [`tests/e2e/test_live_endpoints.py`](tests/e2e/test_live_endpoints.py). Set `KG_MCP_E2E_URL` and `ADMIN_API_TOKEN` (or legacy `KG_MCP_API_KEY`) in env to run with `pytest -m e2e`.

## Consumer integration

`kg-mcp` is a generic MCP server — any conformant MCP client can drive it. In practice the production consumer is **[Syntropy-Journals](https://github.com/Syntropy-Health/SyntropyJournal)** (Reflex/Hydra Python backend) via the **SJ-MCP federation** workstream ([Linear project](https://linear.app/syntropyhealth/project/sj-mcp-tool-manifest-bioactivity-federation-ed858d190602)); other LLM-agent clients (Claude Desktop, custom SDK loops) work identically.

### Transport contract

Streamable-HTTP transport. Every conversation is three POSTs to `/mcp` with a session header:

```
POST /mcp  { "method": "initialize", ... }                              ← capture `mcp-session-id` from response headers
POST /mcp  { "method": "notifications/initialized" }   + session header
POST /mcp  { "method": "tools/call", "params": { "name": ..., "arguments": ... } }   + session header
```

Tool output arrives as both `content[].text` (JSON-string MCP text wrapper) and `structuredContent` (typed object — match against the Pydantic shape in [`src/kg_mcp/schemas.py`](src/kg_mcp/schemas.py)). **Always read `structuredContent`** — the `text` wrapper is for display.

### Python reference client

A complete, reusable client lives in [`tests/e2e/conftest.py`](tests/e2e/conftest.py) (the `mcp_call` fixture). It's ~50 lines of `httpx.Client` — copy-paste into Syntropy-Journals and replace the env-var gating with your auth source.

```python
import httpx, json

GATEWAY = "https://kg-mcp-test.up.railway.app"
TOKEN = "<sj_id_secret | clerk_jwt | mcp_static_key>"

def call_tool(tool: str, args: dict) -> dict:
    h = {"Authorization": f"Bearer {TOKEN}",
         "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{GATEWAY}/mcp", headers=h,
            json={"jsonrpc":"2.0","id":1,"method":"initialize",
                  "params":{"protocolVersion":"2024-11-05","capabilities":{},
                            "clientInfo":{"name":"sj","version":"0.1"}}})
        sid = r.headers["mcp-session-id"]
        h2 = {**h, "mcp-session-id": sid}
        c.post(f"{GATEWAY}/mcp", headers=h2,
            json={"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
        r = c.post(f"{GATEWAY}/mcp", headers=h2,
            json={"jsonrpc":"2.0","id":2,"method":"tools/call",
                  "params":{"name":tool,"arguments":args}})
        # Streamable-HTTP can return SSE; tolerate both shapes.
        for line in r.text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
        return r.json()
```

### Auth choice matrix for consumers

| Consumer environment | Token type | Why |
|---|---|---|
| **Syntropy-Journals prod** (multi-user) | `sj_<id>_<secret>` admin token issued per request | Per-user audit trail; cross-service validator lands in #10 |
| **Syntropy-Journals dev / staging** | Clerk session JWT | The user's signed-in session already carries it |
| **CI / smoke tests / external pentests** | static `MCP_API_KEY` (`mcp_…` prefix) | Deprecated path retained while #10 ships — do not use for new integrations |

### Reference integration test suite

[`mcp/tests/e2e/`](tests/e2e/) is the canonical integration-test reference for any consumer:

- `test_live_endpoints.py` — system-level (health, auth, transport, tools/list).
- `test_tool_roundtrips.py` — one functional test per MCP tool, structural assertions only.
- `test_kg_coverage_probes.py` — named-entity probes that detect KG drift.

All three are gated on `KG_MCP_E2E_URL` + `KG_MCP_API_KEY`; clone the pattern when wiring a consumer-side suite. **Assertion discipline**: probes check structured payload fields (`len(chains) >= 1`, `len(nodes) >= 1`, `english` claim non-empty) — never substring-search the JSON dump, which would mistake schema keys for content.

## Tool catalog (10 tools, 3 layers)

Every tool returns Pydantic-validated structured output. Schemas in [`src/kg_mcp/schemas.py`](src/kg_mcp/schemas.py).

### Layer A — General Q&A (1 tool)

| Tool | Input | Output | When to use |
|---|---|---|---|
| `kg_query` | `question: str`, `mode: Literal["mix","hybrid","local","global","naive"]="mix"`, `top_k: int=40` | `{answer, references, scope_filter}` | Open-ended natural-language exploration. Default fallback when no Layer-B tool fits. ⚠️ See Limitations §1. |

### Layer B — Role-priored deterministic traversals (6 tools)

These tools enforce a fixed `(start_label, edge_type, depth)` and return typed `ProvenanceChain`s — exactly the shape paper provenance metrics expect.

All Layer-B tools accept `seed: str` and `top_k: int=20`. Seed matches against the start node's `entity_id`, `common_name`, any `aliases[]`, or `pubchem_cid` (Compound only, after Phase 2 NCBI overlay).

| Tool | Pattern | Example seed | Used by |
|---|---|---|---|
| `kg_diet_to_compounds` | `Food → bioactive Compound` (FOUND_IN_FOOD ↔ CONTAINS_COMPOUND, depth 2) | `"Garlic"` | Dietitian agent |
| `kg_compound_to_targets` | `Compound → Target` (TARGETS_PROTEIN, depth 1) | `"CURCUMIN"`, `"curcumin"`, `969516` (CID) | Pharmacologist |
| `kg_compound_to_diseases` | `Compound → Target → Disease` (depth-2 chain) | `"CURCUMIN"` | Pharmacologist; provenance |
| `kg_herb_to_diseases` | `Herb → Disease` (ASSOCIATED_WITH_DISEASE, depth 1) | `"Astragalus membranaceus"` | TCM, Pharmacologist |
| `kg_herb_to_symptoms` | `Herb → Symptom` (TREATS_SYMPTOM, depth 1) | `"Zingiber officinale"`, `"Ginger"` (after Phase 0) | TCM, Dietitian |
| `kg_compound_to_symptoms` | `Compound → Herb → Symptom` (composite, depth 2) | `"CURCUMIN"` | Dietitian (mechanism→clinical) |

### Layer C — Lookup primitives (3 tools)

| Tool | Input | Output | Notes |
|---|---|---|---|
| `kg_hdi_check` | `drug: str`, `herb: str` | `{found, severity, mechanism_class, evidence_tier, citations}` | Curated 50-pair Herb-Drug Interaction panel. Phase 0 alias-matching means natural names work: `("Warfarin", "St. John's Wort")` ✅ |
| `kg_bilingual_term` | `term: str` (any of EN/CN/Pinyin) | `{english, chinese, pinyin, source, confidence}` | SymMap 2.0 TCM herb canonicalization. `黄连` → `{english: "Coptis chinensis", chinese: "黄连", pinyin: "Huanglian"}` |
| `kg_node_neighborhood` | `seed: str`, `max_depth: int=2`, `max_nodes: int=200` | `{nodes, edges}` | Generic fallback when no role-priored tool fits. ⚠️ Currently 400s on free-text labels — see Limitations §3. |

## Worked examples

### Compound pharmacology

```python
# kg_compound_to_targets("CURCUMIN") → typed Cypher chain
{
  "chains": [
    {"edges": [{"src_id": "CURCUMIN", "tgt_id": "Histone-lysine N-methyltransferase MLL",
                "rel_type": "TARGETS_PROTEIN",
                "description": "CURCUMIN targets Histone-lysine N-methyltransferase MLL (Potency: 44668.4)",
                "source_id": "duke:targets_protein"}]},
    {"edges": [{"src_id": "CURCUMIN", "tgt_id": "DNA topoisomerase II alpha",
                "rel_type": "TARGETS_PROTEIN",
                "description": "CURCUMIN targets DNA topoisomerase II alpha (IC50: 15000.0)",
                "source_id": "duke:targets_protein"}]}
  ],
  "raw_subgraph_edge_count": 2
}
```

### Herb-disease (CMAUP)

```python
# kg_herb_to_diseases("Astragalus membranaceus")
{
  "chains": [
    {"edges": [{"src_id": "Astragalus membranaceus", "tgt_id": "Acne vulgaris",
                "rel_type": "ASSOCIATED_WITH_DISEASE",
                "description": "CMAUP plant-disease association",
                "source_id": "cmaup:plant_disease"}]},
    ...
  ]
}
```

### Drug-herb interaction (HDI-Safe-50)

```python
# kg_hdi_check(drug="Warfarin", herb="St. John's Wort")
# Phase 0 fix: matches via Herb.aliases = ["St. John's Wort", "Hypericum perforatum"]
#              and Drug entity_id = "Drug:Warfarin" with prefix-strip
{"found": true, "severity": "severe", "mechanism_class": "CYP450",
 "evidence_tier": "case_report_series", "citations": ["hdi-safe-50:HDI-001"]}
```

### Bilingual TCM

```python
# kg_bilingual_term("黄连")
{"english": "Rhizoma Coptidis,Coptidis Rhizoma", "chinese": "黄连",
 "pinyin": "Huanglian", "source": "symmap", "confidence": 1.0}
```

## Capabilities

The KG can answer any deterministic query along these mission axes:

| Axis | Edges | Source | Aura count |
|---|---|---|---|
| Food → bioactive Compound | `FOUND_IN_FOOD` | Duke + FooDB | 4.13M |
| Herb → Compound | `CONTAINS_COMPOUND` | Duke + FooDB | 85K |
| Compound → Target | `TARGETS_PROTEIN` | Duke + CMAUP | 6.5K |
| Compound → Disease (via Target) | composite chain | Duke + CMAUP | depth-2 traversal |
| Herb → Disease | `ASSOCIATED_WITH_DISEASE` | CMAUP + HERB 2.0 | 763K |
| Herb → Symptom | `TREATS_SYMPTOM` | Duke + SymMap | 41.8K |
| Drug ↔ Herb interaction | `INTERACTS_WITH` | curated HDI-Safe-50 | 50 |
| TCM bilingual canonicalization | node-level alias | SymMap 2.0 | ~4K Herbs |

Per-source provenance, license, and refresh procedure: [`shrine-diet-bioactivity/data/manifest.yaml`](../shrine-diet-bioactivity/data/manifest.yaml) and [`docs/DATASET_PROVENANCE.md`](../docs/DATASET_PROVENANCE.md).

## Limitations (read before using in production)

1. **Layer A (`kg_query`) is degraded.** Returns `"None"` or `"[no-context]"` on representative queries. Root cause is orthogonal to data quality (vector index dim mismatch + free-tier LLM rate limits) — tracked as [issue #5](https://github.com/Syntropy-Health/shrine-diet-bioactivity/issues/5). **Use Layer B (typed traversals) as the primary retrieval path**; Layer A is a documented fallback only.
2. **HDI lookup limited to the curated 50-pair panel.** Not exhaustive. `kg_hdi_check` only finds interactions explicitly in `research-journal/shared/hdi_safe_50.json` (NIH ODS / MSK About Herbs / LiverTox sources). Negative results are not safety guarantees.
3. **`kg_node_neighborhood` 400s on free-text labels.** Tracked as [issue #6](https://github.com/Syntropy-Health/shrine-diet-bioactivity/issues/6). Use the role-priored Layer-B tools instead.
4. **Compound seed-resolution depth.** Phase 2 PubChem overlay covers ~30–40% of the ~7K Duke compounds (non-canonical compound names don't all resolve to PubChem CIDs). Compounds without a PubChem match still need their canonical Duke `entity_id` (typically uppercase). For known canonical names (CURCUMIN, QUERCETIN, BERBERINE) Layer B is reliable; for novel names users may need to consult `data/manifest.yaml`.
5. **Nutrition enrichment is sparse.** Only 647 of 962 FooDB-aware Foods carry `nutrition_100g` (algorithmic plateau in fuzzy-bridge — not an NCBI-solvable gap).
6. **English / Latin / 中文 / Pinyin only.** Other languages not modeled.
7. **`scope_filter` defaults to `["shared"]`.** Tenant-scoped reads need explicit `["shared", "tenant:<slug>"]` and a tenant write path that's intentionally restricted.

## Refresh cadence

| Slot | Source | Procedure | Last refresh |
|---|---|---|---|
| Aura graph (entity ingest) | per-source SQLite + `lightrag/ingest_*.py` | `make lightrag-ingest-local` | see `scope-state-snapshot.md` |
| HDI-Safe-50 panel | curated JSON | `python lightrag/ingest_hdi.py` | 2026-04 |
| Herb/Drug aliases | from HDI JSON | `python scripts/enrich_hdi_aliases.py` | 2026-05-01 |
| MeSH UID overlay | NCBI E-utilities | `python scripts/ncbi/phase_1_mesh_overlay.py --resume` | 2026-05-01 |
| PubChem CID + synonyms | NCBI PubChem | `python scripts/ncbi/phase_2_pubchem_overlay.py --resume` | 2026-05-01 |

## Run locally

```bash
# Prerequisites:
#   - scoped_server running on :9621 (cd shrine-diet-bioactivity && make lightrag-server)
#   - .env with NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, OPENROUTER_API_KEY
#   - MCP_API_KEY (or MCP_AUTH_DISABLED=true for unguarded local dev)

cd mcp
pip install -e .
MCP_TRANSPORT=stdio python -m kg_mcp.server
```

For HTTP transport (the Railway-deployed shape):

```bash
MCP_TRANSPORT=streamable-http MCP_PORT=8080 \
MCP_DISABLE_DNS_REBINDING_PROTECTION=true \
MCP_API_KEY=<some-test-key> \
python -m kg_mcp.server
```

## Layout

```
mcp/
├── README.md                        ← you are here
├── pyproject.toml
├── src/kg_mcp/
│   ├── __init__.py
│   ├── schemas.py                   ← Pydantic input/output models
│   ├── client.py                    ← async httpx wrapper for scoped_server
│   ├── tools.py                     ← pure async tool functions
│   ├── auth.py                      ← Bearer-token middleware (static + Clerk)
│   └── server.py                    ← FastMCP wiring + /health route + auth wrap
└── tests/
    ├── unit/                        ← 69 tests, ~89% coverage
    └── e2e/                         ← live-endpoint tests (opt-in via env)
```

## Boundary contract

This package never:
- writes to the KG (use scoped_server's `/documents/custom_kg` for tenant-scoped writes)
- holds Aura credentials directly (delegates to scoped_server)
- runs Cypher on its own (Layer B/C tools delegate to typed scoped_server endpoints)

This package always:
- enforces Bearer-token auth on every `/mcp*` request
- propagates `scope_filter=["shared"]` by default to scoped_server
- validates inputs/outputs against Pydantic schemas before/after every tool

## See also

- **Researcher's guide** (question-first): [`docs/RESEARCHER_GUIDE.md`](../docs/RESEARCHER_GUIDE.md) — pick your persona, map question → tool, worked walkthroughs
- **Design**: [`research-journal/plans/2026-04-29-mcp-gateway-design.md`](../research-journal/plans/2026-04-29-mcp-gateway-design.md) — toolkit + design tensions + 4 trade-off considerations
- **NCBI enrichment**: [`research-journal/plans/2026-05-01-ncbi-enrichment-and-entity-resolution-design.md`](../research-journal/plans/2026-05-01-ncbi-enrichment-and-entity-resolution-design.md) — current data-overlay plan
- **Auth contract**: `~/.claude/projects/.../memory/mcp-auth-contract.md`
- **Open issues**: [#5 (Layer A degraded)](https://github.com/Syntropy-Health/shrine-diet-bioactivity/issues/5) · [#6 (kg_node_neighborhood 400)](https://github.com/Syntropy-Health/shrine-diet-bioactivity/issues/6) · [#7 (paper-source ingestion)](https://github.com/Syntropy-Health/shrine-diet-bioactivity/issues/7)
