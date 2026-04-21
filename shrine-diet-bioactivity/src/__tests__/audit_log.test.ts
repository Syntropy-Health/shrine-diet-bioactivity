import { describe, it, expect, beforeEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import Database from 'better-sqlite3';
import { AuditLog, hashQueryBody } from '../audit_log.js';

let tmpDir: string;
let dbPath: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'mcp-audit-test-'));
  dbPath = join(tmpDir, 'mcp_audit.db');
});

function readRows(path: string): Array<Record<string, unknown>> {
  const db = new Database(path, { readonly: true });
  try {
    return db.prepare('SELECT * FROM mcp_audit ORDER BY id ASC').all() as Array<
      Record<string, unknown>
    >;
  } finally {
    db.close();
  }
}

describe('AuditLog.emit', () => {
  it('creates the schema on first use', () => {
    const audit = new AuditLog(dbPath);
    audit.emit({
      tool: 'semantic-search',
      scope_filter: ['shared'],
      tenant_id: null,
      query_hash: null,
      result_count: 0,
      token_usage: null,
      status: 'ok',
      error_class: null,
      latency_ms: 10,
    });
    const rows = readRows(dbPath);
    expect(rows).toHaveLength(1);
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it('persists every audit field in the expected shape', () => {
    const audit = new AuditLog(dbPath);
    audit.emit({
      tool: 'get-subgraph',
      scope_filter: ['shared', 'tenant:clinic-a'],
      tenant_id: 'clinic-a',
      query_hash: 'abc123',
      result_count: 5,
      token_usage: 1200,
      status: 'ok',
      error_class: null,
      latency_ms: 42,
    });
    const [row] = readRows(dbPath);
    expect(row.tool).toBe('get-subgraph');
    expect(row.tenant_id).toBe('clinic-a');
    expect(row.query_hash).toBe('abc123');
    expect(JSON.parse(row.scope_filter as string)).toEqual([
      'shared',
      'tenant:clinic-a',
    ]);
    expect(row.latency_ms).toBe(42);
    expect(row.result_count).toBe(5);
    expect(row.token_usage).toBe(1200);
    expect(row.status).toBe('ok');
    expect(row.error_class).toBeNull();
    expect(typeof row.ts).toBe('string');
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it('never throws if the db path is unwritable', () => {
    const audit = new AuditLog('/nonexistent/directory/audit.db');
    expect(() =>
      audit.emit({
        tool: 'x',
        scope_filter: ['shared'],
        tenant_id: null,
        query_hash: null,
        result_count: null,
        token_usage: null,
        status: 'ok',
        error_class: null,
        latency_ms: 1,
      }),
    ).not.toThrow();
  });

  it('appends multiple rows in order', () => {
    const audit = new AuditLog(dbPath);
    for (const tool of ['a', 'b', 'c']) {
      audit.emit({
        tool,
        scope_filter: ['shared'],
        tenant_id: null,
        query_hash: null,
        result_count: null,
        token_usage: null,
        status: 'ok',
        error_class: null,
        latency_ms: 1,
      });
    }
    const rows = readRows(dbPath);
    expect(rows.map((r) => r.tool)).toEqual(['a', 'b', 'c']);
    rmSync(tmpDir, { recursive: true, force: true });
  });
});

describe('AuditLog.record', () => {
  it('emits one row with latency + ok status on success', async () => {
    const audit = new AuditLog(dbPath);
    const result = await audit.record(
      {
        tool: 'semantic-search',
        scope_filter: ['shared'],
        tenant_id: null,
        query_body: { query: 'x' },
      },
      async () => ({ items: [1, 2, 3] }),
    );
    expect(result.items).toEqual([1, 2, 3]);
    const [row] = readRows(dbPath);
    expect(row.status).toBe('ok');
    expect(Number(row.latency_ms)).toBeGreaterThanOrEqual(0);
    expect(row.query_hash).toEqual(hashQueryBody({ query: 'x' }));
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it('emits error row and re-throws on failure', async () => {
    const audit = new AuditLog(dbPath);
    await expect(
      audit.record(
        {
          tool: 'get-entity',
          scope_filter: ['shared'],
          tenant_id: null,
          query_body: { id: 'x' },
        },
        async () => {
          throw new TypeError('bad input');
        },
      ),
    ).rejects.toThrow(TypeError);
    const [row] = readRows(dbPath);
    expect(row.status).toBe('error');
    expect(row.error_class).toBe('TypeError');
    rmSync(tmpDir, { recursive: true, force: true });
  });
});

describe('hashQueryBody', () => {
  it('returns the same hash for semantically-equal bodies', () => {
    expect(hashQueryBody({ a: 1, b: 2 })).toBe(hashQueryBody({ b: 2, a: 1 }));
  });

  it('returns different hashes for different bodies', () => {
    expect(hashQueryBody({ a: 1 })).not.toBe(hashQueryBody({ a: 2 }));
  });

  it('handles non-JSON-serialisable values without throwing', () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(() => hashQueryBody(circular)).not.toThrow();
  });
});
