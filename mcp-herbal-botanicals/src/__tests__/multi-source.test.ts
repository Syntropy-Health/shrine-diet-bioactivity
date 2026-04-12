import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as path from 'path';
import * as fs from 'fs';
import { HerbalDBAdapter } from '../HerbalDBAdapter.js';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const DB_EXISTS = fs.existsSync(DB_PATH);

describe.skipIf(!DB_EXISTS)('Multi-source integration tests', () => {
  let db: HerbalDBAdapter;

  beforeAll(() => {
    db = new HerbalDBAdapter(DB_PATH);
  });

  afterAll(() => {
    db?.close();
  });

  it('getStats includes new table counts', () => {
    const stats = db.getStats();
    // These should always exist (even if 0)
    expect(stats).toHaveProperty('targets');
    expect(stats).toHaveProperty('compound_targets');
    expect(stats).toHaveProperty('target_diseases');
    expect(stats).toHaveProperty('chemical_diseases');
    expect(stats).toHaveProperty('chemical_phenotypes');
    expect(stats).toHaveProperty('food_plants');
  });

  it('searchDiseases returns results for known diseases', () => {
    const result = db.searchDiseases('cancer');
    // May be empty if CMAUP/TTD not loaded yet, but should not throw
    expect(result).toHaveProperty('data');
    expect(result).toHaveProperty('total');
    expect(result).toHaveProperty('page');
    expect(Array.isArray(result.data)).toBe(true);
  });

  it('searchDiseases returns empty for unknown disease', () => {
    const result = db.searchDiseases('xyznonexistent12345');
    expect(result.data.length).toBe(0);
    expect(result.total).toBe(0);
  });

  it('searchDiseases respects pagination', () => {
    const page1 = db.searchDiseases('a', 1, 5);
    expect(page1.page).toBe(1);
    expect(page1.pageSize).toBe(5);
    if (page1.total > 5) {
      expect(page1.hasMore).toBe(true);
      expect(page1.data.length).toBe(5);
    }
  });

  it('getTargetDiseases returns paginated results', () => {
    const result = db.getTargetDiseases('nonexistent_target');
    expect(result.data.length).toBe(0);
    expect(result.total).toBe(0);
  });

  it('getChemicalDiseases returns empty for unknown compound', () => {
    const result = db.getChemicalDiseases('fake_compound_id_12345');
    expect(result.data.length).toBe(0);
    expect(result.total).toBe(0);
  });

  it('getCompoundTargets returns array (even if empty before CMAUP)', () => {
    const targets = db.getCompoundTargets('curcumin');
    expect(Array.isArray(targets)).toBe(true);
  });
});

// Separate describe block for tests that require CMAUP data
const CMAUP_LOADED = DB_EXISTS && (() => {
  try {
    const adapter = new HerbalDBAdapter(DB_PATH);
    const stats = adapter.getStats();
    adapter.close();
    return stats.targets > 0;
  } catch {
    return false;
  }
})();

describe.skipIf(!CMAUP_LOADED)('CMAUP-dependent tests', () => {
  let db: HerbalDBAdapter;

  beforeAll(() => {
    db = new HerbalDBAdapter(DB_PATH);
  });

  afterAll(() => {
    db?.close();
  });

  it('targets table has entries from CMAUP', () => {
    const stats = db.getStats();
    expect(stats.targets).toBeGreaterThan(0);
  });

  it('compound_targets has entries after CMAUP load', () => {
    const stats = db.getStats();
    expect(stats.compound_targets).toBeGreaterThan(0);
  });

  it('searchDiseases finds disease associations', () => {
    const result = db.searchDiseases('diabetes');
    expect(result.data.length).toBeGreaterThan(0);
  });
});
