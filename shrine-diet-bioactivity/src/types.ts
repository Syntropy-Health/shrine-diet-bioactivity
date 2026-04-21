/** Shared types for the shrine-diet-bioactivity MCP thin-adapter. */

/** Tenant scoping context extracted from MCP _meta. */
export interface TenantContext {
  /** Tenant identifier, e.g. "clinic-a". Null means shared-only query. */
  tenantId: string | null;
  /** Scope filter values for LightRAG queries. Always includes "shared". */
  scopeFilter: string[];
}
