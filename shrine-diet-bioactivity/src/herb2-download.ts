/**
 * Integrity helpers for scripts/download-herb2.ts (#125 review R5).
 *
 * The download script skips any output file that already exists, and CI caches
 * `data/` under a downloads key. So a file that is present but INCOMPLETE is
 * reused as complete forever. Two ways that used to happen:
 *
 *   1. a kill (e.g. the step timeout) during a direct writeFileSync left a
 *      truncated file — fixed by writing to a temp file and renaming;
 *   2. a herb whose detail fetch failed was stored as "no evidence"
 *      ({herb_disease: [], drug_paper_disease: []}) — fixed by retrying failed
 *      herbs and refusing to write the details file while any still fail.
 */
import { renameSync, writeFileSync } from 'fs';

/** Write JSON so the target path holds either the old file or the complete new one. */
export function writeJsonAtomic(path: string, value: unknown): void {
  const tmp = `${path}.tmp-${process.pid}`;
  writeFileSync(tmp, JSON.stringify(value, null, 2), 'utf8');
  renameSync(tmp, path); // atomic on the same filesystem
}

export type DetailResult<T> = {
  details: Map<string, T>;
  /** herb ids that still failed after every attempt — never written as empty. */
  failed: string[];
};

/**
 * Fetch every id with bounded concurrency; ids that fail are retried up to
 * `attempts` times in total. A failure is reported in `failed`, never stored as
 * an empty result.
 */
export async function collectDetails<T>(
  ids: string[],
  fetchOne: (id: string) => Promise<T>,
  opts: {
    concurrency: number;
    attempts: number;
    onProgress?: (done: number, total: number) => void;
    /** polite pause: wait `ms` after every `every` completed requests */
    throttle?: { every: number; ms: number };
    /** wait before retry round k+2 (index k); default none. Spaces retries out of a 429/503 window. */
    retryDelaysMs?: number[];
  },
): Promise<DetailResult<T>> {
  const details = new Map<string, T>();
  let pending = [...ids];
  for (let attempt = 1; attempt <= opts.attempts && pending.length > 0; attempt++) {
    if (attempt > 1) {
      const wait = opts.retryDelaysMs?.[attempt - 2] ?? 0;
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    }
    const failedThisRound: string[] = [];
    let idx = 0;
    let done = 0;
    const round = pending;
    const worker = async (): Promise<void> => {
      while (idx < round.length) {
        const id = round[idx++];
        try {
          details.set(id, await fetchOne(id));
        } catch {
          failedThisRound.push(id);
        }
        done += 1;
        opts.onProgress?.(done, round.length);
        if (opts.throttle && done % opts.throttle.every === 0) {
          await new Promise((r) => setTimeout(r, opts.throttle!.ms));
        }
      }
    };
    await Promise.all(Array.from({ length: Math.max(1, opts.concurrency) }, () => worker()));
    pending = failedThisRound;
  }
  return { details, failed: pending };
}

/**
 * MEASURED 2026-10-12 against detail_api: every real herb — including one with no
 * evidence — returns an object carrying BOTH keys (header-only arrays when empty);
 * an unknown id returns an HTML 500. So a response with neither key is a failure
 * (e.g. a 200 error body), never "no evidence", and must throw so it is retried.
 */
export function assertDetailShape(herbId: string, data: unknown): asserts data is Record<string, unknown> {
  if (
    !data ||
    typeof data !== 'object' ||
    Array.isArray(data) ||
    (!('herb_disease' in data) && !('drug_paper_disease' in data))
  ) {
    throw new Error(`malformed detail_api response for ${herbId}`);
  }
}

/** A paginated list that stops early must not be written as complete. */
export function assertCompleteHerbList(fetched: number, total: number): void {
  if (!Number.isFinite(total) || total <= 0) throw new Error(`browse_api reported no total (got ${total})`);
  if (fetched < total) throw new Error(`herb list incomplete: ${fetched} of ${total}`);
}

/** Output in INPUT order, so the file is stable across runs (retries finish last). */
export function inInputOrder<T>(ids: string[], details: Map<string, T>): Record<string, T> {
  return Object.fromEntries(ids.filter((id) => details.has(id)).map((id) => [id, details.get(id) as T]));
}
