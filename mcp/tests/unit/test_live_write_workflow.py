"""#116: the #113 live write-integrity suite runs in CI against a throwaway Neo4j
service container, and can never go green without actually running.

Structure-level checks on .github/workflows/lightrag-live-write.yml. The live
behaviour (RED on a known mutation) is proven by running the suite, not here.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/lightrag-live-write.yml"


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _on(wf: dict) -> dict:
    # PyYAML parses the bare key `on` as boolean True.
    return wf.get("on", wf.get(True))


def _job(wf: dict) -> dict:
    jobs = wf["jobs"]
    assert len(jobs) == 1
    return next(iter(jobs.values()))


def test_runs_on_prs_touching_the_write_path(wf) -> None:
    paths = _on(wf)["pull_request"]["paths"]
    assert "shrine-diet-bioactivity/lightrag/**" in paths
    assert ".github/workflows/lightrag-live-write.yml" in paths


def test_uses_a_loopback_neo4j_service_container_never_aura(wf) -> None:
    job = _job(wf)
    neo = job["services"]["neo4j"]
    assert neo["image"] == "neo4j:5.26-community"
    assert any(p.startswith("127.0.0.1:") and p.endswith(":7687") for p in neo["ports"])
    assert '["apoc"]' in neo["env"]["NEO4J_PLUGINS"]
    text = WORKFLOW.read_text()
    # No Aura credential may ever reach this job.
    assert "secrets.NEO4J" not in text and "databases.neo4j.io" not in text


def test_sets_the_uri_unconditionally_so_the_suite_cannot_skip(wf) -> None:
    env = _job(wf)["env"]
    assert env["SCOPED_WRITE_TEST_NEO4J_URI"].startswith("bolt://127.0.0.1:")
    assert env["SCOPED_WRITE_TEST_NEO4J_PASSWORD"]


def test_waits_for_bolt_and_fails_if_the_container_never_comes_up(wf) -> None:
    runs = "\n".join(s.get("run", "") for s in _job(wf)["steps"])
    assert "RETURN 1" in runs
    assert "exit 1" in runs


def test_runs_the_make_target_and_refuses_a_green_without_passes(wf) -> None:
    steps = _job(wf)["steps"]
    run = next(s["run"] for s in steps if "lightrag-test-scope-write-live" in s.get("run", ""))
    # Exit status must survive the tee (a pipe reports the LAST command's status).
    assert "pipefail" in run
    # Green requires real passes and no skips: a skipped module exits 0.
    assert "passed" in run and "skipped" in run and "no tests ran" in run


def _suite_step(wf: dict) -> dict:
    return next(s for s in _job(wf)["steps"] if "lightrag-test-scope-write-live" in s.get("run", ""))


def test_nothing_can_turn_a_red_suite_green(wf) -> None:
    job = _job(wf)
    assert "continue-on-error" not in job and "if" not in job
    for step in job["steps"]:
        assert "continue-on-error" not in step, step.get("name")
        assert "if" not in step, step.get("name")


def test_the_checks_judge_the_make_output_in_order(wf) -> None:
    run = _suite_step(wf)["run"]
    i_make = run.index("make lightrag-test-scope-write-live")
    i_passed = run.index("passed=")
    i_hide = run.index("xfail|xpass|deselected")
    i_min = run.index("MIN_LIVE_PASSED")
    assert i_make < i_passed < i_hide < i_min


def test_partial_hiding_and_dropped_tests_are_red(wf) -> None:
    run = _suite_step(wf)["run"]
    for word in ("skipped", "no tests ran", "xfail", "xpass", "deselected"):
        assert word in run, word
    assert int(_suite_step(wf)["env"]["MIN_LIVE_PASSED"]) >= 14


def test_triggers_cover_the_makefile_push_schedule_and_its_own_pin(wf) -> None:
    on = _on(wf)
    for trig in ("pull_request", "push"):
        assert "shrine-diet-bioactivity/Makefile" in on[trig]["paths"], trig
    assert on["schedule"]
    mcp_ci = yaml.safe_load((REPO_ROOT / ".github/workflows/mcp-ci.yml").read_text())
    mcp_on = mcp_ci.get("on", mcp_ci.get(True))
    assert ".github/workflows/lightrag-live-write.yml" in mcp_on["pull_request"]["paths"]


def test_the_test_db_password_matches_the_container_auth(wf) -> None:
    job = _job(wf)
    auth = job["services"]["neo4j"]["env"]["NEO4J_AUTH"]
    assert auth == f"neo4j/{job['env']['SCOPED_WRITE_TEST_NEO4J_PASSWORD']}"
