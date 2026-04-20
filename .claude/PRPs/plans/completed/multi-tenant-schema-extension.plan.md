# Plan: Multi-Tenant Schema Extension (Phase 2)

## Summary
Extend entity_schema.py with 4 tenant-specific entity types (Protocol, Intervention, Outcome, Biomarker) and 7 tenant relationship types that connect the clinical practice layer to the shared biochemical layer. Add `scope` metadata to all entity/relationship extraction so new ingestions are always scope-tagged. These types enable AI agents to traverse from clinical protocols through interventions to measurable biomarker outcomes — the feedback loop required for treatment optimization.

## User Story
As a wellness clinic's AI agent,
I want to ingest clinic-specific protocols, interventions, outcomes, and biomarker measurements into the shared knowledge graph,
So that my queries can optimize treatment recommendations by linking clinical practice to biochemical evidence with measurable outcomes.

## Problem -> Solution
The current schema has 6 shared entity types (Herb, Compound, Food, Target, Disease, Symptom) and 5 relationship types — all biochemical. There is no support for clinical practice entities (what clinics prescribe, what they measure, what outcomes they observe) or scope metadata for tenant isolation. -> Extend with 4 orthogonal tenant entity types that form a clinical practice layer, 7 relationship types connecting practice to biochemistry, description generators, scope propagation, and tests.

## Design Rationale

### Why NOT Injectable, Supplement, ClinicalNote

The original PRD proposed Injectable, Supplement, ClinicalNote as tenant types. These were rejected:

| Rejected Type | Problem | Better Model |
|---|---|---|
| **Injectable** | Just a Compound with a delivery route. IV glutathione IS glutathione. Fragments graph traversal — agent can't unify "all things targeting GST" across oral/IV/topical. | **Intervention** with `route` property (IV/oral/topical/sublingual) pointing USES→Compound |
| **Supplement** | Just a branded product containing Compounds. Creates entity duplication at 40M scale. | **Intervention** with `form` property (capsule/powder/liquid) pointing USES→Compound/Herb |
| **ClinicalNote** | Unstructured free-text. Not queryable for optimization. No link to measurable evidence. | **Outcome** (structured: what changed) + **Biomarker** (what was measured) |

### Why These 4 Types

The clinic workflow — screening, testing, diagnosis, treatment, validation — maps to:

```
SHARED LAYER (biochemistry, 40M entries):
  Herb ─CONTAINS→ Compound ─TARGETS→ Target ─ASSOCIATED_WITH→ Disease
                      │                  │
                      └──FOUND_IN→ Food  └──linked to── Biomarker ←── TENANT
                                                              │
TENANT LAYER (clinical practice, per-clinic):                 │
  Protocol ─INCLUDES→ Intervention ─USES→ Compound     Biomarker
                           │                              ↑
                           └─RESULTED_IN→ Outcome ─MEASURED_BY─┘
```

- **Protocol**: Clinic's IP — ordered treatment plans with phases (screening/treatment/validation)
- **Intervention**: Unified therapeutic action (compound + route + dosage + frequency). One type replaces Injectable+Supplement
- **Outcome**: Structured clinical observation with measurable results. Links intervention → condition change
- **Biomarker**: Measurable physiological indicator (hsCRP, HbA1c, cortisol). The **missing link** that makes the graph optimizable — connects clinical observations to molecular targets

### Optimization Query This Enables

```cypher
// "What interventions targeting TNF-alpha improved hsCRP in Clinic A?"
MATCH (p:Protocol)-[:INCLUDES]->(i:Intervention)-[:USES]->(c:Compound)-[:TARGETS_PROTEIN]->(t:Target)
WHERE t.name = 'TNF-alpha' AND p.scope = 'tenant:clinic_a'
MATCH (i)-[:RESULTED_IN]->(o:Outcome)-[:MEASURED_BY]->(b:Biomarker)
WHERE b.name = 'hsCRP' AND o.direction = 'improved'
RETURN p.name, i.name, c.name, o.magnitude, o.timeframe
```

## Metadata
- **Complexity**: Medium
- **Source PRD**: `.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md`
- **PRD Phase**: Phase 2 — Schema Extension
- **Estimated Files**: 4 files modified, 0 new files

---

## UX Design

N/A — internal change. No user-facing UX transformation. This phase extends the Python data model; downstream phases (3, 4) wire it to MCP tools and ingestion APIs.

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 (critical) | `mcp-herbal-botanicals/lightrag/entity_schema.py` | all | Core file being extended — must follow all existing patterns exactly |
| P0 (critical) | `mcp-herbal-botanicals/lightrag/ingest_unified.py` | 74-155 | Entity/relationship extraction — must add scope metadata to output dicts |
| P1 (important) | `mcp-herbal-botanicals/lightrag/test_ingest.py` | all | Test patterns to mirror for new entity types |
| P1 (important) | `mcp-herbal-botanicals/lightrag/fix_unknown_entities.py` | 108-148 | Shows how entity classification works — new types must integrate |
| P2 (reference) | `.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md` | 99-124 | Entity-relationship schema extension spec (updated by this plan) |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| LightRAG ainsert_custom_kg | LightRAG repo / existing usage in ingest_unified.py | Entity dicts: `entity_name`, `entity_type`, `description`, `source_id`. Relationship dicts: `src_id`, `tgt_id`, `description`, `keywords`, `weight`, `source_id`. Additional metadata keys are preserved as node/edge properties. |

---

## Patterns to Mirror

### ENTITY_TYPE_DEFINITION
```python
# SOURCE: entity_schema.py:31-71
ENTITY_TYPES = {
    "Herb": {
        "source_table": "herbs",
        "id_field": "id",
        "name_field": "scientific_name",
        "query": "SELECT * FROM herbs",
    },
    "Disease": {
        "source_table": None,  # aggregated from multiple tables
        "id_field": "disease_name",
        "name_field": "disease_name",
        "query": None,
        "query_builder": "build_disease_query",
    },
}
```

### DESCRIPTION_GENERATOR
```python
# SOURCE: entity_schema.py:144-164
def describe_herb(row: dict[str, Any]) -> str:
    """Generate a rich description for an Herb entity."""
    parts = [row.get("scientific_name", "Unknown herb")]
    if row.get("common_name"):
        parts[0] += f" ({row['common_name']})"
    if row.get("family"):
        parts.append(f"Family: {row['family']}")
    # ... conditional field appends
    return ". ".join(parts)
```

### RELATIONSHIP_TYPE_DEFINITION
```python
# SOURCE: entity_schema.py:78-136
RELATIONSHIP_TYPES = {
    "CONTAINS_COMPOUND": {
        "source_table": "herb_compounds",
        "src_type": "Herb",
        "tgt_type": "Compound",
        "query": (...),
    },
}
```

### RELATIONSHIP_DESCRIPTION
```python
# SOURCE: entity_schema.py:295-338
def describe_relationship(rel_type: str, row: dict[str, Any]) -> tuple[str, str]:
    src = row.get("src_name", "?")
    tgt = row.get("tgt_name", "?")
    if rel_type == "CONTAINS_COMPOUND":
        part = row.get("plant_part", "")
        desc = f"{src} contains {tgt}"
        if part:
            desc += f" in {part}"
        return desc, "herb compound phytochemical contains"
```

### TEST_PATTERN
```python
# SOURCE: test_ingest.py:39-104
class TestDescriptionGenerators:
    def test_describe_herb_basic(self):
        row = {"scientific_name": "Curcuma longa", "common_name": "Turmeric", "family": "Zingiberaceae"}
        desc = describe_herb(row)
        assert "Curcuma longa" in desc
        assert "Turmeric" in desc
```

### ENTITY_EXTRACTION_OUTPUT
```python
# SOURCE: ingest_unified.py:109-114
entities.append({
    "entity_name": entity_name,
    "entity_type": entity_type,
    "description": description,
    "source_id": f"sqlite-{entity_type.lower()}",
})
```

### RELATIONSHIP_EXTRACTION_OUTPUT
```python
# SOURCE: ingest_unified.py:139-153
relationships.append({
    "src_id": src,
    "tgt_id": tgt,
    "description": description,
    "keywords": keywords,
    "weight": 1.0,
    "source_id": f"sqlite-{rel_type.lower()}",
})
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `mcp-herbal-botanicals/lightrag/entity_schema.py` | UPDATE | Add 4 tenant entity types, 7 tenant relationship types, description generators, update registries |
| `mcp-herbal-botanicals/lightrag/ingest_unified.py` | UPDATE | Add `scope: shared` to all entity/relationship output dicts; guard for None source_table in extract_relationships |
| `mcp-herbal-botanicals/lightrag/test_ingest.py` | UPDATE | Add tests for new description generators, relationship descriptions, and schema completeness |
| `mcp-herbal-botanicals/lightrag/fix_unknown_entities.py` | UPDATE | Add new entity types to classification awareness |

## NOT Building

- Query gateway middleware (Phase 3)
- Tenant ingestion API/MCP tool (Phase 4)
- Neo4j migration script to tag existing data (Phase 1 — already done)
- MCP tool changes for tenant-aware queries
- Cypher queries for tenant filtering
- Any TypeScript/MCP server changes
- PRD update for revised entity types (will update PRD when plan is implemented)

---

## Step-by-Step Tasks

### Task 1: Add tenant entity types to ENTITY_TYPES
- **ACTION**: Add Protocol, Intervention, Outcome, Biomarker to `ENTITY_TYPES` dict in entity_schema.py
- **IMPLEMENT**: These are tenant-only types with no SQLite source table. Set `source_table: None`, `query: None`, `id_field: "name"`, `name_field: "name"`. Add a comment block above separating "Shared entity types" from "Tenant entity types (clinical practice layer)".
  ```python
  # -- Tenant entity types (clinical practice layer) --
  "Protocol": {
      "source_table": None,
      "id_field": "name",
      "name_field": "name",
      "query": None,
  },
  "Intervention": {
      "source_table": None,
      "id_field": "name",
      "name_field": "name",
      "query": None,
  },
  "Outcome": {
      "source_table": None,
      "id_field": "name",
      "name_field": "name",
      "query": None,
  },
  "Biomarker": {
      "source_table": None,
      "id_field": "name",
      "name_field": "name",
      "query": None,
  },
  ```
- **MIRROR**: ENTITY_TYPE_DEFINITION pattern — same dict structure as Disease (which also has `source_table: None`)
- **IMPORTS**: None needed
- **GOTCHA**: `extract_entities()` at ingest_unified.py:84 already guards: `if spec["source_table"] and not table_exists(...)` — but `query: None` without a `query_builder` will hit the `if query is None` guard at line 95 and print a warning. That's fine for shared ingestion (tenant types have no SQLite data). To avoid the warning, add a `"tenant_only": True` flag and skip extraction entirely for tenant types.
- **VALIDATE**: `python -c "from entity_schema import ENTITY_TYPES; print(list(ENTITY_TYPES.keys()))"`

### Task 2: Add description generators for tenant entity types
- **ACTION**: Add `describe_protocol()`, `describe_intervention()`, `describe_outcome()`, `describe_biomarker()` functions to entity_schema.py
- **IMPLEMENT**: Each generator follows the `parts = [name]; if field: parts.append(...); return ". ".join(parts)` pattern. Fields per type:
  - **Protocol**: `name` (required), `description`, `target_conditions` (JSON list), `phase` (screening/treatment/validation), `duration`
  - **Intervention**: `name` (required), `compound` (what's administered), `route` (IV/oral/topical/sublingual), `dosage`, `frequency`, `form` (capsule/powder/liquid/injection)
  - **Outcome**: `name` (required), `observation`, `direction` (improved/worsened/unchanged), `magnitude`, `timeframe`, `condition`
  - **Biomarker**: `name` (required), `unit` (mg/dL, ng/mL, etc.), `normal_range`, `category` (inflammatory/metabolic/endocrine/nutritional), `target_gene` (links to shared Target)
- **MIRROR**: DESCRIPTION_GENERATOR pattern
- **IMPORTS**: None — `Any` and `json` already imported
- **GOTCHA**: Use `.get()` with fallbacks for all fields since tenant data may be sparse. Handle JSON list fields (`target_conditions`) with the same try/except pattern as `describe_herb()` uses for `alternate_names`.
- **VALIDATE**: Unit test in Task 8

### Task 3: Register new generators in DESCRIPTION_GENERATORS
- **ACTION**: Add all 4 new generators to the `DESCRIPTION_GENERATORS` dict
- **IMPLEMENT**: `"Protocol": describe_protocol, "Intervention": describe_intervention, "Outcome": describe_outcome, "Biomarker": describe_biomarker`
- **MIRROR**: Existing registry at entity_schema.py:280-287
- **IMPORTS**: None
- **GOTCHA**: Must match the exact key strings used in ENTITY_TYPES
- **VALIDATE**: `python -c "from entity_schema import DESCRIPTION_GENERATORS, ENTITY_TYPES; assert set(ENTITY_TYPES) == set(DESCRIPTION_GENERATORS)"`

### Task 4: Add tenant relationship types to RELATIONSHIP_TYPES
- **ACTION**: Add 7 tenant relationship types to `RELATIONSHIP_TYPES`
- **IMPLEMENT**: All have `source_table: None`, `query: None` (tenant-ingested via API in Phase 4). Add a comment block separating shared from tenant types. Structure:
  ```python
  # -- Tenant relationship types (clinical practice layer) --
  "INCLUDES": {
      "source_table": None,
      "src_type": "Protocol",
      "tgt_type": "Intervention",
      "query": None,
  },
  "USES": {
      "source_table": None,
      "src_type": "Intervention",
      "tgt_type": "Compound",  # also Herb, Food
      "query": None,
  },
  "RESULTED_IN": {
      "source_table": None,
      "src_type": "Intervention",
      "tgt_type": "Outcome",
      "query": None,
  },
  "MEASURED_BY": {
      "source_table": None,
      "src_type": "Outcome",
      "tgt_type": "Biomarker",
      "query": None,
  },
  "INDICATES": {
      "source_table": None,
      "src_type": "Biomarker",
      "tgt_type": "Disease",  # also Symptom
      "query": None,
  },
  "CONTRAINDICATES": {
      "source_table": None,
      "src_type": "Compound",  # also Intervention
      "tgt_type": "Disease",   # also Symptom
      "query": None,
  },
  "SYNERGIZES_WITH": {
      "source_table": None,
      "src_type": "Compound",  # also Intervention → Intervention
      "tgt_type": "Compound",
      "query": None,
  },
  ```
- **MIRROR**: RELATIONSHIP_TYPE_DEFINITION pattern
- **IMPORTS**: None
- **GOTCHA**: `extract_relationships()` calls `table_exists(conn, spec["source_table"])` — if `source_table` is None, `table_exists` receives None and fails. Must add guard (Task 6).
- **VALIDATE**: `python -c "from entity_schema import RELATIONSHIP_TYPES; print(list(RELATIONSHIP_TYPES.keys()))"`

### Task 5: Add relationship descriptions for tenant types
- **ACTION**: Extend `describe_relationship()` function with cases for the 7 new relationship types
- **IMPLEMENT**: Add elif branches following the existing pattern:
  - `INCLUDES`: `"{src} includes intervention {tgt}"` + phase/order; keywords: `"protocol intervention treatment plan includes"`
  - `USES`: `"{src} uses {tgt}"` + route/dosage; keywords: `"intervention compound administration uses therapeutic"`
  - `RESULTED_IN`: `"{src} resulted in {tgt}"` + timeframe; keywords: `"intervention outcome result clinical effect"`
  - `MEASURED_BY`: `"{src} measured by {tgt}"` + value/unit; keywords: `"outcome biomarker measurement laboratory"`
  - `INDICATES`: `"{src} indicates {tgt}"` + evidence_level; keywords: `"biomarker disease indicator diagnostic marker"`
  - `CONTRAINDICATES`: `"{src} contraindicated with {tgt}"` + reason/severity; keywords: `"contraindication warning interaction safety adverse"`
  - `SYNERGIZES_WITH`: `"{src} synergizes with {tgt}"` + mechanism; keywords: `"synergy combination interaction enhancement potentiation"`
- **MIRROR**: RELATIONSHIP_DESCRIPTION pattern
- **IMPORTS**: None
- **GOTCHA**: Fallback at end of function already handles unknown types. Specific descriptions improve semantic search quality in LightRAG.
- **VALIDATE**: Unit test in Task 8

### Task 6: Guard extract_relationships for None source_table and add scope metadata
- **ACTION**: In `extract_relationships()` in ingest_unified.py, add a guard for None source_table. Also add `"scope": "shared"` to relationship output dicts.
- **IMPLEMENT**: After `spec = RELATIONSHIP_TYPES[rel_type]`, add:
  ```python
  if spec.get("source_table") is None:
      return []
  ```
  Then in the relationship dict (line ~143), add `"scope": "shared"`.
- **MIRROR**: extract_entities guard at ingest_unified.py:84
- **IMPORTS**: None
- **GOTCHA**: Without this guard, calling `extract_relationships()` on tenant types would pass None to `table_exists()` and crash.
- **VALIDATE**: `python -c "from ingest_unified import extract_relationships; import sqlite3; conn = sqlite3.connect(':memory:'); print(extract_relationships(conn, 'INCLUDES'))"`

### Task 7: Add scope metadata to entity extraction and skip tenant types
- **ACTION**: In `extract_entities()` in ingest_unified.py, add `"scope": "shared"` to entity output dicts. Also skip tenant-only types gracefully during shared ingestion.
- **IMPLEMENT**: In the entity dict (line ~109), add `"scope": "shared"`. In the extraction loop in `main()` (line ~256), check for `spec.get("source_table") is None and "query_builder" not in spec` to skip tenant types without printing misleading warnings.
- **MIRROR**: ENTITY_EXTRACTION_OUTPUT pattern
- **IMPORTS**: None
- **GOTCHA**: LightRAG's `ainsert_custom_kg()` preserves extra keys as Neo4j properties — verified by how `source_id` flows through. The `scope` key becomes a node/edge property.
- **VALIDATE**: Dry-run: `python ingest_unified.py --config local --dry-run`

### Task 8: Update fix_unknown_entities.py classification
- **ACTION**: Add Protocol, Intervention, Outcome, Biomarker awareness to the classifier
- **IMPLEMENT**: Add a `TENANT_ENTITY_TYPES` set at module level. In `classify_entity()`, add an early check: if entity_id matches known biomarker patterns (e.g. "hsCRP", "HbA1c", "cortisol", "25-hydroxyvitamin D"), classify as Biomarker. This prevents biomarker names from being misclassified as Compound by the fallback logic.
  ```python
  BIOMARKER_INDICATORS = {
      "HSCRP", "HBA1C", "CORTISOL", "TSH", "INSULIN", "HOMOCYSTEINE",
      "FERRITIN", "TESTOSTERONE", "ESTRADIOL", "DHEA", "IGF-1",
  }
  ```
- **MIRROR**: Existing set-based classification pattern (MINERALS, VITAMINS, etc.)
- **IMPORTS**: None
- **GOTCHA**: Tenant entities are unlikely to appear as UNKNOWN (they're ingested with explicit types), but biomarker names could appear as edge endpoints from shared data. Defensive classification is warranted.
- **VALIDATE**: `python -c "from fix_unknown_entities import classify_entity; print(classify_entity('hsCRP'))"`

### Task 9: Write tests for new schema
- **ACTION**: Add test cases to test_ingest.py for all new description generators, relationship descriptions, and schema completeness
- **IMPLEMENT**:
  Add imports:
  ```python
  from entity_schema import (
      # ... existing imports ...
      describe_protocol,
      describe_intervention,
      describe_outcome,
      describe_biomarker,
  )
  ```
  Add to `TestDescriptionGenerators`:
  - `test_describe_protocol_full` — row with name, description, target_conditions (JSON list), phase, duration
  - `test_describe_protocol_minimal` — row with only name (sparse tenant data, no crash)
  - `test_describe_intervention_full` — row with name, compound, route, dosage, frequency
  - `test_describe_intervention_minimal` — row with only name
  - `test_describe_outcome_full` — row with name, observation, direction, magnitude, timeframe
  - `test_describe_biomarker_full` — row with name, unit, normal_range, category, target_gene
  - `test_describe_biomarker_minimal` — row with only name
  - `test_describe_relationship_includes` — INCLUDES rel
  - `test_describe_relationship_uses` — USES rel with route/dosage
  - `test_describe_relationship_resulted_in` — RESULTED_IN rel
  - `test_describe_relationship_measured_by` — MEASURED_BY rel
  - `test_describe_relationship_indicates` — INDICATES rel
  - `test_describe_relationship_contraindicates` — CONTRAINDICATES rel
  - `test_describe_relationship_synergizes_with` — SYNERGIZES_WITH rel
  Add to `TestEntitySchema`:
  - `test_tenant_entity_types_have_no_source_table` — verify Protocol/Intervention/Outcome/Biomarker have `source_table: None`
  - `test_tenant_relationship_types_have_no_source_table` — verify all 7 tenant rel types have `source_table: None`
  - `test_all_entity_types_have_generators` — existing test already covers this (it iterates all ENTITY_TYPES)
- **MIRROR**: TEST_PATTERN
- **IMPORTS**: See above
- **GOTCHA**: Existing `test_all_entity_types_have_generators` and `test_all_relationship_types_have_queries` will automatically cover new types. The rel test checks for "query" key existence, not that query is non-None — `query: None` satisfies `"query" in spec`.
- **VALIDATE**: `cd mcp-herbal-botanicals/lightrag && python -m pytest test_ingest.py -v`

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| describe_protocol full | Row with all fields | Contains name, conditions, phase | No |
| describe_protocol minimal | Row with only name | Contains name, no crash | Yes — sparse tenant data |
| describe_intervention full | Row with compound, route, dosage, frequency | Contains all fields | No |
| describe_intervention minimal | Row with only name | Contains name, no crash | Yes |
| describe_outcome full | Row with observation, direction, magnitude | Contains all fields | No |
| describe_biomarker full | Row with unit, range, category, target_gene | Contains all fields | No |
| describe_biomarker minimal | Row with only name | Contains name, no crash | Yes |
| describe_relationship INCLUDES | src/tgt + phase | "includes" in desc | No |
| describe_relationship USES | src/tgt + route/dosage | "uses" in desc | No |
| describe_relationship RESULTED_IN | src/tgt + timeframe | "resulted in" in desc | No |
| describe_relationship MEASURED_BY | src/tgt + value | "measured by" in desc | No |
| describe_relationship INDICATES | src/tgt | "indicates" in desc | No |
| describe_relationship CONTRAINDICATES | src/tgt + reason | "contraindicated" in desc | No |
| describe_relationship SYNERGIZES_WITH | src/tgt + mechanism | "synergizes" in desc | No |
| tenant entity types no source | Protocol et al | source_table is None | No |
| tenant rel types no source | INCLUDES et al | source_table is None | No |
| schema completeness | All ENTITY_TYPES | All have generators | No |

### Edge Cases Checklist
- [x] Empty/missing fields in tenant entity descriptions (sparse data)
- [x] JSON list fields (target_conditions) with invalid JSON
- [x] Relationship types with None source_table don't crash extract_relationships
- [x] Biomarker names not misclassified as Compound in fix_unknown_entities
- [ ] Concurrent access — N/A (schema is read-only module state)
- [ ] Network failure — N/A (no network calls in this phase)

---

## Validation Commands

### Static Analysis
```bash
cd mcp-herbal-botanicals/lightrag && python -m py_compile entity_schema.py && python -m py_compile ingest_unified.py && python -m py_compile fix_unknown_entities.py
```
EXPECT: Zero errors

### Unit Tests
```bash
cd mcp-herbal-botanicals/lightrag && python -m pytest test_ingest.py -v
```
EXPECT: All tests pass (existing + ~17 new)

### Schema Completeness Check
```bash
cd mcp-herbal-botanicals/lightrag && python -c "
from entity_schema import ENTITY_TYPES, DESCRIPTION_GENERATORS, RELATIONSHIP_TYPES
assert set(ENTITY_TYPES) == set(DESCRIPTION_GENERATORS), 'Mismatch: types vs generators'
shared_et = [k for k, v in ENTITY_TYPES.items() if v.get('source_table') is not None or 'query_builder' in v]
tenant_et = [k for k, v in ENTITY_TYPES.items() if v.get('source_table') is None and 'query_builder' not in v]
shared_rt = [k for k, v in RELATIONSHIP_TYPES.items() if v.get('source_table') is not None]
tenant_rt = [k for k, v in RELATIONSHIP_TYPES.items() if v.get('source_table') is None]
print(f'Shared entity types ({len(shared_et)}): {shared_et}')
print(f'Tenant entity types ({len(tenant_et)}): {tenant_et}')
print(f'Shared relationship types ({len(shared_rt)}): {shared_rt}')
print(f'Tenant relationship types ({len(tenant_rt)}): {tenant_rt}')
print('Schema complete ✓')
"
```
EXPECT: 6 shared + 4 tenant entity types, 5 shared + 7 tenant relationship types

### Dry Run
```bash
cd mcp-herbal-botanicals/lightrag && python ingest_unified.py --config local --dry-run
```
EXPECT: Runs without error; tenant types skipped cleanly (no "⚠ No query" warnings for them)

### Manual Validation
- [ ] All 4 new entity types in ENTITY_TYPES: Protocol, Intervention, Outcome, Biomarker
- [ ] All 7 new relationship types in RELATIONSHIP_TYPES: INCLUDES, USES, RESULTED_IN, MEASURED_BY, INDICATES, CONTRAINDICATES, SYNERGIZES_WITH
- [ ] All description generators registered in DESCRIPTION_GENERATORS (10 total)
- [ ] `scope: shared` present in extract_entities output dicts
- [ ] `scope: shared` present in extract_relationships output dicts
- [ ] extract_relationships handles None source_table gracefully (returns [])
- [ ] extract_entities skips tenant types without "No query" warnings
- [ ] fix_unknown_entities recognizes biomarker names

---

## Acceptance Criteria
- [ ] All 9 tasks completed
- [ ] All validation commands pass
- [ ] Tests written and passing (~17 new tests)
- [ ] No Python syntax errors
- [ ] Schema completeness: 10 entity types, 12 relationship types
- [ ] Dry-run ingestion works without errors
- [ ] Existing tests still pass (no regressions)

## Completion Checklist
- [ ] Code follows discovered patterns (parts list → join, .get() with fallbacks)
- [ ] Error handling matches codebase style (try/except for JSON list fields)
- [ ] Tests follow test patterns (TestDescriptionGenerators class, assert "X" in desc)
- [ ] No hardcoded values
- [ ] No unnecessary scope additions
- [ ] Self-contained — no questions needed during implementation

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LightRAG ignores extra metadata keys (scope) | Low | High | Verified: source_id already passes through as property. Test with dry-run. |
| Existing test_all_entity_types_have_queries fails for tenant types | Medium | Low | Test checks key existence not value — `query: None` satisfies `"query" in spec` |
| Biomarker names misclassified in fix_unknown_entities | Medium | Low | Added BIOMARKER_INDICATORS set for explicit classification |
| PRD entity types diverge from implementation | Low | Medium | Will update PRD after implementation to reflect Protocol/Intervention/Outcome/Biomarker |

## Notes
- **Design decision**: Injectable and Supplement merged into Intervention (compound + delivery context). This avoids entity duplication at 40M scale and keeps graph traversal unified. Route/dosage/form are properties on Intervention or on the USES relationship.
- **Design decision**: ClinicalNote replaced by structured Outcome + Biomarker. This makes clinical observations queryable for optimization rather than opaque free-text blobs.
- **Biomarker is the key addition**: Without it, the graph has prescriptions and observations but no measurable feedback loop. Biomarker connects Outcome → Target, enabling `Intervention → Outcome → Biomarker → Target` evidence chains.
- Tenant entity types have no SQLite backing — they exist in the schema for type validation, description generation, and documentation of the data model
- The `scope` field in entity/relationship dicts will be picked up by LightRAG's `ainsert_custom_kg()` and stored as a Neo4j node/edge property — foundation for query-time tenant filtering in Phase 3
- Phase 1 (Scope Bootstrap) already tagged existing Neo4j data with `scope: shared` via Cypher — this phase ensures NEW ingestions also carry the scope tag
- The PRD's entity-relationship schema section should be updated after this implementation to reflect the revised types
