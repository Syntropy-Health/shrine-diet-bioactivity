/**
 * SQLite adapter for the herbal_botanicals database.
 *
 * Provides typed query methods for herbs, compounds, herb-compound links,
 * compound-food bridges, and aggregate overlap queries.
 */

import Database from 'better-sqlite3';
import * as path from 'path';
import { fileURLToPath } from 'url';
import type {
  Herb,
  Compound,
  HerbCompound,
  CompoundFood,
  CompoundTarget,
  HerbFoodOverlap,
  FunctionalFood,
  Symptom,
  SymptomSearchResult,
  PaginatedResult,
} from './types.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function parseJsonArray(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export class HerbalDBAdapter {
  private readonly db: Database.Database;

  constructor(dbPath?: string) {
    const resolvedPath =
      dbPath || path.join(__dirname, '..', 'data_local', 'herbal_botanicals.db');
    this.db = new Database(resolvedPath, { readonly: true });
    this.db.pragma('journal_mode = WAL');
  }

  close(): void {
    this.db.close();
  }

  // -------------------------------------------------------------------------
  // search-herbs: fuzzy search by name/synonym
  // -------------------------------------------------------------------------

  searchHerbs(query: string, page = 1, pageSize = 10): PaginatedResult<Herb> {
    const pattern = `%${query}%`;
    const offset = (page - 1) * pageSize;

    const countRow = this.db.prepare(`
      SELECT COUNT(*) as cnt FROM herbs
      WHERE common_name LIKE ? OR scientific_name LIKE ? OR alternate_names LIKE ?
    `).get(pattern, pattern, pattern) as { cnt: number };

    const rows = this.db.prepare(`
      SELECT * FROM herbs
      WHERE common_name LIKE ? OR scientific_name LIKE ? OR alternate_names LIKE ?
      ORDER BY
        CASE WHEN common_name LIKE ? THEN 0 ELSE 1 END,
        common_name
      LIMIT ? OFFSET ?
    `).all(pattern, pattern, pattern, pattern, pageSize, offset) as Array<Record<string, unknown>>;

    return {
      data: rows.map((r) => ({
        id: r.id as string,
        scientific_name: r.scientific_name as string,
        common_name: r.common_name as string | null,
        family: r.family as string | null,
        genus: r.genus as string | null,
        species: r.species as string | null,
        usage_type: r.usage_type as string | null,
        alternate_names: parseJsonArray(r.alternate_names as string),
        is_food_plant: !!(r.is_food_plant as number),
        is_edible: !!(r.is_edible as number),
      })),
      total: countRow.cnt,
      page,
      pageSize,
      hasMore: offset + pageSize < countRow.cnt,
    };
  }

  // -------------------------------------------------------------------------
  // get-herb-compounds: compounds for a specific herb
  // -------------------------------------------------------------------------

  getHerbCompounds(herbId: string): HerbCompound[] {
    const rows = this.db.prepare(`
      SELECT
        hc.herb_id,
        hc.compound_id,
        c.name as compound_name,
        hc.plant_part,
        hc.plant_part_code,
        hc.concentration_low_ppm,
        hc.concentration_high_ppm,
        COALESCE(hc.compound_class, c.compound_class) as compound_class
      FROM herb_compounds hc
      JOIN compounds c ON hc.compound_id = c.id
      WHERE hc.herb_id = ?
      ORDER BY hc.concentration_high_ppm DESC NULLS LAST, c.name
    `).all(herbId) as HerbCompound[];

    return rows;
  }

  // -------------------------------------------------------------------------
  // search-compounds: search by name, return herb + food associations
  // -------------------------------------------------------------------------

  searchCompounds(query: string, page = 1, pageSize = 10): PaginatedResult<Compound & { herb_count: number; food_count: number }> {
    const pattern = `%${query}%`;
    const offset = (page - 1) * pageSize;

    const countRow = this.db.prepare(`
      SELECT COUNT(*) as cnt FROM compounds WHERE name LIKE ? OR name_normalized LIKE ?
    `).get(pattern, pattern.toLowerCase().replace(/[^a-z0-9%]/g, '')) as { cnt: number };

    const rows = this.db.prepare(`
      SELECT c.*,
        (SELECT COUNT(DISTINCT hc.herb_id) FROM herb_compounds hc WHERE hc.compound_id = c.id) as herb_count,
        (SELECT COUNT(DISTINCT cf.food_name) FROM compound_foods cf WHERE cf.compound_id = c.id) as food_count
      FROM compounds c
      WHERE c.name LIKE ? OR c.name_normalized LIKE ?
      ORDER BY
        CASE WHEN c.name LIKE ? THEN 0 ELSE 1 END,
        c.name
      LIMIT ? OFFSET ?
    `).all(pattern, pattern.toLowerCase().replace(/[^a-z0-9%]/g, ''), pattern, pageSize, offset) as Array<Record<string, unknown>>;

    return {
      data: rows.map((r) => ({
        id: r.id as string,
        name: r.name as string,
        name_normalized: r.name_normalized as string,
        cas_number: r.cas_number as string | null,
        pubchem_cid: r.pubchem_cid as string | null,
        compound_class: r.compound_class as string | null,
        bioactivities: parseJsonArray(r.bioactivities as string),
        herb_count: r.herb_count as number,
        food_count: r.food_count as number,
      })),
      total: countRow.cnt,
      page,
      pageSize,
      hasMore: offset + pageSize < countRow.cnt,
    };
  }

  // -------------------------------------------------------------------------
  // get-compound-foods: foods containing a specific compound
  // -------------------------------------------------------------------------

  getCompoundFoods(compoundId: string, page = 1, pageSize = 20): PaginatedResult<CompoundFood> {
    const normalized = compoundId.toLowerCase().replace(/[^a-z0-9]/g, '');
    const offset = (page - 1) * pageSize;

    const countRow = this.db.prepare(`
      SELECT COUNT(*) as cnt FROM compound_foods
      WHERE compound_id = ? OR compound_id = ?
    `).get(compoundId, normalized) as { cnt: number };

    const rows = this.db.prepare(`
      SELECT cf.*, c.name as compound_name
      FROM compound_foods cf
      JOIN compounds c ON cf.compound_id = c.id
      WHERE cf.compound_id = ? OR cf.compound_id = ?
      ORDER BY cf.content_value DESC NULLS LAST, cf.food_name
      LIMIT ? OFFSET ?
    `).all(compoundId, normalized, pageSize, offset) as CompoundFood[];

    return {
      data: rows,
      total: countRow.cnt,
      page,
      pageSize,
      hasMore: offset + pageSize < countRow.cnt,
    };
  }

  // -------------------------------------------------------------------------
  // get-herb-food-overlap: foods sharing compounds with a given herb
  // -------------------------------------------------------------------------

  getHerbFoodOverlap(herbId: string, limit = 20): HerbFoodOverlap[] {
    const rows = this.db.prepare(`
      SELECT
        cf.food_name,
        cf.food_name_scientific,
        cf.food_group,
        COUNT(DISTINCT cf.compound_id) as shared_compounds,
        GROUP_CONCAT(DISTINCT c.name) as compound_names_csv
      FROM herb_compounds hc
      JOIN compound_foods cf ON hc.compound_id = cf.compound_id
      JOIN compounds c ON cf.compound_id = c.id
      WHERE hc.herb_id = ?
      GROUP BY cf.food_name
      ORDER BY shared_compounds DESC
      LIMIT ?
    `).all(herbId, limit) as Array<Record<string, unknown>>;

    // Calculate overlap score as shared / total herb compounds
    const totalCompoundsRow = this.db.prepare(`
      SELECT COUNT(DISTINCT compound_id) as cnt FROM herb_compounds WHERE herb_id = ?
    `).get(herbId) as { cnt: number };
    const totalCompounds = totalCompoundsRow.cnt || 1;

    return rows.map((r) => ({
      food_name: r.food_name as string,
      food_name_scientific: r.food_name_scientific as string | null,
      food_group: r.food_group as string | null,
      shared_compounds: r.shared_compounds as number,
      compound_names: (r.compound_names_csv as string || '').split(',').filter(Boolean),
      overlap_score: Math.round(((r.shared_compounds as number) / totalCompounds) * 100) / 100,
    }));
  }

  // -------------------------------------------------------------------------
  // search-by-bioactivity: herbs/compounds by health benefit
  // -------------------------------------------------------------------------

  searchByBioactivity(activity: string, page = 1, pageSize = 10): PaginatedResult<{
    compound: Compound;
    herbs: Array<{ id: string; common_name: string | null; scientific_name: string }>;
  }> {
    const pattern = `%${activity}%`;
    const offset = (page - 1) * pageSize;

    const countRow = this.db.prepare(`
      SELECT COUNT(*) as cnt FROM compounds WHERE bioactivities LIKE ?
    `).get(pattern) as { cnt: number };

    const compounds = this.db.prepare(`
      SELECT * FROM compounds WHERE bioactivities LIKE ?
      ORDER BY name
      LIMIT ? OFFSET ?
    `).all(pattern, pageSize, offset) as Array<Record<string, unknown>>;

    const herbStmt = this.db.prepare(`
      SELECT DISTINCT h.id, h.common_name, h.scientific_name
      FROM herb_compounds hc
      JOIN herbs h ON hc.herb_id = h.id
      WHERE hc.compound_id = ?
      LIMIT 10
    `);

    const results = compounds.map((c) => {
      const herbs = herbStmt.all(c.id as string) as Array<{
        id: string;
        common_name: string | null;
        scientific_name: string;
      }>;
      return {
        compound: {
          id: c.id as string,
          name: c.name as string,
          name_normalized: c.name_normalized as string,
          cas_number: c.cas_number as string | null,
          pubchem_cid: c.pubchem_cid as string | null,
          compound_class: c.compound_class as string | null,
          bioactivities: parseJsonArray(c.bioactivities as string),
        },
        herbs,
      };
    });

    return {
      data: results,
      total: countRow.cnt,
      page,
      pageSize,
      hasMore: offset + pageSize < countRow.cnt,
    };
  }

  // -------------------------------------------------------------------------
  // get-herb-profile: full herb monograph
  // -------------------------------------------------------------------------

  getHerbProfile(herbId: string): {
    herb: Herb;
    compound_count: number;
    top_compounds: HerbCompound[];
    bioactivity_summary: string[];
    food_overlap_count: number;
  } | null {
    const row = this.db.prepare('SELECT * FROM herbs WHERE id = ?').get(herbId) as Record<string, unknown> | undefined;
    if (!row) return null;

    const herb: Herb = {
      id: row.id as string,
      scientific_name: row.scientific_name as string,
      common_name: row.common_name as string | null,
      family: row.family as string | null,
      genus: row.genus as string | null,
      species: row.species as string | null,
      usage_type: row.usage_type as string | null,
      alternate_names: parseJsonArray(row.alternate_names as string),
      is_food_plant: !!(row.is_food_plant as number),
      is_edible: !!(row.is_edible as number),
    };

    const compoundCount = (this.db.prepare(
      'SELECT COUNT(DISTINCT compound_id) as cnt FROM herb_compounds WHERE herb_id = ?'
    ).get(herbId) as { cnt: number }).cnt;

    const topCompounds = this.getHerbCompounds(herbId).slice(0, 15);

    // Aggregate bioactivities from this herb's compounds
    const bioRows = this.db.prepare(`
      SELECT DISTINCT c.bioactivities
      FROM herb_compounds hc
      JOIN compounds c ON hc.compound_id = c.id
      WHERE hc.herb_id = ? AND c.bioactivities != '[]'
    `).all(herbId) as Array<{ bioactivities: string }>;

    const allActivities = new Set<string>();
    for (const r of bioRows) {
      for (const a of parseJsonArray(r.bioactivities)) {
        allActivities.add(a);
      }
    }

    const foodOverlapCount = (this.db.prepare(`
      SELECT COUNT(DISTINCT cf.food_name) as cnt
      FROM herb_compounds hc
      JOIN compound_foods cf ON hc.compound_id = cf.compound_id
      WHERE hc.herb_id = ?
    `).get(herbId) as { cnt: number }).cnt;

    return {
      herb,
      compound_count: compoundCount,
      top_compounds: topCompounds,
      bioactivity_summary: [...allActivities].sort().slice(0, 50),
      food_overlap_count: foodOverlapCount,
    };
  }

  // -------------------------------------------------------------------------
  // search-by-symptom: find herbs, compounds, and foods for a symptom
  // -------------------------------------------------------------------------

  searchBySymptom(query: string, page = 1, pageSize = 10): SymptomSearchResult {
    const pattern = `%${query}%`;

    // Find matching symptoms
    const symptoms = this.db.prepare(`
      SELECT * FROM symptoms WHERE name LIKE ?
      ORDER BY
        CASE WHEN name LIKE ? THEN 0 ELSE 1 END,
        name
      LIMIT 20
    `).all(pattern, pattern) as Array<Record<string, unknown>>;

    const matchedSymptoms: SymptomSearchResult['symptoms_matched'] = symptoms.map((s) => ({
      id: s.id as string,
      name: s.name as string,
      symptom_type: s.symptom_type as 'tcm' | 'modern' | 'bioactivity',
      mm_symptom_id: s.mm_symptom_id as string | null,
      description: s.description as string | null,
    }));

    if (matchedSymptoms.length === 0) {
      return { symptoms_matched: [], herbs: [], compounds: [], functional_foods: [] };
    }

    const symptomIds = matchedSymptoms.map((s) => s.id);
    const placeholders = symptomIds.map(() => '?').join(',');

    // Find herbs linked to these symptoms (via herb_symptoms)
    const herbs = this.db.prepare(`
      SELECT DISTINCT h.id, h.common_name, h.scientific_name, h.is_food_plant,
        (SELECT COUNT(DISTINCT compound_id) FROM herb_compounds WHERE herb_id = h.id) as compound_count
      FROM herb_symptoms hs
      JOIN herbs h ON hs.herb_id = h.id
      WHERE hs.symptom_id IN (${placeholders})
      ORDER BY compound_count DESC
      LIMIT ?
    `).all(...symptomIds, pageSize) as Array<Record<string, unknown>>;

    const herbResults: SymptomSearchResult['herbs'] = herbs.map((h) => ({
      id: h.id as string,
      common_name: h.common_name as string | null,
      scientific_name: h.scientific_name as string,
      is_food_plant: !!(h.is_food_plant as number),
      compound_count: h.compound_count as number,
    }));

    // Find compounds from those herbs that are linked to the bioactivity
    const herbIds = herbResults.map((h) => h.id);
    const herbPlaceholders = herbIds.length > 0 ? herbIds.map(() => '?').join(',') : "'__none__'";

    const compounds = herbIds.length > 0
      ? this.db.prepare(`
          SELECT DISTINCT c.id, c.name, c.compound_class, c.bioactivities,
            (SELECT COUNT(DISTINCT hc2.herb_id) FROM herb_compounds hc2 WHERE hc2.compound_id = c.id) as herb_count,
            (SELECT COUNT(DISTINCT cf.food_name) FROM compound_foods cf WHERE cf.compound_id = c.id) as food_count
          FROM herb_compounds hc
          JOIN compounds c ON hc.compound_id = c.id
          WHERE hc.herb_id IN (${herbPlaceholders})
          ORDER BY food_count DESC
          LIMIT 20
        `).all(...herbIds) as Array<Record<string, unknown>>
      : [];

    const compoundResults: SymptomSearchResult['compounds'] = compounds.map((c) => ({
      id: c.id as string,
      name: c.name as string,
      compound_class: c.compound_class as string | null,
      bioactivities: parseJsonArray(c.bioactivities as string),
      herb_count: c.herb_count as number,
      food_count: c.food_count as number,
    }));

    // Find functional foods — foods from food plants that share compounds with matched herbs
    const functionalFoods = herbIds.length > 0
      ? this.db.prepare(`
          SELECT cf.food_name, cf.food_group,
            COUNT(DISTINCT cf.compound_id) as shared_compounds,
            GROUP_CONCAT(DISTINCT c.name) as compound_names_csv
          FROM herb_compounds hc
          JOIN compound_foods cf ON hc.compound_id = cf.compound_id
          JOIN compounds c ON cf.compound_id = c.id
          WHERE hc.herb_id IN (${herbPlaceholders})
          GROUP BY cf.food_name
          ORDER BY shared_compounds DESC
          LIMIT 15
        `).all(...herbIds) as Array<Record<string, unknown>>
      : [];

    const foodResults: SymptomSearchResult['functional_foods'] = functionalFoods.map((f) => ({
      food_name: f.food_name as string,
      food_group: f.food_group as string | null,
      shared_compounds: f.shared_compounds as number,
      compound_names: (f.compound_names_csv as string || '').split(',').filter(Boolean),
    }));

    return {
      symptoms_matched: matchedSymptoms,
      herbs: herbResults,
      compounds: compoundResults,
      functional_foods: foodResults,
    };
  }

  // -------------------------------------------------------------------------
  // get-compound-targets: molecular targets for a compound
  // -------------------------------------------------------------------------

  getCompoundTargets(compoundId: string): CompoundTarget[] {
    const normalized = compoundId.toLowerCase().replace(/[^a-z0-9]/g, '');

    const rows = this.db.prepare(`
      SELECT ct.compound_id, c.name as compound_name,
        ct.target_id, t.name as target_name,
        ct.activity_value, ct.activity_type, ct.interaction_type
      FROM compound_targets ct
      JOIN compounds c ON ct.compound_id = c.id
      JOIN targets t ON ct.target_id = t.id
      WHERE ct.compound_id = ? OR ct.compound_id = ?
      ORDER BY ct.activity_value ASC NULLS LAST
    `).all(compoundId, normalized) as CompoundTarget[];

    return rows;
  }

  // -------------------------------------------------------------------------
  // find-functional-foods: food plants with therapeutic compound profiles
  // -------------------------------------------------------------------------

  findFunctionalFoods(query: string, page = 1, pageSize = 20): PaginatedResult<FunctionalFood> {
    const pattern = `%${query}%`;
    const offset = (page - 1) * pageSize;

    // Find herbs that are food plants matching the query
    const countRow = this.db.prepare(`
      SELECT COUNT(*) as cnt FROM herbs
      WHERE (is_food_plant = 1 OR is_edible = 1)
        AND (common_name LIKE ? OR scientific_name LIKE ? OR alternate_names LIKE ?)
    `).get(pattern, pattern, pattern) as { cnt: number };

    const herbs = this.db.prepare(`
      SELECT h.id, h.common_name, h.scientific_name,
        (SELECT COUNT(DISTINCT hc.compound_id) FROM herb_compounds hc WHERE hc.herb_id = h.id) as compound_count,
        (SELECT GROUP_CONCAT(DISTINCT c.name)
         FROM herb_compounds hc2 JOIN compounds c ON hc2.compound_id = c.id
         WHERE hc2.herb_id = h.id
         LIMIT 10) as compound_names_csv
      FROM herbs h
      WHERE (h.is_food_plant = 1 OR h.is_edible = 1)
        AND (h.common_name LIKE ? OR h.scientific_name LIKE ? OR h.alternate_names LIKE ?)
      ORDER BY compound_count DESC
      LIMIT ? OFFSET ?
    `).all(pattern, pattern, pattern, pageSize, offset) as Array<Record<string, unknown>>;

    // For each food herb, find the top foods it shares compounds with
    const results: FunctionalFood[] = [];
    for (const herb of herbs) {
      // Get foods that share compounds with this herb
      const foods = this.db.prepare(`
        SELECT cf.food_name, cf.food_group,
          COUNT(DISTINCT cf.compound_id) as compound_count,
          GROUP_CONCAT(DISTINCT c.name) as compound_names_csv
        FROM herb_compounds hc
        JOIN compound_foods cf ON hc.compound_id = cf.compound_id
        JOIN compounds c ON cf.compound_id = c.id
        WHERE hc.herb_id = ?
        GROUP BY cf.food_name
        ORDER BY compound_count DESC
        LIMIT 3
      `).all(herb.id as string) as Array<Record<string, unknown>>;

      if (foods.length > 0) {
        for (const food of foods) {
          results.push({
            food_name: food.food_name as string,
            food_group: food.food_group as string | null,
            herb_name: herb.common_name as string | null,
            herb_scientific_name: herb.scientific_name as string,
            compound_count: food.compound_count as number,
            compound_names: (food.compound_names_csv as string || '').split(',').filter(Boolean).slice(0, 10),
          });
        }
      } else {
        results.push({
          food_name: (herb.common_name as string) || (herb.scientific_name as string),
          food_group: null,
          herb_name: herb.common_name as string | null,
          herb_scientific_name: herb.scientific_name as string,
          compound_count: herb.compound_count as number,
          compound_names: (herb.compound_names_csv as string || '').split(',').filter(Boolean).slice(0, 10),
        });
      }
    }

    return {
      data: results,
      total: countRow.cnt,
      page,
      pageSize,
      hasMore: offset + pageSize < countRow.cnt,
    };
  }

  // -------------------------------------------------------------------------
  // Database stats for health check
  // -------------------------------------------------------------------------

  getStats(): Record<string, number> {
    const safeCount = (sql: string): number => {
      try {
        return (this.db.prepare(sql).get() as { cnt: number }).cnt;
      } catch {
        return 0;
      }
    };

    return {
      herbs: safeCount('SELECT COUNT(*) as cnt FROM herbs'),
      compounds: safeCount('SELECT COUNT(*) as cnt FROM compounds'),
      herb_compounds: safeCount('SELECT COUNT(*) as cnt FROM herb_compounds'),
      compound_foods: safeCount('SELECT COUNT(*) as cnt FROM compound_foods'),
      bridge_compounds: safeCount(`
        SELECT COUNT(DISTINCT c.id) as cnt FROM compounds c
        WHERE EXISTS (SELECT 1 FROM herb_compounds hc WHERE hc.compound_id = c.id)
          AND EXISTS (SELECT 1 FROM compound_foods cf WHERE cf.compound_id = c.id)
      `),
      symptoms: safeCount('SELECT COUNT(*) as cnt FROM symptoms'),
      herb_symptoms: safeCount('SELECT COUNT(*) as cnt FROM herb_symptoms'),
      targets: safeCount('SELECT COUNT(*) as cnt FROM targets'),
      compound_targets: safeCount('SELECT COUNT(*) as cnt FROM compound_targets'),
      food_plants: safeCount('SELECT COUNT(*) as cnt FROM herbs WHERE is_food_plant = 1'),
    };
  }
}
