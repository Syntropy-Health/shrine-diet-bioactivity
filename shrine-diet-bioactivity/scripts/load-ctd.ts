/**
 * Load CTD (Comparative Toxicogenomics Database) data into herbal_botanicals.db.
 *
 * Populates: chemical_diseases, chemical_phenotypes tables.
 * Filters to only chemicals matching our compound universe.
 *
 * CTD files must be downloaded manually (CAPTCHA required):
 *   https://ctdbase.org/downloads/
 *
 * Place files in data/ directory:
 *   - CTD_chemicals_diseases.csv.gz
 *   - CTD_chem_phenotype_interactions.csv.gz
 *
 * Usage:
 *   tsx scripts/load-ctd.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import * as readline from 'readline';
import * as zlib from 'zlib';
import Database from 'better-sqlite3';
import { normalizeCompoundName } from './_normalize.js';
import { parseCsvLine } from './_csv-parse.js';

const DATA_DIR = path.join(process.cwd(), 'data');
const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');

function createCtdSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS chemical_diseases (
      compound_id TEXT NOT NULL,
      chemical_name TEXT NOT NULL,
      disease_name TEXT NOT NULL,
      disease_id TEXT,
      direct_evidence TEXT,
      inference_score REAL,
      source TEXT DEFAULT 'ctd',
      PRIMARY KEY (compound_id, disease_name)
    );

    CREATE TABLE IF NOT EXISTS chemical_phenotypes (
      compound_id TEXT NOT NULL,
      chemical_name TEXT NOT NULL,
      phenotype_name TEXT NOT NULL,
      phenotype_id TEXT,
      interaction TEXT,
      source TEXT DEFAULT 'ctd',
      PRIMARY KEY (compound_id, phenotype_name)
    );

    CREATE INDEX IF NOT EXISTS idx_chemical_diseases_compound ON chemical_diseases(compound_id);
    CREATE INDEX IF NOT EXISTS idx_chemical_diseases_disease ON chemical_diseases(disease_name);
    CREATE INDEX IF NOT EXISTS idx_chemical_phenotypes_compound ON chemical_phenotypes(compound_id);
    CREATE INDEX IF NOT EXISTS idx_chemical_phenotypes_phenotype ON chemical_phenotypes(phenotype_name);
  `);
}

async function streamGzipCsv(
  filePath: string,
  compoundLookup: Map<string, string>,
  handler: (compoundId: string, fields: string[]) => void
): Promise<{ processed: number; matched: number; skipped: number }> {
  const stats = { processed: 0, matched: 0, skipped: 0 };

  const gunzip = zlib.createGunzip();
  const input = fs.createReadStream(filePath);
  const rl = readline.createInterface({ input: input.pipe(gunzip) });

  for await (const rawLine of rl) {
    // Defense-in-depth against CRLF: CTD currently ships LF-only files
    // (verified May 2026), but readline does NOT strip a trailing \r if
    // the upstream ever switches to Windows endings. Strip it here so
    // the last field on every row never carries a stray \r into the DB.
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;

    // Skip comment lines
    if (line.startsWith('#')) {
      continue;
    }

    stats.processed++;
    // RFC-4180 parser — preserves commas inside quoted disease names like
    // "Lymphoma, Mantle-Cell". The previous `line.split(',')` corrupted
    // these rows and silently shifted every subsequent field by one.
    const fields = parseCsvLine(line).map((f) => f.trim());
    const chemicalName = fields[0] || '';
    if (!chemicalName) continue;

    const normalized = normalizeCompoundName(chemicalName);
    const compoundId = compoundLookup.get(normalized);
    if (compoundId) {
      stats.matched++;
      handler(compoundId, fields);
    } else {
      stats.skipped++;
    }
  }

  return stats;
}

export async function loadCtd(db: Database.Database): Promise<{ diseases: number; phenotypes: number; matched: number; skipped: number }> {
  const result = { diseases: 0, phenotypes: 0, matched: 0, skipped: 0 };

  createCtdSchema(db);

  // Build compound lookup
  const compoundLookup = new Map<string, string>();
  const compoundRows = db.prepare('SELECT id, name_normalized FROM compounds').all() as Array<{ id: string; name_normalized: string }>;
  for (const row of compoundRows) {
    compoundLookup.set(row.name_normalized, row.id);
  }
  // Also add CAS number lookup
  const casRows = db.prepare('SELECT id, cas_number FROM compounds WHERE cas_number IS NOT NULL').all() as Array<{ id: string; cas_number: string }>;
  for (const row of casRows) {
    compoundLookup.set(row.cas_number.toLowerCase(), row.id);
  }
  console.error(`  Compound lookup built: ${compoundLookup.size} entries (name + CAS)`);

  // --- Load chemical-disease associations ---
  // Phase 3 dual-write: legacy chemical_diseases (single-string disease_id)
  // PLUS the new compound_disease_evidence table (canonical disease_id +
  // evidence_type + PubMed citations + gene-symbol inference). Both written
  // in the same batch transaction so a partial run can't desynchronize them.
  // The new table is preferred by all post-Phase-3 queries; the legacy table
  // is kept for one stable cycle then dropped (spec §4.5).
  const cdFile = path.join(DATA_DIR, 'CTD_chemicals_diseases.csv.gz');
  if (fs.existsSync(cdFile)) {
    console.error('  Loading CTD chemical-disease associations (dual-write)...');
    const insertCD = db.prepare(`
      INSERT OR IGNORE INTO chemical_diseases (compound_id, chemical_name, disease_name, disease_id, direct_evidence, inference_score)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    // New: prepared statements for canonical-disease lookup + CDE insert.
    const lookupCanonByMesh = db.prepare(
      'SELECT id FROM diseases_canonical WHERE mesh_id = ?',
    );
    const lookupCanonByAlias = db.prepare(
      'SELECT disease_id FROM disease_name_aliases WHERE lower(alias) = lower(?) LIMIT 1',
    );
    const insertCDE = db.prepare(`
      INSERT INTO compound_disease_evidence
        (compound_id, disease_id, evidence_type, inference_gene_symbol,
         inference_score, pubmed_ids, ingested_at)
      VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    `);

    // Idempotent dual-write: clear compound_disease_evidence so a re-run
    // doesn't duplicate. (chemical_diseases dedupes via PK so it's
    // append-safe; CDE has SERIAL id so we need explicit cleanup.)
    db.exec('DELETE FROM compound_disease_evidence');

    let batch: Array<() => void> = [];
    const BATCH_SIZE = 10000;
    let cdeInserted = 0;
    let cdeSkippedNoCanonical = 0;
    let cdeSkippedTypology = 0;

    const stats = await streamGzipCsv(cdFile, compoundLookup, (compoundId, fields) => {
      const chemName = fields[0] || '';
      const diseaseName = fields[3] || '';
      const diseaseId = fields[4] || '';
      const directEvidence = fields[5] || '';
      const inferenceGene = fields[6] || '';
      const inferenceScore = fields[7] ? parseFloat(fields[7]) || null : null;
      // PubMed IDs at column 9; pipe-separated, preserve as-is.
      const pubmedIds = fields[9] || null;

      if (!diseaseName) return;

      // Skip rows with no evidence at all. (Note: CTD writes empty string,
      // not NULL, for the inferred case — caught at harden-plan probe.)
      const hasDirectTherapeutic = directEvidence === 'therapeutic';
      const hasDirectMarker = directEvidence === 'marker/mechanism';
      const hasInferredViaGene = !hasDirectTherapeutic && !hasDirectMarker
        && inferenceScore !== null && inferenceGene.length > 0;

      if (!hasDirectTherapeutic && !hasDirectMarker && !hasInferredViaGene) {
        cdeSkippedTypology++;
        return;
      }

      // Resolve canonical disease id. Prefer MeSH-anchored row.
      let canonicalId: string | null = null;
      if (diseaseId.startsWith('MESH:')) {
        const mesh = diseaseId.substring(5);
        const row = lookupCanonByMesh.get(mesh) as { id: string } | undefined;
        if (row) canonicalId = row.id;
      }
      if (!canonicalId) {
        // Fall back to alias lookup (covers UMLS-anchored rows + bare-name).
        const row = lookupCanonByAlias.get(diseaseName) as
          | { disease_id: string }
          | undefined;
        if (row) canonicalId = row.disease_id;
      }

      // Compute evidence_type for the new CDE table.
      const evidenceType = hasDirectTherapeutic
        ? 'direct_therapeutic'
        : hasDirectMarker
          ? 'direct_marker'
          : 'inferred_via_gene';
      const cdeGene = hasInferredViaGene ? inferenceGene : null;
      const cdeScore = hasInferredViaGene ? inferenceScore : null;

      batch.push(() => {
        // Always write legacy chemical_diseases so existing queries survive.
        insertCD.run(
          compoundId, chemName, diseaseName, diseaseId,
          directEvidence, inferenceScore,
        );
        result.diseases++;
        // Dual-write to compound_disease_evidence (skip if canonical missing).
        if (canonicalId !== null) {
          insertCDE.run(
            compoundId, canonicalId, evidenceType,
            cdeGene, cdeScore, pubmedIds,
          );
          cdeInserted++;
        } else {
          cdeSkippedNoCanonical++;
        }
      });

      if (batch.length >= BATCH_SIZE) {
        db.transaction(() => { for (const fn of batch) fn(); })();
        batch = [];
      }
    });

    if (batch.length > 0) {
      db.transaction(() => { for (const fn of batch) fn(); })();
    }

    result.matched += stats.matched;
    result.skipped += stats.skipped;
    console.error(
      `  CTD legacy chemical_diseases: ${result.diseases} loaded ` +
      `(${stats.matched} matched, ${stats.skipped} skipped)`,
    );
    console.error(
      `  CTD compound_disease_evidence: ${cdeInserted} inserted, ` +
      `${cdeSkippedNoCanonical} skipped (no canonical), ` +
      `${cdeSkippedTypology} skipped (no evidence type)`,
    );
  } else {
    console.error(`  CTD chemical-disease file not found: ${cdFile}`);
    console.error(
      '  Run `npm run download:ctd` to fetch directly from ctdbase.org',
    );
    console.error('  (Direct file URLs are NOT CAPTCHA-gated — the website page is.)');
  }

  // --- Load chemical-phenotype interactions ---
  // CTD's actual filename is CTD_pheno_term_ixns.csv.gz (the upstream
  // renamed it from the older CTD_chem_phenotype_interactions). Accept
  // either for backward compatibility with locally-cached older files.
  let cpFile = path.join(DATA_DIR, 'CTD_pheno_term_ixns.csv.gz');
  if (!fs.existsSync(cpFile)) {
    const legacy = path.join(DATA_DIR, 'CTD_chem_phenotype_interactions.csv.gz');
    if (fs.existsSync(legacy)) {
      cpFile = legacy;
    }
  }
  if (fs.existsSync(cpFile)) {
    console.error('  Loading CTD chemical-phenotype interactions...');
    const insertCP = db.prepare(`
      INSERT OR IGNORE INTO chemical_phenotypes (compound_id, chemical_name, phenotype_name, phenotype_id, interaction)
      VALUES (?, ?, ?, ?, ?)
    `);

    let batch: Array<() => void> = [];
    const BATCH_SIZE = 10000;

    const stats = await streamGzipCsv(cpFile, compoundLookup, (compoundId, fields) => {
      const chemName = fields[0] || '';
      const phenotypeName = fields[3] || '';
      const phenotypeId = fields[4] || '';
      const interaction = fields[6] || '';

      if (!phenotypeName) return;

      batch.push(() => {
        insertCP.run(compoundId, chemName, phenotypeName, phenotypeId, interaction);
        result.phenotypes++;
      });

      if (batch.length >= BATCH_SIZE) {
        db.transaction(() => { for (const fn of batch) fn(); })();
        batch = [];
      }
    });

    if (batch.length > 0) {
      db.transaction(() => { for (const fn of batch) fn(); })();
    }

    console.error(`  CTD phenotypes: ${result.phenotypes} loaded (${stats.matched} matched, ${stats.skipped} skipped)`);
  } else {
    console.error(`  CTD phenotype file not found: ${cpFile}`);
    console.error(
      '  Run `npm run download:ctd` to fetch directly from ctdbase.org',
    );
  }

  return result;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  if (!fs.existsSync(DB_PATH)) {
    console.error('Database not found. Run npm run convert-data && npm run migrate-kg first.');
    process.exit(1);
  }
  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  try {
    const stats = await loadCtd(db);
    console.error('\n=== CTD Load Summary ===');
    console.error(JSON.stringify(stats, null, 2));
  } finally {
    db.close();
  }
}
