"""Integration test: snapshot generator writes all required sections."""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.aura]


@pytest.mark.integration
def test_snapshot_has_required_sections(tmp_path: Path) -> None:
    from generate_snapshot import generate

    out = tmp_path / "snapshot.md"
    generate(out)
    text = out.read_text()
    for section in (
        "# KG Ingestion Snapshot",
        "## Node counts by type",
        "## Edge counts by type",
        "## Source distribution",
        "## Bilingual coverage",
        "## HDI-Safe 50 coverage",
    ):
        assert section in text, f"missing section: {section}"
