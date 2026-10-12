# Researcher's Guide — Diet Bioactivity KG

_How to use the KG as a working research surface, framed by what you're trying to learn — not by the tools._

This is the question-first companion to:
- [`mcp/README.md`](../mcp/README.md) — operator-facing tool reference
- [`docs/DATASET_PROVENANCE.md`](DATASET_PROVENANCE.md) — per-source license + edge counts for paper Methods

If you're integrating against the MCP API directly, start there. If you're a researcher trying to answer a question, start here.

## Pick your persona

Find the row that matches your work and jump to that section.

| You are… | You'll find this useful for | Section |
|---|---|---|
| **Clinical pharmacist / patient-safety researcher** | Drug-herb interaction screening for patients on chronic medication | [§1](#1-clinical-pharmacist) |
| **Nutrition researcher** | Mechanistic chains from food → compound → target → disease | [§2](#2-nutrition-researcher) |
| **TCM / classical medicine researcher** | Bilingual cross-walk between Chinese symptom names and modern disease nomenclature | [§3](#3-tcm-researcher) |
| **Symptom-Diet Optimizer (SDO) developer** | Programmatic queries for the [Diet Insight Engine](https://github.com/Syntropy-Health/diet-insight-engine) | [§4](#4-sdo-developer) |
| **Drug-discovery / hypothesis generator** | Natural-product seeding for a target gene | [§5](#5-hypothesis-generator) |
| **Systematic reviewer** | Bulk evidence-table extraction (herb-disease, compound-target) | [§6](#6-systematic-reviewer) |

## Getting access

All MCP calls require `Authorization: Bearer $ADMIN_API_TOKEN`. To obtain a token, see [`mcp/README.md` § Authentication](../mcp/README.md#authentication) — the canonical path is a Syntropy-Journals admin token (`sj_*` from `scripts/issue_admin_token.py`); Clerk admin sign-in works today; the static `MCP_API_KEY` is deprecated. **Do not commit any token to git.**

## Question → Tool map (cheat sheet)

| Research question | Tool | Returns |
|---|---|---|
| "What compounds are in food X?" | `kg_diet_to_compounds(food)` | List of Compound nodes with provenance |
| "What proteins does compound X target?" | `kg_compound_to_targets(compound)` | Compound→Target chains, evidence_tier |
| "What diseases are associated with compound X?" | `kg_compound_to_diseases(compound)` | Compound→Disease chains via Target |
| "What diseases is herb X associated with?" | `kg_herb_to_diseases(herb)` | Herb→Disease (CMAUP/HERB-backed) |
| "What symptoms does herb X treat?" | `kg_herb_to_symptoms(herb)` | Herb→Symptom (Duke + SymMap) |
| "What symptoms is compound X linked to?" | `kg_compound_to_symptoms(compound)` | Compound→Symptom via Herb |
| "Is drug X dangerous with herb Y?" | `kg_hdi_check(drug, herb)` | Severity, mechanism, source URL |
| "What's the modern disease for TCM term 阴虚?" | `kg_bilingual_term(term)` | Cross-walk to modern terminology |
| "Tell me about X" (open-ended) | `kg_query(question)` | **Currently degraded** — see [Limitations](#limitations-by-persona) |

All tools accept `top_k` (default 20) and respect `scope_filter=["shared"]` for the public KG.

---

## §1 Clinical pharmacist

**You're useful here when:** Your patient is on a chronic medication and you want to screen common dietary herbs and supplements for known interactions before recommending or vetoing them.

### Walkthrough — Warfarin patient screening

Goal: list every dietary herb known to interact dangerously with warfarin, with severity and mechanism.

```bash
# Per-herb screen — repeat for each candidate herb the patient mentions
curl -X POST $MCP_URL/mcp \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -d '{"name":"kg_hdi_check",
       "arguments":{"drug":"Warfarin","herb":"St. John'\''s Wort"}}'
```

Returns:
```json
{
  "interaction": {
    "severity": "severe",
    "mechanism_class": "CYP450",
    "evidence_tier": "clinical",
    "source_id": "hdi-safe-50:HDI-001",
    "source_url": "https://ods.od.nih.gov/factsheets/StJohnsWort/"
  }
}
```

**What's in the panel:** 50 curated drug-herb pairs spanning 35 drugs × 21 herbs. Sources are NIH ODS / MSK About Herbs / LiverTox — citable in a paper. Phase 0 alias resolution (2026-05-01) means herbs match by Latin name (`Hypericum perforatum`), common name (`St. John's Wort`), or any aliased form — no canonical-casing required.

**For paper Methods:** cite as "Drug-herb interactions sourced from the HDI-Safe-50 panel (n=50 curated pairs from NIH ODS, MSK About Herbs, LiverTox; severity tiers: contraindicated / severe / moderate / monitor)."

---

## §2 Nutrition researcher

**You're useful here when:** You want to mechanistically explain why a food is associated with a health outcome — not just correlate it.

### Walkthrough — "Why might turmeric help inflammation?"

Goal: build the mechanistic chain `turmeric → curcumin → COX-2/NF-κB → inflammatory disease`.

```bash
# Step 1: what compounds are in turmeric?
kg_diet_to_compounds("turmeric", top_k=10)
# → [Curcumin, Demethoxycurcumin, Bisdemethoxycurcumin, ...] (Duke + FooDB)

# Step 2: what proteins does curcumin target?
kg_compound_to_targets("curcumin", top_k=20)
# → [COX2, NF-kB, TNF-alpha, ...] (Duke + CMAUP)

# Step 3: what diseases are associated with curcumin?
kg_compound_to_diseases("curcumin", top_k=20)
# → returns Compound→Target→Disease chains, with evidence tier per edge
```

Each chain comes back as a `ProvenanceChain` with `edges[]`, each edge carrying `source_id` (so you can tell `duke:contains_compound` from `cmaup:compound_targets`) and `evidence_tier` where available.

**For paper Methods:** cite as "Mechanism chains derived from Dr. Duke's Phytochemical Database (food→compound), CMAUP v2.0 (compound→target), and per-edge provenance preserved in the Aura graph."

**Limitation to know:** evidence is positive-only (no null findings), and Duke/FooDB don't always agree on which compounds are *abundant* in a food vs merely *detectable*. Treat as hypothesis-generating, not effect-size-establishing.

---

## §3 TCM researcher

**You're useful here when:** You're bridging classical Chinese medicine vocabulary to modern Western disease nomenclature, or vice versa.

### Walkthrough — Map 阴虚 (yin deficiency) to modern conditions

```bash
# Step 1: cross-walk the TCM term
kg_bilingual_term("阴虚")
# → {english:"yin deficiency", aliases:["阴虚","yin deficiency","yin xu"], ...}

# Step 2: find herbs traditionally treating it
kg_herb_to_symptoms("阴虚", top_k=20)
# → [生地黄 / Rehmannia glutinosa, 玄参 / Scrophularia ningpoensis, ...]

# Step 3: find modern disease associations for those herbs
kg_herb_to_diseases("Rehmannia glutinosa", top_k=10)
# → [type-2 diabetes, autoimmune thyroiditis, ...] (CMAUP)
```

**What's in the bilingual layer:** SymMap 2.0 + HERB 2.0 — TCM-symptom ↔ herb ↔ modern-symptom ↔ modern-disease bridges. Bilingual aliases are stamped on every TCM-origin entity.

**For paper Methods:** cite as "TCM-modern terminology bridges from SymMap 2.0 (Wu et al., 2019) and HERB 2.0 (Fang et al., 2021), with bilingual aliases preserved per-node."

**Limitation to know:** ~28% of Symptom nodes have a MeSH UID stamp (Phase 1 NCBI overlay); the rest are TCM-specific terms with no MeSH equivalent. That's upstream-bound, not a coverage bug.

---

## §4 SDO developer

**You're useful here when:** You're building the [Diet Insight Engine](https://github.com/Syntropy-Health/diet-insight-engine) Symptom-Diet Optimizer and need programmatic, deterministic queries — not prose.

### Walkthrough — Symptom → food recommendation

```bash
# Symptom-first: what compounds are linked to "nausea"?
kg_compound_to_symptoms("nausea", top_k=30)
# Reverse the chain: which foods contain those compounds?
# Layer-B traversals expose `direction` parameter for reverse traversal.
```

The full chain `Symptom → Compound → Food` is a 2-hop traversal you can either issue as two calls (preferred — easier to filter intermediate) or as one `kg_traverse` call with `direction="in"` and `depth=2`. See `mcp/README.md` §Worked examples.

**Output shape stability:** every Layer-B tool returns `{chains: [{edges: [...]}], seeds_resolved: [...], raw_subgraph_node_count: N}`. Stable across versions; SDO can assume this contract.

**Performance:** typical 1-hop traversal returns in <500ms (Aura warm). Multi-tenant scope filter is enforced server-side — no client-side checks needed.

---

## §5 Hypothesis generator

**You're useful here when:** You have a target gene/protein in mind (e.g., from a disease GWAS) and want to seed natural-product drug discovery.

### Walkthrough — "Find dietary compounds that hit COX-2"

```bash
# Reverse traversal: which compounds target COX-2?
kg_traverse(start_label="Target", seed="COX-2",
            edge_types=["TARGETS_PROTEIN"], direction="in", depth=1, top_k=50)

# For each compound, find which foods contain it
kg_compound_to_food(compound, top_k=10)  # via kg_traverse direction="in" on FOUND_IN_FOOD
```

You now have a ranked list of dietary compounds bound to your target, plus the foods they're abundant in. Cross-reference with PubChem CID (stamped via Phase 2) for downstream cheminformatics.

**For paper Methods:** "Compound-target bindings from Dr. Duke's Phytochemical Database (n=6,465 edges) and CMAUP v2.0 (`compound_targets` table). Compounds standardized against PubChem CID via PUG-REST overlay (n≈1,200 mission-critical compounds, 94% match)."

---

## §6 Systematic reviewer

**You're useful here when:** You're populating an evidence table for a review and need to bulk-extract every (subject, predicate, object) row matching some filter.

### Walkthrough — All herbs associated with inflammatory bowel disease

```bash
# Disease as seed; reverse direction on ASSOCIATED_WITH_DISEASE
kg_traverse(start_label="Disease", seed="inflammatory bowel disease",
            edge_types=["ASSOCIATED_WITH_DISEASE"], direction="in",
            depth=1, top_k=200)
```

Returns up to 200 herb→disease edges with full per-edge provenance: `source_id` (`cmaup:plant_disease` or `herb2:experimental` or `herb2:clinical`), `evidence_tier`, edge-level metadata. Drop into your evidence-table CSV.

**Sources backing this query:**
- CMAUP v2.0 — 763,600 plant-disease associations (curated)
- HERB 2.0 — 5,300 high-tier (experimental + clinical) edges

**For paper Methods:** see [`docs/DATASET_PROVENANCE.md` §Citation guidance](DATASET_PROVENANCE.md#citation-guidance-for-paper-methods) for the canonical Methods paragraph.

---

## Limitations by persona

What the KG is **not** good at, framed by who's asking:

| Persona | Don't trust the KG for |
|---|---|
| Clinical pharmacist | Dose-response or pharmacokinetic reasoning. The HDI-Safe-50 panel is curated qualitative interaction risk, not a PK/PD model. Always cross-reference with a pharmacy-grade interaction checker. |
| Nutrition researcher | Effect sizes, RCT-grade evidence weighting. Edges are positive-association only — absence of an edge is not evidence of absence. |
| TCM researcher | One-to-one canonical mappings between TCM symptoms and modern conditions. The bridges are *associative* (this herb is used for both), not *equivalent*. |
| SDO developer | Open-ended natural-language Q&A via `kg_query` until [#7 Phase A](https://github.com/Syntropy-Health/shrine-health-bioactivity/issues/7) lands. Use Layer-B typed tools. |
| Hypothesis generator | Drug-drug interactions or synthetic chemistry — out of scope by design (drugs aren't diet). |
| Systematic reviewer | Negative results, retracted papers, study quality scoring. The KG curates upstream assertions; quality assessment stays in your review protocol. |

## Things in flight that will widen the surface

Tracked as GitHub issues; each has a design + acceptance criteria.

- [#7 Hybrid KG: ingest upstream paper sources](https://github.com/Syntropy-Health/shrine-health-bioactivity/issues/7) — paragraph-level provenance + restored hybrid-RAG retrieval
- [#5 `kg_query` Layer A degradation](https://github.com/Syntropy-Health/shrine-health-bioactivity/issues/5) — closed by #7 Phase A
- [#6 `kg_node_neighborhood` 400](https://github.com/Syntropy-Health/shrine-health-bioactivity/issues/6) — replacement with custom `/neighborhood` Cypher endpoint

## See also

- [`mcp/README.md`](../mcp/README.md) — full tool reference (input schemas, error codes, auth)
- [`docs/DATASET_PROVENANCE.md`](DATASET_PROVENANCE.md) — per-source provenance for paper Methods
- [`research-journal/shared/2026-05-01-phase-0-1-2-verification.md`](../research-journal/shared/2026-05-01-phase-0-1-2-verification.md) — current coverage proof
- [`shrine-diet-bioactivity/data/manifest.yaml`](../shrine-diet-bioactivity/data/manifest.yaml) — machine-readable dataset manifest
