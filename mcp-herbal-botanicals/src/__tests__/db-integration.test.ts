import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as path from 'path';
import * as fs from 'fs';
import { HerbalDBAdapter } from '../HerbalDBAdapter.js';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const DB_EXISTS = fs.existsSync(DB_PATH);

describe.skipIf(!DB_EXISTS)('HerbalDBAdapter integration tests', () => {
  let db: HerbalDBAdapter;

  beforeAll(() => {
    db = new HerbalDBAdapter(DB_PATH);
  });

  afterAll(() => {
    db?.close();
  });

  it('database exists with expected tables', () => {
    const stats = db.getStats();
    expect(stats.herbs).toBeGreaterThan(2000);
    expect(stats.compounds).toBeGreaterThan(20000);
    expect(stats.herb_compounds).toBeGreaterThan(50000);
  });

  it('searchHerbs finds Ashwagandha', () => {
    const result = db.searchHerbs('ashwagandha');
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].common_name).toBe('Ashwagandha');
    expect(result.data[0].scientific_name).toContain('Withania somnifera');
  });

  it('searchHerbs finds Turmeric', () => {
    const result = db.searchHerbs('turmeric');
    expect(result.data.length).toBeGreaterThan(0);
    const turmeric = result.data.find((h) => h.common_name === 'Turmeric');
    expect(turmeric).toBeDefined();
    expect(turmeric!.scientific_name).toContain('Curcuma longa');
  });

  it('searchHerbs finds by scientific name', () => {
    const result = db.searchHerbs('Panax ginseng');
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].scientific_name).toContain('Panax');
  });

  it('getHerbCompounds returns compounds for Ashwagandha', () => {
    const herbs = db.searchHerbs('ashwagandha');
    const herbId = herbs.data[0].id;
    const compounds = db.getHerbCompounds(herbId);
    expect(compounds.length).toBeGreaterThan(50);
    const hasWithanolide = compounds.some((c) => c.compound_name.toLowerCase().includes('withanol'));
    expect(hasWithanolide).toBe(true);
  });

  it('searchCompounds finds quercetin with herb associations', () => {
    const result = db.searchCompounds('quercetin');
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].herb_count).toBeGreaterThan(0);
    const withBio = result.data.find((c) => c.bioactivities.length > 0);
    expect(withBio).toBeDefined();
  });

  it('searchByBioactivity finds anti-inflammatory compounds', () => {
    const result = db.searchByBioactivity('Antiinflammatory');
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].herbs.length).toBeGreaterThan(0);
  });

  it('getHerbProfile returns full profile for a herb', () => {
    const herbs = db.searchHerbs('Curcuma longa');
    expect(herbs.data.length).toBeGreaterThan(0);
    const herbId = herbs.data[0].id;
    const profile = db.getHerbProfile(herbId);
    expect(profile).not.toBeNull();
    expect(profile!.herb.scientific_name).toContain('Curcuma longa');
    expect(profile!.compound_count).toBeGreaterThan(10);
    expect(profile!.top_compounds.length).toBeGreaterThan(0);
    expect(profile!.bioactivity_summary.length).toBeGreaterThan(0);
  });

  it('pagination works correctly', () => {
    const page1 = db.searchHerbs('a', 1, 5);
    const page2 = db.searchHerbs('a', 2, 5);
    expect(page1.data.length).toBe(5);
    expect(page2.data.length).toBe(5);
    expect(page1.data[0].id).not.toBe(page2.data[0].id);
    expect(page1.hasMore).toBe(true);
  });

  it('getStats returns valid counts', () => {
    const stats = db.getStats();
    expect(stats.herbs).toBeGreaterThan(0);
    expect(stats.compounds).toBeGreaterThan(0);
    expect(stats.herb_compounds).toBeGreaterThan(0);
  });
});
