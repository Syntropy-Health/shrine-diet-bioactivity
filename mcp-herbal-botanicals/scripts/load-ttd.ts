/**
 * Load TTD (Therapeutic Target Database) data into herbal_botanicals.db.
 *
 * Enriches: targets table with druggability_status from TTD.
 * Cross-references via UniProt_ID and Gene_Symbol.
 *
 * Usage:
 *   tsx scripts/load-ttd.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';

const DATA_DIR = path.join(process.cwd(), 'data');
const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');

interface TtdTarget {
  targetId: string;
  name: string;
  type: string;
  uniprotId: string | null;
  geneSymbol: string | null;
  druggabilityStatus: string | null;
}

/**
 * TTD P1-01 v10 uses a 3-column format:
 *   T47101\tTARGETID\tT47101
 *   T47101\tUNIPROID\tFGFR1_HUMAN
 *   T47101\tTARGNAME\tFibroblast growth factor receptor 1 (FGFR1)
 *   T47101\tGENENAME\tFGFR1
 *   T47101\tTARGTYPE\tSuccessful
 *   T59328\tTARGETID\tT59328
 *   ...
 * Records are grouped by the first column (target ID). No blank line separators.
 */
function parseTtdTargetFile(filePath: string): TtdTarget[] {
  if (!fs.existsSync(filePath)) {
    console.error(`  File not found: ${filePath}`);
    return [];
  }

  const raw = fs.readFileSync(filePath, 'utf-8');
  const lines = raw.split('\n');
  const targetMap = new Map<string, Record<string, string>>();

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('TTD') || trimmed.startsWith('Title') ||
        trimmed.startsWith('Version') || trimmed.startsWith('Provided') ||
        trimmed.startsWith('---') || trimmed.startsWith('TARGETID\t')) {
      continue; // Skip headers
    }

    const parts = trimmed.split('\t');
    if (parts.length < 3) continue;

    const id = parts[0].trim();
    const field = parts[1].trim();
    const value = parts.slice(2).join('\t').trim();

    if (!id || !field) continue;

    let record = targetMap.get(id);
    if (!record) {
      record = {};
      targetMap.set(id, record);
    }
    record[field] = value;
  }

  const targets: TtdTarget[] = [];
  for (const [id, record] of targetMap) {
    targets.push({
      targetId: id,
      name: record['TARGNAME'] || record['FORESSION'] || '',
      type: record['TARGTYPE'] || '',
      uniprotId: record['UNIPROID'] || null,
      geneSymbol: record['GENENAME'] || null,
      druggabilityStatus: record['TARGTYPE'] || null,
    });
  }

  return targets;
}

export function loadTtd(db: Database.Database): { enriched: number; newTargets: number; drugDiseases: number } {
  const stats = { enriched: 0, newTargets: 0, drugDiseases: 0 };

  // Add druggability_status column if not exists
  try {
    db.exec('ALTER TABLE targets ADD COLUMN druggability_status TEXT');
  } catch {
    // Column already exists — fine
  }

  // --- Load TTD targets ---
  const targetFile = path.join(DATA_DIR, 'ttd-targets.txt');
  const ttdTargets = parseTtdTargetFile(targetFile);
  if (ttdTargets.length === 0) {
    console.error('  No TTD target data found');
    return stats;
  }
  console.error(`  Parsed ${ttdTargets.length} TTD targets`);

  // Build UniProt lookup from existing targets
  const existingByUniprot = new Map<string, string>();
  const existingByGene = new Map<string, string>();
  const existingTargets = db.prepare('SELECT id, uniprot_id, gene_symbol FROM targets').all() as Array<{ id: string; uniprot_id: string | null; gene_symbol: string | null }>;
  for (const t of existingTargets) {
    if (t.uniprot_id) existingByUniprot.set(t.uniprot_id.toLowerCase(), t.id);
    if (t.gene_symbol) existingByGene.set(t.gene_symbol.toLowerCase(), t.id);
  }

  const updateDruggability = db.prepare('UPDATE targets SET druggability_status = ? WHERE id = ?');
  const insertTarget = db.prepare(`
    INSERT OR IGNORE INTO targets (id, name, uniprot_id, gene_symbol, source, druggability_status)
    VALUES (?, ?, ?, ?, 'ttd', ?)
  `);

  const tx = db.transaction(() => {
    for (const ttd of ttdTargets) {
      if (!ttd.targetId) continue;

      // Try to match existing target by UniProt or gene symbol
      let existingId: string | undefined;
      if (ttd.uniprotId) {
        existingId = existingByUniprot.get(ttd.uniprotId.toLowerCase());
      }
      if (!existingId && ttd.geneSymbol) {
        existingId = existingByGene.get(ttd.geneSymbol.toLowerCase());
      }

      if (existingId) {
        // Enrich existing target with druggability
        updateDruggability.run(ttd.druggabilityStatus, existingId);
        stats.enriched++;
      } else {
        // Add as new target
        insertTarget.run(
          `ttd:${ttd.targetId}`,
          ttd.name,
          ttd.uniprotId,
          ttd.geneSymbol,
          ttd.druggabilityStatus
        );
        stats.newTargets++;
      }
    }
  });
  tx();
  console.error(`  TTD: ${stats.enriched} enriched, ${stats.newTargets} new targets added`);

  // --- Load drug-disease associations ---
  // TTD P1-05 format: INDICATI\tDiseaseName\tICD-11: XX\tClinicalStatus
  // Grouped by DRUGNAME rows
  const ddFile = path.join(DATA_DIR, 'ttd-drug-disease.txt');
  if (fs.existsSync(ddFile)) {
    const raw = fs.readFileSync(ddFile, 'utf-8');
    const lines = raw.split('\n');

    const insertDD = db.prepare(`
      INSERT OR IGNORE INTO target_diseases (target_id, disease_name, evidence_layer, source)
      VALUES (?, ?, ?, 'ttd')
    `);

    let currentDrug = '';
    const ddTx = db.transaction(() => {
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        const parts = trimmed.split('\t');
        const field = parts[0]?.trim() || '';

        if (field === 'DRUGNAME' && parts.length >= 2) {
          currentDrug = parts[1]?.trim() || '';
        } else if (field === 'INDICATI' && parts.length >= 2 && currentDrug) {
          const diseaseName = parts[1]?.trim() || '';
          const clinicalStatus = parts[parts.length - 1]?.trim() || '';
          if (diseaseName && diseaseName !== 'Indication') {
            insertDD.run(`drug:${currentDrug}`, diseaseName, clinicalStatus);
            stats.drugDiseases++;
          }
        }
      }
    });
    ddTx();
    console.error(`  TTD: ${stats.drugDiseases} drug-disease associations loaded`);
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
    const stats = loadTtd(db);
    console.error('\n=== TTD Load Summary ===');
    console.error(JSON.stringify(stats, null, 2));
  } finally {
    db.close();
  }
}
