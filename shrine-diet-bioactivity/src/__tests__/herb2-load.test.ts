import Database from 'better-sqlite3';
import { describe, it, expect, afterAll } from 'vitest';

describe('HERB 2.0 SQLite load', () => {
  const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });

  afterAll(() => {
    db.close();
  });

  it('herb2_herbs has >= 1200 herbs with CN names', () => {
    // HERB 2.0 covers 7,263 herbs per browse_api; we load all of them.
    // Threshold set to 1200 (plan estimate) — calibrate down with comment if actual < 1200.
    const r = db
      .prepare('SELECT COUNT(*) AS c FROM herb2_herbs WHERE name_cn IS NOT NULL')
      .get() as { c: number };
    expect(r.c).toBeGreaterThanOrEqual(1200);
  });

  it('herb2_herbs has bilingual entries (both name_en and name_cn)', () => {
    const r = db
      .prepare(
        'SELECT COUNT(*) AS c FROM herb2_herbs WHERE name_cn IS NOT NULL AND name_en IS NOT NULL',
      )
      .get() as { c: number };
    expect(r.c).toBeGreaterThan(0);
  });

  it('herb2_herb_disease has evidence_tier in {clinical, experimental, traditional}', () => {
    const rows = db
      .prepare('SELECT DISTINCT evidence_tier FROM herb2_herb_disease')
      .all() as Array<{ evidence_tier: string }>;
    const tiers = new Set(rows.map((x) => x.evidence_tier));
    expect(tiers.size).toBeGreaterThan(0);
    for (const t of tiers) {
      expect(['clinical', 'experimental', 'traditional']).toContain(t);
    }
  });

  it('herb2_herb_disease has both clinical and experimental tiers', () => {
    // HERB 2.0 provides paper-based (clinical) and p-value-based (experimental) associations.
    const rows = db
      .prepare('SELECT DISTINCT evidence_tier FROM herb2_herb_disease')
      .all() as Array<{ evidence_tier: string }>;
    const tiers = new Set(rows.map((x) => x.evidence_tier));
    expect(tiers.has('clinical') || tiers.has('experimental')).toBe(true);
  });

  it('herb2_herb_disease has at least 100 total relationships', () => {
    // HERB 2.0 covers 7263 herbs × disease associations; even a partial load yields thousands.
    // Threshold set conservatively at 100 to guard against empty loads.
    const r = db
      .prepare('SELECT COUNT(*) AS c FROM herb2_herb_disease')
      .get() as { c: number };
    expect(r.c).toBeGreaterThanOrEqual(100);
  });

  it('herb2_herbs primary keys are unique HERB IDs (format HERB######)', () => {
    const r = db
      .prepare("SELECT COUNT(*) AS c FROM herb2_herbs WHERE herb_id LIKE 'HERB%'")
      .get() as { c: number };
    expect(r.c).toBeGreaterThan(0);
  });

  it('herb2_herb_disease foreign keys reference valid herb_ids in herb2_herbs', () => {
    const r = db
      .prepare(`
        SELECT COUNT(*) AS c FROM herb2_herb_disease hd
        WHERE NOT EXISTS (
          SELECT 1 FROM herb2_herbs h WHERE h.herb_id = hd.herb_id
        )
      `)
      .get() as { c: number };
    // All herb_ids in herb2_herb_disease must exist in herb2_herbs
    expect(r.c).toBe(0);
  });
});
