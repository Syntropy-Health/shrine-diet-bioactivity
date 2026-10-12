import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { describe, expect, it } from 'vitest';

import { collectDetails, writeJsonAtomic } from '../herb2-download.js';

// #125 review R5: the HERB download skips any existing output file and CI caches
// it, so a present-but-incomplete file is reused as complete forever.

describe('writeJsonAtomic', () => {
  it('writes the full value and leaves no temp file', () => {
    const dir = mkdtempSync(join(tmpdir(), 'herb2-'));
    const path = join(dir, 'herb_details.json');
    writeJsonAtomic(path, { H1: { herb_disease: [], drug_paper_disease: [] } });
    expect(JSON.parse(readFileSync(path, 'utf8'))).toHaveProperty('H1');
    expect(readdirSync(dir)).toEqual(['herb_details.json']);
  });

  it('replaces an existing file whole (never appends or truncates in place)', () => {
    const dir = mkdtempSync(join(tmpdir(), 'herb2-'));
    const path = join(dir, 'herbs.json');
    writeFileSync(path, 'x'.repeat(10_000));
    writeJsonAtomic(path, [1, 2]);
    expect(JSON.parse(readFileSync(path, 'utf8'))).toEqual([1, 2]);
  });
});

describe('collectDetails', () => {
  it('collects every id', async () => {
    const r = await collectDetails(['a', 'b', 'c'], async (id) => id.toUpperCase(), {
      concurrency: 2,
      attempts: 1,
    });
    expect(Object.fromEntries(r.details)).toEqual({ a: 'A', b: 'B', c: 'C' });
    expect(r.failed).toEqual([]);
  });

  it('retries a transient failure instead of storing it as empty', async () => {
    const calls: Record<string, number> = {};
    const r = await collectDetails(
      ['ok', 'flaky'],
      async (id) => {
        calls[id] = (calls[id] ?? 0) + 1;
        if (id === 'flaky' && calls[id] < 2) throw new Error('503');
        return `detail-${id}`;
      },
      { concurrency: 2, attempts: 3 },
    );
    expect(r.details.get('flaky')).toBe('detail-flaky');
    expect(r.failed).toEqual([]);
    expect(calls).toEqual({ ok: 1, flaky: 2 });
  });

  it('reports a persistent failure and never puts a placeholder in details', async () => {
    const r = await collectDetails(
      ['ok', 'dead'],
      async (id) => {
        if (id === 'dead') throw new Error('404');
        return 'fine';
      },
      { concurrency: 1, attempts: 3 },
    );
    expect(r.failed).toEqual(['dead']);
    expect(r.details.has('dead')).toBe(false);
    expect(r.details.get('ok')).toBe('fine');
  });

  it('pauses after every N completed requests when throttled', async () => {
    const t0 = Date.now();
    await collectDetails(['a', 'b', 'c', 'd'], async (id) => id, {
      concurrency: 1,
      attempts: 1,
      throttle: { every: 2, ms: 40 },
    });
    expect(Date.now() - t0).toBeGreaterThanOrEqual(75); // two pauses
  });
});

describe('download-herb2.ts wiring', () => {
  const script = readFileSync(join(__dirname, '../../scripts/download-herb2.ts'), 'utf8');

  it('writes both outputs atomically', () => {
    expect(script).not.toMatch(/writeFileSync\(/);
    expect(script.match(/writeJsonAtomic\(/g)?.length).toBe(2);
  });

  it('refuses to write herb_details.json while any herb still fails', () => {
    const failIdx = script.indexOf('if (failed.length > 0)');
    const writeIdx = script.indexOf('writeJsonAtomic(detailsFile');
    expect(failIdx).toBeGreaterThan(0);
    expect(writeIdx).toBeGreaterThan(failIdx);
    expect(script.slice(failIdx, writeIdx)).toMatch(/process\.exit\(1\)/);
  });

  it('no longer substitutes an empty detail for a failed fetch', () => {
    expect(script).not.toMatch(/results\.set\([^)]*herb_disease:\s*\[\]/);
  });
});
