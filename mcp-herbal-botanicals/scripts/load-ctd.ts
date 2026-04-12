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
import { normalizeCompoundName } from './build-herbal-db.js';

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

  for await (const line of rl) {
    // Skip comment lines
    if (line.startsWith('#')) {
      continue;
    }

    stats.processed++;
    const fields = line.split(',').map(f => f.trim());
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
  const cdFile = path.join(DATA_DIR, 'CTD_chemicals_diseases.csv.gz');
  if (fs.existsSync(cdFile)) {
    console.error('  Loading CTD chemical-disease associations...');
    const insertCD = db.prepare(`
      INSERT OR IGNORE INTO chemical_diseases (compound_id, chemical_name, disease_name, disease_id, direct_evidence, inference_score)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    let batch: Array<() => void> = [];
    const BATCH_SIZE = 10000;

    const stats = await streamGzipCsv(cdFile, compoundLookup, (compoundId, fields) => {
      const chemName = fields[0] || '';
      const diseaseName = fields[3] || '';
      const diseaseId = fields[4] || '';
      const directEvidence = fields[5] || '';
      const inferenceScore = fields[7] ? parseFloat(fields[7]) || null : null;

      if (!diseaseName) return;

      // Only keep direct evidence entries to avoid millions of inferred rows
      if (!directEvidence && !inferenceScore) return;

      batch.push(() => {
        insertCD.run(compoundId, chemName, diseaseName, diseaseId, directEvidence, inferenceScore);
        result.diseases++;
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
    console.error(`  CTD diseases: ${result.diseases} loaded (${stats.matched} matched, ${stats.skipped} skipped)`);
  } else {
    console.error(`  CTD chemical-disease file not found: ${cdFile}`);
    console.error('  Download from https://ctdbase.org/downloads/ (CAPTCHA required)');
  }

  // --- Load chemical-phenotype interactions ---
  const cpFile = path.join(DATA_DIR, 'CTD_chem_phenotype_interactions.csv.gz');
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
    console.error('  Download from https://ctdbase.org/downloads/ (CAPTCHA required)');
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
