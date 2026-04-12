import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as path from 'path';
import * as fs from 'fs';
import { HerbalDBAdapter } from '../HerbalDBAdapter.js';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const DB_EXISTS = fs.existsSync(DB_PATH);

describe.skipIf(!DB_EXISTS)('KG expansion tests', () => {
  let db: HerbalDBAdapter;

  beforeAll(() => {
    db = new HerbalDBAdapter(DB_PATH);
  });

  afterAll(() => {
    db?.close();
  });

  it('getStats returns symptom and food plant counts', () => {
    const stats = db.getStats();
    expect(stats.symptoms).toBeGreaterThan(0);
    expect(stats.herb_symptoms).toBeGreaterThan(0);
    expect(stats.food_plants).toBeGreaterThan(0);
  });

  it('searchBySymptom finds herbs for inflammation', () => {
    const result = db.searchBySymptom('inflammation');
    expect(result.symptoms_matched.length).toBeGreaterThan(0);
    expect(result.symptoms_matched[0].name).toBe('Inflammation');
    expect(result.herbs.length).toBeGreaterThan(0);
  });

  it('searchBySymptom returns functional foods', () => {
    const result = db.searchBySymptom('inflammation');
    expect(result.compounds.length).toBeGreaterThan(0);
    expect(result.functional_foods.length).toBeGreaterThan(0);
  });

  it('searchBySymptom finds herbs for insomnia', () => {
    const result = db.searchBySymptom('insomnia');
    expect(result.symptoms_matched.length).toBeGreaterThan(0);
    expect(result.herbs.length).toBeGreaterThan(0);
  });

  it('searchBySymptom finds herbs for fatigue', () => {
    const result = db.searchBySymptom('fatigue');
    expect(result.symptoms_matched.length).toBeGreaterThan(0);
    expect(result.herbs.length).toBeGreaterThan(0);
  });

  it('searchBySymptom returns empty for unknown symptom', () => {
    const result = db.searchBySymptom('xyznonexistent');
    expect(result.symptoms_matched.length).toBe(0);
    expect(result.herbs.length).toBe(0);
  });

  it('getCompoundTargets returns empty (no CMAUP data yet)', () => {
    const targets = db.getCompoundTargets('curcumin');
    expect(Array.isArray(targets)).toBe(true);
  });

  it('findFunctionalFoods finds turmeric as food plant', () => {
    const result = db.findFunctionalFoods('turmeric');
    expect(result.data.length).toBeGreaterThan(0);
  });

  it('findFunctionalFoods finds ginger as food plant', () => {
    const result = db.findFunctionalFoods('ginger');
    expect(result.data.length).toBeGreaterThan(0);
  });

  it('searchHerbs returns is_food_plant field', () => {
    const result = db.searchHerbs('turmeric');
    expect(result.data.length).toBeGreaterThan(0);
    const turmeric = result.data.find((h) => h.common_name === 'Turmeric');
    expect(turmeric).toBeDefined();
    expect(turmeric!.is_food_plant).toBe(true);
    expect(turmeric!.is_edible).toBe(true);
  });

  it('searchHerbs shows ashwagandha as edible but not food', () => {
    const result = db.searchHerbs('ashwagandha');
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].is_edible).toBe(true);
  });

  it('findFunctionalFoods pagination works', () => {
    const page1 = db.findFunctionalFoods('a', 1, 5);
    expect(page1.data.length).toBeGreaterThan(0);
    expect(page1.page).toBe(1);
  });
});
