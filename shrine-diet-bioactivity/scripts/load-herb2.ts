/**
 * load-herb2.ts
 *
 * Loads HERB 2.0 cached JSON data into SQLite (herbal_botanicals.db).
 *
 * Evidence tier classification:
 *   - drug_paper_disease (PMID-backed literature references) → evidence_tier = 'clinical'
 *   - herb_disease (computational p-value associations from GEO experiments) → evidence_tier = 'experimental'
 *
 * Tables created/populated:
 *   herb2_herbs       — 7,263+ herbs with bilingual CN/EN names + pinyin + latin
 *   herb2_herb_disease — herb↔disease links with evidence_tier + optional PMID
 *
 * Usage:
 *   npx tsx scripts/load-herb2.ts
 *   make load-herb2
 *
 * Prerequisites:
 *   make download-herb2   (populates data/herb2/herbs.json + herb_details.json)
 */

import Database from 'better-sqlite3';
import { readFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadDataSources } from '../src/config.js';

const _dir = typeof __dirname !== 'undefined'
  ? __dirname
  : dirname(fileURLToPath(import.meta.url));

const cfg = loadDataSources();
const DATA_DIR = resolve(_dir, '..', cfg.herb2.out_dir);
const DB_PATH = resolve(_dir, '..', cfg.paths.sqlite_db);

type HerbRow = {
  herb_id: string;
  pinyin: string;
  name_cn: string;
  name_en: string;
  latin: string;
};

type DiseaseRow = {
  disease_id: string;
  disease_name: string;
  pvalue: string | null;
  pmid: string | null;
  tier: 'clinical' | 'experimental';
};

type HerbDetail = {
  herb_disease: DiseaseRow[];
  drug_paper_disease: DiseaseRow[];
};

function createSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS herb2_herbs (
      herb_id    TEXT PRIMARY KEY,
      name_en    TEXT,
      name_cn    TEXT,
      pinyin     TEXT,
      latin      TEXT
    );

    CREATE TABLE IF NOT EXISTS herb2_herb_disease (
      herb_id        TEXT NOT NULL,
      disease_id     TEXT NOT NULL,
      disease_label  TEXT NOT NULL,
      evidence_tier  TEXT NOT NULL CHECK (evidence_tier IN ('clinical','experimental','traditional')),
      source_pmid    TEXT,
      PRIMARY KEY (herb_id, disease_id, evidence_tier)
    );
  `);
}

function loadHerbs(db: Database.Database, herbs: HerbRow[]): number {
  const stmt = db.prepare(
    'INSERT OR REPLACE INTO herb2_herbs (herb_id, name_en, name_cn, pinyin, latin) VALUES (?, ?, ?, ?, ?)',
  );
  const tx = db.transaction((rows: HerbRow[]) => {
    let count = 0;
    for (const h of rows) {
      if (!h.herb_id) continue;
      stmt.run(
        h.herb_id,
        h.name_en || null,
        h.name_cn || null,
        h.pinyin || null,
        h.latin || null,
      );
      count += 1;
    }
    return count;
  });
  return tx(herbs) as number;
}

function loadDiseaseRelationships(
  db: Database.Database,
  details: Record<string, HerbDetail>,
): { clinical: number; experimental: number } {
  const stmt = db.prepare(
    `INSERT OR IGNORE INTO herb2_herb_disease
     (herb_id, disease_id, disease_label, evidence_tier, source_pmid)
     VALUES (?, ?, ?, ?, ?)`,
  );

  let clinical = 0;
  let experimental = 0;

  const tx = db.transaction((entries: [string, HerbDetail][]) => {
    for (const [herbId, detail] of entries) {
      // Paper-backed (clinical) associations
      for (const d of detail.drug_paper_disease) {
        if (!d.disease_id && !d.disease_name) continue;
        stmt.run(herbId, d.disease_id || d.disease_name, d.disease_name, 'clinical', d.pmid ?? null);
        clinical += 1;
      }
      // Computational/experimental associations (GEO experiment p-values)
      for (const d of detail.herb_disease) {
        if (!d.disease_id && !d.disease_name) continue;
        stmt.run(herbId, d.disease_id || d.disease_name, d.disease_name, 'experimental', null);
        experimental += 1;
      }
    }
  });

  tx(Object.entries(details));
  return { clinical, experimental };
}

function main(): void {
  const herbsFile = `${DATA_DIR}/herbs.json`;
  const detailsFile = `${DATA_DIR}/herb_details.json`;

  if (!existsSync(herbsFile)) {
    console.error(`Missing: ${herbsFile}`);
    console.error('Run: make download-herb2');
    process.exit(1);
  }
  if (!existsSync(detailsFile)) {
    console.error(`Missing: ${detailsFile}`);
    console.error('Run: make download-herb2');
    process.exit(1);
  }

  console.log(`Loading herbs from ${herbsFile}`);
  const herbs = JSON.parse(readFileSync(herbsFile, 'utf8')) as HerbRow[];
  console.log(`  ${herbs.length} herbs`);

  console.log(`Loading details from ${detailsFile}`);
  const details = JSON.parse(readFileSync(detailsFile, 'utf8')) as Record<string, HerbDetail>;
  console.log(`  ${Object.keys(details).length} herb detail records`);

  const db = new Database(DB_PATH);
  try {
    createSchema(db);
    console.log('Schema created/verified');

    const herbCount = loadHerbs(db, herbs);
    console.log(`Inserted/replaced ${herbCount} rows in herb2_herbs`);

    const { clinical, experimental } = loadDiseaseRelationships(db, details);
    console.log(`Inserted ${clinical} clinical + ${experimental} experimental rows in herb2_herb_disease`);

    // Verification query
    const herbCn = db
      .prepare('SELECT COUNT(*) AS c FROM herb2_herbs WHERE name_cn IS NOT NULL')
      .get() as { c: number };
    const totalDiseaseLinks = db
      .prepare('SELECT COUNT(*) AS c FROM herb2_herb_disease')
      .get() as { c: number };
    const tierBreakdown = db
      .prepare('SELECT evidence_tier, COUNT(*) AS c FROM herb2_herb_disease GROUP BY evidence_tier')
      .all() as Array<{ evidence_tier: string; c: number }>;

    console.log('\n=== Load Summary ===');
    console.log(`  herb2_herbs with name_cn: ${herbCn.c}`);
    console.log(`  herb2_herb_disease total: ${totalDiseaseLinks.c}`);
    for (const row of tierBreakdown) {
      console.log(`    ${row.evidence_tier}: ${row.c}`);
    }
    console.log('\nHERB 2.0 loaded successfully.');
  } finally {
    db.close();
  }
}

main();
