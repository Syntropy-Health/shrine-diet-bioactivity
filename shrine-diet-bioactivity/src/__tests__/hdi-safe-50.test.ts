import { readFileSync, existsSync } from 'fs';
import { describe, it, expect } from 'vitest';
import { resolve } from 'path';

// Resolve from the test file's location to the repo-shared HDI reference set.
const FILE = resolve(__dirname, '../../../research-journal/shared/hdi_safe_50.json');

interface HDISource {
  name: string;
  url: string;
}

interface HDI {
  id: string;
  herb: { name: string; latin: string; symmap_id?: string };
  drug: { name: string; rxnorm?: string; atc?: string };
  severity: 'severe' | 'moderate' | 'mild';
  mechanism_class: 'CYP450' | 'P-gp' | 'PD-antagonism' | 'coagulation' | 'serotonergic';
  evidence_tier:
    | 'clinical_trial'
    | 'pharmacokinetic_study'
    | 'case_report_series'
    | 'case_report'
    | 'in_vitro';
  sources: HDISource[];
  notes: string;
}

describe('HDI-Safe 50', () => {
  it('exists and contains 50 entries', () => {
    expect(existsSync(FILE)).toBe(true);
    const data = JSON.parse(readFileSync(FILE, 'utf8')) as HDI[];
    expect(data).toHaveLength(50);
  });

  it('covers 5 mechanism classes with >= 5 entries each', () => {
    const data = JSON.parse(readFileSync(FILE, 'utf8')) as HDI[];
    const byMech = new Map<string, number>();
    for (const d of data) byMech.set(d.mechanism_class, (byMech.get(d.mechanism_class) ?? 0) + 1);
    for (const cls of ['CYP450', 'P-gp', 'PD-antagonism', 'coagulation', 'serotonergic']) {
      expect(byMech.get(cls) ?? 0).toBeGreaterThanOrEqual(5);
    }
  });

  it('every entry cites at least one of NIH ODS / MSK / LiverTox', () => {
    const data = JSON.parse(readFileSync(FILE, 'utf8')) as HDI[];
    for (const d of data) {
      const sourceNames = d.sources.map((s) => s.name.toLowerCase());
      const hasAllowed = sourceNames.some(
        (n) =>
          n.includes('nih ods') ||
          n.includes('memorial sloan') ||
          n.includes('msk') ||
          n.includes('livertox'),
      );
      expect(hasAllowed).toBe(true);
    }
  });
});
