/**
 * Extract Dr. Duke's ZIP and FooDB tar.gz into data_local_temp/.
 *
 * Usage:
 *   tsx scripts/decompress-datasets.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import { createWriteStream } from 'fs';
import { pipeline } from 'stream/promises';
import { execSync } from 'child_process';
import * as yauzl from 'yauzl';

const DATA_DIR = path.join(process.cwd(), 'data');
const TEMP_DIR = path.join(process.cwd(), 'data_local_temp');
const DUKE_ZIP = path.join(DATA_DIR, 'duke-source-csv.zip');
const FOODB_TAR = path.join(DATA_DIR, 'foodb-csv.tar.gz');

async function decompressDukeZip(): Promise<void> {
  const outputDir = path.join(TEMP_DIR, 'duke');
  fs.mkdirSync(outputDir, { recursive: true });

  if (!fs.existsSync(DUKE_ZIP)) {
    throw new Error(`Duke ZIP not found at ${DUKE_ZIP}. Run 'npm run download-data' first.`);
  }

  console.error("Extracting Dr. Duke's CSV...");

  return new Promise<void>((resolve, reject) => {
    yauzl.open(DUKE_ZIP, { lazyEntries: true }, (err, zipfile) => {
      if (err) { reject(err); return; }
      if (!zipfile) { reject(new Error('Failed to open zip file')); return; }

      let fileCount = 0;
      zipfile.readEntry();

      zipfile.on('entry', (entry) => {
        if (/\/$/.test(entry.fileName)) {
          zipfile.readEntry();
        } else {
          // Flatten: extract just the filename, not subdirectory paths
          const basename = path.basename(entry.fileName);
          const outputPath = path.join(outputDir, basename);

          zipfile.openReadStream(entry, (err, readStream) => {
            if (err) { reject(err); return; }
            if (!readStream) { reject(new Error('Failed to open read stream')); return; }

            const writeStream = createWriteStream(outputPath);
            pipeline(readStream, writeStream)
              .then(() => {
                fileCount++;
                zipfile.readEntry();
              })
              .catch(reject);
          });
        }
      });

      zipfile.on('end', () => {
        console.error(`  Extracted ${fileCount} files to data_local_temp/duke/`);
        resolve();
      });

      zipfile.on('error', reject);
    });
  });
}

function decompressFoodbTar(): void {
  const outputDir = path.join(TEMP_DIR, 'foodb');
  fs.mkdirSync(outputDir, { recursive: true });

  if (!fs.existsSync(FOODB_TAR)) {
    console.error('  FooDB tar.gz not found — skipping FooDB extraction.');
    console.error(`  To include FooDB data, run: npm run download-data`);
    return;
  }

  console.error('Extracting FooDB CSV...');
  // Try gzipped first, fall back to plain tar
  const isGzip = fs.readFileSync(FOODB_TAR, { encoding: null }).subarray(0, 2).toString('hex') === '1f8b';
  const tarFlag = isGzip ? '-xzf' : '-xf';
  execSync(`tar ${tarFlag} "${FOODB_TAR}" -C "${outputDir}" --strip-components=1`, {
    stdio: 'inherit',
  });

  const files = fs.readdirSync(outputDir).filter((f) => f.endsWith('.csv'));
  console.error(`  Extracted ${files.length} CSV files to data_local_temp/foodb/`);
}

async function main(): Promise<void> {
  fs.mkdirSync(TEMP_DIR, { recursive: true });
  await decompressDukeZip();
  decompressFoodbTar();
  console.error('=== Decompression complete ===');
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error('Decompression failed:', err);
    process.exit(1);
  });
}

export { main as decompressDatasets };
