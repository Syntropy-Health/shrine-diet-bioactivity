import { describe, it, expect } from 'vitest';
import { loadDataSources, loadIngestParams } from '../config';

describe('config loader', () => {
  it('loads data_sources.yaml with expected shape', () => {
    const cfg = loadDataSources();
    expect(cfg.symmap.base_url).toMatch(/^https?:\/\//);
    expect(cfg.symmap.files.length).toBeGreaterThan(0);
    expect(cfg.herb2.base_url).toMatch(/^https?:\/\//);
    expect(cfg.paths.sqlite_db).toContain('herbal_botanicals.db');
  });

  it('loads ingest_params.yaml with validated ranges', () => {
    const cfg = loadIngestParams();
    expect(cfg.subsample.seed).toBeTypeOf('number');
    expect(cfg.ingestion.batch_size).toBeGreaterThan(0);
    expect(cfg.hdi_severity_weights.severe).toBeGreaterThan(cfg.hdi_severity_weights.mild);
  });

  it('rejects malformed YAML at load time', () => {
    expect(() => loadDataSources('/dev/null/nonexistent.yaml')).toThrow();
  });
});
