/**
 * Tenant scoping utilities for multi-tenant MCP queries.
 *
 * Extracts tenant_id from MCP request _meta, validates it,
 * and builds scope filter parameters for LightRAG queries.
 */

import type { TenantContext } from './types.js';

/** Valid tenant IDs: lowercase alphanumeric + hyphens, 3-64 chars. */
const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

/**
 * Extract tenant context from MCP request _meta.
 * Returns null tenantId if _meta is missing or has no tenant_id.
 */
export function extractTenantContext(
  meta: Record<string, unknown> | undefined,
): TenantContext {
  if (
    !meta ||
    typeof meta.tenant_id !== 'string' ||
    meta.tenant_id.trim() === ''
  ) {
    return { tenantId: null, scopeFilter: ['shared'] };
  }
  const tenantId = meta.tenant_id.trim();
  return {
    tenantId,
    scopeFilter: ['shared', `tenant:${tenantId}`],
  };
}

/**
 * Validate that a tenant ID is well-formed.
 * Throws if the ID is present but malformed.
 */
export function validateTenantId(tenantId: string | null): void {
  if (tenantId === null) return;
  if (!TENANT_ID_PATTERN.test(tenantId)) {
    throw new Error(
      `Invalid tenant_id "${tenantId}": must be 3-64 lowercase alphanumeric characters or hyphens`,
    );
  }
}

/**
 * Build scope filter parameter for LightRAG query.
 * Returns the scope values to include in the query body.
 */
export function buildScopeParam(
  ctx: TenantContext,
): { scope_filter: string[] } {
  return { scope_filter: ctx.scopeFilter };
}
