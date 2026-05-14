/**
 * Compound-name normalization shared across loaders.
 *
 * Lower-cases, trims, and strips every non-alphanumeric character so
 * "Curcumin (curcuma longa)" → "curcumincurcumalonga" — collapses
 * formatting differences across data sources (Duke, FooDB, CTD, CMAUP)
 * for join lookups.
 *
 * Lives in its own module so importers don't transitively pull in
 * build-herbal-db's CSV-parser dependency (papaparse) when all they
 * need is name normalization.
 */
export function normalizeCompoundName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]/g, '');
}
