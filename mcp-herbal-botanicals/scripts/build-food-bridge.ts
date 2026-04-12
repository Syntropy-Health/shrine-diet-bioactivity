/**
 * Build food name bridge between FooDB (compound_foods) and OpenNutrition.
 *
 * Fuzzy-matches FooDB's 962 unique food names to OpenNutrition's 326K foods,
 * creating a bridge table that enables nutrition enrichment of phytochemical data.
 *
 * Matching strategy (in priority order):
 *   1. Exact case-insensitive match
 *   2. Exact match against OpenNutrition 'everyday' type foods
 *   3. Token-based match (all words in FooDB name appear in ON name)
 *   4. Prefix match (ON name starts with FooDB name)
 *
 * Usage:
 *   tsx scripts/build-food-bridge.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';

const HERBAL_DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const ON_DB_PATH = path.join(process.cwd(), '..', 'mcp-opennutrition', 'data_local', 'opennutrition_foods.db');

interface BridgeMatch {
  foodb_food_name: string;
  opennutrition_id: string;
  opennutrition_name: string;
  match_type: 'exact' | 'everyday_exact' | 'alternate_name' | 'token' | 'prefix';
  match_score: number;
}

function normalizeFoodName(name: string): string {
  return name.toLowerCase().trim();
}

function tokenize(name: string): string[] {
  return normalizeFoodName(name)
    .replace(/[^a-z0-9\s]/g, '')
    .split(/\s+/)
    .filter(t => t.length > 1);
}

export function buildFoodBridge(): { matched: number; unmatched: number; total: number } {
  if (!fs.existsSync(HERBAL_DB_PATH)) {
    console.error(`Herbal DB not found: ${HERBAL_DB_PATH}`);
    process.exit(1);
  }
  if (!fs.existsSync(ON_DB_PATH)) {
    console.error(`OpenNutrition DB not found: ${ON_DB_PATH}`);
    console.error('Run: cd ../mcp-opennutrition && npm install && npm run build');
    process.exit(1);
  }

  const herbalDb = new Database(HERBAL_DB_PATH);
  const onDb = new Database(ON_DB_PATH, { readonly: true });

  // Get distinct food names from FooDB compound_foods
  const foodNames = herbalDb
    .prepare('SELECT DISTINCT food_name FROM compound_foods ORDER BY food_name')
    .all() as Array<{ food_name: string }>;

  console.error(`Found ${foodNames.length} unique food names in compound_foods`);

  // Create bridge table
  herbalDb.exec(`
    CREATE TABLE IF NOT EXISTS food_nutrition_bridge (
      foodb_food_name TEXT PRIMARY KEY,
      opennutrition_id TEXT,
      opennutrition_name TEXT,
      match_type TEXT NOT NULL,
      match_score REAL NOT NULL DEFAULT 0
    );
    DELETE FROM food_nutrition_bridge;
  `);

  const insertBridge = herbalDb.prepare(`
    INSERT INTO food_nutrition_bridge (foodb_food_name, opennutrition_id, opennutrition_name, match_type, match_score)
    VALUES (?, ?, ?, ?, ?)
  `);

  // Prepare ON queries
  const exactMatch = onDb.prepare(
    `SELECT id, name FROM foods WHERE LOWER(name) = LOWER(?) LIMIT 1`
  );
  const everydayExact = onDb.prepare(
    `SELECT id, name FROM foods WHERE LOWER(name) = LOWER(?) AND type = 'everyday' LIMIT 1`
  );
  // Strategy 3: Match against alternate_names JSON array
  const alternateNameMatch = onDb.prepare(
    `SELECT DISTINCT foods.id, foods.name FROM foods, json_each(foods.alternate_names) AS alt
     WHERE LOWER(alt.value) = LOWER(?)
     ORDER BY CASE foods.type WHEN 'everyday' THEN 0 WHEN 'prepared' THEN 1 ELSE 2 END
     LIMIT 1`
  );
  const prefixMatch = onDb.prepare(
    `SELECT id, name FROM foods WHERE LOWER(name) LIKE ? AND type = 'everyday' LIMIT 1`
  );
  const likeMatch = onDb.prepare(
    `SELECT id, name, type FROM foods WHERE LOWER(name) LIKE ? ORDER BY
      CASE type WHEN 'everyday' THEN 0 WHEN 'prepared' THEN 1 WHEN 'grocery' THEN 2 ELSE 3 END,
      LENGTH(name) ASC
    LIMIT 1`
  );

  const matches: BridgeMatch[] = [];
  const unmatched: string[] = [];

  const insertMany = herbalDb.transaction(() => {
    for (const { food_name } of foodNames) {
      const normalized = normalizeFoodName(food_name);

      // Strategy 1: Exact match (any type)
      let row = exactMatch.get(normalized) as { id: string; name: string } | undefined;
      if (row) {
        insertBridge.run(food_name, row.id, row.name, 'exact', 1.0);
        matches.push({ foodb_food_name: food_name, opennutrition_id: row.id, opennutrition_name: row.name, match_type: 'exact', match_score: 1.0 });
        continue;
      }

      // Strategy 2: Everyday type exact match
      row = everydayExact.get(normalized) as { id: string; name: string } | undefined;
      if (row) {
        insertBridge.run(food_name, row.id, row.name, 'everyday_exact', 0.95);
        matches.push({ foodb_food_name: food_name, opennutrition_id: row.id, opennutrition_name: row.name, match_type: 'everyday_exact', match_score: 0.95 });
        continue;
      }

      // Strategy 3: Alternate names match (ON alternate_names JSON array)
      row = alternateNameMatch.get(normalized) as { id: string; name: string } | undefined;
      if (row) {
        insertBridge.run(food_name, row.id, row.name, 'alternate_name', 0.92);
        matches.push({ foodb_food_name: food_name, opennutrition_id: row.id, opennutrition_name: row.name, match_type: 'alternate_name' as BridgeMatch['match_type'], match_score: 0.92 });
        continue;
      }

      // Strategy 4: Prefix match (ON name starts with FooDB name, everyday preferred)
      row = prefixMatch.get(`${normalized}%`) as { id: string; name: string } | undefined;
      if (row) {
        const score = normalized.length / normalizeFoodName(row.name).length;
        insertBridge.run(food_name, row.id, row.name, 'prefix', Math.round(score * 100) / 100);
        matches.push({ foodb_food_name: food_name, opennutrition_id: row.id, opennutrition_name: row.name, match_type: 'prefix', match_score: Math.round(score * 100) / 100 });
        continue;
      }

      // Strategy 5: Token match (all tokens from FooDB name appear in ON name)
      const tokens = tokenize(food_name);
      if (tokens.length > 0) {
        const pattern = `%${tokens.join('%')}%`;
        row = likeMatch.get(pattern) as { id: string; name: string; type: string } | undefined;
        if (row) {
          const score = tokens.length / tokenize(row.name).length;
          insertBridge.run(food_name, row.id, row.name, 'token', Math.round(Math.min(score, 0.9) * 100) / 100);
          matches.push({ foodb_food_name: food_name, opennutrition_id: row.id, opennutrition_name: row.name, match_type: 'token', match_score: Math.round(Math.min(score, 0.9) * 100) / 100 });
          continue;
        }
      }

      // No match found
      unmatched.push(food_name);
    }
  });

  insertMany();

  // Print stats
  const byType = { exact: 0, everyday_exact: 0, alternate_name: 0, prefix: 0, token: 0 };
  for (const m of matches) {
    byType[m.match_type]++;
  }

  console.error(`\n=== Food Bridge Results ===`);
  console.error(`Total FooDB foods:    ${foodNames.length}`);
  console.error(`Matched:              ${matches.length} (${Math.round(matches.length / foodNames.length * 100)}%)`);
  console.error(`  exact:              ${byType.exact}`);
  console.error(`  everyday_exact:     ${byType.everyday_exact}`);
  console.error(`  alternate_name:     ${byType.alternate_name}`);
  console.error(`  prefix:             ${byType.prefix}`);
  console.error(`  token:              ${byType.token}`);
  console.error(`Unmatched:            ${unmatched.length}`);

  if (unmatched.length > 0 && unmatched.length <= 50) {
    console.error(`\nUnmatched foods:`);
    for (const name of unmatched) {
      console.error(`  - ${name}`);
    }
  } else if (unmatched.length > 50) {
    console.error(`\nFirst 50 unmatched foods:`);
    for (const name of unmatched.slice(0, 50)) {
      console.error(`  - ${name}`);
    }
  }

  herbalDb.close();
  onDb.close();

  return { matched: matches.length, unmatched: unmatched.length, total: foodNames.length };
}

// Run if called directly
buildFoodBridge();
