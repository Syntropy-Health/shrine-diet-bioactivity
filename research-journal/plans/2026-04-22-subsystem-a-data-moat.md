# Subsystem A — Data Moat Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the LightRAG knowledge graph to full-breadth data readiness for primary-paper evaluation — ingest SymMap + HERB 2.0, curate HDI-Safe 50, populate food_nutrition_bridge, un-pin the subsample, and produce a reproducible ingestion snapshot.

**Architecture:** Incremental ETL into the existing SQLite intermediate (`data_local/herbal_botanicals.db`), followed by `ainsert_custom_kg` ingestion into LightRAG/Neo4j Aura. New edge types (`INTERACTS_WITH`, `CONTRAINDICATES`) extend `entity_schema.py`. Curated data files (HDI-Safe 50, symptom crosswalk) live under `research-journal/shared/` as checked-in JSON.

**Tech Stack:** TypeScript (Node 18+, better-sqlite3, tsx), Python 3.10+ (pytest, neo4j driver, dotenv), LightRAG (HKUDS), Neo4j Aura.

**Prerequisites:**
- Phase B Neo4j Aura credentials live in Infisical "SyntropyHealth App" and local gitignored `.env`. If not, see `research-journal/DESIGN.md §Open risks` and block on user rotation first.
- Working dir: `/home/mo/projects/SyntropyHealth/apps/shrine-diet-bioactivity`
- Existing DB: `shrine-diet-bioactivity/data_local/herbal_botanicals.db`

---

## File layout created or modified

| Path | Role |
|---|---|
| `shrine-diet-bioactivity/scripts/check-aura.ts` *(new)* | Preflight connectivity + baseline count |
| `shrine-diet-bioactivity/scripts/download-symmap.ts` *(new)* | SymMap v2 TSV downloader |
| `shrine-diet-bioactivity/scripts/load-symmap.ts` *(new)* | SymMap → SQLite loader |
| `shrine-diet-bioactivity/scripts/build-symptom-crosswalk.ts` *(new)* | Duke↔SymMap alignment |
| `shrine-diet-bioactivity/scripts/download-herb2.ts` *(new)* | HERB 2.0 downloader |
| `shrine-diet-bioactivity/scripts/load-herb2.ts` *(new)* | HERB 2.0 → SQLite loader with evidence tiers |
| `shrine-diet-bioactivity/scripts/ingest-hdi.py` *(new)* | HDI + CONTRAINDICATES ingestion via `ainsert_custom_kg` |
| `shrine-diet-bioactivity/lightrag/entity_schema.py` *(modify)* | Add `INTERACTS_WITH`, `CONTRAINDICATES` relationship types + SymMap/HERB 2.0 description generators |
| `shrine-diet-bioactivity/Makefile` *(modify)* | `MAX_RELATIONSHIPS` default + new targets |
| `research-journal/shared/hdi_safe_50.json` *(new)* | Curated 50-interaction reference set |
| `research-journal/shared/symptom_crosswalk.json` *(new)* | Duke↔SymMap symptom alignment |
| `research-journal/shared/ingestion-snapshot.md` *(new)* | Post-ingest KG metrics report |
| `shrine-diet-bioactivity/src/__tests__/symmap-load.test.ts` *(new)* | Vitest coverage for SymMap loader |
| `shrine-diet-bioactivity/src/__tests__/herb2-load.test.ts` *(new)* | Vitest coverage for HERB 2.0 loader |
| `shrine-diet-bioactivity/lightrag/test_ingest_hdi.py` *(new)* | pytest coverage for HDI ingestion |
| `shrine-diet-bioactivity/lightrag/test_aura_connectivity.py` *(new)* | pytest preflight |

---

## Task 0 — Preflight: Neo4j Aura connectivity

**Purpose:** Fail fast if credentials are missing or Aura is unreachable.

**Files:**
- Create: `shrine-diet-bioactivity/lightrag/test_aura_connectivity.py`
- Create: `shrine-diet-bioactivity/scripts/check-aura.ts`

- [ ] **Step 1: Write the failing test**

```python
# shrine-diet-bioactivity/lightrag/test_aura_connectivity.py
import os
import pytest
from neo4j import GraphDatabase


@pytest.mark.integration
def test_aura_reachable_and_returns_constant():
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    assert uri.startswith("neo4j+s://"), "expected Aura secure URI"
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as s:
            assert s.run("RETURN 1 AS ok").single()["ok"] == 1
```

- [ ] **Step 2: Run test — expect failure until env vars set**

```bash
cd shrine-diet-bioactivity && pytest lightrag/test_aura_connectivity.py -m integration -v
```
Expected: **KeyError** if `.env` not loaded, or **ServiceUnavailable** if creds wrong.

- [ ] **Step 3: Confirm env via `.env` / Infisical**

Ensure `shrine-diet-bioactivity/.env` (gitignored) contains `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, loaded via `python-dotenv` or `infisical run --`.

- [ ] **Step 4: Re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity && infisical run -- pytest lightrag/test_aura_connectivity.py -m integration -v
```
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/lightrag/test_aura_connectivity.py
git commit -m "test(infra): Aura connectivity preflight"
```

---

## Task 0.5 — Shared config scaffolding (modularity + reproducibility)

**Purpose:** All ingestion scripts from Task 1 onward read from two YAML configs and a typed loader module, not hardcoded constants. This makes the pipeline reproducible, parameter-clear, and rewireable without code edits.

**Files:**
- Create: `shrine-diet-bioactivity/config/data_sources.yaml`
- Create: `shrine-diet-bioactivity/config/ingest_params.yaml`
- Create: `shrine-diet-bioactivity/src/config.ts` (Zod loader for TS scripts)
- Create: `shrine-diet-bioactivity/lightrag/config_loader.py` (Pydantic loader for Python)
- Create: `shrine-diet-bioactivity/src/__tests__/config.test.ts`
- Create: `shrine-diet-bioactivity/lightrag/test_config_loader.py`

### Config contract (both languages load the same YAML files)

```yaml
# shrine-diet-bioactivity/config/data_sources.yaml
symmap:
  base_url: https://www.symmap.org/static/download/
  files: [SMHB.txt, SMTT.txt, SMIT.txt, SMTT_SMHB.txt]
  out_dir: data/symmap
herb2:
  base_url: http://herb.ac.cn/static/download/
  files: [herb_info.txt, herb_experiment.txt, herb_clinical.txt]
  out_dir: data/herb2
paths:
  sqlite_db: data_local/herbal_botanicals.db
  hdi_safe_50: ../research-journal/shared/hdi_safe_50.json
  symptom_crosswalk: ../research-journal/shared/symptom_crosswalk.json
  ingestion_snapshot: ../research-journal/shared/ingestion-snapshot.md
```

```yaml
# shrine-diet-bioactivity/config/ingest_params.yaml
subsample:
  max_relationships: 0   # 0 = unlimited (full-scale); override for prototype
  seed: 42
ingestion:
  batch_size: 100
  max_async: 2
lightrag:
  working_dir: ./rag_storage_local
hdi_severity_weights:
  severe: 1.0
  moderate: 0.6
  mild: 0.3
evidence_tier_weights:
  clinical: 1.0
  clinical_trial: 1.0
  pharmacokinetic_study: 0.85
  observational: 0.7
  experimental: 0.55
  case_report_series: 0.5
  case_report: 0.4
  in_vitro: 0.3
  traditional: 0.2
```

### Loader contract

- Both loaders validate the YAML against schema at load time; missing/mistyped keys raise immediately.
- Paths in `data_sources.yaml` are resolved relative to the `shrine-diet-bioactivity/` subpackage root.
- Both loaders expose the same shape (same field names, same nesting) so scripts are language-parallel.
- Python loader uses `pydantic` (already a LightRAG transitive dep); TS loader uses `zod`.

- [ ] **Step 1: Write the failing tests**

```typescript
// shrine-diet-bioactivity/src/__tests__/config.test.ts
import { describe, it, expect } from 'vitest';
import { loadDataSources, loadIngestParams } from '../config';

describe('config loader', () => {
  it('loads data_sources.yaml with expected shape', () => {
    const cfg = loadDataSources();
    expect(cfg.symmap.base_url).toMatch(/^https?:\/\//);
    expect(cfg.symmap.files.length).toBeGreaterThan(0);
    expect(cfg.herb2.base_url).toMatch(/^https?:\/\//);
    expect(cfg.paths.sqlite_db).toContain('herbal_botanicals.db');
  });

  it('loads ingest_params.yaml with validated ranges', () => {
    const cfg = loadIngestParams();
    expect(cfg.subsample.seed).toBeTypeOf('number');
    expect(cfg.ingestion.batch_size).toBeGreaterThan(0);
    expect(cfg.hdi_severity_weights.severe).toBeGreaterThan(cfg.hdi_severity_weights.mild);
  });

  it('rejects malformed YAML at load time', () => {
    expect(() => loadDataSources('/dev/null/nonexistent.yaml')).toThrow();
  });
});
```

```python
# shrine-diet-bioactivity/lightrag/test_config_loader.py
import pytest
from pathlib import Path
from config_loader import load_data_sources, load_ingest_params, ConfigError


def test_loads_data_sources():
    cfg = load_data_sources()
    assert cfg.symmap.base_url.startswith(("http://", "https://"))
    assert len(cfg.symmap.files) > 0
    assert "herbal_botanicals.db" in cfg.paths.sqlite_db


def test_loads_ingest_params_with_validated_ranges():
    cfg = load_ingest_params()
    assert isinstance(cfg.subsample.seed, int)
    assert cfg.ingestion.batch_size > 0
    assert cfg.hdi_severity_weights["severe"] > cfg.hdi_severity_weights["mild"]


def test_rejects_malformed_yaml_at_load_time():
    with pytest.raises(ConfigError):
        load_data_sources(Path("/dev/null/nonexistent.yaml"))
```

- [ ] **Step 2: Run both test suites — expect FAIL**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/config.test.ts
cd shrine-diet-bioactivity/lightrag && pytest test_config_loader.py -v
```

- [ ] **Step 3: Write the two YAML configs + two loaders**

```typescript
// shrine-diet-bioactivity/src/config.ts
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { parse } from 'yaml';
import { z } from 'zod';

const DataSourcesSchema = z.object({
  symmap: z.object({
    base_url: z.string().url(),
    files: z.array(z.string()).min(1),
    out_dir: z.string(),
  }),
  herb2: z.object({
    base_url: z.string().url(),
    files: z.array(z.string()).min(1),
    out_dir: z.string(),
  }),
  paths: z.object({
    sqlite_db: z.string(),
    hdi_safe_50: z.string(),
    symptom_crosswalk: z.string(),
    ingestion_snapshot: z.string(),
  }),
});

const IngestParamsSchema = z.object({
  subsample: z.object({
    max_relationships: z.number().int().nonnegative(),
    seed: z.number().int(),
  }),
  ingestion: z.object({
    batch_size: z.number().int().positive(),
    max_async: z.number().int().positive(),
  }),
  lightrag: z.object({
    working_dir: z.string(),
  }),
  hdi_severity_weights: z.object({
    severe: z.number().min(0).max(1),
    moderate: z.number().min(0).max(1),
    mild: z.number().min(0).max(1),
  }),
  evidence_tier_weights: z.record(z.string(), z.number().min(0).max(1)),
});

export type DataSources = z.infer<typeof DataSourcesSchema>;
export type IngestParams = z.infer<typeof IngestParamsSchema>;

const DEFAULT_DATA = resolve(__dirname, '..', 'config', 'data_sources.yaml');
const DEFAULT_PARAMS = resolve(__dirname, '..', 'config', 'ingest_params.yaml');

export function loadDataSources(path: string = DEFAULT_DATA): DataSources {
  const raw = readFileSync(path, 'utf8');
  const parsed = parse(raw);
  return DataSourcesSchema.parse(parsed);
}

export function loadIngestParams(path: string = DEFAULT_PARAMS): IngestParams {
  const raw = readFileSync(path, 'utf8');
  const parsed = parse(raw);
  return IngestParamsSchema.parse(parsed);
}
```

```python
# shrine-diet-bioactivity/lightrag/config_loader.py
"""YAML-backed config loader shared across all ingestion scripts.
Same shape as shrine-diet-bioactivity/src/config.ts for language parity."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml
from pydantic import BaseModel, Field, ValidationError


class ConfigError(RuntimeError):
    pass


class DataSource(BaseModel):
    base_url: str
    files: list[str] = Field(min_length=1)
    out_dir: str


class Paths(BaseModel):
    sqlite_db: str
    hdi_safe_50: str
    symptom_crosswalk: str
    ingestion_snapshot: str


class DataSourcesConfig(BaseModel):
    symmap: DataSource
    herb2: DataSource
    paths: Paths


class SubsampleCfg(BaseModel):
    max_relationships: int = Field(ge=0)
    seed: int


class IngestionCfg(BaseModel):
    batch_size: int = Field(gt=0)
    max_async: int = Field(gt=0)


class LightRAGCfg(BaseModel):
    working_dir: str


class HDIWeights(BaseModel):
    severe:   float = Field(ge=0, le=1)
    moderate: float = Field(ge=0, le=1)
    mild:     float = Field(ge=0, le=1)


class IngestParamsConfig(BaseModel):
    subsample: SubsampleCfg
    ingestion: IngestionCfg
    lightrag: LightRAGCfg
    hdi_severity_weights: HDIWeights
    evidence_tier_weights: Mapping[str, float]


_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = _ROOT / "config" / "data_sources.yaml"
DEFAULT_PARAMS = _ROOT / "config" / "ingest_params.yaml"


def _load(path: Path, model: type[BaseModel]):
    try:
        raw = path.read_text()
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    try:
        return model.model_validate(yaml.safe_load(raw))
    except (yaml.YAMLError, ValidationError) as e:
        raise ConfigError(f"invalid config at {path}: {e}") from e


def load_data_sources(path: Path = DEFAULT_DATA) -> DataSourcesConfig:
    return _load(path, DataSourcesConfig)


def load_ingest_params(path: Path = DEFAULT_PARAMS) -> IngestParamsConfig:
    return _load(path, IngestParamsConfig)
```

Add `yaml` + `zod` to package.json dependencies; add `pyyaml` + `pydantic` to `lightrag/requirements.txt` if missing.

- [ ] **Step 4: Re-run both test suites — expect PASS**

```bash
cd shrine-diet-bioactivity && npm install yaml zod && npx vitest run src/__tests__/config.test.ts
cd shrine-diet-bioactivity/lightrag && pip install pyyaml pydantic && pytest test_config_loader.py -v
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/config/ shrine-diet-bioactivity/src/config.ts shrine-diet-bioactivity/src/__tests__/config.test.ts shrine-diet-bioactivity/lightrag/config_loader.py shrine-diet-bioactivity/lightrag/test_config_loader.py shrine-diet-bioactivity/package.json shrine-diet-bioactivity/package-lock.json shrine-diet-bioactivity/lightrag/requirements.txt
git commit -m "feat(config): YAML-backed data_sources + ingest_params with typed loaders"
```

**Note for downstream tasks:** Tasks 1–10 now read URLs, paths, seeds, batch sizes, and weight constants from these configs via `loadDataSources()` / `loadIngestParams()`. No hardcoded literals in the ingestion scripts. Example: `scripts/download-symmap.ts` becomes `const cfg = loadDataSources(); for (const f of cfg.symmap.files) { download(cfg.symmap.base_url + f, ...) }`.

---

## Task 1 — Populate `food_nutrition_bridge`

**Purpose:** The existing bridge script has never been executed; the table is empty. This enables nutrition-enriched Food nodes for Stage 3 Dietitian agent.

**Files:**
- Execute: `shrine-diet-bioactivity/scripts/build-food-bridge.ts` (existing)
- Execute: `shrine-diet-bioactivity/scripts/enrich-nutrition.ts` (existing)
- Modify: `shrine-diet-bioactivity/src/__tests__/food-bridge.test.ts` (existing — add count assertion)

- [ ] **Step 1: Extend existing test to assert non-empty bridge**

```typescript
// Append to src/__tests__/food-bridge.test.ts
import Database from 'better-sqlite3';
import { describe, it, expect } from 'vitest';

describe('food_nutrition_bridge population', () => {
  it('has at least 900 bridge rows after bridge+enrich', () => {
    const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });
    const row = db.prepare('SELECT COUNT(*) AS c FROM food_nutrition_bridge').get() as { c: number };
    expect(row.c).toBeGreaterThanOrEqual(900);
    db.close();
  });
});
```

- [ ] **Step 2: Run test — expect FAIL (table empty)**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/food-bridge.test.ts
```
Expected: the new case fails with `0 < 900`.

- [ ] **Step 3: Run the existing bridge + enrich pipeline**

```bash
cd shrine-diet-bioactivity && make food-bridge && make enrich-nutrition
```
Expected: console output reports ~962 FooDB foods processed, ≥ 900 matched.

- [ ] **Step 4: Re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/food-bridge.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/src/__tests__/food-bridge.test.ts
git commit -m "test(food-bridge): assert >=900 bridge rows after enrichment"
```

---

## Task 2 — Download SymMap v2

**Purpose:** Get the canonical TCM symptom + bilingual herb TSVs on disk.

**Files:**
- Create: `shrine-diet-bioactivity/scripts/download-symmap.ts`
- Modify: `shrine-diet-bioactivity/Makefile` (add `download-symmap` target)

- [ ] **Step 1: Write failing test**

```typescript
// shrine-diet-bioactivity/src/__tests__/symmap-download.test.ts
import { existsSync, statSync } from 'fs';
import { describe, it, expect } from 'vitest';

describe('SymMap download', () => {
  it.each([
    'data/symmap/SMHB.txt',
    'data/symmap/SMTT.txt',
    'data/symmap/SMIT.txt',
    'data/symmap/SMTT_SMHB.txt',
  ])('%s exists and is non-empty', (path) => {
    expect(existsSync(path)).toBe(true);
    expect(statSync(path).size).toBeGreaterThan(1024);
  });
});
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/symmap-download.test.ts
```

- [ ] **Step 3: Write downloader**

```typescript
// shrine-diet-bioactivity/scripts/download-symmap.ts
import { mkdirSync, createWriteStream } from 'fs';
import { get } from 'https';

const BASE = 'https://www.symmap.org/static/download/';
const FILES = ['SMHB.txt', 'SMTT.txt', 'SMIT.txt', 'SMTT_SMHB.txt'];
const OUT_DIR = 'data/symmap';

async function download(url: string, dest: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = createWriteStream(dest);
    get(url, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        return;
      }
      res.pipe(file);
      file.on('finish', () => file.close(() => resolve()));
    }).on('error', reject);
  });
}

async function main(): Promise<void> {
  mkdirSync(OUT_DIR, { recursive: true });
  for (const f of FILES) {
    const url = BASE + f;
    const dest = `${OUT_DIR}/${f}`;
    console.log(`fetching ${url}`);
    await download(url, dest);
  }
  console.log('done');
}

main().catch((e) => { console.error(e); process.exit(1); });
```

Add Makefile target:
```makefile
download-symmap:
	npx tsx scripts/download-symmap.ts
```

- [ ] **Step 4: Run + re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity && make download-symmap && npx vitest run src/__tests__/symmap-download.test.ts
```

- [ ] **Step 5: Commit (source files only — not raw data; ensure `data/symmap/` in `.gitignore`)**

```bash
git add shrine-diet-bioactivity/scripts/download-symmap.ts shrine-diet-bioactivity/src/__tests__/symmap-download.test.ts shrine-diet-bioactivity/Makefile
# Confirm data/symmap is ignored:
grep -q "^data/$" shrine-diet-bioactivity/.gitignore || echo "data/" >> shrine-diet-bioactivity/.gitignore
git add shrine-diet-bioactivity/.gitignore
git commit -m "feat(symmap): add SymMap v2 downloader"
```

---

## Task 3 — Load SymMap into SQLite

**Purpose:** Parse the four TSVs into new SQLite tables alongside Duke-derived data.

**Files:**
- Create: `shrine-diet-bioactivity/scripts/load-symmap.ts`
- Create: `shrine-diet-bioactivity/src/__tests__/symmap-load.test.ts`
- Modify: `shrine-diet-bioactivity/Makefile`

- [ ] **Step 1: Write failing test**

```typescript
// shrine-diet-bioactivity/src/__tests__/symmap-load.test.ts
import Database from 'better-sqlite3';
import { describe, it, expect } from 'vitest';

describe('SymMap SQLite load', () => {
  const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });

  it('symmap_symptoms has >= 5000 rows', () => {
    const r = db.prepare('SELECT COUNT(*) AS c FROM symmap_symptoms').get() as { c: number };
    expect(r.c).toBeGreaterThanOrEqual(5000);
  });

  it('symmap_herbs has CN + EN names', () => {
    const r = db.prepare('SELECT COUNT(*) AS c FROM symmap_herbs WHERE name_cn IS NOT NULL AND name_en IS NOT NULL').get() as { c: number };
    expect(r.c).toBeGreaterThan(1000);
  });

  it('symmap_herb_symptoms links both', () => {
    const r = db.prepare(`
      SELECT COUNT(*) AS c FROM symmap_herb_symptoms hs
      JOIN symmap_herbs h ON hs.herb_id = h.symmap_id
      JOIN symmap_symptoms s ON hs.symptom_id = s.symmap_id
    `).get() as { c: number };
    expect(r.c).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run test — expect FAIL (tables do not exist)**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/symmap-load.test.ts
```

- [ ] **Step 3: Write loader**

```typescript
// shrine-diet-bioactivity/scripts/load-symmap.ts
import Database from 'better-sqlite3';
import { readFileSync } from 'fs';

const DB = './data_local/herbal_botanicals.db';

function parseTsv(path: string): string[][] {
  return readFileSync(path, 'utf8').split('\n').filter(Boolean).map((l) => l.split('\t'));
}

function loadSymptoms(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_symptoms (
      symmap_id TEXT PRIMARY KEY,
      name_en   TEXT NOT NULL,
      name_cn   TEXT,
      tcm_category TEXT
    );
  `);
  const rows = parseTsv('data/symmap/SMIT.txt');
  const header = rows[0].map((h) => h.toLowerCase());
  const idIdx = header.indexOf('symmap_id');
  const enIdx = header.indexOf('tcm_symptom');
  const cnIdx = header.indexOf('tcm_symptom_cn');
  const catIdx = header.indexOf('tcm_symptom_category');
  const stmt = db.prepare('INSERT OR REPLACE INTO symmap_symptoms VALUES (?, ?, ?, ?)');
  const tx = db.transaction((rs: string[][]) => {
    for (const r of rs) stmt.run(r[idIdx], r[enIdx], r[cnIdx] || null, r[catIdx] || null);
  });
  tx(rows.slice(1));
}

function loadHerbs(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_herbs (
      symmap_id TEXT PRIMARY KEY,
      name_en   TEXT,
      name_cn   TEXT,
      pinyin    TEXT,
      latin     TEXT
    );
  `);
  const rows = parseTsv('data/symmap/SMHB.txt');
  const header = rows[0].map((h) => h.toLowerCase());
  const idIdx = header.indexOf('symmap_id');
  const enIdx = header.indexOf('english_name');
  const cnIdx = header.indexOf('chinese_name');
  const pyIdx = header.indexOf('pinyin_name');
  const laIdx = header.indexOf('latin_name');
  const stmt = db.prepare('INSERT OR REPLACE INTO symmap_herbs VALUES (?, ?, ?, ?, ?)');
  const tx = db.transaction((rs: string[][]) => {
    for (const r of rs) stmt.run(r[idIdx], r[enIdx] || null, r[cnIdx] || null, r[pyIdx] || null, r[laIdx] || null);
  });
  tx(rows.slice(1));
}

function loadHerbSymptoms(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_herb_symptoms (
      herb_id    TEXT NOT NULL,
      symptom_id TEXT NOT NULL,
      PRIMARY KEY (herb_id, symptom_id),
      FOREIGN KEY (herb_id)    REFERENCES symmap_herbs(symmap_id),
      FOREIGN KEY (symptom_id) REFERENCES symmap_symptoms(symmap_id)
    );
  `);
  // SymMap joins via SMTT (TCM syndrome) as an intermediate; SMTT_SMHB links herbs→syndromes.
  // For v1 ingest, use direct herb→symptom links from SMHB where present.
  const rows = parseTsv('data/symmap/SMTT_SMHB.txt');
  const header = rows[0].map((h) => h.toLowerCase());
  const herbIdx = header.indexOf('smhb_id');
  const symIdx = header.indexOf('smit_id');
  if (herbIdx < 0 || symIdx < 0) throw new Error('SMTT_SMHB schema unexpected');
  const stmt = db.prepare('INSERT OR IGNORE INTO symmap_herb_symptoms VALUES (?, ?)');
  const tx = db.transaction((rs: string[][]) => {
    for (const r of rs) stmt.run(r[herbIdx], r[symIdx]);
  });
  tx(rows.slice(1));
}

function main() {
  const db = new Database(DB);
  db.pragma('foreign_keys = ON');
  loadSymptoms(db);
  loadHerbs(db);
  loadHerbSymptoms(db);
  db.close();
  console.log('SymMap loaded');
}
main();
```

Add Makefile target:
```makefile
load-symmap:
	npx tsx scripts/load-symmap.ts
```

- [ ] **Step 4: Run + re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity && make load-symmap && npx vitest run src/__tests__/symmap-load.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/scripts/load-symmap.ts shrine-diet-bioactivity/src/__tests__/symmap-load.test.ts shrine-diet-bioactivity/Makefile
git commit -m "feat(symmap): load SymMap v2 symptoms + herbs into SQLite"
```

**Note:** SymMap column names may shift across v2 revisions. If the loader test fails at the schema-parse step, inspect `data/symmap/SMIT.txt` header and update the column-name lookups. Do not hardcode column indices.

---

## Task 4 — Build symptom crosswalk (Duke ↔ SymMap)

**Purpose:** Duke's 47 bioactivity-derived symptoms must map into SymMap's 5.2K TCM symptoms so agents see a unified symptom vocabulary.

**Files:**
- Create: `research-journal/shared/symptom_crosswalk.json`
- Create: `shrine-diet-bioactivity/scripts/build-symptom-crosswalk.ts` (LLM-assisted scaffolder)
- Create: `shrine-diet-bioactivity/src/__tests__/symptom-crosswalk.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// shrine-diet-bioactivity/src/__tests__/symptom-crosswalk.test.ts
import Database from 'better-sqlite3';
import { readFileSync, existsSync } from 'fs';
import { describe, it, expect } from 'vitest';

const CROSSWALK = '../research-journal/shared/symptom_crosswalk.json';

describe('symptom crosswalk', () => {
  it('exists', () => {
    expect(existsSync(CROSSWALK)).toBe(true);
  });

  it('covers all 47 Duke symptoms (matched or explicitly unmatched)', () => {
    const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });
    const dukeIds = db.prepare('SELECT id FROM symptoms').all().map((r: { id: number }) => r.id);
    db.close();
    const crosswalk = JSON.parse(readFileSync(CROSSWALK, 'utf8')) as Array<{ duke_id: number; symmap_id: string | null; confidence: 'high' | 'medium' | 'low' | 'unmatched' }>;
    const covered = new Set(crosswalk.map((e) => e.duke_id));
    for (const id of dukeIds) expect(covered.has(id)).toBe(true);
  });

  it('every matched entry references a valid symmap_id', () => {
    const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });
    const symmapIds = new Set(db.prepare('SELECT symmap_id FROM symmap_symptoms').all().map((r: { symmap_id: string }) => r.symmap_id));
    db.close();
    const crosswalk = JSON.parse(readFileSync(CROSSWALK, 'utf8'));
    for (const entry of crosswalk) {
      if (entry.symmap_id !== null) expect(symmapIds.has(entry.symmap_id)).toBe(true);
    }
  });
});
```

- [ ] **Step 2: Run test — expect FAIL (file missing)**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/symptom-crosswalk.test.ts
```

- [ ] **Step 3: Scaffold the crosswalk with an LLM-assisted draft + manual review**

Run the scaffolder script that pairs each Duke symptom with the top-3 SymMap candidates (by embedding similarity) and emits a draft JSON. A human reviewer then confirms/overrides.

```typescript
// shrine-diet-bioactivity/scripts/build-symptom-crosswalk.ts
import Database from 'better-sqlite3';
import { writeFileSync } from 'fs';

const DB = './data_local/herbal_botanicals.db';
const OUT = '../research-journal/shared/symptom_crosswalk.json';

type Entry = { duke_id: number; duke_name: string; symmap_id: string | null; symmap_name: string | null; confidence: 'high' | 'medium' | 'low' | 'unmatched'; note: string };

function main() {
  const db = new Database(DB, { readonly: true });
  const duke = db.prepare('SELECT id, name FROM symptoms ORDER BY id').all() as Array<{ id: number; name: string }>;
  const symmap = db.prepare('SELECT symmap_id, name_en FROM symmap_symptoms').all() as Array<{ symmap_id: string; name_en: string }>;
  db.close();

  // v1: simple case-insensitive exact/substring match; reviewer upgrades to semantic match.
  const byName = new Map<string, { symmap_id: string; name_en: string }>();
  for (const s of symmap) byName.set(s.name_en.toLowerCase(), s);

  const draft: Entry[] = duke.map((d) => {
    const exact = byName.get(d.name.toLowerCase());
    if (exact) return { duke_id: d.id, duke_name: d.name, symmap_id: exact.symmap_id, symmap_name: exact.name_en, confidence: 'high', note: 'exact name match' };
    const substr = symmap.find((s) => s.name_en.toLowerCase().includes(d.name.toLowerCase()));
    if (substr) return { duke_id: d.id, duke_name: d.name, symmap_id: substr.symmap_id, symmap_name: substr.name_en, confidence: 'medium', note: 'substring match — REVIEW' };
    return { duke_id: d.id, duke_name: d.name, symmap_id: null, symmap_name: null, confidence: 'unmatched', note: 'no match — REVIEW' };
  });

  writeFileSync(OUT, JSON.stringify(draft, null, 2));
  console.log(`wrote ${draft.length} entries; ${draft.filter((e) => e.confidence === 'high').length} exact`);
}
main();
```

Run, then manually upgrade medium/unmatched entries to `high` or `low` with reviewer sign-off in the `note` field. Commit the reviewed file.

- [ ] **Step 4: Re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity && npx tsx scripts/build-symptom-crosswalk.ts
# ...manual review step...
cd shrine-diet-bioactivity && npx vitest run src/__tests__/symptom-crosswalk.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add research-journal/shared/symptom_crosswalk.json shrine-diet-bioactivity/scripts/build-symptom-crosswalk.ts shrine-diet-bioactivity/src/__tests__/symptom-crosswalk.test.ts
git commit -m "data(symmap): Duke↔SymMap symptom crosswalk with reviewer notes"
```

---

## Task 5 — Download + load HERB 2.0 (evidence tiers + bilingual herbs)

**Purpose:** Supplies evidence-tier labels (clinical/experimental/traditional) for Stage 4 calibrator and bilingual CN/EN herb names for Stage 3 TCM agent.

**Files:**
- Create: `shrine-diet-bioactivity/scripts/download-herb2.ts`
- Create: `shrine-diet-bioactivity/scripts/load-herb2.ts`
- Create: `shrine-diet-bioactivity/src/__tests__/herb2-load.test.ts`
- Modify: `shrine-diet-bioactivity/Makefile`

- [ ] **Step 1: Write failing test**

```typescript
// shrine-diet-bioactivity/src/__tests__/herb2-load.test.ts
import Database from 'better-sqlite3';
import { describe, it, expect } from 'vitest';

describe('HERB 2.0 SQLite load', () => {
  const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });

  it('herb2_herbs has >= 1200 herbs with CN+EN names', () => {
    const r = db.prepare('SELECT COUNT(*) AS c FROM herb2_herbs WHERE name_cn IS NOT NULL').get() as { c: number };
    expect(r.c).toBeGreaterThanOrEqual(1200);
  });

  it('herb2_herb_disease has evidence_tier in {clinical, experimental, traditional}', () => {
    const r = db.prepare(`SELECT DISTINCT evidence_tier FROM herb2_herb_disease`).all() as Array<{ evidence_tier: string }>;
    const tiers = new Set(r.map((x) => x.evidence_tier));
    expect(tiers.size).toBeGreaterThan(0);
    for (const t of tiers) expect(['clinical', 'experimental', 'traditional']).toContain(t);
  });
});
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/herb2-load.test.ts
```

- [ ] **Step 3: Write downloader + loader**

HERB 2.0 download URL: `http://herb.ac.cn/static/download/`. TSV files: `herb_info.txt`, `herb_experiment.txt`, `herb_clinical.txt`. Save under `data/herb2/`.

```typescript
// shrine-diet-bioactivity/scripts/download-herb2.ts
import { mkdirSync, createWriteStream } from 'fs';
import { get } from 'http';

const BASE = 'http://herb.ac.cn/static/download/';
const FILES = ['herb_info.txt', 'herb_experiment.txt', 'herb_clinical.txt'];
const OUT_DIR = 'data/herb2';

async function download(url: string, dest: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = createWriteStream(dest);
    get(url, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        return;
      }
      res.pipe(file);
      file.on('finish', () => file.close(() => resolve()));
    }).on('error', reject);
  });
}

async function main(): Promise<void> {
  mkdirSync(OUT_DIR, { recursive: true });
  for (const f of FILES) {
    const url = BASE + f;
    const dest = `${OUT_DIR}/${f}`;
    console.log(`fetching ${url}`);
    await download(url, dest);
  }
  console.log('done');
}

main().catch((e) => { console.error(e); process.exit(1); });
```

```typescript
// shrine-diet-bioactivity/scripts/load-herb2.ts
import Database from 'better-sqlite3';
import { readFileSync } from 'fs';

const DB = './data_local/herbal_botanicals.db';

function parseTsv(path: string): string[][] {
  return readFileSync(path, 'utf8').split('\n').filter(Boolean).map((l) => l.split('\t'));
}

function loadHerbs(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS herb2_herbs (
      herb_id    TEXT PRIMARY KEY,
      name_en    TEXT,
      name_cn    TEXT,
      pinyin     TEXT,
      latin      TEXT
    );
  `);
  const rows = parseTsv('data/herb2/herb_info.txt');
  const header = rows[0].map((h) => h.toLowerCase());
  const stmt = db.prepare('INSERT OR REPLACE INTO herb2_herbs VALUES (?, ?, ?, ?, ?)');
  const tx = db.transaction((rs: string[][]) => {
    const idx = {
      id: header.indexOf('herb_id'),
      en: header.indexOf('herb_en_name'),
      cn: header.indexOf('herb_cn_name'),
      py: header.indexOf('herb_pinyin_name'),
      la: header.indexOf('herb_latin_name'),
    };
    for (const r of rs) stmt.run(r[idx.id], r[idx.en] || null, r[idx.cn] || null, r[idx.py] || null, r[idx.la] || null);
  });
  tx(rows.slice(1));
}

function loadHerbDisease(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS herb2_herb_disease (
      herb_id        TEXT NOT NULL,
      disease_label  TEXT NOT NULL,
      evidence_tier  TEXT NOT NULL CHECK (evidence_tier IN ('clinical','experimental','traditional')),
      source_pmid    TEXT,
      PRIMARY KEY (herb_id, disease_label, evidence_tier)
    );
  `);
  const tiers: [string, string][] = [
    ['data/herb2/herb_clinical.txt', 'clinical'],
    ['data/herb2/herb_experiment.txt', 'experimental'],
  ];
  const stmt = db.prepare('INSERT OR IGNORE INTO herb2_herb_disease VALUES (?, ?, ?, ?)');
  for (const [path, tier] of tiers) {
    const rows = parseTsv(path);
    const header = rows[0].map((h) => h.toLowerCase());
    const hIdx = header.indexOf('herb_id');
    const dIdx = header.indexOf('disease_name');
    const pIdx = header.indexOf('pmid');
    const tx = db.transaction((rs: string[][]) => {
      for (const r of rs) stmt.run(r[hIdx], r[dIdx], tier, r[pIdx] || null);
    });
    tx(rows.slice(1));
  }
}

function main() {
  const db = new Database(DB);
  loadHerbs(db);
  loadHerbDisease(db);
  db.close();
  console.log('HERB 2.0 loaded');
}
main();
```

Makefile:
```makefile
download-herb2:
	npx tsx scripts/download-herb2.ts

load-herb2:
	npx tsx scripts/load-herb2.ts
```

- [ ] **Step 4: Run + re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity && make download-herb2 && make load-herb2 && npx vitest run src/__tests__/herb2-load.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/scripts/download-herb2.ts shrine-diet-bioactivity/scripts/load-herb2.ts shrine-diet-bioactivity/src/__tests__/herb2-load.test.ts shrine-diet-bioactivity/Makefile
git commit -m "feat(herb2): load HERB 2.0 with evidence tiers + bilingual herb names"
```

---

## Task 6 — Curate HDI-Safe 50

**Purpose:** Reference set of 50 well-documented herb-drug interactions for Safety Reviewer + C3 calibration PoC.

**Files:**
- Create: `research-journal/shared/hdi_safe_50.json`
- Create: `shrine-diet-bioactivity/src/__tests__/hdi-safe-50.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// shrine-diet-bioactivity/src/__tests__/hdi-safe-50.test.ts
import { readFileSync, existsSync } from 'fs';
import { describe, it, expect } from 'vitest';

const FILE = '../research-journal/shared/hdi_safe_50.json';

type HDI = {
  id: string;
  herb: { name: string; latin: string; symmap_id?: string };
  drug: { name: string; rxnorm?: string; atc?: string };
  severity: 'severe' | 'moderate' | 'mild';
  mechanism_class: 'CYP450' | 'P-gp' | 'PD-antagonism' | 'coagulation' | 'serotonergic';
  evidence_tier: 'clinical_trial' | 'pharmacokinetic_study' | 'case_report_series' | 'case_report' | 'in_vitro';
  sources: { name: string; url: string }[];
  notes: string;
};

describe('HDI-Safe 50', () => {
  it('exists and contains 50 entries', () => {
    expect(existsSync(FILE)).toBe(true);
    const data = JSON.parse(readFileSync(FILE, 'utf8')) as HDI[];
    expect(data).toHaveLength(50);
  });

  it('covers 5 mechanism classes with ≥ 5 entries each', () => {
    const data = JSON.parse(readFileSync(FILE, 'utf8')) as HDI[];
    const byMech = new Map<string, number>();
    for (const d of data) byMech.set(d.mechanism_class, (byMech.get(d.mechanism_class) ?? 0) + 1);
    for (const cls of ['CYP450', 'P-gp', 'PD-antagonism', 'coagulation', 'serotonergic']) {
      expect(byMech.get(cls) ?? 0).toBeGreaterThanOrEqual(5);
    }
  });

  it('every entry cites at least one of NIH ODS / MSK / LiverTox', () => {
    const data = JSON.parse(readFileSync(FILE, 'utf8')) as HDI[];
    for (const d of data) {
      const sourceNames = d.sources.map((s) => s.name.toLowerCase());
      const hasAllowed = sourceNames.some((n) => n.includes('nih ods') || n.includes('memorial sloan') || n.includes('msk') || n.includes('livertox'));
      expect(hasAllowed).toBe(true);
    }
  });
});
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/hdi-safe-50.test.ts
```

- [ ] **Step 3: Curate `research-journal/shared/hdi_safe_50.json`**

Hand-curate 50 entries using the schema above. Example (first entry):

```json
[
  {
    "id": "HDI-001",
    "herb":  { "name": "St. John's Wort", "latin": "Hypericum perforatum" },
    "drug":  { "name": "Sertraline", "atc": "N06AB06" },
    "severity": "severe",
    "mechanism_class": "serotonergic",
    "evidence_tier": "clinical_trial",
    "sources": [
      { "name": "NIH ODS Fact Sheet — St. John's Wort", "url": "https://ods.od.nih.gov/factsheets/StJohnsWort-HealthProfessional/" },
      { "name": "MSK About Herbs — St. John's Wort", "url": "https://www.mskcc.org/cancer-care/integrative-medicine/herbs/st-johns-wort" }
    ],
    "notes": "Serotonin syndrome risk from additive serotonergic effect + CYP3A4/SSRI pharmacokinetics."
  }
]
```

Distribution target: CYP450 (15 entries: SJW×SSRI/OCP/warfarin; grapefruit×statins/CCBs; etc.); P-gp (6 entries); PD-antagonism (8 entries: licorice×ACEi; ginseng×warfarin); coagulation (10 entries: ginkgo/garlic/ginger×antiplatelets); serotonergic (11 entries: SJW×MAOIs/SSRIs/triptans).

Use MSK About Herbs (https://www.mskcc.org/cancer-care/integrative-medicine/herbs), NIH ODS (https://ods.od.nih.gov/factsheets/list-all/), and LiverTox (https://www.ncbi.nlm.nih.gov/books/NBK547852/) as primary sources — all three are citable, open, and evidence-graded.

- [ ] **Step 4: Re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity && npx vitest run src/__tests__/hdi-safe-50.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add research-journal/shared/hdi_safe_50.json shrine-diet-bioactivity/src/__tests__/hdi-safe-50.test.ts
git commit -m "data(hdi): curate HDI-Safe 50 reference set (5 mechanism classes)"
```

---

## Task 7 — Add `INTERACTS_WITH` + `CONTRAINDICATES` edge types to entity_schema

**Purpose:** Wire the new relationship types into LightRAG's schema so `ainsert_custom_kg` can ingest HDI edges.

**Files:**
- Modify: `shrine-diet-bioactivity/lightrag/entity_schema.py`
- Create: `shrine-diet-bioactivity/lightrag/test_entity_schema_hdi.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/lightrag/test_entity_schema_hdi.py
import pytest
from entity_schema import RELATIONSHIP_TYPES, describe_interacts_with, describe_contraindicates


def test_interacts_with_registered():
    assert "INTERACTS_WITH" in RELATIONSHIP_TYPES
    spec = RELATIONSHIP_TYPES["INTERACTS_WITH"]
    assert spec["source_table"] is None  # curated JSON, not SQLite
    assert spec["src_type"] == "Herb"
    assert spec["tgt_type"] == "Drug"


def test_contraindicates_registered():
    assert "CONTRAINDICATES" in RELATIONSHIP_TYPES
    assert RELATIONSHIP_TYPES["CONTRAINDICATES"]["source_table"] is None


def test_describe_interacts_with():
    d = describe_interacts_with({
        "herb_name": "St. John's Wort",
        "drug_name": "Sertraline",
        "severity": "severe",
        "mechanism_class": "serotonergic",
        "evidence_tier": "clinical_trial",
    })
    assert "St. John's Wort" in d
    assert "Sertraline" in d
    assert "severe" in d
    assert "serotonergic" in d
```

- [ ] **Step 2: Run test — expect FAIL (symbols not defined)**

```bash
cd shrine-diet-bioactivity/lightrag && pytest test_entity_schema_hdi.py -v
```

- [ ] **Step 3: Extend `entity_schema.py`**

Add to `RELATIONSHIP_TYPES` dict:

```python
# shrine-diet-bioactivity/lightrag/entity_schema.py — append to RELATIONSHIP_TYPES
    "INTERACTS_WITH": {
        "source_table": None,  # curated via hdi_safe_50.json, ingested by ingest-hdi.py
        "src_type": "Herb",
        "tgt_type": "Drug",
        "description": "Herb-drug interaction (HDI) from NIH ODS / MSK About Herbs / LiverTox",
    },
    "CONTRAINDICATES": {
        "source_table": None,
        "src_type": "Herb",
        "tgt_type": "Condition",
        "description": "Contraindication (pregnancy, hepatic, renal, pediatric, etc.)",
    },
```

Add description generators (near other `describe_*` functions):

```python
# shrine-diet-bioactivity/lightrag/entity_schema.py — append
def describe_interacts_with(row: dict) -> str:
    return (
        f"{row['herb_name']} interacts with {row['drug_name']} "
        f"({row['severity']} severity; mechanism class: {row['mechanism_class']}; "
        f"evidence: {row['evidence_tier']})"
    )


def describe_contraindicates(row: dict) -> str:
    return (
        f"{row['herb_name']} is contraindicated in {row['condition']} "
        f"({row.get('severity', 'unspecified')})"
    )
```

- [ ] **Step 4: Re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity/lightrag && pytest test_entity_schema_hdi.py -v
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/lightrag/entity_schema.py shrine-diet-bioactivity/lightrag/test_entity_schema_hdi.py
git commit -m "feat(schema): add INTERACTS_WITH + CONTRAINDICATES relationship types"
```

---

## Task 8 — Ingest HDI-Safe 50 via `ainsert_custom_kg`

**Purpose:** Land the 50 HDI edges in the LightRAG/Neo4j Aura KG so the Safety Reviewer can query them.

**Files:**
- Create: `shrine-diet-bioactivity/lightrag/ingest_hdi.py`
- Create: `shrine-diet-bioactivity/lightrag/test_ingest_hdi.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/lightrag/test_ingest_hdi.py
import json
import os
import pytest
from neo4j import GraphDatabase


@pytest.mark.integration
def test_hdi_edges_land_in_aura(tmp_path):
    # Run the ingest module as a subprocess would in production,
    # but import it here and call main() for test coverage.
    from ingest_hdi import main as ingest_main
    ingest_main(dry_run=False)

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            n = s.run("MATCH ()-[r:INTERACTS_WITH]->() RETURN count(r) AS c").single()["c"]
            assert n >= 50
            sample = s.run("""
                MATCH (h:Herb)-[r:INTERACTS_WITH]->(d:Drug)
                RETURN h.entity_id AS herb, d.entity_id AS drug, r.severity AS sev LIMIT 5
            """).data()
            assert all({"herb", "drug", "sev"}.issubset(row.keys()) for row in sample)
```

- [ ] **Step 2: Run test — expect FAIL (module missing)**

```bash
cd shrine-diet-bioactivity/lightrag && infisical run -- pytest test_ingest_hdi.py -m integration -v
```

- [ ] **Step 3: Write `ingest_hdi.py`**

```python
# shrine-diet-bioactivity/lightrag/ingest_hdi.py
"""Ingest HDI-Safe 50 and any contraindications into LightRAG via ainsert_custom_kg."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from lightrag import LightRAG
from lightrag.llm import openai_embedding

from entity_schema import describe_contraindicates, describe_interacts_with

HDI_JSON = Path(__file__).resolve().parents[2] / "research-journal" / "shared" / "hdi_safe_50.json"


def build_payload(hdis: list[dict]) -> dict:
    herbs: dict[str, dict] = {}
    drugs: dict[str, dict] = {}
    relationships: list[dict] = []
    for entry in hdis:
        herb_id = f"Herb:{entry['herb']['latin']}"
        drug_id = f"Drug:{entry['drug']['name']}"
        herbs[herb_id] = {
            "entity_name": herb_id,
            "entity_type": "Herb",
            "description": f"{entry['herb']['name']} ({entry['herb']['latin']})",
            "source_id": f"hdi-safe-50:{entry['id']}",
        }
        drugs[drug_id] = {
            "entity_name": drug_id,
            "entity_type": "Drug",
            "description": f"Drug {entry['drug']['name']}"
                           + (f" (ATC {entry['drug']['atc']})" if entry['drug'].get('atc') else ""),
            "source_id": f"hdi-safe-50:{entry['id']}",
        }
        relationships.append({
            "src_id": herb_id,
            "tgt_id": drug_id,
            "description": describe_interacts_with({
                "herb_name": entry['herb']['name'],
                "drug_name": entry['drug']['name'],
                "severity": entry['severity'],
                "mechanism_class": entry['mechanism_class'],
                "evidence_tier": entry['evidence_tier'],
            }),
            "keywords": f"HDI {entry['mechanism_class']} {entry['severity']}",
            "weight": {"severe": 1.0, "moderate": 0.6, "mild": 0.3}[entry['severity']],
            "source_id": f"hdi-safe-50:{entry['id']}",
            # custom properties — LightRAG passes through via upsert_node/edge
            "severity": entry['severity'],
            "mechanism_class": entry['mechanism_class'],
            "evidence_tier": entry['evidence_tier'],
            "scope": "shared",
        })
    return {
        "entities": list(herbs.values()) + list(drugs.values()),
        "relationships": relationships,
        "chunks": [],
    }


async def _ingest_async(payload: dict) -> None:
    rag = LightRAG(
        working_dir=os.environ.get("WORKING_DIR", "./rag_storage_local"),
        embedding_func=openai_embedding,
        llm_model_func=None,  # custom_kg path bypasses extraction LLM
    )
    await rag.ainsert_custom_kg(payload)


def main(dry_run: bool = False) -> None:
    load_dotenv()
    with HDI_JSON.open() as f:
        hdis = json.load(f)
    payload = build_payload(hdis)
    if dry_run:
        print(f"would ingest {len(payload['entities'])} entities, {len(payload['relationships'])} relationships")
        return
    asyncio.run(_ingest_async(payload))
    print(f"ingested {len(payload['relationships'])} HDI edges")


if __name__ == "__main__":
    import sys
    main(dry_run="--dry-run" in sys.argv)
```

- [ ] **Step 4: Re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity/lightrag && infisical run -- pytest test_ingest_hdi.py -m integration -v
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/lightrag/ingest_hdi.py shrine-diet-bioactivity/lightrag/test_ingest_hdi.py
git commit -m "feat(hdi): ingest HDI-Safe 50 into LightRAG via ainsert_custom_kg"
```

---

## Task 9 — Un-pin subsample + full-scale re-ingest

**Purpose:** Move from the 50K-edge prototype to full-breadth ingestion of the expanded dataset (Duke + FooDB + CMAUP + CTD + TTD + OpenNutrition + SymMap + HERB 2.0 + HDI).

**Files:**
- Modify: `shrine-diet-bioactivity/Makefile` (change `MAX_RELATIONSHIPS ?= 50000` to `?= 0` meaning unlimited)
- Modify: `shrine-diet-bioactivity/lightrag/ingest_unified.py` (wire SymMap + HERB 2.0 description generators)
- Create: `shrine-diet-bioactivity/lightrag/test_ingest_unpinned.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/lightrag/test_ingest_unpinned.py
import os
import pytest
from neo4j import GraphDatabase


@pytest.mark.integration
def test_fullscale_ingest_counts():
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            symmap_herbs = s.run(
                "MATCH (h:Herb) WHERE h.source_id STARTS WITH 'symmap:' RETURN count(h) AS c"
            ).single()["c"]
            herb2_edges = s.run(
                "MATCH ()-[r]->() WHERE r.source_id STARTS WITH 'herb2:' RETURN count(r) AS c"
            ).single()["c"]
    assert nodes > 100_000, f"expected full-scale KG, got {nodes} nodes"
    assert edges > 500_000, f"expected full-scale KG, got {edges} edges"
    assert symmap_herbs > 1_000, f"SymMap herbs missing: {symmap_herbs}"
    assert herb2_edges > 500, f"HERB 2.0 edges missing: {herb2_edges}"
```

- [ ] **Step 2: Run test — expect FAIL (still on pinned subsample)**

```bash
cd shrine-diet-bioactivity/lightrag && infisical run -- pytest test_ingest_unpinned.py -m integration -v
```

- [ ] **Step 3: Un-pin Makefile + extend `ingest_unified.py`**

```makefile
# Makefile — change default
MAX_RELATIONSHIPS ?= 0    # 0 = unlimited (full-scale); override via env for prototype reruns
```

In `ingest_unified.py`, register description generators for `symmap_herbs`, `symmap_symptoms`, `symmap_herb_symptoms`, `herb2_herbs`, `herb2_herb_disease` — following the pattern of existing `describe_herb`, `describe_compound` etc. (see Task 5 for schema; edit `ingest_unified.py` to import and wire them into the per-table extraction loop — exact structure matches existing entity-type iteration).

- [ ] **Step 4: Run full-scale ingest + re-run test — expect PASS**

Full re-ingest may take 1–3 hours depending on embedding model. Use Aura + OpenAI production config:

```bash
cd shrine-diet-bioactivity && infisical run -- make lightrag-ingest-local CONFIG=config_production.env
cd shrine-diet-bioactivity/lightrag && infisical run -- pytest test_ingest_unpinned.py -m integration -v
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/Makefile shrine-diet-bioactivity/lightrag/ingest_unified.py shrine-diet-bioactivity/lightrag/test_ingest_unpinned.py
git commit -m "chore(kg): un-pin subsample + full-scale re-ingest with SymMap + HERB 2.0 + HDI"
```

---

## Task 10 — Ingestion snapshot report

**Purpose:** Produce a reproducible post-ingest snapshot (node/edge counts per type, source distribution, bilingual coverage stats) that the primary paper's Methods section can cite.

**Files:**
- Create: `shrine-diet-bioactivity/lightrag/generate_snapshot.py`
- Create: `research-journal/shared/ingestion-snapshot.md` (generated)
- Create: `shrine-diet-bioactivity/lightrag/test_generate_snapshot.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/lightrag/test_generate_snapshot.py
from pathlib import Path

import pytest


@pytest.mark.integration
def test_snapshot_has_required_sections(tmp_path):
    from generate_snapshot import generate
    out = tmp_path / "snapshot.md"
    generate(out)
    text = out.read_text()
    for section in [
        "# KG Ingestion Snapshot",
        "## Node counts by type",
        "## Edge counts by type",
        "## Source distribution",
        "## Bilingual coverage",
        "## HDI-Safe 50 coverage",
    ]:
        assert section in text, f"missing section: {section}"
```

- [ ] **Step 2: Run test — expect FAIL (module missing)**

```bash
cd shrine-diet-bioactivity/lightrag && pytest test_generate_snapshot.py -m integration -v
```

- [ ] **Step 3: Write `generate_snapshot.py`**

```python
# shrine-diet-bioactivity/lightrag/generate_snapshot.py
"""Generate a post-ingest KG metrics report for the paper's Methods section."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase


def _query_counts(session, cypher: str) -> list[dict]:
    return [dict(r) for r in session.run(cypher)]


def generate(out_path: Path) -> None:
    load_dotenv()
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session() as s:
            node_counts = _query_counts(s, "MATCH (n) RETURN labels(n)[0] AS type, count(n) AS n ORDER BY n DESC")
            edge_counts = _query_counts(s, "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS n ORDER BY n DESC")
            sources    = _query_counts(s, """
                MATCH (n) WHERE n.source_id IS NOT NULL
                WITH split(n.source_id, ':')[0] AS src, count(n) AS n
                RETURN src, n ORDER BY n DESC
            """)
            bilingual  = _query_counts(s, """
                MATCH (h:Herb)
                RETURN
                  count(h) AS total,
                  sum(CASE WHEN h.name_cn IS NOT NULL THEN 1 ELSE 0 END) AS with_cn,
                  sum(CASE WHEN h.name_en IS NOT NULL THEN 1 ELSE 0 END) AS with_en
            """)
            hdi_cov    = _query_counts(s, """
                MATCH ()-[r:INTERACTS_WITH]->()
                RETURN r.mechanism_class AS mech, count(r) AS n ORDER BY mech
            """)
    lines = [
        "# KG Ingestion Snapshot",
        f"_Generated {datetime.utcnow().isoformat()}Z_",
        "",
        "## Node counts by type",
        "| Type | Count |",
        "|---|---|",
        *[f"| {r['type']} | {r['n']:,} |" for r in node_counts],
        "",
        "## Edge counts by type",
        "| Type | Count |",
        "|---|---|",
        *[f"| {r['type']} | {r['n']:,} |" for r in edge_counts],
        "",
        "## Source distribution",
        "| Source | Node count |",
        "|---|---|",
        *[f"| {r['src']} | {r['n']:,} |" for r in sources],
        "",
        "## Bilingual coverage",
        f"| Total Herbs | With CN | With EN |",
        f"|---|---|---|",
        f"| {bilingual[0]['total']:,} | {bilingual[0]['with_cn']:,} | {bilingual[0]['with_en']:,} |",
        "",
        "## HDI-Safe 50 coverage",
        "| Mechanism class | Edges |",
        "|---|---|",
        *[f"| {r['mech']} | {r['n']} |" for r in hdi_cov],
        "",
    ]
    out_path.write_text("\n".join(lines))


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[2] / "research-journal" / "shared" / "ingestion-snapshot.md"
    generate(out)
    print(f"wrote {out}")
```

- [ ] **Step 4: Run + re-run test — expect PASS**

```bash
cd shrine-diet-bioactivity/lightrag && infisical run -- python generate_snapshot.py
cd shrine-diet-bioactivity/lightrag && pytest test_generate_snapshot.py -m integration -v
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/lightrag/generate_snapshot.py shrine-diet-bioactivity/lightrag/test_generate_snapshot.py research-journal/shared/ingestion-snapshot.md
git commit -m "docs(kg): generate post-ingest snapshot report for paper Methods"
```

---

## Completion checklist (Subsystem A done when all of these are green)

- [ ] Aura reachable, test_aura_connectivity passes
- [ ] `food_nutrition_bridge` populated (≥ 900 rows)
- [ ] SymMap TSVs downloaded + loaded (≥ 5000 symptoms, ≥ 1000 bilingual herbs)
- [ ] Duke↔SymMap symptom crosswalk complete and covers all 47 Duke symptoms
- [ ] HERB 2.0 loaded (≥ 1200 herbs with CN names, evidence tiers distributed across clinical/experimental/traditional)
- [ ] `hdi_safe_50.json` has 50 entries, 5 mechanism classes, all cite NIH ODS / MSK / LiverTox
- [ ] `INTERACTS_WITH` + `CONTRAINDICATES` edge types registered in entity_schema
- [ ] 50 HDI edges live in Aura
- [ ] Subsample un-pinned, full-scale re-ingest complete (> 500K edges)
- [ ] Snapshot report generated + committed to `research-journal/shared/ingestion-snapshot.md`
- [ ] All unit + integration tests pass; `pytest --cov=lightrag --cov-report=term-missing` shows ≥ 80% coverage on new modules

After completion, write Subsystem B's plan (Clinical Intake Agent) — by then the unified KG shape is stable and intake agent prompts can reference real entity types.
