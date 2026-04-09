# Data Sources Catalog — MCP Herbal Botanicals Knowledge Graph

> Comprehensive index of all data sources used or planned for the `mcp-herbal-botanicals` phytochemical knowledge graph. Each source is documented with entity types, schemas, relationships, license, and integration status.

**Last updated**: 2026-04-07

---

## Table of Contents

1. [Source Overview](#1-source-overview)
2. [Integration Status Matrix](#2-integration-status-matrix)
3. [Segment 1: Herb-to-Compound Sources](#3-segment-1-herb-to-compound-sources)
   - 3.1 Dr. Duke's Phytochemical Database
   - 3.2 CMAUP 2024
   - 3.3 BATMAN-TCM 2.0
   - 3.4 TCMSP
   - 3.5 IMPPAT 2.0
4. [Segment 2: Compound-to-Food Sources](#4-segment-2-compound-to-food-sources)
   - 4.1 FooDB
   - 4.2 Phenol-Explorer 3.0
   - 4.3 USDA Flavonoid Database
5. [Segment 3: Symptom & Health Benefit Sources](#5-segment-3-symptom--health-benefit-sources)
   - 5.1 SymMap v2
   - 5.2 Chinese Medicine NER Dataset (Kaggle)
6. [Segment 4: Compound Reference & Disambiguation](#6-segment-4-compound-reference--disambiguation)
   - 6.1 PubChem
   - 6.2 COCONUT 2.0
   - 6.3 LOTUS / Wikidata
7. [Segment 5: Prior Art & Pre-Built KGs](#7-segment-5-prior-art--pre-built-kgs)
   - 7.1 TCM_knowledge_graph (GitHub)
   - 7.2 FoodKG
   - 7.3 HerbKG
8. [Knowledge Graph Schema](#8-knowledge-graph-schema)
9. [Cross-Source Join Strategy](#9-cross-source-join-strategy)
10. [License Summary](#10-license-summary)

---

## 1. Source Overview

| # | Source | Entities | Primary Role | License | Status |
|---|--------|----------|-------------- |---------|--------|
| 1 | Dr. Duke's Phytochemical DB | 2,376 herbs, 94K compounds | Herb→compound backbone | CC0 | **Loaded** |
| 2 | FooDB | 28K compounds, 1K+ foods | Compound→food bridge | CC BY-NC 4.0 | **Loaded** |
| 3 | CMAUP 2024 | 7,865 plants, 60K compounds, 758 targets | Food plant + compound→target | Academic | Planned (Phase 4) |
| 4 | SymMap v2 | 499 herbs, 19.5K compounds, 2,678 symptoms | Symptom→herb mapping | Academic | Planned (Phase 4) |
| 5 | BATMAN-TCM 2.0 | 8,404 herbs, 39K compounds, 2.3M interactions | Dense predicted interactions | CC BY-NC | Planned (Phase 7) |
| 6 | TCMSP | 499 herbs, 29K compounds, ADME props | Bioavailability filtering | CC BY 4.0 | Deferred |
| 7 | Phenol-Explorer 3.0 | 500 polyphenols, 400+ foods | Polyphenol→food bridge | Academic | Deferred |
| 8 | IMPPAT 2.0 | 4,010 plants, 18K phytochemicals | Ayurvedic herb coverage | MIT (code) | Deferred |
| 9 | PubChem | 110M+ compounds | Compound disambiguation | Public domain | As needed |
| 10 | COCONUT 2.0 | 400K+ natural products | NP compound reference | CC0 | Deferred |
| 11 | Chinese Medicine NER (Kaggle) | 1,000 annotated samples, 13 entity types | TCM NER training data | MIT | Low priority |
| 12 | TCM_knowledge_graph (GitHub) | 3.4M records, 20 entity types | Pre-built multi-source KG | Varies | Reference |

---

## 2. Integration Status Matrix

```
                          ┌─────────────────────────────────────────────┐
                          │         INTEGRATION PIPELINE                 │
                          │                                             │
  LOADED (Phase 1)        │  Dr. Duke's ──► herbs, compounds            │
  ████████████████        │  FooDB ──────► compound_foods               │
                          │                                             │
  PLANNED (Phase 4)       │  CMAUP ──────► targets, compound_targets,   │
  ░░░░░░░░░░░░░░░░        │                is_food_plant flags          │
                          │  SymMap ─────► symptoms, herb_symptoms      │
                          │                                             │
  PLANNED (Phase 7)       │  BATMAN-TCM ─► compound_targets (predicted) │
  ░░░░░░░░░░░░░░░░        │                                             │
                          │                                             │
  DEFERRED                │  TCMSP ──────► ADME properties              │
  ················        │  Phenol-Exp ─► polyphenol→food              │
                          │  IMPPAT ─────► Ayurvedic herbs              │
                          │  COCONUT ────► compound enrichment          │
                          │  TCM NER ────► NER entities (post-process)  │
                          └─────────────────────────────────────────────┘
```

---

## 3. Segment 1: Herb-to-Compound Sources

These sources map **plants/herbs → bioactive compounds** with concentrations.

### 3.1 Dr. Duke's Phytochemical Database

| Field | Value |
|-------|-------|
| **URL** | https://phytochem.nal.usda.gov / https://data.nal.usda.gov/dataset/dr-dukes-phytochemical-and-ethnobotanical-databases |
| **License** | CC0 (public domain) |
| **Format** | ZIP archive containing 6 CSV files (latin1 encoding) |
| **Status** | **Loaded** — Phase 1 complete |
| **Download** | `Duke-Source-CSV.zip` (~5.8 MB) |

**Entity Counts (as loaded):**

| Entity | Count | Source File |
|--------|-------|-------------|
| Herbs/Plants | 2,376 | FNFTAX.csv |
| Compounds | 94,512 | CHEMICALS.csv |
| Herb-compound links | 99,280 | FARMACY_NEW.csv |
| Common names | multi-valued | COMMON_NAMES.csv |
| Plant parts | lookup table | PARTS.csv |
| Bioactivities | per-compound | AGGREGAC.csv |

**CSV Files & Column Headers:**

| File | Key Columns | Purpose |
|------|-------------|---------|
| `FNFTAX.csv` | FNFNUM, TAXON, FAMILY, GENUS, SPECIES | Plant taxonomy |
| `COMMON_NAMES.csv` | FNFNUM, CNNAM | Common name aliases |
| `CHEMICALS.csv` | CHEM, CAS_NUMBER | Compound registry |
| `FARMACY_NEW.csv` | FNFNUM, CHEM, PPM_LOW, PPM_HIGH, PART_CODE, CLASS, REFERENCE | Herb-compound links with concentrations |
| `AGGREGAC.csv` | CHEM, ACTIVITY | Bioactivity annotations |
| `PARTS.csv` | PART_CODE, PART_NAME | Plant part lookup |

**Schema (as loaded into SQLite):**

```sql
CREATE TABLE herbs (
  id TEXT PRIMARY KEY,              -- FNFNUM from Duke
  scientific_name TEXT NOT NULL,    -- TAXON
  common_name TEXT,                 -- first CNNAM
  family TEXT,                      -- FAMILY
  genus TEXT,                       -- GENUS
  species TEXT,                     -- SPECIES
  usage_type TEXT,
  alternate_names TEXT              -- JSON array of all CNNAMs
);

CREATE TABLE compounds (
  id TEXT PRIMARY KEY,              -- normalizeCompoundName(CHEM)
  name TEXT NOT NULL,               -- original CHEM
  name_normalized TEXT NOT NULL,    -- lowercase stripped
  cas_number TEXT,                  -- CAS_NUMBER
  pubchem_cid TEXT,                 -- (not populated from Duke)
  compound_class TEXT,              -- CLASS from FARMACY_NEW
  bioactivities TEXT                -- JSON array from AGGREGAC
);

CREATE TABLE herb_compounds (
  herb_id TEXT NOT NULL REFERENCES herbs(id),
  compound_id TEXT NOT NULL REFERENCES compounds(id),
  plant_part TEXT,                  -- resolved PART_NAME
  plant_part_code TEXT,             -- PART_CODE
  concentration_low_ppm REAL,       -- PPM_LOW
  concentration_high_ppm REAL,      -- PPM_HIGH
  compound_class TEXT,              -- CLASS
  reference TEXT,                   -- REFERENCE
  source TEXT DEFAULT 'duke',
  PRIMARY KEY (herb_id, compound_id, plant_part_code)
);
```

**Indexes:**
```
idx_herbs_common_name (common_name)
idx_herbs_scientific_name (scientific_name)
idx_compounds_name_normalized (name_normalized)
idx_compounds_name (name)
idx_herb_compounds_herb (herb_id)
idx_herb_compounds_compound (compound_id)
```

**Relationships:**
```
Herb ──[CONTAINS {plant_part, concentration_ppm}]──► Compound
Compound ──[HAS_BIOACTIVITY]──► Bioactivity (stored as JSON array)
```

---

### 3.2 CMAUP 2024 (Collective Molecular Activities of Useful Plants)

| Field | Value |
|-------|-------|
| **URL** | https://bidd.group/CMAUP/ |
| **Paper** | NAR 2024: https://academic.oup.com/nar/article/52/D1/D1508/7332076 |
| **License** | Freely accessible for academic use |
| **Format** | CSV downloadable files |
| **Status** | Planned — Phase 4 |

**Entity Counts:**

| Entity | Count |
|--------|-------|
| Plants (total) | 7,865 |
| — Medicinal plants | 2,567 |
| — Food plants | 170 |
| — Edible plants | 1,567 |
| — Other useful plants | 3,561 |
| Ingredients/compounds | 60,222 |
| Potent targets | 758 |
| Diseases | 1,399 |
| KEGG pathways | 238 |
| GO terms | 3,013 |
| Clinical trials (plant-level) | 691 |
| Clinical trials (ingredient-level) | 14,516 |
| Target-based associations | 428,737 |

**Key Distinguishing Feature:** Explicit **food/edible/medicinal** plant classification — the only source that tells us which herbs are also foods.

**Entity-Relationship Diagram:**

```
┌──────────┐    ┌──────────────┐    ┌──────────┐
│  Plant   │───►│  Ingredient  │───►│  Target  │
│ (7,865)  │    │  (60,222)    │    │  (758)   │
│          │    │              │    │          │
│ is_food  │    │ activity_val │    │ uniprot  │
│ is_edible│    │ ADME props   │    │ gene_sym │
└──────────┘    └──────────────┘    └──────────┘
                                         │
                                         ▼
                                    ┌──────────┐
                                    │ Disease  │
                                    │ (1,399)  │
                                    │          │
                                    │ evidence │
                                    │ layer    │
                                    └──────────┘
```

**4 Evidence Layers for Disease Associations:**
1. Target mapping (computational)
2. Transcriptomic reversal
3. Plant-level clinical trials
4. Ingredient-level clinical trials

**Planned Schema (Phase 4):**

```sql
-- Enrichment to herbs table
ALTER TABLE herbs ADD COLUMN is_food_plant INTEGER DEFAULT 0;
ALTER TABLE herbs ADD COLUMN is_edible INTEGER DEFAULT 0;

CREATE TABLE targets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  uniprot_id TEXT,
  gene_symbol TEXT,
  source TEXT DEFAULT 'cmaup'
);

CREATE TABLE compound_targets (
  compound_id TEXT NOT NULL REFERENCES compounds(id),
  target_id TEXT NOT NULL REFERENCES targets(id),
  activity_value REAL,
  activity_type TEXT,
  interaction_type TEXT,
  source TEXT DEFAULT 'cmaup',
  PRIMARY KEY (compound_id, target_id, source)
);

CREATE TABLE target_diseases (
  target_id TEXT NOT NULL REFERENCES targets(id),
  disease_name TEXT NOT NULL,
  disease_id TEXT,
  evidence_layer TEXT,
  source TEXT DEFAULT 'cmaup',
  PRIMARY KEY (target_id, disease_name, source)
);
```

---

### 3.3 BATMAN-TCM 2.0

| Field | Value |
|-------|-------|
| **URL** | http://bionet.ncpsb.org.cn/batman-tcm/ |
| **Paper** | NAR 2024: https://academic.oup.com/nar/article/52/D1/D1110/7334089 |
| **License** | CC BY-NC |
| **Format** | Tab-delimited text files (bulk download), JSON API |
| **Status** | Planned — Phase 7 |

**Entity Counts:**

| Entity | Count |
|--------|-------|
| Herbs | 8,404 |
| Ingredients/compounds | 39,171 |
| Target proteins | 9,927 |
| Formulas | 54,832 |
| Known compound-target interactions | 17,068 |
| Predicted compound-target interactions | ~2,300,000 |

**Key Distinguishing Feature:** **Largest entity counts** of any TCM database. 2.3M predicted interactions provide dense graph connectivity for multi-hop queries.

**Relationships:**
```
Herb ──[CONTAINS]──► Ingredient ──[TARGETS (known)]──► Target ──[ASSOCIATED]──► Disease
                                  ──[TARGETS (predicted, with confidence)]──►
Herb ──[IN_FORMULA]──► Formula
```

**Download Files (expected):**

| File | Content | Columns |
|------|---------|---------|
| `herb_ingredient.txt` | Herb-compound links | herb_id, herb_name, ingredient_id, ingredient_name |
| `ingredient_target_known.txt` | Experimentally validated | ingredient_id, target_id, interaction_type |
| `ingredient_target_predicted.txt` | Predicted interactions | ingredient_id, target_id, score |
| `target_disease.txt` | Target-disease associations | target_id, disease_id, disease_name |

**Planned Schema (Phase 7):**
Will extend `compound_targets` table with `source='batman-tcm'` and `confidence_score` column.

---

### 3.4 TCMSP (Traditional Chinese Medicine Systems Pharmacology)

| Field | Value |
|-------|-------|
| **URL** | https://tcmsp-e.com/ |
| **Paper** | J Cheminform 2014: https://jcheminf.biomedcentral.com/articles/10.1186/1758-2946-6-13 |
| **License** | CC BY 4.0 (most permissive among TCM sources) |
| **Format** | XGMML network files (Cytoscape-compatible), web search |
| **Status** | Deferred |

**Entity Counts:**

| Entity | Count |
|--------|-------|
| Herbs | 499 |
| Chemicals (total) | 29,384 |
| Unique molecules | 13,144 |
| Targets | 3,311 |
| Diseases | 837 |

**Key Distinguishing Feature:** **12 ADME pharmacokinetic properties** per compound (oral bioavailability, Caco-2, BBB penetration, drug-likeness, half-life, Lipinski's rule). Enables filtering for bioavailable compounds only.

**Relationships:**
```
Herb ──[H]──► Compound ──[C]──► Target ──[T]──► Disease
                │
                └── ADME: OB, Caco-2, BBB, DL, HL, MW, Lipinski
```

**ADME Properties (per compound):**

| Property | Description |
|----------|-------------|
| OB% | Oral bioavailability (%) |
| Caco-2 | Caco-2 permeability |
| BBB | Blood-brain barrier penetration |
| DL | Drug-likeness |
| FASA- | Fractional accessible surface area |
| TPSA | Topological polar surface area |
| MW | Molecular weight |
| AlogP | Lipophilicity |
| Hdon | H-bond donors |
| Hacc | H-bond acceptors |
| RBN | Rotatable bonds |
| HL | Half-life |

---

### 3.5 IMPPAT 2.0 (Indian Medicinal Plants, Phytochemistry and Therapeutics)

| Field | Value |
|-------|-------|
| **URL** | https://cb.imsc.res.in/imppat/ |
| **Code** | https://github.com/asamallab/IMPPAT2 (MIT) |
| **License** | MIT (code); database freely accessible |
| **Format** | Web database, SDF/MOL files for 3D structures |
| **Status** | Deferred |

**Entity Counts:**

| Entity | Count |
|--------|-------|
| Indian medicinal plants | 4,010 |
| Phytochemicals | 17,967 |
| Therapeutic uses | 1,095 |

**Key Distinguishing Feature:** Covers **Ayurvedic/Indian medicinal plants** (turmeric, ashwagandha, neem, tulsi) with FAIR-compliant stereo-aware 3D chemical structures.

**Relationships:**
```
Plant + Part ──[CONTAINS]──► Phytochemical
Plant + Part ──[USED_FOR]──► Therapeutic Use
```

---

## 4. Segment 2: Compound-to-Food Sources

These sources map **compounds → foods** with quantitative concentrations.

### 4.1 FooDB

| Field | Value |
|-------|-------|
| **URL** | https://foodb.ca |
| **License** | CC BY-NC 4.0 |
| **Format** | CSV dump (952 MB compressed), MySQL dump |
| **Status** | **Loaded** — Phase 1 complete |

**Entity Counts (as loaded):**

| Entity | Count |
|--------|-------|
| Compound-food pairs | 4,149,541 |
| Distinct compounds | ~28,000 |
| Distinct foods | ~1,000 |
| Food groups | ~20 |

**CSV Files Used:**

| File | Key Columns | Size |
|------|-------------|------|
| `Food.csv` | id, name, name_scientific, food_group | Small |
| `Compound.csv` | id, name, cas_number, moldb_formula | Small |
| `Content.csv` | food_id, source_id, source_type, orig_content, orig_unit, orig_food_part, citation | ~5M rows |

**Schema (as loaded):**

```sql
CREATE TABLE compound_foods (
  compound_id TEXT NOT NULL REFERENCES compounds(id),
  food_name TEXT NOT NULL,
  food_name_scientific TEXT,
  food_group TEXT,
  content_value REAL,
  content_min REAL,
  content_max REAL,
  content_unit TEXT,
  food_part TEXT,
  citation TEXT,
  foodb_food_id TEXT,
  foodb_compound_id TEXT,
  source TEXT DEFAULT 'foodb',
  PRIMARY KEY (compound_id, food_name, food_part)
);
```

**Indexes:**
```
idx_compound_foods_compound (compound_id)
idx_compound_foods_food (food_name)
```

**ETL Notes:**
- Streamed line-by-line (`readline.createInterface`) due to 5M+ rows
- Batch transactions: 10,000 rows per batch
- Filtered to `source_type === 'Compound'` only
- Joined to Duke compounds via `normalizeCompoundName()` on compound name

---

### 4.2 Phenol-Explorer 3.0

| Field | Value |
|-------|-------|
| **URL** | http://phenol-explorer.eu/ |
| **License** | Freely accessible for academic use |
| **Format** | Microsoft Access database files, PDF |
| **Status** | Deferred |

**Entity Counts:**

| Entity | Count |
|--------|-------|
| Polyphenol compounds | ~500 |
| Foods with polyphenol data | 400+ |
| Metabolites | 380 |

**Key Distinguishing Feature:** **Quantitative polyphenol concentrations in foods** with food processing retention factors. The gold standard for polyphenol→food mapping.

**Data Tables:**

| Table | Content |
|-------|---------|
| Composition | Polyphenol content per food (mg/100g) |
| Metabolism | Metabolite concentrations after ingestion |
| Retention Factors | How processing (cooking, drying) affects content |

---

### 4.3 USDA Flavonoid Database

| Field | Value |
|-------|-------|
| **URL** | https://agdatacommons.nal.usda.gov |
| **License** | Public domain |
| **Format** | CSV |
| **Status** | Deferred (public-domain fallback for CC BY-NC FooDB) |

Covers ~500 flavonoid compounds in ~400 foods. Subset of FooDB but fully public domain.

---

## 5. Segment 3: Symptom & Health Benefit Sources

These sources map **symptoms/conditions → herbs/compounds**.

### 5.1 SymMap v2

| Field | Value |
|-------|-------|
| **URL** | http://www.symmap.org/ |
| **Download** | http://www.symmap.org/download/ |
| **Paper** | NAR 2019: https://academic.oup.com/nar/article/47/D1/D1110/5150228 |
| **License** | Academic use |
| **Format** | Tabular/CSV key files |
| **Status** | Planned — Phase 4 |

**Entity Counts:**

| Entity | ID Format | Count |
|--------|-----------|-------|
| TCM symptoms | SMSY##### | 1,717 |
| Modern medicine (MM) symptoms | SMMS##### | 961 |
| Herbs | SMHB##### | 499 |
| Ingredients/compounds | SMIN##### | 19,595 |
| Target genes | — | 4,302 |
| Diseases | — | 5,235 |

**Relationship Types (6 direct + 9 indirect):**

| Relationship | Count | Type |
|--------------|-------|------|
| Herb → TCM symptom | 6,638 | Direct |
| TCM symptom → MM symptom | 2,978 | Direct |
| Herb → ingredient | 48,372 | Direct |
| MM symptom → disease | 12,107 | Direct |
| Ingredient → target | 29,370 | Direct |
| Target → disease | 7,256 | Direct |
| Herb → MM symptom | indirect | Via TCM symptom |
| Herb → disease | indirect | Via MM symptom or target |
| Plus 7 other indirect types | — | — |

**Entity-Relationship Diagram:**

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ TCM Symptom  │────►│  MM Symptom  │────►│   Disease    │
│   (1,717)    │     │    (961)     │     │   (5,235)    │
└──────────────┘     └──────────────┘     └──────────────┘
       ▲                                        ▲
       │                                        │
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│    Herb      │────►│  Ingredient  │────►│   Target     │
│    (499)     │     │  (19,595)    │     │   (4,302)    │
└──────────────┘     └──────────────┘     └──────────────┘
```

**Download Files (expected from http://www.symmap.org/download/):**

| File | Content | Key Columns |
|------|---------|-------------|
| `herb.csv` | Herb entities | herb_id, herb_name, herb_pinyin, herb_en |
| `tcm_symptom.csv` | TCM symptoms | symptom_id, symptom_name |
| `mm_symptom.csv` | Modern symptoms | symptom_id, symptom_name |
| `ingredient.csv` | Compounds | ingredient_id, molecule_name, formula, PubChem_id, CAS_id |
| `herb_tcm_symptom.csv` | Herb-symptom links | herb_id, symptom_id |
| `tcm_mm_symptom.csv` | Symptom mapping | tcm_symptom_id, mm_symptom_id |
| `herb_ingredient.csv` | Herb-compound links | herb_id, ingredient_id |
| `ingredient_target.csv` | Compound-target links | ingredient_id, target_id |
| `mm_symptom_disease.csv` | Symptom-disease links | symptom_id, disease_name |
| `target_disease.csv` | Target-disease links | target_id, disease_name |

**Planned Schema (Phase 4):**

```sql
CREATE TABLE symptoms (
  id TEXT PRIMARY KEY,            -- SMSY or SMMS ID
  name TEXT NOT NULL,
  symptom_type TEXT NOT NULL,     -- 'tcm' or 'modern'
  mm_symptom_id TEXT,             -- mapped MM symptom ID (for TCM symptoms)
  description TEXT,
  source TEXT DEFAULT 'symmap'
);

CREATE TABLE herb_symptoms (
  herb_id TEXT NOT NULL REFERENCES herbs(id),
  symptom_id TEXT NOT NULL REFERENCES symptoms(id),
  evidence_type TEXT,
  source TEXT DEFAULT 'symmap',
  PRIMARY KEY (herb_id, symptom_id)
);
```

**Cross-Reference Strategy:**
- SymMap herb IDs (SMHB####) ≠ Duke IDs (numeric FNFNUM)
- Join by normalized scientific name: `herbs.scientific_name LIKE symmap_herb.herb_name`
- SymMap ingredients have PubChem_id and CAS_id for compound cross-referencing

---

### 5.2 Chinese Medicine Entity Recognition Dataset (Kaggle)

| Field | Value |
|-------|-------|
| **URL** | https://www.kaggle.com/datasets/chanemo/chinese-medicine-entity-recognition-dataset |
| **License** | MIT |
| **Format** | JSON (medical_ner_entities.json in ZIP, ~2.9 MB) |
| **Status** | Low priority — NER training data, not structured KG |

**Entity Types (13 NER categories):**

| Tag | Entity Type | Description |
|-----|-------------|-------------|
| DRUG | Medicine | Chinese medicine substances |
| DRUG_INGREDIENT | Active ingredient | Pharmacologically active compounds |
| DRUG_GROUP | Drug class | Category of medicines |
| DRUG_DOSAGE | Formulation | Dosage forms (pill, decoction) |
| DRUG_TASTE | Nature/taste | TCM property: sweet, bitter, cool, warm |
| DRUG_EFFICACY | Function | Main effects and indications |
| DISEASE | Disease | Disease names |
| SYMPTOM | Symptom | Abnormal sensations or pathological changes |
| SYNDROME | TCM Syndrome | TCM-specific diagnostic patterns (e.g., qi deficiency) |
| DISEASE_GROUP | Disease class | Generalized disease concepts |
| FOOD | Food | Edible substances |
| FOOD_GROUP | Food class | Food categories |
| PERSON_GROUP | Population | Specific demographics (elderly, pregnant) |

**Data Format:** BIO tagging scheme (Beginning-Inside-Outside) for NER training.

```json
// Example structure (approximate)
{
  "text": "黄芪补气升阳，用于气虚乏力...",
  "entities": [
    {"start": 0, "end": 2, "label": "DRUG", "text": "黄芪"},
    {"start": 2, "end": 6, "label": "DRUG_EFFICACY", "text": "补气升阳"},
    {"start": 8, "end": 12, "label": "SYNDROME", "text": "气虚乏力"}
  ]
}
```

**Sample size:** 1,000 annotated documents

**Knowledge Graph Potential:**
- **Primary use**: NER model training, NOT direct KG construction
- **Could enable KG via pipeline**: Train NER → Extract entities from TCM corpus → Apply relation extraction → Build structured triples
- **Relevant entity pairs for KG**: DRUG↔DRUG_INGREDIENT, DRUG↔DRUG_EFFICACY, DRUG↔DISEASE, SYMPTOM↔SYNDROME
- **Integration path**: Post-process extracted entities to supplement SymMap symptom-herb mappings, especially for TCM-specific syndromes not in SymMap

**Why low priority:**
- Requires ML pipeline (NER training + relation extraction) before structured data is available
- SymMap already provides structured symptom→herb mappings
- Primary value is enriching TCM syndrome vocabulary, not providing new relationships

---

## 6. Segment 4: Compound Reference & Disambiguation

These sources support **compound name normalization** and **cross-referencing** between sources.

### 6.1 PubChem

| Field | Value |
|-------|-------|
| **URL** | https://pubchem.ncbi.nlm.nih.gov |
| **API** | PUG-REST (free, no key needed) |
| **License** | Public domain |
| **Status** | As needed (for ambiguous compound disambiguation) |

**Role**: Canonical compound identifiers. PubChem CID resolves synonym issues ("Vitamin C" = "ascorbic acid" = "L-ascorbic acid" = CID 54670067).

**API Example:**
```
GET https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/curcumin/cids/JSON
→ {"IdentifierList": {"CID": [969516]}}
```

**Current Integration**: `compounds.pubchem_cid` column exists but is not populated from Duke's data. SymMap provides PubChem_id for its ingredients.

---

### 6.2 COCONUT 2.0

| Field | Value |
|-------|-------|
| **URL** | https://coconut.naturalproducts.net |
| **License** | CC0 (data), MIT (code) |
| **Format** | SDF (287-691 MB), CSV (191-207 MB), PostgreSQL dump (31.9 GB), SMILES |
| **Status** | Deferred |

**Entity Counts**: 400,000+ natural product compounds with organism sources, geographic data, chemical classifications. The largest open compound library.

---

### 6.3 LOTUS / Wikidata

| Field | Value |
|-------|-------|
| **URL** | https://lotus.naturalproducts.net |
| **License** | CC0 |
| **Format** | SPARQL endpoint via Wikidata |
| **Status** | Deferred |

Most comprehensive open compound→organism mapping. Queryable via Wikidata SPARQL for additional herb→compound pairs.

---

## 7. Segment 5: Prior Art & Pre-Built KGs

### 7.1 TCM_knowledge_graph (GitHub)

| Field | Value |
|-------|-------|
| **URL** | https://github.com/AI-HPC-Research-Team/TCM_knowledge_graph |
| **Format** | CSV files (3.4M records) |
| **License** | Varies by source |

**Integrates 6 sources:** SymMap, TCMID 2.0, CPMCP, PharMeBINet, PrimeKG, plus custom curation.

**Entity Types (20):** herbs, ingredients, diseases, genes, symptoms, syndromes, prescriptions, pathways, anatomical structures, side effects, pharmacologic classes, and more.

**Relationship Types (46):** Including herb-treats-disease, ingredient-targets-gene, symptom-associates-disease, herb-contains-ingredient.

**Value**: Pre-processed multi-source integration. Could accelerate Phase 4 ETL instead of downloading raw SymMap data separately.

---

### 7.2 FoodKG

| Field | Value |
|-------|-------|
| **URL** | https://foodkg.github.io/ |
| **Format** | RDF (63M triples) |
| **Sources** | USDA, FoodOn ontology, Im2Recipe |

Food ontology and recipe knowledge graph. Useful as a reference for food entity standardization.

---

### 7.3 HerbKG

| Field | Value |
|-------|-------|
| **URL** | https://github.com/FeiYee/HerbKG |
| **Format** | NER-extracted relations |
| **Source** | 500K PubMed abstracts → 53K relations |

NLP-derived herb-chemical-gene-disease relations. Less structured than curated databases but covers recent literature.

---

## 8. Knowledge Graph Schema

### Current State (Phase 1 — SQLite)

```
┌──────────┐                    ┌──────────────┐                    ┌──────────────┐
│  herbs   │──[herb_compounds]─►│  compounds   │──[compound_foods]─►│    foods     │
│  (2,376) │                    │  (94,512)    │                    │  (implicit)  │
│          │                    │              │                    │              │
│ id       │                    │ id           │                    │ food_name    │
│ sci_name │                    │ name         │                    │ food_group   │
│ com_name │                    │ cas_number   │                    │ content_val  │
│ family   │                    │ bioactivities│                    │              │
└──────────┘                    └──────────────┘                    └──────────────┘
                                       │
                                compound_name_map
                                (cross-source reconciliation)
```

### Target State (Phase 4+ — Expanded SQLite → Kuzu)

```
┌──────────────┐     ┌──────────────┐
│   Symptom    │────►│    Herb      │────────────────────────┐
│  (SymMap)    │     │ (Duke+CMAUP) │                        │
│              │     │              │                        │
│ id           │     │ is_food_plant│    ┌──────────────┐    │
│ name         │     │ is_edible    │───►│  Compound    │    │
│ symptom_type │     └──────────────┘    │(Duke+FooDB+  │    │
│ mm_symptom_id│                         │ CMAUP+SymMap)│    │
└──────────────┘                         │              │    │
       │                                 │ bioactivities│    │
       ▼                                 └──────┬───────┘    │
┌──────────────┐                                │            │
│   Disease    │◄───────────┐                   │            │
│  (CMAUP)     │            │                   ▼            │
│              │     ┌──────────────┐    ┌──────────────┐    │
│ disease_name │     │   Target     │    │    Food      │◄───┘
│ evidence     │◄────│  (CMAUP)     │    │  (FooDB)     │ [IS_FOOD]
└──────────────┘     │              │    │              │
                     │ uniprot_id   │    │ food_name    │
                     │ gene_symbol  │    │ food_group   │
                     └──────────────┘    └──────────────┘
```

### Full Table Index

| Table | Source(s) | Row Count | Phase |
|-------|-----------|-----------|-------|
| `herbs` | Duke, CMAUP | 2,376 (+CMAUP enrichment) | 1, 4 |
| `compounds` | Duke, FooDB, CMAUP, SymMap | 94,512 (+CMAUP/SymMap) | 1, 4 |
| `herb_compounds` | Duke | 99,280 | 1 |
| `compound_foods` | FooDB | 4,149,541 | 1 |
| `compound_name_map` | Duke, FooDB, CMAUP, SymMap | 99,430 (+new) | 1, 4 |
| `symptoms` | SymMap | 2,678 (1,717 TCM + 961 MM) | 4 |
| `herb_symptoms` | SymMap | ~6,638 | 4 |
| `targets` | CMAUP | ~758 | 4 |
| `compound_targets` | CMAUP, BATMAN-TCM | ~428K+ | 4, 7 |
| `target_diseases` | CMAUP | ~7,256 | 4 |

---

## 9. Cross-Source Join Strategy

### Primary Join Key: `normalizeCompoundName()`

```typescript
// Strips all non-alphanumeric characters, lowercases
normalizeCompoundName("Vitamin C")    → "vitaminc"
normalizeCompoundName("ascorbic acid") → "ascorbicacid"  // DIFFERENT — false negative!
normalizeCompoundName("L-Ascorbic Acid") → "lascorbicacid"  // DIFFERENT
```

**Limitation**: Pure string normalization cannot resolve synonyms. Mitigation: use PubChem CID as secondary join key when available.

### Cross-Reference Table

```sql
-- compound_name_map tracks provenance across sources
SELECT normalized_name, GROUP_CONCAT(source) as sources, COUNT(DISTINCT source) as source_count
FROM compound_name_map
GROUP BY normalized_name
HAVING source_count >= 2
ORDER BY source_count DESC;

-- Example output:
-- "quercetin" | "duke,foodb,cmaup,symmap" | 4
-- "curcumin"  | "duke,foodb,cmaup"        | 3
```

### Join Matrix

| Source A | Source B | Join Key | Expected Match Rate |
|----------|---------|----------|---------------------|
| Duke → FooDB | normalizeCompoundName(name) | ~4,449 bridge compounds (current) |
| Duke → CMAUP | normalizeCompoundName(name) + scientific_name | TBD — needs validation |
| Duke → SymMap | normalizeCompoundName(name) + PubChem_id/CAS_id | TBD — SymMap has PubChem IDs |
| SymMap → CMAUP | PubChem_id, normalizeCompoundName | TBD |
| FooDB → CMAUP | normalizeCompoundName(name) | TBD |

---

## 10. License Summary

| Source | License | Internal Use | External Product | Notes |
|--------|---------|-------------|-----------------|-------|
| Dr. Duke's | CC0 | Yes | Yes | Public domain, USDA-backed |
| FooDB | CC BY-NC 4.0 | Yes | **No** (needs commercial) | Non-commercial restriction |
| CMAUP 2024 | Academic | Yes | **Needs review** | Published in NAR; cite paper |
| SymMap v2 | Academic | Yes | **Needs review** | Published in NAR; cite paper |
| BATMAN-TCM 2.0 | CC BY-NC | Yes | **No** (needs commercial) | Non-commercial restriction |
| TCMSP | CC BY 4.0 | Yes | Yes | Most permissive TCM source |
| Phenol-Explorer | Academic | Yes | **Needs review** | Cite publications |
| IMPPAT 2.0 | MIT (code) | Yes | Yes (code) | Database access terms separate |
| PubChem | Public domain | Yes | Yes | US Government work |
| COCONUT 2.0 | CC0 | Yes | Yes | Public domain |
| TCM NER (Kaggle) | MIT | Yes | Yes | Fully open |
| USDA Flavonoid DB | Public domain | Yes | Yes | Fallback for FooDB |

**Key risk**: FooDB and BATMAN-TCM are CC BY-NC. If the product goes external-facing, these need commercial alternatives (USDA Flavonoid DB for food-compound data, TCMSP CC BY 4.0 for TCM compound-target data).

---

*Document generated: 2026-04-07*
*Source PRD: `.claude/PRPs/prds/mcp-herbal-botanicals.prd.md`*
*Implementation plan: `.claude/PRPs/plans/mcp-herbal-botanicals-phase4-kg-expansion.plan.md`*
