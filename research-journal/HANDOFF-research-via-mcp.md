# Handoff — Parallel Research Session via the LightRAG-KG MCP

_Drafted 2026-04-29. Read this first if you are picking up the research thread in a separate Claude session and consuming the KG via MCP rather than authoring it._

---

## TL;DR

You are running in a **separate session from the KG-engineering session**. The KG-engineering session owns the data (Aura), the storage layer (`scoped_server.py`), and the MCP gateway (`mcp/`). **You consume.**

Your session does:

1. Authoring, annotating, and validating the v2 benchmark dataset (per `plans/2026-04-29-v2-benchmark-expansion.md`).
2. Running v1 / v2 eval matrices, analyzing results, drafting the paper Methods + Results.
3. Driving the agent panel against the MCP gateway.

You do NOT touch:

- `scoped_server.py`, `scoped_neo4j_storage.py`, `scoped_neo4j_vector_storage.py`, `ingest_*.py`, `bootstrap_scope.py`, `migrate_embeddings_to_aura.py`. That belongs to the KG-engineering session.
- The Aura graph directly (`NEO4J_URI`). All graph access is via the MCP gateway.
- The vector index (only the gateway reads it).

If you find yourself wanting to write to the KG or change the schema, **stop and message the engineering session** — don't fork the data.

---

## What's already in place

- **Aura `unified_diet_kg`** (Neo4j AuraDB Professional 8GB, instance `c16cebae`):
  - 166K+ entity nodes, ~5M relationships.
  - Sources: Duke, SymMap 2.0, HERB 2.0, CMAUP plant-disease, HDI-Safe-50, OpenNutrition food bridge.
  - Every node + edge tagged `scope='shared'`.
  - 8 vector + node indexes ONLINE.
- **Re-embedded vector index** (in flight as of 2026-04-29; check `research-journal/shared/scope-state-snapshot.md` for `VectorEntity` count vs. eligible total).
- **MCP gateway** at `mcp/` — 10 tools (see §3).
- **Eval harness** (`shrine-diet-bioactivity/eval/`): F0–F7 wired, 6 baselines (`single_llm`, `single_llm_rag`, `yang2025`, `medagents`, `mdagents`, `diet_os`).
- **Pre-flight gate + lifecycle script** (`scripts/run_v1_eval.sh`, `make eval-run-v1`).

## What's NOT in place yet

- v2 dataset (target: 200 scenarios, two-annotator gold) — your job per memo §6–§9.
- Paid-tier alternate LLM routing (free-tier OpenRouter is the current default; rate-limited to 20 RPM at chat endpoint).
- Paper drafts (Methods, Results, Discussion).

---

## Your environment setup

### 0. Repo
```
git checkout feature/mcp-herbal-botanicals
git pull
```
Branch state: see `research-journal/shared/scope-state-snapshot.md` for the live KG metrics; the snapshot is the audit trail.

### 1. Secrets

You need:

| Variable | Source | Purpose |
|---|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | Infisical SyntropyHealth App / prod | DO NOT use directly — go through the MCP gateway. These are here only for diagnostics if the gateway is down. |
| `OPENROUTER_API_KEY` | Infisical SyntropyHealth App / prod | LLM calls in the eval baselines + panel agents |
| `NCBI_API_KEY` | Infisical SyntropyHealth App / prod | PMID / Cochrane resolution for v2 gold-label provenance. **Paper-track only — never hits the KG.** |

Pull all three into your shell `.env` from Infisical before starting:
```
infisical run -- bash -c 'echo OK'   # confirms creds resolve
```

### 2. Start the MCP gateway

In one terminal owned by the engineering session (or yours, but coordinate):
```
cd shrine-diet-bioactivity
make eval-run-v1            # one-shot lifecycle
# OR for a long-running interactive session:
make lightrag-server &       # background scoped_server on :9621
python -m mcp.server         # MCP stdio gateway, reads from scoped_server
```

Verify health:
```
curl http://localhost:9621/health
# {"status":"ok","config":"local"}
```

### 3. Confirm the MCP tools work

In your Claude session, the gateway exposes 10 tools. Smoke-test each:

```
kg_query("Does ginger reduce CINV?")
kg_compound_to_targets("Curcumin")
kg_herb_to_diseases("Astragalus membranaceus")
kg_hdi_check("warfarin", "Ginkgo biloba")
kg_bilingual_term("黄连")
```

If any tool returns an error, message engineering.

---

## The 10 MCP tools (your surface area)

See `plans/2026-04-29-mcp-gateway-design.md` for full schemas. Quick reference:

### Layer A — General Q&A

- **`kg_query(question, mode='mix', top_k=40)`** — natural-language Q&A. Default fallback when no role-prior fits.

### Layer B — Role-priored entrypoints (deterministic traversal)

- **`kg_diet_to_compounds(seed, top_k=20)`** — Food → bioactives. Dietitian.
- **`kg_compound_to_targets(seed, top_k=20)`** — Compound → Target. Pharmacologist.
- **`kg_compound_to_diseases(seed, top_k=20)`** — Compound → Target → Disease (depth-2 chain). Pharmacologist + provenance.
- **`kg_herb_to_diseases(seed, top_k=20)`** — Herb → Disease. TCM.
- **`kg_herb_to_symptoms(seed, top_k=20)`** — Herb → Symptom. TCM, Dietitian.
- **`kg_compound_to_symptoms(seed, top_k=20)`** — Compound → Herb → Symptom (composite). Dietitian.

### Layer C — Lookup primitives

- **`kg_hdi_check(drug, herb)`** — exact lookup against HDI-Safe-50 panel. Returns severity + mechanism + evidence tier or `null`. Safety reviewer.
- **`kg_bilingual_term(term, languages=['en','cn','pinyin'])`** — SymMap canonicalization. TCM.
- **`kg_node_neighborhood(seed, max_depth=2, max_nodes=200)`** — generic subgraph dump. Use only when above tools don't fit.

**Picking a tool: try the role-prior first; fall back to `kg_query` only when the prior doesn't apply.** Reviewers will look for "the agent used `kg_compound_to_diseases` to retrieve evidence for HDI" — that's much stronger than "the LLM did a free-text RAG query."

---

## Your tasks (priority order)

### Task A — v2 benchmark scaffold

Per `plans/2026-04-29-v2-benchmark-expansion.md`:

1. Build the Streamlit annotation UI (memo §4) — 3 days.
2. Author 50 pilot scenarios across the 7 categories with PMID/Cochrane references — 1 week.
3. Run pilot annotation (A1 RD + A2 PharmD) — 1 week.
4. Compute IAA on pilot. **Decision gate:** if κ < 0.5 on verdict, redesign the rubric. If ≥ 0.5, scale to 200.

**NCBI API key** is for PMID resolution at scenario authoring time — you cite a PMID, the CI gate (later) verifies it resolves. Don't put PMIDs in the KG.

### Task B — Run v1 eval against the now-populated KG

Once the engineering session confirms `VectorEntity` count = `Eligible source entities` (i.e., re-embed migration done):

```
make eval-run-v1                    # full 6-baseline matrix
make eval-report                    # render summary.md + reliability_diagram.png
```

Compare results against the prior run at `research-journal/shared/results/20260428T224038Z/` — diet_os should now have non-empty subgraphs (`raw_subgraph_node_count > 0` in case-study output JSONs) and meaningful `verdict_kappa`, `hdi_recall`, `provenance` numbers.

If diet_os κ is still ≈ 0:
- Check: was kg_query in `hybrid` mode actually returning chains? Look at the case-study JSONs.
- Check: was OpenRouter rate-limiting most calls? Look at the raw eval log for 429 patterns.

### Task C — Paper draft

Once you have a clean v1 re-run with non-zero signal:

- Methods section: copy-edit from `plans/2026-04-22-program.md` and the audit memos.
- Results section: tables from `summary.md` + `paired_tests.md`.
- Discussion: anchor on the 5 falsifiable claims C1–C5 (post-mortem §6); discuss which ones survived the run.

Do NOT publish anything without confirming citation hygiene (PMID + Cochrane IDs resolvable).

---

## Coordination protocol

- **Boundary:** the engineering session owns `lightrag/`, `ingest_*.py`, `bootstrap_scope.py`, `migrate_embeddings_to_aura.py`, `scoped_server.py`, `scoped_neo4j_*.py`, `scripts/capture_scope_state.py`, `mcp/`. Your session owns `eval/scenarios/v2/`, `gold/v2/`, the Streamlit UI, paper drafts under `research-journal/primary/`.
- **Schema changes:** if you need a field added to `Scenario` or `GoldStandard`, message engineering, don't fork. Same for new MCP tools.
- **Snapshot trail:** any change to the live KG is captured in `research-journal/shared/scope-state-snapshot-*.md`. If counts change unexpectedly, ask before assuming.
- **Branch hygiene:** keep your work on `feature/mcp-herbal-botanicals`. If you need to branch, do so from there. Never merge into `main` directly — the engineering session owns the merge cadence to `main`.

---

## What to do if the gateway is down

In order of escalation:

1. `curl http://localhost:9621/health` — is scoped_server up?
2. `pgrep -fa scoped_server` — is the python process alive?
3. `tail -200 <wherever scoped_server logs are>` — startup error?
4. Check `research-journal/shared/scope-state-snapshot.md` "Health check" — `Untagged` should be 0; if not, `bootstrap_scope.py` regression.
5. If any of the above is broken, message engineering. **Do not** restart processes or run migrations from your session.

---

## Reading order for context

Before you start any task above, read these in order:

1. `research-journal/plans/2026-04-22-program.md` — what we're building, why.
2. `research-journal/shared/2026-04-26-v1-postmortem-and-next-steps.md` — what v1 measured and didn't measure.
3. `research-journal/plans/2026-04-26-kg-unification-priorities.md` — the data layer.
4. `docs/adr/0001-vector-storage-on-aura.md` — vector storage architecture.
5. `research-journal/plans/2026-04-29-mcp-gateway-design.md` — the MCP layer (your interface).
6. `research-journal/plans/2026-04-29-v2-benchmark-expansion.md` — your primary work item.

After this, you should be able to operate independently.
