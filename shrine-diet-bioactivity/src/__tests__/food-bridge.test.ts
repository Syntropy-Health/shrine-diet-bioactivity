import Database from 'better-sqlite3';
import { describe, it, expect } from 'vitest';

describe('food_nutrition_bridge population', () => {
  it('has at least 900 bridge rows after bridge+enrich', () => {
    const db = new Database('./data_local/herbal_botanicals.db', { readonly: true });
    const row = db.prepare('SELECT COUNT(*) AS c FROM food_nutrition_bridge').get() as { c: number };
    expect(row.c).toBeGreaterThanOrEqual(900);
    db.close();
  });
});
