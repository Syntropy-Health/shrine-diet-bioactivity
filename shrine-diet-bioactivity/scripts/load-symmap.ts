/**
 * Load SymMap v2.0 into herbal_botanicals.db as 5 flat reference tables.
 *
 * SymMap publishes only entity tables (no junction files), so this loader
 * creates a bilingual CN/EN vocabulary + cross-reference resource:
 *   symmap_herbs            ← SMHB (TCM herbs, 698 kept after Suppress)
 *   symmap_tcm_symptoms     ← SMTS (TCM symptoms, 2,285 kept)
 *   symmap_modern_symptoms  ← SMMS (modern/ICD-aligned symptoms, 1,148)
 *   symmap_ingredients      ← SMIT (molecules, 26,035 kept)
 *   symmap_genes            ← SMTT (genes/targets, 20,965)
 *
 * Herb↔symptom linkage is NOT in SymMap — it comes from Duke (existing) +
 * HERB 2.0 (Task 5). See docs and config/data_sources.yaml for context.
 *
 * Rows where Suppress != 0 are skipped (SymMap's deprecation marker).
 *
 * Usage: npx tsx scripts/load-symmap.ts
 */

import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import Database from 'better-sqlite3';
// xlsx ships an ESM-friendly entry under /xlsx.mjs; required for node ESM
import * as XLSX from 'xlsx/xlsx.mjs';
import * as fs from 'fs';
XLSX.set_fs(fs);
import { loadDataSources } from '../src/config';

const _dir = typeof __dirname !== 'undefined'
  ? __dirname
  : dirname(fileURLToPath(import.meta.url));

const PKG_ROOT = resolve(_dir, '..');

interface LoadStats {
  table: string;
  total: number;
  suppressed: number;
  inserted: number;
}

/** Read a single-sheet XLSX into header-keyed rows. */
function readXlsx(path: string): Record<string, unknown>[] {
  const wb = XLSX.readFile(path);
  const firstSheet = wb.Sheets[wb.SheetNames[0]];
  return XLSX.utils.sheet_to_json<Record<string, unknown>>(firstSheet, { defval: null });
}

/** SymMap marks deprecated rows with Suppress=1 (numeric or string). */
function isSuppressed(row: Record<string, unknown>): boolean {
  const s = row.Suppress;
  if (s === null || s === undefined) return false;
  if (typeof s === 'number') return s !== 0;
  if (typeof s === 'string') return s.trim() !== '' && s.trim() !== '0';
  return Boolean(s);
}

/** Coerce a cell to non-empty string or null (for TEXT columns). */
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s === '' ? null : s;
}

/** Coerce a cell to number or null (for REAL columns). */
function asReal(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string') {
    const s = v.trim();
    if (s === '') return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function loadHerbs(db: Database.Database, xlsxPath: string): LoadStats {
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_herbs (
      symmap_id TEXT PRIMARY KEY,
      chinese_name TEXT,
      pinyin_name TEXT,
      latin_name TEXT,
      english_name TEXT,
      properties_cn TEXT,
      properties_en TEXT,
      meridians_cn TEXT,
      meridians_en TEXT,
      class_cn TEXT,
      class_en TEXT,
      use_part TEXT,
      tcmid_id TEXT,
      tcmsp_id TEXT
    )
  `);
  const rows = readXlsx(xlsxPath);
  const stmt = db.prepare(`
    INSERT OR REPLACE INTO symmap_herbs (
      symmap_id, chinese_name, pinyin_name, latin_name, english_name,
      properties_cn, properties_en, meridians_cn, meridians_en,
      class_cn, class_en, use_part, tcmid_id, tcmsp_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  let suppressed = 0;
  let inserted = 0;
  const tx = db.transaction(() => {
    for (const r of rows) {
      if (isSuppressed(r)) { suppressed++; continue; }
      const id = asText(r.Herb_id);
      if (!id) continue;
      stmt.run(
        id,
        asText(r.Chinese_name),
        asText(r.Pinyin_name),
        asText(r.Latin_name),
        asText(r.English_name),
        asText(r.Properties_Chinese),
        asText(r.Properties_English),
        asText(r.Meridians_Chinese),
        asText(r.Meridians_English),
        asText(r.Class_Chinese),
        asText(r.Class_English),
        asText(r.UsePart),
        asText(r.TCMID_id),
        asText(r.TCMSP_id),
      );
      inserted++;
    }
  });
  tx();
  return { table: 'symmap_herbs', total: rows.length, suppressed, inserted };
}

function loadTcmSymptoms(db: Database.Database, xlsxPath: string): LoadStats {
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_tcm_symptoms (
      symmap_id TEXT PRIMARY KEY,
      name_cn TEXT,
      name_en TEXT,
      pinyin TEXT,
      definition TEXT,
      locus TEXT,
      property TEXT,
      symptom_type TEXT
    )
  `);
  const rows = readXlsx(xlsxPath);
  const stmt = db.prepare(`
    INSERT OR REPLACE INTO symmap_tcm_symptoms (
      symmap_id, name_cn, name_en, pinyin, definition, locus, property, symptom_type
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `);
  let suppressed = 0;
  let inserted = 0;
  const tx = db.transaction(() => {
    for (const r of rows) {
      if (isSuppressed(r)) { suppressed++; continue; }
      const id = asText(r.TCM_symptom_id);
      if (!id) continue;
      // SMTS sheet has no separate English name column — leave name_en null;
      // pinyin serves as the romanized identifier for non-CN consumers.
      stmt.run(
        id,
        asText(r.TCM_symptom_name),
        null,
        asText(r.Symptom_pinYin),
        asText(r.Symptom_definition),
        asText(r.Symptom_locus),
        asText(r.Symptom_property),
        asText(r.Type),
      );
      inserted++;
    }
  });
  tx();
  return { table: 'symmap_tcm_symptoms', total: rows.length, suppressed, inserted };
}

function loadModernSymptoms(db: Database.Database, xlsxPath: string): LoadStats {
  // SMMS schema (discovered in Phase B):
  //   MM_symptom_id, MM_symptom_name, MM_symptom_definition,
  //   UMLS_id (100% coverage), MeSH_tree_numbers, OMIM_id,
  //   ICD10CM_id (~35%), HPO_id, MeSH_id, Version, Suppress
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_modern_symptoms (
      symmap_id TEXT PRIMARY KEY,
      name TEXT,
      definition TEXT,
      umls_id TEXT,
      mesh_tree_numbers TEXT,
      mesh_id TEXT,
      omim_id TEXT,
      icd10cm_id TEXT,
      hpo_id TEXT
    )
  `);
  const rows = readXlsx(xlsxPath);
  const stmt = db.prepare(`
    INSERT OR REPLACE INTO symmap_modern_symptoms (
      symmap_id, name, definition, umls_id, mesh_tree_numbers, mesh_id,
      omim_id, icd10cm_id, hpo_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  let suppressed = 0;
  let inserted = 0;
  const tx = db.transaction(() => {
    for (const r of rows) {
      if (isSuppressed(r)) { suppressed++; continue; }
      const id = asText(r.MM_symptom_id);
      if (!id) continue;
      stmt.run(
        id,
        asText(r.MM_symptom_name),
        asText(r.MM_symptom_definition),
        asText(r.UMLS_id),
        asText(r.MeSH_tree_numbers),
        asText(r.MeSH_id),
        asText(r.OMIM_id),
        asText(r.ICD10CM_id),
        asText(r.HPO_id),
      );
      inserted++;
    }
  });
  tx();
  return { table: 'symmap_modern_symptoms', total: rows.length, suppressed, inserted };
}

function loadIngredients(db: Database.Database, xlsxPath: string): LoadStats {
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_ingredients (
      mol_id TEXT PRIMARY KEY,
      name TEXT,
      pubchem_cid TEXT,
      cas_id TEXT,
      formula TEXT,
      molecular_weight REAL,
      ob_score REAL,
      tcmid_id TEXT,
      tcmsp_id TEXT
    )
  `);
  const rows = readXlsx(xlsxPath);
  const stmt = db.prepare(`
    INSERT OR REPLACE INTO symmap_ingredients (
      mol_id, name, pubchem_cid, cas_id, formula,
      molecular_weight, ob_score, tcmid_id, tcmsp_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  let suppressed = 0;
  let inserted = 0;
  const tx = db.transaction(() => {
    for (const r of rows) {
      if (isSuppressed(r)) { suppressed++; continue; }
      const id = asText(r.Mol_id);
      if (!id) continue;
      stmt.run(
        id,
        asText(r.Molecule_name),
        asText(r.PubChem_CID),
        asText(r.CAS_id),
        asText(r.Molecule_formula),
        asReal(r.Molecule_weight),
        asReal(r.OB_score),
        asText(r.TCMID_id),
        asText(r.TCMSP_id),
      );
      inserted++;
    }
  });
  tx();
  return { table: 'symmap_ingredients', total: rows.length, suppressed, inserted };
}

function loadGenes(db: Database.Database, xlsxPath: string): LoadStats {
  db.exec(`
    CREATE TABLE IF NOT EXISTS symmap_genes (
      gene_id TEXT PRIMARY KEY,
      gene_symbol TEXT,
      gene_name TEXT,
      protein_name TEXT,
      uniprot_id TEXT,
      ensembl_id TEXT,
      hgnc_id TEXT,
      ncbi_id TEXT
    )
  `);
  const rows = readXlsx(xlsxPath);
  const stmt = db.prepare(`
    INSERT OR REPLACE INTO symmap_genes (
      gene_id, gene_symbol, gene_name, protein_name,
      uniprot_id, ensembl_id, hgnc_id, ncbi_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `);
  let suppressed = 0;
  let inserted = 0;
  const tx = db.transaction(() => {
    for (const r of rows) {
      if (isSuppressed(r)) { suppressed++; continue; }
      const id = asText(r.Gene_id);
      if (!id) continue;
      stmt.run(
        id,
        asText(r.Gene_symbol),
        asText(r.Gene_name),
        asText(r.Protein_name),
        asText(r.UniProt_id),
        asText(r.Ensembl_id),
        asText(r.HGNC_id),
        asText(r.NCBI_id),
      );
      inserted++;
    }
  });
  tx();
  return { table: 'symmap_genes', total: rows.length, suppressed, inserted };
}

function main(): void {
  const cfg = loadDataSources();
  const symmapDir = resolve(PKG_ROOT, cfg.symmap.out_dir);
  const dbPath = resolve(PKG_ROOT, cfg.paths.sqlite_db);

  if (!fs.existsSync(dbPath)) {
    process.stderr.write(`Database not found at ${dbPath}. Run 'make build' first.\n`);
    process.exit(1);
  }

  // Map filename → loader (matched by filename substring so the order in
  // data_sources.yaml.files is irrelevant).
  const loaders: Array<[string, (db: Database.Database, p: string) => LoadStats]> = [
    ['SMHB', loadHerbs],
    ['SMTS', loadTcmSymptoms],
    ['SMMS', loadModernSymptoms],
    ['SMIT', loadIngredients],
    ['SMTT', loadGenes],
  ];

  const db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  try {
    const stats: LoadStats[] = [];
    for (const [tag, loader] of loaders) {
      const file = cfg.symmap.files.find((f) => f.includes(tag));
      if (!file) {
        process.stderr.write(`No SymMap file matching tag '${tag}' in data_sources.yaml; skipping.\n`);
        continue;
      }
      const path = resolve(symmapDir, file);
      if (!fs.existsSync(path)) {
        process.stderr.write(`Missing XLSX: ${path}; skipping.\n`);
        continue;
      }
      process.stderr.write(`Loading ${tag} from ${file}...\n`);
      const s = loader(db, path);
      stats.push(s);
      process.stderr.write(`  -> ${s.table}: total=${s.total}, suppressed=${s.suppressed}, inserted=${s.inserted}\n`);
    }
    process.stderr.write('\n=== SymMap Load Summary ===\n');
    process.stderr.write(JSON.stringify(stats, null, 2) + '\n');
  } finally {
    db.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
