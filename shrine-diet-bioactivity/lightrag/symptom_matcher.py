"""Symptom → disease/SymMap matcher (audit §4.2 spec).

Pure logic — no DB. Callers feed lists of dicts that mirror the live
SymMap table shape; the matcher returns a single best ``MatchResult`` per
query symptom (or ``None`` if nothing matches at any tier).

Four-tier strategy, applied in order (first hit wins):

  Tier 1 — case-insensitive exact match against ``symmap_modern.name``
           or ``symmap_tcm.name_en``. Score 1.0. Carries MeSH/UMLS/ICD-10/HPO.

  Tier 2 — token-Jaccard ≥ 0.5 against the same tables. Score = jaccard.
           Tied scores broken by tier-1-source preference (modern > tcm).

  Tier 3 — substring containment: query contained in SymMap name OR
           SymMap name contained in query. Score = 0.5–0.8 based on
           length ratio (longer overlap = higher score). When several
           rows match, prefer the one with the highest token overlap
           with the query (so "Heart Disease" picks "Acute Heart Disease"
           over "Acute Disease" — both substring-match but the former
           shares more meaningful tokens).

  Tier 4 — fallback to ``target_diseases.disease_name`` substring search.
           No formal IDs. Score 0.3 — clearly weaker than SymMap matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class MatchResult:
    """Single best disease/concept mapping for a symptom query."""

    disease_name: str  # canonical name from SymMap or target_diseases
    source: str  # 'symmap_modern' | 'symmap_tcm' | 'string_match'
    symmap_id: Optional[str]
    mesh_id: Optional[str]
    umls_id: Optional[str]
    icd10cm_id: Optional[str]
    match_score: float  # in [0.0, 1.0]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# Tokens that carry too little signal to anchor a match on their own.
# E.g. "low libido" → head token 'low' is generic; want to match on 'libido'.
_STOPWORDS = frozenset(
    {
        "low",
        "high",
        "poor",
        "good",
        "bad",
        "the",
        "of",
        "a",
        "an",
        "and",
        "or",
        "with",
        "without",
    }
)


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).replace("-", " ").split() if t}


def _content_tokens(s: str) -> set[str]:
    """Tokens minus stopwords — the semantically informative slice."""
    return _tokens(s) - _STOPWORDS


def token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity over normalized whitespace-split tokens."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _modern_to_match(row: dict, score: float, source: str) -> MatchResult:
    return MatchResult(
        disease_name=row.get("name") or "",
        source=source,
        symmap_id=row.get("symmap_id"),
        mesh_id=row.get("mesh_id"),
        umls_id=row.get("umls_id"),
        icd10cm_id=row.get("icd10cm_id"),
        match_score=score,
    )


def _tcm_to_match(row: dict, score: float) -> MatchResult:
    # TCM rows lack MeSH; carry symmap_id + UMLS where present.
    return MatchResult(
        disease_name=row.get("name_en") or "",
        source="symmap_tcm",
        symmap_id=row.get("symmap_id"),
        mesh_id=None,
        umls_id=row.get("umls_id"),
        icd10cm_id=None,
        match_score=score,
    )


def _string_match_to_match(disease: str, score: float) -> MatchResult:
    return MatchResult(
        disease_name=disease,
        source="string_match",
        symmap_id=None,
        mesh_id=None,
        umls_id=None,
        icd10cm_id=None,
        match_score=score,
    )


def match_symptom(
    symptom: str,
    *,
    modern: Iterable[dict],
    tcm: Iterable[dict],
    diseases: Iterable[str],
    jaccard_threshold: float = 0.5,
) -> Optional[MatchResult]:
    """Return the best disease/concept mapping for ``symptom``, or None.

    Tries four tiers in order; first non-None wins.
    """
    q = _norm(symptom)
    if not q:
        return None
    q_tokens = _tokens(q)

    modern_list = list(modern)
    tcm_list = list(tcm)

    # ---- Tier 1: case-insensitive exact ----
    for row in modern_list:
        if _norm(row.get("name", "")) == q:
            return _modern_to_match(row, 1.0, "symmap_modern")
    for row in tcm_list:
        if _norm(row.get("name_en", "")) == q:
            return _tcm_to_match(row, 1.0)

    # ---- Tier 2: token Jaccard (≥ threshold) ----
    # Tie-breaker (score, has_mesh_id) — when two rows have equal Jaccard,
    # prefer the row whose mesh_id is non-NULL (downstream-joinable).
    best_jaccard: tuple[tuple, dict, str] | None = None
    for row in modern_list:
        sc = token_jaccard(q, row.get("name", ""))
        if sc >= jaccard_threshold:
            has_mesh = 1 if row.get("mesh_id") else 0
            sort_key = (sc, has_mesh)
            if best_jaccard is None or sort_key > best_jaccard[0]:
                best_jaccard = (sort_key, row, "symmap_modern")
    for row in tcm_list:
        sc = token_jaccard(q, row.get("name_en", ""))
        if sc >= jaccard_threshold:
            sort_key = (sc, 0)  # TCM has no mesh
            if best_jaccard is None or sort_key > best_jaccard[0]:
                best_jaccard = (sort_key, row, "symmap_tcm")
    if best_jaccard is not None:
        sort_key, row, source = best_jaccard
        score = sort_key[0]
        if source == "symmap_modern":
            return _modern_to_match(row, score, source)
        return _tcm_to_match(row, score)

    # ---- Tier 3: substring containment ----
    # Score = 0.5 + 0.3 * (token-overlap fraction). Pick the row with the
    # most shared tokens to break ties. Range 0.5..0.8 — strictly less
    # than 1.0 so callers can rank tier-1 matches above tier-3.
    #
    # Tie-breaker key: (score, shared_tokens, has_mesh_id). The has_mesh_id
    # bit means that when multiple rows substring-match with identical token
    # overlap (e.g. "Hypertension" matches both "Essential Hypertension"
    # MeSH=C562386 AND "Rebound Hypertension" MeSH=NULL), we prefer the row
    # with downstream-joinable formal IDs.
    best_substring: tuple[tuple, dict, str] | None = None
    for row in modern_list:
        name = row.get("name", "")
        n = _norm(name)
        if not n:
            continue
        if q in n or n in q:
            shared = len(q_tokens & _tokens(name))
            denom = max(len(q_tokens), 1)
            score = 0.5 + 0.3 * (shared / denom)
            score = min(score, 0.8)
            has_mesh = 1 if row.get("mesh_id") else 0
            sort_key = (score, shared, has_mesh)
            if best_substring is None or sort_key > best_substring[0]:
                best_substring = (sort_key, row, "symmap_modern")
    for row in tcm_list:
        name = row.get("name_en", "")
        n = _norm(name)
        if not n:
            continue
        if q in n or n in q:
            shared = len(q_tokens & _tokens(name))
            denom = max(len(q_tokens), 1)
            score = 0.5 + 0.3 * (shared / denom)
            score = min(score, 0.8)
            # TCM has no mesh_id, weight has_mesh=0.
            sort_key = (score, shared, 0)
            if best_substring is None or sort_key > best_substring[0]:
                best_substring = (sort_key, row, "symmap_tcm")
    if best_substring is not None:
        sort_key, row, source = best_substring
        score = sort_key[0]
        if source == "symmap_modern":
            return _modern_to_match(row, score, source)
        return _tcm_to_match(row, score)

    # ---- Tier 3.5: content-token match against SymMap ----
    # When a symptom's head/content token (e.g. 'memory' from 'Memory decline',
    # 'libido' from 'Low libido') appears in a SymMap name, that's a strong
    # concept signal even if Jaccard is low. Score 0.4 — lower than substring
    # but still anchored to formal MeSH/UMLS IDs.
    q_content = _content_tokens(q)
    if q_content:
        best_token: tuple[int, dict, str] | None = None
        for row in modern_list:
            row_content = _content_tokens(row.get("name", ""))
            shared = len(q_content & row_content)
            if shared > 0 and (best_token is None or shared > best_token[0]):
                best_token = (shared, row, "symmap_modern")
        for row in tcm_list:
            row_content = _content_tokens(row.get("name_en", ""))
            shared = len(q_content & row_content)
            if shared > 0 and (best_token is None or shared > best_token[0]):
                best_token = (shared, row, "symmap_tcm")
        if best_token is not None:
            shared, row, source = best_token
            score = 0.4
            if source == "symmap_modern":
                return _modern_to_match(row, score, source)
            return _tcm_to_match(row, score)

    # ---- Tier 4: fallback to target_diseases substring ----
    for disease in diseases:
        n = _norm(disease)
        if not n:
            continue
        if q in n or n in q:
            return _string_match_to_match(disease, 0.3)

    return None
