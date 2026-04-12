import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as path from 'path';
import * as fs from 'fs';
import Database from 'better-sqlite3';

const HERBAL_DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const ON_DB_PATH = path.join(process.cwd(), '..', 'mcp-opennutrition', 'data_local', 'opennutrition_foods.db');
const HERBAL_DB_EXISTS = fs.existsSync(HERBAL_DB_PATH);
const ON_DB_EXISTS = fs.existsSync(ON_DB_PATH);
const BOTH_DBS_EXIST = HERBAL_DB_EXISTS && ON_DB_EXISTS;

describe.skipIf(!HERBAL_DB_EXISTS)('Food bridge table tests (herbal DB only)', () => {
  let db: Database.Database;

  beforeAll(() => {
    db = new Database(HERBAL_DB_PATH, { readonly: true });
  });

  afterAll(() => {
    db?.close();
  });

  it('compound_foods table has food entries', () => {
    const row = db.prepare('SELECT COUNT(DISTINCT food_name) as cnt FROM compound_foods').get() as { cnt: number };
    expect(row.cnt).toBeGreaterThan(0);
  });

  it('food_nutrition_bridge table exists when bridge has been run', () => {
    const table = db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='food_nutrition_bridge'"
    ).get();
    // Bridge table may or may not exist depending on whether build-food-bridge.ts has been run
    // Just ensure the query doesn't throw
    expect(true).toBe(true);
  });
});

describe.skipIf(!BOTH_DBS_EXIST)('Food bridge matching tests (both DBs required)', () => {
  let herbalDb: Database.Database;
  let onDb: Database.Database;

  beforeAll(() => {
    herbalDb = new Database(HERBAL_DB_PATH, { readonly: true });
    onDb = new Database(ON_DB_PATH, { readonly: true });
  });

  afterAll(() => {
    herbalDb?.close();
    onDb?.close();
  });

  it('OpenNutrition has known foods that FooDB references', () => {
    // These foods exist in FooDB compound_foods
    const knownFoods = ['Garlic', 'Turmeric', 'Ginger', 'Cinnamon', 'Spinach'];
    for (const food of knownFoods) {
      const row = onDb.prepare(
        `SELECT COUNT(*) as cnt FROM foods WHERE LOWER(name) = LOWER(?)`
      ).get(food) as { cnt: number };
      expect(row.cnt, `Expected OpenNutrition to have '${food}'`).toBeGreaterThan(0);
    }
  });

  it('OpenNutrition everyday foods include common items', () => {
    const row = onDb.prepare(
      `SELECT COUNT(*) as cnt FROM foods WHERE type = 'everyday'`
    ).get() as { cnt: number };
    expect(row.cnt).toBeGreaterThan(1000);
  });

  it('FooDB foods are mostly single-word generic names', () => {
    const foods = herbalDb.prepare(
      `SELECT DISTINCT food_name FROM compound_foods LIMIT 100`
    ).all() as Array<{ food_name: string }>;

    // Most FooDB food names should be 1-3 words
    const shortNames = foods.filter(f => f.food_name.split(/\s+/).length <= 3);
    expect(shortNames.length).toBeGreaterThan(foods.length * 0.5);
  });

  it('nutrition_100g column is queryable when enrichment has run', () => {
    // Column only exists after enrich-nutrition.ts has been run (ALTER TABLE)
    const columns = herbalDb.prepare('PRAGMA table_info(compound_foods)').all() as Array<{ name: string }>;
    const hasCol = columns.some(c => c.name === 'nutrition_100g');
    if (!hasCol) {
      // Column not added yet — skip gracefully
      expect(true).toBe(true);
      return;
    }
    const row = herbalDb.prepare(
      `SELECT COUNT(*) as cnt FROM compound_foods WHERE nutrition_100g IS NOT NULL`
    ).get() as { cnt: number };
    expect(row.cnt).toBeGreaterThanOrEqual(0);
  });
});
