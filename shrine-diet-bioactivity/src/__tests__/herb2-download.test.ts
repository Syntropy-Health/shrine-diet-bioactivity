import { mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { describe, expect, it } from 'vitest';

import {
  assertCompleteHerbList,
  assertDetailShape,
  collectDetails,
  inInputOrder,
  writeJsonAtomic,
} from '../herb2-download.js';

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

  it('never touches the target until the full new content exists (write-then-rename)', () => {
    // If the temp file cannot be created, an atomic writer fails BEFORE the target
    // changes; a plain writeFileSync(path) would have overwritten it.
    const dir = mkdtempSync(join(tmpdir(), 'herb2-'));
    const path = join(dir, 'herb_details.json');
    writeFileSync(path, '{"old":true}');
    mkdirSync(`${path}.tmp-${process.pid}`); // blocks the temp file
    expect(() => writeJsonAtomic(path, { new: true })).toThrow();
    expect(readFileSync(path, 'utf8')).toBe('{"old":true}');
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

  it('tries a persistent failure exactly `attempts` times', async () => {
    let calls = 0;
    await collectDetails(['dead'], async () => {
      calls += 1;
      throw new Error('x');
    }, { concurrency: 1, attempts: 3 });
    expect(calls).toBe(3);
  });

  it('never has more than `concurrency` requests in flight', async () => {
    let inFlight = 0;
    let peak = 0;
    await collectDetails(Array.from({ length: 20 }, (_, i) => `h${i}`), async (id) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 2));
      inFlight -= 1;
      return id;
    }, { concurrency: 3, attempts: 1 });
    expect(peak).toBe(3);
  });

  it('waits before each retry round (backoff out of a 429/503 window)', async () => {
    const at: number[] = [];
    const t0 = Date.now();
    await collectDetails(['x'], async () => {
      at.push(Date.now() - t0);
      throw new Error('503');
    }, { concurrency: 1, attempts: 3, retryDelaysMs: [30, 60] });
    expect(at).toHaveLength(3);
    expect(at[1] - at[0]).toBeGreaterThanOrEqual(25);
    expect(at[2] - at[1]).toBeGreaterThanOrEqual(55);
  });

  it('pauses after every N completed requests when throttled', async () => {
    const t0 = Date.now();
    await collectDetails(['a', 'b', 'c', 'd'], async (id) => id, {
      concurrency: 1,
      attempts: 1,
      throttle: { every: 2, ms: 40 },
    });
    const took = Date.now() - t0;
    expect(took).toBeGreaterThanOrEqual(75); // two pauses (after 2 and 4)...
    expect(took).toBeLessThan(150); // ...not one after every request
  });
});

describe('response integrity', () => {
  // MEASURED 2026-10-12: a real herb with no evidence still returns both keys
  // (header-only arrays); an unknown id is an HTML 500.
  it('accepts a real no-evidence response (both keys, header rows only)', () => {
    expect(() => assertDetailShape('H1', { herb_disease: [['h']], drug_paper_disease: [['h']] })).not.toThrow();
  });

  it.each([null, undefined, {}, [], 'x', { error: 'rate limited' }])(
    'rejects %j instead of caching it as "no evidence"',
    (body) => {
      expect(() => assertDetailShape('H1', body)).toThrow(/malformed/);
    },
  );

  it('rejects a herb list that stopped early', () => {
    expect(() => assertCompleteHerbList(7000, 7263)).toThrow(/incomplete/);
    expect(() => assertCompleteHerbList(0, 0)).toThrow(/no total/);
    expect(() => assertCompleteHerbList(7263, 7263)).not.toThrow();
  });

  it('writes details in input order (stable across runs; retries finish last)', () => {
    const m = new Map([['c', 3], ['a', 1], ['b', 2]]);
    expect(Object.keys(inInputOrder(['a', 'b', 'c', 'missing'], m))).toEqual(['a', 'b', 'c']);
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

  it('no longer substitutes an empty detail for a failed or malformed fetch', () => {
    expect(script).not.toMatch(/herb_disease:\s*\[\],\s*drug_paper_disease:\s*\[\]/);
    expect(script).toMatch(/assertDetailShape\(herbId, data\)/);
  });

  it('a missing browse page fails instead of ending the list', () => {
    expect(script).not.toMatch(/browse_data\) break;/);
    expect(script).toMatch(/assertCompleteHerbList\(herbs\.length, totalNum\)/);
  });

  it('bounds every request with a timeout and backs off between retry rounds', () => {
    expect(script).toMatch(/signal: AbortSignal\.timeout\(/);
    expect(script).toMatch(/retryDelaysMs: RETRY_DELAYS_MS/);
  });
});
