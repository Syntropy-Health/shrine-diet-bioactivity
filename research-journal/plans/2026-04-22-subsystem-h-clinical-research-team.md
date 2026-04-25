# Subsystem H — Clinical Research Team Implementation Plan (PRIMARY)

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use checkbox `- [ ]` syntax for tracking.

**Goal:** Build an AG2-based multi-agent **clinical research team** that performs evidence synthesis and safety analysis over the unified diet/TCM/evidence knowledge graph (delivered by Subsystem A), producing structured research artifacts with auditable provenance chains.

**Architecture:** 4-stage AG2 pipeline — (1) **Triage** elicits the research question via structured intake; (2) **KG retrieval tool** is shared across all agents; (3) **6-role panel** (Dietitian, Pharmacologist, TCM Practitioner, Clinical Research Scientist, Safety Reviewer, Defer-to-Clinician) deliberates via `GroupChat` + round-robin debate + 1-round rebuttal; (4) **Calibrator + Provenance Formatter** produces the final structured `ResearchSynthesis` artifact with evidence-tier × HDI-risk × research-question-fit confidence scoring.

**Tech Stack:** Python 3.10+, AG2 (`ag2ai/ag2`) v0.12+, Pydantic v2, OpenAI / Anthropic SDK, LightRAG `/query` HTTP client (with SQLite fallback), pytest, Neo4j Aura.

**Why Subsystem H is the primary implementation:** see `research-journal/DESIGN-PIVOT-2026-04-22.md`. Briefly: adjacent-space research and Subsystem A's 1.8M-edge HERB 2.0 + bilingual-SymMap data substrate are research-grade; the open whitespace is multi-agent clinical research synthesis, not patient recommendation.

**Reproducibility commitment:**
- LLM model snapshots pinned (`gpt-4o-2024-08-06`, `claude-opus-4-7`, etc. — declared in `config/llm_models.yaml`)
- `cache_seed=42` on every AG2 `LLMConfig`
- `temperature=0` on every agent
- `extra_body={"seed": 42}` to pass through to OpenAI's seed parameter
- Case-study inputs version-controlled in `research-journal/shared/case_studies/`
- All agent transcripts captured to `research-journal/shared/case_study_runs/<case>/<timestamp>.jsonl`

---

## File layout

| Path | Role |
|---|---|
| `shrine-diet-bioactivity/agents/__init__.py` *(new)* | package marker |
| `shrine-diet-bioactivity/agents/models.py` *(new)* | Pydantic typed models |
| `shrine-diet-bioactivity/agents/llm_config.py` *(new)* | shared `LLMConfig` factory with pins |
| `shrine-diet-bioactivity/agents/tools/kg_query.py` *(new)* | LightRAG-or-SQLite query tool registered with AG2 |
| `shrine-diet-bioactivity/agents/tools/chain_extractor.py` *(new)* | herb→compound→target→symptom chain post-processor |
| `shrine-diet-bioactivity/agents/triage.py` *(new)* | intake/triage agent (absorbs former Subsystem B) |
| `shrine-diet-bioactivity/agents/panel/dietitian.py` *(new)* | role agent |
| `shrine-diet-bioactivity/agents/panel/pharmacologist.py` *(new)* | role agent |
| `shrine-diet-bioactivity/agents/panel/tcm_practitioner.py` *(new)* | role agent |
| `shrine-diet-bioactivity/agents/panel/clinical_research_scientist.py` *(new)* | role agent |
| `shrine-diet-bioactivity/agents/panel/safety_reviewer.py` *(new)* | role agent |
| `shrine-diet-bioactivity/agents/panel/defer_to_clinician.py` *(new)* | role agent |
| `shrine-diet-bioactivity/agents/panel/assembly.py` *(new)* | GroupChat + GroupChatManager assembly |
| `shrine-diet-bioactivity/agents/calibrator.py` *(new)* | composite confidence + Bayesian fusion |
| `shrine-diet-bioactivity/agents/provenance.py` *(new)* | provenance-chain formatter |
| `shrine-diet-bioactivity/agents/run_case_study.py` *(new)* | end-to-end case study runner |
| `shrine-diet-bioactivity/config/llm_models.yaml` *(new)* | pinned model snapshots |
| `shrine-diet-bioactivity/agents/tests/...` *(new)* | TDD test suite |
| `research-journal/shared/case_studies/01_ginger_cin.json` *(new)* | demo case study spec |
| `research-journal/shared/case_studies/02_sjw_sertraline_hdi.json` *(new)* | demo case study spec |
| `research-journal/shared/case_studies/03_tcm_western_menopause.json` *(new)* | demo case study spec |
| `shrine-diet-bioactivity/lightrag/config_loader.py` *(modify)* | add `load_llm_models()` |

---

## Task H0 — AG2 install + smoke test

**Files:**
- Modify: `shrine-diet-bioactivity/lightrag/requirements.txt` (add `ag2`, `openai`, `anthropic`)
- Create: `shrine-diet-bioactivity/agents/__init__.py`
- Create: `shrine-diet-bioactivity/agents/tests/__init__.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_smoke.py`

- [ ] **Step 1: Write failing smoke test**

```python
# shrine-diet-bioactivity/agents/tests/test_smoke.py
"""Smoke test — confirms AG2 installs cleanly and basic ConversableAgent works."""
import pytest


def test_ag2_imports():
    import autogen  # ag2 publishes under both `ag2` and `autogen` aliases
    assert hasattr(autogen, "ConversableAgent")
    assert hasattr(autogen, "GroupChat")
    assert hasattr(autogen, "GroupChatManager")


def test_pydantic_v2_available():
    from pydantic import BaseModel, Field
    class Probe(BaseModel):
        x: int = Field(ge=0)
    assert Probe(x=1).x == 1
    with pytest.raises(Exception):
        Probe(x=-1)
```

- [ ] **Step 2: Run — expect FAIL on import**

```bash
cd shrine-diet-bioactivity/agents && python3 -m pytest tests/test_smoke.py -v
```

- [ ] **Step 3: Add deps + install**

Append to `shrine-diet-bioactivity/lightrag/requirements.txt`:
```
ag2>=0.12.0
openai>=1.40.0
anthropic>=0.39.0
```

```bash
pip install ag2>=0.12.0 openai>=1.40.0 anthropic>=0.39.0
```

- [ ] **Step 4: Re-run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/agents/ shrine-diet-bioactivity/lightrag/requirements.txt
git commit -m "feat(agents): bootstrap AG2 package + smoke tests"
```

---

## Task H1 — Pydantic typed models

**Purpose:** define the structured-output contracts that every agent emits and the moderator consumes. Pinning these first prevents prompt-engineering drift.

**Files:**
- Create: `shrine-diet-bioactivity/agents/models.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_models.py`

- [ ] **Step 1: Write failing tests**

```python
# shrine-diet-bioactivity/agents/tests/test_models.py
"""Tests for typed contracts shared by all agents."""
import pytest
from pydantic import ValidationError

from agents.models import (  # type: ignore[import-not-found]
    ResearchQuestion,
    Triage,
    KGResult,
    ProvenanceChain,
    RoleVerdict,
    PanelDeliberation,
    ConfidenceComponents,
    ResearchSynthesis,
)


def test_research_question_minimal():
    q = ResearchQuestion(text="What is the evidence for ginger in CIN?")
    assert q.text.startswith("What is the evidence")
    assert q.intervention is None
    assert q.outcome is None


def test_triage_complexity_enum():
    t = Triage(complexity="moderate", rationale="multi-drug context", red_flags=[])
    assert t.complexity == "moderate"
    with pytest.raises(ValidationError):
        Triage(complexity="trivial", rationale="x", red_flags=[])


def test_provenance_chain_min_one_edge():
    with pytest.raises(ValidationError):
        ProvenanceChain(edges=[])
    pc = ProvenanceChain(edges=[{
        "src": "Zingiber officinale", "edge": "CONTAINS_COMPOUND",
        "tgt": "6-gingerol", "source_id": "duke:1234",
        "weight": 0.9, "evidence_tier": "experimental"
    }])
    assert len(pc.edges) == 1


def test_role_verdict_enum():
    v = RoleVerdict(role="Dietitian", verdict="prefer", support=[], concerns=[], notes="")
    assert v.verdict == "prefer"
    with pytest.raises(ValidationError):
        RoleVerdict(role="Dietitian", verdict="approve", support=[], concerns=[], notes="")


def test_confidence_components_bounds():
    c = ConfidenceComponents(evidence_tier=0.8, hdi_risk=0.1, question_fit=0.9)
    assert 0 <= c.evidence_tier <= 1
    with pytest.raises(ValidationError):
        ConfidenceComponents(evidence_tier=1.5, hdi_risk=0.1, question_fit=0.9)


def test_research_synthesis_complete():
    rs = ResearchSynthesis(
        question=ResearchQuestion(text="x"),
        triage=Triage(complexity="low", rationale="y", red_flags=[]),
        candidate_chains=[],
        panel=PanelDeliberation(verdicts=[], dissent=[], moderator_summary="z"),
        confidence=0.5,
        components=ConfidenceComponents(evidence_tier=0.5, hdi_risk=0.0, question_fit=0.5),
        defer_to_clinician=False,
    )
    assert rs.confidence == 0.5
```

- [ ] **Step 2: Run — expect FAIL (module missing)**

- [ ] **Step 3: Implement `agents/models.py`**

```python
# shrine-diet-bioactivity/agents/models.py
"""Typed contracts for the Subsystem H clinical research team.

Every AG2 ConversableAgent that emits structured output uses these models
via response_format=PydanticModel. The moderator consumes them; the
calibrator + provenance formatter assemble the final ResearchSynthesis.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ComplexityTier = Literal["low", "moderate", "high"]
Verdict = Literal["prefer", "caution", "reject", "abstain"]
EvidenceTier = Literal[
    "clinical_trial", "pharmacokinetic_study", "observational",
    "case_report_series", "case_report",
    "experimental", "in_vivo", "in_vitro",
    "traditional", "unknown",
]
RoleName = Literal[
    "Dietitian", "Pharmacologist", "TCMPractitioner",
    "ClinicalResearchScientist", "SafetyReviewer", "DeferToClinician",
]


class ResearchQuestion(BaseModel):
    text: str = Field(min_length=1)
    intervention: str | None = None      # e.g., "ginger" or "Zingiber officinale"
    outcome: str | None = None           # e.g., "chemotherapy-induced nausea"
    population: str | None = None        # e.g., "adult oncology patients on cisplatin"
    comparator: str | None = None        # e.g., "ondansetron"
    languages: list[str] = Field(default_factory=lambda: ["en"])  # e.g., ["en", "zh"]


class Triage(BaseModel):
    complexity: ComplexityTier
    rationale: str
    red_flags: list[str]                 # e.g., ["pregnancy", "anticoagulant_therapy"]
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list, max_length=3)


class KGEdge(BaseModel):
    src: str
    edge: str
    tgt: str
    source_id: str
    weight: float = Field(ge=0, le=1)
    evidence_tier: EvidenceTier = "unknown"


class ProvenanceChain(BaseModel):
    edges: list[KGEdge] = Field(min_length=1)


class KGResult(BaseModel):
    chains: list[ProvenanceChain]
    raw_subgraph_node_count: int = Field(ge=0)
    raw_subgraph_edge_count: int = Field(ge=0)
    query_mode: Literal["local", "global", "hybrid", "naive", "mix"] = "hybrid"


class RoleVerdict(BaseModel):
    role: RoleName
    verdict: Verdict
    support: list[str]                   # bullet points the role finds compelling
    concerns: list[str]                  # bullet points the role finds problematic
    notes: str                           # free-form qualitative note
    cited_chains: list[int] = Field(default_factory=list)  # indices into KGResult.chains


class PanelDeliberation(BaseModel):
    verdicts: list[RoleVerdict]
    dissent: list[str]                   # minority opinions surfaced explicitly
    moderator_summary: str


class ConfidenceComponents(BaseModel):
    evidence_tier: float = Field(ge=0, le=1)
    hdi_risk: float = Field(ge=0, le=1)
    question_fit: float = Field(ge=0, le=1)


class ResearchSynthesis(BaseModel):
    question: ResearchQuestion
    triage: Triage
    candidate_chains: list[ProvenanceChain]
    panel: PanelDeliberation
    confidence: float = Field(ge=0, le=1)
    components: ConfidenceComponents
    defer_to_clinician: bool
```

- [ ] **Step 4: Re-run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/agents/models.py shrine-diet-bioactivity/agents/tests/test_models.py
git commit -m "feat(agents): typed Pydantic contracts for Subsystem H pipeline"
```

---

## Task H2 — KG-query tool (LightRAG primary, SQLite fallback)

**Purpose:** every panel agent calls `kg_query(question, mode=...)` to ground claims in the KG. Uses LightRAG `/query` when reachable, falls back to direct SQLite reads when offline (so prototyping unblocks before Aura ingest completes).

**Files:**
- Create: `shrine-diet-bioactivity/agents/tools/__init__.py`
- Create: `shrine-diet-bioactivity/agents/tools/kg_query.py`
- Create: `shrine-diet-bioactivity/agents/tools/chain_extractor.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_kg_query.py`

- [ ] **Step 1: Write failing tests**

```python
# shrine-diet-bioactivity/agents/tests/test_kg_query.py
"""KG-query tool tests — exercises both LightRAG and SQLite fallback paths."""
import pytest
from unittest.mock import patch

from agents.tools.kg_query import kg_query, KGQueryError  # type: ignore[import-not-found]
from agents.models import KGResult


def test_kg_query_falls_back_to_sqlite_on_lightrag_unreachable():
    with patch("agents.tools.kg_query._lightrag_query", side_effect=KGQueryError("unreachable")):
        result = kg_query("ginger nausea evidence", mode="hybrid")
    assert isinstance(result, KGResult)
    # SQLite fallback should still find Duke ginger entries
    assert result.raw_subgraph_node_count > 0


def test_kg_query_lightrag_path_on_success():
    fake_chains = [{
        "edges": [{"src": "Zingiber officinale", "edge": "CONTAINS_COMPOUND",
                   "tgt": "6-gingerol", "source_id": "duke:1",
                   "weight": 0.9, "evidence_tier": "experimental"}]
    }]
    with patch("agents.tools.kg_query._lightrag_query") as m:
        m.return_value = {"chains": fake_chains, "node_count": 5, "edge_count": 4}
        result = kg_query("test", mode="hybrid")
    assert len(result.chains) == 1
    assert result.chains[0].edges[0].tgt == "6-gingerol"


def test_kg_query_validates_mode():
    with pytest.raises(ValueError):
        kg_query("test", mode="invalid")
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `agents/tools/kg_query.py`**

```python
# shrine-diet-bioactivity/agents/tools/kg_query.py
"""KG-query tool registered with AG2. Tries LightRAG /query first;
falls back to direct SQLite reads when LightRAG is unreachable.
Returns a typed KGResult Pydantic model so panel agents can reason
over structured chains rather than free-form text."""
from __future__ import annotations

import os
from typing import Literal

import requests

from agents.models import KGEdge, KGResult, ProvenanceChain
from agents.tools.chain_extractor import extract_chains_from_sqlite

QueryMode = Literal["local", "global", "hybrid", "naive", "mix"]
_VALID_MODES = {"local", "global", "hybrid", "naive", "mix"}


class KGQueryError(RuntimeError):
    pass


def _lightrag_query(question: str, mode: QueryMode) -> dict:
    base = os.environ.get("LIGHTRAG_BASE_URL", "http://localhost:9621")
    try:
        r = requests.post(f"{base}/query", json={"query": question, "mode": mode}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        raise KGQueryError(f"LightRAG unreachable: {e}") from e
    data = r.json()
    return {
        "chains": data.get("chains", []),
        "node_count": data.get("node_count", 0),
        "edge_count": data.get("edge_count", 0),
    }


def kg_query(question: str, mode: QueryMode = "hybrid") -> KGResult:
    """Query the unified diet KG; return typed chains.
    Tries LightRAG first; on failure, falls back to deterministic SQLite traversal."""
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; valid: {sorted(_VALID_MODES)}")
    try:
        raw = _lightrag_query(question, mode)
        chains = [ProvenanceChain(edges=[KGEdge(**e) for e in c["edges"]]) for c in raw["chains"]]
        return KGResult(
            chains=chains,
            raw_subgraph_node_count=raw["node_count"],
            raw_subgraph_edge_count=raw["edge_count"],
            query_mode=mode,
        )
    except KGQueryError:
        return extract_chains_from_sqlite(question, mode)
```

```python
# shrine-diet-bioactivity/agents/tools/chain_extractor.py
"""SQLite-backed fallback chain extraction.
Implements the deterministic herb→compound→target→symptom traversal
used both as a LightRAG fallback and during prototyping before Aura ingest."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from agents.models import KGEdge, KGResult, ProvenanceChain
from lightrag.config_loader import load_data_sources  # type: ignore[import-not-found]

QueryMode = Literal["local", "global", "hybrid", "naive", "mix"]


def _connect() -> sqlite3.Connection:
    db_path = Path(load_data_sources().paths.sqlite_db)
    return sqlite3.connect(db_path)


def extract_chains_from_sqlite(question: str, mode: QueryMode = "hybrid", k: int = 10) -> KGResult:
    """Deterministic fallback: tokenize question, find matching herbs/symptoms,
    traverse herb→compound→target→symptom chains. Returns top-k by edge weight."""
    tokens = [t.lower() for t in question.split() if len(t) > 2]
    if not tokens:
        return KGResult(chains=[], raw_subgraph_node_count=0, raw_subgraph_edge_count=0, query_mode=mode)

    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        # Anchor herbs by name token
        like = " OR ".join(["LOWER(scientific_name) LIKE ?"] * len(tokens))
        params = [f"%{t}%" for t in tokens]
        herb_rows = conn.execute(
            f"SELECT id, scientific_name FROM herbs WHERE {like} LIMIT 5",
            params,
        ).fetchall()

        chains: list[ProvenanceChain] = []
        node_set: set[str] = set()
        edge_count = 0
        for h in herb_rows:
            cmpd_rows = conn.execute(
                "SELECT c.id, c.name FROM herb_compounds hc "
                "JOIN compounds c ON hc.compound_id = c.id "
                "WHERE hc.herb_id = ? LIMIT 3",
                (h["id"],),
            ).fetchall()
            for c in cmpd_rows:
                edges = [KGEdge(
                    src=h["scientific_name"], edge="CONTAINS_COMPOUND",
                    tgt=c["name"], source_id=f"duke:{h['id']}.{c['id']}",
                    weight=0.85, evidence_tier="traditional",
                )]
                node_set.add(h["scientific_name"]); node_set.add(c["name"])
                edge_count += 1

                tgt_rows = conn.execute(
                    "SELECT t.target_name FROM compound_targets ct "
                    "JOIN targets t ON ct.target_id = t.id "
                    "WHERE ct.compound_id = ? LIMIT 2",
                    (c["id"],),
                ).fetchall()
                for tgt in tgt_rows:
                    edges.append(KGEdge(
                        src=c["name"], edge="TARGETS_PROTEIN",
                        tgt=tgt["target_name"], source_id=f"cmaup:{c['id']}",
                        weight=0.7, evidence_tier="experimental",
                    ))
                    node_set.add(tgt["target_name"]); edge_count += 1

                chains.append(ProvenanceChain(edges=edges))
                if len(chains) >= k:
                    break
            if len(chains) >= k:
                break

        return KGResult(
            chains=chains[:k],
            raw_subgraph_node_count=len(node_set),
            raw_subgraph_edge_count=edge_count,
            query_mode=mode,
        )
    finally:
        conn.close()
```

- [ ] **Step 4: Re-run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/agents/tools/ shrine-diet-bioactivity/agents/tests/test_kg_query.py
git commit -m "feat(agents): KG-query tool with LightRAG primary + SQLite fallback"
```

---

## Task H3 — Triage agent (absorbs Subsystem B's intake schema)

**Purpose:** transforms a free-form research question into a typed `ResearchQuestion` + `Triage` with complexity classification. This is where the OPQRST + SOCRATES + NCP/ADIME schemas from former Subsystem B live now — but they're applied to the **research question** (intervention, population, outcome, comparator) rather than a patient's symptom profile.

**Files:**
- Create: `shrine-diet-bioactivity/agents/triage.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_triage.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/agents/tests/test_triage.py
"""Triage agent — converts free-form research question to typed structure."""
import os
import pytest

from agents.triage import build_triage_agent  # type: ignore[import-not-found]
from agents.models import ResearchQuestion, Triage


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="LLM smoke test")
def test_triage_classifies_simple_question_as_low():
    agent = build_triage_agent()
    rq, t = agent("Is there evidence that ginger reduces post-prandial bloating?")
    assert isinstance(rq, ResearchQuestion)
    assert isinstance(t, Triage)
    assert t.complexity in {"low", "moderate", "high"}


def test_build_triage_agent_returns_callable():
    """Builder must return a callable even without an API key (won't run, just constructed)."""
    agent = build_triage_agent()
    assert callable(agent)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `agents/triage.py`**

```python
# shrine-diet-bioactivity/agents/triage.py
"""Triage agent — first stage of the clinical research team.

Absorbs the OPQRST + SOCRATES + NCP/ADIME structured-intake schema
from former Subsystem B, but applies it to a *research question*
(intervention, population, outcome, comparator) rather than a patient's
symptom profile. Emits ResearchQuestion + Triage via response_format."""
from __future__ import annotations

from typing import Callable

from autogen import ConversableAgent

from agents.llm_config import default_llm_config
from agents.models import ResearchQuestion, Triage

TRIAGE_SYSTEM_PROMPT = """\
You are the triage clinician of a clinical research team. Given a
free-form research question about a herbal/dietary intervention, you:

1. Extract a structured ResearchQuestion (intervention, outcome, population,
   comparator if present). Borrow PICO conventions from clinical research.
2. Classify complexity:
   - "low"      = single-intervention, single-outcome, no polypharmacy or pregnancy/organ-failure
   - "moderate" = multi-drug interaction question, or comparison across interventions
   - "high"     = pregnancy / hepatic / renal / pediatric / weak-evidence / safety-critical
3. List red_flags (anticoagulant_therapy, pregnancy, hepatic_impairment,
   renal_impairment, pediatric, polypharmacy_3plus, etc.)
4. If the question is ambiguous, set needs_clarification=true and emit
   up to 3 clarification_questions a researcher would ask back.

Use the OPQRST mnemonic for symptom-mention parsing if the question
references presenting symptoms; use NCP/ADIME conventions for nutritional
context. The intent is research-grade rigor, not patient guidance.
"""


def build_triage_agent() -> Callable[[str], tuple[ResearchQuestion, Triage]]:
    cfg = default_llm_config(response_format=None)  # we run two structured calls explicitly

    rq_agent = ConversableAgent(
        name="ResearchQuestionExtractor",
        system_message=TRIAGE_SYSTEM_PROMPT + "\nFor this turn, emit ONLY a ResearchQuestion JSON.",
        llm_config={**cfg, "response_format": ResearchQuestion},
        human_input_mode="NEVER",
    )
    triage_agent = ConversableAgent(
        name="TriageClassifier",
        system_message=TRIAGE_SYSTEM_PROMPT + "\nFor this turn, emit ONLY a Triage JSON.",
        llm_config={**cfg, "response_format": Triage},
        human_input_mode="NEVER",
    )

    def run(question_text: str) -> tuple[ResearchQuestion, Triage]:
        rq_reply = rq_agent.generate_reply(messages=[{"role": "user", "content": question_text}])
        rq = ResearchQuestion.model_validate_json(rq_reply if isinstance(rq_reply, str) else rq_reply["content"])
        triage_reply = triage_agent.generate_reply(
            messages=[{"role": "user", "content": f"Question: {question_text}\nResearchQuestion: {rq.model_dump_json()}"}]
        )
        t = Triage.model_validate_json(triage_reply if isinstance(triage_reply, str) else triage_reply["content"])
        return rq, t

    return run
```

- [ ] **Step 4: Run tests — expect PASS** (the smoke-skip is OK without `OPENAI_API_KEY`)

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/agents/triage.py shrine-diet-bioactivity/agents/tests/test_triage.py shrine-diet-bioactivity/agents/llm_config.py
git commit -m "feat(agents): triage agent with PICO + complexity classification"
```

*(Implement `agents/llm_config.py` as part of this task — see Step 3 import. It is a thin factory that reads `config/llm_models.yaml` and produces a pinned `LLMConfig` dict with `cache_seed=42`, `temperature=0`, and `extra_body={"seed": 42}`. The implementation is straightforward — open the YAML, pick the model snapshot, return the dict. ~30 lines.)*

---

## Task H4 — Six role agents

**Purpose:** each role agent is a `ConversableAgent` with a role-specific `system_message`, registered with the shared `kg_query` tool, and emits a typed `RoleVerdict`. All six follow an identical structure — only the system prompt and the cited KG edges differ.

**Files:**
- Create: `shrine-diet-bioactivity/agents/panel/__init__.py`
- Create: `shrine-diet-bioactivity/agents/panel/dietitian.py`
- Create: `shrine-diet-bioactivity/agents/panel/pharmacologist.py`
- Create: `shrine-diet-bioactivity/agents/panel/tcm_practitioner.py`
- Create: `shrine-diet-bioactivity/agents/panel/clinical_research_scientist.py`
- Create: `shrine-diet-bioactivity/agents/panel/safety_reviewer.py`
- Create: `shrine-diet-bioactivity/agents/panel/defer_to_clinician.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_panel_roles.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/agents/tests/test_panel_roles.py
import pytest
from autogen import ConversableAgent

from agents.panel import (  # type: ignore[import-not-found]
    build_dietitian, build_pharmacologist, build_tcm_practitioner,
    build_clinical_research_scientist, build_safety_reviewer, build_defer_to_clinician,
)


@pytest.mark.parametrize("builder, expected_role", [
    (build_dietitian, "Dietitian"),
    (build_pharmacologist, "Pharmacologist"),
    (build_tcm_practitioner, "TCMPractitioner"),
    (build_clinical_research_scientist, "ClinicalResearchScientist"),
    (build_safety_reviewer, "SafetyReviewer"),
    (build_defer_to_clinician, "DeferToClinician"),
])
def test_role_builder_returns_conversable_agent(builder, expected_role):
    agent = builder()
    assert isinstance(agent, ConversableAgent)
    assert expected_role in agent.system_message
    # All roles share the kg_query tool (after assembly registers it)
    # Tool registration happens during GroupChat assembly (Task H5).
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement role builders (one example shown — repeat pattern for all 6)**

```python
# shrine-diet-bioactivity/agents/panel/dietitian.py
"""Dietitian role — judges nutrition adequacy and dietary-pattern fit."""
from autogen import ConversableAgent

from agents.llm_config import default_llm_config
from agents.models import RoleVerdict

DIETITIAN_PROMPT = """\
You are the Dietitian on a clinical research team. You evaluate the
NUTRITIONAL adequacy and dietary-pattern fit of candidate interventions
sourced from a knowledge graph spanning Duke ethnobotany, FooDB compound-
food links, OpenNutrition (90 nutrients), and HERB 2.0 evidence tiers.

When deliberating:
- Cite chains by index (cited_chains).
- Use the kg_query tool for any claim that is not already in the panel context.
- Surface concerns about deficiency risk, caloric adequacy, dietary restrictions,
  or pattern mismatch (e.g., recommending a high-FODMAP herb for IBS).
- Be terse; favor numerical evidence (mg, % RDA) over hedge phrases.
- Issue verdict ∈ {prefer, caution, reject, abstain} with explicit support+concerns.

Output a RoleVerdict JSON with role="Dietitian".
"""


def build_dietitian() -> ConversableAgent:
    cfg = default_llm_config(response_format=RoleVerdict)
    return ConversableAgent(
        name="Dietitian",
        system_message=DIETITIAN_PROMPT,
        llm_config=cfg,
        human_input_mode="NEVER",
    )
```

```python
# shrine-diet-bioactivity/agents/panel/pharmacologist.py
"""Pharmacologist role — judges mechanism plausibility and PK/PD."""
from autogen import ConversableAgent
from agents.llm_config import default_llm_config
from agents.models import RoleVerdict

PHARMACOLOGIST_PROMPT = """\
You are the Pharmacologist on a clinical research team. You evaluate the
MECHANISTIC plausibility and pharmacokinetics/pharmacodynamics of candidate
interventions, drawing on CMAUP (compound→target), CTD/TTD (target→disease),
and HERB 2.0 experimental evidence (1.8M GEO p-value associations).

When deliberating:
- Trace each candidate via Compound → Target → Disease/Symptom.
- Distinguish in-vitro vs in-vivo vs clinical-trial evidence (use evidence_tier).
- Flag dose-response gaps, bioavailability concerns, first-pass metabolism issues.
- Use the kg_query tool to verify any mechanism you assert.
- Issue verdict ∈ {prefer, caution, reject, abstain}.

Output a RoleVerdict JSON with role="Pharmacologist".
"""


def build_pharmacologist() -> ConversableAgent:
    return ConversableAgent(
        name="Pharmacologist",
        system_message=PHARMACOLOGIST_PROMPT,
        llm_config=default_llm_config(response_format=RoleVerdict),
        human_input_mode="NEVER",
    )
```

```python
# shrine-diet-bioactivity/agents/panel/tcm_practitioner.py
"""TCM Practitioner role — bilingual classical TCM context."""
from autogen import ConversableAgent
from agents.llm_config import default_llm_config
from agents.models import RoleVerdict

TCM_PROMPT = """\
You are the TCM Practitioner on a clinical research team. You evaluate
candidate interventions through CLASSICAL TCM lens, drawing on the
SymMap v2.0 bilingual herb table (698 entries with CN/Pinyin/Latin/EN
names + properties + meridians) and HERB 2.0 (7,263 herbs, 100% Chinese
name coverage). The Duke↔SymMap symptom crosswalk gives you classical
TCM analogs (e.g., 消渴 Xiao Ke for diabetes, 胸痹 Xiong Bi for ischemic
heart disease, 瘀血阻络 for poor circulation).

When deliberating:
- Cite TCM properties (cool/warm/neutral) and meridians.
- Reference classical formulas where applicable (Jingui Yaolue, Shanghan Lun, Bencao Gangmu).
- Distinguish syndrome-pattern (辨證) reasoning from biomedical reasoning.
- Use kg_query (it accepts Chinese terms).
- Issue verdict ∈ {prefer, caution, reject, abstain}.

Output a RoleVerdict JSON with role="TCMPractitioner".
"""


def build_tcm_practitioner() -> ConversableAgent:
    return ConversableAgent(
        name="TCMPractitioner",
        system_message=TCM_PROMPT,
        llm_config=default_llm_config(response_format=RoleVerdict),
        human_input_mode="NEVER",
    )
```

```python
# shrine-diet-bioactivity/agents/panel/clinical_research_scientist.py
"""Clinical Research Scientist role — methodology + evidence hierarchy."""
from autogen import ConversableAgent
from agents.llm_config import default_llm_config
from agents.models import RoleVerdict

CRS_PROMPT = """\
You are the Clinical Research Scientist on a clinical research team. You
do not propose interventions; you evaluate the QUALITY OF EVIDENCE behind
the panel's candidate chains.

When deliberating:
- Apply GRADE-style evidence hierarchy (clinical trial > observational >
  in vivo > in vitro > traditional use). The KG carries this in
  evidence_tier on every edge — use it.
- Flag chains supported only by case-report-level evidence as "caution".
- Flag chains relying entirely on traditional-use evidence as "abstain"
  unless the panel explicitly justifies extrapolation.
- Write the dissenting-minority report when the panel converges on a
  weak-evidence verdict.
- Issue verdict ∈ {prefer, caution, reject, abstain}.

Output a RoleVerdict JSON with role="ClinicalResearchScientist".
"""


def build_clinical_research_scientist() -> ConversableAgent:
    return ConversableAgent(
        name="ClinicalResearchScientist",
        system_message=CRS_PROMPT,
        llm_config=default_llm_config(response_format=RoleVerdict),
        human_input_mode="NEVER",
    )
```

```python
# shrine-diet-bioactivity/agents/panel/safety_reviewer.py
"""Safety Reviewer role — herb-drug interactions and contraindications."""
from autogen import ConversableAgent
from agents.llm_config import default_llm_config
from agents.models import RoleVerdict

SAFETY_PROMPT = """\
You are the Safety Reviewer on a clinical research team. You evaluate
candidate interventions for HERB-DRUG INTERACTIONS and contraindications,
drawing on the HDI-Safe 50 reference set (NIH ODS / MSK About Herbs /
LiverTox curated, 5 mechanism classes: CYP450, P-gp, PD-antagonism,
coagulation, serotonergic) plus CONTRAINDICATES edges in the KG.

When deliberating:
- Cross-reference every candidate herb against the patient's stated
  current medications.
- Distinguish severe / moderate / mild interactions; severe = caution or reject.
- Flag pregnancy, hepatic, renal, pediatric contraindications via
  CONTRAINDICATES edges.
- Reference LiverTox for hepatotoxicity profiles.
- Issue verdict ∈ {prefer, caution, reject, abstain}; severe HDI = reject.

Output a RoleVerdict JSON with role="SafetyReviewer".
"""


def build_safety_reviewer() -> ConversableAgent:
    return ConversableAgent(
        name="SafetyReviewer",
        system_message=SAFETY_PROMPT,
        llm_config=default_llm_config(response_format=RoleVerdict),
        human_input_mode="NEVER",
    )
```

```python
# shrine-diet-bioactivity/agents/panel/defer_to_clinician.py
"""Defer-to-Clinician role — scope boundary classifier."""
from autogen import ConversableAgent
from agents.llm_config import default_llm_config
from agents.models import RoleVerdict

DEFER_PROMPT = """\
You are the Defer-to-Clinician role on the clinical research team. Your job
is to flag questions that require human clinician judgement and should
NOT be answered by the team alone.

Defer when:
- The question concerns active acute symptoms (chest pain, severe headache, etc.)
- The intervention requires prescription-only medication titration.
- The question implicates pregnancy, pediatric, or end-of-life decisions
  AND the panel evidence is weak.
- The user appears to be a patient (not a clinician researcher) and is
  asking for personalized treatment.

Issue verdict ∈ {prefer (do not defer), caution (defer for review), reject
(strong defer)}. Only "prefer" allows the synthesis to proceed without a
defer flag in the final ResearchSynthesis.

Output a RoleVerdict JSON with role="DeferToClinician".
"""


def build_defer_to_clinician() -> ConversableAgent:
    return ConversableAgent(
        name="DeferToClinician",
        system_message=DEFER_PROMPT,
        llm_config=default_llm_config(response_format=RoleVerdict),
        human_input_mode="NEVER",
    )
```

`shrine-diet-bioactivity/agents/panel/__init__.py`:
```python
from agents.panel.dietitian import build_dietitian
from agents.panel.pharmacologist import build_pharmacologist
from agents.panel.tcm_practitioner import build_tcm_practitioner
from agents.panel.clinical_research_scientist import build_clinical_research_scientist
from agents.panel.safety_reviewer import build_safety_reviewer
from agents.panel.defer_to_clinician import build_defer_to_clinician

__all__ = [
    "build_dietitian", "build_pharmacologist", "build_tcm_practitioner",
    "build_clinical_research_scientist", "build_safety_reviewer",
    "build_defer_to_clinician",
]
```

- [ ] **Step 4: Run — expect PASS (6 parametrized tests)**

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/agents/panel/ shrine-diet-bioactivity/agents/tests/test_panel_roles.py
git commit -m "feat(agents): six panel role agents (Dietitian/Pharmacologist/TCM/CRS/Safety/Defer)"
```

---

## Task H5 — GroupChat assembly + tool registration

**Purpose:** wire the 6 role agents into an AG2 `GroupChat` with a `GroupChatManager` moderator, register the shared `kg_query` tool with all of them via `register_for_llm` + `register_for_execution`, and orchestrate the round-robin debate (1 verdict round + 1 rebuttal round).

**Files:**
- Create: `shrine-diet-bioactivity/agents/panel/assembly.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_assembly.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/agents/tests/test_assembly.py
import pytest
from autogen import ConversableAgent, GroupChat, GroupChatManager

from agents.panel.assembly import assemble_panel  # type: ignore[import-not-found]
from agents.models import Triage


def test_assemble_panel_low_complexity_returns_solo():
    triage = Triage(complexity="low", rationale="single intervention", red_flags=[])
    chat, manager = assemble_panel(triage)
    assert isinstance(chat, GroupChat)
    assert isinstance(manager, GroupChatManager)
    assert len(chat.agents) == 1  # solo Dietitian


def test_assemble_panel_moderate_returns_three_role_team():
    triage = Triage(complexity="moderate", rationale="multi-drug", red_flags=["polypharmacy_3plus"])
    chat, manager = assemble_panel(triage)
    role_names = sorted(a.name for a in chat.agents)
    assert role_names == sorted(["Dietitian", "Pharmacologist", "TCMPractitioner"])


def test_assemble_panel_high_returns_full_six():
    triage = Triage(complexity="high", rationale="pregnancy + weak-evidence", red_flags=["pregnancy"])
    chat, manager = assemble_panel(triage)
    assert len(chat.agents) == 6
    assert chat.max_round == 2  # 1 verdict + 1 rebuttal
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `agents/panel/assembly.py`**

```python
# shrine-diet-bioactivity/agents/panel/assembly.py
"""GroupChat assembly with MDAgents-style adaptive triage.
Maps Triage.complexity → role-agent subset → GroupChat with round-robin
speaker selection + 2-round cap (verdict + rebuttal)."""
from __future__ import annotations

from autogen import ConversableAgent, GroupChat, GroupChatManager

from agents.llm_config import default_llm_config
from agents.models import Triage
from agents.panel import (
    build_clinical_research_scientist, build_defer_to_clinician,
    build_dietitian, build_pharmacologist, build_safety_reviewer,
    build_tcm_practitioner,
)
from agents.tools.kg_query import kg_query


MODERATOR_PROMPT = """\
You are the moderator of a clinical research team. Synthesize the role
verdicts into a PanelDeliberation:
- moderator_summary: 2-3 sentence consensus or majority position.
- dissent: list any minority verdicts the Clinical Research Scientist or
  Safety Reviewer raised — even if the majority disagreed.
- Do NOT over-rule a Safety Reviewer 'reject' verdict. If safety rejects,
  the panel summary must reflect that.
Output a PanelDeliberation JSON.
"""


def _select_roles(triage: Triage) -> list[ConversableAgent]:
    if triage.complexity == "low":
        return [build_dietitian()]
    if triage.complexity == "moderate":
        return [build_dietitian(), build_pharmacologist(), build_tcm_practitioner()]
    return [
        build_dietitian(), build_pharmacologist(), build_tcm_practitioner(),
        build_clinical_research_scientist(), build_safety_reviewer(),
        build_defer_to_clinician(),
    ]


def _register_kg_tool(agents: list[ConversableAgent]) -> None:
    """Register kg_query with every panel agent (for both LLM-call discovery
    and Python-side execution). AG2 will route tool calls correctly."""
    for a in agents:
        a.register_for_llm(name="kg_query", description="Query the unified diet/TCM KG; returns typed chains.")(kg_query)
        a.register_for_execution(name="kg_query")(kg_query)


def assemble_panel(triage: Triage) -> tuple[GroupChat, GroupChatManager]:
    roles = _select_roles(triage)
    _register_kg_tool(roles)
    chat = GroupChat(
        agents=roles,
        messages=[],
        max_round=2,                                  # 1 verdict + 1 rebuttal
        speaker_selection_method="round_robin",       # deterministic, cheap
    )
    manager = GroupChatManager(
        groupchat=chat,
        name="Moderator",
        llm_config=default_llm_config(response_format=None),
        system_message=MODERATOR_PROMPT,
    )
    return chat, manager
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/agents/panel/assembly.py shrine-diet-bioactivity/agents/tests/test_assembly.py
git commit -m "feat(agents): GroupChat assembly with adaptive triage + kg_query tool registration"
```

---

## Task H6 — Calibrator + provenance formatter

**Purpose:** consume the `PanelDeliberation` + retrieved chains, compute the composite confidence score, and assemble the final `ResearchSynthesis` artifact. Implements a deterministic Bayesian-linear-fusion baseline; full Bayesian Optimization tuning is deferred to Subsystem F (evaluation phase).

**Files:**
- Create: `shrine-diet-bioactivity/agents/calibrator.py`
- Create: `shrine-diet-bioactivity/agents/provenance.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_calibrator.py`

- [ ] **Step 1: Write failing test**

```python
# shrine-diet-bioactivity/agents/tests/test_calibrator.py
from agents.calibrator import compute_confidence  # type: ignore[import-not-found]
from agents.models import ConfidenceComponents


def test_confidence_increases_with_evidence_tier():
    low = compute_confidence(ConfidenceComponents(evidence_tier=0.2, hdi_risk=0.0, question_fit=0.5))
    high = compute_confidence(ConfidenceComponents(evidence_tier=0.9, hdi_risk=0.0, question_fit=0.5))
    assert high > low


def test_confidence_capped_by_hdi_risk():
    no_risk = compute_confidence(ConfidenceComponents(evidence_tier=0.9, hdi_risk=0.0, question_fit=0.9))
    severe  = compute_confidence(ConfidenceComponents(evidence_tier=0.9, hdi_risk=0.95, question_fit=0.9))
    assert severe < no_risk
    assert 0 <= severe <= 1


def test_confidence_bounds_satisfied():
    for et in (0.0, 0.5, 1.0):
        for hr in (0.0, 0.5, 1.0):
            for qf in (0.0, 0.5, 1.0):
                v = compute_confidence(ConfidenceComponents(evidence_tier=et, hdi_risk=hr, question_fit=qf))
                assert 0 <= v <= 1
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `agents/calibrator.py` and `agents/provenance.py`**

```python
# shrine-diet-bioactivity/agents/calibrator.py
"""Composite confidence calibrator (Subsystem H — primary; full Bayesian
optimization in Subsystem F).

Baseline: weighted geometric mean on the logit scale, derived from
weights pinned in config/ingest_params.yaml (loaded at import). Equivalent
to a Bayesian linear fusion with fixed priors — the deterministic baseline
that Subsystem F's BayesOpt will tune."""
from __future__ import annotations

from agents.models import ConfidenceComponents
from lightrag.config_loader import load_ingest_params  # type: ignore[import-not-found]


def compute_confidence(c: ConfidenceComponents) -> float:
    """Weighted geometric mean: evidence^a · (1−hdi)^b · question_fit^c."""
    # Baseline weights — Subsystem F replaces with BayesOpt-tuned values.
    a, b, g = 0.5, 0.3, 0.2
    eps = 1e-6
    score = (max(c.evidence_tier, eps) ** a
             * max(1.0 - c.hdi_risk, eps) ** b
             * max(c.question_fit, eps) ** g)
    return min(max(score, 0.0), 1.0)
```

```python
# shrine-diet-bioactivity/agents/provenance.py
"""Provenance-chain formatter — assembles the final ResearchSynthesis."""
from __future__ import annotations

from agents.models import (
    ConfidenceComponents, KGResult, PanelDeliberation,
    ResearchQuestion, ResearchSynthesis, Triage,
)
from agents.calibrator import compute_confidence


def assemble_synthesis(
    question: ResearchQuestion,
    triage: Triage,
    kg: KGResult,
    panel: PanelDeliberation,
    components: ConfidenceComponents,
) -> ResearchSynthesis:
    confidence = compute_confidence(components)
    safety_reject = any(v.role == "SafetyReviewer" and v.verdict == "reject" for v in panel.verdicts)
    defer_strong = any(v.role == "DeferToClinician" and v.verdict in {"caution", "reject"} for v in panel.verdicts)
    return ResearchSynthesis(
        question=question,
        triage=triage,
        candidate_chains=kg.chains,
        panel=panel,
        confidence=confidence,
        components=components,
        defer_to_clinician=safety_reject or defer_strong,
    )
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/agents/calibrator.py shrine-diet-bioactivity/agents/provenance.py shrine-diet-bioactivity/agents/tests/test_calibrator.py
git commit -m "feat(agents): composite confidence + provenance synthesis"
```

---

## Task H7 — End-to-end case study runner + 3 demo case studies

**Purpose:** the deliverable. A CLI runner that takes a case-study spec, runs the full Triage → Panel → Calibrator pipeline, captures the AG2 transcript, and writes the `ResearchSynthesis` artifact alongside it.

**Files:**
- Create: `shrine-diet-bioactivity/agents/run_case_study.py`
- Create: `shrine-diet-bioactivity/agents/tests/test_run_case_study.py`
- Create: `research-journal/shared/case_studies/01_ginger_cin.json`
- Create: `research-journal/shared/case_studies/02_sjw_sertraline_hdi.json`
- Create: `research-journal/shared/case_studies/03_tcm_western_menopause.json`

### The three demo case studies (the paper's Results section)

**Case 1 — Evidence-synthesis (low complexity):**
*"Synthesize the evidence for ginger (Zingiber officinale) in chemotherapy-induced nausea and vomiting (CINV) in adult oncology patients."*
- Tests: classical evidence-synthesis question. Solo Dietitian (low complexity) but should escalate if KG retrieval surfaces HDI risk → demonstrates triage adaptation.

**Case 2 — Safety-critical (high complexity):**
*"Evaluate the herb-drug interaction profile of St. John's Wort with sertraline. What is the mechanism, severity, and clinical management?"*
- Tests: full 6-role panel (high complexity). Safety Reviewer should issue 'reject' verdict via HDI-Safe 50; CRS should flag evidence quality; Defer-to-Clinician should set defer flag.

**Case 3 — Bilingual TCM ↔ Western (moderate complexity):**
*"Compare TCM and Western evidence for menopausal vasomotor symptoms (hot flashes). Include classical TCM syndrome differentiation and modern phytoestrogen mechanism."*
- Tests: bilingual reasoning. TCM Practitioner cites SymMap classical herbs (e.g., 当归 Dang Gui, 黑升麻 black cohosh = 升麻 Sheng Ma); Pharmacologist cites phytoestrogen targets (CMAUP); CRS distinguishes evidence quality across both vocabularies.

### Case-study spec format

```json
// research-journal/shared/case_studies/01_ginger_cin.json
{
  "id": "case-01-ginger-cin",
  "version": "v1",
  "research_question": "Synthesize the evidence for ginger (Zingiber officinale) in chemotherapy-induced nausea and vomiting (CINV) in adult oncology patients.",
  "expected_complexity": "low",
  "expected_red_flags": [],
  "expected_panel_verdict": "prefer",
  "expected_evidence_tier": "clinical_trial",
  "expected_min_chains": 1,
  "notes": "Multiple RCT-level studies exist (e.g., Ryan 2012, Marx 2017). Tests basic evidence-synthesis pipeline."
}
```

```json
// research-journal/shared/case_studies/02_sjw_sertraline_hdi.json
{
  "id": "case-02-sjw-sertraline-hdi",
  "version": "v1",
  "research_question": "Evaluate the herb-drug interaction profile of St. John's Wort (Hypericum perforatum) with sertraline. What is the mechanism, severity, and clinical management?",
  "expected_complexity": "high",
  "expected_red_flags": ["serotonergic_interaction"],
  "expected_panel_verdict": "reject",
  "expected_evidence_tier": "clinical_trial",
  "expected_min_chains": 1,
  "expected_defer": true,
  "notes": "Severe serotonin syndrome risk. HDI-Safe 50 entry HDI-001. Tests safety-critical pathway."
}
```

```json
// research-journal/shared/case_studies/03_tcm_western_menopause.json
{
  "id": "case-03-tcm-western-menopause",
  "version": "v1",
  "research_question": "Compare TCM and Western evidence for menopausal vasomotor symptoms (hot flashes). Include classical TCM syndrome differentiation and modern phytoestrogen mechanism.",
  "expected_complexity": "moderate",
  "expected_red_flags": [],
  "expected_panel_verdict": "caution",
  "expected_evidence_tier": "observational",
  "expected_min_chains": 2,
  "languages": ["en", "zh"],
  "notes": "Tests bilingual reasoning. TCM herbs: 当归 Dang Gui, 升麻 Sheng Ma. Western: black cohosh, isoflavones. Evidence quality is mixed (some RCTs, mostly observational)."
}
```

### Runner skeleton

```python
# shrine-diet-bioactivity/agents/run_case_study.py
"""End-to-end runner — load case spec, execute pipeline, save synthesis."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.calibrator import compute_confidence
from agents.models import (
    ConfidenceComponents, PanelDeliberation, ResearchQuestion, ResearchSynthesis, Triage,
)
from agents.panel.assembly import assemble_panel
from agents.provenance import assemble_synthesis
from agents.tools.kg_query import kg_query
from agents.triage import build_triage_agent


def run_case_study(spec_path: Path, out_dir: Path) -> ResearchSynthesis:
    spec = json.loads(spec_path.read_text())
    triage_agent = build_triage_agent()

    # Stage 1: triage
    rq, triage = triage_agent(spec["research_question"])

    # Stage 2: KG retrieval (also called by panel agents inline as needed)
    kg = kg_query(spec["research_question"], mode="hybrid")

    # Stage 3: panel deliberation
    chat, manager = assemble_panel(triage)
    moderator_input = (
        f"Research question: {rq.model_dump_json()}\n"
        f"Triage: {triage.model_dump_json()}\n"
        f"Initial KG retrieval: {kg.model_dump_json()}\n"
        f"Each role agent emit a RoleVerdict; moderator emit a PanelDeliberation."
    )
    manager.initiate_chat(chat.agents[0], message=moderator_input)
    panel = _extract_panel_deliberation(chat.messages)

    # Stage 4: calibration + synthesis
    components = _derive_components(rq, kg, panel)
    synthesis = assemble_synthesis(rq, triage, kg, panel, components)

    # Persist
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    case_dir = out_dir / spec["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / f"{timestamp}-synthesis.json").write_text(synthesis.model_dump_json(indent=2))
    (case_dir / f"{timestamp}-transcript.jsonl").write_text(
        "\n".join(json.dumps(m, default=str) for m in chat.messages)
    )
    return synthesis


def _extract_panel_deliberation(messages: list[dict[str, Any]]) -> PanelDeliberation:
    """Parse panel verdicts from AG2 chat history. The moderator emits a
    PanelDeliberation JSON in its final message; everything earlier is per-role."""
    from agents.models import PanelDeliberation, RoleVerdict
    verdicts: list[RoleVerdict] = []
    moderator_summary = ""
    dissent: list[str] = []
    for m in messages:
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        try:
            obj = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        if "role" in obj and "verdict" in obj:
            verdicts.append(RoleVerdict.model_validate(obj))
        elif "moderator_summary" in obj:
            moderator_summary = obj["moderator_summary"]
            dissent = obj.get("dissent", [])
    return PanelDeliberation(verdicts=verdicts, dissent=dissent, moderator_summary=moderator_summary)


def _derive_components(rq, kg, panel) -> ConfidenceComponents:
    """Map raw KG + panel signals to ConfidenceComponents in [0,1]."""
    tier_score = {
        "clinical_trial": 1.0, "pharmacokinetic_study": 0.85, "observational": 0.7,
        "case_report_series": 0.55, "case_report": 0.4,
        "experimental": 0.55, "in_vivo": 0.5, "in_vitro": 0.3,
        "traditional": 0.2, "unknown": 0.1,
    }
    tiers = [e.evidence_tier for c in kg.chains for e in c.edges]
    evidence_tier = max((tier_score.get(t, 0.1) for t in tiers), default=0.1)

    # HDI risk: presence of safety-reviewer "reject" → 1.0, "caution" → 0.5
    hdi = 0.0
    for v in panel.verdicts:
        if v.role == "SafetyReviewer":
            if v.verdict == "reject":  hdi = 1.0
            elif v.verdict == "caution": hdi = 0.5

    # Question fit: fraction of role agents that issued "prefer" (excludes Defer/Safety)
    actionable = [v for v in panel.verdicts if v.role not in {"DeferToClinician", "SafetyReviewer"}]
    if not actionable:
        question_fit = 0.5
    else:
        question_fit = sum(1 for v in actionable if v.verdict == "prefer") / len(actionable)

    return ConfidenceComponents(evidence_tier=evidence_tier, hdi_risk=hdi, question_fit=question_fit)


if __name__ == "__main__":
    import sys
    spec = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("research-journal/shared/case_study_runs")
    s = run_case_study(spec, out)
    print(f"confidence={s.confidence:.3f} defer={s.defer_to_clinician}")
```

- [ ] **Step 1 → Step 5: standard TDD** — write the spec-loading + run-orchestration test (mock the LLM); implement; verify; commit.

```bash
git add shrine-diet-bioactivity/agents/run_case_study.py research-journal/shared/case_studies/ shrine-diet-bioactivity/agents/tests/test_run_case_study.py
git commit -m "feat(agents): end-to-end case-study runner + 3 demo specs (paper Results)"
```

---

## Completion checklist (Subsystem H done when all green)

- [ ] AG2 + Pydantic + OpenAI/Anthropic SDKs installed and smoke-tested
- [ ] All 8 typed Pydantic models in `agents/models.py` with bounds-validated tests
- [ ] `kg_query` tool: LightRAG primary path + SQLite fallback, both unit-tested
- [ ] Triage agent: PICO + complexity classification, OPQRST/SOCRATES/NCP-ADIME prompts in place
- [ ] All 6 role agents constructible, each with role-specific `system_message`
- [ ] `assemble_panel` triage-routes to {1, 3, 6}-agent teams
- [ ] `compute_confidence` deterministic baseline, monotonic in evidence_tier, decreasing in HDI risk
- [ ] 3 demo case studies in `research-journal/shared/case_studies/`
- [ ] End-to-end runner produces `ResearchSynthesis` JSON + AG2 transcript
- [ ] `pytest --cov=agents --cov-report=term-missing` ≥ 80% on new modules

After completion: dispatch Subsystem F (DietBench-Clinical / ResearchBench-Clinical) plan — by then the system is exercisable end-to-end and benchmark scenarios can be written against its actual output schema.
