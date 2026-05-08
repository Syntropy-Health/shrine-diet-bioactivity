# KG Architecture (post-Phase-3)

> Authoritative architectural reference for the unified diet KG. Updated each phase.
>
> Last refreshed: 2026-05-08 (Phase 3 — disease canonicalization). For per-source
> licensing and refresh cadence see [`DATASET_PROVENANCE.md`](DATASET_PROVENANCE.md).
> For the gap-driven roadmap see [`KG_COMPLETENESS_AUDIT.md`](KG_COMPLETENESS_AUDIT.md).

---

## TL;DR — what this graph encodes

A unified knowledge graph spanning **diet → food → bioactive compound → molecular target → disease/symptom**, evidence-graded by literature citations. Purpose-built for two LLM-agent query patterns:

- **A. Symptom → food** — "what foods may help with X?" — ranked by ontology join + ChEMBL bioactivity + CTD literature
- **D. Diet → effects** — "what physiological effects does this diet predict?" — mechanistic chain through compound → gene → target → disease

A third query pattern (**C. Compound dossier**) falls out for free from the same backbone.

---

## High-level entity graph (Mermaid)

```mermaid
graph TD
    Herb[Herb<br/>2,376 Duke + 7,263 HERB2.0<br/>resolved 76.5%]
    Compound[Compound<br/>94,512 entities]
    Food[Food<br/>62K via FooDB+OpenNutrition]
    Symptom[Symptom<br/>47 hand-curated]
    Disease[Disease<br/>24,403 canonical<br/>5,351 MeSH-anchored]
    Target[Target<br/>4,355 with UniProt/Gene]
    BioactivityEvidence[BioactivityEvidence<br/>ChEMBL — Phase 1<br/>incoming]
    CompoundIdentity[CompoundIdentity<br/>InChIKey + cross-refs<br/>Phase 1]

    Herb -->|CONTAINS_COMPOUND<br/>99K Duke + HERB2.0 transitive| Compound
    Compound -->|FOUND_IN_FOOD<br/>4.1M edges| Food
    Compound -->|TARGETS_PROTEIN<br/>7K direct| Target
    Compound -->|HAS_EVIDENCE| BioactivityEvidence
    BioactivityEvidence -->|EVIDENCE_FOR_TARGET| Target
    Compound -->|HAS_IDENTITY| CompoundIdentity
    Herb -->|TREATS_SYMPTOM<br/>41,823 edges| Symptom
    Symptom -->|MAPS_TO_DISEASE<br/>40/47 mapped, 33 with MeSH| Disease
    Target -->|ASSOCIATED_WITH_DISEASE<br/>795K edges from CMAUP| Disease
    Compound -->|COMPOUND_TREATS_DISEASE<br/>11,976 + PubMed| Disease
    Compound -->|COMPOUND_MARKER_FOR_DISEASE<br/>17,289 + PubMed| Disease
    Compound -->|COMPOUND_INFERRED_DISEASE<br/>2.89M via gene_symbol| Disease

    style Disease fill:#e1f5ff,stroke:#0288d1,stroke-width:3px
    style CompoundIdentity fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style BioactivityEvidence fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Caption:** Eleven entity types (8 domain + 3 added in Phases 1–3, highlighted). The Disease node is a *unification point* — five distinct relationship types converge there from different evidence layers (symptom mapping, target association, three flavors of compound evidence). The orange-bordered nodes (`CompoundIdentity`, `BioactivityEvidence`) are scaffolding from Phase 1; their actual ingest runs against the live DB are pending.

---

## Data ingest topology (sources → canonical)

```mermaid
flowchart LR
    subgraph Sources [Public open-source datasets]
        Duke["Dr. Duke's Phytochemical DB<br/>2,376 herbs · 94K compounds"]
        FooDB["FooDB<br/>4.1M compound-food pairs"]
        OpenNutrition["OpenNutrition<br/>326K foods, 90 nutrient keys"]
        CMAUP["CMAUP v2.0<br/>4,355 targets · 795K target-disease"]
        TTD["TTD<br/>3,730 targets · druggability"]
        CTD["CTD<br/>17.7K chemicals · 3.8M evidence rows"]
        SymMap["SymMap v2<br/>1,148 modern + 2,285 TCM symptoms"]
        HERB2["HERB 2.0<br/>7,263 herbs · 1.8M herb-disease"]
        ChEMBL["ChEMBL 36<br/>~21M bioactivity rows"]
        PubChem["PubChem PUG-REST<br/>name → InChIKey + xrefs"]
        UniChem["UniChem<br/>InChIKey → ChEMBL/KEGG/DrugBank"]
    end

    subgraph SQLite [data_local/herbal_botanicals.db — 5.5GB]
        herbs
        compounds
        compound_foods
        targets
        target_diseases
        symmap_modern_symptoms
        herb2_herb_disease
        symptom_disease_map["symptom_disease_map<br/>(Phase 2)"]
        herb_resolution_map["herb_resolution_map<br/>(Phase 2)"]
        compound_identity["compound_identity<br/>(Phase 1)"]
        bioactivity_evidence["bioactivity_evidence<br/>(Phase 1)"]
        diseases_canonical["diseases_canonical<br/>(Phase 3)"]
        disease_name_aliases["disease_name_aliases<br/>(Phase 3)"]
        compound_disease_evidence["compound_disease_evidence<br/>(Phase 3)"]
    end

    subgraph LightRAG [Neo4j + vector index]
        Entities[11 entity types]
        Relations[15 relationship types]
    end

    Duke --> herbs
    Duke --> compounds
    FooDB --> compound_foods
    OpenNutrition --> compound_foods
    CMAUP --> targets
    CMAUP --> target_diseases
    TTD --> targets
    SymMap --> symmap_modern_symptoms
    SymMap --> symptom_disease_map
    HERB2 --> herb2_herb_disease
    HERB2 --> herb_resolution_map
    CTD --> diseases_canonical
    CTD --> compound_disease_evidence
    ChEMBL -.pending ingest.-> bioactivity_evidence
    PubChem -.pending ingest.-> compound_identity
    UniChem -.pending ingest.-> compound_identity

    SQLite ==>|extract_entities + extract_relationships<br/>via ainsert_custom_kg| LightRAG

    style diseases_canonical fill:#e1f5ff,stroke:#0288d1
    style compound_disease_evidence fill:#e1f5ff,stroke:#0288d1
    style disease_name_aliases fill:#e1f5ff,stroke:#0288d1
```

**Caption:** Sources flow into the ground-truth SQLite database (left → middle), which feeds LightRAG via per-entity-type extractors that emit pre-formed graph deltas (`ainsert_custom_kg`, zero LLM cost). Phase 3's three new tables (blue-highlighted) materialize cross-source disease unification. Dotted arrows mark Phase 1 sources whose ingest scripts ship in PR #19 but haven't been run end-to-end yet.

---

## The Disease unification (Phase 3 — what this PR adds)

Before Phase 3, three independent free-text disease columns lived siloed:

```mermaid
graph LR
    subgraph Before [Pre-Phase-3 — siloed disease references]
        cd_old[chemical_diseases<br/>disease_name 'Diabetes Mellitus']
        td_old[target_diseases<br/>disease_name 'Diabetes Mellitus']
        sdm_old[symptom_disease_map<br/>disease_name 'Diabetes Mellitus']
        cd_old -.LIKE join.- td_old
        td_old -.LIKE join.- sdm_old
    end
```

After Phase 3:

```mermaid
graph TB
    subgraph After [Post-Phase-3 — canonical registry]
        DC["diseases_canonical<br/>id='mesh:D003920'<br/>preferred_name='Diabetes Mellitus'<br/>mesh_id='D003920' umls_id='C0011849' icd10cm_id='E11'"]
        DNA["disease_name_aliases<br/>(disease_id='mesh:D003920',<br/>alias='Diabetes Mellitus', source='ctd')<br/>(disease_id='mesh:D003920',<br/>alias='Diabetes Mellitus', source='symmap')<br/>(disease_id='mesh:D003920',<br/>alias='Diabetes Mellitus', source='target_diseases')"]
        CDE["compound_disease_evidence<br/>(compound_id='curcumin',<br/>disease_id='mesh:D003920',<br/>evidence_type='direct_therapeutic',<br/>pubmed_ids='12345|67890')"]
        SDM["symptom_disease_map<br/>(symptom_id='diabetes',<br/>mesh_id='D003920',<br/>match_score=0.5)"]
        TD["target_diseases<br/>(target_id='NPT1',<br/>disease_name='Diabetes Mellitus')"]

        DNA -->|FK disease_id| DC
        CDE -->|FK disease_id| DC
        SDM -->|JOIN d.mesh_id = sdm.mesh_id| DC
        TD -->|alias lookup<br/>via DNA| DC
    end

    style DC fill:#0288d1,color:#fff,stroke-width:3px
```

**Caption:** Every observable disease string in any source resolves to one canonical entity keyed by its strongest formal ID (MeSH > UMLS > ICD-10 > local-slug fallback). Cross-source joins become indexed equality on `diseases_canonical.id` instead of free-text `LIKE` (with all the noise that implied).

### Live-DB outcome of canonicalization

| Metric | Value | Source contribution |
|---|---:|---|
| Canonical disease entities | **24,403** | symmap +1,148, ctd +6,678, target_diseases +2,398, herb2 +14,833 |
| With MeSH ID | 5,351 | symmap + ctd anchored |
| With UMLS ID | 855 | symmap-only |
| Aliases recorded | 29,075 | every observed name |
| Compound→disease evidence rows | **2,922,025** | re-ingested from CTD into typed schema |
| ↳ direct_therapeutic | 11,976 | gold-standard treatment relationships |
| ↳ direct_marker | 17,289 | biomarker relationships |
| ↳ inferred_via_gene | 2,892,760 | mechanistic chain via inference_gene_symbol |
| Rows with PubMed citations | **2,756,378 (94%)** | preserved from CTD column 9 |
| Rows with inference_gene_symbol | 2,892,760 | preserved from CTD column 6 |

**Caption:** The 94% citation fill rate is the headline number — every direct or inferred relationship now anchors to literature, enabling use-case-A's "evidence-graded recommendation" doneness criterion. The 2.89M `inference_via_gene` rows enable the use-case-D mechanistic chain `compound → gene → target → disease` that's been waiting since Phase 1.

---

## Use case A — Symptom → food (post-Phase-3)

```mermaid
sequenceDiagram
    participant U as User asks<br/>'foods for diabetes?'
    participant LR as LightRAG<br/>(MCP semantic-search)
    participant N as Neo4j
    participant SQL as SQLite<br/>(ground truth)

    U->>LR: query 'diabetes'
    LR->>N: vector search for Symptom='diabetes'
    N-->>LR: Symptom node + edges
    LR->>N: traverse MAPS_TO_DISEASE
    N-->>LR: Disease(mesh:D003920, 'Diabetes Mellitus')
    LR->>N: traverse COMPOUND_TREATS_DISEASE
    N-->>LR: 11,976 compounds with PubMed citations
    LR->>N: traverse FOUND_IN_FOOD
    N-->>LR: foods containing those compounds
    LR-->>U: ranked list of foods<br/>+ evidence scores<br/>+ citation counts
```

**Caption:** The query path traverses 4 edge hops (Symptom → Disease → Compound → Food). Each hop preserves provenance: `symptom_disease_map.match_score` (ontology confidence), `compound_disease_evidence.evidence_type` (therapeutic > marker > inferred), `compound_disease_evidence.pubmed_ids` (citation depth). The agent layer ranks the results.

---

## Use case D — Diet → effects (mechanistic chain)

```mermaid
flowchart TB
    Diet["User: 'turmeric, broccoli, ginger'"] --> Foods
    Foods --> Compounds[Bioactive compounds<br/>via compound_foods]
    Compounds --> Path1[Direct path<br/>compound_targets<br/>7K edges]
    Compounds --> Path2[Inferred path<br/>compound_disease_evidence<br/>inference_via_gene<br/>2.89M edges]

    Path1 --> Targets
    Path2 -->|inference_gene_symbol<br/>= targets.gene_symbol| Targets
    Targets --> Diseases[diseases_canonical<br/>via target_diseases]

    style Path1 fill:#fff3e0
    style Path2 fill:#e1f5ff
    style Targets fill:#f3e5f5
```

**Caption:** Two evidence paths converge on `targets`: the direct compound-target binding (CMAUP, 7K edges, kept since Phase 0) and the gene-mediated inference (CTD, 2.89M edges, added in Phase 3). The gene-symbol bridge is what closes the mechanistic chain. Phase 1's ChEMBL ingest will multiply Path 1; Phase 4 (KEGG) will add a third path through pathway membership.

---

## Schema schematic (post-Phase-3, all tables)

```mermaid
erDiagram
    compounds ||--o{ compound_foods : "found in"
    compounds ||--o{ herb_compounds : "contained in herbs"
    compounds ||--o{ compound_targets : "binds to"
    compounds ||--o{ compound_identity : "InChIKey + xrefs"
    compounds ||--o{ bioactivity_evidence : "ChEMBL evidence"
    compounds ||--o{ compound_disease_evidence : "treats/markers/infers"

    herbs ||--o{ herb_compounds : ""
    herbs ||--o{ herb_symptoms : "treats"
    herbs ||--o{ herb_resolution_map : "resolves to HERB2.0"
    herb2_herbs ||--o{ herb_resolution_map : ""
    herb2_herbs ||--o{ herb2_herb_disease : ""

    targets ||--o{ compound_targets : ""
    targets ||--o{ target_diseases : "associated"
    targets ||--o{ bioactivity_evidence : "evidence target"

    symptoms ||--o{ herb_symptoms : ""
    symptoms ||--o{ symptom_disease_map : "maps to disease"

    diseases_canonical ||--o{ disease_name_aliases : "has aliases"
    diseases_canonical ||--o{ compound_disease_evidence : "is target of"
    symmap_modern_symptoms ||--o{ diseases_canonical : "seeds with MeSH"

    chemical_diseases }o--|| compounds : "DEPRECATED — Phase 3 supersedes"
```

**Caption:** Eight core tables (`compounds`, `herbs`, `targets`, `symptoms`, `compound_foods`, `compound_targets`, `target_diseases`, `herb_symptoms`) plus seven Phase-1/2/3 additions. `chemical_diseases` is marked deprecated — kept populated for one stable cycle for backward-compat, then dropped.

---

## Audit-gate test surface

```mermaid
graph LR
    subgraph Phase0to3 [13 audit gates — all GREEN as of 2026-05-08]
        G1[chemical_diseases ≥10K rows]
        G2a[symptom_disease_map exists]
        G2b[≥40/47 symptoms mapped]
        G2c[Inflammation/Diabetes/Hypertension MeSH-anchored]
        G2d[match_score in [0,1]]
        G2e[MAPS_TO_DISEASE query runs]
        G3[≥75% Duke herbs resolved to HERB2.0]
        P3a[diseases_canonical ≥5K rows]
        P3b[compound_disease_evidence ≥800K]
        P3c[3 evidence types balanced]
        P3d[≥40% PubMed citation fill]
        P3e[4 sources unified in aliases]
        P3f[mesh_id UNIQUE]
    end

    style P3a fill:#e1f5ff
    style P3b fill:#e1f5ff
    style P3c fill:#e1f5ff
    style P3d fill:#e1f5ff
    style P3e fill:#e1f5ff
    style P3f fill:#e1f5ff
```

**Caption:** The audit gate suite is the project's regression backstop. Each gate corresponds to a doneness criterion from `KG_COMPLETENESS_AUDIT.md`. New phase work adds gates without removing them — `chemical_diseases ≥10K` (gate G1) stays green during the Phase 3 migration cycle so existing query consumers never see a regression.

---

## Phase roadmap (where we are, where we're going)

| Phase | Status | What it added |
|---|---|---|
| 0 (foundations) | ✅ Pre-PRs | Duke + FooDB + OpenNutrition + CMAUP + TTD + SymMap + HERB 2.0 ingest |
| 1 — Drug ↔ bioactive bridge | ✅ #19 | `compound_identity` + `bioactivity_evidence` (PubChem→UniChem→ChEMBL) |
| 1.5 — Audit | ✅ #20 | `KG_COMPLETENESS_AUDIT.md` + 6 RED gate tests |
| 2 — Symptom→disease map | ✅ #21 | `symptom_disease_map` (40/47, 33 with MeSH) |
| 2 — CTD ingest | ✅ #22 | `chemical_diseases` populated (934K rows) |
| 2 — HERB 2.0 resolution | ✅ #23 | `herb_resolution_map` (76.5%) |
| 3 — Disease canonicalization | ✅ #25 (this PR) | `diseases_canonical` + `compound_disease_evidence` + LightRAG reroute |
| **4 — KEGG pathway overlay** | ⏳ next | `pathways` + `compound_pathways` + `pathway_genes` — closes the use-case-D mechanistic chain |
| 5 — Diet scoring | 📋 spec'd | Aggregate compound exposures → predicted target/disease modulation |
| 6 — Drop legacy `chemical_diseases` | 📋 stable cycle | Migration cleanup (1 week post Phase 3 stable) |

---

## Conventions reminder

- **Architecture changes get an ADR.** ADR 0007 (compound identity), ADR 0008 (disease canonical). Don't edit closed ADRs; supersede with a new one.
- **Specs live in `docs/superpowers/specs/`** with date-prefix.
- **Audit-gate tests are append-only.** A phase that closes a gap removes the `xfail` marker but keeps the test.
- **Schema migrations dual-write.** Old table stays populated for one stable cycle before drop.
- **All builds idempotent.** `make build-X` re-runnable any time.
