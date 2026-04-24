import { existsSync, statSync } from 'fs';
import { describe, it, expect } from 'vitest';

describe('SymMap download', () => {
  it.each([
    'data/symmap/SymMap v2.0, SMHB file.xlsx',
    'data/symmap/SymMap v2.0, SMTS file.xlsx',
    'data/symmap/SymMap v2.0, SMIT file.xlsx',
    'data/symmap/SymMap v2.0, SMTT file.xlsx',
  ])('%s exists and is non-empty', (path) => {
    expect(existsSync(path)).toBe(true);
    expect(statSync(path).size).toBeGreaterThan(1024);
  });
});
