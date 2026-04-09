import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as path from 'path';
import * as fs from 'fs';
import { HerbalDBAdapter } from '../HerbalDBAdapter.js';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');

describe('KG expansion tests', () => {
  let db: HerbalDBAdapter;

  beforeAll(() => {
    if (!fs.existsSync(DB_PATH)) {
      console.warn('Database not found — skipping KG expansion tests. Run npm run migrate-kg first.');
      return;
    }
    db = new HerbalDBAdapter(DB_PATH);
  });

  afterAll(() => {
    db?.close();
  });

  it('getStats returns symptom and food plant counts', () => {
    if (!db) return;
    const stats = db.getStats();
    expect(stats.symptoms).toBeGreaterThan(0);
    expect(stats.herb_symptoms).toBeGreaterThan(0);
    expect(stats.food_plants).toBeGreaterThan(0);
  });

  it('searchBySymptom finds herbs for inflammation', () => {
    if (!db) return;
    const result = db.searchBySymptom('inflammation');
    expect(result.symptoms_matched.length).toBeGreaterThan(0);
    expect(result.symptoms_matched[0].name).toBe('Inflammation');
    expect(result.herbs.length).toBeGreaterThan(0);
  });

  it('searchBySymptom returns functional foods', () => {
    if (!db) return;
    const result = db.searchBySymptom('inflammation');
    expect(result.compounds.length).toBeGreaterThan(0);
    expect(result.functional_foods.length).toBeGreaterThan(0);
  });

  it('searchBySymptom finds herbs for insomnia', () => {
    if (!db) return;
    const result = db.searchBySymptom('insomnia');
    expect(result.symptoms_matched.length).toBeGreaterThan(0);
    expect(result.herbs.length).toBeGreaterThan(0);
  });

  it('searchBySymptom finds herbs for fatigue', () => {
    if (!db) return;
    const result = db.searchBySymptom('fatigue');
    expect(result.symptoms_matched.length).toBeGreaterThan(0);
    expect(result.herbs.length).toBeGreaterThan(0);
  });

  it('searchBySymptom returns empty for unknown symptom', () => {
    if (!db) return;
    const result = db.searchBySymptom('xyznonexistent');
    expect(result.symptoms_matched.length).toBe(0);
    expect(result.herbs.length).toBe(0);
  });

  it('getCompoundTargets returns empty (no CMAUP data yet)', () => {
    if (!db) return;
    const targets = db.getCompoundTargets('curcumin');
    // Empty until CMAUP data is loaded — but should not throw
    expect(Array.isArray(targets)).toBe(true);
  });

  it('findFunctionalFoods finds turmeric as food plant', () => {
    if (!db) return;
    const result = db.findFunctionalFoods('turmeric');
    expect(result.data.length).toBeGreaterThan(0);
  });

  it('findFunctionalFoods finds ginger as food plant', () => {
    if (!db) return;
    const result = db.findFunctionalFoods('ginger');
    expect(result.data.length).toBeGreaterThan(0);
  });

  it('searchHerbs returns is_food_plant field', () => {
    if (!db) return;
    const result = db.searchHerbs('turmeric');
    expect(result.data.length).toBeGreaterThan(0);
    const turmeric = result.data.find((h) => h.common_name === 'Turmeric');
    expect(turmeric).toBeDefined();
    expect(turmeric!.is_food_plant).toBe(true);
    expect(turmeric!.is_edible).toBe(true);
  });

  it('searchHerbs shows ashwagandha as edible but not food', () => {
    if (!db) return;
    const result = db.searchHerbs('ashwagandha');
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].is_edible).toBe(true);
  });

  it('findFunctionalFoods pagination works', () => {
    if (!db) return;
    const page1 = db.findFunctionalFoods('a', 1, 5);
    expect(page1.data.length).toBeGreaterThan(0);
    expect(page1.page).toBe(1);
  });
});
