/**
 * Audit the herbal_botanicals.db for data quality and coverage.
 *
 * Usage:
 *   tsx scripts/audit-herbal-data.ts
 */

import Database from 'better-sqlite3';
import * as path from 'path';
import * as fs from 'fs';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');

// Top-50 herbal supplements to validate (scientific names for matching)
const TOP_HERBS: Array<{ common: string; scientific: string }> = [
  { common: 'Ashwagandha', scientific: 'Withania somnifera' },
  { common: 'Turmeric', scientific: 'Curcuma longa' },
  { common: 'Ginseng (Asian)', scientific: 'Panax ginseng' },
  { common: 'Echinacea', scientific: 'Echinacea' },
  { common: 'Ginkgo', scientific: 'Ginkgo biloba' },
  { common: "St. John's Wort", scientific: 'Hypericum perforatum' },
  { common: 'Valerian', scientific: 'Valeriana officinalis' },
  { common: 'Chamomile', scientific: 'Matricaria' },
  { common: 'Milk Thistle', scientific: 'Silybum marianum' },
  { common: 'Garlic', scientific: 'Allium sativum' },
  { common: 'Ginger', scientific: 'Zingiber officinale' },
  { common: 'Black Cohosh', scientific: 'Actaea racemosa' },
  { common: 'Saw Palmetto', scientific: 'Serenoa repens' },
  { common: 'Green Tea', scientific: 'Camellia sinensis' },
  { common: 'Aloe Vera', scientific: 'Aloe vera' },
  { common: 'Lavender', scientific: 'Lavandula' },
  { common: 'Peppermint', scientific: 'Mentha piperita' },
  { common: 'Rosemary', scientific: 'Rosmarinus officinalis' },
  { common: 'Cinnamon', scientific: 'Cinnamomum' },
  { common: 'Licorice', scientific: 'Glycyrrhiza glabra' },
  { common: 'Elderberry', scientific: 'Sambucus nigra' },
  { common: 'Neem', scientific: 'Azadirachta indica' },
  { common: 'Moringa', scientific: 'Moringa oleifera' },
  { common: 'Holy Basil', scientific: 'Ocimum' },
  { common: 'Rhodiola', scientific: 'Rhodiola rosea' },
];

function main(): void {
  if (!fs.existsSync(DB_PATH)) {
    console.error(`Database not found at ${DB_PATH}`);
    process.exit(1);
  }

  const db = new Database(DB_PATH, { readonly: true });

  // Table counts
  const herbs = (db.prepare('SELECT COUNT(*) as cnt FROM herbs').get() as { cnt: number }).cnt;
  const compounds = (db.prepare('SELECT COUNT(*) as cnt FROM compounds').get() as { cnt: number }).cnt;
  const herbCompounds = (db.prepare('SELECT COUNT(*) as cnt FROM herb_compounds').get() as { cnt: number }).cnt;
  const compoundFoods = (db.prepare('SELECT COUNT(*) as cnt FROM compound_foods').get() as { cnt: number }).cnt;
  const bridgeCompounds = (db.prepare(`
    SELECT COUNT(DISTINCT c.id) as cnt FROM compounds c
    WHERE EXISTS (SELECT 1 FROM herb_compounds hc WHERE hc.compound_id = c.id)
      AND EXISTS (SELECT 1 FROM compound_foods cf WHERE cf.compound_id = c.id)
  `).get() as { cnt: number }).cnt;

  const herbsWithCompounds = (db.prepare(`
    SELECT COUNT(DISTINCT herb_id) as cnt FROM herb_compounds
  `).get() as { cnt: number }).cnt;
  const herbsWithNames = (db.prepare(`
    SELECT COUNT(*) as cnt FROM herbs WHERE common_name IS NOT NULL
  `).get() as { cnt: number }).cnt;
  const compoundsWithBio = (db.prepare(`
    SELECT COUNT(*) as cnt FROM compounds WHERE bioactivities != '[]' AND bioactivities IS NOT NULL
  `).get() as { cnt: number }).cnt;
  const compoundsWithClass = (db.prepare(`
    SELECT COUNT(*) as cnt FROM compounds WHERE compound_class IS NOT NULL AND compound_class != ''
  `).get() as { cnt: number }).cnt;

  console.log('# Herbal Botanicals Database Audit\n');
  console.log('## Table Counts\n');
  console.log('| Table | Rows |');
  console.log('|-------|------|');
  console.log(`| herbs | ${herbs.toLocaleString()} |`);
  console.log(`| compounds | ${compounds.toLocaleString()} |`);
  console.log(`| herb_compounds | ${herbCompounds.toLocaleString()} |`);
  console.log(`| compound_foods | ${compoundFoods.toLocaleString()} |`);
  console.log(`| bridge compounds | ${bridgeCompounds.toLocaleString()} |`);

  console.log('\n## Data Quality\n');
  console.log('| Metric | Value |');
  console.log('|--------|-------|');
  console.log(`| Herbs with compounds | ${herbsWithCompounds} / ${herbs} (${((herbsWithCompounds / herbs) * 100).toFixed(1)}%) |`);
  console.log(`| Herbs with common names | ${herbsWithNames} / ${herbs} (${((herbsWithNames / herbs) * 100).toFixed(1)}%) |`);
  console.log(`| Compounds with bioactivities | ${compoundsWithBio} / ${compounds} (${((compoundsWithBio / compounds) * 100).toFixed(1)}%) |`);
  console.log(`| Compounds with class | ${compoundsWithClass} / ${compounds} (${((compoundsWithClass / compounds) * 100).toFixed(1)}%) |`);

  // Top 10 herbs by compound count
  console.log('\n## Top 10 Herbs by Compound Count\n');
  console.log('| Herb | Scientific Name | Compounds |');
  console.log('|------|----------------|-----------|');
  const topHerbs = db.prepare(`
    SELECT h.common_name, h.scientific_name, COUNT(DISTINCT hc.compound_id) as cnt
    FROM herbs h
    JOIN herb_compounds hc ON h.id = hc.herb_id
    GROUP BY h.id
    ORDER BY cnt DESC
    LIMIT 10
  `).all() as Array<{ common_name: string | null; scientific_name: string; cnt: number }>;
  for (const h of topHerbs) {
    console.log(`| ${h.common_name || '-'} | ${h.scientific_name} | ${h.cnt} |`);
  }

  // Top 10 compounds by herb count
  console.log('\n## Top 10 Compounds by Herb Count\n');
  console.log('| Compound | Class | Herbs | Bioactivities |');
  console.log('|----------|-------|-------|---------------|');
  const topCompounds = db.prepare(`
    SELECT c.name, c.compound_class, COUNT(DISTINCT hc.herb_id) as herb_cnt,
      json_array_length(c.bioactivities) as bio_cnt
    FROM compounds c
    JOIN herb_compounds hc ON c.id = hc.compound_id
    GROUP BY c.id
    ORDER BY herb_cnt DESC
    LIMIT 10
  `).all() as Array<{ name: string; compound_class: string | null; herb_cnt: number; bio_cnt: number }>;
  for (const c of topCompounds) {
    console.log(`| ${c.name} | ${c.compound_class || '-'} | ${c.herb_cnt} | ${c.bio_cnt} |`);
  }

  // Top herb validation
  console.log('\n## Top-25 Herbal Supplement Coverage\n');
  console.log('| Herb | Found | Compounds | Food Matches |');
  console.log('|------|-------|-----------|--------------|');

  let foundCount = 0;
  for (const target of TOP_HERBS) {
    const herb = db.prepare(`
      SELECT h.id, h.common_name, h.scientific_name
      FROM herbs h
      WHERE h.scientific_name LIKE ?
      LIMIT 1
    `).get(`%${target.scientific}%`) as { id: string; common_name: string | null; scientific_name: string } | undefined;

    if (herb) {
      foundCount++;
      const compoundCount = (db.prepare(`
        SELECT COUNT(DISTINCT compound_id) as cnt FROM herb_compounds WHERE herb_id = ?
      `).get(herb.id) as { cnt: number }).cnt;
      const foodCount = (db.prepare(`
        SELECT COUNT(DISTINCT cf.food_name) as cnt
        FROM herb_compounds hc
        JOIN compound_foods cf ON hc.compound_id = cf.compound_id
        WHERE hc.herb_id = ?
      `).get(herb.id) as { cnt: number }).cnt;
      console.log(`| ${target.common} | yes | ${compoundCount} | ${foodCount} |`);
    } else {
      console.log(`| ${target.common} | **NO** | - | - |`);
    }
  }

  console.log(`\n**Coverage: ${foundCount}/${TOP_HERBS.length} top herbs found (${((foundCount / TOP_HERBS.length) * 100).toFixed(0)}%)**\n`);

  db.close();
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

export { main as auditHerbalData };
