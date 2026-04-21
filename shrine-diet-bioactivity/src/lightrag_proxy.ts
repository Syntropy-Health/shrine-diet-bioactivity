/**
 * Typed HTTP client for the scoped LightRAG wrapper
 * (`lightrag/scoped_server.py`). All 5 MCP thin-adapter tools fan out
 * through this module — the MCP server itself owns tenancy + audit and
 * keeps zero retrieval logic of its own.
 *
 * Wire contract:
 * - `POST /query`           — body: QueryRequest   → QueryResponse
 * - `GET  /graphs`          — query params         → SubgraphResponse
 * - `GET  /graph/label/popular` — query params     → string[]
 * - `POST /documents/custom_kg` — body: IngestReq  → IngestResponse
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

export const ingestResponseSchema = z.object({
  ingested: z.object({
    entities: z.number().int().nonnegative(),
    relationships: z.number().int().nonnegative(),
  }),
  scope: z.string(),
});
export type IngestResponse = z.infer<typeof ingestResponseSchema>;

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

export interface CustomKGEntity {
  entity_name: string;
  entity_type: string;
  description?: string;
  source_id?: string;
}

export interface CustomKGRelationship {
  src_id: string;
  tgt_id: string;
  description?: string;
  keywords?: string;
  weight?: number;
  source_id?: string;
}

export interface IngestCustomKGRequest {
  scope_filter: string[];
  custom_kg: {
    entities: CustomKGEntity[];
    relationships: CustomKGRelationship[];
  };
  source_label?: string;
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

  async ingestCustomKG(req: IngestCustomKGRequest): Promise<IngestResponse> {
    const body = await this.postJson('/documents/custom_kg', {
      scope_filter: req.scope_filter,
      custom_kg: req.custom_kg,
      source_label: req.source_label,
    });
    return ingestResponseSchema.parse(body);
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
