# Design — NCBI Overlay + Entity Resolution Fix + Server/Dataset Documentation

_Authored 2026-05-01. Implements the user-approved plan after re-review against the **functional parsimony** principle: leanest KG that finds all diet ⇄ food ⇄ compound ⇄ symptom ⇄ disease relationships._

---

## 0. Goal and architectural framing

**Goal**: maximize relationship discoverability across the diet ⇄ food ⇄ compound ⇄ symptom ⇄ disease axis without bloating the graph.

**Architecture (per user clarification 2026-05-01)**:

```
                    ┌─────────────────────────────────────────────┐
                    │  AURA NEO4J (sole data layer; durable)      │
                    │  166K nodes, 5M+ edges, scope='shared'      │
                    │  Native vector + B-tree + per-rel-type idx  │
                    └─────────────────────────────────────────────┘
                                       ▲
                                       │ neo4j+s://
                                       │
                    ┌─────────────────────────────────────────────┐
                    │  RAILWAY (stateless compute; restartable)   │
                    │  ┌─────────────────────────────────────┐    │
                    │  │ scoped_server (FastAPI, internal)   │    │
                    │  │   /query /traverse /hdi_check       │    │
                    │  │   /bilingual_term /graphs           │    │
                    │  └─────────────────────────────────────┘    │
                    │  ┌─────────────────────────────────────┐    │
                    │  │ MCP gateway (FastMCP, public /mcp)  │    │
                    │  │   10 typed tools + auth middleware  │    │
                    │  └─────────────────────────────────────┘    │
                    └─────────────────────────────────────────────┘
```

**No persistent state on Railway.** Container restart loses zero data — the graph is in Aura. NCBI enrichment writes go to Aura; Railway is only the route for them.

---

## 1. Audit findings (against the goal)

| Source | Status | Mission relevance | Action |
|---|---|---|---|
| Duke (herbs/compounds/foods/targets/symptoms) | ✅ ingested | core | none |
| FooDB compound-food (4.1M edges) | ✅ ingested | core | none |
| SymMap 2.0 TCM | ✅ ingested | core (bilingual) | none |
| HERB 2.0 (capped at 5.1k of 1.8M) | ✅ partial | medium | defer (evidence-tier filter is its own task) |
| CMAUP plant-disease (765k) | ✅ ingested | core | none |
| HDI-Safe-50 panel (50 edges) | ✅ ingested but **broken lookup** | core (drug-herb safety = dietary supplement safety) | **Phase 0** |
| OpenNutrition food bridge (647 of 962) | ✅ partial; algorithm-bound plateau | medium | defer (not NCBI-solvable) |
| TTD drug-disease (30k rows in SQLite) | ❌ not ingested | **off-mission** (drugs aren't diet) | drop per parsimony |
| CTD chemical-disease | ❌ never loaded | low | defer |
| TCMSP / STITCH / DisGeNET / BATMAN-TCM | ❌ aspirational | low | defer pending v1 eval signal |

**Conclusion**: the unindexed-but-on-mission gaps are entity-resolution defects (Blockers 1+4), not missing relationships.

---

## 2. NCBI capabilities — what we leverage and why

Two capabilities only:

1. **MeSH UID lookup** for Disease + Symptom nodes — enables hierarchical query expansion at retrieval time. `T2DM` → MeSH `D003924` → matches descendants. Real previously-unfindable relationships become findable.
2. **PubChem CID + synonyms** for Compound nodes — provides canonical IDs and rich synonym lists. Resolves `curcumin` ↔ `CURCUMIN` ↔ `diferuloylmethane` ↔ IUPAC variants.

**Out of scope and why**:
- PMID/PubMed evidence stamping on edges → paper hygiene, not relationship discovery
- Entrez Gene IDs on Target nodes → Targets are mid-link only; we don't query by gene
- Bulk PubMed scenario authoring → parallel-session paper-track work
- Replacing internal IDs with NCBI IDs → would break ingestion idempotency

**Throughput budget**: 10 RPS with API key, batched via `epost+esummary` (200 IDs/call). Keeps actual call rate ≪ cap.

---

## 3. Phase 0 — Entity-resolution fix (no NCBI; closes Blockers 1+4)

The HDI-Safe-50 ingest at `lightrag/ingest_hdi.py:50` stores Drug `entity_id` as `Drug:<name>` and Herb `entity_id` as Latin scientific name only. Users naturally type `Warfarin` not `Drug:Warfarin`, and `St. John's Wort` not `Hypericum perforatum`. The current `/hdi_check` Cypher does case-insensitive equality and breaks on both forms.

**0.1** Patch `/hdi_check` Cypher to match against `entity_id` (with `Drug:` prefix-strip) OR `common_name` OR any element of `aliases: list[str]`.

**0.2** One-shot Aura migration that re-reads `research-journal/shared/hdi_safe_50.json` and stamps each Herb node with `common_name = entry.herb.name` and `aliases = [entry.herb.name, entry.herb.latin]`. Each Drug node gets `aliases = [drug_name, "Drug:" + drug_name]`.

**0.3** Patch `/traverse` Cypher seed-match (already case-insensitive) to also check `aliases` so Layer-B traversals accept any canonical-or-common name.

**0.4** Live e2e tests using the 4 acceptance pairs from `HANDOFF-blockers-to-engineering.md` — must all return `found=true` with non-null severity + mechanism_class.

Cost: 0 NCBI calls; ~3 h TDD + small Aura SET migration on 41 Herb + ~50 Drug nodes.

---

## 4. Phase 1 — MeSH UID overlay on Disease + Symptom (~3 h)

For each Disease and Symptom node:
1. `esearch[mesh] term=<entity_id>` → MeSH UID
2. `esummary[mesh] id=<uid>` → tree numbers + ICD-10 xref where present

Stamp on the node:
- `mesh_uid: str | None`
- `mesh_tree_numbers: list[str]` (e.g., `["C19.246.099"]`)
- `icd10_xref: list[str]` (best-effort; not all MeSH terms cross-walk)

~80 NCBI calls (200/batch); ~8 s wall-clock + Aura SET.

Mission impact: query rewriter can expand `T2DM` → MeSH `D003924` → all child terms → matches every Disease tagged with that or a descendant tree number.

---

## 5. Phase 2 — PubChem CID + synonyms on Compound (~3 h)

For each Compound node:
1. PubChem `name → CID` lookup (E-utils PubChem domain)
2. `pubchem_cid → top-N synonyms` (typically 10–50 per compound)

Stamp on the node:
- `pubchem_cid: int | None`
- `inchi_key: str | None`
- `canonical_smiles: str | None`
- `aliases: list[str]` (synonyms list, lowercased + canonical case preserved)

The Layer-B Compound-seeded tools (`kg_compound_to_targets`, etc.) get an updated seed matcher:

```cypher
MATCH (start:`workspace`:Compound)
WHERE toLower(start.entity_id) = toLower($seed)
   OR start.pubchem_cid = toInteger($seed)        // accept CID literally
   OR any(alias IN coalesce(start.aliases, [])
          WHERE toLower(alias) = toLower($seed))
```

~70 NCBI calls; ~7 s wall-clock + Aura SET.

Mission impact: closes Blocker 4 for compounds. `kg_compound_to_targets("curcumin")` returns the same chains as `("CURCUMIN")`.

---

## 6. Phase 3 — Documentation (~4 h)

**Purpose** (per user 2026-05-01): the MCP server + underlying dataset must be self-describing for any MCP-client integrator who picks up the URL + key cold.

Three artifacts, all in-repo:

### 6.1 — Enrich `mcp/README.md` as the canonical user-facing doc

Sections:

1. **What this is** — single paragraph, 2–3 sentences
2. **Architecture** — the diagram from §0; explicit Aura-vs-Railway split
3. **Connection** — URL, auth header, two paths (static `MCP_API_KEY`, Clerk JWT)
4. **Tool catalog** — full table of the 10 tools, with one-line description, input shape, output shape, example seed; cross-references to `mcp/src/kg_mcp/schemas.py`
5. **Examples** — 3–4 worked curl/Python examples covering the most common queries (compound→target, herb→disease, hdi check, bilingual term)
6. **Capabilities** — what relationships can be retrieved (the Mission cardinality table)
7. **Limitations** — known issues:
   - Layer A `kg_query` degraded under free-tier LLM (rate limit)
   - HDI lookup limited to the curated 50-pair panel (not exhaustive)
   - English / Latin / Pinyin / 中文 supported for terminology; other languages not
   - `nutrition_100g` enrichment limited to the 647 fuzzy-bridged Foods (out of 962)
   - Refresh cadence (see §6.3)
8. **Authentication** — both paths, link to `mcp-auth-contract.md` memory doc
9. **Versioning + changelog** — short entry per dataset/code release

### 6.2 — Enrich `shrine-diet-bioactivity/data/manifest.yaml` as the dataset descriptor

The existing file already declares per-source ETL details. Add per-source:

- `relationship_axis: str` — which mission axis the source feeds (e.g., `compound_food`, `herb_disease`, `compound_target`)
- `freshness_pinned_at: ISO-date` — when the snapshot was taken from upstream
- `aura_node_count: int`, `aura_edge_count: int` — synchronized with `scope-state-snapshot.md` after each ingest round
- `refresh_procedure: str` — make-target or script that re-ingests this source
- `license: str` — for paper Methods attribution

### 6.3 — New `docs/DATASET_PROVENANCE.md`

A reviewer-facing single-page summary tying each Aura node/edge type to:
- The upstream source (with citation + license)
- The ingest script that loaded it
- The current Aura count
- The refresh cadence

This is the doc a paper reviewer or downstream MCP integrator reads once to understand "where every edge in this KG came from".

Cost: ~4 h writing + a small Aura query script that auto-populates the count fields in `manifest.yaml` from `scope-state-snapshot.md` so this doc doesn't drift.

---

## 7. Storage design (additive, zero schema migrations)

All new Aura properties:

**Disease + Symptom node** (Phase 1):
- `mesh_uid: str | None`
- `mesh_tree_numbers: list[str]`
- `icd10_xref: list[str]`

**Compound node** (Phase 2):
- `pubchem_cid: int | None`
- `inchi_key: str | None`
- `canonical_smiles: str | None`
- `aliases: list[str]`

**Herb + Drug node** (Phase 0):
- `common_name: str | None`
- `aliases: list[str]`

Existing indexes unchanged. New optional indexes added for join-back queries:
- `CREATE INDEX disease_mesh_uid IF NOT EXISTS FOR (d:Disease) ON (d.mesh_uid)`
- `CREATE INDEX compound_pubchem_cid IF NOT EXISTS FOR (c:Compound) ON (c.pubchem_cid)`

All writes use `MERGE … SET` keyed on `entity_id`. Re-running any phase = no-op on already-stamped nodes.

---

## 8. Reliability + rate limiting

- **Token-bucket limiter** — single asyncio.Semaphore at 10 RPS, jitter on retries, max 6 attempts with exponential backoff (2s → 32s) on 429.
- **Resumable checkpointing** — per-phase JSON in `data_local/ncbi_progress/{phase}.json`; resumes from last completed batch on crash.
- **One script per phase** — `scripts/ncbi/phase_0_entity_resolution.py`, `phase_1_mesh_overlay.py`, `phase_2_pubchem_overlay.py`. Each independently runnable, idempotent.
- **TDD per script** — unit tests with mocked NCBI responses; live integration tests behind opt-in `NCBI_LIVE=1` env so CI doesn't burn the rate-limit quota.

---

## 9. Verification per phase

After each phase, run `scripts/capture_scope_state.py` and confirm:

| Phase | Cypher | Expected |
|---|---|---|
| 0 | `MATCH (h:Herb) WHERE h.common_name IS NOT NULL RETURN count(h)` | ≥ 41 (HDI panel herbs) |
| 0 | `MATCH (d:Drug) WHERE size(coalesce(d.aliases, [])) > 0 RETURN count(d)` | ≥ ~50 (HDI panel drugs) |
| 0 | live `kg_hdi_check("Warfarin", "St. John's Wort")` | `found=true, severity="severe", mechanism_class="CYP450"` |
| 1 | `MATCH (d:Disease) WHERE d.mesh_uid IS NOT NULL RETURN count(d)` | 4–5k (not all map) |
| 2 | `MATCH (c:Compound) WHERE c.pubchem_cid IS NOT NULL RETURN count(c)` | 4–6k (not all match PubChem) |
| 2 | live `kg_compound_to_targets("curcumin")` (lowercase) | non-empty chains |
| 3 | `mcp/README.md` covers all 10 tools, all 4 limitations, both auth paths | manual review |
| 3 | `data/manifest.yaml` per-source counts match latest `scope-state-snapshot.md` | diff check |

---

## 10. Total cost estimate

| Phase | NCBI calls | Wall-clock NCBI | Aura write | Implementation |
|---|---:|---:|---:|---:|
| 0 — Entity resolution | 0 | — | ~5 s SET | ~3 h |
| 1 — MeSH overlay | ~80 | ~8 s | ~5 s SET | ~3 h |
| 2 — PubChem CID + synonyms | ~70 | ~7 s | ~10 s SET | ~3 h |
| 3 — Documentation | 0 | — | minimal (count refresh) | ~4 h |
| **Total** | **~150** | **~15 s** | **~20 s** | **~13 h ≈ 1.5–2 days** |

Within the user's "a few days acceptable" budget; well below the 10 RPS NCBI cap.

---

## 11. Open questions resolved

- **Q: Are TTD drug-disease 30k rows on-mission?** → No. Dropped per parsimony.
- **Q: Edge-level evidence stamping (PMIDs)?** → No. Defer until eval shows missing citations are blocking C3.
- **Q: Where does data live?** → Aura is sole data layer; Railway is stateless compute. Documented in §0.
- **Q: How does an MCP-client integrator learn the contract?** → Phase 3 docs (`mcp/README.md` + `data/manifest.yaml` + `docs/DATASET_PROVENANCE.md`) — single discoverable entry point.

---

## 12. Acceptance gate for the whole plan

The plan is "done" when **all four** are true:

1. `kg_hdi_check` passes the 4-pair acceptance criteria (Blocker 1 closed)
2. Compound-seeded Layer-B tools accept lowercase + synonym names (Blocker 4 closed for compounds)
3. Disease nodes have MeSH UID where MeSH covers them (≥ 80% coverage)
4. The three Phase-3 docs exist, are in-tree, and a fresh MCP-client integrator can stand up against the live URL using only those docs
