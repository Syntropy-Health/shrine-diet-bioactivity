import Database from 'better-sqlite3';
import { readFileSync, existsSync } from 'fs';
import { resolve } from 'path';
import { describe, it, expect } from 'vitest';
import { loadDataSources } from '../config.js';

const sources = loadDataSources();
// loadDataSources() resolves config from <pkg>/config — but the symptom_crosswalk
// path inside data_sources.yaml is recorded relative to the package root
// (e.g. "../research-journal/shared/symptom_crosswalk.json").
const PKG_ROOT = resolve(__dirname, '..', '..');
const CROSSWALK = resolve(PKG_ROOT, sources.paths.symptom_crosswalk);
const DB_PATH = resolve(PKG_ROOT, sources.paths.sqlite_db);

interface Entry {
  duke_id: string;
  duke_name: string;
  modern_symmap_id: string | null;
  modern_name: string | null;
  modern_umls_id: string | null;
  modern_confidence: 'high' | 'medium' | 'low' | 'unmatched';
  tcm_symmap_id: string | null;
  tcm_name_en: string | null;
  tcm_name_cn: string | null;
  tcm_confidence: 'high' | 'medium' | 'low' | 'unmatched' | 'not_applicable';
  note: string;
}

describe('Duke<->SymMap symptom crosswalk', () => {
  it('exists and covers all 47 Duke symptoms', () => {
    expect(existsSync(CROSSWALK)).toBe(true);
    const db = new Database(DB_PATH, { readonly: true });
    const dukeIds = db
      .prepare('SELECT id FROM symptoms')
      .all()
      .map((r) => (r as { id: string }).id);
    db.close();
    const crosswalk = JSON.parse(readFileSync(CROSSWALK, 'utf8')) as Entry[];
    expect(crosswalk.length).toBe(dukeIds.length);
    const covered = new Set(crosswalk.map((e) => e.duke_id));
    for (const id of dukeIds) expect(covered.has(id)).toBe(true);
  });

  it('every matched modern_symmap_id references a valid SMMS row', () => {
    const db = new Database(DB_PATH, { readonly: true });
    const smmsIds = new Set(
      db
        .prepare('SELECT symmap_id FROM symmap_modern_symptoms')
        .all()
        .map((r) => (r as { symmap_id: string }).symmap_id),
    );
    db.close();
    const crosswalk = JSON.parse(readFileSync(CROSSWALK, 'utf8')) as Entry[];
    for (const e of crosswalk) {
      if (e.modern_symmap_id !== null) expect(smmsIds.has(e.modern_symmap_id)).toBe(true);
    }
  });

  it('every matched tcm_symmap_id references a valid SMTS row', () => {
    const db = new Database(DB_PATH, { readonly: true });
    const smtsIds = new Set(
      db
        .prepare('SELECT symmap_id FROM symmap_tcm_symptoms')
        .all()
        .map((r) => (r as { symmap_id: string }).symmap_id),
    );
    db.close();
    const crosswalk = JSON.parse(readFileSync(CROSSWALK, 'utf8')) as Entry[];
    for (const e of crosswalk) {
      if (e.tcm_symmap_id !== null) expect(smtsIds.has(e.tcm_symmap_id)).toBe(true);
    }
  });

  it('at least 30 of 47 Duke symptoms have a modern match', () => {
    const crosswalk = JSON.parse(readFileSync(CROSSWALK, 'utf8')) as Entry[];
    const matched = crosswalk.filter((e) => e.modern_symmap_id !== null);
    expect(matched.length).toBeGreaterThanOrEqual(30);
  });

  it('every entry has a non-empty reviewer note', () => {
    const crosswalk = JSON.parse(readFileSync(CROSSWALK, 'utf8')) as Entry[];
    for (const e of crosswalk) {
      expect(typeof e.note).toBe('string');
      expect(e.note.trim().length).toBeGreaterThan(0);
    }
  });
});
