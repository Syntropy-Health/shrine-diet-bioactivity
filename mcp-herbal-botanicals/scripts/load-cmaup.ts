/**
 * Load CMAUP v2.0 data into herbal_botanicals.db.
 *
 * Populates: targets, compound_targets, target_diseases tables.
 * Enriches: herbs with CMAUP plant classification.
 * Cross-references compounds via normalizeCompoundName().
 *
 * Usage:
 *   tsx scripts/load-cmaup.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { normalizeCompoundName } from './build-herbal-db.js';

const DATA_DIR = path.join(process.cwd(), 'data');
const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');

function readTsvFile(filePath: string): Record<string, string>[] {
  if (!fs.existsSync(filePath)) {
    console.error(`  File not found: ${filePath}`);
    return [];
  }
  const raw = fs.readFileSync(filePath, 'utf-8');
  const lines = raw.split('\n').filter(l => l.trim().length > 0);
  if (lines.length === 0) return [];

  const headers = lines[0].split('\t').map(h => h.trim());
  const rows: Record<string, string>[] = [];
  for (let i = 1; i < lines.length; i++) {
    const values = lines[i].split('\t');
    const row: Record<string, string> = {};
    for (let j = 0; j < headers.length; j++) {
      row[headers[j]] = (values[j] || '').trim();
    }
    rows.push(row);
  }
  return rows;
}

export function loadCmaup(db: Database.Database): { targets: number; compoundTargets: number; plantDiseases: number; matched: number; unmatched: number } {
  const stats = { targets: 0, compoundTargets: 0, plantDiseases: 0, matched: 0, unmatched: 0 };

  // Build compound lookup from existing DB
  const compoundLookup = new Map<string, string>();
  const compoundRows = db.prepare('SELECT id, name_normalized FROM compounds').all() as Array<{ id: string; name_normalized: string }>;
  for (const row of compoundRows) {
    compoundLookup.set(row.name_normalized, row.id);
  }
  console.error(`  Compound lookup built: ${compoundLookup.size} entries`);

  // --- Load targets ---
  const targetsFile = path.join(DATA_DIR, 'cmaup-targets.txt');
  const targetRows = readTsvFile(targetsFile);
  if (targetRows.length > 0) {
    const insertTarget = db.prepare(`
      INSERT OR IGNORE INTO targets (id, name, uniprot_id, gene_symbol, source)
      VALUES (?, ?, ?, ?, 'cmaup')
    `);
    const tx = db.transaction(() => {
      for (const row of targetRows) {
        const id = row['Target_ID'] || '';
        const name = row['Protein_Name'] || row['Target_Name'] || '';
        const uniprot = row['Uniprot_ID'] || row['UniProt_ID'] || null;
        const gene = row['Gene_Symbol'] || null;
        if (id && name) {
          insertTarget.run(id, name, uniprot, gene);
          stats.targets++;
        }
      }
    });
    tx();
    console.error(`  Loaded ${stats.targets} targets from CMAUP`);
  }

  // --- Load ingredient-target associations ---
  const itFile = path.join(DATA_DIR, 'cmaup-ingredient-targets.txt');
  const itRows = readTsvFile(itFile);
  if (itRows.length > 0) {
    const insertCT = db.prepare(`
      INSERT OR IGNORE INTO compound_targets (compound_id, target_id, activity_value, activity_type, interaction_type, source)
      VALUES (?, ?, ?, ?, ?, 'cmaup')
    `);

    const BATCH_SIZE = 10000;
    let batch: Array<() => void> = [];

    // Build ingredient ID → name lookup from ingredients file
    const ingredientLookup = new Map<string, string>();
    const ingredientsFile = path.join(DATA_DIR, 'cmaup-ingredients.txt');
    const ingredientRows = readTsvFile(ingredientsFile);
    for (const ir of ingredientRows) {
      const iid = ir['np_id'] || ir['Ingredient_ID'] || '';
      const iname = ir['pref_name'] || ir['Ingredient_Name'] || '';
      if (iid && iname) ingredientLookup.set(iid, iname);
    }
    console.error(`  Ingredient lookup built: ${ingredientLookup.size} entries`);

    for (const row of itRows) {
      const ingredientId = row['Ingredient_ID'] || '';
      const targetId = row['Target_ID'] || '';
      const activityValue = row['Activity_Value'] || null;
      const activityType = row['Activity_Type'] || null;

      if (!ingredientId || !targetId) continue;

      // Look up ingredient name, then normalize to find compound
      const ingredientName = ingredientLookup.get(ingredientId) || ingredientId;
      const normalized = normalizeCompoundName(ingredientName);
      const compoundId = compoundLookup.get(normalized);
      if (compoundId) {
        stats.matched++;
        batch.push(() => {
          insertCT.run(
            compoundId,
            targetId,
            activityValue ? parseFloat(activityValue) || null : null,
            activityType || null,
            null
          );
          stats.compoundTargets++;
        });
      } else {
        stats.unmatched++;
      }

      if (batch.length >= BATCH_SIZE) {
        db.transaction(() => { for (const fn of batch) fn(); })();
        batch = [];
      }
    }
    if (batch.length > 0) {
      db.transaction(() => { for (const fn of batch) fn(); })();
    }
    console.error(`  Loaded ${stats.compoundTargets} compound-target associations (${stats.matched} matched, ${stats.unmatched} unmatched)`);
  }

  // --- Load plant-disease associations ---
  const pdFile = path.join(DATA_DIR, 'cmaup-plant-diseases.txt');
  const pdRows = readTsvFile(pdFile);
  if (pdRows.length > 0) {
    const insertPD = db.prepare(`
      INSERT OR IGNORE INTO target_diseases (target_id, disease_name, evidence_layer, source)
      VALUES (?, ?, ?, 'cmaup')
    `);
    // CMAUP plant-disease uses Disease column and Plant_ID
    // Build evidence string from association columns
    const BATCH_SIZE_PD = 10000;
    let pdBatch: Array<() => void> = [];
    for (const row of pdRows) {
      const plantId = row['Plant_ID'] || '';
      const disease = row['Disease'] || row['Disease_Category'] || '';
      if (!plantId || !disease) continue;

      // Build evidence from association columns
      const evidence: string[] = [];
      if (row['Association_by_Therapeutic_Target'] === '1') evidence.push('therapeutic_target');
      if (row['Association_by_Disease_Transcriptiome_Reversion'] === '1') evidence.push('transcriptome');
      if (row['Association_by_Clinical_Trials_of_Plant'] === '1') evidence.push('clinical_trial_plant');
      if (row['Association_by_Clinical_Trials_of_Plant_Ingredients'] === '1') evidence.push('clinical_trial_ingredient');

      pdBatch.push(() => {
        insertPD.run(`plant:${plantId}`, disease, evidence.join(',') || null);
        stats.plantDiseases++;
      });

      if (pdBatch.length >= BATCH_SIZE_PD) {
        db.transaction(() => { for (const fn of pdBatch) fn(); })();
        pdBatch = [];
      }
    }
    if (pdBatch.length > 0) {
      db.transaction(() => { for (const fn of pdBatch) fn(); })();
    }
    console.error(`  Loaded ${stats.plantDiseases} plant-disease associations`);
  }

  return stats;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  if (!fs.existsSync(DB_PATH)) {
    console.error('Database not found. Run npm run convert-data && npm run migrate-kg first.');
    process.exit(1);
  }
  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  try {
    const stats = loadCmaup(db);
    console.error('\n=== CMAUP Load Summary ===');
    console.error(JSON.stringify(stats, null, 2));
  } finally {
    db.close();
  }
}
