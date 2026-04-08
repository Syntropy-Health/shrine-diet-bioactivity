import { describe, it, expect } from 'vitest';
import { normalizeCompoundName } from '../../scripts/build-herbal-db.js';

describe('normalizeCompoundName', () => {
  it('lowercases uppercase names', () => {
    expect(normalizeCompoundName('QUERCETIN')).toBe('quercetin');
  });

  it('strips hyphens and spaces', () => {
    expect(normalizeCompoundName('beta-Carotene')).toBe('betacarotene');
    expect(normalizeCompoundName('Vitamin C')).toBe('vitaminc');
  });

  it('strips parentheses and special chars', () => {
    expect(normalizeCompoundName('(+)-Catechin')).toBe('catechin');
    expect(normalizeCompoundName('1,8-Cineole')).toBe('18cineole');
  });

  it('strips L- prefix in vitamin names', () => {
    expect(normalizeCompoundName('L-Ascorbic acid')).toBe('lascorbicacid');
  });

  it('handles whitespace trimming', () => {
    expect(normalizeCompoundName('  QUERCETIN  ')).toBe('quercetin');
  });

  it('matches Duke uppercase to FooDB mixed case', () => {
    // This is the critical join test
    expect(normalizeCompoundName('QUERCETIN')).toBe(normalizeCompoundName('Quercetin'));
    expect(normalizeCompoundName('CURCUMIN')).toBe(normalizeCompoundName('Curcumin'));
    expect(normalizeCompoundName('BETA-CAROTENE')).toBe(normalizeCompoundName('beta-Carotene'));
  });

  it('returns empty string for empty input', () => {
    expect(normalizeCompoundName('')).toBe('');
    expect(normalizeCompoundName('   ')).toBe('');
  });
});
