import { mkdirSync, createWriteStream } from 'fs';
import { get } from 'http';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadDataSources } from '../src/config';

// ESM-compatible __dirname
const _dir = typeof __dirname !== 'undefined'
  ? __dirname
  : dirname(fileURLToPath(import.meta.url));

async function download(url: string, dest: string): Promise<void> {
  return new Promise((resolveP, reject) => {
    const file = createWriteStream(dest);
    get(url, (res) => {
      if (res.statusCode !== 200) {
        file.close();
        reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        return;
      }
      res.pipe(file);
      file.on('finish', () => file.close(() => resolveP()));
    }).on('error', (err) => {
      file.close();
      reject(err);
    });
  });
}

async function main(): Promise<void> {
  const cfg = loadDataSources().symmap;
  // Resolve out_dir relative to the shrine-diet-bioactivity package root
  const pkgRoot = resolve(_dir, '..');
  const outDir = resolve(pkgRoot, cfg.out_dir);
  mkdirSync(outDir, { recursive: true });

  for (const f of cfg.files) {
    // URL-encode the filename (spaces → %20, commas → %2C, etc.)
    const encodedFile = encodeURIComponent(f);
    const url = cfg.base_url + encodedFile;
    const dest = resolve(outDir, f);
    console.log(`fetching ${url}`);
    await download(url, dest);
    console.log(`  saved ${dest}`);
  }
  console.log('done');
}

main().catch((e) => { console.error(e); process.exit(1); });
