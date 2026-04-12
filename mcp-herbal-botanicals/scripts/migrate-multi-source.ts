/**
 * Orchestrate multi-source data integration into herbal_botanicals.db.
 *
 * This is the single entry point for loading CMAUP, CTD, and TTD data.
 * Must run AFTER: npm run convert-data && npm run migrate-kg
 *
 * All operations are idempotent (IF NOT EXISTS, INSERT OR IGNORE).
 *
 * Usage:
 *   tsx scripts/migrate-multi-source.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { loadCmaup } from './load-cmaup.js';
import { loadCtd } from './load-ctd.js';
import { loadTtd } from './load-ttd.js';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');

function ensurePrerequisites(db: Database.Database): void {
  // Check that base tables exist
  const tables = db.prepare(`
    SELECT name FROM sqlite_master WHERE type='table' AND name IN ('herbs', 'compounds', 'herb_compounds', 'targets')
  `).all() as Array<{ name: string }>;

  const tableNames = new Set(tables.map(t => t.name));
  if (!tableNames.has('herbs') || !tableNames.has('compounds')) {
    throw new Error('Base tables (herbs, compounds) not found. Run npm run convert-data first.');
  }
  if (!tableNames.has('targets')) {
    throw new Error('KG expansion tables not found. Run npm run migrate-kg first.');
  }
}

function createAdditionalSchema(db: Database.Database): void {
  // CTD tables
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

  // Add druggability_status to targets if not exists
  try {
    db.exec('ALTER TABLE targets ADD COLUMN druggability_status TEXT');
  } catch {
    // Column already exists
  }
}

function printStats(db: Database.Database): void {
  const safeCount = (sql: string): number => {
    try {
      return (db.prepare(sql).get() as { cnt: number }).cnt;
    } catch {
      return 0;
    }
  };

  console.error('\n=== Multi-Source Integration Summary ===');
  console.error(`  herbs:              ${safeCount('SELECT COUNT(*) as cnt FROM herbs')}`);
  console.error(`  compounds:          ${safeCount('SELECT COUNT(*) as cnt FROM compounds')}`);
  console.error(`  targets:            ${safeCount('SELECT COUNT(*) as cnt FROM targets')}`);
  console.error(`  compound_targets:   ${safeCount('SELECT COUNT(*) as cnt FROM compound_targets')}`);
  console.error(`  target_diseases:    ${safeCount('SELECT COUNT(*) as cnt FROM target_diseases')}`);
  console.error(`  chemical_diseases:  ${safeCount('SELECT COUNT(*) as cnt FROM chemical_diseases')}`);
  console.error(`  chemical_phenotypes: ${safeCount('SELECT COUNT(*) as cnt FROM chemical_phenotypes')}`);
  console.error(`  symptoms:           ${safeCount('SELECT COUNT(*) as cnt FROM symptoms')}`);
  console.error(`  herb_symptoms:      ${safeCount('SELECT COUNT(*) as cnt FROM herb_symptoms')}`);
  console.error(`  food_plants:        ${safeCount("SELECT COUNT(*) as cnt FROM herbs WHERE is_food_plant = 1")}`);
  const druggable = safeCount("SELECT COUNT(*) as cnt FROM targets WHERE druggability_status IS NOT NULL");
  console.error(`  druggable_targets:  ${druggable}`);
  console.error('=======================================\n');
}

async function main(): Promise<void> {
  if (!fs.existsSync(DB_PATH)) {
    console.error('Database not found. Run npm run convert-data && npm run migrate-kg first.');
    process.exit(1);
  }

  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');

  try {
    console.error('=== Multi-Source Data Integration ===\n');

    // Step 0: Verify prerequisites
    console.error('Step 0: Checking prerequisites...');
    ensurePrerequisites(db);
    console.error('  Prerequisites OK\n');

    // Step 1: Create additional schema
    console.error('Step 1: Creating additional schema...');
    createAdditionalSchema(db);
    console.error('  Schema ready\n');

    // Step 2: Load CMAUP
    console.error('Step 2: Loading CMAUP data...');
    const cmaupStats = loadCmaup(db);
    console.error(`  CMAUP done: ${JSON.stringify(cmaupStats)}\n`);

    // Step 3: Load CTD (skip if files not present)
    console.error('Step 3: Loading CTD data...');
    const ctdStats = await loadCtd(db);
    console.error(`  CTD done: ${JSON.stringify(ctdStats)}\n`);

    // Step 4: Load TTD (skip if files not present)
    console.error('Step 4: Loading TTD data...');
    const ttdStats = loadTtd(db);
    console.error(`  TTD done: ${JSON.stringify(ttdStats)}\n`);

    // Step 5: Print summary
    printStats(db);
  } finally {
    db.close();
  }
}

main().catch((err) => {
  console.error('Migration failed:', err);
  process.exit(1);
});
