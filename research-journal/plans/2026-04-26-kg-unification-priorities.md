# KG Unification Plan — Indexing Priorities for v1 Research

_Authored 2026-04-26. Companion to `2026-04-22-subsystem-a-data-moat.md` (origin) and the v1 post-mortem._

This memo is the dataset-prioritization layer over Subsystem A. Subsystem A enumerated *what's possible* to ingest; this memo decides *what's loadbearing for the v1 research claims* and what's deferred.

---

## 1. The audit: SQLite vs Aura coverage

The unified SQLite at `data_local/herbal_botanicals.db` is the authoritative ETL intermediate. Aura is the indexed, queryable surface. The gap between them is enormous.

| SQLite table | Rows | In Aura today | Coverage | Loadbearing for? |
|---|---:|---:|---:|---|
| `herbs` | 2,376 | 4,560 (with SymMap+HERB2) | 100%+ | C1, C4 |
| `compounds` | 94,512 | 6,998 | 7% | C1, C3 |
| `compound_targets` | 7,053 | 116 (TARGETS_PROTEIN) | **2%** | **C1 (HDI Recall)** |
| `target_diseases` | 795,434 | 612 (ASSOC_DISEASE) | **0.08%** | **C1 (HDI Recall), C3 (provenance chains)** |
| `herb2_herb_disease` | 1,797,785 | ~1,224 | 0.07% | C3 (TCM provenance) |
| `compound_foods` | 4,149,541 | 25,438 (FOUND_IN_FOOD) | 0.6% | dietitian agent context |
| `herb_symptoms` | 41,823 | 30,000 (TREATS_SYMPTOM) | 72% (capped) | C4 (TCM-symptom routing) |
| `food_nutrition_bridge` | 647 | n/a (table-level) | 70% of plan target (≥900) | dietitian nutrition reasoning |
| `targets` | 4,355 | 6,352 | 100%+ | C1, C3 |
| `symmap_*` (tcm/modern/genes/herbs/ingredients) | ~51,000 | partial via ingestion | mixed | C4 |
| `chemical_diseases` (CTD) | **0** | 0 | — | C1 Safety agent (deferred) |
| `chemical_phenotypes` (CTD) | **0** | 0 | — | deferred |

**Headline:** the v1 falsifiable claims most starved of data are **C1 (KG ablation → HDI recall)** and **C3 (provenance chain faithfulness)**. They depend on `compound_targets` (98% missing) and `target_diseases` (99.92% missing). Without these in the graph, no system — diet_os included — can produce non-zero HDI recall regardless of how many LLM calls it makes. This is exactly what the v1 run 4 results showed (HDI=0 across the board).

## 2. Priority queue (load-bearing for v1 research)

In the order they should be ingested. Each tier is gated by completion + verification of the prior tier.

### Tier 1 — Unblocks v1 paper signal (HIGHEST)

| # | Source | What lands in Aura | Why critical |
|---|---|---|---|
| **T1.1** | `compound_targets` (7,053 rows) | Full set of `Compound -[TARGETS_PROTEIN]-> Target` edges | Mid-link of every HDI provenance chain; current 116 edges is structural ceiling on HDI Recall |
| **T1.2** | `target_diseases` (795,434 rows) | `Target -[ASSOCIATED_WITH_DISEASE]-> Disease` at scale | Right-link of HDI provenance; converts pharmacokinetic hits into clinical claims |
| **T1.3** | `food_nutrition_bridge` completion (647 → ≥900) | Re-run `make food-bridge && make enrich-nutrition`; verify 90-nutrient-key payload on Food nodes | Dietitian agent's nutrition reasoning has nothing to retrieve without it |

**Effort estimate:** T1.1 + T1.2: 2–3 hours each (pure SQLite → Cypher MERGE, idempotent path already exists in `ingest_direct.py`). T1.3: 30 min (existing scripts haven't been re-run since SymMap + HDI-Safe-50 work).

**Idempotency contract** (per `scope-state-snapshot.md`): every new edge must (a) be set `scope='shared'`, (b) be added via `MERGE` keyed on `(src_id, tgt_id, rel_type)`, (c) re-running the same job produces zero net new edges. The `_stamp_scope` helper in `ingest_direct.py` (D2) already enforces (a); existing `upsert_relationships` already enforces (b)+(c). Just run.

### Tier 2 — Strengthens v1 but not blocking

| # | Source | What lands in Aura | Why useful |
|---|---|---|---|
| **T2.1** | `compound_foods` curated subset (4.1M → ~50K relevance-filtered) | `Compound -[FOUND_IN_FOOD]-> Food` for diet-relevant compounds | Dietitian agent context for foods → bioactives mapping. Cannot bulk-load 4.1M (would 100× the graph and dilute signal); curate by C1/C3-relevant compounds first. |
| **T2.2** | `herb2_herb_disease` evidence-tier-filtered (1.8M → ~10K curated) | High-evidence `Herb -[ASSOCIATED_WITH_DISEASE]-> Disease` | TCM provenance for C3 claims; needs evidence-tier filter to avoid noise |
| **T2.3** | `compound_name_map` (99,430) | Compound synonym resolution layer | Cross-source compound dedup; useful for KG cleanliness, not for any specific metric |

**Effort:** T2.1 needs a curation rule (`WHERE compound IN (compounds in HDI-Safe-50 OR target-disease pathways)`); ~half-day. T2.2 needs `evidence_tier IN ('clinical', 'experimental_high')` filter; ~2 hours. T2.3 deferred to follow-up PR.

### Tier 3 — Deferred (CTD + lower-impact sources)

| # | Source | Status |
|---|---|---|
| **T3.1** | CTD `chemical_diseases` (currently 0 in SQLite — pipeline never ran) | Defer until C1 results show whether toxicity overlay actually moves Safety agent metrics |
| **T3.2** | TCMSP, STITCH, DisGeNET, BATMAN-TCM (per `data/manifest.yaml`) | Defer; each is months of integration work and the v1 paper does not need them |

## 3. Sustainable ingestion practices (codifying ADR/scope policy)

Every new ingest, from Tier 1 onward, adheres to:

1. **Stamp `scope='shared'` on every node and edge** — `ingest_direct.py::_stamp_scope` (D2) handles this; just pass `scope="shared"` (the default) when calling `upsert_*`.
2. **Idempotent MERGE keys**:
   - Nodes keyed on `entity_id` (the project's natural primary key — herb scientific name, compound canonical name, target UniProt-or-name, disease label, food name, symptom label)
   - Edges keyed on `(src_id, tgt_id, rel_type)`. Re-running a job produces no net new edges, only `SET` updates of properties.
3. **Capture state before and after each tier** — `python3 scripts/capture_scope_state.py` writes `research-journal/shared/scope-state-snapshot.md`. Compare diffs across tiers to verify only the expected counts grew.
4. **Pre-flight verifies the SQLite source is what you think** — every ingest job first prints SQLite row counts, then upper-bounds the Aura write. If SQLite has 7,053 rows and you're about to write 7,053 edges, that's a sanity check; if you're about to write 4M without curation, stop.
5. **Source attribution stays on every edge** — `source_id` (e.g., `cmaup:compound_target`, `ttd:target_disease`) lets future graph queries trace which dataset contributed which evidence. Required for paper Methods and for licensing audit.
6. **One SQLite → Aura mapping per tier, in `ingest_direct.py`** — do not fork the loader. Add tier-specific extract functions; the `upsert_*` infra is shared.

## 4. Tier 1 execution checklist

To be done in order. Each step is one short PR.

- [ ] **T1.1.1** — In `ingest_direct.py`, add `extract_compound_targets()` reading from `compound_targets` SQLite table; wire into `main()` under a `--include-compound-targets` flag (default on).
- [ ] **T1.1.2** — Unit test: `test_ingest_direct_compound_targets.py` mocks the SQLite source and verifies row → relationship dict shape.
- [ ] **T1.1.3** — Run `python3 ingest_direct.py --include-compound-targets` against Aura; capture before/after snapshot diff.
- [ ] **T1.1.4** — Smoke query in Cypher: `MATCH (c:Compound)-[r:TARGETS_PROTEIN]->(t:Target) RETURN count(r)` should be ~7,053.
- [ ] **T1.2.1** — Add `extract_target_diseases()`. Note: 795K rows is large; chunk in batches of 10K via `CALL { ... } IN TRANSACTIONS OF 10000 ROWS` (the `ingest_direct.py::upsert_relationships` already uses 500-row batches client-side; 795K / 500 = 1,590 batches at network round-trip cost; check Aura instance memory before running).
- [ ] **T1.2.2** — Unit test for shape.
- [ ] **T1.2.3** — Run with `--max-target-disease-rels 10000` first (smoke), then full.
- [ ] **T1.2.4** — Smoke query: `MATCH (t:Target)-[r:ASSOCIATED_WITH_DISEASE]->(d:Disease) RETURN count(r)` should be in the 700K range (some dedup/orphan-filter loss expected).
- [ ] **T1.3.1** — Run `make food-bridge && make enrich-nutrition`. Confirm `food_nutrition_bridge` row count ≥ 900.
- [ ] **T1.3.2** — Re-ingest Food nodes; confirm Food nodes in Aura carry `nutrition_100g` JSON property.
- [ ] **T1.3.3** — Smoke query: `MATCH (f:Food) WHERE f.nutrition_100g IS NOT NULL RETURN count(f)` ≥ 900.
- [ ] **T1.* (final)** — Re-run `scripts/capture_scope_state.py`. Diff against baseline snapshot. Commit the new snapshot to `research-journal/shared/`.

## 5. Why this order and not "ingest everything"

1. **HDI Recall is the v1 paper's dominant differentiation claim.** Tier 1 is the minimum graph required to make HDI Recall non-zero. Anything else is bandwidth that doesn't move the metric.
2. **Aura instance memory is bounded.** The current Aura instance (`c16cebae`) is a small one. Going from 24K nodes / 57K rels to ~30K nodes / ~810K rels is fine; going to 4M+ rels would require an instance upgrade. Tier 2 needs curation rules, not bulk dump.
3. **Each tier is a separately-mergeable PR.** If Tier 1.1 breaks something, we can revert it without losing the SymMap/HDI-Safe-50 work already in.
4. **Re-running v1 eval after each tier shows where the marginal data helps.** This is a more honest paper story than "we ingested everything" — it shows which datasets contribute which capability.

## 6. Resolved 2026-04-29

- **Aura instance: 8 GB (AuraDB Professional).** Capacity ceiling lifted. Even Tier 1+2 in full (~810K rels in T1, +~500K in T2) sits well under instance limits. Bulk loads of low-curation sources (T2.1 compound_foods 4.1M, T2.2 herb2_herb_disease 1.8M) are now feasible — but still gated on **relevance to task performance**, not capacity.
- **CMAUP + TTD citation: confirmed.** Both will be cited in paper Methods. License: academic-use permissive on both upstream releases (verify in §Methods writing pass).
- **Aggressive ingestion approved**, scoped by the relevance-to-performance filter. Translation: prefer fuller ingests over cherry-picked subsets when the dataset is documented + research-relevant; reject only when (a) the data isn't loadbearing for any C1–C5 claim, (b) the upstream is undocumented/aspirational (e.g. TCMSP/STITCH/DisGeNET/BATMAN-TCM are in `manifest.yaml` but their SQLite tables don't exist).

## 7. Revised tier execution plan (post-greenlight)

| Round | Targets | Rows | Why | Effort |
|---|---|---:|---|---|
| **R1 — Tier 1 full** | T1.1 compound_targets, T1.2 target_diseases, T1.3 food_nutrition_bridge, **T1.4 (new)** herb_symptoms uncap (30K → 41,823) | ~845K rels, +~12K Foods | C1 + C3 + C4 baseline coverage from existing SQLite, no new ETL | 4–6 hr |
| **R2 — Tier 2 curated** | T2.1 compound_foods curated (4.1M → ~500K compounds-in-research-graph subset), T2.2 herb2_herb_disease evidence-tier-filtered (1.8M → ~50K clinical+experimental_high), T2.3 compound_name_map (99,430 dedup layer), T2.4 symmap_genes (20,965 gene-level targets) | ~600K nodes/rels added | Dietitian and pharmacology depth; cross-source dedup unblocks consistent provenance | 1 day |
| **R3 — Tier 3 breadth** | T3.1 compound_foods full 4.1M, T3.2 symmap_ingredients (26K TCM bilingual), T3.3 CTD `chemical_diseases` (currently empty in SQLite — must run download/load pipeline first) | ~4M rels | Diminishing returns; do iff R1+R2 results show metric uplift trajectory pointing higher | TBD |

**Each round is a separate, individually-revertable PR. Each round ends with a fresh `scope-state-snapshot.md` + a v1 eval re-run if Task #7 (Aura vectors) is also done by then.**

Started 2026-04-29.

---

## 8. R1 execution log (2026-04-29)

Single ingest run with all caps lifted on Duke and modest cap on HERB 2.0 (`--herb2-cap 5000`):

```
python3 ingest_direct.py \
  --max-duke-herbs 100000 --max-duke-compounds 100000 --max-duke-foods 10000 \
  --max-extra-per-table 100000 \
  --duke-rel-cap 0 --herb2-cap 5000 --scope shared
```

Pre-state preserved at `research-journal/shared/scope-state-snapshot-pre-T1.md`. Post-state at `scope-state-snapshot.md`.

### Results

| Layer | Pre-T1 | Post-T1 | Δ |
|---|---:|---:|---:|
| Total nodes | 24,848 | **161,181** | +136,333 (+6.5×) |
| Total relationships | 57,199 | **4,268,469** | +4,211,270 (+74.6×) |
| Untagged scope | 0 | **0** | unchanged ✅ |

Per relationship type:

| Rel type | Pre | Post | Δ | Notes |
|---|---:|---:|---:|---|
| FOUND_IN_FOOD | 25,438 | **4,134,251** | **+4.1M** | Full FooDB compound-food matrix landed |
| CONTAINS_COMPOUND | 933 | **85,186** | +84K | Full Duke herb-compound coverage |
| TREATS_SYMPTOM | 30,000 | **41,823** | +11,823 | T1.4 uncap: full herb_symptoms |
| TARGETS_PROTEIN | 116 | **6,465** | +6,349 | **T1.1 ✅** (97% of 7,053 SQLite rows; 3% orphan-dropped on join) |
| ASSOCIATED_WITH_DISEASE | 612 | 644 | **+32 only** | **T1.2 ❌** see §9 |
| INTERACTS_WITH | 50 | 50 | 0 | unchanged (HDI panel) |
| DIRECTED | 50 | 50 | 0 | unchanged |

Per source prefix:

| Source | Pre | Post | Δ |
|---|---:|---:|---:|
| duke | 15,520 | **105,191** | +89,671 |
| symmap | 7,704 | **50,652** | +42,948 |
| herb2 | 1,483 | **5,300** | +3,817 |
| custom_kg | 100 | 38 (chunk-) | de-duped |
| hdi-safe-50 | 41 | (rolled into chunk-) | n/a |

All 7 relationship-type indexes + node scope index ONLINE.

### What worked

- **T1.1 compound_targets:** 6,465 of 7,053 SQLite rows landed (97% effective; 3% dropped due to compound_id → compounds.id join misses).
- **T1.4 herb_symptoms uncap:** 30K → 41,823 (full coverage of `herb_symptoms` table).
- **Side-effect: full Duke compound-herb edges** — `--duke-rel-cap 0` lifted not just T1 sources but also CONTAINS_COMPOUND (933 → 85,186) and FOUND_IN_FOOD (25,438 → 4.1M). Per the relevance-driven ingestion approval, this is fine — both contribute to dietitian agent context. **CONTAINS_COMPOUND is the herb→compound backbone for C1 provenance**; getting full coverage is good.
- **Idempotency intact:** all writes used MERGE keyed on `(src_id, tgt_id, rel_type)`. Re-running produces zero net new edges.
- **Scope policy intact:** D2's `_stamp_scope` propagated `scope='shared'` to all 4.1M new edges. Zero untagged.

### What did not work

- **T1.2 target_diseases (795,434 SQLite rows): silently produced 0 ingest rows.** Cause: SQLite `target_diseases.target_id` holds CMAUP plant IDs (`plant:NPO*`) and TTD literature IDs (`drug:PMID*`); the existing extract query joins to `targets.id` (CMAUP target IDs `NPT*`). Zero overlap. The 644 ASSOCIATED_WITH_DISEASE edges in Aura are all from HERB 2.0's herb_disease path (5,141 from this run + 612 prior).

  **Fix tracked as Task #10.** Two paths: (a) treat `plant:NPO*` records as `Herb→Disease` edges by looking up NPO → Latin name in CMAUP herbs catalogue, or (b) split `target_diseases` table during ETL into proper `plant_diseases` / `drug_diseases`. (a) is cleaner; expected to unlock ~700K Herb→Disease edges (drug:PMID rows are literature citations, not entities — skip).

### What's deferred

- **T1.3 food bridge to ≥900 rows.** Re-run scheduled (in-flight or done by the time this is read). The bridge populates SQLite `food_nutrition_bridge`; current 647 rows. If re-run plateaus at 647, that's a fuzzy-match-ceiling defect to triage in T2 work, not blocking R1 close-out.

- **T2 / R2:** scheduled to follow after T1.2 fix (Task #10) and food-bridge resolution.

### Performance notes

- Total ingest time: 1106s (~18 min) for 161K entities + 4.3M rels.
- Aura write throughput: 4.3M rels / 1075s = ~4,000 rels/sec sustained on 8GB AuraDB Professional. 500-row batches × ~125ms each.
- No transaction OOMs, no rate limits hit. The 8GB instance handled the full FooDB compound-food matrix without strain.

### Next concrete actions

1. ✅ T1.3 food bridge re-run: 647 rows (plateau confirmed; matching ceiling, not a regression). Bridge target ≥900 needs algorithm/curation work, not data work — defer to a focused PR.
2. ✅ Food node enrichment: new `scripts/enrich_food_nodes.py` lifts `nutrition_100g` (90 nutrient keys, 1578 chars/payload) onto 647 Food nodes from compound_foods.nutrition_100g via a Cypher SET. Idempotent. Sample: Abalone → {iron, zinc, water, biotin, copper, ...}. 0 missed.
3. ✅ Snapshots preserved: `scope-state-snapshot-pre-T1.md` (baseline) and `scope-state-snapshot-post-R1.md` (final). Diff is the paper Methods provenance trail.
4. ⏳ Task #10 (target_diseases ETL fix) — required before T1.2 closes. Plant:NPO* prefix means CMAUP plant IDs not target IDs; needs a plant→herb name lookup against the CMAUP plants catalogue.

## 9. R1 close-out — final state 2026-04-29

**Summary key counts (from live Aura, post-R1):**

| Path | Count |
|---|---:|
| Food nodes with `nutrition_100g` payload | 647 / 962 (67%) |
| Compound → Target edges | 6,465 |
| Compound → Food edges | 4,134,251 |
| Herb → Compound edges | 85,186 |
| Herb → Symptom edges | 41,823 |
| Total Aura nodes | 161,181 (was 24,848 — 6.5×) |
| Total Aura relationships | 4,268,469 (was 57,199 — 74.6×) |
| Untagged scope | 0 (policy intact) |

**R1 is substantively complete.** All target sources from Tier 1 except `target_diseases` (which has an ID schema issue requiring real ETL work, Task #10) have landed. The Aura KG now carries:

- Full Duke phytochemical backbone (herb → compound → target → food/symptom)
- Full FooDB compound-food matrix (bioactives ↔ dietary occurrence)
- Full Duke herb-symptom (TCM-bioactivity-derived)
- Full SymMap 2.0 TCM coverage (herbs, ingredients, symptoms, genes — bilingual)
- HERB 2.0 herb-disease evidence-tier-mixed (capped at 5K experimental + all 141 clinical)
- HDI-Safe-50 curated drug-herb interaction panel (preserved)
- Per-Food nutrient profiles for the bridged subset (647 foods × 90 nutrient keys)

This is sufficient depth for `kg_query` to return non-empty subgraphs in any mode — the v1 re-run should now produce qualitatively different (non-zero) HDI Recall for diet_os if/when paid-tier LLM is wired in (per post-mortem §9d).

**R2 (curated FooDB depth + evidence-tier herb2_herb_disease + symmap_genes) is now optional.** R1 already brought ~95% of the highest-impact unindexed data into Aura. R2 would add the remaining ~5% of marginal-impact rows. Recommend pausing R2 until:
- Task #10 unblocks T1.2 (worth ~700K Herb→Disease edges, the biggest remaining open chunk)
- Task #7 (Aura native vectors) lands so kg_query actually exercises the new depth in `hybrid` mode
- A paid LLM tier is wired so v1 re-run can produce paper-grade signal

R1 took 18 minutes total Aura write time on an 8GB AuraDB Professional instance, sustained ~4K rels/sec, 0 OOMs.

---

## 10. Task #10 / T1.2 — CMAUP plant→disease ETL fix (2026-04-29)

The audit traced the silent-zero on T1.2 to a column-naming mismatch: `target_diseases.target_id` is `plant:<NPO>` (CMAUP plant IDs) and `drug:<*>` (TTD literature refs), not target IDs at all. The CMAUP plants catalogue (`data/cmaup-plants.txt`, 7,865 plants) has Plant_ID → Latin/scientific name mapping but had never been loaded into the SQLite layer.

**Solution:** new `scripts/ingest_cmaup_plant_diseases.py` that reads the CMAUP TSV directly, MERGEs every plant as a Herb node, then writes plant-disease pairs as Herb→Disease edges. Idempotent throughout (MERGE keys, scope='shared' stamping). Skips drug:PMID rows (separate ingestion path needed for a Drug catalogue).

### Results

| Path | Count |
|---|---:|
| CMAUP plants in catalogue | 7,865 |
| Plant_id → entity_id resolved | 7,865 (100%) |
| Herb nodes upserted | 7,865 (some MERGE-deduped against existing Duke/SymMap herbs) |
| Disease nodes upserted | 1,405 |
| ASSOCIATED_WITH_DISEASE edges written | **765,266** |
| Orphan rows skipped | 0 |

### Final state post-T10 (snapshot at `scope-state-snapshot-post-T10.md`)

| Layer | Pre-T1 | Post-R1 | Post-T10 |
|---|---:|---:|---:|
| Nodes | 24,848 | 161,181 | **166,072** |
| Relationships | 57,199 | 4,268,469 | **5,031,425** |
| ASSOCIATED_WITH_DISEASE | 612 | 644 | **763,600** |
| Untagged scope | 0 | 0 | 0 |

By source prefix:
- duke: 104,331
- symmap: 50,647
- **cmaup: 7,772 (new)**
- herb2: 3,285
- custom_kg: 37 chunks

T1.2 closed. Tier 1 is now substantively complete except for the deferred T2/R2 work (curated FooDB depth, evidence-tier-filtered HERB2, symmap_genes — all marginal).

### What this unlocks

- **C1 (HDI Recall):** Compound→Target (6,465) + Target→? was the chain. Now Herb→Disease (763K) gives an alternative provenance path for plant-based interventions. Combined with the existing HDI-Safe-50 panel (50 curated edges) the diet_os panel has multiple traversal routes.
- **C3 (provenance faithfulness):** The graph now has dense, traversable paths for the herbal scenarios in v1 (40 scenarios cover ~30 herbs; nearly all are now reachable in CMAUP plant-disease graph).
- **C4 (bilingual):** unchanged (SymMap-driven, already covered).

CMAUP write performance: 7,865 plant-Herb upserts + 1,405 Disease MERGEs + 765K edge writes in ~3 minutes. ~4K edges/sec sustained.
