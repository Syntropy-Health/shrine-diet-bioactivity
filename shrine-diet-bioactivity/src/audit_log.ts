/**
 * SQLite-backed audit log for MCP tool invocations.
 *
 * One row per tool call. Schema + semantics mirror the Python
 * ``audit_log.py`` in ``lightrag/`` so both sides can read each other's
 * output and a single ``mcp_audit.db`` file survives the TS → Python
 * boundary.
 *
 * Writes are fire-and-forget: a SQLite error NEVER propagates out of
 * this module.  Audit failure must not break a tool call.
 */

import { createHash } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import Database from 'better-sqlite3';

export interface AuditRow {
  tool: string;
  scope_filter: string[];
  tenant_id: string | null;
  query_hash: string | null;
  result_count: number | null;
  token_usage: number | null;
  status: 'ok' | 'error' | 'invalid_tenant';
  error_class: string | null;
  latency_ms: number;
}

export interface RecordContext {
  tool: string;
  scope_filter: string[];
  tenant_id: string | null;
  /** Query body — hashed, not stored verbatim. */
  query_body?: unknown;
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS mcp_audit (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL,
  tenant_id     TEXT,
  tool          TEXT NOT NULL,
  query_hash    TEXT,
  scope_filter  TEXT NOT NULL,
  latency_ms    INTEGER NOT NULL,
  result_count  INTEGER,
  token_usage   INTEGER,
  status        TEXT NOT NULL,
  error_class   TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts ON mcp_audit(tenant_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON mcp_audit(ts);
`;

export class AuditLog {
  private db: Database.Database | null = null;

  constructor(private readonly dbPath: string) {
    this.openQuietly();
  }

  emit(row: AuditRow): void {
    try {
      if (!this.db) this.openQuietly();
      if (!this.db) return; // open failed — swallow
      this.db
        .prepare(
          `INSERT INTO mcp_audit (
             ts, tenant_id, tool, query_hash, scope_filter,
             latency_ms, result_count, token_usage, status, error_class
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .run(
          new Date().toISOString(),
          row.tenant_id,
          row.tool,
          row.query_hash,
          JSON.stringify(row.scope_filter),
          row.latency_ms,
          row.result_count,
          row.token_usage,
          row.status,
          row.error_class,
        );
    } catch (err) {
      this.warn('emit', err);
    }
  }

  /**
   * Time an async operation and emit one audit row.
   * Re-throws the inner error, but still emits a `status='error'` row.
   */
  async record<T>(ctx: RecordContext, fn: () => Promise<T>): Promise<T> {
    const started = process.hrtime.bigint();
    const queryHash =
      ctx.query_body !== undefined ? hashQueryBody(ctx.query_body) : null;

    try {
      const result = await fn();
      const latencyMs = Number(
        (process.hrtime.bigint() - started) / 1_000_000n,
      );
      this.emit({
        tool: ctx.tool,
        scope_filter: ctx.scope_filter,
        tenant_id: ctx.tenant_id,
        query_hash: queryHash,
        result_count: this.inferResultCount(result),
        token_usage: null,
        status: 'ok',
        error_class: null,
        latency_ms: latencyMs,
      });
      return result;
    } catch (err: unknown) {
      const latencyMs = Number(
        (process.hrtime.bigint() - started) / 1_000_000n,
      );
      this.emit({
        tool: ctx.tool,
        scope_filter: ctx.scope_filter,
        tenant_id: ctx.tenant_id,
        query_hash: queryHash,
        result_count: null,
        token_usage: null,
        status: 'error',
        error_class: err instanceof Error ? err.constructor.name : 'Unknown',
        latency_ms: latencyMs,
      });
      throw err;
    }
  }

  // -------------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------------

  private openQuietly(): void {
    try {
      mkdirSync(dirname(this.dbPath), { recursive: true });
      this.db = new Database(this.dbPath);
      this.db.exec(SCHEMA);
    } catch (err) {
      this.warn('open', err);
      this.db = null;
    }
  }

  private inferResultCount(result: unknown): number | null {
    if (Array.isArray(result)) return result.length;
    if (result && typeof result === 'object') {
      const maybeNodes = (result as { nodes?: unknown[] }).nodes;
      if (Array.isArray(maybeNodes)) return maybeNodes.length;
    }
    return null;
  }

  private warn(context: string, err: unknown): void {
    // Intentional stderr — audit is infra, not user-facing.
    process.stderr.write(
      `[audit-log] WARN (${context}) at ${this.dbPath}: ${
        err instanceof Error ? err.message : String(err)
      }\n`,
    );
  }
}

/**
 * SHA-256 hex digest of the JSON-normalised body.  Keys are sorted so
 * semantically-equal objects hash identically.  Never throws.
 */
export function hashQueryBody(body: unknown): string {
  let payload: string;
  try {
    payload = stableStringify(body);
  } catch {
    payload = String(body);
  }
  return createHash('sha256').update(payload).digest('hex');
}

function stableStringify(value: unknown): string {
  const seen = new WeakSet<object>();
  return JSON.stringify(value, function replace(_key, val: unknown) {
    if (val && typeof val === 'object') {
      if (seen.has(val as object)) return '[Circular]';
      seen.add(val as object);
      if (!Array.isArray(val)) {
        const sorted: Record<string, unknown> = {};
        for (const k of Object.keys(val as Record<string, unknown>).sort()) {
          sorted[k] = (val as Record<string, unknown>)[k];
        }
        return sorted;
      }
    }
    return val;
  });
}
