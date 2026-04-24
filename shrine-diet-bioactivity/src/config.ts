import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { parse } from 'yaml';
import { z } from 'zod';

const DataSourcesSchema = z.object({
  symmap: z.object({
    base_url: z.string().url(),
    files: z.array(z.string()).min(1),
    out_dir: z.string(),
  }),
  herb2: z.object({
    base_url: z.string().url(),
    files: z.array(z.string()).min(1),
    out_dir: z.string(),
  }),
  paths: z.object({
    sqlite_db: z.string(),
    hdi_safe_50: z.string(),
    symptom_crosswalk: z.string(),
    ingestion_snapshot: z.string(),
  }),
});

const IngestParamsSchema = z.object({
  subsample: z.object({
    max_relationships: z.number().int().nonnegative(),
    seed: z.number().int(),
  }),
  ingestion: z.object({
    batch_size: z.number().int().positive(),
    max_async: z.number().int().positive(),
  }),
  lightrag: z.object({
    working_dir: z.string(),
  }),
  hdi_severity_weights: z.object({
    severe: z.number().min(0).max(1),
    moderate: z.number().min(0).max(1),
    mild: z.number().min(0).max(1),
  }),
  evidence_tier_weights: z.record(z.string(), z.number().min(0).max(1)),
});

export type DataSources = z.infer<typeof DataSourcesSchema>;
export type IngestParams = z.infer<typeof IngestParamsSchema>;

// ESM-compatible __dirname equivalent
const _dir = typeof __dirname !== 'undefined'
  ? __dirname
  : dirname(fileURLToPath(import.meta.url));

const DEFAULT_DATA = resolve(_dir, '..', 'config', 'data_sources.yaml');
const DEFAULT_PARAMS = resolve(_dir, '..', 'config', 'ingest_params.yaml');

export function loadDataSources(path: string = DEFAULT_DATA): DataSources {
  const raw = readFileSync(path, 'utf8');
  const parsed = parse(raw);
  return DataSourcesSchema.parse(parsed);
}

export function loadIngestParams(path: string = DEFAULT_PARAMS): IngestParams {
  const raw = readFileSync(path, 'utf8');
  const parsed = parse(raw);
  return IngestParamsSchema.parse(parsed);
}
