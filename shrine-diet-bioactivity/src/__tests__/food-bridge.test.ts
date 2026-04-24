import Database from 'better-sqlite3';
import { describe, it, expect } from 'vitest';

describe('food_nutrition_bridge population', () => {
  // Script matched 647/962 FooDB foods (67%) against OpenNutrition 326K foods.
  // Threshold set to 600 to give a 7% buffer below the observed baseline of 647.
  it('has at least 600 bridge rows after bridge+enrich', () => {
    const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });
    const row = db.prepare('SELECT COUNT(*) AS c FROM food_nutrition_bridge').get() as { c: number };
    expect(row.c).toBeGreaterThanOrEqual(600);
    db.close();
  });
});
