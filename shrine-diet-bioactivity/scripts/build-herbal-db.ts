/**
 * Build herbal_botanicals.db from Dr. Duke's and FooDB CSV files.
 *
 * Reads extracted CSVs from data_local_temp/, normalizes compound names,
 * joins herb→compound→food, and outputs data_local/herbal_botanicals.db.
 *
 * Usage:
 *   tsx scripts/build-herbal-db.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import * as readline from 'readline';
import Database from 'better-sqlite3';
import Papa from 'papaparse';

const DUKE_DIR = path.join(process.cwd(), 'data_local_temp', 'duke');
const FOODB_DIR = path.join(process.cwd(), 'data_local_temp', 'foodb');
const OUTPUT_DIR = path.join(process.cwd(), 'data_local');
const DB_PATH = path.join(OUTPUT_DIR, 'herbal_botanicals.db');

// ---------------------------------------------------------------------------
// Compound name normalization
// ---------------------------------------------------------------------------

export function normalizeCompoundName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]/g, '');
}

export function compoundSlug(name: string): string {
  return normalizeCompoundName(name);
}

// ---------------------------------------------------------------------------
// CSV parsing helpers
// ---------------------------------------------------------------------------

function readCsvFile(filePath: string, encoding: BufferEncoding = 'latin1'): Record<string, string>[] {
  const raw = fs.readFileSync(filePath, encoding);
  const result = Papa.parse<Record<string, string>>(raw, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (h: string) => h.trim(),
  });
  if (result.errors.length > 0) {
    const criticalErrors = result.errors.filter((e) => e.type !== 'FieldMismatch');
    if (criticalErrors.length > 0) {
      console.error(`  CSV parse warnings for ${path.basename(filePath)}:`, criticalErrors.slice(0, 5));
    }
  }
  return result.data;
}

function parsePpm(value: string | undefined): number | null {
  if (!value || value.trim() === '') return null;
  const num = parseFloat(value);
  return isNaN(num) ? null : num;
}

// ---------------------------------------------------------------------------
// Schema creation
// ---------------------------------------------------------------------------

function createSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS herbs (
      id TEXT PRIMARY KEY,
      scientific_name TEXT NOT NULL,
      common_name TEXT,
      family TEXT,
      genus TEXT,
      species TEXT,
      usage_type TEXT,
      alternate_names TEXT
    );

    CREATE TABLE IF NOT EXISTS compounds (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      name_normalized TEXT NOT NULL,
      cas_number TEXT,
      pubchem_cid TEXT,
      compound_class TEXT,
      bioactivities TEXT
    );

    CREATE TABLE IF NOT EXISTS herb_compounds (
      herb_id TEXT NOT NULL REFERENCES herbs(id),
      compound_id TEXT NOT NULL REFERENCES compounds(id),
      plant_part TEXT,
      plant_part_code TEXT,
      concentration_low_ppm REAL,
      concentration_high_ppm REAL,
      compound_class TEXT,
      reference TEXT,
      source TEXT DEFAULT 'duke',
      PRIMARY KEY (herb_id, compound_id, plant_part_code)
    );

    CREATE TABLE IF NOT EXISTS compound_foods (
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

    CREATE TABLE IF NOT EXISTS compound_name_map (
      normalized_name TEXT NOT NULL,
      source TEXT NOT NULL,
      original_name TEXT NOT NULL,
      compound_id TEXT REFERENCES compounds(id),
      PRIMARY KEY (normalized_name, source)
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_herbs_common_name ON herbs(common_name);
    CREATE INDEX IF NOT EXISTS idx_herbs_scientific_name ON herbs(scientific_name);
    CREATE INDEX IF NOT EXISTS idx_compounds_name_normalized ON compounds(name_normalized);
    CREATE INDEX IF NOT EXISTS idx_compounds_name ON compounds(name);
    CREATE INDEX IF NOT EXISTS idx_herb_compounds_herb ON herb_compounds(herb_id);
    CREATE INDEX IF NOT EXISTS idx_herb_compounds_compound ON herb_compounds(compound_id);
    CREATE INDEX IF NOT EXISTS idx_compound_foods_compound ON compound_foods(compound_id);
    CREATE INDEX IF NOT EXISTS idx_compound_foods_food ON compound_foods(food_name);
    CREATE INDEX IF NOT EXISTS idx_compound_name_map_normalized ON compound_name_map(normalized_name);
  `);

  // -------------------------------------------------------------------------
  // Phase 1 drug-bioactive bridge — see ADR 0007
  // -------------------------------------------------------------------------
  // compound_identity holds canonical structural identifiers (InChIKey + cross-refs)
  // resolved via PubChem PUG-REST and UniChem source-mapping files.
  // bioactivity_evidence holds measured drug-target activities from ChEMBL,
  // joined to our compound universe by InChIKey. Both tables use TEXT compound_id
  // to match compounds.id.
  db.exec(`
    CREATE TABLE IF NOT EXISTS compound_identity (
      compound_id          TEXT PRIMARY KEY,
      inchikey             TEXT,
      inchi                TEXT,
      smiles               TEXT,
      pubchem_cid          INTEGER,
      chembl_id            TEXT,
      kegg_compound_id     TEXT,
      drugbank_id          TEXT,
      chebi_id             INTEGER,
      unichem_src_count    INTEGER NOT NULL DEFAULT 0,
      resolution_method    TEXT NOT NULL,
      resolved_at          TEXT NOT NULL,
      FOREIGN KEY (compound_id) REFERENCES compounds(id)
    );
    CREATE INDEX IF NOT EXISTS idx_compound_identity_inchikey ON compound_identity(inchikey);
    CREATE INDEX IF NOT EXISTS idx_compound_identity_chembl ON compound_identity(chembl_id);
    CREATE INDEX IF NOT EXISTS idx_compound_identity_pubchem ON compound_identity(pubchem_cid);

    CREATE TABLE IF NOT EXISTS bioactivity_evidence (
      id                   INTEGER PRIMARY KEY AUTOINCREMENT,
      compound_id          TEXT NOT NULL,
      chembl_compound_id   TEXT NOT NULL,
      chembl_target_id     TEXT NOT NULL,
      target_pref_name     TEXT,
      target_type          TEXT,
      target_organism      TEXT,
      activity_type        TEXT NOT NULL,
      relation             TEXT,
      value                REAL,
      units                TEXT,
      pchembl              REAL,
      activity_comment     TEXT,
      assay_confidence     INTEGER,
      chembl_doc_id        TEXT,
      publication_year     INTEGER,
      ingested_at          TEXT NOT NULL,
      FOREIGN KEY (compound_id) REFERENCES compounds(id)
    );
    CREATE INDEX IF NOT EXISTS idx_bioactivity_compound ON bioactivity_evidence(compound_id);
    CREATE INDEX IF NOT EXISTS idx_bioactivity_target ON bioactivity_evidence(chembl_target_id);
    CREATE INDEX IF NOT EXISTS idx_bioactivity_pchembl ON bioactivity_evidence(pchembl);
  `);
  console.error('  ✓ Phase 1 bridge tables: compound_identity + bioactivity_evidence');

  // Phase 2 — Duke ↔ HERB 2.0 herb resolution (audit §4.3 / Gap 3)
  // -------------------------------------------------------------------------
  // Multi-tier name resolution between Dr. Duke's herbs (2,376 rows) and
  // HERB 2.0 (7,263 rows). Built by scripts/build_herb_resolution_map.py
  // using four match tiers (latin_exact, binomial, common_name, genus).
  // PK is (duke_id, herb2_id, match_type) so a single Duke→HERB2 pair can
  // be recorded under multiple tiers; consumers rank by match_score.
  db.exec(`
    CREATE TABLE IF NOT EXISTS herb_resolution_map (
      duke_id      TEXT NOT NULL,
      herb2_id     TEXT NOT NULL,
      match_type   TEXT NOT NULL,
      match_score  REAL NOT NULL,
      PRIMARY KEY (duke_id, herb2_id, match_type),
      FOREIGN KEY (duke_id)  REFERENCES herbs(id),
      FOREIGN KEY (herb2_id) REFERENCES herb2_herbs(herb_id)
    );
    CREATE INDEX IF NOT EXISTS idx_hrm_duke   ON herb_resolution_map(duke_id);
    CREATE INDEX IF NOT EXISTS idx_hrm_herb2  ON herb_resolution_map(herb2_id);
    CREATE INDEX IF NOT EXISTS idx_hrm_score  ON herb_resolution_map(match_score);
  `);
  console.error('  ✓ herb_resolution_map table');

  // -------------------------------------------------------------------------
  // Phase 3 — disease canonicalization (spec 2026-05-08-disease-canonicalization-design)
  // -------------------------------------------------------------------------
  // Promotes Disease to a first-class unified entity. Three tables:
  //   diseases_canonical    — registry, one row per real-world concept
  //   disease_name_aliases  — free-text alias registry, points at canonical
  //   compound_disease_evidence — replaces chemical_diseases (parallel write
  //                                during the migration cycle)
  // Built by scripts/build_disease_canonical.py and the modified
  // scripts/load-ctd.ts.
  db.exec(`
    CREATE TABLE IF NOT EXISTS diseases_canonical (
      id              TEXT PRIMARY KEY,
      preferred_name  TEXT NOT NULL,
      mesh_id         TEXT,
      umls_id         TEXT,
      icd10cm_id      TEXT,
      hpo_id          TEXT,
      source_origin   TEXT NOT NULL,
      created_at      TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_dc_unique_mesh ON diseases_canonical(mesh_id) WHERE mesh_id IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_dc_unique_umls ON diseases_canonical(umls_id) WHERE umls_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_dc_name ON diseases_canonical(preferred_name);

    CREATE TABLE IF NOT EXISTS disease_name_aliases (
      disease_id  TEXT NOT NULL,
      alias       TEXT NOT NULL,
      source      TEXT NOT NULL,
      PRIMARY KEY (disease_id, alias, source),
      FOREIGN KEY (disease_id) REFERENCES diseases_canonical(id)
    );
    CREATE INDEX IF NOT EXISTS idx_dna_alias_lower ON disease_name_aliases(lower(alias));

    CREATE TABLE IF NOT EXISTS compound_disease_evidence (
      id                     INTEGER PRIMARY KEY AUTOINCREMENT,
      compound_id            TEXT NOT NULL,
      disease_id             TEXT NOT NULL,
      evidence_type          TEXT NOT NULL,
      inference_gene_symbol  TEXT,
      inference_score        REAL,
      pubmed_ids             TEXT,
      source                 TEXT NOT NULL DEFAULT 'ctd',
      ingested_at            TEXT NOT NULL,
      FOREIGN KEY (compound_id) REFERENCES compounds(id),
      FOREIGN KEY (disease_id)  REFERENCES diseases_canonical(id),
      CHECK (
        (evidence_type IN ('direct_therapeutic', 'direct_marker')
           AND inference_gene_symbol IS NULL AND inference_score IS NULL)
        OR
        (evidence_type = 'inferred_via_gene'
           AND inference_score IS NOT NULL
           AND inference_gene_symbol IS NOT NULL)
      )
    );
    CREATE INDEX IF NOT EXISTS idx_cde_compound ON compound_disease_evidence(compound_id);
    CREATE INDEX IF NOT EXISTS idx_cde_disease  ON compound_disease_evidence(disease_id);
    CREATE INDEX IF NOT EXISTS idx_cde_gene     ON compound_disease_evidence(inference_gene_symbol)
      WHERE inference_gene_symbol IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_cde_type     ON compound_disease_evidence(evidence_type);
  `);
  console.error('  ✓ Phase 3: diseases_canonical + disease_name_aliases + compound_disease_evidence');

  // -------------------------------------------------------------------------
  // Phase 4 — KEGG pathway overlay (spec 2026-05-08-kegg-pathway-overlay-design)
  // -------------------------------------------------------------------------
  // Self-contained KEGG layer. PATHWAY_INCLUDES_TARGET joins through
  // targets.gene_symbol (works without Phase 1); COMPOUND_IN_PATHWAY joins
  // through compound_identity.kegg_compound_id (activates lazily once Phase 1
  // ingest runs). License: KEGG is academic-use-only — see ADR 0009.
  db.exec(`
    CREATE TABLE IF NOT EXISTS kegg_pathways (
      id            TEXT PRIMARY KEY,
      name          TEXT NOT NULL,
      organism      TEXT NOT NULL DEFAULT 'hsa',
      category      TEXT,
      source        TEXT NOT NULL DEFAULT 'kegg',
      ingested_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_kp_name ON kegg_pathways(name);

    CREATE TABLE IF NOT EXISTS kegg_compound_pathways (
      kegg_compound_id  TEXT NOT NULL,
      kegg_pathway_id   TEXT NOT NULL,
      ingested_at       TEXT NOT NULL,
      PRIMARY KEY (kegg_compound_id, kegg_pathway_id),
      FOREIGN KEY (kegg_pathway_id) REFERENCES kegg_pathways(id)
    );
    CREATE INDEX IF NOT EXISTS idx_kcp_compound ON kegg_compound_pathways(kegg_compound_id);

    CREATE TABLE IF NOT EXISTS kegg_pathway_genes (
      kegg_pathway_id   TEXT NOT NULL,
      kegg_gene_id      TEXT NOT NULL,
      gene_symbol       TEXT,
      ingested_at       TEXT NOT NULL,
      PRIMARY KEY (kegg_pathway_id, kegg_gene_id),
      FOREIGN KEY (kegg_pathway_id) REFERENCES kegg_pathways(id)
    );
    CREATE INDEX IF NOT EXISTS idx_kpg_gene_symbol ON kegg_pathway_genes(gene_symbol);
  `);
  console.error('  ✓ Phase 4: kegg_pathways + kegg_compound_pathways + kegg_pathway_genes');

  // Phase 2 — symptom→disease materialized map (audit §4.2 / KG audit Gap 2)
  // -------------------------------------------------------------------------
  // Eliminates the implicit string-LIKE bridge between our 47 hand-curated
  // symptoms and target_diseases.disease_name. Joined upstream against
  // SymMap (modern + TCM) so each symptom carries formal MeSH/UMLS/ICD-10
  // IDs into use case A queries. Built by scripts/build_symptom_disease_map.py.
  db.exec(`
    CREATE TABLE IF NOT EXISTS symptom_disease_map (
      symptom_id     TEXT NOT NULL,
      disease_name   TEXT NOT NULL,
      source         TEXT NOT NULL,        -- 'symmap_modern' | 'symmap_tcm' | 'string_match'
      symmap_id      TEXT,
      mesh_id        TEXT,
      umls_id        TEXT,
      icd10cm_id     TEXT,
      match_score    REAL NOT NULL,
      PRIMARY KEY (symptom_id, disease_name, source),
      FOREIGN KEY (symptom_id) REFERENCES symptoms(id)
    );
    CREATE INDEX IF NOT EXISTS idx_sdm_symptom ON symptom_disease_map(symptom_id);
    CREATE INDEX IF NOT EXISTS idx_sdm_mesh    ON symptom_disease_map(mesh_id);
    CREATE INDEX IF NOT EXISTS idx_sdm_score   ON symptom_disease_map(match_score);
  `);
  console.error('  ✓ symptom_disease_map table');
}

// ---------------------------------------------------------------------------
// Duke: Parse FNFTAX → herbs
// ---------------------------------------------------------------------------

function loadHerbs(db: Database.Database): void {
  console.error('  Loading herbs from FNFTAX.csv...');
  const rows = readCsvFile(path.join(DUKE_DIR, 'FNFTAX.csv'));

  const stmt = db.prepare(`
    INSERT OR IGNORE INTO herbs (id, scientific_name, common_name, family, genus, species, usage_type, alternate_names)
    VALUES (?, ?, NULL, ?, ?, ?, ?, '[]')
  `);

  const insertAll = db.transaction((data: Record<string, string>[]) => {
    for (const row of data) {
      const id = row['FNFNUM']?.trim();
      const taxon = row['TAXON']?.trim() || '';
      const family = row['FAMILY']?.trim() || null;
      const genus = row['GENUS']?.trim() || null;
      const species = row['SPECIES']?.trim() || null;
      const usage = row['USEAGE']?.trim() || null;
      if (id) {
        stmt.run(id, taxon, family, genus, species, usage);
      }
    }
  });

  insertAll(rows);
  console.error(`    Loaded ${rows.length} herbs`);
}

// ---------------------------------------------------------------------------
// Duke: Parse COMMON_NAMES → update herbs.common_name, alternate_names
// ---------------------------------------------------------------------------

function loadCommonNames(db: Database.Database): void {
  console.error('  Loading common names from COMMON_NAMES.csv...');
  const rows = readCsvFile(path.join(DUKE_DIR, 'COMMON_NAMES.csv'));

  // Group names by FNFNUM
  const namesByHerb = new Map<string, string[]>();
  for (const row of rows) {
    const id = row['FNFNUM']?.trim();
    const name = row['CNNAM']?.trim();
    if (id && name) {
      const existing = namesByHerb.get(id) || [];
      existing.push(name);
      namesByHerb.set(id, existing);
    }
  }

  const stmt = db.prepare(`
    UPDATE herbs SET common_name = ?, alternate_names = ? WHERE id = ?
  `);

  const updateAll = db.transaction(() => {
    for (const [id, names] of namesByHerb) {
      stmt.run(names[0], JSON.stringify(names), id);
    }
  });

  updateAll();
  console.error(`    Updated ${namesByHerb.size} herbs with common names`);
}

// ---------------------------------------------------------------------------
// Duke: Parse PARTS → in-memory map
// ---------------------------------------------------------------------------

function loadPartsMap(): Map<string, string> {
  console.error('  Loading plant parts from PARTS.csv...');
  const rows = readCsvFile(path.join(DUKE_DIR, 'PARTS.csv'));
  const map = new Map<string, string>();
  for (const row of rows) {
    const code = row['PPCO']?.trim();
    const name = row['PPNA']?.trim();
    if (code && name) {
      map.set(code, name);
    }
  }
  console.error(`    Loaded ${map.size} plant part codes`);
  return map;
}

// ---------------------------------------------------------------------------
// Duke: Parse CHEMICALS → compounds
// ---------------------------------------------------------------------------

function loadCompounds(db: Database.Database): void {
  console.error('  Loading compounds from CHEMICALS.csv...');
  const rows = readCsvFile(path.join(DUKE_DIR, 'CHEMICALS.csv'));

  const compoundStmt = db.prepare(`
    INSERT OR IGNORE INTO compounds (id, name, name_normalized, cas_number, pubchem_cid, compound_class, bioactivities)
    VALUES (?, ?, ?, ?, NULL, NULL, '[]')
  `);

  const nameMapStmt = db.prepare(`
    INSERT OR IGNORE INTO compound_name_map (normalized_name, source, original_name, compound_id)
    VALUES (?, 'duke', ?, ?)
  `);

  const insertAll = db.transaction((data: Record<string, string>[]) => {
    for (const row of data) {
      const name = row['CHEM']?.trim();
      if (!name) continue;

      const normalized = normalizeCompoundName(name);
      const cas = row['CASNUM']?.trim() || null;

      compoundStmt.run(normalized, name, normalized, cas);
      nameMapStmt.run(normalized, name, normalized);
    }
  });

  insertAll(rows);
  console.error(`    Loaded ${rows.length} compounds`);
}

// ---------------------------------------------------------------------------
// Duke: Parse FARMACY_NEW → herb_compounds
// ---------------------------------------------------------------------------

function loadHerbCompounds(db: Database.Database, partsMap: Map<string, string>): void {
  console.error('  Loading herb-compound relationships from FARMACY_NEW.csv...');
  const rows = readCsvFile(path.join(DUKE_DIR, 'FARMACY_NEW.csv'));

  const stmt = db.prepare(`
    INSERT OR IGNORE INTO herb_compounds
      (herb_id, compound_id, plant_part, plant_part_code, concentration_low_ppm, concentration_high_ppm, compound_class, reference, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'duke')
  `);

  let inserted = 0;
  let skipped = 0;

  const insertAll = db.transaction((data: Record<string, string>[]) => {
    for (const row of data) {
      const herbId = row['FNFNUM']?.trim();
      const chem = row['CHEM']?.trim();
      const ppco = row['PPCO']?.trim() || 'UNK';
      if (!herbId || !chem) { skipped++; continue; }

      const compoundId = normalizeCompoundName(chem);
      const partName = partsMap.get(ppco) || ppco;
      const amtLow = parsePpm(row['AMT_OR_LO']);
      const amtHigh = parsePpm(row['AMT_HI']);
      const chemClass = row['CHEMCLASS']?.trim() || null;
      const reference = row['REFERENCE']?.trim() || null;

      stmt.run(herbId, compoundId, partName, ppco, amtLow, amtHigh, chemClass, reference);
      inserted++;
    }
  });

  insertAll(rows);
  console.error(`    Inserted ${inserted} herb-compound links (${skipped} skipped)`);
}

// ---------------------------------------------------------------------------
// Duke: Parse AGGREGAC → update compounds.bioactivities
// ---------------------------------------------------------------------------

function loadBioactivities(db: Database.Database): void {
  console.error('  Loading bioactivities from AGGREGAC.csv...');
  const rows = readCsvFile(path.join(DUKE_DIR, 'AGGREGAC.csv'));

  // Group activities by compound
  const activitiesByCompound = new Map<string, Set<string>>();
  for (const row of rows) {
    const chem = row['CHEM']?.trim();
    const activity = row['ACTIVITY']?.trim();
    if (chem && activity) {
      const id = normalizeCompoundName(chem);
      const existing = activitiesByCompound.get(id) || new Set<string>();
      existing.add(activity);
      activitiesByCompound.set(id, existing);
    }
  }

  const stmt = db.prepare(`
    UPDATE compounds SET bioactivities = ? WHERE id = ?
  `);

  const updateAll = db.transaction(() => {
    for (const [id, activities] of activitiesByCompound) {
      stmt.run(JSON.stringify([...activities].sort()), id);
    }
  });

  updateAll();
  console.error(`    Updated bioactivities for ${activitiesByCompound.size} compounds`);
}

// ---------------------------------------------------------------------------
// Duke: Backfill compound_class from FARMACY_NEW
// ---------------------------------------------------------------------------

function backfillCompoundClass(db: Database.Database): void {
  console.error('  Backfilling compound classes from herb_compounds...');
  const result = db.prepare(`
    UPDATE compounds
    SET compound_class = (
      SELECT hc.compound_class
      FROM herb_compounds hc
      WHERE hc.compound_id = compounds.id AND hc.compound_class IS NOT NULL
      LIMIT 1
    )
    WHERE compound_class IS NULL
  `).run();
  console.error(`    Updated ${result.changes} compounds with class info`);
}

// ---------------------------------------------------------------------------
// FooDB: Stream Content.csv (5M+ rows) line-by-line
// ---------------------------------------------------------------------------

function parseCsvLine(line: string): string[] {
  // Simple CSV parser handling quoted fields
  const fields: string[] = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && i + 1 < line.length && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      fields.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

async function loadFoodbContent(
  db: Database.Database,
  contentCsvPath: string,
  foodbCompoundMap: Map<string, { name: string; publicId: string; normalized: string }>,
  foodMap: Map<string, { name: string; nameScientific: string; group: string; publicId: string }>,
): Promise<void> {
  const insertContent = db.prepare(`
    INSERT OR IGNORE INTO compound_foods
      (compound_id, food_name, food_name_scientific, food_group, content_value, content_min, content_max, content_unit, food_part, citation, foodb_food_id, foodb_compound_id, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'foodb')
  `);

  let contentInserted = 0;
  let contentSkipped = 0;
  let lineNum = 0;
  let headers: string[] = [];

  const BATCH_SIZE = 10_000;
  let batch: Array<() => void> = [];

  const flushBatch = db.transaction((ops: Array<() => void>) => {
    for (const op of ops) op();
  });

  const rl = readline.createInterface({
    input: fs.createReadStream(contentCsvPath, 'utf8'),
    crlfDelay: Infinity,
  });

  for await (const line of rl) {
    lineNum++;
    if (lineNum === 1) {
      headers = parseCsvLine(line).map((h) => h.trim());
      continue;
    }

    const values = parseCsvLine(line);
    const row: Record<string, string> = {};
    for (let i = 0; i < headers.length; i++) {
      row[headers[i]] = values[i] || '';
    }

    const sourceType = row['source_type']?.trim();
    if (sourceType !== 'Compound') { contentSkipped++; continue; }

    const sourceId = row['source_id']?.trim();
    const foodId = row['food_id']?.trim();
    if (!sourceId || !foodId) { contentSkipped++; continue; }

    const compound = foodbCompoundMap.get(sourceId);
    const food = foodMap.get(foodId);
    if (!compound || !food) { contentSkipped++; continue; }

    const compoundId = compound.normalized;
    const origContent = parsePpm(row['orig_content']);
    const origMin = parsePpm(row['orig_min']);
    const origMax = parsePpm(row['orig_max']);
    const origUnit = row['orig_unit']?.trim() || null;
    const foodPart = row['orig_food_part']?.trim() || 'Whole';
    const citation = row['citation']?.trim() || null;

    batch.push(() => {
      insertContent.run(
        compoundId, food.name, food.nameScientific, food.group,
        origContent, origMin, origMax, origUnit, foodPart, citation,
        food.publicId, compound.publicId,
      );
    });
    contentInserted++;

    if (batch.length >= BATCH_SIZE) {
      flushBatch(batch);
      batch = [];
    }

    if (lineNum % 500_000 === 0) {
      console.error(`    Processed ${lineNum.toLocaleString()} lines...`);
    }
  }

  if (batch.length > 0) {
    flushBatch(batch);
  }

  console.error(`    Inserted ${contentInserted.toLocaleString()} compound-food links (${contentSkipped.toLocaleString()} skipped)`);
}

// ---------------------------------------------------------------------------
// FooDB: Parse compound→food relationships
// ---------------------------------------------------------------------------

async function loadFoodbData(db: Database.Database): Promise<void> {
  const foodCsvPath = path.join(FOODB_DIR, 'Food.csv');
  const compoundCsvPath = path.join(FOODB_DIR, 'Compound.csv');
  const contentCsvPath = path.join(FOODB_DIR, 'Content.csv');

  if (!fs.existsSync(foodCsvPath)) {
    console.error('  FooDB data not found — skipping compound-food loading.');
    console.error('  To include FooDB, run: npm run download-data && npm run convert-data');
    return;
  }

  console.error('  Loading FooDB foods...');
  const foodRows = readCsvFile(foodCsvPath, 'utf8');
  const foodMap = new Map<string, { name: string; nameScientific: string; group: string; publicId: string }>();
  for (const row of foodRows) {
    const id = row['id']?.trim();
    if (id) {
      foodMap.set(id, {
        name: row['name']?.trim() || '',
        nameScientific: row['name_scientific']?.trim() || '',
        group: row['food_group']?.trim() || row['food_subgroup']?.trim() || '',
        publicId: row['public_id']?.trim() || '',
      });
    }
  }
  console.error(`    Loaded ${foodMap.size} foods`);

  console.error('  Loading FooDB compounds...');
  const compoundRows = readCsvFile(compoundCsvPath, 'utf8');
  const foodbCompoundMap = new Map<string, { name: string; publicId: string; normalized: string }>();
  const nameMapStmt = db.prepare(`
    INSERT OR IGNORE INTO compound_name_map (normalized_name, source, original_name, compound_id)
    VALUES (?, 'foodb', ?, ?)
  `);

  const insertNameMaps = db.transaction((data: Record<string, string>[]) => {
    for (const row of data) {
      const id = row['id']?.trim();
      const name = row['name']?.trim();
      if (id && name) {
        const normalized = normalizeCompoundName(name);
        foodbCompoundMap.set(id, {
          name,
          publicId: row['public_id']?.trim() || '',
          normalized,
        });
        nameMapStmt.run(normalized, name, normalized);
      }
    }
  });
  insertNameMaps(compoundRows);
  console.error(`    Loaded ${foodbCompoundMap.size} FooDB compounds`);

  // Also create compounds not already in Duke
  console.error('  Merging FooDB compounds into compounds table...');
  const insertCompound = db.prepare(`
    INSERT OR IGNORE INTO compounds (id, name, name_normalized, cas_number, pubchem_cid, compound_class, bioactivities)
    VALUES (?, ?, ?, NULL, NULL, NULL, '[]')
  `);
  const mergeCompounds = db.transaction(() => {
    for (const [, info] of foodbCompoundMap) {
      insertCompound.run(info.normalized, info.name, info.normalized);
    }
  });
  mergeCompounds();

  // Parse Content.csv — 5M+ rows, must stream line-by-line
  console.error('  Loading FooDB content (compound→food mappings)...');
  await loadFoodbContent(db, contentCsvPath, foodbCompoundMap, foodMap);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  console.error('=== Building herbal_botanicals.db ===');

  // Verify Duke data exists
  if (!fs.existsSync(path.join(DUKE_DIR, 'FNFTAX.csv'))) {
    throw new Error(`Duke CSVs not found in ${DUKE_DIR}. Run 'npm run convert-data' after decompress.`);
  }

  // Clean slate
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  if (fs.existsSync(DB_PATH)) {
    fs.unlinkSync(DB_PATH);
  }

  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.pragma('synchronous = NORMAL');
  db.pragma('foreign_keys = OFF'); // Disable during ETL; re-enable after

  try {
    createSchema(db);

    // Duke data (herbs, compounds, herb-compounds, bioactivities)
    loadHerbs(db);
    loadCommonNames(db);
    const partsMap = loadPartsMap();
    loadCompounds(db);
    loadHerbCompounds(db, partsMap);
    loadBioactivities(db);
    backfillCompoundClass(db);

    // FooDB data (compound→food bridge)
    await loadFoodbData(db);

    // Summary
    const herbCount = (db.prepare('SELECT COUNT(*) as cnt FROM herbs').get() as { cnt: number }).cnt;
    const compoundCount = (db.prepare('SELECT COUNT(*) as cnt FROM compounds').get() as { cnt: number }).cnt;
    const herbCompoundCount = (db.prepare('SELECT COUNT(*) as cnt FROM herb_compounds').get() as { cnt: number }).cnt;
    const compoundFoodCount = (db.prepare('SELECT COUNT(*) as cnt FROM compound_foods').get() as { cnt: number }).cnt;
    const bridgeCount = (db.prepare(`
      SELECT COUNT(DISTINCT c.id) as cnt FROM compounds c
      WHERE EXISTS (SELECT 1 FROM herb_compounds hc WHERE hc.compound_id = c.id)
        AND EXISTS (SELECT 1 FROM compound_foods cf WHERE cf.compound_id = c.id)
    `).get() as { cnt: number }).cnt;

    console.error('\n=== Database Summary ===');
    console.error(`  Herbs:           ${herbCount.toLocaleString()}`);
    console.error(`  Compounds:       ${compoundCount.toLocaleString()}`);
    console.error(`  Herb-Compounds:  ${herbCompoundCount.toLocaleString()}`);
    console.error(`  Compound-Foods:  ${compoundFoodCount.toLocaleString()}`);
    console.error(`  Bridge compounds: ${bridgeCount.toLocaleString()} (in both herb + food)`);
    console.error(`  Database: ${DB_PATH}`);
    console.error('=== Build complete ===');
  } finally {
    db.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error('Build failed:', err);
    process.exit(1);
  });
}

export { main as buildHerbalDb };
