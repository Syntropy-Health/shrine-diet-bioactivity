# DietResearchBench-Clinical — Datasets

This directory contains the benchmark dataset and split manifest for the
DietResearchBench-Clinical v1 evaluation harness (Subsystem F).

## Files

### `dietresearchbench_v1.json`

**40 clinician research scenarios** across four categories and three complexity tiers.

| Category | Count | Description |
| --- | --- | --- |
| `herbal_single_symptom` | 10 | Single herb evaluated against a primary symptom/condition |
| `nutrition` | 10 | Macronutrient or micronutrient deficiency and therapeutic use |
| `multi_drug_hdi` | 10 | Herb-drug interaction (HDI) safety scenarios |
| `tcm_bilingual` | 10 | Traditional Chinese Medicine herbs with Chinese + English queries |

Each scenario includes:
- `research_question` — framed as a clinician PICO question
- `gold.expected_panel_verdict` — one of `prefer | caution | reject | abstain`
- `gold.expected_evidence_tier` — highest qualifying evidence level
- `gold.expected_hdi_severity` — severity rating for HDI scenarios
- `gold.languages` — `["en"]` or `["en","zh"]` for TCM bilingual scenarios
- `rationale` and `source_citations` — primary literature backing the gold standard

Schema: `eval.scenario.BenchmarkSet` (Pydantic, validated at load time).

### `splits_seed42.json`

**Deterministic 60/20/20 train/val/test split** generated with seed 42.

Stratified by `(category, expected_complexity)` — 12 strata total. The split is
pinned so evaluation results are reproducible across runs without re-splitting.

Fields: `seed`, `benchmark_version`, `ratios`, `train_ids`, `val_ids`, `test_ids`.

### `annotation-protocol.md`

Guidelines for expanding the benchmark from v1 (40 scenarios) to v2 (200+ scenarios)
with dietitian, pharmacist, and TCM clinician sign-off. Covers inter-annotator
agreement requirements (Cohen's κ ≥ 0.70) and field-by-field annotation instructions.

## How to run the evaluation

```bash
# 1. Smoke-test structural imports + optional OpenRouter connectivity
make eval-smoke

# 2. Run all baselines against the test split
#    Set OPENROUTER_API_KEY in shrine-diet-bioactivity/.env first
make eval-run

# 3. Restrict to specific systems (comma-separated)
make eval-run SYSTEMS=diet_os,medagents

# 4. Render summary.md + reliability_diagram.png from the latest run
make eval-report
```

Results are written under `research-journal/shared/results/<timestamp>/` and are
gitignored (ephemeral). To preserve a run, cherry-pick `summary.md` into a commit.

## Adding scenarios

See `annotation-protocol.md` for the full workflow. Quick steps:

1. Add a new `Scenario` object to `dietresearchbench_v1.json` following the schema.
2. Re-generate splits: `cd shrine-diet-bioactivity && python3 -c "from pathlib import Path; import json; from eval.scenario import BenchmarkSet; from eval.splits import persist_splits; persist_splits(BenchmarkSet.model_validate(json.loads(Path('../research-journal/shared/datasets/dietresearchbench_v1.json').read_text())), Path('../research-journal/shared/datasets/splits_seed42.json'))"`
3. Run `make eval-smoke` to confirm the benchmark still validates.

## Version notes

| Version | Scenarios | Status |
| --- | --- | --- |
| v1 | 40 | Current — hand-curated seed benchmark |
| v2 | 200+ | Planned — post-clinician annotation round |

Citation: DietResearchBench-Clinical v1, Syntropy Health, 2026.
