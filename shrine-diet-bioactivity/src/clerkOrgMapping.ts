/**
 * Canonical Clerk org_id → tenant_id slug mapping.
 *
 * Clerk organisation IDs look like `org_2abc123XYZ` (uppercase +
 * underscore, 27–32 chars typical) — they fail the tenant slug regex
 * enforced by the MCP server. Every consumer (ShrineAgent, CLI,
 * back-office tools) must run the org_id through this one function at
 * the call boundary before passing it into `_meta.tenant_id`.
 *
 * The rule is:
 *   1. Strip the `org_` prefix if present.
 *   2. Lowercase.
 *   3. Replace underscores with hyphens.
 *   4. Cap at 60 chars (headroom under the 64-char tenant limit).
 *   5. Revalidate against the tenant regex; throw on mismatch — do
 *      NOT silently drop characters beyond the cap.
 *
 * The result is stable per Clerk organisation (Clerk org IDs are
 * immutable), so a clinic's tenant slug is stable for the life of the
 * org.
 */

/** Mirrors TENANT_ID_PATTERN in src/tenant.ts. */
const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

const CLERK_ORG_PREFIX = 'org_';
const MAX_SLUG_LEN = 60;

/**
 * Convert a Clerk `organization.id` into a tenant slug accepted by
 * the shrine-health-bioactivity MCP server.
 *
 * @throws Error when the result does not match the tenant slug regex.
 */
export function slugifyClerkOrgId(orgId: string): string {
  if (typeof orgId !== 'string' || orgId.trim() === '') {
    throw new Error('Cannot map empty org_id to a tenant slug');
  }

  const stripped = orgId.startsWith(CLERK_ORG_PREFIX)
    ? orgId.slice(CLERK_ORG_PREFIX.length)
    : orgId;

  const slug = stripped
    .toLowerCase()
    .replace(/_/g, '-')
    .slice(0, MAX_SLUG_LEN);

  if (!TENANT_ID_PATTERN.test(slug)) {
    throw new Error(
      `Cannot map Clerk org_id "${orgId}" to a valid tenant slug (got "${slug}")`,
    );
  }

  return slug;
}

/**
 * Safe variant that returns null instead of throwing. Useful in code
 * paths where a missing/invalid org just means "anonymous / shared
 * only" (e.g. public landing pages).
 */
export function slugifyClerkOrgIdSafe(orgId: string | null | undefined): string | null {
  if (!orgId) return null;
  try {
    return slugifyClerkOrgId(orgId);
  } catch {
    return null;
  }
}
