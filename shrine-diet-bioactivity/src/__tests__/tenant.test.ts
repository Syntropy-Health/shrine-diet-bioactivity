import { describe, it, expect } from 'vitest';
import {
  extractTenantContext,
  validateTenantId,
  buildScopeParam,
} from '../tenant.js';

describe('extractTenantContext', () => {
  it('returns shared-only when meta is undefined', () => {
    const ctx = extractTenantContext(undefined);
    expect(ctx.tenantId).toBeNull();
    expect(ctx.scopeFilter).toEqual(['shared']);
  });

  it('returns shared-only when meta is empty object', () => {
    const ctx = extractTenantContext({});
    expect(ctx.tenantId).toBeNull();
    expect(ctx.scopeFilter).toEqual(['shared']);
  });

  it('extracts valid tenant_id', () => {
    const ctx = extractTenantContext({ tenant_id: 'clinic-a' });
    expect(ctx.tenantId).toBe('clinic-a');
    expect(ctx.scopeFilter).toEqual(['shared', 'tenant:clinic-a']);
  });

  it('returns shared-only when tenant_id is empty string', () => {
    const ctx = extractTenantContext({ tenant_id: '' });
    expect(ctx.tenantId).toBeNull();
    expect(ctx.scopeFilter).toEqual(['shared']);
  });

  it('returns shared-only when tenant_id is non-string', () => {
    const ctx = extractTenantContext({ tenant_id: 123 });
    expect(ctx.tenantId).toBeNull();
    expect(ctx.scopeFilter).toEqual(['shared']);
  });

  it('trims whitespace from tenant_id', () => {
    const ctx = extractTenantContext({ tenant_id: '  clinic-b  ' });
    expect(ctx.tenantId).toBe('clinic-b');
    expect(ctx.scopeFilter).toEqual(['shared', 'tenant:clinic-b']);
  });

  it('returns shared-only when tenant_id is whitespace only', () => {
    const ctx = extractTenantContext({ tenant_id: '   ' });
    expect(ctx.tenantId).toBeNull();
    expect(ctx.scopeFilter).toEqual(['shared']);
  });
});

describe('validateTenantId', () => {
  it('accepts null (no tenant)', () => {
    expect(() => validateTenantId(null)).not.toThrow();
  });

  it('accepts valid lowercase with hyphens', () => {
    expect(() => validateTenantId('clinic-a')).not.toThrow();
    expect(() => validateTenantId('abc')).not.toThrow();
    expect(() => validateTenantId('clinic-123-test')).not.toThrow();
  });

  it('rejects underscores', () => {
    expect(() => validateTenantId('clinic_a')).toThrow(/Invalid tenant_id/);
  });

  it('rejects too short (2 chars)', () => {
    expect(() => validateTenantId('ab')).toThrow(/Invalid tenant_id/);
  });

  it('rejects too long (65 chars)', () => {
    expect(() => validateTenantId('a'.repeat(65))).toThrow(
      /Invalid tenant_id/,
    );
  });

  it('rejects uppercase', () => {
    expect(() => validateTenantId('Clinic-A')).toThrow(/Invalid tenant_id/);
  });

  it('rejects special characters', () => {
    expect(() => validateTenantId("'; DROP TABLE")).toThrow(
      /Invalid tenant_id/,
    );
  });

  it('rejects leading hyphen', () => {
    expect(() => validateTenantId('-clinic')).toThrow(/Invalid tenant_id/);
  });

  it('rejects trailing hyphen', () => {
    expect(() => validateTenantId('clinic-')).toThrow(/Invalid tenant_id/);
  });
});

describe('buildScopeParam', () => {
  it('returns shared-only scope for null tenant', () => {
    const result = buildScopeParam({
      tenantId: null,
      scopeFilter: ['shared'],
    });
    expect(result).toEqual({ scope_filter: ['shared'] });
  });

  it('returns shared + tenant scope', () => {
    const result = buildScopeParam({
      tenantId: 'clinic-a',
      scopeFilter: ['shared', 'tenant:clinic-a'],
    });
    expect(result).toEqual({
      scope_filter: ['shared', 'tenant:clinic-a'],
    });
  });
});
