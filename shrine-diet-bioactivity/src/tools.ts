/**
 * MCP tool definitions for the shrine-diet-bioactivity thin-adapter.
 *
 * Every tool in this catalog is a domain-agnostic pass-through to the
 * scoped LightRAG wrapper (``lightrag/scoped_server.py``).  Clinical /
 * culinary reasoning lives in the agent layer — see
 * ``docs/clinical-integration-notes.md``.
 *
 * The 4 primitives are (read-only):
 *
 *   1. ``semantic-search``   — POST /query, 5 modes, scope-filtered
 *   2. ``get-entity``        — GET /graphs?label&max_depth=0
 *   3. ``get-subgraph``      — GET /graphs?label&max_depth=N&max_nodes=M
 *   4. ``list-labels``       — GET /graph/label/popular?limit=N
 *
 * There is no write tool: [PRINCIPAL-RULED 2026-10-03] the KG is read-only
 * shared data, so the former ``ingest-knowledge`` tenant write tool was removed.
 *
 * Plus ``get-health`` — server-only, no data.
 *
 * Entity vocabulary surfaced through these primitives (post-ingest):
 *
 *   Domain:  Herb, Compound, Food, Target, Disease, Symptom,
 *            BioactivityEvidence  ← Phase 1 (ChEMBL drug-target evidence)
 *   Tenant:  Protocol, Intervention, Outcome, Biomarker
 *
 * Relationships (selected):
 *   CONTAINS_COMPOUND, FOUND_IN_FOOD, TARGETS_PROTEIN,
 *   ASSOCIATED_WITH_DISEASE, TREATS_SYMPTOM,
 *   HAS_EVIDENCE, EVIDENCE_FOR_TARGET   ← Phase 1
 *
 * See docs/adr/0007-compound-identity-bridge.md for details.
 */

import { z } from 'zod';
import type { AuditLog } from './audit_log.js';
import type { LightRagClient } from './lightrag_proxy.js';
import {
  buildScopeParam,
  extractTenantContext,
  validateTenantId,
} from './tenant.js';

/**
 * Verbs that must not appear in any thin-adapter tool description.
 * Tool descriptions lead with ontology + retrieval mode — use-case
 * language belongs in the agent layer.  The guard catches regressions
 * that would drag clinical / culinary intent back into the MCP surface.
 */
export const FORBIDDEN_USECASE_VERBS: readonly string[] = [
  'find protocols',
  'find functional',
  'search-by-bioactivity',
  'search-by-symptom',
  'find-functional-foods',
  'get-contraindications',
  'get-intervention-outcomes',
  'get-clinical-context',
  'meal plan',
  'food plan',
  'intervention outcome',
  'contraindication',
  'biomarker protocol',
  'recipe',
] as const;

export type McpToolContent = {
  content: Array<{ type: 'text'; text: string }>;
  structuredContent?: { [x: string]: unknown };
  isError?: boolean;
};

export interface ToolDef<Args extends Record<string, unknown>> {
  name: string;
  description: string;
  schema: z.ZodRawShape;
  title: string;
  readOnlyHint: boolean;
  handler: (
    args: Args,
    meta: Record<string, unknown> | undefined,
  ) => Promise<McpToolContent>;
}

export interface ToolDeps {
  client: LightRagClient;
  audit: AuditLog;
}

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

const QueryModeSchema = z.enum(['local', 'global', 'hybrid', 'naive', 'mix']);

const SemanticSearchSchema = {
  query: z.string().min(1),
  mode: QueryModeSchema.optional().default('hybrid'),
  top_k: z.number().int().min(1).max(200).optional().default(40),
};

const GetEntitySchema = {
  entity_id: z.string().min(1),
};

const GetSubgraphSchema = {
  entity_id: z.string().min(1),
  max_depth: z.number().int().min(1).max(3).optional().default(1),
  max_nodes: z.number().int().min(1).max(1000).optional().default(100),
};

const ListLabelsSchema = {
  limit: z.number().int().min(1).max(1000).optional().default(300),
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function textResult(value: unknown): McpToolContent {
  const text = JSON.stringify(value, null, 2);
  const structured: { [x: string]: unknown } =
    value !== null && typeof value === 'object' && !Array.isArray(value)
      ? (value as { [x: string]: unknown })
      : { value };
  return {
    content: [{ type: 'text', text }],
    structuredContent: structured,
  };
}

function errorResult(err: unknown): McpToolContent {
  const message = err instanceof Error ? err.message : 'Internal error';
  return { content: [{ type: 'text', text: message }], isError: true };
}

function tenantScope(meta: Record<string, unknown> | undefined): {
  scopeFilter: string[];
  tenantId: string | null;
} {
  const ctx = extractTenantContext(meta);
  validateTenantId(ctx.tenantId);
  return { scopeFilter: buildScopeParam(ctx).scope_filter, tenantId: ctx.tenantId };
}

// ---------------------------------------------------------------------------
// Build the catalog
// ---------------------------------------------------------------------------

export function buildToolDefs(deps: ToolDeps): ToolDef<Record<string, unknown>>[] {
  const { client, audit } = deps;

  const semanticSearch: ToolDef<{
    query: string;
    mode: 'local' | 'global' | 'hybrid' | 'naive' | 'mix';
    top_k: number;
  }> = {
    name: 'semantic-search',
    description:
      'Retrieve entities and relations from the knowledge graph for a natural-language query. Modes map to LightRAG retrieval strategies: local (entity-focused), global (community summaries), hybrid (both), mix (KG + vector), naive (vector only). Results are scope-filtered to shared + the caller tenant.',
    schema: SemanticSearchSchema,
    title: 'Semantic KG search',
    readOnlyHint: true,
    handler: async (args, meta) => {
      try {
        const { scopeFilter, tenantId } = tenantScope(meta);
        return await audit.record(
          {
            tool: 'semantic-search',
            scope_filter: scopeFilter,
            tenant_id: tenantId,
            query_body: args,
          },
          async () => {
            const result = await client.query({
              query: args.query,
              mode: args.mode,
              top_k: args.top_k,
              scope_filter: scopeFilter,
            });
            return textResult(result);
          },
        );
      } catch (err) {
        return errorResult(err);
      }
    },
  };

  const getEntity: ToolDef<{ entity_id: string }> = {
    name: 'get-entity',
    description:
      'Look up a single entity by id. Returns the node with its properties if it exists in the caller scope; null otherwise. Pass-through to LightRAG graph route at depth 0.',
    schema: GetEntitySchema,
    title: 'Get entity by id',
    readOnlyHint: true,
    handler: async (args, meta) => {
      try {
        const { scopeFilter, tenantId } = tenantScope(meta);
        return await audit.record(
          {
            tool: 'get-entity',
            scope_filter: scopeFilter,
            tenant_id: tenantId,
            query_body: args,
          },
          async () => {
            const result = await client.getSubgraph({
              label: args.entity_id,
              max_depth: 0,
              max_nodes: 1,
              scope_filter: scopeFilter,
            });
            const entity = result.nodes[0] ?? null;
            return textResult({ entity });
          },
        );
      } catch (err) {
        return errorResult(err);
      }
    },
  };

  const getSubgraph: ToolDef<{
    entity_id: string;
    max_depth: number;
    max_nodes: number;
  }> = {
    name: 'get-subgraph',
    description:
      'Return the connected subgraph around an entity up to max_depth hops with at most max_nodes nodes. Pass-through to LightRAG graph route. Scope-filtered.',
    schema: GetSubgraphSchema,
    title: 'Expand entity neighborhood',
    readOnlyHint: true,
    handler: async (args, meta) => {
      try {
        const { scopeFilter, tenantId } = tenantScope(meta);
        return await audit.record(
          {
            tool: 'get-subgraph',
            scope_filter: scopeFilter,
            tenant_id: tenantId,
            query_body: args,
          },
          async () => {
            const result = await client.getSubgraph({
              label: args.entity_id,
              max_depth: args.max_depth,
              max_nodes: args.max_nodes,
              scope_filter: scopeFilter,
            });
            return textResult(result);
          },
        );
      } catch (err) {
        return errorResult(err);
      }
    },
  };

  const listLabels: ToolDef<{ limit: number }> = {
    name: 'list-labels',
    description:
      'Return the most connected entity labels visible in the caller scope. Use to discover the ontology shape (entity types and exemplars) without sending a query. Pass-through to LightRAG /graph/label/popular.',
    schema: ListLabelsSchema,
    title: 'List popular labels in scope',
    readOnlyHint: true,
    handler: async (args, meta) => {
      try {
        const { scopeFilter, tenantId } = tenantScope(meta);
        return await audit.record(
          {
            tool: 'list-labels',
            scope_filter: scopeFilter,
            tenant_id: tenantId,
            query_body: args,
          },
          async () => {
            const labels = await client.listPopularLabels({
              limit: args.limit,
              scope_filter: scopeFilter,
            });
            return textResult({ labels });
          },
        );
      } catch (err) {
        return errorResult(err);
      }
    },
  };

  const getHealth: ToolDef<Record<string, never>> = {
    name: 'get-health',
    description:
      'Report server status. Returns the scoped LightRAG wrapper health and adapter version. No data access.',
    schema: {},
    title: 'Server health',
    readOnlyHint: true,
    handler: async () => {
      try {
        return textResult({ status: 'ok', adapter: 'shrine-diet-bioactivity' });
      } catch (err) {
        return errorResult(err);
      }
    },
  };

  return [
    semanticSearch as unknown as ToolDef<Record<string, unknown>>,
    getEntity as unknown as ToolDef<Record<string, unknown>>,
    getSubgraph as unknown as ToolDef<Record<string, unknown>>,
    listLabels as unknown as ToolDef<Record<string, unknown>>,
    getHealth as unknown as ToolDef<Record<string, unknown>>,
  ];
}
