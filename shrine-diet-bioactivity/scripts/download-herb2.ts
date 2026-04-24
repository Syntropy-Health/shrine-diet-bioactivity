/**
 * download-herb2.ts
 *
 * Downloads HERB 2.0 herb data via the chedi JSON-RPC API.
 *
 * Background: herb.ac.cn/static/download/*.txt returns the SPA HTML shell for all
 * paths (the download feature is disabled:true in the UI). The actual data is
 * served via POST /chedi/api/ using browse_api (herbs list) and detail_api
 * (per-herb disease associations). This script fetches and caches both as JSON
 * under data/herb2/ so the loader can run offline.
 *
 * Usage:
 *   npx tsx scripts/download-herb2.ts
 *   make download-herb2
 *
 * Output:
 *   data/herb2/herbs.json         — array of all 7263+ herb rows
 *   data/herb2/herb_details.json  — map of herb_id → {herb_disease, drug_paper_disease}
 */

import { mkdirSync, writeFileSync, existsSync, readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadDataSources } from '../src/config.js';

const _dir = typeof __dirname !== 'undefined'
  ? __dirname
  : dirname(fileURLToPath(import.meta.url));

const cfg = loadDataSources();
const API_URL = cfg.herb2.base_url; // http://herb.ac.cn/chedi/api/
const OUT_DIR = resolve(_dir, '..', cfg.herb2.out_dir);
const PAGE_SIZE = 100;
const CONCURRENT = 5; // parallel detail_api requests
const REQUEST_DELAY_MS = 100; // polite delay between batch requests

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

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function post(funcName: string, body: Record<string, unknown>): Promise<unknown> {
  const payload = JSON.stringify({ func_name: funcName, ...body });
  const res = await fetch(API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} for func_name=${funcName}`);
  }
  const text = await res.text();
  if (!text || text.startsWith('<')) {
    throw new Error(`Non-JSON response for func_name=${funcName}: ${text.slice(0, 100)}`);
  }
  return JSON.parse(text);
}

function parseHerbRow(row: unknown[]): HerbRow {
  const idCell = row[0] as { title?: string } | string;
  const herb_id = typeof idCell === 'object' && idCell !== null ? idCell.title ?? '' : String(idCell);
  const pinyin = String(row[1] ?? '').trim();
  const name_cn = String(row[2] ?? '').trim();
  const name_en = String(row[3] ?? '').trim();
  const latinCell = row[4] as { title?: string } | string;
  const latin = typeof latinCell === 'object' && latinCell !== null ? latinCell.title ?? '' : String(latinCell ?? '').trim();
  return { herb_id, pinyin, name_cn, name_en, latin };
}

async function fetchAllHerbs(): Promise<HerbRow[]> {
  console.log('Fetching herb list via browse_api ...');
  const herbs: HerbRow[] = [];
  let page = 1;
  let totalNum = 0;

  while (true) {
    const data = (await post('browse_api', { label: 'Herb', page, page_size: PAGE_SIZE })) as {
      total_num: number;
      browse_data: unknown[][];
    };
    if (!data || !data.browse_data) break;
    if (page === 1) {
      totalNum = data.total_num;
      console.log(`Total herbs: ${totalNum}`);
    }
    const rows = data.browse_data.slice(1); // skip header row
    for (const row of rows) {
      herbs.push(parseHerbRow(row as unknown[]));
    }
    console.log(`  page ${page}: fetched ${rows.length} herbs (${herbs.length}/${totalNum})`);
    if (herbs.length >= totalNum) break;
    page += 1;
    await delay(REQUEST_DELAY_MS);
  }
  return herbs;
}

async function fetchHerbDetail(herbId: string): Promise<HerbDetail> {
  const data = (await post('detail_api', {
    v: herbId,
    label: 'Herb',
    key_id: herbId,
  })) as {
    herb_disease?: unknown[][];
    drug_paper_disease?: unknown[][];
  };
  if (!data) return { herb_disease: [], drug_paper_disease: [] };

  const experimentalRows: DiseaseRow[] = [];
  const clinicalRows: DiseaseRow[] = [];

  // herb_disease: ['Disease id', 'Disease name', 'P-value', 'FDR_BH']
  const hd = data.herb_disease ?? [];
  for (const row of hd.slice(1)) {
    const r = row as unknown[];
    const idCell = r[0] as { title?: string } | string;
    const disease_id = typeof idCell === 'object' && idCell !== null ? idCell.title ?? '' : String(idCell);
    const disease_name = String(r[1] ?? '').trim();
    const pvalue = String(r[2] ?? '').trim() || null;
    experimentalRows.push({ disease_id, disease_name, pvalue, pmid: null, tier: 'experimental' });
  }

  // drug_paper_disease: ['Paper id', 'Disease id', 'Disease name', 'PubMed id']
  const dpd = data.drug_paper_disease ?? [];
  for (const row of dpd.slice(1)) {
    const r = row as unknown[];
    const diseaseCell = r[1] as { title?: string } | string;
    const disease_id = typeof diseaseCell === 'object' && diseaseCell !== null ? diseaseCell.title ?? '' : String(diseaseCell);
    const disease_name = String(r[2] ?? '').trim();
    const pmidCell = r[3] as { title?: string } | string;
    const pmid = typeof pmidCell === 'object' && pmidCell !== null ? pmidCell.title ?? null : String(pmidCell ?? '') || null;
    clinicalRows.push({ disease_id, disease_name, pvalue: null, pmid, tier: 'clinical' });
  }

  return { herb_disease: experimentalRows, drug_paper_disease: clinicalRows };
}

async function fetchDetailsWithConcurrency(
  herbIds: string[],
  concurrency: number,
): Promise<Map<string, HerbDetail>> {
  const results = new Map<string, HerbDetail>();
  let idx = 0;
  let done = 0;

  async function worker(): Promise<void> {
    while (idx < herbIds.length) {
      const herbId = herbIds[idx++];
      try {
        const detail = await fetchHerbDetail(herbId);
        results.set(herbId, detail);
      } catch (err) {
        console.warn(`  WARN: failed to fetch detail for ${herbId}: ${(err as Error).message}`);
        results.set(herbId, { herb_disease: [], drug_paper_disease: [] });
      }
      done += 1;
      if (done % 100 === 0) {
        console.log(`  detail progress: ${done}/${herbIds.length}`);
        await delay(REQUEST_DELAY_MS);
      }
    }
  }

  const workers = Array.from({ length: concurrency }, () => worker());
  await Promise.all(workers);
  return results;
}

async function main(): Promise<void> {
  mkdirSync(OUT_DIR, { recursive: true });

  // Step 1: fetch herb list (cached if exists)
  const herbsFile = `${OUT_DIR}/herbs.json`;
  let herbs: HerbRow[];

  if (existsSync(herbsFile)) {
    console.log(`Loading cached herbs from ${herbsFile}`);
    herbs = JSON.parse(readFileSync(herbsFile, 'utf8')) as HerbRow[];
    console.log(`  ${herbs.length} herbs loaded from cache`);
  } else {
    herbs = await fetchAllHerbs();
    writeFileSync(herbsFile, JSON.stringify(herbs, null, 2), 'utf8');
    console.log(`Saved ${herbs.length} herbs → ${herbsFile}`);
  }

  // Step 2: fetch herb details (cached if exists)
  const detailsFile = `${OUT_DIR}/herb_details.json`;
  let details: Record<string, HerbDetail>;

  if (existsSync(detailsFile)) {
    console.log(`Loading cached details from ${detailsFile}`);
    details = JSON.parse(readFileSync(detailsFile, 'utf8')) as Record<string, HerbDetail>;
    console.log(`  ${Object.keys(details).length} herb details loaded from cache`);
  } else {
    console.log(`Fetching detail for ${herbs.length} herbs (concurrency=${CONCURRENT}) ...`);
    const herbIds = herbs.map((h) => h.herb_id).filter(Boolean);
    const detailMap = await fetchDetailsWithConcurrency(herbIds, CONCURRENT);
    details = Object.fromEntries(detailMap);
    writeFileSync(detailsFile, JSON.stringify(details, null, 2), 'utf8');
    console.log(`Saved details for ${Object.keys(details).length} herbs → ${detailsFile}`);
  }

  // Summary
  let clinicalCount = 0;
  let experimentalCount = 0;
  for (const d of Object.values(details)) {
    clinicalCount += d.drug_paper_disease.length;
    experimentalCount += d.herb_disease.length;
  }
  console.log(`\nSummary:`);
  console.log(`  Herbs: ${herbs.length}`);
  console.log(`  Clinical disease associations (paper-based): ${clinicalCount}`);
  console.log(`  Experimental disease associations (p-value-based): ${experimentalCount}`);
  console.log('\nDone.');
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});
