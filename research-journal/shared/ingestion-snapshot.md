# KG Ingestion Snapshot

_Generated 2026-04-25T05:40:30.203311+00:00_
_Aura instance: c16cebae_

## Node counts by type

| Entity type | Count |
|---|---|
| Compound | 6,998 |
| Target | 6,352 |
| Herb | 4,560 |
| Symptom | 3,055 |
| Disease | 2,948 |
| Food | 900 |
| Drug | 35 |

## Edge counts by type

| Relationship type | Count |
|---|---|
| TREATS_SYMPTOM | 30,000 |
| FOUND_IN_FOOD | 25,438 |
| CONTAINS_COMPOUND | 933 |
| ASSOCIATED_WITH_DISEASE | 612 |
| TARGETS_PROTEIN | 116 |
| INTERACTS_WITH | 50 |
| DIRECTED | 50 |

## Source distribution (nodes)

| Source prefix | Node count |
|---|---|
| duke | 15,520 |
| symmap | 7,704 |
| herb2 | 1,483 |
| custom_kg | 100 |
| hdi-safe-50 | 41 |

## Source distribution (edges)

| Source prefix | Edge count |
|---|---|
| duke | 56,487 |
| herb2 | 612 |
| hdi-safe-50 | 50 |

## Bilingual coverage

| Total Herbs | With CN | With EN | With Pinyin |
|---|---|---|---|
| 4,563 | 2,181 | 1,976 | 2,181 |

## HDI-Safe 50 coverage

_Mechanism class breakdown — should match the curated hdi_safe_50.json mix._

| Mechanism class | Edges |
|---|---|
| CYP450 | 15 |
| P-gp | 6 |
| PD-antagonism | 8 |
| coagulation | 10 |
| serotonergic | 11 |

_Severity breakdown — for the Safety Reviewer agent._

| Severity | Edges |
|---|---|
| mild | 1 |
| moderate | 26 |
| severe | 23 |

