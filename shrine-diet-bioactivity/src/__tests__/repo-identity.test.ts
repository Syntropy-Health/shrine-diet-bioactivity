import { execFileSync } from 'child_process';
import { readFileSync } from 'fs';
import { join, resolve } from 'path';
import { describe, expect, it } from 'vitest';

// The repo was renamed shrine-diet-bioactivity -> shrine-health-bioactivity (CTO
// #14051). GitHub redirects the old URL, but redirects are not forever, so no
// tracked text file may carry the old repo slug. Lives in the TS CI job because
// that job runs on EVERY PR (mcp-ci is paths-filtered).

const ROOT = resolve(__dirname, '../../..');
const OLD_SLUG = ['Syntropy-Health', 'shrine-diet-bioactivity'].join('/'); // not a literal match itself
// Binary snapshot that cannot be regenerated here (a rendered design doc).
const KNOWN_BINARY = new Set(['docs/shrine-bioactivity-graph-design-v2.pdf']);

function trackedFiles(): string[] {
  return execFileSync('git', ['ls-files', '-z'], { cwd: ROOT, encoding: 'utf8' })
    .split('\0')
    .filter(Boolean);
}

describe('repo identity after the rename', () => {
  it('no tracked text file carries the old GitHub repo slug', () => {
    const offenders: string[] = [];
    for (const rel of trackedFiles()) {
      if (KNOWN_BINARY.has(rel)) continue;
      let buf: Buffer;
      try {
        buf = readFileSync(join(ROOT, rel));
      } catch {
        continue; // submodule gitlinks / unreadable entries
      }
      if (buf.includes(0)) continue; // binary
      if (buf.toString('utf8').includes(OLD_SLUG)) offenders.push(rel);
    }
    expect(offenders).toEqual([]);
  });

  it('the npm package uses the new name and keeps the old bin as an alias', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT, 'shrine-diet-bioactivity/package.json'), 'utf8'));
    expect(pkg.name).toBe('shrine-health-bioactivity');
    expect(pkg.bin['shrine-health-bioactivity']).toBe('./build/index.js');
    // Existing MCP client configs invoke the old command name.
    expect(pkg.bin['shrine-diet-bioactivity']).toBe('./build/index.js');
  });
});
