"""#125: the TS CI job spent ~1h45m re-downloading HERB 2.0 on every run.

MEASURED 2026-10-12: main went 9 days without CI (10-03 -> 10-12), GitHub evicted
its fixtures cache (caches unread for 7 days are removed), and PR caches are
per-PR, so every run went cold until one main run rebuilt the cache. A warm run
then took ~40 s.

These tests pin the fix in .github/workflows/ci.yml:
  * a schedule on main keeps the cache read inside the 7-day eviction window;
  * the restore result is classified hit / downloads / miss, shown in the step
    summary, and gates the steps (a downloads-only match skips the downloads);
  * the external HERB download has a timeout.
"""
from __future__ import annotations

import itertools
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
CI = REPO_ROOT / ".github/workflows/ci.yml"

DOWNLOAD_STEPS = [
    "Download Duke source data",
    "Download CMAUP source data",
    "Download TTD source data",
    "Download SymMap xlsx files",
    "Download HERB 2.0 via chedi API",
]
BUILD_STEPS = [
    "Decompress Duke + FooDB archives",
    "Build unified SQLite (Duke + FooDB)",
    "KG expansion migration (symptoms, targets)",
    "Multi-source migration (CMAUP + CTD + TTD)",
    "Load SymMap (5 bilingual reference tables)",
    "Load HERB 2.0 (herbs + herb_disease evidence)",
    "Save full fixtures cache",
]


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(CI.read_text())


def _steps(wf) -> dict[str, dict]:
    return {s.get("name", ""): s for s in wf["jobs"]["test"]["steps"]}


def _on(wf):
    return wf.get("on", wf.get(True))


def test_a_schedule_reads_the_cache_inside_the_7_day_eviction_window(wf) -> None:
    crons = [c["cron"] for c in _on(wf)["schedule"]]
    assert crons
    days: list[int] = []
    for c in crons:
        dom, dow = c.split()[2], c.split()[4]
        if dom == "*" and dow == "*":
            return  # daily
        assert dom == "*", c
        days += [int(d) for d in dow.split(",")]
    days = sorted(set(days))
    gaps = [(b - a) for a, b in itertools.pairwise(days)] + [days[0] + 7 - days[-1]]
    assert max(gaps) < 7, f"longest gap between scheduled runs is {max(gaps)} days"


def _classify(step: dict, *, hit: str, matched: str, tmp_path: Path) -> tuple[str, str]:
    dl_key = "data-fixtures-v1-downloads-abc123"
    out, summary = tmp_path / "out", tmp_path / "summary"
    out.write_text("")
    summary.write_text("")
    env = {
        "PATH": "/usr/bin:/bin",
        "HIT": hit,
        "MATCHED": matched,
        "DL_KEY": dl_key,
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    r = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return out.read_text(), summary.read_text()


@pytest.mark.parametrize(
    "hit,matched,state",
    [
        ("true", "data-fixtures-v1-full", "hit"),
        ("false", "data-fixtures-v1-downloads-abc123", "downloads"),
        # An older FULL cache: its downloads may be stale -> re-download.
        ("false", "data-fixtures-v1-oldhash", "miss"),
        ("false", "", "miss"),
        ("", "", "miss"),
    ],
)
def test_classifier_names_the_cache_state_and_reports_it(wf, tmp_path, hit, matched, state) -> None:
    step = _steps(wf)["Classify fixtures cache (HIT / DOWNLOADS / MISS)"]
    out, summary = _classify(step, hit=hit, matched=matched, tmp_path=tmp_path)
    assert out.strip() == f"state={state}"
    assert f"Data fixtures cache: {state.upper()}" in summary


def test_classifier_compares_against_the_same_downloads_key_that_is_saved(wf) -> None:
    steps = _steps(wf)
    dl_key = steps["Classify fixtures cache (HIT / DOWNLOADS / MISS)"]["env"]["DL_KEY"]
    assert steps["Save downloads cache"]["with"]["key"] == dl_key
    assert dl_key in steps["Restore data fixtures cache"]["with"]["restore-keys"]
    # And the full key restored is the full key saved.
    assert steps["Restore data fixtures cache"]["with"]["key"] == steps["Save full fixtures cache"]["with"]["key"]


def test_downloads_run_only_on_a_miss_and_builds_on_anything_but_a_hit(wf) -> None:
    steps = _steps(wf)
    for name in DOWNLOAD_STEPS + ["Save downloads cache"]:
        assert steps[name]["if"] == "steps.fixtures.outputs.state == 'miss'", name
    for name in BUILD_STEPS:
        assert steps[name]["if"] == "steps.fixtures.outputs.state != 'hit'", name


def test_nothing_gates_on_the_raw_cache_hit_flag_any_more(wf) -> None:
    # The raw flag is false on a downloads-only match, which re-ran every download.
    for s in wf["jobs"]["test"]["steps"]:
        assert "cache-hit" not in str(s.get("if", "")), s.get("name")


def test_the_external_herb_download_has_a_timeout(wf) -> None:
    t = _steps(wf)["Download HERB 2.0 via chedi API"].get("timeout-minutes")
    assert t is not None and 0 < t <= 180


def test_verification_steps_are_never_skipped_by_the_cache(wf) -> None:
    steps = _steps(wf)
    for name in ("Typecheck", "Test with coverage"):
        assert "if" not in steps[name], name
