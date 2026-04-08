/**
 * Download Dr. Duke's Phytochemical CSV and FooDB CSV archives.
 *
 * Usage:
 *   tsx scripts/download-sources.ts
 *   tsx scripts/download-sources.ts --duke-only
 *   tsx scripts/download-sources.ts --foodb-only
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

  console.error('=== Downloading source data ===');

  if (!foodbOnly) {
    await downloadFile(SOURCES.duke);
  }
  if (!dukeOnly) {
    await downloadFile(SOURCES.foodb);
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
