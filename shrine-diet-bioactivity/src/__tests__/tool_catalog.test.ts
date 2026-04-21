import { describe, it, expect } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { z } from 'zod';
import { buildToolDefs, FORBIDDEN_USECASE_VERBS } from '../tools.js';
import { LightRagClient } from '../lightrag_proxy.js';
import { AuditLog } from '../audit_log.js';

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
  it('registers exactly 5 thin-adapter tools + get-health', () => {
    const { client, audit, tmpDir } = fakeDeps();
    const defs = buildToolDefs({ client, audit });
    const names = defs.map((d) => d.name).sort();
    expect(names).toEqual(
      [
        'get-entity',
        'get-health',
        'get-subgraph',
        'ingest-knowledge',
        'list-labels',
        'semantic-search',
      ].sort(),
    );
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
});
