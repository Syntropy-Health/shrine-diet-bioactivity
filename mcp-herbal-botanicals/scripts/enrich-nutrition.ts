/**
 * Enrich compound_foods table with nutrition data from OpenNutrition.
 *
 * Uses the food_nutrition_bridge table (created by build-food-bridge.ts) to
 * look up nutrition_100g JSON from the OpenNutrition DB and populate it on
 * matching compound_foods rows.
 *
 * Prerequisites:
 *   - Run build-food-bridge.ts first to create the bridge table.
 *
 * Usage:
 *   tsx scripts/enrich-nutrition.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';

const HERBAL_DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const ON_DB_PATH = path.join(process.cwd(), '..', 'mcp-opennutrition', 'data_local', 'opennutrition_foods.db');

export function enrichNutrition(): { enriched_foods: number; enriched_rows: number; total_rows: number } {
  if (!fs.existsSync(HERBAL_DB_PATH)) {
    console.error(`Herbal DB not found: ${HERBAL_DB_PATH}`);
    process.exit(1);
  }
  if (!fs.existsSync(ON_DB_PATH)) {
    console.error(`OpenNutrition DB not found: ${ON_DB_PATH}`);
    process.exit(1);
  }

  const herbalDb = new Database(HERBAL_DB_PATH);
  const onDb = new Database(ON_DB_PATH, { readonly: true });

  // Check bridge table exists
  const bridgeExists = herbalDb.prepare(
    `SELECT name FROM sqlite_master WHERE type='table' AND name='food_nutrition_bridge'`
  ).get();
  if (!bridgeExists) {
    console.error('Bridge table not found. Run build-food-bridge.ts first.');
    process.exit(1);
  }

  // Add nutrition_100g column to compound_foods if not exists
  const columns = herbalDb
    .prepare(`PRAGMA table_info(compound_foods)`)
    .all() as Array<{ name: string }>;
  const hasNutritionCol = columns.some(c => c.name === 'nutrition_100g');

  if (!hasNutritionCol) {
    herbalDb.exec(`ALTER TABLE compound_foods ADD COLUMN nutrition_100g TEXT`);
    console.error('Added nutrition_100g column to compound_foods');
  }

  // Get all bridge entries
  const bridgeEntries = herbalDb
    .prepare(`SELECT foodb_food_name, opennutrition_id FROM food_nutrition_bridge WHERE opennutrition_id IS NOT NULL`)
    .all() as Array<{ foodb_food_name: string; opennutrition_id: string }>;

  console.error(`Found ${bridgeEntries.length} bridged foods to enrich`);

  // Prepare ON nutrition lookup
  const getNutrition = onDb.prepare(
    `SELECT json_extract(nutrition_100g, '$') as nutrition_100g FROM foods WHERE id = ?`
  );

  // Prepare herbal update
  const updateCompoundFoods = herbalDb.prepare(
    `UPDATE compound_foods SET nutrition_100g = ? WHERE food_name = ?`
  );

  let enrichedFoods = 0;
  let enrichedRows = 0;

  const enrichAll = herbalDb.transaction(() => {
    for (const { foodb_food_name, opennutrition_id } of bridgeEntries) {
      const nutritionRow = getNutrition.get(opennutrition_id) as { nutrition_100g: string } | undefined;
      if (!nutritionRow || !nutritionRow.nutrition_100g) continue;

      const result = updateCompoundFoods.run(nutritionRow.nutrition_100g, foodb_food_name);
      if (result.changes > 0) {
        enrichedFoods++;
        enrichedRows += result.changes;
      }
    }
  });

  enrichAll();

  const totalRows = (herbalDb.prepare('SELECT COUNT(*) as cnt FROM compound_foods').get() as { cnt: number }).cnt;
  const enrichedCount = (herbalDb.prepare('SELECT COUNT(*) as cnt FROM compound_foods WHERE nutrition_100g IS NOT NULL').get() as { cnt: number }).cnt;

  console.error(`\n=== Nutrition Enrichment Results ===`);
  console.error(`Bridge entries:       ${bridgeEntries.length}`);
  console.error(`Foods enriched:       ${enrichedFoods}`);
  console.error(`Rows enriched:        ${enrichedRows} / ${totalRows} (${Math.round(enrichedRows / totalRows * 100)}%)`);
  console.error(`Total with nutrition:  ${enrichedCount}`);

  herbalDb.close();
  onDb.close();

  return { enriched_foods: enrichedFoods, enriched_rows: enrichedRows, total_rows: totalRows };
}

enrichNutrition();
