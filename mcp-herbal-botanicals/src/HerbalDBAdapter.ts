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
  HerbFoodOverlap,
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
  // Database stats for health check
  // -------------------------------------------------------------------------

  getStats(): Record<string, number> {
    return {
      herbs: (this.db.prepare('SELECT COUNT(*) as cnt FROM herbs').get() as { cnt: number }).cnt,
      compounds: (this.db.prepare('SELECT COUNT(*) as cnt FROM compounds').get() as { cnt: number }).cnt,
      herb_compounds: (this.db.prepare('SELECT COUNT(*) as cnt FROM herb_compounds').get() as { cnt: number }).cnt,
      compound_foods: (this.db.prepare('SELECT COUNT(*) as cnt FROM compound_foods').get() as { cnt: number }).cnt,
      bridge_compounds: (this.db.prepare(`
        SELECT COUNT(DISTINCT c.id) as cnt FROM compounds c
        WHERE EXISTS (SELECT 1 FROM herb_compounds hc WHERE hc.compound_id = c.id)
          AND EXISTS (SELECT 1 FROM compound_foods cf WHERE cf.compound_id = c.id)
      `).get() as { cnt: number }).cnt,
    };
  }
}
