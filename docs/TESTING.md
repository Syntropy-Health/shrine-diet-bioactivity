# Testing Guide

## What's Tested

The primary TS MCP in `shrine-diet-bioactivity/` is tested with [Vitest](https://vitest.dev/). Tests live next to source files under `src/__tests__/`.

## Run Tests Locally

```bash
cd shrine-diet-bioactivity
npm install
npm test                 # run tests once
npm run test:coverage    # run with coverage report (HTML in coverage/)
npm run typecheck        # tsc --noEmit
```

Open `coverage/index.html` in a browser to browse per-file coverage.

## Coverage Thresholds

Enforced via `vitest.config.ts`:

| Metric | Threshold |
|--------|-----------|
| Statements | 80% |
| Branches | 75% |
| Functions | 85% |
| Lines | 80% |

Exceeding them is fine; falling below fails CI. Adjust in `vitest.config.ts` if the threshold becomes unrealistic for a genuine reason — but prefer adding tests.

## What's Excluded from Coverage

| Path / file | Reason |
|---|---|
| `build/**` | Compiled output |
| `node_modules/**` | Dependencies |
| `src/**/*.test.ts`, `src/__tests__/**` | The tests themselves |
| `src/types.ts` | Type-only declarations, no runtime behavior |
| `vitest.config.ts` | Test configuration |

## Adding Tests

1. Put new test files in `src/__tests__/<module>.test.ts`
2. Mock external dependencies (HTTP, filesystem) with `vi.mock()`
3. Assert on response structure, not literal copy, so tests survive unrelated copy changes
4. If you add a new source file, run `npm run test:coverage` locally before pushing to confirm thresholds

## CI Behavior

`.github/workflows/ci.yml` runs typecheck + coverage on every PR and push to `main`/`test`. PRs cannot merge while red. Coverage report is attached as a workflow artifact.

## Troubleshooting

- **Vitest can't find tests** — ensure filename matches `*.test.ts` pattern
- **Coverage report missing** — install the dev dep: `npm install --save-dev @vitest/coverage-v8`
- **Threshold fails by <1%** — add one more test for the uncovered branch rather than lowering the threshold
- **Flaky HTTP mock** — use `vi.fn()` with explicit return values, not timing-dependent mocks
