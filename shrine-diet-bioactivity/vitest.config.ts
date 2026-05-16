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
      // Thresholds reflect current main reality + ~2-point margin. The phase
      // PR stack (#19→#35, all merged 2026-05-14) lifted coverage substantially.
      // Re-measured 2026-05-15 against current main (94 tests, 12 test files):
      //   statements 72.82  branches 71.05  functions 61.90  lines 73.71
      // tools.ts remains the largest uncovered surface at 27.86% — closing
      // that gap is the next coverage initiative (publication-aligned MCP
      // tool tests).
      thresholds: {
        statements: 70,
        branches: 68,
        functions: 58,
        lines: 70,
      },
    },
  },
});
