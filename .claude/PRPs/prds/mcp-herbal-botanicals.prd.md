# MCP Herbal Botanicals — Phytochemical Knowledge Graph for AI Dietitians

## Problem Statement

AI dietitian agents cannot bridge herbal medicine, active compounds, and everyday foods. When a user says "I'm tired too easily but I sleep enough," the agent needs to suggest active compounds (iron, B12, adaptogenic withanolides), find herbs rich in those compounds (ashwagandha, ginseng), AND map those compounds to common foods (spinach for iron, turmeric for curcumin) — all in a single tool call. No existing MCP server, API, or database connects herbs to their active compounds to the foods that share them AND to the health benefits/symptoms those compounds address.

The current Phase 1 implementation (Dr. Duke's + FooDB, SQLite) provides the herb→compound→food bridge but lacks:
- **Symptom/condition mapping**: no way to go from "chronic inflammation" → relevant compounds → herbs + foods
- **Target/pathway data**: no molecular target or pathway information for compounds
- **Food plant classification**: no distinction between medicinal-only vs. edible plants
- **Graph traversal**: relational JOINs become unwieldy for multi-hop queries (symptom → compound → target → herb → food)

## Evidence

- Phase 1 delivered: 2,376 herbs, 94,512 compounds, 4.1M compound-food pairs, 8 MCP tools, 17/17 tests passing
- No herbal/botanical MCP server with symptom-to-food traversal exists in the MCP ecosystem (confirmed March 2026)
- CMAUP 2024 (NAR paper) explicitly classifies 170 food plants + 1,567 edible plants among 7,865 total — the food bridge we need
- SymMap v2 maps 1,717 TCM symptoms to 961 modern medicine symptoms to 499 herbs with 19,595 compounds — the symptom layer we need
- BATMAN-TCM 2.0 provides 2.3M predicted compound-target interactions — graph density for multi-hop queries
- TCM_knowledge_graph GitHub project (3.4M records) already integrates SymMap + 5 other databases — prior art for multi-source integration
- Graphiti (24.6K GitHub stars) inspired the knowledge graph approach, but is designed for temporal agent memory, not static domain ontologies — Kuzu embedded graph DB (MIT, 3.8K stars) is the right fit

## Proposed Solution

Evolve `mcp-herbal-botanicals` from a relational SQLite bridge into a **phytochemical knowledge graph** powered by Kuzu (embedded graph DB). The graph connects 6 node types (herbs, compounds, foods, symptoms, targets, diseases) via typed edges, enabling multi-hop traversals like "chronic inflammation → anti-inflammatory compounds → herbs AND foods containing them."

Phase 1 (complete) established the herb→compound→food bridge with Dr. Duke's + FooDB. Phase 2 adds CMAUP (food plant classification + compound-target data), SymMap v2 (symptom mapping), and BATMAN-TCM 2.0 (dense predicted interactions). Phase 3 migrates from SQLite to Kuzu for native graph traversal. Phase 4 adds new MCP tools for symptom-based and multi-hop queries.

## Key Hypothesis

We believe a knowledge graph MCP server that pre-joins herb→compound→food→symptom→target data will enable any AI dietitian to answer "what foods give me the same benefits as ashwagandha?" or "what herbs and foods help with chronic inflammation?" in a single tool call.
We'll know we're right when the agent can resolve symptom-to-food queries with grounded, citation-backed data across at least 3 independent data sources.

## What We're NOT Building

- **A symptom-to-product recommendation engine** — the MCP is a data lookup tool, not a diagnostic system
- **A drug interaction checker** — out of scope; requires clinical-grade data and regulatory compliance
- **A supplement product database** — NIH DSLD already covers this; can be composed later
- **A real-time web scraper** — all data is pre-built into the graph at build time
- **A consumer-facing API** — this is an MCP tool for AI agent consumption only
- **A temporal/conversational knowledge graph** — Graphiti-style agent memory is not needed; this is a static domain ontology
- **A TCM formula recommender** — formula-level data (ETCM, BATMAN-TCM formulas) is out of scope for MVP

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| Herb→compound lookup accuracy | 90%+ of top-50 herbs return correct primary compounds | Manual validation against NIH ODS monographs |
| Compound→food bridge coverage | 60%+ of herb compounds have at least 1 food match | Automated audit script |
| Symptom→herb resolution | Top-20 common symptoms return relevant herbs within top-10 results | Manual validation against SymMap ground truth |
| Multi-hop query latency | <500ms for 3-hop traversals (symptom→compound→food) | Benchmark test suite |
| Data source coverage | 3+ independent sources per compound | Audit provenance fields |
| Agent composability | Works alongside mcp-opennutrition in same agent | Integration test with Claude |

## Open Questions

- [ ] FooDB CC BY-NC 4.0 and BATMAN-TCM CC BY-NC licenses — acceptable for Syntropy's internal use? If product becomes external-facing, need commercial license or alternative
- [ ] Kuzu Node.js bindings maturity — are they production-ready for MCP server use, or should we use Kuzu's Python API with a thin TypeScript wrapper?
- [ ] Should bioactivity/symptom terms be normalized to a standard ontology (MeSH, SNOMED-CT) or kept as source-native terms?
- [ ] Compound name disambiguation: current `normalizeCompoundName()` strips all non-alphanumeric chars. Is this sufficient for CMAUP/SymMap compounds, or do we need PubChem CID resolution?
- [ ] Should the MCP return USDA FDC food codes (linkable to mcp-opennutrition) or standalone food names? CMAUP has some FDC cross-references.
- [ ] Graph DB size constraints — Kuzu with 6 node types + 2.3M predicted interactions may produce a large file. Acceptable for local-first MCP?

---

## Users & Context

**Primary User**
- **Who**: Syntropy's internal AI dietitian agent (LLM with MCP tool access), and eventually any AI dietitian agent
- **Current behavior**: Can look up food nutrition via mcp-opennutrition, and herb→compound→food via Phase 1. Cannot go from symptoms/health concerns to herbs/foods. Relies on LLM parametric knowledge for symptom-to-herb mapping (unreliable for specific compounds/concentrations).
- **Trigger**: User describes a health concern ("I'm tired easily but I sleep enough"), mentions herbal supplements, asks about functional foods, or asks "what foods help with X"
- **Success state**: Agent retrieves structured, citation-backed symptom→compound→herb→food data in 1-2 tool calls and uses it to ground its response with specific compounds and concentrations

**Job to Be Done**
When a user describes a health concern (e.g., "I'm tired easily but I sleep enough"), I want to look up relevant active compounds (iron, B12, adaptogenic withanolides) and find both herbal sources AND common foods containing those compounds, so I can give grounded dietary suggestions that bridge supplements and whole foods — like suggesting ashwagandha supplements, ashwagandha tea, AND iron-rich spinach.

**Non-Users**
- End consumers (they interact with the AI agent, not the MCP directly)
- Pharmaceutical researchers needing clinical-grade drug interaction data
- Supplement manufacturers needing regulatory/labeling data
- TCM practitioners needing formula-level prescriptions

---

## Solution Detail

### Core Capabilities (MoSCoW)

| Priority | Capability | Rationale |
|----------|------------|-----------|
| Must | **search-herbs** — fuzzy search herbs by common/scientific name | Entry point for herb queries (Phase 1 ✅) |
| Must | **get-herb-compounds** — active compounds for a herb with concentrations | Core herb→compound mapping (Phase 1 ✅) |
| Must | **search-compounds** — search compounds, return herb + food associations | Bridge query (Phase 1 ✅) |
| Must | **get-compound-foods** — foods containing a compound | Enables "foods like ashwagandha" (Phase 1 ✅) |
| Must | **get-herb-food-overlap** — foods sharing most compounds with a herb | Flagship query (Phase 1 ✅) |
| Must | **search-by-bioactivity** — herbs/compounds by health benefit tag | Symptom→compound flow (Phase 1 ✅, needs enrichment) |
| Must | **get-herb-profile** — full herb monograph | Comprehensive single-call lookup (Phase 1 ✅) |
| Should | **search-by-symptom** — find herbs AND foods for a health concern/symptom | NEW: SymMap symptom→herb→food traversal |
| Should | **get-compound-targets** — molecular targets for a compound | NEW: CMAUP/BATMAN-TCM target data |
| Should | **find-functional-foods** — foods with therapeutic compound profiles | NEW: CMAUP food plant classification |
| Could | **traverse-path** — arbitrary multi-hop graph traversal | NEW: Kuzu Cypher query exposure |
| Could | **get-compound-evidence** — clinical trial + evidence layers for compound | NEW: CMAUP 4-layer evidence data |
| Won't | **check-interactions** — drug-herb interaction checking | Requires clinical data; out of scope |
| Won't | **recommend-formula** — TCM formula recommendation | Formula-level data deferred |
| Won't | **diagnose-condition** — symptom-to-diagnosis | Not a diagnostic tool |

### MVP Scope (Phase 2: KG Data Expansion)

The minimum to validate the knowledge graph hypothesis:
1. ETL pipeline for CMAUP 2024 (plant→compound→target, food/edible classification)
2. ETL pipeline for SymMap v2 (symptom→herb→compound mapping)
3. New SQLite tables: `symptoms`, `herb_symptoms`, `targets`, `compound_targets`, `diseases`
4. Enriched `herbs` table with `is_food_plant`, `is_edible` flags from CMAUP
5. Updated `search-by-bioactivity` to use structured symptom data instead of JSON LIKE queries
6. New `search-by-symptom` MCP tool

### User Flow (Agent Perspective)

```
User: "I'm feeling stressed and it affects my sleep"
  |
Agent calls: search-by-symptom("stress insomnia")
  → Returns: {
      symptoms_matched: ["Stress", "Insomnia"],
      herbs: [
        { name: "Ashwagandha", compounds: ["Withanolide A", "Withaferin A"],
          evidence: "SymMap + CMAUP", foods_with_overlap: 3 },
        { name: "Valerian", compounds: ["Valerenic acid"],
          evidence: "SymMap", foods_with_overlap: 1 }
      ],
      functional_foods: [
        { name: "Chamomile tea", shared_compounds: ["Apigenin"], sources: ["CMAUP"] },
        { name: "Tart cherry", shared_compounds: ["Melatonin"], sources: ["FooDB"] }
      ]
    }
  |
Agent calls: get-herb-food-overlap("withania_somnifera")
  → Returns: [{ food: "Winter Cherry fruit", shared_compounds: 4, overlap_score: 0.82 }, ...]
  |
Agent responds: "For stress and sleep, consider ashwagandha (as supplement or tea)
                 which contains withanolides. Foods like chamomile tea (apigenin)
                 and tart cherries (melatonin) share similar calming compounds."
```

---

## Technical Approach

**Feasibility**: HIGH

### Architecture Evolution

```
Phase 1 (COMPLETE):                     Phase 2-3 (PLANNED):
┌──────────────────────┐                ┌──────────────────────────────────┐
│   SQLite (914 MB)    │                │   SQLite (expanded) → Kuzu      │
│                      │                │                                  │
│  herbs ──► compounds │                │  symptoms ──► herbs ──► compounds│
│             │        │                │                         │        │
│             ▼        │                │              targets ◄──┘        │
│        compound_foods│                │                │                 │
│                      │                │              diseases            │
└──────────────────────┘                │                                  │
                                        │  herbs ──► compounds ──► foods   │
Data: Duke + FooDB                      │    ▲           │                 │
Tools: 8 MCP tools                      │    │           ▼                 │
                                        │  CMAUP    compound_foods         │
                                        │  SymMap   (Duke+FooDB+CMAUP)     │
                                        │  BATMAN                          │
                                        └──────────────────────────────────┘
                                        Data: Duke + FooDB + CMAUP + SymMap + BATMAN
                                        Tools: 11+ MCP tools
```

### Data Sources (Ranked by Priority)

| # | Source | Entities | Role in Graph | License | Format |
|---|--------|----------|---------------|---------|--------|
| 1 | **Dr. Duke's** (Phase 1 ✅) | 2,376 herbs, 94K compounds | Herb→compound backbone | CC0 | CSV |
| 2 | **FooDB** (Phase 1 ✅) | 4.1M compound-food pairs | Compound→food bridge | CC BY-NC 4.0 | CSV |
| 3 | **CMAUP 2024** | 7,865 plants (170 food, 1,567 edible), 60K compounds, 758 targets | Food plant classification + compound→target | Academic | CSV download |
| 4 | **SymMap v2** | 499 herbs, 19,595 compounds, 1,717 TCM symptoms, 961 MM symptoms | Symptom→herb→compound mapping | Academic | CSV download |
| 5 | **BATMAN-TCM 2.0** | 8,404 herbs, 39,171 compounds, 2.3M predicted interactions | Dense graph connectivity | CC BY-NC | TSV + API |
| 6 | **TCMSP** | 499 herbs, 29K compounds, ADME properties | Bioavailability filtering | CC BY 4.0 | XGMML |
| 7 | **Phenol-Explorer** | 500 polyphenols → 400+ foods with concentrations | Polyphenol→food bridge | Academic | Access DB |
| 8 | **IMPPAT 2.0** | 4,010 Indian plants, 17,967 phytochemicals | Ayurvedic herb coverage | MIT (code) | Web/SDF |

### Knowledge Graph Schema (Target State)

**Node Types:**
```
(Herb)       — id, scientific_name, common_name, family, is_food_plant, is_edible
(Compound)   — id, name, pubchem_cid, compound_class, molecular_weight
(Food)       — food_name, food_group, fdc_id
(Symptom)    — id, name, symptom_type (tcm|modern), mm_symptom_id
(Target)     — id, name, uniprot_id, gene_symbol
(Disease)    — id, name, icd_code
```

**Edge Types:**
```
(Herb)-[:CONTAINS {plant_part, concentration_ppm, source}]->(Compound)
(Compound)-[:FOUND_IN {content_per_100g, content_unit, source}]->(Food)
(Symptom)-[:TREATED_BY {evidence_type, source}]->(Herb)
(Compound)-[:TARGETS {activity_value, interaction_type, source}]->(Target)
(Target)-[:ASSOCIATED_WITH {evidence_layer, source}]->(Disease)
(Symptom)-[:MAPS_TO {source}]->(Symptom)  // TCM↔modern symptom mapping
(Herb)-[:IS_FOOD]->(Food)  // CMAUP food plant classification
```

### Storage Strategy

**Phase 2**: Expand SQLite with new tables (symptoms, targets, diseases, join tables). This preserves the working Phase 1 architecture while adding data.

**Phase 3**: Migrate to Kuzu embedded graph DB. Rationale:
- Embedded (file-based, like SQLite) — no server dependency
- MIT license
- Cypher query language for natural multi-hop traversals
- Node.js bindings available (kuzu npm package)
- Graphiti already supports Kuzu as a backend driver
- The `HerbalDBAdapter` class interface isolates the MCP server from storage — a `KuzuDBAdapter` implementing the same methods is a clean swap

**Technical Risks**

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Compound name mismatch across 5+ sources | HIGH | Continue using `normalizeCompoundName()` as primary join key; add PubChem CID resolution for ambiguous cases during ETL |
| SymMap/CMAUP download availability | MEDIUM | Cache source archives in `data/`; document manual download steps; add checksums |
| Kuzu Node.js bindings instability | MEDIUM | Phase 2 stays on SQLite; Kuzu migration is Phase 3 with fallback to SQLite |
| Graph DB file size with 2.3M BATMAN interactions | MEDIUM | Start with CMAUP + SymMap only; add BATMAN-TCM as optional enrichment layer |
| N+1 query patterns in `searchByBioactivity` | HIGH (exists) | Graph migration eliminates this; interim fix: batch SQL with CTEs |
| License compliance (CC BY-NC sources) | LOW for internal | Document license per source; flag if product goes external |

---

## Implementation Phases

| # | Phase | Description | Status | Parallel | Depends | PRP Plan |
|---|-------|-------------|--------|----------|---------|----------|
| 1 | Data acquisition & ETL (Duke + FooDB) | Download, parse, normalize, join into SQLite | complete | - | - | `.claude/PRPs/plans/mcp-herbal-botanicals-phase1-etl.plan.md` |
| 2 | MCP server & core tools | TypeScript MCP server with 8 tools | complete | - | 1 | - |
| 3 | Validation & testing | 17 tests, data audit, Claude integration | complete | - | 2 | - |
| 4 | KG data expansion (CMAUP + SymMap) | ETL for new sources, new tables, symptom/target data | complete | - | 3 | `.claude/PRPs/plans/completed/mcp-herbal-botanicals-phase4-kg-expansion.plan.md` |
| 5 | New MCP tools (symptom & target queries) | search-by-symptom, get-compound-targets, find-functional-foods | pending | - | 4 | - |
| 6 | Kuzu graph migration | Migrate from SQLite to Kuzu embedded graph DB | pending | - | 4 | - |
| 7 | BATMAN-TCM enrichment | Add 2.3M predicted interactions for graph density | pending | with 6 | 4 | - |
| 8 | Integration testing & validation | Multi-source audit, agent integration, benchmarks | pending | - | 5, 6 | - |

### Phase Details

**Phase 1: Data Acquisition & ETL (Duke + FooDB)** ✅ COMPLETE
- **Delivered**: SQLite DB (914 MB), 2,376 herbs, 94,512 compounds, 4.1M compound-food pairs
- **Scripts**: download-sources.ts, decompress-datasets.ts, build-herbal-db.ts, audit-herbal-data.ts

**Phase 2: MCP Server & Core Tools** ✅ COMPLETE
- **Delivered**: 8 MCP tools (search-herbs, get-herb-compounds, search-compounds, get-compound-foods, get-herb-food-overlap, search-by-bioactivity, get-herb-profile, get-health)
- **Architecture**: TypeScript, @modelcontextprotocol/sdk, better-sqlite3, Zod, vitest

**Phase 3: Validation & Testing** ✅ COMPLETE
- **Delivered**: 17/17 tests passing, data quality audit, MCP Inspector integration

**Phase 4: KG Data Expansion (CMAUP + SymMap)**
- **Goal**: Enrich the database with symptom, target, and food-plant classification data from CMAUP 2024 and SymMap v2
- **Scope**:
  - Download CMAUP CSV data (plant-ingredient-target-disease with evidence layers)
  - Download SymMap tabular data (herb-symptom-compound-target mappings)
  - New SQLite tables: `symptoms`, `herb_symptoms`, `targets`, `compound_targets`, `diseases`, `target_diseases`
  - Enrich `herbs` table with `is_food_plant`, `is_edible` flags from CMAUP
  - Cross-reference compounds across sources using `compound_name_map` + PubChem CID
  - Update `compound_name_map` with source='cmaup' and source='symmap' entries
- **Success signal**: SQLite DB contains symptom→herb relationships for top-20 common symptoms; CMAUP food plants flagged; compound cross-references validated

**Phase 5: New MCP Tools (Symptom & Target Queries)**
- **Goal**: Expose the new graph relationships as MCP tools
- **Scope**:
  - `search-by-symptom`: Given symptom text, find matching symptoms, linked herbs, linked compounds, and foods containing those compounds
  - `get-compound-targets`: Given compound, return molecular targets with activity values
  - `find-functional-foods`: Search for food plants with therapeutic compound profiles
  - Update `search-by-bioactivity` to use structured symptom table instead of JSON LIKE queries
  - Zod schemas, unit tests, integration tests for all new tools
- **Success signal**: Agent can answer "what foods help with chronic inflammation?" with grounded data

**Phase 6: Kuzu Graph Migration**
- **Goal**: Migrate from SQLite to Kuzu embedded graph DB for native multi-hop traversals
- **Scope**:
  - Create `KuzuDBAdapter` implementing same interface as `HerbalDBAdapter`
  - ETL pipeline to load all data into Kuzu property graph
  - Cypher queries replacing SQL JOINs for all existing tools
  - New `traverse-path` tool for arbitrary graph traversal
  - Benchmark: verify <500ms for 3-hop queries
- **Success signal**: All existing tests pass with KuzuDBAdapter; 3-hop queries under 500ms

**Phase 7: BATMAN-TCM Enrichment**
- **Goal**: Add 2.3M predicted compound-target interactions for graph density
- **Scope**:
  - Download BATMAN-TCM 2.0 TSV data
  - Load predicted interactions with confidence scores
  - Filter: only include predictions above confidence threshold
  - Add provenance tracking (predicted vs. experimentally validated)
- **Success signal**: Graph connectivity increases by 10x+; multi-hop queries return richer results

**Phase 8: Integration Testing & Validation**
- **Goal**: Verify data quality, query accuracy, and agent usability across all sources
- **Scope**:
  - Cross-source compound audit (how many compounds match across 3+ sources?)
  - Accuracy validation against NIH ODS monographs (top-50 herbs)
  - Symptom resolution accuracy against SymMap ground truth (top-20 symptoms)
  - Integration test: Claude agent with mcp-opennutrition + mcp-herbal-botanicals
  - Performance benchmarks: latency by query complexity
  - README update, usage examples, agent prompt patterns
- **Success signal**: Agent can answer symptom→food queries with multi-source citations

### Parallelism Notes

Phases 6 (Kuzu migration) and 7 (BATMAN-TCM) can run in parallel in separate worktrees — Phase 6 changes the storage layer, Phase 7 adds new data. They converge at Phase 8 for integration testing.

Phase 4 is the critical path — all subsequent phases depend on the expanded data model.

---

## Decisions Log

| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Separate MCP vs fork opennutrition | Separate `mcp-herbal-botanicals` | Fork/extend opennutrition | Cleaner separation of concerns; composable MCP design |
| Primary herb→compound source | Dr. Duke's Phytochemical DB | TCMSP, IMPPAT, COCONUT | CC0 license, USDA-backed, bulk CSV, covers Western + Eastern herbs |
| Primary compound→food source | FooDB | Phenol-Explorer, USDA Flavonoid DB | Broadest compound coverage (28K compounds); USDA Flavonoid DB can supplement |
| Symptom mapping source | SymMap v2 | ETCM, manual curation | Unique TCM↔modern medicine symptom bridge; 1,717+961 symptoms; downloadable |
| Food plant classification source | CMAUP 2024 | Manual annotation, FoodOn ontology | Explicit food/edible/medicinal classification; 60K compounds with targets |
| Dense interaction source | BATMAN-TCM 2.0 | STITCH, ChEMBL | 2.3M predicted interactions; TCM-focused; downloadable TSV |
| Graph DB | Kuzu (embedded) | Neo4j, FalkorDB, SQLite-only | Embedded (no server), MIT license, Cypher queries, Node.js bindings; Graphiti supports it as backend |
| NOT Graphiti | Kuzu directly | Graphiti framework | Graphiti is for temporal agent memory, not static domain ontologies; adds LLM dependency and Python runtime |
| Compound disambiguation | normalizeCompoundName() + PubChem CID | Exact string matching, ChEBI IDs | Normalize first (fast, no API calls); PubChem CID for ambiguous cases |
| Data storage | Local embedded DB (pre-built) | Runtime API calls | Matches opennutrition pattern; zero latency; offline-first |
| ChiMed 2.0 | Excluded | Include for NLP enrichment | Purely NLP training data (204M chars text); no structured compound/relationship data |

---

## Research Summary

**Market Context**
- No herbal/botanical MCP server with symptom-to-food traversal exists — first-of-kind
- 120+ natural products databases exist but none bridge herb→compound→food→symptom in a single interface
- Growing consumer demand for functional foods, longevity/wellness research, and Eastern/preventative health
- TCM_knowledge_graph GitHub project (3.4M records, integrates SymMap + 5 sources) provides prior art for multi-source integration
- FoodKG (63M RDF triples) and HerbKG (53K relations from PubMed) exist but not as MCP tools

**Technical Context**
- Phase 1 delivers a proven reference architecture: TypeScript, MCP SDK, SQLite, Zod, stdio transport, 8 tools, 17 tests
- `HerbalDBAdapter` class cleanly isolates storage from MCP tools — graph migration is a adapter swap
- `normalizeCompoundName()` (lowercase + strip non-alphanumeric) is the cross-source join key; validated across Duke + FooDB
- ETL pipeline handles 5M+ rows via streaming line-by-line parser with 10K batch transactions
- Compound name map table tracks provenance across sources for auditability

**Key Data Sources**

| Source | URL | License | Role | Status |
|--------|-----|---------|------|--------|
| Dr. Duke's Phytochemical DB | https://phytochem.nal.usda.gov | CC0 | Herb→compound mapping | ✅ Loaded |
| FooDB | https://foodb.ca | CC BY-NC 4.0 | Compound→food mapping | ✅ Loaded |
| CMAUP 2024 | https://bidd.group/CMAUP/ | Academic | Food plant + compound→target | Pending |
| SymMap v2 | http://www.symmap.org | Academic | Symptom→herb→compound | Pending |
| BATMAN-TCM 2.0 | http://bionet.ncpsb.org.cn/batman-tcm/ | CC BY-NC | Dense predicted interactions | Pending |
| TCMSP | https://tcmsp-e.com/ | CC BY 4.0 | ADME filtering (future) | Deferred |
| Phenol-Explorer | http://phenol-explorer.eu/ | Academic | Polyphenol→food (future) | Deferred |
| IMPPAT 2.0 | https://cb.imsc.res.in/imppat/ | MIT (code) | Ayurvedic herbs (future) | Deferred |
| COCONUT 2.0 | https://coconut.naturalproducts.net | CC0 | NP compound reference | Deferred |
| PubChem | https://pubchem.ncbi.nlm.nih.gov | Public domain | Compound disambiguation | As needed |

**Knowledge Graph Prior Art**

| Project | Description | Relevance |
|---------|-------------|-----------|
| [TCM_knowledge_graph](https://github.com/AI-HPC-Research-Team/TCM_knowledge_graph) | 20 entity types, 46 relationship types, 3.4M CSV records; integrates SymMap + TCMID + PharMeBINet + PrimeKG | High — could accelerate Phase 4 ETL |
| [FoodKG](https://foodkg.github.io/) | 63M RDF triples; recipes, nutrients, food ontology | Medium — food ontology reference |
| [HerbKG](https://github.com/FeiYee/HerbKG) | NER from 500K PubMed abstracts; 53K relations | Low — NLP-derived, less structured |
| [Graphiti](https://github.com/getzep/graphiti) | Temporal KG for agent memory; supports Kuzu backend | Architecture reference only |

---

*Generated: 2026-03-04, Updated: 2026-04-07*
*Status: DRAFT — Phase 1-3 complete, Phase 4+ needs validation*
