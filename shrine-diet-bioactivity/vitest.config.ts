import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    exclude: ['build/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'html'],
      reportsDirectory: 'coverage',
      include: ['src/**/*.ts'],
      exclude: [
        'build/**',
        'node_modules/**',
        'src/**/*.test.ts',
        'src/__tests__/**',
        'src/types.ts',
        'vitest.config.ts',
        // CLI entry point (MCP server bootstrap) — never imported by unit
        // tests, exercised only end-to-end via the MCP runtime. 0% line
        // coverage is expected and not meaningful here.
        'src/index.ts',
      ],
      // Thresholds reflect current main reality + 2-point margin. They are
      // intentionally below the org-wide 80% target while the phase PR stack
      // (#19→#35 — KG audit-closure) lands; those PRs add tested code paths
      // that lift tools.ts coverage substantially. Re-raise after the stack
      // merges. See research-journal/ for the audit context.
      thresholds: {
        statements: 63,
        branches: 60,
        functions: 50,
        lines: 63,
      },
    },
  },
});
