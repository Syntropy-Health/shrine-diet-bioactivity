import { describe, it, expect } from 'vitest';
import {
  extractTenantContext,
  validateTenantId,
  buildScopeParam,
} from '../tenant.js';

describe('semantic-search scope injection', () => {
  it('builds shared-only LightRAG body when no tenant', () => {
    const tenant = extractTenantContext(undefined);
    const body = {
      query: 'anti-inflammatory herbs',
      mode: 'hybrid',
      top_k: 60,
      ...buildScopeParam(tenant),
    };
    expect(body).toEqual({
      query: 'anti-inflammatory herbs',
      mode: 'hybrid',
      top_k: 60,
      scope_filter: ['shared'],
    });
  });

  it('builds tenant-scoped LightRAG body', () => {
    const tenant = extractTenantContext({ tenant_id: 'clinic-a' });
    const body = {
      query: 'IV protocol for inflammation',
      mode: 'local',
      top_k: 20,
      ...buildScopeParam(tenant),
    };
    expect(body).toEqual({
      query: 'IV protocol for inflammation',
      mode: 'local',
      top_k: 20,
      scope_filter: ['shared', 'tenant:clinic-a'],
    });
  });

  it('rejects invalid tenant_id before query', () => {
    const tenant = extractTenantContext({ tenant_id: "'; DROP TABLE nodes" });
    expect(() => validateTenantId(tenant.tenantId)).toThrow(
      /Invalid tenant_id/,
    );
  });

  it('allows query when _meta present but no tenant_id', () => {
    const tenant = extractTenantContext({ some_other_field: 'value' });
    expect(tenant.tenantId).toBeNull();
    expect(buildScopeParam(tenant)).toEqual({ scope_filter: ['shared'] });
  });

  it('handles tenant_id as boolean gracefully', () => {
    const tenant = extractTenantContext({ tenant_id: true });
    expect(tenant.tenantId).toBeNull();
    expect(tenant.scopeFilter).toEqual(['shared']);
  });

  it('handles tenant_id as object gracefully', () => {
    const tenant = extractTenantContext({
      tenant_id: { org: 'clinic-a' },
    });
    expect(tenant.tenantId).toBeNull();
    expect(tenant.scopeFilter).toEqual(['shared']);
  });
});
