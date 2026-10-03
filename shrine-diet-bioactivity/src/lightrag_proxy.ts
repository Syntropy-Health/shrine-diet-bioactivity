/**
 * Typed HTTP client for the scoped LightRAG wrapper
 * (`lightrag/scoped_server.py`). All MCP thin-adapter tools (read-only) fan out
 * through this module — the MCP server itself owns tenancy + audit and
 * keeps zero retrieval logic of its own.
 *
 * Wire contract:
 * - `POST /query`           — body: QueryRequest   → QueryResponse
 * - `GET  /graphs`          — query params         → SubgraphResponse
 * - `GET  /graph/label/popular` — query params     → string[]
 *
 * No write route: the server is read-only ([PRINCIPAL-RULED 2026-10-03]).
 */

import { z } from 'zod';

// ---------------------------------------------------------------------------
// Zod response schemas — `.safeParse` for defensive validation at the edge.
// ---------------------------------------------------------------------------

export const queryResponseSchema = z.object({
  response: z.string(),
  scope_filter: z.array(z.string()),
});
export type QueryResponse = z.infer<typeof queryResponseSchema>;

export const subgraphNodeSchema = z
  .object({
    entity_id: z.string().optional(),
    entity_type: z.string().optional(),
  })
  .passthrough();

export const subgraphResponseSchema = z
  .object({
    nodes: z.array(subgraphNodeSchema).default([]),
    edges: z.array(z.unknown()).default([]),
  })
  .passthrough();
export type SubgraphResponse = z.infer<typeof subgraphResponseSchema>;

export const popularLabelsResponseSchema = z.array(z.string());

// ---------------------------------------------------------------------------
// Request types
// ---------------------------------------------------------------------------

export type QueryMode = 'local' | 'global' | 'hybrid' | 'naive' | 'mix';

export interface QueryRequest {
  query: string;
  mode: QueryMode;
  top_k?: number;
  scope_filter: string[];
}

export interface GetSubgraphRequest {
  label: string;
  max_depth?: number;
  max_nodes?: number;
  scope_filter: string[];
}

export interface ListPopularLabelsRequest {
  limit?: number;
  scope_filter: string[];
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class LightRagProxyError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(message);
    this.name = 'LightRagProxyError';
  }
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export interface LightRagClientOptions {
  baseUrl: string;
  /** Defaults to global fetch. Override in tests. */
  fetchImpl?: typeof fetch;
  /** Defaults to 30_000ms. */
  timeoutMs?: number;
}

export class LightRagClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(opts: LightRagClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
  }

  async query(req: QueryRequest): Promise<QueryResponse> {
    const body = await this.postJson('/query', {
      query: req.query,
      mode: req.mode,
      top_k: req.top_k ?? 40,
      scope_filter: req.scope_filter,
    });
    return queryResponseSchema.parse(body);
  }

  async getSubgraph(req: GetSubgraphRequest): Promise<SubgraphResponse> {
    const params = new URLSearchParams({
      label: req.label,
      max_depth: String(req.max_depth ?? 1),
      max_nodes: String(req.max_nodes ?? 100),
      scope_filter: req.scope_filter.join(','),
    });
    const body = await this.getJson(`/graphs?${params.toString()}`);
    return subgraphResponseSchema.parse(body);
  }

  async listPopularLabels(req: ListPopularLabelsRequest): Promise<string[]> {
    const params = new URLSearchParams({
      limit: String(req.limit ?? 300),
      scope_filter: req.scope_filter.join(','),
    });
    const body = await this.getJson(
      `/graph/label/popular?${params.toString()}`,
    );
    return popularLabelsResponseSchema.parse(body);
  }

  // -------------------------------------------------------------------------
  // Private helpers
  // -------------------------------------------------------------------------

  private async postJson(
    path: string,
    body: Record<string, unknown>,
  ): Promise<unknown> {
    return this.requestJson(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  private async getJson(path: string): Promise<unknown> {
    return this.requestJson(path, { method: 'GET' });
  }

  private async requestJson(
    path: string,
    init: RequestInit,
  ): Promise<unknown> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const resp = await this.fetchImpl(url, {
        ...init,
        signal: controller.signal,
      });
      const payload = await resp.json().catch(() => null);
      if (!resp.ok) {
        throw new LightRagProxyError(
          `LightRAG proxy ${init.method ?? 'GET'} ${path} failed with ${resp.status}`,
          resp.status,
          payload,
        );
      }
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }
}
