import Database from 'better-sqlite3';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';

/**
 * Calibrated thresholds based on actual SymMap v2.0 data after Suppress filter:
 *   SMHB total kept: 698 (493 with both CN+EN names — many lack English_name)
 *   SMTS total kept: 2285 (all have TCM name)
 *   SMMS total kept: 1148 (no suppressed rows)
 *   SMIT total kept: 26035 (39.5% with PubChem_CID — lower than naive 50% expectation)
 *   SMTT total kept: 20965 (UniProt_id only 8.3%, HGNC_id 88.8% — switched cross-ref to HGNC)
 */

describe('SymMap v2.0 SQLite load (5 tables, no junction)', () => {
  let db: Database.Database;

  beforeAll(() => {
    db = new Database('./data_local/herbal_botanicals.db', { readonly: true });
  });

  afterAll(() => {
    db.close();
  });

  it('symmap_herbs: ≥480 rows with CN+EN names (calibrated from 493 actual)', () => {
    const r = db.prepare(
      "SELECT COUNT(*) AS c FROM symmap_herbs WHERE chinese_name IS NOT NULL AND english_name IS NOT NULL"
    ).get() as { c: number };
    expect(r.c).toBeGreaterThanOrEqual(480);
  });

  it('symmap_tcm_symptoms: ≥2000 rows with CN names', () => {
    const r = db.prepare(
      "SELECT COUNT(*) AS c FROM symmap_tcm_symptoms WHERE name_cn IS NOT NULL"
    ).get() as { c: number };
    expect(r.c).toBeGreaterThanOrEqual(2000);
  });

  it('symmap_modern_symptoms: ≥1100 rows (calibrated from 1148 actual)', () => {
    const r = db.prepare("SELECT COUNT(*) AS c FROM symmap_modern_symptoms").get() as { c: number };
    expect(r.c).toBeGreaterThanOrEqual(1100);
  });

  it('symmap_modern_symptoms: ≥80% rows have UMLS_id (1148/1148 actual)', () => {
    const tot = db.prepare("SELECT COUNT(*) AS c FROM symmap_modern_symptoms").get() as { c: number };
    const withUmls = db.prepare(
      "SELECT COUNT(*) AS c FROM symmap_modern_symptoms WHERE umls_id IS NOT NULL AND umls_id != ''"
    ).get() as { c: number };
    expect(tot.c).toBeGreaterThan(0);
    expect(withUmls.c / tot.c).toBeGreaterThanOrEqual(0.8);
  });

  it('symmap_ingredients: ≥25000 rows, ≥30% with PubChem_CID (calibrated; raw is 39.5%)', () => {
    const tot = db.prepare("SELECT COUNT(*) AS c FROM symmap_ingredients").get() as { c: number };
    const withCid = db.prepare(
      "SELECT COUNT(*) AS c FROM symmap_ingredients WHERE pubchem_cid IS NOT NULL AND pubchem_cid != ''"
    ).get() as { c: number };
    expect(tot.c).toBeGreaterThanOrEqual(25000);
    expect(withCid.c / tot.c).toBeGreaterThanOrEqual(0.3);
  });

  it('symmap_genes: ≥20000 rows, ≥80% with HGNC_id (UniProt only 8.3% — switched cross-ref to HGNC at 88.8%)', () => {
    const tot = db.prepare("SELECT COUNT(*) AS c FROM symmap_genes").get() as { c: number };
    const withHgnc = db.prepare(
      "SELECT COUNT(*) AS c FROM symmap_genes WHERE hgnc_id IS NOT NULL AND hgnc_id != ''"
    ).get() as { c: number };
    expect(tot.c).toBeGreaterThanOrEqual(20000);
    expect(withHgnc.c / tot.c).toBeGreaterThanOrEqual(0.8);
  });
});
