import { describe, it, expect } from 'vitest';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import { buildToolDefs, FORBIDDEN_USECASE_VERBS } from '../tools.js';
import { LightRagClient } from '../lightrag_proxy.js';
import { AuditLog } from '../audit_log.js';

const __dirname_test = dirname(fileURLToPath(import.meta.url));

function fakeDeps() {
  const tmp = mkdtempSync(join(tmpdir(), 'mcp-catalog-'));
  return {
    client: new LightRagClient({
      baseUrl: 'http://localhost:9621',
      fetchImpl: (async () =>
        new Response('{}', { status: 200 })) as unknown as typeof fetch,
    }),
    audit: new AuditLog(join(tmp, 'audit.db')),
    tmpDir: tmp,
  };
}

describe('MCP tool catalog', () => {
  it('registers exactly 4 read-only thin-adapter tools + get-health', () => {
    const { client, audit, tmpDir } = fakeDeps();
    const defs = buildToolDefs({ client, audit });
    const names = defs.map((d) => d.name).sort();
    expect(names).toEqual(
      [
        'get-entity',
        'get-health',
        'get-subgraph',
        'list-labels',
        'semantic-search',
      ].sort(),
    );
    // [PRINCIPAL-RULED 2026-10-03] the KG is read-only: no tool may be a writer.
    expect(defs.filter((d) => d.readOnlyHint !== true).map((d) => d.name)).toEqual([]);
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it('never uses a clinical or culinary use-case verb in descriptions', () => {
    const { client, audit, tmpDir } = fakeDeps();
    const defs = buildToolDefs({ client, audit });
    for (const def of defs) {
      for (const verb of FORBIDDEN_USECASE_VERBS) {
        expect(
          def.description.toLowerCase(),
          `tool ${def.name} description must not contain verb "${verb}"`,
        ).not.toContain(verb.toLowerCase());
      }
    }
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it('every tool schema is a valid Zod raw shape', () => {
    const { client, audit, tmpDir } = fakeDeps();
    const defs = buildToolDefs({ client, audit });
    for (const def of defs) {
      expect(def.schema).toBeDefined();
      // Wrapping the raw shape in z.object should succeed.
      expect(() => z.object(def.schema)).not.toThrow();
    }
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it('no tool name contains a domain noun from the retired catalog', () => {
    const { client, audit, tmpDir } = fakeDeps();
    const defs = buildToolDefs({ client, audit });
    const retiredNames = [
      'search-herbs',
      'search-compounds',
      'get-herb-compounds',
      'get-compound-foods',
      'get-herb-food-overlap',
      'get-herb-profile',
      'search-by-bioactivity',
      'search-by-symptom',
      'find-functional-foods',
      'search-diseases',
      'get-target-diseases',
      'get-chemical-diseases',
      'get-compound-targets',
      'search-food-by-name',
    ];
    const names = new Set(defs.map((d) => d.name));
    for (const retired of retiredNames) {
      expect(names.has(retired)).toBe(false);
    }
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it('tools.ts header lists Phase 1 BioactivityEvidence vocabulary', () => {
    // Regression: the docstring listing the entity/edge vocabulary should
    // call out the Phase 1 drug-bioactive bridge so consumers know which
    // labels become queryable through the existing primitives.
    const src = readFileSync(
      join(__dirname_test, '..', 'tools.ts'),
      'utf8',
    );
    expect(src).toContain('BioactivityEvidence');
    expect(src).toContain('HAS_EVIDENCE');
    expect(src).toContain('EVIDENCE_FOR_TARGET');
  });
});
