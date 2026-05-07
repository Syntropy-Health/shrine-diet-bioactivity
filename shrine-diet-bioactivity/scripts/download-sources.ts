/**
 * Download Dr. Duke's Phytochemical CSV and FooDB CSV archives.
 *
 * Usage:
 *   tsx scripts/download-sources.ts
 *   tsx scripts/download-sources.ts --duke-only
 *   tsx scripts/download-sources.ts --foodb-only
 *   tsx scripts/download-sources.ts --cmaup-only
 *   tsx scripts/download-sources.ts --ttd-only
 *   tsx scripts/download-sources.ts --ctd-only
 */

import * as fs from 'fs';
import * as path from 'path';
import { pipeline } from 'stream/promises';
import { Readable } from 'stream';

const DATA_DIR = path.join(process.cwd(), 'data');

interface DownloadTarget {
  url: string;
  filename: string;
  description: string;
  expectedMinSize: number; // bytes — sanity check
}

const SOURCES: Record<string, DownloadTarget> = {
  duke: {
    url: 'https://ndownloader.figshare.com/files/43363335',
    filename: 'duke-source-csv.zip',
    description: "Dr. Duke's Phytochemical DB (CSV)",
    expectedMinSize: 1_000_000, // ~5.8 MB
  },
  foodb: {
    url: 'https://foodb.ca/public/system/downloads/foodb_2020_4_7_csv.tar.gz',
    filename: 'foodb-csv.tar.gz',
    description: 'FooDB Compound-Food CSV (2020)',
    expectedMinSize: 100_000_000, // ~952 MB
  },
  cmaup_plants: {
    url: 'https://bidd.group/CMAUP/downloadFiles/CMAUPv2.0_download_Plants.txt',
    filename: 'cmaup-plants.txt',
    description: 'CMAUP v2.0 Plants',
    expectedMinSize: 100_000,
  },
  cmaup_targets: {
    url: 'https://bidd.group/CMAUP/downloadFiles/CMAUPv2.0_download_Targets.txt',
    filename: 'cmaup-targets.txt',
    description: 'CMAUP v2.0 Targets',
    expectedMinSize: 10_000,
  },
  cmaup_ingredients: {
    url: 'https://bidd.group/CMAUP/downloadFiles/CMAUPv2.0_download_Ingredients_All.txt',
    filename: 'cmaup-ingredients.txt',
    description: 'CMAUP v2.0 All Ingredients',
    expectedMinSize: 1_000_000,
  },
  cmaup_ingredient_targets: {
    url: 'https://bidd.group/CMAUP/downloadFiles/CMAUPv2.0_download_Ingredient_Target_Associations_ActivityValues_References.txt',
    filename: 'cmaup-ingredient-targets.txt',
    description: 'CMAUP v2.0 Ingredient-Target Associations',
    expectedMinSize: 1_000_000,
  },
  cmaup_plant_diseases: {
    url: 'https://bidd.group/CMAUP/downloadFiles/CMAUPv2.0_download_Plant_Human_Disease_Associations.txt',
    filename: 'cmaup-plant-diseases.txt',
    description: 'CMAUP v2.0 Plant-Disease Associations',
    expectedMinSize: 10_000,
  },
  ttd_targets: {
    url: 'https://ttd.idrblab.cn/files/download/P1-01-TTD_target_download.txt',
    filename: 'ttd-targets.txt',
    description: 'TTD Targets with Druggability',
    expectedMinSize: 100_000,
  },
  ttd_drug_disease: {
    url: 'https://ttd.idrblab.cn/files/download/P1-05-Drug_disease.txt',
    filename: 'ttd-drug-disease.txt',
    description: 'TTD Drug-Disease Associations',
    expectedMinSize: 100_000,
  },
  // CTD: the website's downloads page is CAPTCHA-gated, but the static
  // file URLs under /reports/ are not. ~50 MB and ~30 MB respectively.
  ctd_chemicals_diseases: {
    url: 'https://ctdbase.org/reports/CTD_chemicals_diseases.csv.gz',
    filename: 'CTD_chemicals_diseases.csv.gz',
    description: 'CTD Chemical-Disease Associations (gzipped CSV)',
    expectedMinSize: 30_000_000,
  },
  ctd_pheno_term_ixns: {
    url: 'https://ctdbase.org/reports/CTD_pheno_term_ixns.csv.gz',
    filename: 'CTD_pheno_term_ixns.csv.gz',
    description: 'CTD Chemical-Phenotype Interactions (gzipped CSV)',
    expectedMinSize: 5_000_000,
  },
};

async function downloadFile(target: DownloadTarget): Promise<void> {
  const destPath = path.join(DATA_DIR, target.filename);

  if (fs.existsSync(destPath)) {
    const stat = fs.statSync(destPath);
    if (stat.size >= target.expectedMinSize) {
      console.error(`  Skip: ${target.filename} already exists (${(stat.size / 1_048_576).toFixed(1)} MB)`);
      return;
    }
    console.error(`  Removing incomplete ${target.filename} (${stat.size} bytes)`);
    fs.unlinkSync(destPath);
  }

  console.error(`  Downloading ${target.description}...`);
  console.error(`  URL: ${target.url}`);

  const response = await fetch(target.url, { redirect: 'follow' });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} downloading ${target.url}`);
  }
  if (!response.body) {
    throw new Error('No response body');
  }

  const contentLength = response.headers.get('content-length');
  const totalBytes = contentLength ? parseInt(contentLength, 10) : 0;

  const tmpPath = destPath + '.tmp';
  const writeStream = fs.createWriteStream(tmpPath);

  let downloaded = 0;
  let lastReport = 0;
  const reader = response.body.getReader();
  const nodeStream = new Readable({
    async read() {
      const { done, value } = await reader.read();
      if (done) {
        this.push(null);
        return;
      }
      downloaded += value.length;
      if (totalBytes > 0 && downloaded - lastReport > 10_000_000) {
        const pct = ((downloaded / totalBytes) * 100).toFixed(1);
        console.error(`  Progress: ${(downloaded / 1_048_576).toFixed(1)} / ${(totalBytes / 1_048_576).toFixed(1)} MB (${pct}%)`);
        lastReport = downloaded;
      }
      this.push(value);
    },
  });

  await pipeline(nodeStream, writeStream);
  fs.renameSync(tmpPath, destPath);

  const finalSize = fs.statSync(destPath).size;
  console.error(`  Done: ${target.filename} (${(finalSize / 1_048_576).toFixed(1)} MB)`);
}

async function main(): Promise<void> {
  fs.mkdirSync(DATA_DIR, { recursive: true });

  const args = process.argv.slice(2);
  const dukeOnly = args.includes('--duke-only');
  const foodbOnly = args.includes('--foodb-only');
  const cmaupOnly = args.includes('--cmaup-only');
  const ttdOnly = args.includes('--ttd-only');
  const ctdOnly = args.includes('--ctd-only');

  console.error('=== Downloading source data ===');

  // Determine which sources to download
  const keysToDownload: string[] = [];
  if (dukeOnly) keysToDownload.push('duke');
  else if (foodbOnly) keysToDownload.push('foodb');
  else if (cmaupOnly) keysToDownload.push(...Object.keys(SOURCES).filter(k => k.startsWith('cmaup')));
  else if (ttdOnly) keysToDownload.push(...Object.keys(SOURCES).filter(k => k.startsWith('ttd')));
  else if (ctdOnly) keysToDownload.push(...Object.keys(SOURCES).filter(k => k.startsWith('ctd')));
  else keysToDownload.push(...Object.keys(SOURCES));

  for (const key of keysToDownload) {
    await downloadFile(SOURCES[key]);
  }

  console.error('=== Downloads complete ===');
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error('Download failed:', err);
    process.exit(1);
  });
}

export { main as downloadSources };
