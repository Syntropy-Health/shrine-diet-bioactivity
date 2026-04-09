# Feature: Purchase-Health Correlation Data Source

## Summary

Add a fourth data source to open-diet-data that correlates health product purchases (supplements, health foods) with health outcomes through user reviews, adverse event reports, and survey data. This is implemented as a multi-layer data pipeline: (1) ingest three freely available public datasets (FDA CAERS adverse events, NHANES supplement-biomarker surveys, UCI Drugs.com condition-labeled reviews), (2) build an NLP extraction pipeline to surface health signals from unstructured review text, and (3) define a first-party user survey framework for future longitudinal purchase-outcome collection. Output is a SQLite database + MCP tools enabling the Diet Insight Engine to recommend products based on actual health outcomes, not just nutrient content.

## User Story

As a health data researcher and Diet Insight Engine developer
I want purchase-health correlation datasets (or a pipeline to curate them)
So that the SDO can recommend products based on real health outcomes and adverse signals

## Problem Statement

The current Diet Insight Engine has nutrition facts data (USDA 900k+ foods, OpenNutrition 326k foods, NIH DSLD 200k+ supplement labels) but zero data connecting what people buy to how it affects their health. The SDO recommends foods purely by nutrient content — there is no signal for "people who took Vitamin D reported improved energy" or "this fish oil brand has adverse event reports." No single public dataset provides this link cleanly.

## Solution Statement

Compose three freely available open datasets into a unified purchase-health-correlation SQLite database:

1. **FDA CAERS** (adverse events) — structured reports of supplement adverse reactions with product names, symptoms (MedDRA coded), and outcomes
2. **NHANES supplement module** — validated survey data linking supplement use to biomarker levels and health conditions across 10,000+ participants per cycle
3. **UCI Drugs.com Reviews** (CC BY 4.0) — 215k reviews with explicit `condition` labels and `rating` scores, usable for NLP training

Plus an NLP extraction pipeline to generate structured `(product, health_signal, direction, confidence)` tuples from review text, and a first-party survey schema for future longitudinal collection.

## Metadata

| Field            | Value                                                        |
| ---------------- | ------------------------------------------------------------ |
| Type             | NEW_CAPABILITY                                               |
| Complexity       | HIGH                                                         |
| Systems Affected | open-diet-data (new data source), DATA_SOURCES.md, AGENT.md, PRD.md |
| Dependencies     | requests, pandas, Python 3.8+; openFDA API (free, key optional) |
| Estimated Tasks  | 10                                                           |

---

## UX Design

### Before State

```
+===========================================================================+
|                              BEFORE STATE                                  |
+===========================================================================+
|                                                                           |
|   +-------------+         +-------------+         +-------------+         |
|   |   USDA FDC  | ------> | OpenNutri.  | ------> |  NIH DSLD   |         |
|   |  (nutrition |         | (nutrition  |         | (supplement |         |
|   |   facts)    |         |  facts)     |         |  labels)    |         |
|   +------+------+         +------+------+         +------+------+         |
|          |                       |                       |                |
|          v                       v                       v                |
|   +---------------------------------------------------------------+       |
|   |            NutritionDataAgent (Unified Query)                 |       |
|   |   query_food() -> nutrients only                              |       |
|   |   recommend_foods() -> by nutrient content only               |       |
|   |   validate_supplement() -> label check only                   |       |
|   +---------------------------------------------------------------+       |
|                                                                           |
|   USER_FLOW: User reports symptoms -> SDO identifies deficiency ->        |
|              Recommends foods by nutrient content -> No outcome data      |
|   PAIN_POINT: "Take Vitamin D" with no evidence of real-world benefit     |
|   DATA_FLOW: Nutrients only; no purchase->outcome signal                  |
|                                                                           |
+===========================================================================+
```

### After State

```
+===========================================================================+
|                               AFTER STATE                                  |
+===========================================================================+
|                                                                           |
|   +-------+  +----------+  +---------+  +------------------------------+ |
|   | USDA  |  | OpenNut. |  |NIH DSLD |  | Purchase-Health Correlation  | |
|   | FDC   |  | MCP      |  | API     |  | (NEW)                        | |
|   +---+---+  +----+-----+  +----+----+  | - FDA CAERS adverse events   | |
|       |           |             |        | - NHANES supplement+biomarker| |
|       |           |             |        | - Drugs.com labeled reviews  | |
|       |           |             |        | - NLP-extracted health tuples| |
|       |           |             |        +-------------+----------------+ |
|       |           |             |                      |                  |
|       v           v             v                      v                  |
|   +---------------------------------------------------------------+       |
|   |            NutritionDataAgent (Unified Query)                 |       |
|   |   query_food() -> nutrients + health signals                  |       |
|   |   recommend_foods() -> ranked by outcomes + nutrients         |       |
|   |   validate_supplement() -> label + adverse events             |       |
|   |   NEW: get_health_signals(product) -> health outcome data     |       |
|   +---------------------------------------------------------------+       |
|                                                                           |
|   USER_FLOW: User reports symptoms -> SDO identifies deficiency ->        |
|              Recommends foods by nutrients AND real-world outcomes ->      |
|              Flags adverse events -> Confidence based on evidence          |
|   VALUE_ADD: Evidence-based recommendations with outcome citations        |
|   DATA_FLOW: Nutrients + purchase-outcome signals + adverse signals       |
|                                                                           |
+===========================================================================+
```

### Interaction Changes

| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `recommend_foods()` | Returns nutrients only | Returns nutrients + health outcome scores | Recommendations backed by real outcomes |
| `validate_supplement()` | Label check only | Label + FDA adverse event signal | Users warned of known adverse signals |
| Agent interface | 4 methods | 5 methods (+ `get_health_signals`) | New capability: query health outcomes by product |
| Data sources | 3 (USDA, OpenNutrition, NIH DSLD) | 4 (+ purchase-health-correlation) | Broader evidence base |

---

## Mandatory Reading

**CRITICAL: Implementation agent MUST read these files before starting any task:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `scripts/query-nih-dsld.py` | 1-220 | Python API client pattern to MIRROR exactly for FDA CAERS and NHANES scripts |
| P0 | `DATA_SOURCES.md` | 1-184 | Source documentation pattern — new source entry must match this format |
| P0 | `AGENT.md` | 40-45, 66-106 | Data source table + data models to extend |
| P1 | `scripts/generate-embeddings.py` | 37-75 | `create_food_text()` pattern for building embeddable strings from structured data |
| P1 | `PRD.md` | 24-64 | Data source specification and comparison matrix |
| P1 | `mcp-opennutrition/scripts/tsv-to-sqlite.ts` | 1-119 | ETL pipeline pattern for reference (but our ETL is Python) |
| P2 | `mcp-opennutrition/src/types.ts` | 1-48 | TypeScript type extension point for `source` discriminator |
| P2 | `docs/data-audit-results.md` | 1-35 | Data audit output format to follow |

**External Documentation:**

| Source | Section | Why Needed |
|--------|---------|------------|
| [openFDA CAERS API](https://open.fda.gov/apis/food/event/) | Query syntax | How to filter by industry_code=54 (supplements) |
| [NHANES Dietary Supplement Data](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Dietary) | DSQTOT module | Supplement use + biomarker linkage fields |
| [UCI Drugs.com Reviews](https://archive.ics.uci.edu/dataset/462/drug+review+dataset+drugs+com) | Dataset description | Fields: drugName, condition, review, rating |
| [FDA CAERS ReadMe](https://www.fda.gov/files/food/published/Read-Me-File-For-CFSAN-Adverse-Event-Reporting-System-Quarterly-Data-Extract.pdf) | CSV schema | Column definitions for quarterly extract |
| [WA MHMDA RCW 19.373](https://app.leg.wa.gov/RCW/default.aspx?cite=19.373&full=true) | Definition of consumer health data | Legal requirements for purchase-health data |

---

## Patterns to Mirror

**PYTHON_API_CLIENT:**
```python
# SOURCE: scripts/query-nih-dsld.py:1-16, 30-88
# COPY THIS PATTERN for FDA CAERS and NHANES scripts:

#!/usr/bin/env python3
"""
<Source Name> - Query Script
=============================================================================
<Description>

API Documentation: <url>
No API key required - public API with rate limits.

Usage:
    python scripts/query-<source>.py --search "vitamin d"
=============================================================================
"""

import argparse
import json
import sys
from typing import Optional

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

BASE_URL = "https://api.example.gov/v1"

def search(query: str, limit: int = 10) -> dict:
    """Search function with typed return."""
    url = f"{BASE_URL}/endpoint"
    params = {"search": query, "limit": limit}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()
```

**DATA_SOURCE_DOC_ENTRY:**
```markdown
# SOURCE: DATA_SOURCES.md:11-65
# COPY THIS PATTERN for new source entry:

### N. [Source Name] STATUS

**Status**: [Description]

| Attribute | Value |
| --- | --- |
| Source | [URL or repo] |
| License | [License type] |
| Data Types | [What kinds of records] |
| Items | [Count] |
| Format | [CSV | SQLite | REST API (JSON)] |
| Update Frequency | [Quarterly | Real-time] |

**Why Selected**:
- [Reason 1]
- [Reason 2]
```

**EMBEDDING_TEXT_CREATION:**
```python
# SOURCE: scripts/generate-embeddings.py:37-58
# COPY THIS PATTERN for building embeddable text from structured health data:

def create_health_signal_text(row: dict) -> str:
    """Create searchable text from health signal row."""
    parts = []
    if row.get('product_name'):
        parts.append(row['product_name'])
    if row.get('condition'):
        parts.append(f"Condition: {row['condition']}")
    if row.get('direction'):
        parts.append(f"Effect: {row['direction']}")
    return " | ".join(parts)
```

**AUDIT_OUTPUT_FORMAT:**
```markdown
# SOURCE: docs/data-audit-results.md:1-35
# COPY THIS FORMAT for purchase-health data audit:

# Purchase-Health Correlation Data Audit Results

**Date**: YYYY-MM-DD
**Database**: purchase_health.db
**Total records**: N

## Source Coverage

| Source | Records | Coverage Notes |
|---|---|---|
| FDA CAERS | N | Supplement adverse events (code 54) |
| NHANES | N | Supplement use + biomarker cycles |
| UCI Drugs.com | N | Condition-labeled reviews |
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `scripts/fetch-fda-caers.py` | CREATE | FDA CAERS adverse event data fetcher + SQLite loader |
| `scripts/fetch-nhanes-supplements.py` | CREATE | NHANES supplement/biomarker data downloader + processor |
| `scripts/fetch-drugscom-reviews.py` | CREATE | UCI Drugs.com dataset downloader + SQLite loader |
| `scripts/build-purchase-health-db.py` | CREATE | Orchestrator: merge all 3 sources into unified SQLite DB |
| `scripts/extract-health-signals.py` | CREATE | NLP pipeline: extract (product, signal, direction, confidence) tuples |
| `schemas/purchase-health-schema.sql` | CREATE | SQLite schema definition for the unified DB |
| `schemas/first-party-survey.yaml` | CREATE | Survey instrument definition for future user data collection |
| `DATA_SOURCES.md` | UPDATE | Add Purchase-Health Correlation source entry + comparison matrix row |
| `AGENT.md` | UPDATE | Add source to data table, extend NutrientProfile.source, add get_health_signals() |
| `PRD.md` | UPDATE | Add Phase 5 for purchase-health data; add source to comparison matrix |

---

## NOT Building (Scope Limits)

Explicit exclusions to prevent scope creep:

- **MCP server for purchase-health data**: Not in this phase. The existing mcp-opennutrition pattern can be extended later. This plan produces the SQLite DB and Python query scripts only.
- **Production NLP model training**: The extraction script uses rule-based + simple VADER/spaCy methods. Fine-tuned BioBERT is documented as a future enhancement, not built now.
- **First-party data collection app/UI**: Only the survey schema definition is created. No web UI, no mobile app, no backend endpoints.
- **iHerb/Amazon scraping**: Legally risky, ToS-prohibited. Only use published academic datasets and official APIs.
- **Shopify integration**: Already specified in PRD.md Phase 3; separate feature.
- **HIPAA/MHMDA compliance implementation**: Only documented as requirements in the survey schema. No consent flow code.
- **RAG embeddings for this source**: The embedding pipeline extension is a separate follow-up task.
- **Real-time API integration**: All data is batch-fetched and stored locally. No live API calls at query time.

---

## Step-by-Step Tasks

Execute in order. Each task is atomic and independently verifiable.

### Task 1: CREATE `schemas/purchase-health-schema.sql` - SQLite Schema

- **ACTION**: CREATE the unified database schema for purchase-health correlation data
- **IMPLEMENT**: Three source tables + one unified signals table:
  ```sql
  -- FDA CAERS adverse events
  CREATE TABLE caers_events (
    report_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    product_role TEXT,              -- 'suspect' | 'concomitant'
    industry_code TEXT,             -- '54' = dietary supplement
    reactions TEXT,                 -- JSON array of MedDRA terms
    outcomes TEXT,                  -- JSON array: hospitalization, death, etc.
    patient_age REAL,
    patient_sex TEXT,
    report_date TEXT,
    source TEXT DEFAULT 'fda_caers'
  );

  -- NHANES supplement use + biomarker linkage
  CREATE TABLE nhanes_supplement_use (
    seqn TEXT PRIMARY KEY,          -- NHANES respondent ID
    cycle TEXT NOT NULL,            -- e.g., '2021-2023'
    supplement_name TEXT,
    ingredient TEXT,
    amount REAL,
    unit TEXT,
    frequency TEXT,                 -- days per month
    duration_months REAL,
    linked_biomarkers TEXT,         -- JSON: {vitamin_d_level: 45.2, ...}
    health_conditions TEXT,         -- JSON array from medical exam
    source TEXT DEFAULT 'nhanes'
  );

  -- UCI Drugs.com condition-labeled reviews
  CREATE TABLE drugscom_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drug_name TEXT NOT NULL,
    condition TEXT,                 -- e.g., 'Depression', 'Insomnia'
    review_text TEXT,
    rating INTEGER,                -- 1-10
    date TEXT,
    useful_count INTEGER,
    source TEXT DEFAULT 'drugscom'
  );

  -- Unified health signals (NLP-extracted or direct)
  CREATE TABLE health_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    ingredient TEXT,                -- normalized ingredient name
    health_condition TEXT,          -- normalized condition
    direction TEXT NOT NULL,        -- 'positive' | 'negative' | 'neutral'
    confidence REAL,               -- 0.0-1.0
    evidence_type TEXT,            -- 'adverse_report' | 'survey' | 'review'
    evidence_source TEXT,          -- 'fda_caers' | 'nhanes' | 'drugscom'
    evidence_id TEXT,              -- FK to source table
    citation TEXT                  -- Human-readable citation
  );

  CREATE INDEX idx_signals_product ON health_signals(product_name);
  CREATE INDEX idx_signals_ingredient ON health_signals(ingredient);
  CREATE INDEX idx_signals_condition ON health_signals(health_condition);
  ```
- **MIRROR**: `mcp-opennutrition/scripts/tsv-to-sqlite.ts` — uses TEXT for all columns, JSON for nested data
- **GOTCHA**: Use TEXT not VARCHAR for SQLite; JSON columns stored as TEXT with `json()` validation
- **VALIDATE**: `sqlite3 :memory: < schemas/purchase-health-schema.sql` — must execute without errors

### Task 2: CREATE `scripts/fetch-fda-caers.py` - FDA CAERS Fetcher

- **ACTION**: CREATE Python script to fetch FDA CAERS adverse events for dietary supplements
- **IMPLEMENT**:
  - Module docstring following `scripts/query-nih-dsld.py:1-16` pattern
  - `try/except ImportError` for `requests` and `pandas`
  - Base URL: `https://api.fda.gov/food/event.json`
  - Filter: `products.industry_code:"54"` (dietary supplements)
  - Paginate through results (FDA API limit 100/request, max 26,000 skip)
  - Parse reactions (array), outcomes (array), products (array), patient demographics
  - Write to `output/purchase-health/caers_events.csv` and load into SQLite
  - CLI args: `--limit`, `--output-dir`, `--api-key` (optional, increases rate limit)
  - Rate limiting: 240 req/min without key, 120,000 req/day with key
- **MIRROR**: `scripts/query-nih-dsld.py:30-88` — REST client pattern
- **GOTCHA**: FDA API `skip` parameter maxes at 26,000; use `search` date ranges to get full dataset
- **GOTCHA**: `response.raise_for_status()` + `timeout=30` on every request
- **VALIDATE**: `python -m py_compile scripts/fetch-fda-caers.py` && `python scripts/fetch-fda-caers.py --limit 10`

### Task 3: CREATE `scripts/fetch-nhanes-supplements.py` - NHANES Downloader

- **ACTION**: CREATE Python script to download and process NHANES dietary supplement data
- **IMPLEMENT**:
  - Module docstring following project convention
  - Download DSQTOT (total supplement) and DSQIDS (individual supplement) SAS transport files from CDC
  - URL pattern: `https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{cycle}/DataFiles/DSQTOT_{suffix}.XPT`
  - Convert SAS XPT to CSV using `pandas.read_sas()`
  - Link to biomarker data (BIOPRO, VID) by SEQN respondent ID
  - Link to health conditions (MCQ medical conditions questionnaire) by SEQN
  - Output: `output/purchase-health/nhanes_supplements.csv`
  - CLI args: `--cycles` (default: "2017-2018,2019-2020,2021-2023"), `--output-dir`
- **MIRROR**: `scripts/fetch-usda.sh:54-100` pattern but in Python (subprocess not needed, pure Python HTTP)
- **GOTCHA**: SAS XPT format requires `pandas` with no extra deps; use `pd.read_sas(filepath, format='xport')`
- **GOTCHA**: NHANES cycles have different variable names across years — map carefully
- **VALIDATE**: `python -m py_compile scripts/fetch-nhanes-supplements.py` && `python scripts/fetch-nhanes-supplements.py --cycles "2021-2023" --limit 100`

### Task 4: CREATE `scripts/fetch-drugscom-reviews.py` - UCI Dataset Downloader

- **ACTION**: CREATE Python script to download and process the UCI Drugs.com reviews dataset
- **IMPLEMENT**:
  - Module docstring with UCI citation: Graber et al. 2018, CC BY 4.0 license
  - Download from UCI ML Repository: `https://archive.ics.uci.edu/static/public/462/drug+review+dataset+drugs+com.zip`
  - Extract ZIP, parse TSV files (train + test splits)
  - Fields: `drugName`, `condition`, `review`, `rating`, `date`, `usefulCount`
  - Filter to supplement-relevant entries (match against NIH DSLD ingredient list if available)
  - Output: `output/purchase-health/drugscom_reviews.csv`
  - CLI args: `--output-dir`, `--filter-supplements` (optional flag to filter to supplement-like products)
- **MIRROR**: `scripts/query-nih-dsld.py:1-16` docstring + argparse pattern
- **GOTCHA**: File encoding is Latin-1 (ISO-8859-1), not UTF-8
- **GOTCHA**: `condition` field has ~850 unique values; some are empty — handle with `.get("condition", "Unknown")`
- **VALIDATE**: `python -m py_compile scripts/fetch-drugscom-reviews.py` && `python scripts/fetch-drugscom-reviews.py --limit 100`

### Task 5: CREATE `scripts/build-purchase-health-db.py` - Unified DB Builder

- **ACTION**: CREATE orchestrator script that loads all three source CSVs into a single SQLite database
- **IMPLEMENT**:
  - Read CSVs from `output/purchase-health/` (caers_events.csv, nhanes_supplements.csv, drugscom_reviews.csv)
  - Apply `schemas/purchase-health-schema.sql` to create tables
  - Load each CSV into its respective table using `pandas.to_sql()` or raw `INSERT`
  - Generate basic health signals from structured data:
    - CAERS: each (product, reaction) pair → health_signal with direction='negative', evidence_type='adverse_report'
    - NHANES: supplement use + abnormal biomarker → health_signal with direction inferred from biomarker vs. RDA
    - Drugs.com: each (drug, condition, rating) → health_signal with direction from rating threshold (>=7 positive, <=4 negative)
  - Compute data completeness stats and print audit summary
  - Output: `output/purchase-health/purchase_health.db`
  - CLI args: `--input-dir`, `--output`, `--schema`
- **MIRROR**: `mcp-opennutrition/scripts/tsv-to-sqlite.ts:60-113` — transaction-wrapped bulk insert
- **GOTCHA**: Use `db.executemany()` with transaction for performance on large datasets
- **VALIDATE**: `python scripts/build-purchase-health-db.py` && `sqlite3 output/purchase-health/purchase_health.db "SELECT COUNT(*) FROM health_signals"`

### Task 6: CREATE `scripts/extract-health-signals.py` - NLP Extraction Pipeline

- **ACTION**: CREATE NLP pipeline to extract structured health signals from review text
- **IMPLEMENT**:
  - Module docstring with NLP method description
  - Three extraction levels (configurable via `--method`):
    1. **Rule-based** (default, no deps): regex patterns for health keywords + sentiment words
    2. **VADER** (requires `nltk`): sentiment scoring on review sentences mentioning health terms
    3. **spaCy NER** (requires `spacy` + `en_core_web_sm`): entity extraction for conditions/symptoms
  - Input: `output/purchase-health/purchase_health.db` (reads `drugscom_reviews` table)
  - Output: INSERT into `health_signals` table with evidence_type='review', direction from sentiment
  - Health keyword dictionary: symptoms, conditions, body systems (embedded in script or external YAML)
  - Confidence scoring: rule-based=0.5, VADER=0.6, spaCy=0.7 (baseline calibration)
  - CLI args: `--method`, `--db-path`, `--batch-size`
- **MIRROR**: `scripts/generate-embeddings.py:78-131` — batch processing with progress output pattern
- **GOTCHA**: `try/except ImportError` for nltk, spacy — graceful fallback to rule-based
- **GOTCHA**: Write to same DB file as build script; use `INSERT OR IGNORE` to avoid duplicates
- **VALIDATE**: `python -m py_compile scripts/extract-health-signals.py` && `python scripts/extract-health-signals.py --method rule_based --batch-size 100`

### Task 7: CREATE `schemas/first-party-survey.yaml` - Survey Instrument Definition

- **ACTION**: CREATE YAML schema defining the first-party user survey for longitudinal purchase-outcome collection
- **IMPLEMENT**:
  - Survey metadata: name, version, validated instrument reference (SFQ)
  - Consent section: MHMDA-compliant disclosure of health data use
  - Purchase tracking fields: product_name, brand, purchase_date, purchase_source, amount
  - Supplement frequency questionnaire (SFQ): 16 categories per validated instrument
  - Health outcome check-in fields: condition, symptom_change, severity_scale (1-10), timepoint (30d, 90d)
  - Privacy fields: data_retention_days, anonymization_method, deletion_endpoint
  - Legal compliance notes: WA MHMDA, FTC Health Breach Notification Rule
- **GOTCHA**: This is a specification file only — no implementation code
- **VALIDATE**: `python -c "import yaml; yaml.safe_load(open('schemas/first-party-survey.yaml'))"` — must parse without errors

### Task 8: UPDATE `DATA_SOURCES.md` - Add New Source Entry

- **ACTION**: ADD Purchase-Health Correlation section following existing source entry pattern
- **IMPLEMENT**:
  - New `### 4. Purchase-Health Correlation Data` section after NIH DSLD section
  - Attribute table with: Source (3 sub-sources), License (Public Domain + CC BY 4.0), Data Types, Items, Format (SQLite), Update (FDA quarterly, NHANES biennial, UCI static)
  - "Why Selected" block
  - "Key Files" list pointing to new scripts
  - Update comparison matrix to add column for new source
- **MIRROR**: `DATA_SOURCES.md:11-65` — exact section structure
- **VALIDATE**: Visual inspection — section renders correctly in markdown preview

### Task 9: UPDATE `AGENT.md` - Extend Agent Specification

- **ACTION**: UPDATE data sources table, data models, and query interface
- **IMPLEMENT**:
  - Add row to data sources table (lines 40-45): `Purchase-Health Correlation | Local DB | output/purchase-health/ | Active`
  - Extend `NutrientProfile.source` Literal (line 82): add `"purchase_health"`
  - Add new data model:
    ```python
    class HealthSignal(BaseModel):
        product_name: str
        ingredient: Optional[str]
        health_condition: str
        direction: Literal["positive", "negative", "neutral"]
        confidence: float
        evidence_type: str
        citation: Optional[str]
    ```
  - Add `get_health_signals(product) -> List[HealthSignal]` to Unified Query Interface (lines 66-69)
  - Add `PurchaseHealthClient` to architecture diagram (lines 50-71)
- **MIRROR**: `AGENT.md:77-106` — Pydantic data model pattern
- **VALIDATE**: Markdown renders correctly; all cross-references consistent

### Task 10: UPDATE `PRD.md` - Add Phase 5

- **ACTION**: ADD purchase-health data source as Phase 5 in the timeline and requirements
- **IMPLEMENT**:
  - Add `### 4. Purchase-Health Correlation (Evidence)` to Data Sources section (after NIH DSLD)
  - Add functional requirements:
    - FR-7: Ingest FDA CAERS adverse event data for supplements (P1)
    - FR-8: Link NHANES supplement use to biomarker outcomes (P1)
    - FR-9: Extract health signals from product reviews via NLP (P2)
    - FR-10: Define first-party survey schema for longitudinal collection (P2)
  - Add Phase 5 to timeline: "Purchase-health correlation data pipeline" — 2 weeks
  - Update comparison matrix row
  - Add legal requirement: NFR-5 — MHMDA compliance for any user health data
- **MIRROR**: `PRD.md:24-64` — data source specification pattern
- **VALIDATE**: Markdown renders correctly; phase numbering is sequential

---

## Testing Strategy

### Validation by Source

| Script | Test Method | Validates |
|--------|------------|-----------|
| `scripts/fetch-fda-caers.py` | `--limit 10` → check CSV output has correct columns | API connectivity, parsing |
| `scripts/fetch-nhanes-supplements.py` | `--cycles "2021-2023" --limit 100` → check CSV | SAS XPT conversion, column mapping |
| `scripts/fetch-drugscom-reviews.py` | `--limit 100` → check CSV has condition, rating | UCI download, TSV parsing |
| `scripts/build-purchase-health-db.py` | Full run → `SELECT COUNT(*)` per table | SQLite schema, data loading |
| `scripts/extract-health-signals.py` | `--method rule_based --batch-size 100` → check signals | NLP extraction, DB insertion |

### Edge Cases Checklist

- [ ] FDA API returns empty results (no supplements in date range)
- [ ] NHANES cycle URL returns 404 (cycle not yet published)
- [ ] Drugs.com CSV has empty condition field (handle as "Unknown")
- [ ] Drugs.com CSV encoding is Latin-1, not UTF-8
- [ ] SQLite DB file already exists (should overwrite or merge gracefully)
- [ ] Network timeout during batch fetch (retry with backoff)
- [ ] NLP extraction produces zero signals for a review (skip, don't error)
- [ ] FDA CAERS `skip` parameter exceeds 26,000 (switch to date-range pagination)
- [ ] NHANES variable names differ across cycles (mapping table needed)

---

## Validation Commands

### Level 1: STATIC_ANALYSIS

```bash
# Python syntax check for all new scripts
python -m py_compile scripts/fetch-fda-caers.py
python -m py_compile scripts/fetch-nhanes-supplements.py
python -m py_compile scripts/fetch-drugscom-reviews.py
python -m py_compile scripts/build-purchase-health-db.py
python -m py_compile scripts/extract-health-signals.py

# SQL schema validation
sqlite3 :memory: < schemas/purchase-health-schema.sql

# YAML validation
python -c "import yaml; yaml.safe_load(open('schemas/first-party-survey.yaml'))"
```

**EXPECT**: Exit 0, no syntax errors

### Level 2: UNIT_TESTS

```bash
# Fetch with small limits to verify API connectivity and parsing
python scripts/fetch-fda-caers.py --limit 10 --output-dir /tmp/test-ph
python scripts/fetch-drugscom-reviews.py --limit 100 --output-dir /tmp/test-ph

# Verify CSV outputs
python -c "import pandas as pd; df = pd.read_csv('/tmp/test-ph/caers_events.csv'); print(f'CAERS: {len(df)} rows, cols: {list(df.columns)}')"
python -c "import pandas as pd; df = pd.read_csv('/tmp/test-ph/drugscom_reviews.csv'); print(f'Reviews: {len(df)} rows, cols: {list(df.columns)}')"
```

**EXPECT**: Non-zero row counts, expected column names present

### Level 3: FULL_PIPELINE

```bash
# Full pipeline end-to-end
python scripts/fetch-fda-caers.py --output-dir output/purchase-health
python scripts/fetch-drugscom-reviews.py --output-dir output/purchase-health
python scripts/build-purchase-health-db.py --output output/purchase-health/purchase_health.db
python scripts/extract-health-signals.py --db-path output/purchase-health/purchase_health.db --method rule_based

# Verify final DB
sqlite3 output/purchase-health/purchase_health.db "SELECT source, COUNT(*) FROM health_signals GROUP BY source"
```

**EXPECT**: health_signals table populated from at least 2 sources

### Level 6: MANUAL_VALIDATION

1. Query the DB for a known supplement: `sqlite3 output/purchase-health/purchase_health.db "SELECT * FROM health_signals WHERE product_name LIKE '%vitamin d%' LIMIT 5"`
2. Verify adverse events have MedDRA reaction terms
3. Verify review signals have direction and confidence scores
4. Check `DATA_SOURCES.md` renders correctly in GitHub markdown preview
5. Check `AGENT.md` data model additions are consistent with existing patterns

---

## Acceptance Criteria

- [ ] All 5 new Python scripts pass syntax validation
- [ ] SQLite schema creates all 4 tables without errors
- [ ] FDA CAERS script fetches supplement adverse events (industry_code 54)
- [ ] Drugs.com script downloads and parses the UCI CC BY 4.0 dataset
- [ ] Build script produces a single SQLite DB with populated health_signals table
- [ ] NLP extraction script generates at least rule-based signals from review text
- [ ] Survey YAML schema parses without errors and includes MHMDA consent fields
- [ ] DATA_SOURCES.md, AGENT.md, and PRD.md are updated consistently
- [ ] No copyrighted data is committed to git — all generated data is in output/ (gitignored)
- [ ] All scripts handle missing dependencies gracefully with try/except ImportError

---

## Completion Checklist

- [ ] All tasks completed in dependency order (schema → fetchers → builder → extractor → docs)
- [ ] Each task validated immediately after completion
- [ ] Level 1: Static analysis passes
- [ ] Level 2: Unit tests pass with small limits
- [ ] Level 3: Full pipeline produces populated DB
- [ ] Level 6: Manual validation confirms data quality
- [ ] All acceptance criteria met

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| FDA CAERS API rate limiting | MEDIUM | LOW | Use optional API key; implement exponential backoff; batch by date range |
| NHANES variable name changes across cycles | HIGH | MEDIUM | Build explicit column mapping dict per cycle; test with 2+ cycles |
| UCI Drugs.com dataset URL changes | LOW | LOW | Fallback to Hugging Face mirror; document both URLs |
| NLP extraction low precision (rule-based) | HIGH | LOW | Start with rule-based as baseline; document BioBERT upgrade path |
| Legal risk: inferring health from purchases | MEDIUM | HIGH | Survey schema includes MHMDA consent; no PII stored; all source data is public |
| Large dataset size (CAERS ~500k reports) | LOW | MEDIUM | Implement `--limit` on all scripts; pagination with progress output |
| Drugs.com reviews ToS for production use | MEDIUM | MEDIUM | UCI dataset is CC BY 4.0 for research; document limitations in DATA_SOURCES.md |

---

## Notes

### Design Decisions

1. **Three open datasets, not scraping**: FDA CAERS (public domain), NHANES (public domain), and UCI Drugs.com (CC BY 4.0) are all freely available with clear licensing. No web scraping needed.
2. **SQLite, not Postgres**: Matches the existing OpenNutrition pattern. Local-first, no server needed, gitignored output.
3. **Python pipeline, not TypeScript**: The NHANES SAS XPT format requires `pandas.read_sas()`. Python is the natural choice and matches the existing `scripts/` convention.
4. **Rule-based NLP first**: Start simple, document the upgrade path to BioBERT/spaCy. Avoids heavy ML dependencies in the initial implementation.
5. **No MCP server yet**: The purchase-health data is a Python-side data source first. MCP tool registration is a follow-up task after the data pipeline is proven.
6. **Survey schema as YAML, not code**: The first-party collection system needs product, legal, and UX design before implementation. YAML captures the data model requirements without premature coding.

### Available Datasets Summary

| Dataset | Records | License | Health Labels | Cost |
|---------|---------|---------|---------------|------|
| FDA CAERS | ~500k+ reports | Public domain | MedDRA reactions, outcomes | Free |
| NHANES supplements | ~10k/cycle | Public domain | Biomarkers, conditions | Free |
| UCI Drugs.com | 215k reviews | CC BY 4.0 | Condition field (850 values) | Free |
| Amazon Reviews 2023 (Health) | 25.6M ratings | Research use | None (NLP required) | Free |
| UCI Druglib.com | ~10k reviews | CC BY 4.0 | side_effects, benefits fields | Free |
| Open Food Facts | 4M products | ODbL | None (nutrition only) | Free |

### Future Enhancements (Not in Scope)

1. **BioBERT/PubMedBERT fine-tuning**: Train on CAERS + Drugs.com for F1 ~0.78+ health entity extraction
2. **Amazon Reviews 2023 integration**: 25.6M health category reviews; requires NLP at scale
3. **MCP server for purchase-health data**: Expose health_signals via MCP tools like OpenNutrition
4. **RAG embeddings**: Generate embeddings from health_signals for vector search
5. **First-party collection app**: Implement the survey schema as a web/mobile app with consent flows
6. **Knowledge graph**: Build supplement-condition-outcome graph from extracted signals (cf. iDISK2.0)

### Key External References

- [openFDA CAERS API](https://open.fda.gov/apis/food/event/) — supplement adverse events
- [NHANES Dietary Supplement Data](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Dietary) — supplement use surveys
- [UCI Drugs.com Dataset](https://archive.ics.uci.edu/dataset/462/drug+review+dataset+drugs+com) — condition-labeled reviews
- [RAMIE NLP Framework (JAMIA 2025)](https://academic.oup.com/jamia/article/32/3/545/7951915) — state-of-art supplement NLP
- [WA MHMDA](https://app.leg.wa.gov/RCW/default.aspx?cite=19.373&full=true) — health data privacy law
- [Shopping History Biases (npj Digital Medicine 2024)](https://www.nature.com/articles/s41746-024-01231-4) — methodological framework
