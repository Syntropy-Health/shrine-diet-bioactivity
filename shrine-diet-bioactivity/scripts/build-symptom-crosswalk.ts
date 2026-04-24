/**
 * Build the Duke <-> SymMap symptom crosswalk (Subsystem A, Task 4).
 *
 * Duke's 47 bioactivity-derived symptoms are mapped onto two SymMap vocabularies:
 *   - SMMS (modern_symmap_*): English, ICD/UMLS-aligned -> primary high-fidelity target
 *   - SMTS (tcm_symmap_*):    Chinese + pinyin only   -> secondary TCM target
 *
 * Strategy (LLM-free, deterministic):
 *   1. SMMS exact name match (confidence "high")
 *   2. SMMS substring match against the most generic / shortest candidate
 *      that contains the Duke symptom token (confidence "medium")
 *   3. SMMS token-overlap fallback (confidence "low")
 *   4. SMTS exact pinyin/CN match for known TCM-relevant Duke symptoms
 *      (handled in the reviewer pass; the scaffolder leaves these as
 *      "unmatched" / "not_applicable")
 *
 * The scaffolder writes a draft JSON. A human reviewer must then upgrade
 * medium/low picks, drop spurious matches, and fill in TCM analogs by hand.
 *
 * Usage:
 *   npx tsx scripts/build-symptom-crosswalk.ts
 */

import Database from 'better-sqlite3';
import { writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadDataSources } from '../src/config.js';

type ModernConfidence = 'high' | 'medium' | 'low' | 'unmatched';
type TCMConfidence = 'high' | 'medium' | 'low' | 'unmatched' | 'not_applicable';

interface CrosswalkEntry {
  duke_id: string;
  duke_name: string;
  modern_symmap_id: string | null;
  modern_name: string | null;
  modern_umls_id: string | null;
  modern_confidence: ModernConfidence;
  tcm_symmap_id: string | null;
  tcm_name_en: string | null;
  tcm_name_cn: string | null;
  tcm_confidence: TCMConfidence;
  note: string;
}

interface DukeRow {
  id: string;
  name: string;
}

interface SmmsRow {
  symmap_id: string;
  name: string;
  umls_id: string | null;
}

const PKG_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function tokenize(s: string): string[] {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((t) => t.length >= 3);
}

function pickModernMatch(
  dukeName: string,
  smms: SmmsRow[],
): { row: SmmsRow | null; confidence: ModernConfidence; note: string } {
  const dukeLower = dukeName.toLowerCase().trim();
  // 1. Exact match
  for (const r of smms) {
    if (r.name.toLowerCase().trim() === dukeLower) {
      return { row: r, confidence: 'high', note: 'auto: exact SMMS name match' };
    }
  }
  // 2. Substring match: prefer the shortest SMMS name that contains the duke
  //    symptom as a whole word (avoids "Pain" matching "Pelvis Tumor")
  const dukeTokens = tokenize(dukeName);
  if (dukeTokens.length === 0) {
    return { row: null, confidence: 'unmatched', note: 'auto: empty token set' };
  }
  const allTokensJoined = dukeTokens.join(' ');
  const substrCandidates = smms
    .filter((r) => {
      const lower = r.name.toLowerCase();
      // require that all duke tokens appear in the SMMS name
      return dukeTokens.every((t) => lower.includes(t));
    })
    .sort((a, b) => a.name.length - b.name.length);
  if (substrCandidates.length > 0) {
    return {
      row: substrCandidates[0],
      confidence: 'medium',
      note: `auto: SMMS substring match for "${allTokensJoined}" -- REVIEW`,
    };
  }
  // 3. Token-overlap fallback: any token overlap, pick shortest name
  const tokenCandidates = smms
    .map((r) => {
      const lower = r.name.toLowerCase();
      const overlap = dukeTokens.filter((t) => lower.includes(t)).length;
      return { row: r, overlap };
    })
    .filter((c) => c.overlap > 0)
    .sort((a, b) => b.overlap - a.overlap || a.row.name.length - b.row.name.length);
  if (tokenCandidates.length > 0) {
    const best = tokenCandidates[0];
    return {
      row: best.row,
      confidence: 'low',
      note: `auto: SMMS token-overlap (${best.overlap}/${dukeTokens.length}) -- REVIEW`,
    };
  }
  return { row: null, confidence: 'unmatched', note: 'auto: no SMMS overlap -- REVIEW' };
}

function main(): void {
  const sources = loadDataSources();
  const dbPath = resolve(PKG_ROOT, sources.paths.sqlite_db);
  const outPath = resolve(PKG_ROOT, sources.paths.symptom_crosswalk);

  const db = new Database(dbPath, { readonly: true });
  const duke = db.prepare('SELECT id, name FROM symptoms ORDER BY id').all() as DukeRow[];
  const smms = db
    .prepare('SELECT symmap_id, name, umls_id FROM symmap_modern_symptoms WHERE name IS NOT NULL')
    .all() as SmmsRow[];
  db.close();

  const draft: CrosswalkEntry[] = duke.map((d) => {
    const m = pickModernMatch(d.name, smms);
    return {
      duke_id: d.id,
      duke_name: d.name,
      modern_symmap_id: m.row?.symmap_id ?? null,
      modern_name: m.row?.name ?? null,
      modern_umls_id: m.row?.umls_id ?? null,
      modern_confidence: m.confidence,
      tcm_symmap_id: null,
      tcm_name_en: null,
      tcm_name_cn: null,
      tcm_confidence: 'unmatched' as TCMConfidence,
      note: m.note,
    };
  });

  writeFileSync(outPath, JSON.stringify(draft, null, 2) + '\n');

  const tally: Record<ModernConfidence, number> = {
    high: 0,
    medium: 0,
    low: 0,
    unmatched: 0,
  };
  for (const e of draft) tally[e.modern_confidence] += 1;

  process.stdout.write(`wrote ${draft.length} entries to ${outPath}\n`);
  process.stdout.write(
    `modern tier: high=${tally.high} medium=${tally.medium} low=${tally.low} unmatched=${tally.unmatched}\n`,
  );
  process.stdout.write(
    `next step: REVIEWER PASS -- upgrade medium/low matches, fill in TCM analogs by hand\n`,
  );
}

main();
