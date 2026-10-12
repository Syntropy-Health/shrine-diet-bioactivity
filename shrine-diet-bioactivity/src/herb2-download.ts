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
  },
): Promise<DetailResult<T>> {
  const details = new Map<string, T>();
  let pending = [...ids];
  for (let attempt = 1; attempt <= opts.attempts && pending.length > 0; attempt++) {
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
