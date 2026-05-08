"""Disease canonicalization helpers (Phase 3 / spec §4.2).

Pure logic — no DB. Parsers and slug rules used by the canonicalization
orchestrator and the modified CTD loader.

Vocabulary:
  - "canonical id" = a stable string ``<prefix>:<value>`` keying every disease
    entity. Prefix priority: mesh > umls > icd10cm > local-slug fallback.
  - "alias" = any free-text disease name observed in any source, joined back
    to its canonical id via the ``disease_name_aliases`` table.
"""

from __future__ import annotations

import re
from typing import Optional

# Prefix → canonical-prefix map. Order matters only insofar as it documents
# what we accept; the priority chain in canonical_id() is independent.
_PREFIX_MAP = {
    "MESH": "mesh",
    "OMIM": "omim",
    "DOID": "doid",
    "UMLS": "umls",
    "ICD10CM": "icd10cm",
    "HPO": "hpo",
}


def parse_disease_id(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Parse ``PREFIX:VALUE``-style external disease IDs.

    Returns ``(lowercase_prefix, value)`` for known prefixes (MESH, UMLS,
    ICD10CM, OMIM, DOID, HPO), otherwise ``(None, None)``. Bare strings,
    empty inputs, and unknown prefixes all fall through to ``(None, None)``.
    """
    if not raw:
        return (None, None)
    if ":" not in raw:
        return (None, None)
    prefix, _, value = raw.partition(":")
    canonical_prefix = _PREFIX_MAP.get(prefix.strip().upper())
    if canonical_prefix is None:
        return (None, None)
    value = value.strip()
    if not value:
        return (None, None)
    return (canonical_prefix, value)


def canonical_id(
    *,
    mesh: Optional[str] = None,
    umls: Optional[str] = None,
    icd10: Optional[str] = None,
    preferred_name: Optional[str] = None,
) -> str:
    """Compute the canonical disease id per spec §4.2 priority order.

    Priority: mesh > umls > icd10cm > local-slug fallback.

    Raises ``ValueError`` if all four are None — there's no anchor to build
    a stable id from. Callers are expected to filter out empty rows upstream.
    """
    if mesh:
        return f"mesh:{mesh}"
    if umls:
        return f"umls:{umls}"
    if icd10:
        return f"icd10cm:{icd10}"
    if preferred_name:
        return f"local:{slugify_disease_name(preferred_name)}"
    raise ValueError(
        "canonical_id requires at least one of mesh/umls/icd10/preferred_name"
    )


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify_disease_name(name: str) -> str:
    """Lowercase, collapse non-alphanumerics into single dashes, strip edges.

    Used for the ``local:<slug>`` fallback when no formal ID is available.
    Deterministic: re-running on the same input always produces the same slug.
    """
    s = (name or "").lower().strip()
    s = _NON_ALNUM.sub("-", s)
    return s.strip("-")
