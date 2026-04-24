# Dataset Moat — Adjacent-Dataset Survey

> Summary of the adjacent-dataset research for the paper's Dataset + Methods sections. Status as of 2026-04-22. For the primary paper's Methods (substrate description) and companion paper's Dataset section.

## Current baseline (SQLite intermediate, full breadth)

| Table | Count | Source |
|---|---|---|
| herbs | 2,376 | Duke |
| compounds | 94,512 | Duke |
| herb_compounds | 99,280 | Duke |
| compound_foods | 4,149,541 | FooDB |
| compound_targets | 7,053 | CMAUP |
| targets | 4,355 | CMAUP + TTD |
| target_diseases | 795,434 | CTD + TTD |
| chemical_diseases | present | CTD |
| symptoms | 47 | **Duke bioactivity-derived (not SymMap)** |
| herb_symptoms | 41,823 | **Duke-derived (not SymMap)** |
| food_nutrition_bridge | 0 (scripts exist, not executed) | OpenNutrition × FooDB |

**LightRAG KG state:** pinned prototype subsample (`MAX_RELATIONSHIPS=50000`). Task A9 un-pins this.

## Tier 1 — Additions for primary paper (critical path)

| Dataset | Count / content | Licensing | Ingest effort | Why primary |
|---|---|---|---|---|
| **NIH ODS Fact Sheets** | HDI narratives + safety notes for ~90 top herbs | Public domain | ~1 wk | Required source for HDI-Safe 50 |
| **MSK About Herbs** | Curated HDI, mechanism, evidence tier, ~280 herbs | Free non-commercial + citation | ~1 wk | Required source for HDI-Safe 50 |
| **LiverTox** | Hepatotoxicity profiles, evidence-graded | Public domain | ~3 d | Safety Reviewer — hepatotoxic-herb flagging |
| **HERB 2.0** | Evidence tiers (clinical/experimental/traditional), 1,241 herbs, bilingual CN/EN | Open academic | ~2 wk | Evidence-tier anchor for C3; bilingual TCM |
| **SymMap v2** | ~5,200 TCM symptoms, 1,717 herbs (CN/EN/pinyin/latin), 14 syndromes, 20K ingredients | Free academic | ~2 wk + 3–5 d symptom crosswalk | Real TCM symptom vocabulary; bilingual TCM |
| **food_nutrition_bridge** | FooDB↔OpenNutrition 5-strategy matcher (~900+ rows expected) | — | ~1 d | Nutrition-enriched Food nodes for Dietitian agent |

## Tier 2 — Additions for companion paper

| Dataset | Count / content | Licensing | Why companion |
|---|---|---|---|
| **TCMSP** | 499 herbs, 29,384 ingredients, 3,311 targets, 837 diseases, ADME/Lipinski filters | Free academic | TCM breadth + ADME support |
| **ETCM v2.0** | Formulas + ingredients + targets; 45K formula-ingredient links | Free academic | Formula-level reasoning |
| **HIT 2.0** | TCM ingredient-target with evidence tiers | Free academic | Complements CMAUP with TCM focus |
| **KNApSAcK** | ~100K metabolites × 20K species | Free | Broader phytochemistry |
| **Phenol-Explorer 3.6** | 501 polyphenols × 452 foods, bioavailability | Free | Dosing dimension |
| **DrugBank (open subset)** | Drug metadata, targets, interaction narratives | Mixed | Full HDI beyond Safe-50 |
| **PubChem** | Compound metadata, IUPAC, InChI, cross-refs | Open | Canonical compound IDs |
| **ChEMBL** | Bioactivity assays, IC50/EC50 quantitative binding | Open | Quantitative provenance edges |

## Tier 3 — Lower priority / future work

- UniProt (target protein metadata, GO annotations)
- MeSH / SNOMED-CT / ICD-10 (symptom/disease ontology alignment)
- RxNorm / ATC (drug naming standards for full HDI)
- Cochrane Reviews (systematic reviews for herbs)
- Natural Medicines Comprehensive DB (evidence-graded monographs; subscription only)

## Moat argument (for Discussion section)

The unified diet-bioactivity KG's durability derives from three compounding properties:

1. **Cross-ontology linkage.** The FooDB↔USDA-FDC food bridge and the CMAUP↔TTD↔CTD target bridge produce provenance chains no single database provides.
2. **Bilingual TCM–molecular reconciliation.** Classical Chinese herb names (SymMap, HERB 2.0) resolved to both biomedical compound IDs (PubChem-compatible) and molecular targets (CMAUP/TTD), a reconciliation absent from prior TCM KGs (SymMap, TCMSP, ETCM operate in Chinese only or lack target-level linkage).
3. **Evidence-tier provenance on every edge.** HERB 2.0 evidence labels + source_id tagging across all edges enable the compositional calibration in C3.

Each component is replicable in isolation; the composition has not been published.

## Data licensing map (for Ethics + Reproducibility section)

| Dataset | License | Citation requirement | Commercial OK |
|---|---|---|---|
| Duke Phytochemical | Public domain | USDA citation | Yes |
| FooDB | CC BY 4.0 | Citation | Yes |
| CMAUP | Free academic | Citation | Check |
| CTD | Open | Citation | Yes |
| TTD | Free academic | Citation | Check |
| OpenNutrition | USDA + CNF + AUSNUT + FRIDA | Composite | Yes (derivative) |
| SymMap v2 | Free academic | Citation | Research only |
| HERB 2.0 | Open academic | Citation | Research only |
| NIH ODS | Public domain | — | Yes |
| MSK About Herbs | Free non-commercial | Citation required | No — research only |
| LiverTox | Public domain | Citation | Yes |
| DrugBank | Mixed (open + licensed) | Citation | License for commercial |
| HDI-Safe 50 (our curation) | TBD (our license) | Self-citation | Depends on source-upstream |

**Key constraint:** MSK About Herbs is non-commercial. Any commercial derivative would require licensing — worth flagging in the companion paper's Availability section.
